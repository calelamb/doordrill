"""
DoorDrill End-to-End Stress Test
=================================
Tests the full drill loop with real providers: REST → WebSocket → STT → LLM → TTS

Usage:
  python stress_test.py                    # single drill, default settings
  python stress_test.py --turns 6          # 6 rep turns per drill
  python stress_test.py --concurrent 3     # 3 simultaneous drills
  python stress_test.py --skip-tts         # stop timing after LLM text, but still wait for turn completion
  python stress_test.py --provider-latency-only  # benchmark providers directly, no full drill

Prerequisites:
  pip install websockets httpx python-dotenv
  Backend must be running: uvicorn app.main:app --reload --port 8000
"""
import argparse
import asyncio
import base64
import json
import os
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

BASE_URL = "http://localhost:8000"
WS_URL  = "ws://localhost:8000"

# Simulated rep phrases — realistic door-to-door sales lines
REP_TURNS = [
    "Hi there, hope I'm not catching you at a bad time. My name's Alex and I'm with SolarShield. We're working in your neighborhood this week — a lot of your neighbors have been asking us to take a look at their energy bills.",
    "Totally understand. I'm not here to sell you anything today — just a quick two-minute conversation. We've helped families in this area cut their power bill by thirty to fifty percent. Would that kind of savings be worth a quick chat?",
    "That makes sense, it does take time. But here's the thing — our installs are fully covered under the neighborhood program right now, so there's no upfront cost. We handle everything start to finish.",
    "I hear you on the spouse thing. What if I left you a one-page summary you could both look at tonight? No pressure, no follow-up call unless you want one.",
    "Completely fair. Last thing I'll say — we back every install with a twenty-five year guarantee. If anything goes wrong, it's on us. Would it be alright if I left my card?",
    "Thank you for your time. I really appreciate it. Have a great afternoon.",
]


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _make_silent_wav(duration_ms: int = 500, sample_rate: int = 16000) -> bytes:
    """Generate a silent PCM WAV chunk to simulate audio input."""
    num_samples = int(sample_rate * duration_ms / 1000)
    pcm = bytes(num_samples * 2)  # 16-bit silence
    # WAV header
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE", b"fmt ", 16,
        1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", data_size,
    )
    return header + pcm


@dataclass
class TurnMetrics:
    turn_index: int
    text: str
    stt_ms: float | None = None
    llm_first_token_ms: float | None = None
    llm_full_ms: float | None = None
    tts_first_chunk_ms: float | None = None
    tts_full_ms: float | None = None
    total_round_trip_ms: float | None = None
    homeowner_reply: str = ""
    error: str | None = None


@dataclass
class DrillMetrics:
    session_id: str
    scenario_name: str
    turns: list[TurnMetrics] = field(default_factory=list)
    session_start_ms: float = 0.0
    session_end_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.session_end_ms - self.session_start_ms

    def print_report(self, label: str = ""):
        tag = f"[{label}] " if label else ""
        total_ms = max(0.0, self.total_ms)
        print(f"\n{tag}── Session {self.session_id[:8]}... ({self.scenario_name}) ──")
        print(f"  Total session time: {total_ms:.0f}ms ({total_ms/1000:.1f}s)")
        print(f"  {'Turn':<6} {'STT':>8} {'LLM1st':>8} {'LLMFull':>8} {'TTS1st':>8} {'TTSFull':>8} {'RoundTrip':>10}")
        print(f"  {'─'*6} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*10}")
        for t in self.turns:
            if t.error:
                print(f"  Turn {t.turn_index+1:<3} ERROR: {t.error}")
                continue
            def fmt(v): return f"{v:.0f}ms" if v is not None else "  —"
            print(
                f"  Turn {t.turn_index+1:<3} "
                f"{fmt(t.stt_ms):>8} "
                f"{fmt(t.llm_first_token_ms):>8} "
                f"{fmt(t.llm_full_ms):>8} "
                f"{fmt(t.tts_first_chunk_ms):>8} "
                f"{fmt(t.tts_full_ms):>8} "
                f"{fmt(t.total_round_trip_ms):>10}"
            )
            if t.homeowner_reply:
                preview = t.homeowner_reply[:80].replace("\n", " ")
                print(f"         → \"{preview}{'...' if len(t.homeowner_reply) > 80 else ''}\"")

        valid = [t for t in self.turns if t.total_round_trip_ms and not t.error]
        if valid:
            avg = sum(t.total_round_trip_ms for t in valid) / len(valid)
            worst = max(t.total_round_trip_ms for t in valid)
            best = min(t.total_round_trip_ms for t in valid)
            print(f"\n  Round-trip → avg {avg:.0f}ms  best {best:.0f}ms  worst {worst:.0f}ms")
            if avg < 1500:
                print("  ✅ Latency: GOOD (< 1.5s avg)")
            elif avg < 2500:
                print("  ⚠️  Latency: ACCEPTABLE (< 2.5s avg)")
            else:
                print("  ❌ Latency: SLOW (> 2.5s avg)")

        print("\n  Turn summary")
        print(f"  {'Turn':<6} {'Status':<6} Homeowner reply preview")
        print(f"  {'─'*6} {'─'*6} {'─'*48}")
        for t in self.turns:
            status = "FAIL" if t.error else "PASS"
            preview_source = t.error or t.homeowner_reply or "(no homeowner reply captured)"
            preview = preview_source.replace("\n", " ").strip()
            if len(preview) > 96:
                preview = f"{preview[:96]}..."
            print(f"  {t.turn_index + 1:<6} {status:<6} {preview}")


