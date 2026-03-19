from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import json
from dataclasses import dataclass
from urllib.parse import urlencode
from typing import Any, AsyncIterator
import weakref

import httpx
import websockets


@dataclass
class SttTranscript:
    text: str
    confidence: float
    is_final: bool
    source: str


class BaseSttClient:
    provider_name = "base"

    async def start_session(self, session_id: str) -> None:
        return None

    async def end_session(self, session_id: str) -> None:
        return None

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        raise NotImplementedError

    async def trigger_finalization(self) -> None:
        return None


class BaseLlmClient:
    provider_name = "base"

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        raise NotImplementedError


class BaseTtsClient:
    provider_name = "base"

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        raise NotImplementedError


async def _iter_sse_json_payloads(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    async for line in response.aiter_lines():
        if not line:
            continue
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if raw == "[DONE]":
            break
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _decode_base64_audio(payload: dict) -> bytes | None:
    audio_b64 = payload.get("audio_base64")
    if not audio_b64:
        return None
    if isinstance(audio_b64, str) and "," in audio_b64 and audio_b64.startswith("data:"):
        audio_b64 = audio_b64.split(",", 1)[1]
    try:
        return base64.b64decode(audio_b64)
    except Exception:
        return None


def _emit_handler(payload: dict, key: str, transcript: str, is_final: bool) -> None:
    handler = payload.get(key)
    if callable(handler):
        try:
            handler(transcript, is_final)
        except Exception:
            return


class _TaskConversationHistoryMixin:
    def __init__(self) -> None:
        # Keyed by session_id so history survives WebSocket reconnects.
        self._history_by_session: dict[str, list[dict[str, str]]] = {}
        self._active_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "llm_active_session_id", default=None
        )

    def set_session(self, session_id: str) -> None:
        """Call once when a WebSocket session binds to this LLM client."""
        self._active_session_id.set(session_id)
        if session_id not in self._history_by_session:
            self._history_by_session[session_id] = []

    def clear_session(self, session_id: str) -> None:
        """Call when a session ends to free memory."""
        self._history_by_session.pop(session_id, None)

    def _history_for_current_task(self) -> list[dict[str, str]]:
        session_id = self._active_session_id.get()
        if not session_id:
            # Fallback: no session context, return empty (won't be stored)
            return []
        if session_id not in self._history_by_session:
            self._history_by_session[session_id] = []
        return self._history_by_session[session_id]

    def _remember_exchange(self, *, user_text: str, assistant_text: str) -> None:
        history = self._history_for_current_task()
        history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        # Keep the last 16 messages (8 exchanges) to bound context size.
        if len(history) > 16:
            del history[:-16]


class MockSttClient(BaseSttClient):
    provider_name = "mock_stt"

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        return SttTranscript(text=hint, confidence=0.98 if hint else 0.0, is_final=bool(hint), source=self.provider_name)


@dataclass
class _DeepgramSessionState:
    ws: Any
    lock: asyncio.Lock
    keepalive_task: asyncio.Task[Any]
    listen_url: str


