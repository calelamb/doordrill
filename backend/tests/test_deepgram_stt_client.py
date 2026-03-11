from collections.abc import Iterator
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.provider_clients import DeepgramSttClient


FINAL_RESULT = json.dumps({
    "type": "Results",
    "is_final": True,
    "channel": {"alternatives": [{"transcript": "hello world", "confidence": 0.95}]},
})


def make_ws(recv_payloads: list[str] | None = None) -> MagicMock:
    """Return a mock WebSocket that yields recv_payloads in order."""
    ws = MagicMock()
    ws.closed = False
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    payloads = recv_payloads or [FINAL_RESULT]
    ws.recv = AsyncMock(side_effect=payloads)
    return ws


def make_client(**kwargs) -> DeepgramSttClient:
    defaults = dict(
        api_key="test-key",
        base_url="https://api.deepgram.com",
        model="nova-2",
        timeout_seconds=5.0,
    )
    defaults.update(kwargs)
    return DeepgramSttClient(**defaults)


def parse_url_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


@pytest.fixture(scope="session", autouse=True)
def initialize_test_db() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def configure_test_runtime() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def reset_db() -> Iterator[None]:
    yield


def test_listen_url_wav_sets_linear16_encoding_not_mimetype():
    client = make_client()
    url = client._listen_url({"codec": "wav", "content_type": "audio/wav",
                               "sample_rate": 16000, "channels": 1})
    params = parse_url_params(url)
    assert params["encoding"] == ["linear16"]
    assert params["sample_rate"] == ["16000"]
    assert params["channels"] == ["1"]
    assert "mimetype" not in params


def test_listen_url_opus_sets_encoding_opus_not_mimetype():
    client = make_client()
    url = client._listen_url({"codec": "opus", "content_type": "audio/opus",
                               "sample_rate": 48000})
    params = parse_url_params(url)
    assert params["encoding"] == ["opus"]
    assert "mimetype" not in params


def test_listen_url_mp4_sets_mimetype_not_encoding():
    client = make_client()
    url = client._listen_url({"codec": "m4a", "content_type": "audio/mp4"})
    params = parse_url_params(url)
    assert params["mimetype"] == ["audio/mp4"]
    assert "encoding" not in params


def test_listen_url_webm_sets_mimetype_not_encoding():
    client = make_client()
    url = client._listen_url({"codec": "webm", "content_type": "audio/webm"})
    params = parse_url_params(url)
    assert params["mimetype"] == ["audio/webm"]
    assert "encoding" not in params


def test_listen_url_mp3_sets_mimetype_not_encoding():
    client = make_client()
    url = client._listen_url({"codec": "mp3", "content_type": "audio/mpeg"})
    params = parse_url_params(url)
    assert params["mimetype"] == ["audio/mpeg"]
    assert "encoding" not in params


def test_listen_url_default_sample_rate_is_16000():
    client = make_client()
    url = client._listen_url({"codec": "wav", "content_type": "audio/wav"})
    params = parse_url_params(url)
    assert params["sample_rate"] == ["16000"]


def test_listen_url_forwards_sample_rate_from_payload():
    client = make_client()
    url = client._listen_url({"codec": "wav", "content_type": "audio/wav",
                               "sample_rate": 8000, "channels": 1})
    params = parse_url_params(url)
    assert params["sample_rate"] == ["8000"]


def test_listen_url_required_params_always_present():
    client = make_client()
    url = client._listen_url({"codec": "wav", "content_type": "audio/wav"})
    params = parse_url_params(url)
    for key in ("model", "smart_format", "punctuate", "interim_results", "endpointing"):
        assert key in params, f"missing required param: {key}"


@pytest.mark.asyncio
async def test_start_session_does_not_open_websocket():
    client = make_client()
    with patch("app.services.provider_clients.websockets.connect") as mock_connect:
        await client.start_session("sess-1")
        mock_connect.assert_not_called()
    assert "sess-1" in client._session_ids
    assert "sess-1" not in client._sessions


@pytest.mark.asyncio
async def test_no_api_key_start_session_is_noop():
    client = make_client(api_key=None)
    await client.start_session("sess-noop")
    assert "sess-noop" not in client._session_ids