class DrillClient:
    """REST + WebSocket client that drives a complete drill session."""

    def __init__(self, base_url: str, ws_url: str):
        self.base_url = base_url
        self.ws_url = ws_url

    async def _http(self, method: str, path: str, **kwargs) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await getattr(client, method)(f"{self.base_url}{path}", **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def get_or_create_test_rep(self) -> dict:
        return await self._http("get", "/rep/lookup", params={"email": "stress-test@doordrill.dev"})

    async def get_or_create_scenario(self, rep_id: str) -> dict:
        # Try to find existing scenarios — no auth headers = admin actor (auth_required=False)
        scenarios = await self._http("get", "/scenarios")
        if scenarios:
            return scenarios[0]

        # Create one if none exist — admin actor, no user_id → skips manager-self check
        return await self._http(
            "post", "/scenarios",
            json={
                "name": "Stress Test — Skeptical Homeowner",
                "description": "A skeptical homeowner who has heard pitches before. They're not hostile but they need real value to engage.",
                "industry": "Solar",
                "difficulty": 2,
                "persona": {
                    "attitude": "skeptical",
                    "patience": 3,
                    "objection_types": ["already_have_provider", "price", "need_to_think"],
                },
                "rubric": {},
                "stages": [],
                "created_by_id": rep_id,
            }
        )

    async def create_session(self, rep_id: str, scenario_id: str) -> dict:
        return await self._http(
            "post", "/rep/sessions",
            headers={"x-user-id": rep_id, "x-user-role": "rep"},
            json={"rep_id": rep_id, "scenario_id": scenario_id}
        )

    async def run_drill(self, num_turns: int = 4, skip_tts: bool = False) -> DrillMetrics:
        import websockets

        # Setup
        rep = await self.get_or_create_test_rep()
        rep_id = rep["rep_id"]
        scenario = await self.get_or_create_scenario(rep_id)
        scenario_id = scenario["id"]
        scenario_name = scenario.get("name", "Unknown")
        session = await self.create_session(rep_id, scenario_id)
        session_id = session["id"]

        metrics = DrillMetrics(session_id=session_id, scenario_name=scenario_name)
        metrics.session_start_ms = _now_ms()

        ws_uri = f"{self.ws_url}/ws/sessions/{session_id}?user_id={rep_id}&role=rep"

        try:
            async with websockets.connect(ws_uri, open_timeout=10, max_size=8_000_000) as ws:
                seq = 0
                buffered_messages: list[dict[str, Any]] = []

                async def send(event_type: str, payload: dict):
                    nonlocal seq
                    seq += 1
                    await ws.send(json.dumps({
                        "type": event_type,
                        "sequence": seq,
                        "timestamp": asyncio.get_event_loop().time(),
                        "payload": payload,
                    }))

                async def recv_message(timeout: float) -> dict | None:
                    if buffered_messages:
                        return buffered_messages.pop(0)

                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        try:
                            return json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                async def recv_until(target_type: str, timeout: float = 20.0) -> dict | None:
                    deadline = time.perf_counter() + timeout
                    while time.perf_counter() < deadline:
                        remaining = deadline - time.perf_counter()
                        if remaining <= 0:
                            break
                        try:
                            msg = await recv_message(timeout=min(1.0, remaining))
                        except asyncio.TimeoutError:
                            continue
                        except websockets.ConnectionClosed:
                            break
                        if msg is None:
                            continue
                        if msg.get("type") == target_type:
                            return msg
                    return None

                # Wait for server.session.state {state: "connected"}
                ready = await recv_until("server.session.state", timeout=10)
                if not ready:
                    metrics.turns.append(TurnMetrics(0, "", error="Never received server.session.state"))
                    return metrics

                turns_to_run = min(num_turns, len(REP_TURNS))

                for turn_idx in range(turns_to_run):
                    rep_text = REP_TURNS[turn_idx]
                    tm = TurnMetrics(turn_index=turn_idx, text=rep_text)
                    turn_start = _now_ms()
                    turn_label = f"  Turn {turn_idx + 1}:"

                    def log_progress(message: str) -> None:
                        print(f"{turn_label} {message}")

                    async def run_turn() -> None:
                        reply_parts: list[str] = []

                        def append_reply_text(msg: dict[str, Any] | None) -> None:
                            if msg is None or msg.get("type") != "server.ai.text.delta":
                                return
                            payload = msg.get("payload", {})
                            text = payload.get("delta") or payload.get("token") or ""
                            text = str(text)
                            if text:
                                reply_parts.append(text)

                        async def wait_for_turn_commit(timeout: float) -> bool:
                            log_progress("waiting for turn commit...")
                            deadline = time.perf_counter() + timeout
                            while time.perf_counter() < deadline:
                                remaining = deadline - time.perf_counter()
                                if remaining <= 0:
                                    break
                                try:
                                    msg = await recv_message(timeout=min(2.0, remaining))
                                except asyncio.TimeoutError:
                                    continue
                                except websockets.ConnectionClosed:
                                    break
                                if msg is None:
                                    continue
                                append_reply_text(msg)
                                if msg.get("type") == "server.turn.committed":
                                    return True
                            return False

                        async def wait_for_audio_or_turn_commit(timeout: float) -> tuple[dict | None, bool]:
                            deadline = time.perf_counter() + timeout
                            while time.perf_counter() < deadline:
                                remaining = deadline - time.perf_counter()
                                if remaining <= 0:
                                    break
                                try:
                                    msg = await recv_message(timeout=min(2.0, remaining))
                                except asyncio.TimeoutError:
                                    continue
                                except websockets.ConnectionClosed:
                                    break
                                if msg is None:
                                    continue
                                append_reply_text(msg)
                                msg_type = msg.get("type")
                                if msg_type == "server.ai.audio.chunk":
                                    return msg, False
                                if msg_type == "server.turn.committed":
                                    return None, True
                            return None, False

                        log_progress("sending audio...")

                        # 1. Send audio chunk (WAV bytes as base64)
                        await send("client.vad.state", {"speaking": True})
                        audio_wav = _make_silent_wav(800)
                        audio_b64 = base64.b64encode(audio_wav).decode()
                        await send("client.audio.chunk", {
                            "audio_base64": audio_b64,
                            "transcript_hint": rep_text,  # hint bypasses real STT for sim
                            "codec": "wav",
                            "sample_rate": 16000,
                        })
                        await send("client.vad.state", {"speaking": False})
                        stt_sent = _now_ms()

                        # 2. Wait for STT final transcript
                        log_progress("waiting for STT...")
                        transcript_msg = await recv_until("server.stt.final", timeout=25.0)
                        if transcript_msg:
                            tm.stt_ms = _now_ms() - stt_sent
                            log_progress(f"STT complete in {tm.stt_ms:.0f}ms")
                        else:
                            log_progress("STT timed out after 25s")

                        # 3. Wait for first LLM text delta
                        llm_start = _now_ms()
                        log_progress("waiting for first LLM token...")
                        first_token_msg = await recv_until("server.ai.text.delta", timeout=25.0)
                        if not first_token_msg:
                            log_progress("LLM first token timed out after 25s")
                            return

                        tm.llm_first_token_ms = _now_ms() - llm_start
                        log_progress(f"LLM first token in {tm.llm_first_token_ms:.0f}ms")
                        append_reply_text(first_token_msg)

                        first_audio_msg: dict[str, Any] | None = None
                        turn_committed = False

                        # Drain remaining tokens until audio starts or the turn commits.
                        log_progress("draining LLM response...")
                        llm_drain_deadline = time.perf_counter() + 10.0
                        while time.perf_counter() < llm_drain_deadline:
                            remaining = llm_drain_deadline - time.perf_counter()
                            if remaining <= 0:
                                break
                            try:
                                msg = await recv_message(timeout=min(1.5, remaining))
                            except asyncio.TimeoutError:
                                continue
                            except websockets.ConnectionClosed:
                                break
                            if msg is None:
                                continue
                            append_reply_text(msg)
                            msg_type = msg.get("type")
                            if msg_type == "server.ai.audio.chunk":
                                first_audio_msg = msg
                                break
                            if msg_type == "server.turn.committed":
                                turn_committed = True
                                break
                        tm.llm_full_ms = _now_ms() - llm_start
                        log_progress(f"LLM response complete in {tm.llm_full_ms:.0f}ms")

                        if skip_tts:
                            tm.total_round_trip_ms = _now_ms() - turn_start
                            log_progress("skip-tts enabled; ending timed measurement after LLM text")
                            if not turn_committed:
                                committed = await wait_for_turn_commit(timeout=25.0)
                                if not committed:
                                    log_progress("turn commit timed out after 25s")
                            tm.homeowner_reply = "".join(reply_parts).strip()
                            return

                        # 4. Wait for TTS audio
                        tts_start = _now_ms()
                        audio_msg = first_audio_msg
                        if audio_msg is not None:
                            tm.tts_first_chunk_ms = 0.0
                            log_progress("TTS audio already streaming")
                        elif not turn_committed:
                            log_progress("waiting for TTS audio...")
                            audio_msg, turn_committed = await wait_for_audio_or_turn_commit(timeout=25.0)
                        if audio_msg:
                            if first_audio_msg is None:
                                tm.tts_first_chunk_ms = _now_ms() - tts_start
                            log_progress(f"TTS first chunk in {tm.tts_first_chunk_ms:.0f}ms")
                        else:
                            if turn_committed:
                                log_progress("turn committed before any TTS audio chunk")
                            else:
                                log_progress("TTS timed out after 25s")

                        if not turn_committed:
                            turn_committed = await wait_for_turn_commit(timeout=25.0)
                            if not turn_committed:
                                log_progress("turn commit timed out after 25s")

                        if audio_msg and turn_committed:
                            tm.tts_full_ms = _now_ms() - tts_start
                            log_progress(f"TTS complete in {tm.tts_full_ms:.0f}ms")

                        tm.homeowner_reply = "".join(reply_parts).strip()

                    try:
                        await asyncio.wait_for(run_turn(), timeout=45.0)
                    except asyncio.TimeoutError:
                        tm.error = "Turn exceeded 45s timeout"
                        log_progress("failed: turn exceeded 45s timeout")
                    except Exception as e:
                        tm.error = str(e)
                        log_progress(f"failed: {tm.error}")

                    if tm.total_round_trip_ms is None:
                        tm.total_round_trip_ms = _now_ms() - turn_start

                    metrics.turns.append(tm)
                    await asyncio.sleep(0.3)  # brief pause between turns

                # End the session
                await send("client.session.end", {})
        finally:
            metrics.session_end_ms = _now_ms()
        return metrics


async def run_concurrent(num_sessions: int, num_turns: int, skip_tts: bool):
    client = DrillClient(BASE_URL, WS_URL)
    print(f"\n🔀 Running {num_sessions} concurrent drills with {num_turns} turns each...\n")
    start = time.perf_counter()
    results = await asyncio.gather(
        *[client.run_drill(num_turns=num_turns, skip_tts=skip_tts) for _ in range(num_sessions)],
        return_exceptions=True
    )
    elapsed = time.perf_counter() - start
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"\n[Session {i+1}] ❌ FAILED: {r}")
        else:
            r.print_report(label=f"Session {i+1}")
    print(f"\n⏱  Total wall time for {num_sessions} concurrent sessions: {elapsed:.1f}s")


