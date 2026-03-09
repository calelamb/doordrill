#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import websockets

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.core.config import get_settings
from app.services.provider_clients import DeepgramSttClient


@dataclass
class AudioFixture:
    label: str
    audio_bytes: bytes
    payload: dict[str, Any]


@dataclass
class ProbeResult:
    session_type: str
    utterance: str
    total_ms: float


def _make_silent_wav(duration_ms: int = 500, sample_rate: int = 16000) -> bytes:
    num_samples = int(sample_rate * duration_ms / 1000)
    pcm = bytes(num_samples * 2)
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return header + pcm


def _load_audio_fixture() -> AudioFixture:
    candidates = sorted(BACKEND_DIR.rglob("*.wav")) + sorted(BACKEND_DIR.rglob("*.raw")) + sorted(BACKEND_DIR.rglob("*.pcm"))
    for path in candidates:
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".wav":
            return AudioFixture(
                label=str(path.relative_to(BACKEND_DIR)),
                audio_bytes=path.read_bytes(),
                payload={
                    "codec": "wav",
                    "content_type": "audio/wav",
                    "sample_rate": 16000,
                    "channels": 1,
                },
            )
        return AudioFixture(
            label=str(path.relative_to(BACKEND_DIR)),
            audio_bytes=path.read_bytes(),
            payload={
                "codec": "pcm16",
                "content_type": "audio/raw",
                "sample_rate": 16000,
                "channels": 1,
            },
        )

    return AudioFixture(
        label="generated:silent_wav(stress_test_compatible)",
        audio_bytes=_make_silent_wav(),
        payload={
            "codec": "wav",
            "content_type": "audio/wav",
            "sample_rate": 16000,
            "channels": 1,
        },
    )


def _message_details(message: dict[str, Any]) -> tuple[str, str, str]:
    message_type = str(message.get("type") or "unknown")
    is_final = "-"
    transcript_snippet = ""

    if message_type == "Results":
        alternatives = ((message.get("channel") or {}).get("alternatives") or [])
        alternative = alternatives[0] if alternatives else {}
        transcript_snippet = str(alternative.get("transcript") or "").strip()
        is_final = str(bool(message.get("is_final") or message.get("speech_final"))).lower()
    elif message_type == "Error":
        transcript_snippet = str(message.get("description") or "").strip()
    elif message_type == "UtteranceEnd":
        transcript_snippet = f"last_word_end={message.get('last_word_end')}"
    elif message_type == "Metadata":
        request_id = str(message.get("request_id") or "").strip()
        transcript_snippet = f"request_id={request_id}"

    transcript_snippet = transcript_snippet.replace("\n", " ").strip()
    if len(transcript_snippet) > 80:
        transcript_snippet = f"{transcript_snippet[:80]}..."
    return message_type, is_final, transcript_snippet


async def _warm_session(client: DeepgramSttClient, session_id: str) -> None:
    started_at = time.perf_counter()
    await client.start_session(session_id)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    print(f"\n[session warmup] session_id={session_id} total_ms={elapsed_ms:.1f}")
    print("[session warmup] listen_url=deferred_until_first_utterance")