@pytest.mark.asyncio
async def test_stream_utterance_opens_ws_lazily_on_first_call():
    ws = make_ws()
    client = make_client()
    payload = {
        "session_id": "sess-lazy",
        "codec": "wav",
        "content_type": "audio/wav",
        "sample_rate": 16000,
        "channels": 1,
    }
    audio = b"\x00" * 100

    with patch("app.services.provider_clients.websockets.connect",
               new=AsyncMock(return_value=ws)) as mock_connect:
        await client.start_session("sess-lazy")
        assert mock_connect.call_count == 0

        result = await client._stream_utterance(payload, audio, "")
        assert mock_connect.call_count == 1
        assert result.text == "hello world"

        connect_url = mock_connect.call_args[0][0]
        params = parse_url_params(connect_url)
        assert params["encoding"] == ["linear16"]
        assert "mimetype" not in params

        await client.end_session("sess-lazy")


@pytest.mark.asyncio
async def test_stream_utterance_reuses_open_socket_on_second_call():
    ws = make_ws(recv_payloads=[FINAL_RESULT, FINAL_RESULT])
    client = make_client()
    payload = {
        "session_id": "sess-reuse",
        "codec": "wav",
        "content_type": "audio/wav",
        "sample_rate": 16000,
        "channels": 1,
    }
    audio = b"\x00" * 100

    with patch("app.services.provider_clients.websockets.connect",
               new=AsyncMock(return_value=ws)) as mock_connect:
        await client.start_session("sess-reuse")
        await client._stream_utterance(payload, audio, "")
        await client._stream_utterance(payload, audio, "")
        assert mock_connect.call_count == 1

        await client.end_session("sess-reuse")


@pytest.mark.asyncio
async def test_stream_utterance_reconnects_when_codec_changes():
    ws1 = make_ws()
    ws2 = make_ws()
    client = make_client()
    session_id = "sess-codec-change"
    audio = b"\x00" * 100

    wav_payload = {"session_id": session_id, "codec": "wav",
                   "content_type": "audio/wav", "sample_rate": 16000, "channels": 1}
    opus_payload = {"session_id": session_id, "codec": "opus",
                    "content_type": "audio/opus", "sample_rate": 48000}

    connect_side_effect = [ws1, ws2]
    with patch("app.services.provider_clients.websockets.connect",
               new=AsyncMock(side_effect=connect_side_effect)) as mock_connect:
        await client.start_session(session_id)
        await client._stream_utterance(wav_payload, audio, "")
        assert mock_connect.call_count == 1

        await client._stream_utterance(opus_payload, audio, "")
        assert mock_connect.call_count == 2

        await client.end_session(session_id)


@pytest.mark.asyncio
async def test_stream_utterance_retries_once_on_connection_closed():
    ws_closed = make_ws()
    ws_closed.closed = True
    ws_fresh = make_ws()
    client = make_client()
    session_id = "sess-retry"
    payload = {"session_id": session_id, "codec": "wav",
               "content_type": "audio/wav", "sample_rate": 16000, "channels": 1}
    audio = b"\x00" * 100

    connect_calls = [ws_closed, ws_fresh]
    with patch("app.services.provider_clients.websockets.connect",
               new=AsyncMock(side_effect=connect_calls)):
        await client.start_session(session_id)
        result = await client._stream_utterance(payload, audio, "")
        assert result.text == "hello world"

        await client.end_session(session_id)


@pytest.mark.asyncio
async def test_end_session_closes_socket_and_removes_state():
    ws = make_ws()
    client = make_client()
    session_id = "sess-end"
    payload = {"session_id": session_id, "codec": "wav",
               "content_type": "audio/wav", "sample_rate": 16000, "channels": 1}

    with patch("app.services.provider_clients.websockets.connect",
               new=AsyncMock(return_value=ws)):
        await client.start_session(session_id)
        await client._stream_utterance(payload, b"\x00" * 100, "")
        assert session_id in client._sessions

        await client.end_session(session_id)
        assert session_id not in client._sessions
        assert session_id not in client._session_ids
        ws.close.assert_called_once()