async def run_provider_latency_only():
    """Quick standalone provider latency check — no WebSocket needed."""
    import httpx
    openai_key = os.getenv("OPENAI_API_KEY")
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    el_key = os.getenv("ELEVENLABS_API_KEY")
    el_voice = os.getenv("ELEVENLABS_VOICE_ID")
    el_model = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")

    print("\n── Provider Latency Benchmark ──\n")

    # OpenAI
    if openai_key:
        t = time.perf_counter()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    "max_tokens": 60,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": "You are a skeptical homeowner."},
                        {"role": "user", "content": "I'm here to talk about solar panels."},
                    ]
                }
            )
            reply = r.json()["choices"][0]["message"]["content"]
        ms = (time.perf_counter() - t) * 1000
        print(f"  OpenAI (non-stream): {ms:.0f}ms — \"{reply[:60]}...\"")
    else:
        print("  OpenAI:              skipped (OPENAI_API_KEY not set)")

    # Deepgram prerecorded transcription
    if deepgram_key:
        t = time.perf_counter()
        audio_wav = _make_silent_wav(1200)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true",
                headers={
                    "Authorization": f"Token {deepgram_key}",
                    "Content-Type": "audio/wav",
                },
                content=audio_wav,
            )
            r.raise_for_status()
            payload = r.json()
        ms = (time.perf_counter() - t) * 1000
        transcript = (
            payload.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
            .strip()
        )
        transcript_preview = transcript[:40] if transcript else "(empty transcript)"
        print(f"  Deepgram (STT):      {ms:.0f}ms — {transcript_preview}")
    else:
        print("  Deepgram:            skipped (DEEPGRAM_API_KEY not set)")

    # ElevenLabs TTS
    if el_key and el_voice:
        t = time.perf_counter()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{el_voice}",
                headers={"xi-api-key": el_key, "Content-Type": "application/json"},
                json={"text": "I already have someone for that, sorry.", "model_id": el_model,
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
            )
        ms = (time.perf_counter() - t) * 1000
        kb = len(r.content) / 1024
        print(f"  ElevenLabs (TTS):    {ms:.0f}ms — {kb:.1f} KB audio")
    else:
        print("  ElevenLabs:          skipped (ELEVENLABS_API_KEY / VOICE_ID not set)")

    print()


