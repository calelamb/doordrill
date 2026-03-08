from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.device_token import DeviceToken
from app.models.notification_delivery import NotificationDelivery
from app.models.postprocess_run import PostprocessRun
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus
from app.services.notification_providers import ProviderSendResult
from app.services.notification_service import NotificationService
from app.services.session_postprocess_service import SessionPostprocessService


@pytest.mark.asyncio
async def test_notification_retry_sweeper_invalidates_bad_tokens(seed_org):
    db = SessionLocal()
    try:
        service = NotificationService()
        token = service.register_device_token(
            db,
            user_id=seed_org["manager_id"],
            platform="ios",
            token="ExponentPushToken[retry-invalid-token-1234567890]",
        )

        delivery = NotificationDelivery(
            session_id=None,
            manager_id=seed_org["manager_id"],
            channel="push",
            payload={
                "token_id": token.id,
                "push_token": token.token,
                "title": "DoorDrill",
                "body": "Retry this",
                "data": {"session_id": "s1"},
            },
            provider_response={},
            status="retry_scheduled",
            retries=1,
            next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(delivery)
        db.commit()

        class InvalidPushProvider:
            async def send(self, *, push_token: str, title: str, body: str, data: dict):
                return ProviderSendResult(
                    ok=False,
                    status="failed",
                    response={"provider": "test"},
                    error="token_invalid",
                    permanent_failure=True,
                    invalid_token=True,
                )

        service.push_provider = InvalidPushProvider()
        result = await service.retry_due_deliveries(db, limit=10)
        db.refresh(delivery)
        db.refresh(token)

        assert result["retried_count"] == 1
        assert delivery.status == "dead_letter"
        assert delivery.next_retry_at is None
        assert token.provider == "expo"
        assert token.status == "invalid"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_notification_retry_sweeper_ignores_dead_letters_and_filters(client, seed_org):
    db = SessionLocal()
    try:
        service = NotificationService()
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={},
        )
        db.add(assignment)
        db.flush()

        now = datetime.now(timezone.utc)
        db.add_all(
            [
                DrillSession(
                    id="session-old",
                    assignment_id=assignment.id,
                    rep_id=seed_org["rep_id"],
                    scenario_id=seed_org["scenario_id"],
                    started_at=now - timedelta(minutes=15),
                    status=SessionStatus.PROCESSING,
                ),
                DrillSession(
                    id="session-active",
                    assignment_id=assignment.id,
                    rep_id=seed_org["rep_id"],
                    scenario_id=seed_org["scenario_id"],
                    started_at=now - timedelta(minutes=10),
                    status=SessionStatus.PROCESSING,
                ),
            ]
        )
        db.flush()

        old = NotificationDelivery(
            session_id="session-old",
            manager_id=seed_org["manager_id"],
            channel="email",
            payload={"to_email": "mia@example.com"},
            provider_response={},
            status="dead_letter",
            retries=5,
            next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        active = NotificationDelivery(
            session_id="session-active",
            manager_id=seed_org["manager_id"],
            channel="push",
            payload={"push_token": "ExponentPushToken[abc]"},
            provider_response={},
            status="retry_scheduled",
            retries=1,
            next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add_all([old, active])
        db.commit()

        retried = await service.retry_due_deliveries(db, limit=10)
        assert retried["retried_count"] == 0

        response = client.get(
            "/manager/notifications",
            params={
                "manager_id": seed_org["manager_id"],
                "status": "retry_scheduled",
                "channel": "push",
                "session_id": "session-active",
            },
            headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["session_id"] == "session-active"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_postprocess_retry_sweeper_reruns_due_rows(seed_org, monkeypatch):
    db = SessionLocal()
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.IN_PROGRESS,
            retry_policy={},
        )
        db.add(assignment)
        db.flush()

        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.PROCESSING,
        )
        db.add(session)
        db.flush()

        run = PostprocessRun(
            session_id=session.id,
            task_type="notify",
            status="retry_scheduled",
            attempts=1,
            idempotency_key=f"{session.id}:notify",
            next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(run)
        db.commit()

        service = SessionPostprocessService()
        called: list[tuple[str, str]] = []

        async def fake_run_task_inline(db_session, *, session_id: str, task_type: str):
            called.append((session_id, task_type))
            row = db_session.scalar(
                select(PostprocessRun).where(
                    PostprocessRun.session_id == session_id,
                    PostprocessRun.task_type == task_type,
                )
            )
            assert row is not None
            row.status = "completed"
            row.completed_at = datetime.now(timezone.utc)
            db_session.commit()
            return {"task_type": task_type, "status": "completed", "run_id": row.id}

        monkeypatch.setattr(service, "run_task_inline", fake_run_task_inline)
        result = await service.retry_due_runs(db, limit=10)
        db.refresh(run)

        assert result["retried_count"] == 1
        assert called == [(session.id, "notify")]
        assert run.status == "completed"
    finally:
        db.close()
