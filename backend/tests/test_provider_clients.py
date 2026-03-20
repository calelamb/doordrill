import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
import websockets
from websockets.frames import Close

from app.services.provider_clients import AnthropicLlmClient, DeepgramSttClient, ElevenLabsTtsClient, OpenAiLlmClient, _DeepgramSessionState


@pytest.mark.asyncio
async def test_deepgram_client_uses_transcript_hint_without_key():
    client = DeepgramSttClient(api_key=None, base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    result = await client.finalize_utterance({"transcript_hint": "hello there"})
    assert result.text == "hello there"
    assert result.is_final is True


@pytest.mark.asyncio
async def test_deepgram_trigger_finalization_sends_finalize_message():
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    await client.start_session("debug-session")
    fake_ws = _FakeDeepgramWs([])
    keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    client._sessions["debug-session"] = _DeepgramSessionState(
        ws=fake_ws,
        lock=asyncio.Lock(),
        keepalive_task=keepalive_task,
        listen_url="wss://api.deepgram.com/v1/listen?encoding=linear16",
    )

    try:
        await client.trigger_finalization()
    finally:
        keepalive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await keepalive_task

    assert fake_ws.sent == ['{"type": "Finalize"}']


@pytest.mark.asyncio
async def test_deepgram_listen_url_defaults_to_linear16_for_non_opus_payloads():
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)

    wav_url = client._listen_url({"codec": "wav", "content_type": "audio/wav", "sample_rate": 16000, "channels": 1})
    fallback_url = client._listen_url({"codec": "unknown", "sample_rate": 16000, "channels": 1})
    opus_url = client._listen_url({"codec": "opus", "sample_rate": 16000})

    assert "encoding=linear16" in wav_url
    assert "encoding=linear16" in fallback_url
    assert "encoding=opus" in opus_url