async def run_latency_only():
    await run_provider_latency_only()


async def check_server():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{BASE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


async def main():
    parser = argparse.ArgumentParser(description="DoorDrill stress test")
    parser.add_argument("--turns", type=int, default=4, help="Rep turns per drill (default: 4)")
    parser.add_argument("--concurrent", type=int, default=1, help="Concurrent sessions (default: 1)")
    parser.add_argument(
        "--skip-tts",
        action="store_true",
        help="Stop turn timing after the LLM text response finishes, but still wait for server.turn.committed",
    )
    parser.add_argument("--latency-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--provider-latency-only",
        action="store_true",
        help="Benchmark raw OpenAI, Deepgram, and ElevenLabs response times",
    )
    args = parser.parse_args()

    if args.latency_only or args.provider_latency_only:
        await run_provider_latency_only()
        return

    server_up = await check_server()
    if not server_up:
        print(f"""
❌  Backend server is not running at {BASE_URL}

Start it first:
  cd backend
  uvicorn app.main:app --reload --port 8000
""")
        return

    print(f"✅  Server is up at {BASE_URL}")

    if args.concurrent > 1:
        await run_concurrent(args.concurrent, args.turns, args.skip_tts)
    else:
        client = DrillClient(BASE_URL, WS_URL)
        print(f"\n🎯 Running single drill ({args.turns} turns)...\n")
        metrics = await client.run_drill(num_turns=args.turns, skip_tts=args.skip_tts)
        metrics.print_report()

    print("\nDone.\n")


if __name__ == "__main__":
    asyncio.run(main())