class DeepgramSttClient(BaseSttClient):
    provider_name = "deepgram"
    KEEPALIVE_INTERVAL_SECONDS = 10.0

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._fallback = MockSttClient()
        self._sessions: dict[str, _DeepgramSessionState] = {}
        self._session_ids: set[str] = set()
        self._active_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "deepgram_active_session_id",
            default=None,
        )

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        if not self.api_key:
            return await self._fallback.finalize_utterance(payload)

        audio_bytes = _decode_base64_audio(payload)
        if not audio_bytes:
            if hint:
                return SttTranscript(text=hint, confidence=0.98, is_final=True, source=self.provider_name)
            return await self._fallback.finalize_utterance(payload)

        try:
            return await self._stream_utterance(payload, audio_bytes, hint)
        except Exception:
            if hint:
                return SttTranscript(text=hint, confidence=0.98, is_final=True, source=self.provider_name)
            return await self._fallback.finalize_utterance(payload)

    async def start_session(self, session_id: str, payload: dict | None = None) -> None:
        if not self.api_key:
            return
        self._session_ids.add(session_id)
        self._active_session_id.set(session_id)
        # Pre-warm the Deepgram WebSocket so the first utterance doesn't pay
        # the WebSocket handshake cost (~150 ms).  Use the default WAV/linear16
        # params that the mobile client always sends.
        default_payload = payload or {
            "codec": "linear16",
            "content_type": "audio/wav",
            "sample_rate": 16000,
            "channels": 1,
            "session_id": session_id,
        }
        with contextlib.suppress(Exception):
            await self._get_or_open_session(session_id, payload=default_payload)

    async def end_session(self, session_id: str) -> None:
        self._session_ids.discard(session_id)
        if self._active_session_id.get() == session_id:
            self._active_session_id.set(None)
        state = self._sessions.pop(session_id, None)
        if state is None:
            return
        state.keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.keepalive_task
        with contextlib.suppress(Exception):
            await state.ws.send(json.dumps({"type": "CloseStream"}))
        with contextlib.suppress(Exception):
            await state.ws.close()

    async def trigger_finalization(self) -> None:
        session_id = self._active_session_id.get()
        if not self.api_key or not session_id:
            return
        state = self._sessions.get(session_id)
        if state is None or getattr(state.ws, "closed", False):
            return
        try:
            async with state.lock:
                await state.ws.send(json.dumps({"type": "Finalize"}))
        except Exception:
            return

    def _listen_url(self, payload: dict) -> str:
        content_type = str(payload.get("content_type") or "").lower()
        codec = str(payload.get("codec") or "").lower()
        ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        params: dict[str, str] = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
            "interim_results": "true",
            "endpointing": "100",
            "utterance_end_ms": "500",
        }
        if codec == "opus" or "opus" in content_type:
            params["encoding"] = "opus"
            params["sample_rate"] = str(int(payload.get("sample_rate") or 16000))
        elif content_type in ("audio/mp4", "audio/webm", "audio/mpeg"):
            params["mimetype"] = content_type
        else:
            params["encoding"] = "linear16"
            params["sample_rate"] = str(int(payload.get("sample_rate") or 16000))
            params["channels"] = str(int(payload.get("channels") or 1))
        return f"{ws_base}/v1/listen?{urlencode(params)}"

    async def _open_session(self, session_id: str, payload: dict) -> _DeepgramSessionState:
        listen_url = self._listen_url(payload)
        ws = await websockets.connect(
            listen_url,
            additional_headers={"Authorization": f"Token {self.api_key}"},
            open_timeout=self.timeout_seconds,
            close_timeout=self.timeout_seconds,
            max_size=4_000_000,
        )
        state = _DeepgramSessionState(
            ws=ws,
            lock=asyncio.Lock(),
            keepalive_task=asyncio.create_task(asyncio.sleep(0)),
            listen_url=listen_url,
        )

        async def keepalive_loop() -> None:
            while True:
                await asyncio.sleep(self.KEEPALIVE_INTERVAL_SECONDS)
                try:
                    async with state.lock:
                        await state.ws.send(json.dumps({"type": "KeepAlive"}))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    break

        state.keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.keepalive_task
        state.keepalive_task = asyncio.create_task(keepalive_loop())
        self._sessions[session_id] = state
        return state

    async def _get_or_open_session(self, session_id: str, *, payload: dict, force_reconnect: bool = False) -> _DeepgramSessionState:
        state = self._sessions.get(session_id)
        desired_listen_url = self._listen_url(payload)
        if state is not None and (force_reconnect or state.listen_url != desired_listen_url):
            await self.end_session(session_id)
            state = None
        if state is not None:
            return state
        return await self._open_session(session_id, payload)

    async def _stream_utterance(self, payload: dict, audio_bytes: bytes, hint: str) -> SttTranscript:
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            raise RuntimeError("deepgram session_id required")
        MAX_RETRIES = 2
        retry_count = 0
        reopened_state: _DeepgramSessionState | None = None

        while True:
            latest_partial = ""
            final_segments: list[str] = []
            confidences: list[float] = []
            state = reopened_state or await self._get_or_open_session(session_id, payload=payload)
            reopened_state = None

            if getattr(state.ws, "closed", False):
                await self.end_session(session_id)
                if retry_count >= MAX_RETRIES:
                    raise RuntimeError("deepgram_connection_closed")
                retry_count += 1
                await asyncio.sleep(min(0.5 * retry_count, 1.0))
                reopened_state = await self._open_session(session_id, payload)
                continue

            async def consume_results() -> None:
                nonlocal latest_partial, final_segments, confidences
                while True:
                    try:
                        raw_message = await asyncio.wait_for(state.ws.recv(), timeout=self.timeout_seconds)
                    except TimeoutError:
                        break

                    if isinstance(raw_message, bytes):
                        continue

                    try:
                        message = json.loads(raw_message)
                    except json.JSONDecodeError:
                        continue

                    message_type = str(message.get("type", ""))
                    if message_type == "Results":
                        channel = (message.get("channel") or {}).get("alternatives") or []
                        alternative = channel[0] if channel else {}
                        transcript = str(alternative.get("transcript", "")).strip()
                        is_final = bool(message.get("is_final") or message.get("speech_final"))
                        if not transcript:
                            if is_final:
                                break
                            continue

                        confidence = float(alternative.get("confidence", 0.0) or 0.0)
                        if is_final:
                            final_segments.append(transcript)
                            confidences.append(confidence)
                            _emit_handler(payload, "on_final", transcript, True)
                            break
                        else:
                            latest_partial = transcript
                            _emit_handler(payload, "on_partial", transcript, False)
                        continue

                    if message_type == "UtteranceEnd":
                        break
                    if message_type == "Error":
                        raise RuntimeError(str(message.get("description") or "deepgram_error"))

            try:
                # Hold the lock only during the send phase so that
                # trigger_finalization() isn't blocked while Deepgram processes.
                async with state.lock:
                    for idx in range(0, len(audio_bytes), 8192):
                        await state.ws.send(audio_bytes[idx : idx + 8192])
                        await asyncio.sleep(0)
                    await state.ws.send(json.dumps({"type": "Finalize"}))
                # Consume results outside the lock — recv() does not conflict
                # with concurrent sends on a different asyncio task.
                await consume_results()
            except websockets.ConnectionClosed as exc:
                await self.end_session(session_id)
                if retry_count >= MAX_RETRIES:
                    raise RuntimeError("deepgram_connection_closed") from exc
                retry_count += 1
                await asyncio.sleep(min(0.5 * retry_count, 1.0))
                reopened_state = await self._open_session(session_id, payload)
                continue
            except Exception:
                await self.end_session(session_id)
                raise

            transcript = " ".join(final_segments).strip() or latest_partial or hint
            confidence = sum(confidences) / len(confidences) if confidences else (0.98 if transcript == hint and transcript else 0.0)
            return SttTranscript(
                text=transcript,
                confidence=confidence,
                is_final=bool(final_segments) or bool(transcript),
                source=self.provider_name,
            )


