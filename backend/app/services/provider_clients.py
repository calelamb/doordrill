from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator


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

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self._fallback = MockSttClient()

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        # Streaming websocket Deepgram integration is intentionally kept in gateway layer for low latency.
        # This client currently provides final utterance normalization + fallback behavior.
        if payload.get("transcript_hint"):
            return await self._fallback.finalize_utterance(payload)
        return SttTranscript(text="", confidence=0.0, is_final=False, source=self.provider_name)


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

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self._fallback = MockLlmClient()

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str) -> AsyncIterator[str]:
        # Provider integration hook. Use mock streaming until full realtime model wiring is enabled.
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

    def __init__(self, api_key: str | None, voice_id: str | None) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self._fallback = MockTtsClient()

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        # Provider integration hook. Use mock streaming until full websocket TTS plumbing is enabled.
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

        stt = DeepgramSttClient(settings.deepgram_api_key) if stt_provider == "deepgram" else MockSttClient()
        llm = OpenAiLlmClient(settings.openai_api_key) if llm_provider == "openai" else MockLlmClient()
        tts = (
            ElevenLabsTtsClient(settings.elevenlabs_api_key, settings.elevenlabs_voice_id)
            if tts_provider == "elevenlabs"
            else MockTtsClient()
        )

        return cls(stt=stt, llm=llm, tts=tts)
