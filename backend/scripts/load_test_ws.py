#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import time

import httpx
import websockets


@dataclass
class WorkerResult:
    session_id: str | None
    first_audio_ms: float | None
    barge_ack_ms: float | None
    barge_server_latency_ms: float | None
    realism_score: float | None
    transcript_confidence: float | None
    forbidden_phrase_hits: int
    turn_committed: bool
    replay_ok: bool
    link_ok: bool
    ok: bool
    error: str | None = None


FORBIDDEN_HOMEOWNER_PHRASES = (
    "i'm not sure what else to say",
    "i don't know how to respond",
    "could you clarify what you mean",
)


def _normalize_text(text: str | None) -> str:
    normalized = " ".join(str(text or "").lower().replace("’", "'").split()).strip()
    return re.sub(r"\s+", " ", normalized)


def count_forbidden_phrase_hits(transcript_turns: list[dict] | None) -> int:
    hits = 0
    for turn in transcript_turns or []:
        if str(turn.get("speaker") or "").lower() != "ai":
            continue
        text = _normalize_text(turn.get("text"))
        if not text:
            continue
        hits += sum(1 for phrase in FORBIDDEN_HOMEOWNER_PHRASES if phrase in text)
    return hits


def _coerce_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _quality_thresholds_requested(args: argparse.Namespace) -> bool:
    return any(
        value is not None
        for value in (
            args.min_realism_score,
            args.min_transcript_confidence,
            args.max_forbidden_phrase_hits,
        )
    )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


async def create_session(
    client: httpx.AsyncClient,
    *,
    manager_id: str,
    rep_id: str,
    scenario_id: str,
    manager_headers: dict[str, str] | None = None,
    rep_headers: dict[str, str] | None = None,
) -> str:
    assignment_resp = await client.post(
        "/manager/assignments",
        json={
            "scenario_id": scenario_id,
            "rep_id": rep_id,
            "assigned_by": manager_id,
            "retry_policy": {"max_attempts": 1},
        },
        headers=manager_headers or {"x-user-id": manager_id, "x-user-role": "manager"},
    )
    assignment_resp.raise_for_status()
    assignment_id = assignment_resp.json()["id"]

    session_resp = await client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": rep_id,
            "scenario_id": scenario_id,
        },
        headers=rep_headers or {"x-user-id": rep_id, "x-user-role": "rep"},
    )
    session_resp.raise_for_status()
    return session_resp.json()["id"]