async def _probe_utterance(
    *,
    client: DeepgramSttClient,
    session_id: str,
    session_type: str,
    utterance: str,
    fixture: AudioFixture,
) -> ProbeResult:
    start_at = time.perf_counter()
    state = await client._get_or_open_session(session_id, payload=fixture.payload)
    finalize_sent_at: float | None = None
    saw_utterance_end = False
    saw_keepalive = False
    hit_timeout = False

    print(f"\n=== {session_type} | {utterance} | session_id={session_id} | ws_id={id(state.ws)} ===")
    print(f"audio_fixture={fixture.label} bytes={len(fixture.audio_bytes)}")
    print(f"utterance_payload={fixture.payload}")
    print(f"listen_url_if_opened_now={client._listen_url(fixture.payload)}")
    print(f"timeout_seconds={client.timeout_seconds}")

    async with state.lock:
        for idx in range(0, len(fixture.audio_bytes), 8192):
            await state.ws.send(fixture.audio_bytes[idx : idx + 8192])
            await asyncio.sleep(0)
        finalize_sent_at = time.perf_counter()
        print(f"{(finalize_sent_at - start_at) * 1000:9.1f}ms | FinalizeSent | is_final=- | transcript=")
        await state.ws.send(json.dumps({"type": "Finalize"}))

        while True:
            try:
                raw_message = await asyncio.wait_for(state.ws.recv(), timeout=client.timeout_seconds)
            except TimeoutError:
                hit_timeout = True
                elapsed_ms = (time.perf_counter() - start_at) * 1000
                print(f"{elapsed_ms:9.1f}ms | Timeout | is_final=- | transcript=wait_for_timeout")
                break
            except websockets.ConnectionClosed as exc:
                elapsed_ms = (time.perf_counter() - start_at) * 1000
                print(f"{elapsed_ms:9.1f}ms | ConnectionClosed | is_final=- | transcript=code={exc.code} reason={exc.reason}")
                raise

            elapsed_ms = (time.perf_counter() - start_at) * 1000
            if isinstance(raw_message, bytes):
                print(f"{elapsed_ms:9.1f}ms | BytesFrame | is_final=- | transcript=len={len(raw_message)}")
                continue

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                snippet = raw_message.strip().replace("\n", " ")
                if len(snippet) > 80:
                    snippet = f"{snippet[:80]}..."
                print(f"{elapsed_ms:9.1f}ms | InvalidJson | is_final=- | transcript={snippet}")
                continue

            message_type, is_final, transcript_snippet = _message_details(message)
            print(f"{elapsed_ms:9.1f}ms | {message_type} | is_final={is_final} | transcript={transcript_snippet}")

            if message_type == "KeepAlive":
                saw_keepalive = True
                continue
            if message_type == "Results" and is_final == "true":
                break
            if message_type == "UtteranceEnd":
                saw_utterance_end = True
                break
            if message_type == "Error":
                break

    total_ms = (time.perf_counter() - start_at) * 1000
    finalize_to_exit_ms = ((time.perf_counter() - finalize_sent_at) * 1000) if finalize_sent_at is not None else 0.0
    print(
        f"[utterance complete] session_type={session_type} utterance={utterance} "
        f"total_ms={total_ms:.1f} finalize_to_exit_ms={finalize_to_exit_ms:.1f} "
        f"saw_utterance_end={saw_utterance_end} saw_keepalive={saw_keepalive} hit_timeout={hit_timeout}"
    )
    return ProbeResult(session_type=session_type, utterance=utterance, total_ms=total_ms)


def _print_summary(results: list[ProbeResult]) -> None:
    print("\nSummary")
    print(f"{'session_type':<18} {'utterance':<12} {'total_ms':>10}")
    print(f"{'-' * 18} {'-' * 12} {'-' * 10}")
    for result in results:
        print(f"{result.session_type:<18} {result.utterance:<12} {result.total_ms:10.1f}")


async def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set in backend/.env")

    fixture = _load_audio_fixture()
    client = DeepgramSttClient(
        api_key=settings.deepgram_api_key,
        base_url=settings.deepgram_base_url,
        model=settings.deepgram_model,
        timeout_seconds=settings.provider_timeout_seconds,
    )

    results: list[ProbeResult] = []
    print("Deepgram session debug probe")
    print(f"provider={client.provider_name} model={client.model} base_url={client.base_url}")
    print(f"audio_fixture={fixture.label} bytes={len(fixture.audio_bytes)} payload={fixture.payload}")

    try:
        await _warm_session(client, "debug-session-1")
        results.append(
            await _probe_utterance(
                client=client,
                session_id="debug-session-1",
                session_type="reused_session",
                utterance="turn_1",
                fixture=fixture,
            )
        )
        results.append(
            await _probe_utterance(
                client=client,
                session_id="debug-session-1",
                session_type="reused_session",
                utterance="turn_2",
                fixture=fixture,
            )
        )

        results.append(
            await _probe_utterance(
                client=client,
                session_id="debug-session-2",
                session_type="fresh_session",
                utterance="turn_1",
                fixture=fixture,
            )
        )
    finally:
        await client.end_session("debug-session-1")
        await client.end_session("debug-session-2")

    _print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
