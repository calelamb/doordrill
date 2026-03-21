"""Tests for AssemblyAI STT client and updated BaseSttClient interface."""
import inspect
from unittest.mock import MagicMock

import pytest

from app.services.provider_clients import (
    AssemblyAiSttClient,
    BaseSttClient,
    MockSttClient,
    ProviderSuite,
)


def test_base_stt_client_start_session_accepts_vocabulary_kwarg():
    """BaseSttClient.start_session must accept a vocabulary keyword argument."""
    sig = inspect.signature(BaseSttClient.start_session)
    assert "vocabulary" in sig.parameters, "BaseSttClient.start_session must have a 'vocabulary' parameter"
    param = sig.parameters["vocabulary"]
    assert param.default is None, "vocabulary parameter should default to None"
    # Must be keyword-only (the * forces this)
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, "vocabulary must be keyword-only"


@pytest.mark.asyncio
async def test_mock_stt_client_accepts_vocabulary_without_error():
    """MockSttClient.start_session should accept vocabulary kwarg without raising."""
    client = MockSttClient()
    await client.start_session("session-1", vocabulary=["solar", "panel"])
    await client.start_session("session-2", vocabulary=None)
    await client.start_session("session-3")


def test_assemblyai_stt_client_provider_name():
    """AssemblyAiSttClient must have provider_name == 'assemblyai'."""
    client = AssemblyAiSttClient(api_key="test-key")
    assert client.provider_name == "assemblyai"


def test_assemblyai_stt_client_instantiation():
    """AssemblyAiSttClient instantiates with api_key and has expected attributes."""
    client = AssemblyAiSttClient(api_key="my-key")
    assert client._api_key == "my-key"
    assert isinstance(client._sessions, dict)
    assert isinstance(client._vocabulary, list)
    assert isinstance(client._fallback, MockSttClient)


@pytest.mark.asyncio
async def test_assemblyai_start_session_stores_vocabulary():
    """start_session stores vocabulary and creates session entry."""
    client = AssemblyAiSttClient(api_key="test-key")
    vocab = ["solar", "roofing", "kwh"]
    await client.start_session("sess-1", vocabulary=vocab)
    assert "sess-1" in client._sessions
    assert client._vocabulary == vocab


@pytest.mark.asyncio
async def test_assemblyai_start_session_defaults_vocabulary_to_empty():
    """start_session without vocabulary defaults to empty list."""
    client = AssemblyAiSttClient(api_key="test-key")
    await client.start_session("sess-2")
    assert client._vocabulary == []


@pytest.mark.asyncio
async def test_assemblyai_end_session_removes_session():
    """end_session removes the session from _sessions."""
    client = AssemblyAiSttClient(api_key="test-key")
    await client.start_session("sess-3", vocabulary=["x"])
    assert "sess-3" in client._sessions
    await client.end_session("sess-3")
    assert "sess-3" not in client._sessions


@pytest.mark.asyncio
async def test_assemblyai_end_session_nonexistent_does_not_raise():
    """end_session on a nonexistent session should not raise."""
    client = AssemblyAiSttClient(api_key="test-key")
    await client.end_session("does-not-exist")


@pytest.mark.asyncio
async def test_assemblyai_finalize_utterance_no_audio_uses_hint():
    """finalize_utterance with no audio but a hint should return the hint via fallback."""
    client = AssemblyAiSttClient(api_key="test-key")
    result = await client.finalize_utterance({"transcript_hint": "hello world"})
    assert result.text == "hello world"
    assert result.is_final is True


@pytest.mark.asyncio
async def test_assemblyai_finalize_utterance_no_audio_no_hint_uses_fallback():
    """finalize_utterance with no audio and no hint falls back to MockSttClient."""
    client = AssemblyAiSttClient(api_key="test-key")
    result = await client.finalize_utterance({})
    # MockSttClient returns empty text with confidence 0.0 when no hint
    assert result.text == ""
    assert result.source in ("assemblyai_hint", "mock_stt", "assemblyai")


def test_provider_suite_resolves_assemblyai_when_configured():
    """ProviderSuite.from_settings resolves AssemblyAiSttClient when stt_provider='assemblyai'."""
    settings = MagicMock()
    settings.stt_provider = "assemblyai"
    settings.assemblyai_api_key = "aai-test-key"
    settings.llm_provider = "mock"
    settings.tts_provider = "mock"
    settings.provider_timeout_seconds = 10.0

    suite = ProviderSuite.from_settings(settings)
    assert isinstance(suite.stt, AssemblyAiSttClient)
    assert suite.stt._api_key == "aai-test-key"


def test_provider_suite_falls_back_to_mock_when_assemblyai_key_missing():
    """ProviderSuite.from_settings falls back to MockSttClient when assemblyai key is absent."""
    settings = MagicMock()
    settings.stt_provider = "assemblyai"
    settings.assemblyai_api_key = None
    settings.llm_provider = "mock"
    settings.tts_provider = "mock"
    settings.provider_timeout_seconds = 10.0

    suite = ProviderSuite.from_settings(settings)
    assert isinstance(suite.stt, MockSttClient)