async def login_for_token(client: httpx.AsyncClient, *, email: str, password: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


async def run_worker(
    worker_id: int,
    *,
    api_base: str,
    ws_base: str,
    manager_id: str,
    rep_id: str,
    scenario_id: str,
    verify_replay: bool,
    trigger_barge_in: bool,
    manager_headers: dict[str, str] | None = None,
    rep_headers: dict[str, str] | None = None,
    rep_access_token: str | None = None,
) -> WorkerResult:
    try:
        async with httpx.AsyncClient(base_url=api_base, timeout=15.0) as client:
            session_id = await create_session(
                client,
                manager_id=manager_id,
                rep_id=rep_id,
                scenario_id=scenario_id,
                manager_headers=manager_headers,
                rep_headers=rep_headers,
            )

        ws_url = f"{ws_base}/ws/sessions/{session_id}"
        if rep_access_token:
            separator = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{separator}access_token={rep_access_token}"
        committed_rep_turn_id = None
        committed_ai_turn_id = None

        ws_headers = {}
        if rep_headers and "Authorization" in rep_headers:
            ws_headers["Authorization"] = rep_headers["Authorization"]

        async with websockets.connect(ws_url, max_size=2_000_000, additional_headers=ws_headers or None) as ws:
            await ws.recv()  # connected state

            start = time.perf_counter()
            await ws.send(
                json.dumps(
                    {
                        "type": "client.audio.chunk",
                        "sequence": 1,
                        "payload": {
                            "transcript_hint": f"Hi this is worker {worker_id}, we can lower your price today.",
                            "codec": "opus",
                        },
                    }
                )
            )

            first_audio_ms: float | None = None
            barge_ack_ms: float | None = None
            barge_server_latency_ms: float | None = None
            turn_committed = False
            barge_in_sent = False
            barge_sent_at: float | None = None

            for _ in range(250):
                msg = json.loads(await ws.recv())
                msg_type = msg.get("type")

                if msg_type == "server.ai.audio.chunk" and first_audio_ms is None:
                    first_audio_ms = (time.perf_counter() - start) * 1000

                if trigger_barge_in and first_audio_ms is not None and not barge_in_sent:
                    barge_sent_at = time.perf_counter()
                    await ws.send(json.dumps({"type": "client.vad.state", "sequence": 2, "payload": {"speaking": True}}))
                    barge_in_sent = True

                if msg_type == "server.session.state" and barge_sent_at is not None and barge_ack_ms is None:
                    payload = msg.get("payload") or {}
                    if payload.get("state") == "barge_in_detected":
                        barge_ack_ms = (time.perf_counter() - barge_sent_at) * 1000
                        barge_server_latency_ms = float(payload.get("latency_ms") or 0)

                if msg_type == "server.turn.committed":
                    payload = msg.get("payload") or {}
                    committed_rep_turn_id = payload.get("rep_turn_id")
                    committed_ai_turn_id = payload.get("ai_turn_id")
                    turn_committed = True
                    break

            await ws.send(json.dumps({"type": "client.session.end", "sequence": 3, "payload": {}}))

        replay_ok = True
        link_ok = True
        realism_score: float | None = None
        transcript_confidence: float | None = None
        forbidden_phrase_hits = 0
        if verify_replay:
            async with httpx.AsyncClient(base_url=api_base, timeout=15.0) as client:
                replay_resp = await client.get(
                    f"/manager/sessions/{session_id}/replay",
                    headers=manager_headers or {"x-user-id": manager_id, "x-user-role": "manager"},
                )
                replay_resp.raise_for_status()
                replay = replay_resp.json()

            turn_count = int((replay.get("transport_metrics") or {}).get("turn_count") or 0)
            replay_ok = turn_count > 0

            turn_ids = {turn.get("turn_id") for turn in replay.get("transcript_turns") or []}
            link_ok = bool(committed_rep_turn_id and committed_ai_turn_id)
            if link_ok:
                link_ok = committed_rep_turn_id in turn_ids and committed_ai_turn_id in turn_ids

            if trigger_barge_in:
                interruptions = replay.get("interruption_timeline") or []
                link_ok = link_ok and len(interruptions) > 0

            realism_score = _coerce_float((replay.get("conversational_realism") or {}).get("average_score"))
            transcript_confidence = _coerce_float((replay.get("transport_metrics") or {}).get("average_transcript_confidence"))
            forbidden_phrase_hits = count_forbidden_phrase_hits(replay.get("transcript_turns") or [])

        ok = (
            first_audio_ms is not None
            and turn_committed
            and replay_ok
            and link_ok
            and (not trigger_barge_in or barge_ack_ms is not None)
        )
        return WorkerResult(
            session_id=session_id,
            first_audio_ms=first_audio_ms,
            barge_ack_ms=barge_ack_ms,
            barge_server_latency_ms=barge_server_latency_ms,
            realism_score=realism_score,
            transcript_confidence=transcript_confidence,
            forbidden_phrase_hits=forbidden_phrase_hits,
            turn_committed=turn_committed,
            replay_ok=replay_ok,
            link_ok=link_ok,
            ok=ok,
            error=None if ok else "missing_latency_turn_replay_or_link_integrity",
        )
    except Exception as exc:  # pragma: no cover - load harness runtime
        return WorkerResult(
            session_id=None,
            first_audio_ms=None,
            barge_ack_ms=None,
            barge_server_latency_ms=None,
            realism_score=None,
            transcript_confidence=None,
            forbidden_phrase_hits=0,
            turn_committed=False,
            replay_ok=False,
            link_ok=False,
            ok=False,
            error=str(exc),
        )


def parse_ramp(raw: str | None, fallback: int) -> list[int]:
    if not raw:
        return [fallback]
    values: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        values.append(int(token))
    if not values:
        return [fallback]
    return values


async def run_stage(args: argparse.Namespace, concurrency: int) -> dict:
    manager_headers = {"x-user-id": args.manager_id, "x-user-role": "manager"}
    rep_headers = {"x-user-id": args.rep_id, "x-user-role": "rep"}
    rep_access_token = None

    if args.auth_required:
        if not all([args.manager_email, args.manager_password, args.rep_email, args.rep_password]):
            raise ValueError("JWT auth load runs require manager/rep email and password arguments")
        async with httpx.AsyncClient(base_url=args.api_base, timeout=15.0) as client:
            manager_token = await login_for_token(client, email=args.manager_email, password=args.manager_password)
            rep_access_token = await login_for_token(client, email=args.rep_email, password=args.rep_password)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}
        rep_headers = {"Authorization": f"Bearer {rep_access_token}"}

    jobs = [
        run_worker(
            i,
            api_base=args.api_base,
            ws_base=args.ws_base,
            manager_id=args.manager_id,
            rep_id=args.rep_id,
            scenario_id=args.scenario_id,
            verify_replay=args.verify_replay,
            trigger_barge_in=args.trigger_barge_in,
            manager_headers=manager_headers,
            rep_headers=rep_headers,
            rep_access_token=rep_access_token,
        )
        for i in range(concurrency)
    ]

    results = await asyncio.gather(*jobs)
    ok_results = [r for r in results if r.ok and r.first_audio_ms is not None]
    errors = [r for r in results if not r.ok]
    committed = [r for r in results if r.turn_committed]
    replay_ok = [r for r in results if r.replay_ok]
    linked = [r for r in results if r.link_ok]

    latencies = [r.first_audio_ms for r in ok_results if r.first_audio_ms is not None]
    latencies.sort()
    p50 = percentile(latencies, 0.50) if latencies else 0.0
    p95 = percentile(latencies, 0.95) if latencies else 0.0
    p99 = percentile(latencies, 0.99) if latencies else 0.0
    avg = statistics.mean(latencies) if latencies else 0.0

    barge_ack = [r.barge_ack_ms for r in ok_results if r.barge_ack_ms is not None]
    barge_ack.sort()
    barge_server = [r.barge_server_latency_ms for r in ok_results if r.barge_server_latency_ms is not None]
    barge_server.sort()
    barge_p95 = percentile(barge_ack, 0.95) if barge_ack else 0.0
    barge_server_p95 = percentile(barge_server, 0.95) if barge_server else 0.0

    quality_results = [r for r in results if r.replay_ok]
    realism_scores = [r.realism_score for r in quality_results if r.realism_score is not None]
    transcript_confidences = [r.transcript_confidence for r in quality_results if r.transcript_confidence is not None]
    forbidden_phrase_hits_total = sum(r.forbidden_phrase_hits for r in quality_results)
    realism_avg = statistics.mean(realism_scores) if realism_scores else 0.0
    transcript_confidence_avg = statistics.mean(transcript_confidences) if transcript_confidences else 0.0

    success_rate = (len(ok_results) / len(results)) if results else 0.0
    latency_slo_pass = (not latencies) or (p50 <= args.slo_p50_ms and p95 <= args.slo_p95_ms)
    barge_slo_pass = True
    if args.trigger_barge_in:
        barge_slo_pass = bool(barge_ack) and barge_p95 <= args.barge_slo_ms

    realism_slo_pass = True
    if args.min_realism_score is not None:
        realism_slo_pass = bool(realism_scores) and realism_avg >= args.min_realism_score

    transcript_confidence_slo_pass = True
    if args.min_transcript_confidence is not None:
        transcript_confidence_slo_pass = (
            bool(transcript_confidences) and transcript_confidence_avg >= args.min_transcript_confidence
        )

    forbidden_phrase_slo_pass = True
    if args.max_forbidden_phrase_hits is not None:
        forbidden_phrase_slo_pass = forbidden_phrase_hits_total <= args.max_forbidden_phrase_hits

    quality_slo_pass = realism_slo_pass and transcript_confidence_slo_pass and forbidden_phrase_slo_pass

    slo_pass = success_rate >= args.min_success_rate and latency_slo_pass and barge_slo_pass and quality_slo_pass

    print(f"workers={concurrency}")
    print(f"success={len(ok_results)} errors={len(errors)}")
    print(
        "turn_committed="
        f"{len(committed)} replay_verified={len(replay_ok)} turn_linked={len(linked)}"
    )

    if latencies:
        print(f"first_audio_ms_avg={avg:.1f}")
        print(f"first_audio_ms_p50={p50:.1f}")
        print(f"first_audio_ms_p95={p95:.1f}")
        print(f"first_audio_ms_p99={p99:.1f}")
        print(f"first_audio_ms_max={max(latencies):.1f}")

    print(f"slo_target_p50_ms={args.slo_p50_ms:.1f} slo_target_p95_ms={args.slo_p95_ms:.1f}")
    if args.trigger_barge_in:
        print(f"barge_ack_p95_ms={barge_p95:.1f} target={args.barge_slo_ms:.1f}")
        print(f"barge_server_latency_p95_ms={barge_server_p95:.1f}")
    if realism_scores:
        print(f"realism_score_avg={realism_avg:.2f}")
    if transcript_confidences:
        print(f"transcript_confidence_avg={transcript_confidence_avg:.3f}")
    if quality_results:
        print(f"forbidden_phrase_hits_total={forbidden_phrase_hits_total}")
    print(f"success_rate={success_rate:.3f} slo_pass={slo_pass}")

    if errors:
        print("errors_sample=")
        for err in errors[:5]:
            print(f"  - {err.error}")

    return {
        "concurrency": concurrency,
        "workers": len(results),
        "success_count": len(ok_results),
        "error_count": len(errors),
        "turn_committed_count": len(committed),
        "replay_verified_count": len(replay_ok),
        "turn_link_integrity_count": len(linked),
        "success_rate": round(success_rate, 4),
        "first_audio_ms_avg": round(avg, 2),
        "first_audio_ms_p50": round(p50, 2),
        "first_audio_ms_p95": round(p95, 2),
        "first_audio_ms_p99": round(p99, 2),
        "first_audio_ms_max": round(max(latencies), 2) if latencies else 0.0,
        "barge_ack_ms_p95": round(barge_p95, 2),
        "barge_server_latency_ms_p95": round(barge_server_p95, 2),
        "barge_slo_ms": args.barge_slo_ms,
        "slo_target_p50_ms": args.slo_p50_ms,
        "slo_target_p95_ms": args.slo_p95_ms,
        "quality_sample_count": len(quality_results),
        "realism_score_avg": round(realism_avg, 3) if realism_scores else None,
        "realism_score_min": round(min(realism_scores), 3) if realism_scores else None,
        "realism_score_max": round(max(realism_scores), 3) if realism_scores else None,
        "transcript_confidence_avg": round(transcript_confidence_avg, 4) if transcript_confidences else None,
        "transcript_confidence_min": round(min(transcript_confidences), 4) if transcript_confidences else None,
        "transcript_confidence_max": round(max(transcript_confidences), 4) if transcript_confidences else None,
        "forbidden_phrase_hits_total": forbidden_phrase_hits_total,
        "min_realism_score": args.min_realism_score,
        "min_transcript_confidence": args.min_transcript_confidence,
        "max_forbidden_phrase_hits": args.max_forbidden_phrase_hits,
        "realism_slo_pass": realism_slo_pass,
        "transcript_confidence_slo_pass": transcript_confidence_slo_pass,
        "forbidden_phrase_slo_pass": forbidden_phrase_slo_pass,
        "quality_slo_pass": quality_slo_pass,
        "slo_pass": slo_pass,
        "errors": [e.error for e in errors[:10]],
    }