@pytest.mark.asyncio
async def test_deepgram_listen_url_includes_vocabulary_hints():
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    vocabulary_hints = [f"term {index}" for index in range(105)]

    url = client._listen_url(
        {
            "codec": "wav",
            "content_type": "audio/wav",
            "sample_rate": 16000,
            "channels": 1,
            "vocabulary_hints": vocabulary_hints,
        }
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "wss"
    assert parsed.path == "/v1/listen"
    assert "keywords" not in query
    assert query["keyterm"] == vocabulary_hints[:100]
    assert query["language"] == ["en-US"]
    assert query["endpointing"] == ["300"]
    assert query["utterance_end_ms"] == ["1200"]
    assert query["no_delay"] == ["true"]
    assert query["disfluencies"] == ["false"]


class _FakeDeepgramWs:
    def __init__(self, messages, *, closed: bool = False):
        self._messages = list(messages)
        self.sent: list[object] = []
        self.recv_calls = 0
        self.closed = closed
        self.close_calls = 0

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        self.recv_calls += 1
        if not self._messages:
            await asyncio.sleep(3600)
        next_message = self._messages.pop(0)
        if isinstance(next_message, Exception):
            raise next_message
        return next_message

    async def close(self):
        self.close_calls += 1
        self.closed = True


def _connection_closed_ok() -> websockets.ConnectionClosedOK:
    return websockets.ConnectionClosedOK(Close(1000, ""), Close(1000, ""), True)


@pytest.mark.asyncio
async def test_deepgram_stream_exits_on_first_final_result(monkeypatch):
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    fake_ws = _FakeDeepgramWs(
        [
            '{"type":"Results","is_final":true,"speech_final":true,"channel":{"alternatives":[{"transcript":"hello there","confidence":0.91}]}}',
        ]
    )
    keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    state = _DeepgramSessionState(
        ws=fake_ws,
        lock=asyncio.Lock(),
        keepalive_task=keepalive_task,
        listen_url="wss://api.deepgram.com/v1/listen?encoding=linear16",
    )

    async def fake_get_or_open_session(session_id: str, *, payload: dict, force_reconnect: bool = False):
        return state

    monkeypatch.setattr(client, "_get_or_open_session", fake_get_or_open_session)

    try:
        result = await client._stream_utterance(
            {"session_id": "debug-session", "codec": "wav", "content_type": "audio/wav"},
            b"abc",
            "",
        )
    finally:
        keepalive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await keepalive_task

    assert result.text == "hello there"
    assert result.is_final is True
    assert fake_ws.recv_calls == 1
    assert any(payload == '{"type": "Finalize"}' for payload in fake_ws.sent)


@pytest.mark.asyncio
async def test_deepgram_stream_reopens_stale_closed_session(monkeypatch):
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    payload = {"session_id": "debug-session", "codec": "wav", "content_type": "audio/wav"}

    stale_ws = _FakeDeepgramWs([], closed=True)
    stale_keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    client._sessions[payload["session_id"]] = _DeepgramSessionState(
        ws=stale_ws,
        lock=asyncio.Lock(),
        keepalive_task=stale_keepalive_task,
        listen_url=client._listen_url(payload),
    )

    fresh_ws = _FakeDeepgramWs(
        [
            '{"type":"Results","is_final":true,"speech_final":true,"channel":{"alternatives":[{"transcript":"hello again","confidence":0.88}]}}',
        ]
    )
    fresh_keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    open_calls: list[tuple[str, dict]] = []

    async def fake_open_session(session_id: str, open_payload: dict) -> _DeepgramSessionState:
        open_calls.append((session_id, open_payload))
        state = _DeepgramSessionState(
            ws=fresh_ws,
            lock=asyncio.Lock(),
            keepalive_task=fresh_keepalive_task,
            listen_url=client._listen_url(open_payload),
        )
        client._sessions[session_id] = state
        return state

    monkeypatch.setattr(client, "_open_session", fake_open_session)

    try:
        result = await client._stream_utterance(payload, b"abc", "")
    finally:
        if not stale_keepalive_task.done():
            stale_keepalive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stale_keepalive_task
        if not fresh_keepalive_task.done():
            fresh_keepalive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await fresh_keepalive_task

    assert result.text == "hello again"
    assert open_calls == [(payload["session_id"], payload)]
    assert fresh_ws.sent[0] == b"abc"
    assert any(message == '{"type": "Finalize"}' for message in fresh_ws.sent)
    assert stale_ws.close_calls == 1


@pytest.mark.asyncio
async def test_deepgram_stream_retries_once_after_connection_closed_during_results(monkeypatch):
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    payload = {"session_id": "debug-session", "codec": "wav", "content_type": "audio/wav"}

    stale_ws = _FakeDeepgramWs([_connection_closed_ok()])
    stale_keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    client._sessions[payload["session_id"]] = _DeepgramSessionState(
        ws=stale_ws,
        lock=asyncio.Lock(),
        keepalive_task=stale_keepalive_task,
        listen_url=client._listen_url(payload),
    )

    fresh_ws = _FakeDeepgramWs(
        [
            '{"type":"Results","is_final":true,"speech_final":true,"channel":{"alternatives":[{"transcript":"retried transcript","confidence":0.91}]}}',
        ]
    )
    fresh_keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    open_calls: list[tuple[str, dict]] = []

    async def fake_open_session(session_id: str, open_payload: dict) -> _DeepgramSessionState:
        open_calls.append((session_id, open_payload))
        state = _DeepgramSessionState(
            ws=fresh_ws,
            lock=asyncio.Lock(),
            keepalive_task=fresh_keepalive_task,
            listen_url=client._listen_url(open_payload),
        )
        client._sessions[session_id] = state
        return state

    monkeypatch.setattr(client, "_open_session", fake_open_session)

    try:
        result = await client._stream_utterance(payload, b"abc", "")
    finally:
        if not stale_keepalive_task.done():
            stale_keepalive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stale_keepalive_task
        if not fresh_keepalive_task.done():
            fresh_keepalive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await fresh_keepalive_task

    assert result.text == "retried transcript"
    assert open_calls == [(payload["session_id"], payload)]
    assert stale_ws.recv_calls == 1
    assert any(message == '{"type": "Finalize"}' for message in stale_ws.sent)
    assert fresh_ws.sent[0] == b"abc"


@pytest.mark.asyncio
async def test_consume_results_breaks_after_finalize_without_speech_final(monkeypatch):
    client = DeepgramSttClient(api_key="test", base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    payload = {"session_id": "debug-session", "codec": "wav", "content_type": "audio/wav"}
    fake_ws = _FakeDeepgramWs(
        [
            '{"type":"Results","is_final":true,"speech_final":false,"channel":{"alternatives":[{"transcript":"Yeah","confidence":0.93}]}}',
        ]
    )
    keepalive_task = asyncio.create_task(asyncio.sleep(3600))
    state = _DeepgramSessionState(
        ws=fake_ws,
        lock=asyncio.Lock(),
        keepalive_task=keepalive_task,
        listen_url="wss://api.deepgram.com/v1/listen?encoding=linear16",
    )

    async def fake_get_or_open_session(session_id: str, *, payload: dict, force_reconnect: bool = False):
        return state

    monkeypatch.setattr(client, "_get_or_open_session", fake_get_or_open_session)

    try:
        started = asyncio.get_running_loop().time()
        result = await client._stream_utterance(payload, b"abc", "")
        elapsed = asyncio.get_running_loop().time() - started
    finally:
        keepalive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await keepalive_task

    assert result.text == "Yeah"
    assert result.is_final is True
    assert elapsed < 0.4
    assert fake_ws.recv_calls == 2
    assert any(message == '{"type": "Finalize"}' for message in fake_ws.sent)


@pytest.mark.asyncio
async def test_openai_client_falls_back_to_mock_without_key():
    client = OpenAiLlmClient(api_key=None, model="gpt-4o-mini", base_url="https://api.openai.com/v1", timeout_seconds=1)
    chunks = [chunk async for chunk in client.stream_reply(rep_text="We can cut your price", stage="objection_handling", system_prompt="x")]
    combined = "".join(chunks)
    assert "expensive" in combined.lower()


@pytest.mark.asyncio
async def test_elevenlabs_client_falls_back_without_credentials():
    client = ElevenLabsTtsClient(
        api_key=None,
        voice_id=None,
        model_id="eleven_flash_v2_5",
        base_url="https://api.elevenlabs.io",
        timeout_seconds=1,
    )
    chunks = [chunk async for chunk in client.stream_audio("hello")]
    assert chunks
    assert chunks[0]["provider"] == "elevenlabs"


@pytest.mark.asyncio
async def test_anthropic_client_falls_back_to_mock_without_key():
    client = AnthropicLlmClient(
        api_key=None,
        model="claude-3-5-sonnet-latest",
        base_url="https://api.anthropic.com",
        timeout_seconds=1,
    )
    chunks = [chunk async for chunk in client.stream_reply(rep_text="We can cut your price", stage="objection_handling", system_prompt="x")]
    combined = "".join(chunks)
    assert "expensive" in combined.lower()
