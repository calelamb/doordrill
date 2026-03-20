from __future__ import annotations

import argparse

import pytest

import scripts.load_test_ws as load_test_ws


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "api_base": "http://127.0.0.1:8000",
        "ws_base": "ws://127.0.0.1:8000",
        "manager_id": "manager-1",
        "rep_id": "rep-1",
        "scenario_id": "scenario-1",
        "concurrency": 2,
        "ramp": "",
        "ramp_wait_ms": 0,
        "slo_p50_ms": 900.0,
        "slo_p95_ms": 1400.0,
        "barge_slo_ms": 150.0,
        "min_success_rate": 0.99,
        "verify_replay": True,
        "trigger_barge_in": False,
        "min_realism_score": None,
        "min_transcript_confidence": None,
        "max_forbidden_phrase_hits": None,
        "report_json": "",
        "auth_required": False,
        "manager_email": "",
        "manager_password": "",
        "rep_email": "",
        "rep_password": "",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_count_forbidden_phrase_hits_counts_ai_turns_only():
    turns = [
        {"speaker": "rep", "text": "Could you clarify what you mean?"},
        {"speaker": "ai", "text": "I'm not sure what else to say right now."},
        {"speaker": "ai", "text": "Could you clarify what you mean?"},
    ]

    assert load_test_ws.count_forbidden_phrase_hits(turns) == 2


@pytest.mark.asyncio
async def test_run_stage_reports_quality_metrics_and_passes_thresholds(monkeypatch):
    results = [
        load_test_ws.WorkerResult(
            session_id="session-1",
            first_audio_ms=110.0,
            barge_ack_ms=None,
            barge_server_latency_ms=None,
            realism_score=7.8,
            transcript_confidence=0.96,
            forbidden_phrase_hits=0,
            turn_committed=True,
            replay_ok=True,
            link_ok=True,
            ok=True,
        ),
        load_test_ws.WorkerResult(
            session_id="session-2",
            first_audio_ms=125.0,
            barge_ack_ms=None,
            barge_server_latency_ms=None,
            realism_score=8.1,
            transcript_confidence=0.94,
            forbidden_phrase_hits=0,
            turn_committed=True,
            replay_ok=True,
            link_ok=True,
            ok=True,
        ),
    ]

    async def fake_run_worker(worker_id: int, **_: object) -> load_test_ws.WorkerResult:
        return results[worker_id]

    monkeypatch.setattr(load_test_ws, "run_worker", fake_run_worker)

    stage = await load_test_ws.run_stage(
        _args(min_realism_score=7.0, min_transcript_confidence=0.90, max_forbidden_phrase_hits=0),
        concurrency=2,
    )

    assert stage["quality_sample_count"] == 2
    assert stage["realism_score_avg"] == pytest.approx(7.95, abs=1e-3)
    assert stage["transcript_confidence_avg"] == pytest.approx(0.95, abs=1e-4)
    assert stage["forbidden_phrase_hits_total"] == 0
    assert stage["realism_slo_pass"] is True
    assert stage["transcript_confidence_slo_pass"] is True
    assert stage["forbidden_phrase_slo_pass"] is True
    assert stage["quality_slo_pass"] is True
    assert stage["slo_pass"] is True


@pytest.mark.asyncio
async def test_run_stage_fails_when_forbidden_phrase_hits_exceed_threshold(monkeypatch):
    results = [
        load_test_ws.WorkerResult(
            session_id="session-1",
            first_audio_ms=110.0,
            barge_ack_ms=None,
            barge_server_latency_ms=None,
            realism_score=7.4,
            transcript_confidence=0.92,
            forbidden_phrase_hits=1,
            turn_committed=True,
            replay_ok=True,
            link_ok=True,
            ok=True,
        )
    ]

    async def fake_run_worker(worker_id: int, **_: object) -> load_test_ws.WorkerResult:
        return results[worker_id]

    monkeypatch.setattr(load_test_ws, "run_worker", fake_run_worker)

    stage = await load_test_ws.run_stage(
        _args(min_realism_score=7.0, min_transcript_confidence=0.85, max_forbidden_phrase_hits=0),
        concurrency=1,
    )

    assert stage["forbidden_phrase_hits_total"] == 1
    assert stage["forbidden_phrase_slo_pass"] is False
    assert stage["quality_slo_pass"] is False
    assert stage["slo_pass"] is False
