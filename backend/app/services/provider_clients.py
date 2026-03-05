from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import AsyncIterator

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

        audio_b64 = payload.get("audio_base64")
        if not self.api_key or not audio_b64:
            return await self._fallback.finalize_utterance(payload)

        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            return await self._fallback.finalize_utterance(payload)

        content_type = payload.get("content_type") or "audio/wav"
        url = f"{self.base_url}/v1/listen"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": content_type,
        }
        params = {"model": self.model, "smart_format": "true"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, params=params, headers=headers, content=audio_bytes)
                response.raise_for_status()
                body = response.json()
        except Exception:
            return await self._fallback.finalize_utterance(payload)

        transcript = (
            body.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
            .strip()
        )
        confidence = (
            body.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("confidence", 0.0)
        )

        if transcript:
            return SttTranscript(text=transcript, confidence=float(confidence or 0.0), is_final=True, source=self.provider_name)
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
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        raw = line.removeprefix("data:").strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content")
                        if token:
                            emitted = True
                            yield token
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
            OpenAiLlmClient(
                settings.openai_api_key,
                model=settings.openai_model,
                base_url=settings.openai_base_url,
                timeout_seconds=settings.provider_timeout_seconds,
            )
            if llm_provider == "openai"
            else MockLlmClient()
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
