#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass

import httpx
import websockets


@dataclass
class WorkerResult:
    session_id: str | None
    first_audio_ms: float | None
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
            for _ in range(200):
                msg = json.loads(await ws.recv())
                if msg.get("type") == "server.ai.audio.chunk" and first_audio_ms is None:
                    first_audio_ms = (time.perf_counter() - start) * 1000
                if msg.get("type") == "server.turn.committed":
                    break

            await ws.send(json.dumps({"type": "client.session.end", "sequence": 2, "payload": {}}))

        return WorkerResult(session_id=session_id, first_audio_ms=first_audio_ms, ok=first_audio_ms is not None)
    except Exception as exc:  # pragma: no cover - load harness runtime
        return WorkerResult(session_id=None, first_audio_ms=None, ok=False, error=str(exc))


async def run_load(args: argparse.Namespace) -> int:
    jobs = [
        run_worker(
            i,
            api_base=args.api_base,
            ws_base=args.ws_base,
            manager_id=args.manager_id,
            rep_id=args.rep_id,
            scenario_id=args.scenario_id,
        )
        for i in range(args.concurrency)
    ]

    results = await asyncio.gather(*jobs)
    ok_results = [r for r in results if r.ok and r.first_audio_ms is not None]
    errors = [r for r in results if not r.ok]

    latencies = [r.first_audio_ms for r in ok_results if r.first_audio_ms is not None]
    latencies.sort()

    print(f"workers={args.concurrency}")
    print(f"success={len(ok_results)} errors={len(errors)}")

    if latencies:
        print(f"first_audio_ms_avg={statistics.mean(latencies):.1f}")
        print(f"first_audio_ms_p50={percentile(latencies, 0.50):.1f}")
        print(f"first_audio_ms_p95={percentile(latencies, 0.95):.1f}")
        print(f"first_audio_ms_max={max(latencies):.1f}")

    if errors:
        print("errors_sample=")
        for err in errors[:5]:
            print(f"  - {err.error}")

    return 0 if not errors else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DoorDrill realtime WS load harness")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="FastAPI HTTP base URL")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8000", help="FastAPI WebSocket base URL")
    parser.add_argument("--manager-id", required=True, help="Manager user ID used for assignment creation")
    parser.add_argument("--rep-id", required=True, help="Rep user ID used for session creation")
    parser.add_argument("--scenario-id", required=True, help="Scenario ID used for assignments/sessions")
    parser.add_argument("--concurrency", type=int, default=50, help="Concurrent websocket sessions to run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(run_load(args))


if __name__ == "__main__":
    raise SystemExit(main())
