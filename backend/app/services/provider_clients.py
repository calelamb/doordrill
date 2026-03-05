from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx


@dataclass
class SttTranscript:
    text: str
    confidence: float
    is_final: bool
    source: str


class BaseSttClient:
    provider_name = "base"

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        raise NotImplementedError


class BaseLlmClient:
    provider_name = "base"

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str) -> AsyncIterator[str]:
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


class MockSttClient(BaseSttClient):
    provider_name = "mock_stt"

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        return SttTranscript(text=hint, confidence=0.98 if hint else 0.0, is_final=bool(hint), source=self.provider_name)


class DeepgramSttClient(BaseSttClient):
    provider_name = "deepgram"

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._fallback = MockSttClient()

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        if hint:
            return SttTranscript(text=hint, confidence=0.98, is_final=True, source=self.provider_name)

        if not self.api_key:
            return await self._fallback.finalize_utterance(payload)

        audio_bytes = _decode_base64_audio(payload)
        if not audio_bytes:
            return await self._fallback.finalize_utterance(payload)

        content_type = payload.get("content_type") or "audio/wav"
        url = f"{self.base_url}/v1/listen"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": content_type,
        }
        params = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, params=params, headers=headers, content=audio_bytes)
                response.raise_for_status()
                body = response.json()
        except Exception:
            return await self._fallback.finalize_utterance(payload)

        alternatives = (
            body.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])
        )
        transcript = str((alternatives[0] if alternatives else {}).get("transcript", "")).strip()
        confidence = float((alternatives[0] if alternatives else {}).get("confidence", 0.0) or 0.0)

        if transcript:
            return SttTranscript(text=transcript, confidence=confidence, is_final=True, source=self.provider_name)
        return await self._fallback.finalize_utterance(payload)


class MockLlmClient(BaseLlmClient):
    provider_name = "mock_llm"

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str) -> AsyncIterator[str]:
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


class OpenAiLlmClient(BaseLlmClient):
    provider_name = "openai"

    def __init__(self, api_key: str | None, model: str, base_url: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback = MockLlmClient()

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str) -> AsyncIterator[str]:
        if not self.api_key:
            async for chunk in self._fallback.stream_reply(rep_text=rep_text, stage=stage, system_prompt=system_prompt):
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
            "max_tokens": 180,
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": rep_text},
            ],
        }

        emitted = False
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
                            yield token
                            continue
                        if isinstance(token, list):
                            text_parts = [str(item.get("text", "")) for item in token if isinstance(item, dict)]
                            merged = "".join(text_parts).strip()
                            if merged:
                                emitted = True
                                yield merged
        except Exception:
            emitted = False

        if not emitted:
            async for chunk in self._fallback.stream_reply(rep_text=rep_text, stage=stage, system_prompt=system_prompt):
                yield chunk


class AnthropicLlmClient(BaseLlmClient):
    provider_name = "anthropic"

    def __init__(self, api_key: str | None, model: str, base_url: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback = MockLlmClient()

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str) -> AsyncIterator[str]:
        if not self.api_key:
            async for chunk in self._fallback.stream_reply(rep_text=rep_text, stage=stage, system_prompt=system_prompt):
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
            "max_tokens": 220,
            "temperature": 0.4,
            "stream": True,
            "system": system_prompt,
            "messages": [{"role": "user", "content": rep_text}],
        }

        emitted = False
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
                            yield token + " "
        except Exception:
            emitted = False

        if not emitted:
            async for chunk in self._fallback.stream_reply(rep_text=rep_text, stage=stage, system_prompt=system_prompt):
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

        if not self.api_key or not self.voice_id:
            async for chunk in self._fallback.stream_audio(text):
                out = dict(chunk)
                out["provider"] = self.provider_name
                out["voice_id"] = self.voice_id
                yield out
            return

        url = f"{self.base_url}/v1/text-to-speech/{self.voice_id}/stream"
        headers = {
            "xi-api-key": self.api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }
        payload = {
            "text": text,
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
                            "voice_id": self.voice_id,
                        }
        except Exception:
            emitted = False

        if not emitted:
            async for chunk in self._fallback.stream_audio(text):
                out = dict(chunk)
                out["provider"] = self.provider_name
                out["voice_id"] = self.voice_id
                yield out


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