async def run_load(args: argparse.Namespace) -> int:
    if _quality_thresholds_requested(args) and not args.verify_replay:
        raise ValueError("--verify-replay is required when quality thresholds are enabled")

    stages = parse_ramp(args.ramp, args.concurrency)
    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "api_base": args.api_base,
        "ws_base": args.ws_base,
        "verify_replay": args.verify_replay,
        "trigger_barge_in": args.trigger_barge_in,
        "slo": {
            "p50_ms": args.slo_p50_ms,
            "p95_ms": args.slo_p95_ms,
            "barge_p95_ms": args.barge_slo_ms,
            "min_success_rate": args.min_success_rate,
            "min_realism_score": args.min_realism_score,
            "min_transcript_confidence": args.min_transcript_confidence,
            "max_forbidden_phrase_hits": args.max_forbidden_phrase_hits,
        },
        "forbidden_homeowner_phrases": list(FORBIDDEN_HOMEOWNER_PHRASES),
        "stages": [],
    }
    overall_pass = True

    for idx, concurrency in enumerate(stages):
        print(f"\n=== stage {idx + 1}/{len(stages)} concurrency={concurrency} ===")
        stage_result = await run_stage(args, concurrency)
        summary["stages"].append(stage_result)
        if not stage_result["slo_pass"]:
            overall_pass = False
        if idx < len(stages) - 1 and args.ramp_wait_ms > 0:
            await asyncio.sleep(args.ramp_wait_ms / 1000)

    summary["overall_pass"] = overall_pass
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"json_report={report_path}")

    return 0 if overall_pass else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DoorDrill realtime WS load harness")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="FastAPI HTTP base URL")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8000", help="FastAPI WebSocket base URL")
    parser.add_argument("--manager-id", required=True, help="Manager user ID used for assignment creation")
    parser.add_argument("--rep-id", required=True, help="Rep user ID used for session creation")
    parser.add_argument("--scenario-id", required=True, help="Scenario ID used for assignments/sessions")
    parser.add_argument("--concurrency", type=int, default=50, help="Concurrent websocket sessions to run")
    parser.add_argument("--ramp", default="", help="Comma-separated ramp stages, e.g. 50,100,200")
    parser.add_argument("--ramp-wait-ms", type=int, default=750, help="Delay between ramp stages in ms")
    parser.add_argument("--slo-p50-ms", type=float, default=900.0, help="First-audio p50 SLO budget in ms")
    parser.add_argument("--slo-p95-ms", type=float, default=1400.0, help="First-audio p95 SLO budget in ms")
    parser.add_argument("--barge-slo-ms", type=float, default=150.0, help="Barge-in cancel p95 latency budget in ms")
    parser.add_argument("--min-success-rate", type=float, default=0.99, help="Minimum acceptable success rate per stage")
    parser.add_argument("--verify-replay", action="store_true", help="Verify replay turn capture after each worker run")
    parser.add_argument("--trigger-barge-in", action="store_true", help="Send a VAD barge-in during AI audio")
    parser.add_argument("--min-realism-score", type=float, default=None, help="Minimum average replay realism score")
    parser.add_argument(
        "--min-transcript-confidence",
        type=float,
        default=None,
        help="Minimum average replay transcript confidence",
    )
    parser.add_argument(
        "--max-forbidden-phrase-hits",
        type=int,
        default=None,
        help="Maximum banned homeowner fallback phrase hits across replayed AI turns",
    )
    parser.add_argument("--report-json", default="", help="Write stage results to JSON report path")
    parser.add_argument("--auth-required", action="store_true", help="Authenticate REST and WS traffic with JWTs")
    parser.add_argument("--manager-email", default="", help="Manager login email for JWT-enabled runs")
    parser.add_argument("--manager-password", default="", help="Manager login password for JWT-enabled runs")
    parser.add_argument("--rep-email", default="", help="Rep login email for JWT-enabled runs")
    parser.add_argument("--rep-password", default="", help="Rep login password for JWT-enabled runs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(run_load(args))


if __name__ == "__main__":
    raise SystemExit(main())