class MockLlmClient(BaseLlmClient):
    provider_name = "mock_llm"

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        starter = "I hear you. "
        if "price" in rep_text.lower():
            body = "That sounds expensive for us right now."
        elif "spouse" in rep_text.lower() or "partner" in rep_text.lower():
            body = "I need to discuss this with my spouse before deciding."
        elif "already" in rep_text.lower() or "provider" in rep_text.lower():
            body = "We already have someone handling this. Why switch?"
        elif stage == "close_attempt":
            body = "What would the next step look like if we did this today?"
        else:
            body = "Can you explain how this helps my home specifically?"
        for token in [starter, body]:
            await asyncio.sleep(0.01)
            yield token


class OpenAiLlmClient(_TaskConversationHistoryMixin, BaseLlmClient):
    provider_name = "openai"

    def __init__(self, api_key: str | None, model: str, base_url: str, timeout_seconds: float) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback = MockLlmClient()

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        if not self.api_key:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk
            return

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "stream": True,
            "temperature": 0.4,
            "max_tokens": max_tokens,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": system_prompt}, *self._history_for_current_task(), {"role": "user", "content": rep_text}],
        }

        emitted = False
        emitted_parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in _iter_sse_json_payloads(response):
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
                        token = delta.get("content")
                        if isinstance(token, str) and token:
                            emitted = True
                            emitted_parts.append(token)
                            yield token
                            continue
                        if isinstance(token, list):
                            text_parts = [str(item.get("text", "")) for item in token if isinstance(item, dict)]
                            merged = "".join(text_parts).strip()
                            if merged:
                                emitted = True
                                emitted_parts.append(merged)
                                yield merged
        except Exception:
            emitted = False

        if emitted:
            self._remember_exchange(user_text=rep_text, assistant_text="".join(emitted_parts))

        if not emitted:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk


