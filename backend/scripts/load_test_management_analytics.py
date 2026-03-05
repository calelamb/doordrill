#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import time
from typing import Any

import httpx


ENDPOINTS = [
    ("/manager/analytics", {"period": "30"}),
    ("/manager/command-center", {"period": "30"}),
    ("/manager/analytics/scenarios", {"period": "30"}),
    ("/manager/analytics/coaching", {"period": "30"}),
    ("/manager/analytics/explorer", {"period": "30", "limit": "100"}),
    ("/manager/alerts", {"period": "30"}),
    ("/manager/benchmarks", {"period": "30"}),
    ("/manager/analytics/operations", {}),
]


@dataclass
class Sample:
    endpoint: str
    latency_ms: float
    ok: bool
    status_code: int
    error: str | None = None


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def login_for_token(client: httpx.Client, *, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def run_sample(
    *,
    api_base: str,
    endpoint: str,
    params: dict[str, str],
    manager_id: str,
    headers: dict[str, str],
) -> Sample:
    started = time.perf_counter()
    try:
        with httpx.Client(base_url=api_base, timeout=20.0) as client:
            response = client.get(endpoint, params={"manager_id": manager_id, **params}, headers=headers)
            latency_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
        return Sample(endpoint=endpoint, latency_ms=latency_ms, ok=True, status_code=response.status_code)
    except Exception as exc:  # pragma: no cover - runtime harness
        return Sample(
            endpoint=endpoint,
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=False,
            status_code=getattr(getattr(exc, "response", None), "status_code", 0),
            error=str(exc),
        )


def build_report(samples: list[Sample]) -> dict[str, Any]:
    by_endpoint: dict[str, list[Sample]] = {}
    for sample in samples:
        by_endpoint.setdefault(sample.endpoint, []).append(sample)

    endpoint_reports = []
    overall_latencies = [sample.latency_ms for sample in samples if sample.ok]
    for endpoint, rows in by_endpoint.items():
        latencies = sorted(sample.latency_ms for sample in rows if sample.ok)
        errors = [sample.error for sample in rows if not sample.ok]
        endpoint_reports.append(
            {
                "endpoint": endpoint,
                "requests": len(rows),
                "success_count": len(latencies),
                "failure_count": len(errors),
                "p50_ms": round(percentile(latencies, 0.50), 2) if latencies else 0.0,
                "p95_ms": round(percentile(latencies, 0.95), 2) if latencies else 0.0,
                "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
                "errors": errors[:5],
            }
        )
    endpoint_reports.sort(key=lambda item: item["endpoint"])
    return {
        "requests": len(samples),
        "success_count": len([sample for sample in samples if sample.ok]),
        "failure_count": len([sample for sample in samples if not sample.ok]),
        "p50_ms": round(percentile(sorted(overall_latencies), 0.50), 2) if overall_latencies else 0.0,
        "p95_ms": round(percentile(sorted(overall_latencies), 0.95), 2) if overall_latencies else 0.0,
        "endpoints": endpoint_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test DoorDrill management analytics endpoints")
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--manager-id", required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-p50-ms", type=float, default=600.0)
    parser.add_argument("--max-p95-ms", type=float, default=1500.0)
    parser.add_argument("--report-json", default="")
    parser.add_argument("--auth-required", action="store_true")
    parser.add_argument("--manager-email", default="")
    parser.add_argument("--manager-password", default="")
    args = parser.parse_args()

    headers = {"x-user-id": args.manager_id, "x-user-role": "manager"}
    if args.auth_required:
        if not args.manager_email or not args.manager_password:
            raise ValueError("auth-required runs need manager email and password")
        with httpx.Client(base_url=args.api_base, timeout=20.0) as client:
            token = login_for_token(client, email=args.manager_email, password=args.manager_password)
        headers = {"Authorization": f"Bearer {token}"}

    for _ in range(max(0, args.warmup)):
        for endpoint, params in ENDPOINTS:
            sample = run_sample(
                api_base=args.api_base,
                endpoint=endpoint,
                params=params,
                manager_id=args.manager_id,
                headers=headers,
            )
            if not sample.ok:
                raise RuntimeError(f"warmup failed for {endpoint}: {sample.error}")

    samples: list[Sample] = []
    jobs = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        for _ in range(max(1, args.iterations)):
            for endpoint, params in ENDPOINTS:
                jobs.append(
                    pool.submit(
                        run_sample,
                        api_base=args.api_base,
                        endpoint=endpoint,
                        params=params,
                        manager_id=args.manager_id,
                        headers=headers,
                    )
                )
        for future in as_completed(jobs):
            samples.append(future.result())

    report = build_report(samples)
    print(json.dumps(report, indent=2))

    if args.report_json:
        path = Path(args.report_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    failing_endpoints = [
        item
        for item in report["endpoints"]
        if item["failure_count"] > 0 or item["p50_ms"] > args.max_p50_ms or item["p95_ms"] > args.max_p95_ms
    ]
    if failing_endpoints:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
