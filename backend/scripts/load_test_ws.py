#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import websockets


@dataclass
class WorkerResult:
    session_id: str | None
    first_audio_ms: float | None
    turn_committed: bool
    replay_ok: bool
    ok: bool
    error: str | None = None


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
) -> str:
    assignment_resp = await client.post(
        "/manager/assignments",
        json={
            "scenario_id": scenario_id,
            "rep_id": rep_id,
            "assigned_by": manager_id,
            "retry_policy": {"max_attempts": 1},
        },
        headers={"x-user-id": manager_id, "x-user-role": "manager"},
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
        headers={"x-user-id": rep_id, "x-user-role": "rep"},
    )
    session_resp.raise_for_status()
    return session_resp.json()["id"]


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
) -> WorkerResult:
    try:
        async with httpx.AsyncClient(base_url=api_base, timeout=15.0) as client:
            session_id = await create_session(
                client,
                manager_id=manager_id,
                rep_id=rep_id,
                scenario_id=scenario_id,
            )

        ws_url = f"{ws_base}/ws/sessions/{session_id}"
        async with websockets.connect(ws_url, max_size=2_000_000) as ws:
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
            turn_committed = False
            barge_in_sent = False
            for _ in range(200):
                msg = json.loads(await ws.recv())
                if msg.get("type") == "server.ai.audio.chunk" and first_audio_ms is None:
                    first_audio_ms = (time.perf_counter() - start) * 1000
                if trigger_barge_in and first_audio_ms is not None and not barge_in_sent:
                    await ws.send(json.dumps({"type": "client.vad.state", "sequence": 2, "payload": {"speaking": True}}))
                    barge_in_sent = True
                if msg.get("type") == "server.turn.committed":
                    turn_committed = True
                    break

            await ws.send(json.dumps({"type": "client.session.end", "sequence": 3, "payload": {}}))

        replay_ok = True
        if verify_replay:
            async with httpx.AsyncClient(base_url=api_base, timeout=15.0) as client:
                replay_resp = await client.get(
                    f"/manager/sessions/{session_id}/replay",
                    headers={"x-user-id": manager_id, "x-user-role": "manager"},
                )
                replay_resp.raise_for_status()
                replay = replay_resp.json()
                turn_count = int((replay.get("transport_metrics") or {}).get("turn_count") or 0)
                replay_ok = turn_count > 0

        ok = first_audio_ms is not None and turn_committed and replay_ok
        return WorkerResult(
            session_id=session_id,
            first_audio_ms=first_audio_ms,
            turn_committed=turn_committed,
            replay_ok=replay_ok,
            ok=ok,
            error=None if ok else "missing_first_audio_or_commit_or_replay",
        )
    except Exception as exc:  # pragma: no cover - load harness runtime
        return WorkerResult(
            session_id=None,
            first_audio_ms=None,
            turn_committed=False,
            replay_ok=False,
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
        )
        for i in range(concurrency)
    ]

    results = await asyncio.gather(*jobs)
    ok_results = [r for r in results if r.ok and r.first_audio_ms is not None]
    errors = [r for r in results if not r.ok]
    committed = [r for r in results if r.turn_committed]
    replay_ok = [r for r in results if r.replay_ok]

    latencies = [r.first_audio_ms for r in ok_results if r.first_audio_ms is not None]
    latencies.sort()

    p50 = percentile(latencies, 0.50) if latencies else 0.0
    p95 = percentile(latencies, 0.95) if latencies else 0.0
    p99 = percentile(latencies, 0.99) if latencies else 0.0
    avg = statistics.mean(latencies) if latencies else 0.0
    success_rate = (len(ok_results) / len(results)) if results else 0.0
    slo_pass = (
        success_rate >= args.min_success_rate
        and (not latencies or (p50 <= args.slo_p50_ms and p95 <= args.slo_p95_ms))
    )

    print(f"workers={concurrency}")
    print(f"success={len(ok_results)} errors={len(errors)}")
    print(f"turn_committed={len(committed)} replay_verified={len(replay_ok)}")

    if latencies:
        print(f"first_audio_ms_avg={avg:.1f}")
        print(f"first_audio_ms_p50={p50:.1f}")
        print(f"first_audio_ms_p95={p95:.1f}")
        print(f"first_audio_ms_p99={p99:.1f}")
        print(f"first_audio_ms_max={max(latencies):.1f}")

    print(f"slo_target_p50_ms={args.slo_p50_ms:.1f} slo_target_p95_ms={args.slo_p95_ms:.1f}")
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
        "success_rate": round(success_rate, 4),
        "first_audio_ms_avg": round(avg, 2),
        "first_audio_ms_p50": round(p50, 2),
        "first_audio_ms_p95": round(p95, 2),
        "first_audio_ms_p99": round(p99, 2),
        "first_audio_ms_max": round(max(latencies), 2) if latencies else 0.0,
        "slo_target_p50_ms": args.slo_p50_ms,
        "slo_target_p95_ms": args.slo_p95_ms,
        "slo_pass": slo_pass,
        "errors": [e.error for e in errors[:10]],
    }


async def run_load(args: argparse.Namespace) -> int:
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
            "min_success_rate": args.min_success_rate,
        },
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
    parser.add_argument("--min-success-rate", type=float, default=0.99, help="Minimum acceptable success rate per stage")
    parser.add_argument("--verify-replay", action="store_true", help="Verify replay turn capture after each worker run")
    parser.add_argument("--trigger-barge-in", action="store_true", help="Send a VAD barge-in during AI audio")
    parser.add_argument("--report-json", default="", help="Write stage results to JSON report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(run_load(args))


if __name__ == "__main__":
    raise SystemExit(main())