class AnthropicLlmClient(_TaskConversationHistoryMixin, BaseLlmClient):
    provider_name = "anthropic"

    def __init__(self, api_key: str | None, model: str, base_url: str, timeout_seconds: float) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback = MockLlmClient()

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        if not self.api_key:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk
            return

        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.4,
            "stream": True,
            "system": system_prompt,
            "messages": [*self._history_for_current_task(), {"role": "user", "content": rep_text}],
        }

        emitted = False
        emitted_parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in _iter_sse_json_payloads(response):
                        event_type = str(chunk.get("type", ""))
                        token = ""
                        if event_type == "content_block_delta":
                            delta = chunk.get("delta", {})
                            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                                token = str(delta.get("text", ""))
                        elif event_type == "content_block_start":
                            content_block = chunk.get("content_block", {})
                            if isinstance(content_block, dict):
                                token = str(content_block.get("text", ""))

                        token = token.strip()
                        if token:
                            emitted = True
                            emitted_parts.append(token + " ")
                            yield token + " "
        except Exception:
            emitted = False

        if emitted:
            self._remember_exchange(user_text=rep_text, assistant_text="".join(emitted_parts).strip())

        if not emitted:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk


class MockTtsClient(BaseTtsClient):
    provider_name = "mock_tts"

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        if not text:
            return
        await asyncio.sleep(0.005)
        yield {
            "codec": "pcm16",
            "payload": "UklGRiQAAABXQVZFZm10",
            "duration_ms": max(120, min(1200, len(text) * 18)),
            "provider": self.provider_name,
        }


class ElevenLabsTtsClient(BaseTtsClient):
    provider_name = "elevenlabs"

    def __init__(
        self,
        api_key: str | None,
        voice_id: str | None,
        model_id: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback = MockTtsClient()

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        if not text:
            return

        voice_id, cleaned_text = self._resolve_voice(text)

        if not self.api_key or not voice_id:
            async for chunk in self._fallback.stream_audio(cleaned_text):
                out = dict(chunk)
                out["provider"] = self.provider_name
                out["voice_id"] = voice_id
                yield out
            return

        url = f"{self.base_url}/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": self.api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }
        payload = {
            "text": cleaned_text,
            "model_id": self.model_id,
            "optimize_streaming_latency": 3,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }

        emitted = False
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for raw_chunk in response.aiter_bytes():
                        if not raw_chunk:
                            continue
                        emitted = True
                        duration_ms = max(40, int(len(raw_chunk) / 32))
                        yield {
                            "codec": "mp3",
                            "payload": base64.b64encode(raw_chunk).decode("utf-8"),
                            "duration_ms": duration_ms,
                            "provider": self.provider_name,
                            "voice_id": voice_id,
                        }
        except Exception:
            emitted = False

        if not emitted:
            async for chunk in self._fallback.stream_audio(cleaned_text):
                out = dict(chunk)
                out["provider"] = self.provider_name
                out["voice_id"] = voice_id
                yield out

    def _resolve_voice(self, text: str) -> tuple[str | None, str]:
        if text.startswith("[[voice:") and "]]" in text:
            directive, remainder = text.split("]]", 1)
            voice_id = directive.removeprefix("[[voice:").strip()
            return (voice_id or self.voice_id), remainder.lstrip()
        return self.voice_id, text


@dataclass
class ProviderSuite:
    stt: BaseSttClient
    llm: BaseLlmClient
    tts: BaseTtsClient

    @classmethod
    def from_settings(cls, settings) -> ProviderSuite:
        stt_provider = (settings.stt_provider or "mock").lower()
        llm_provider = (settings.llm_provider or "mock").lower()
        tts_provider = (settings.tts_provider or "mock").lower()

        stt = (
            DeepgramSttClient(
                settings.deepgram_api_key,
                base_url=settings.deepgram_base_url,
                model=settings.deepgram_model,
                timeout_seconds=settings.provider_timeout_seconds,
            )
            if stt_provider == "deepgram"
            else MockSttClient()
        )

        llm = (
            AnthropicLlmClient(
                settings.anthropic_api_key,
                model=settings.anthropic_model,
                base_url=settings.anthropic_base_url,
                timeout_seconds=settings.provider_timeout_seconds,
            )
            if llm_provider == "anthropic"
            else (
                OpenAiLlmClient(
                    settings.openai_api_key,
                    model=settings.openai_model,
                    base_url=settings.openai_base_url,
                    timeout_seconds=settings.provider_timeout_seconds,
                )
                if llm_provider == "openai"
                else MockLlmClient()
            )
        )

        tts = (
            ElevenLabsTtsClient(
                settings.elevenlabs_api_key,
                settings.elevenlabs_voice_id,
                model_id=settings.elevenlabs_model_id,
                base_url=settings.elevenlabs_base_url,
                timeout_seconds=settings.provider_timeout_seconds,
            )
            if tts_provider == "elevenlabs"
            else MockTtsClient()
        )

        return cls(stt=stt, llm=llm, tts=tts)
