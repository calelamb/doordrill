from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.api.manager as manager_api
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.user import User
from app.models.types import AssignmentStatus, SessionStatus, UserRole
from app.services.notification_service import NotificationService
from app.services.session_postprocess_service import SessionPostprocessService
from app.tasks.celery_app import get_celery_app
from tests.transcript_pipeline_helpers import create_assignment_and_session


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _create_assignment(client, seed_org: dict[str, str], *, due_at: datetime | None = None) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "due_at": due_at.isoformat() if due_at else None,
            "retry_policy": {"max_attempts": 2},
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert response.status_code == 200
    return response.json()


def _run_session(client, seed_org: dict[str, str], assignment_id: str) -> str:
    session_resp = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {
                    "transcript_hint": "I can lower your monthly rate and get the service started today.",
                    "codec": "opus",
                },
            }
        )
        for _ in range(80):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


@pytest.mark.asyncio
async def test_grade_postprocess_triggers_score_ready_notification(seed_org, monkeypatch):
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        service = SessionPostprocessService()
        captured: dict[str, object] = {}

        async def fake_grade(inner_db, session_id: str):
            scorecard = Scorecard(
                session_id=session_id,
                overall_score=8.1,
                category_scores={},
                highlights=[],
                ai_summary="graded",
                evidence_turn_ids=[],
                weakness_tags=[],
            )
            inner_db.add(scorecard)
            inner_db.commit()
            inner_db.refresh(scorecard)
            return scorecard

        async def fake_notify(inner_db, *, rep_id: str, session_id: str, scenario_name: str, overall_score: float):
            captured["rep_id"] = rep_id
            captured["session_id"] = session_id
            captured["scenario_name"] = scenario_name
            captured["overall_score"] = overall_score
            return None

        monkeypatch.setattr(service.grading_service, "grade_session", fake_grade)
        monkeypatch.setattr(service.turn_enrichment_service, "enrich_session", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(service.adaptive_training_service, "write_recommendation_outcome", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(service.warehouse_etl_service, "write_session", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(service.warehouse_etl_service, "refresh_predictive_aggregates", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(service.notification_service, "notify_rep_score_ready", fake_notify)

        result = await service.run_task_inline(db, session_id=session_id, task_type="grade")

        assert result["status"] == "completed"
        assert captured == {
            "rep_id": seed_org["rep_id"],
            "session_id": session_id,
            "scenario_name": "Skeptical Homeowner",
            "overall_score": 8.1,
        }
    finally:
        db.close()


def test_assignment_creation_triggers_rep_notification(client, seed_org, monkeypatch):
    due_at = datetime(2026, 3, 10, 17, 0, tzinfo=timezone.utc)
    captured: dict[str, object] = {}

    async def fake_notify(_db, *, rep_id: str, assignment_id: str, scenario_name: str, due_at):
        captured["rep_id"] = rep_id
        captured["assignment_id"] = assignment_id
        captured["scenario_name"] = scenario_name
        captured["due_at"] = due_at
        return None

    monkeypatch.setattr(manager_api.notification_service, "notify_rep_assignment_created", fake_notify)

    assignment = _create_assignment(client, seed_org, due_at=due_at)

    assert captured == {
        "rep_id": seed_org["rep_id"],
        "assignment_id": assignment["id"],
        "scenario_name": "Skeptical Homeowner",
        "due_at": _naive_utc(due_at),
    }


def test_visible_coaching_note_triggers_rep_notification(client, seed_org, monkeypatch):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])
    replay = client.get(f"/manager/sessions/{session_id}/replay").json()
    scorecard_id = replay["scorecard"]["id"]
    captured: dict[str, object] = {}

    async def fake_notify(_db, *, rep_id: str, session_id: str, manager_name: str, note_preview: str):
        captured["rep_id"] = rep_id
        captured["session_id"] = session_id
        captured["manager_name"] = manager_name
        captured["note_preview"] = note_preview
        return None

    monkeypatch.setattr(manager_api.notification_service, "notify_rep_coaching_note", fake_notify)

    created = client.post(
        f"/manager/scorecards/{scorecard_id}/coaching-notes",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        json={
            "note": "Slow down after the first objection and confirm understanding.",
            "visible_to_rep": True,
            "weakness_tags": ["pace"],
        },
    )

    assert created.status_code == 200
    assert captured == {
        "rep_id": seed_org["rep_id"],
        "session_id": session_id,
        "manager_name": "Mia Manager",
        "note_preview": "Slow down after the first objection and confirm understanding.",
    }


def test_hidden_coaching_note_does_not_trigger_rep_notification(client, seed_org, monkeypatch):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])
    replay = client.get(f"/manager/sessions/{session_id}/replay").json()
    scorecard_id = replay["scorecard"]["id"]
    called = False

    async def fake_notify(*_args, **_kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(manager_api.notification_service, "notify_rep_coaching_note", fake_notify)

    created = client.post(
        f"/manager/scorecards/{scorecard_id}/coaching-notes",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        json={
            "note": "Keep this private for the next one-on-one.",
            "visible_to_rep": False,
            "weakness_tags": ["timing"],
        },
    )

    assert created.status_code == 200
    assert called is False


@pytest.mark.asyncio
async def test_due_soon_reminders_mark_assignments_and_are_idempotent(seed_org, monkeypatch):
    db = SessionLocal()
    try:
        now = datetime(2026, 3, 9, 18, 0, tzinfo=timezone.utc)
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            due_at=now + timedelta(hours=24),
            status=AssignmentStatus.ASSIGNED,
            retry_policy={},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        service = NotificationService()
        calls: list[dict[str, object]] = []

        async def fake_get_active_tokens(_db, *, user_id: str):
            return [object()] if user_id == seed_org["rep_id"] else []

        async def fake_notify(_db, *, rep_id: str, assignment_id: str, scenario_name: str, due_at: datetime):
            calls.append(
                {
                    "rep_id": rep_id,
                    "assignment_id": assignment_id,
                    "scenario_name": scenario_name,
                    "due_at": due_at,
                }
            )
            return None

        monkeypatch.setattr(service, "_get_active_tokens", fake_get_active_tokens)
        monkeypatch.setattr(service, "notify_rep_assignment_due_soon", fake_notify)

        first = await service.send_assignment_due_soon_reminders(db, now=now)
        db.refresh(assignment)
        second = await service.send_assignment_due_soon_reminders(db, now=now)

        assert first["notified_count"] == 1
        assert first["notified_assignment_ids"] == [assignment.id]
        assert assignment.due_soon_notified_at == _naive_utc(now)
        assert second["notified_count"] == 0
        assert calls == [
            {
                "rep_id": seed_org["rep_id"],
                "assignment_id": assignment.id,
                "scenario_name": "Skeptical Homeowner",
                "due_at": _naive_utc(now + timedelta(hours=24)),
            }
        ]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_streak_nudges_only_target_matching_inactivity_windows(seed_org, monkeypatch):
    db = SessionLocal()
    try:
        now = datetime(2026, 3, 9, 18, 0, tzinfo=timezone.utc)
        team_id = db.scalar(select(User.team_id).where(User.id == seed_org["rep_id"]))
        quiet_rep = User(
            org_id=seed_org["org_id"],
            team_id=team_id,
            role=UserRole.REP,
            name="Quiet Quinn",
            email="quiet.quinn@example.com",
        )
        recent_rep = User(
            org_id=seed_org["org_id"],
            team_id=team_id,
            role=UserRole.REP,
            name="Recent Riley",
            email="recent.riley@example.com",
        )
        db.add_all([quiet_rep, recent_rep])
        db.commit()
        db.refresh(quiet_rep)
        db.refresh(recent_rep)

        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={},
        )
        recent_assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=recent_rep.id,
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={},
        )
        db.add_all([assignment, recent_assignment])
        db.commit()
        db.refresh(assignment)
        db.refresh(recent_assignment)

        stale_session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            started_at=now - timedelta(days=2, hours=1),
            ended_at=now - timedelta(days=2, hours=1) + timedelta(minutes=5),
            duration_seconds=300,
            status=SessionStatus.GRADED,
        )
        recent_session = DrillSession(
            assignment_id=recent_assignment.id,
            rep_id=recent_rep.id,
            scenario_id=seed_org["scenario_id"],
            started_at=now - timedelta(hours=12),
            ended_at=now - timedelta(hours=12) + timedelta(minutes=5),
            duration_seconds=300,
            status=SessionStatus.GRADED,
        )
        db.add_all([stale_session, recent_session])
        db.commit()
        db.refresh(stale_session)
        db.refresh(recent_session)

        db.add(
            Scorecard(
                session_id=stale_session.id,
                overall_score=6.4,
                category_scores={},
                highlights=[],
                ai_summary="stale",
                evidence_turn_ids=[],
                weakness_tags=[],
            )
        )
        db.add(
            Scorecard(
                session_id=recent_session.id,
                overall_score=8.9,
                category_scores={},
                highlights=[],
                ai_summary="recent",
                evidence_turn_ids=[],
                weakness_tags=[],
            )
        )
        db.commit()

        service = NotificationService()
        calls: list[dict[str, object]] = []

        async def fake_notify(_db, *, rep_id: str, days_inactive: int, last_score: float | None):
            calls.append(
                {
                    "rep_id": rep_id,
                    "days_inactive": days_inactive,
                    "last_score": last_score,
                }
            )
            return None

        monkeypatch.setattr(service, "notify_rep_streak_nudge", fake_notify)

        result = await service.send_streak_nudges(db, now=now)

        assert result["nudged_count"] == 1
        assert calls == [
            {
                "rep_id": seed_org["rep_id"],
                "days_inactive": 2,
                "last_score": 6.4,
            }
        ]
    finally:
        db.close()


def test_celery_beat_schedule_includes_notification_reminders():
    settings = get_settings()
    original_use_celery = settings.use_celery
    try:
        settings.use_celery = True
        get_celery_app.cache_clear()
        celery_app = get_celery_app()
        if celery_app is None:
            pytest.skip("Celery is not available in this runtime")
        schedule = celery_app.conf.beat_schedule
        assert "assignment-due-soon-reminders" in schedule
        assert "streak-nudges-daily" in schedule
        assert schedule["assignment-due-soon-reminders"]["task"] == "notifications.assignment_due_soon"
        assert schedule["streak-nudges-daily"]["task"] == "notifications.streak_nudges"
    finally:
        settings.use_celery = original_use_celery
        get_celery_app.cache_clear()
