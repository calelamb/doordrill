from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.device_token import DeviceToken
from app.models.notification_delivery import NotificationDelivery
from app.services.notification_providers import ProviderSendResult
from app.services.notification_service import NotificationService


def _notification_method_cases(now: datetime) -> list[tuple[str, dict[str, object], dict[str, object]]]:
    note_preview = "Tighten the first fifteen seconds and ask the closing question earlier. " * 2
    return [
        (
            "notify_rep_score_ready",
            {
                "rep_id": "rep-id",
                "session_id": "session-123",
                "scenario_name": "Skeptical Homeowner",
                "overall_score": 8.4,
            },
            {
                "title": "🟢 Drill Results Ready",
                "body": "You scored 8.4/10 on Skeptical Homeowner. Tap to review.",
                "data": {"type": "score_ready", "session_id": "session-123"},
                "session_id": "session-123",
            },
        ),
        (
            "notify_rep_assignment_created",
            {
                "rep_id": "rep-id",
                "assignment_id": "assignment-123",
                "scenario_name": "Price Objection",
                "due_at": now,
            },
            {
                "title": "📋 New Drill Assigned",
                "body": "Price Objection has been assigned to you. Due Mar 9.",
                "data": {"type": "assignment_created", "assignment_id": "assignment-123"},
                "session_id": None,
            },
        ),
        (
            "notify_rep_assignment_due_soon",
            {
                "rep_id": "rep-id",
                "assignment_id": "assignment-456",
                "scenario_name": "Fence Sitter",
                "due_at": now.replace(hour=15, minute=0),
            },
            {
                "title": "⏰ Drill Due Tomorrow",
                "body": "'Fence Sitter' is due Mar 9 at 3PM. Get it done!",
                "data": {"type": "assignment_due_soon", "assignment_id": "assignment-456"},
                "session_id": None,
            },
        ),
        (
            "notify_rep_coaching_note",
            {
                "rep_id": "rep-id",
                "session_id": "session-999",
                "manager_name": "Mia",
                "note_preview": note_preview,
            },
            {
                "title": "💬 Note from Mia",
                "body": note_preview[:80] + "…",
                "data": {"type": "coaching_note", "session_id": "session-999"},
                "session_id": "session-999",
            },
        ),
        (
            "notify_rep_streak_nudge",
            {
                "rep_id": "rep-id",
                "days_inactive": 3,
                "last_score": 6.2,
            },
            {
                "title": "🔥 Keep Your Streak Going",
                "body": "You haven't drilled in 3 days. Your last score was 6.2 — there's room to improve!",
                "data": {"type": "streak_nudge"},
                "session_id": None,
            },
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,kwargs,_expected", _notification_method_cases(datetime(2026, 3, 9, tzinfo=timezone.utc)))
async def test_rep_notification_methods_skip_send_when_no_tokens(monkeypatch, method_name, kwargs, _expected):
    service = NotificationService()

    async def fake_get_active_tokens(_db, *, user_id: str):
        assert user_id == kwargs["rep_id"]
        return []

    called = False

    async def fake_send_to_tokens(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(service, "_get_active_tokens", fake_get_active_tokens)
    monkeypatch.setattr(service, "_send_to_tokens", fake_send_to_tokens)

    result = await getattr(service, method_name)(None, **kwargs)

    assert result is None
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,kwargs,expected", _notification_method_cases(datetime(2026, 3, 9, tzinfo=timezone.utc)))
async def test_rep_notification_methods_build_expected_payloads(monkeypatch, method_name, kwargs, expected):
    service = NotificationService()
    token = DeviceToken(
        user_id="rep-id",
        platform="ios",
        provider="expo",
        token="ExponentPushToken[test-token-abcdefghijklmnopqrstuvwxyz]",
        status="active",
        last_seen_at=datetime.now(timezone.utc),
    )
    captured: dict[str, object] = {}

    async def fake_get_active_tokens(_db, *, user_id: str):
        assert user_id == kwargs["rep_id"]
        return [token]

    async def fake_send_to_tokens(_db, *, tokens, title: str, body: str, data: dict[str, object], user_id: str, session_id=None):
        captured["tokens"] = tokens
        captured["title"] = title
        captured["body"] = body
        captured["data"] = data
        captured["user_id"] = user_id
        captured["session_id"] = session_id
        return [{"sent": True}]

    monkeypatch.setattr(service, "_get_active_tokens", fake_get_active_tokens)
    monkeypatch.setattr(service, "_send_to_tokens", fake_send_to_tokens)

    result = await getattr(service, method_name)(None, **kwargs)

    assert result is None
    assert captured["tokens"] == [token]
    assert captured["title"] == expected["title"]
    assert captured["body"] == expected["body"]
    assert captured["data"] == expected["data"]
    assert captured["user_id"] == kwargs["rep_id"]
    assert captured["session_id"] == expected["session_id"]


@pytest.mark.asyncio
async def test_send_to_tokens_uses_provider_once_and_logs_delivery(seed_org, monkeypatch):
    db = SessionLocal()
    try:
        service = NotificationService()
        token = DeviceToken(
            user_id=seed_org["rep_id"],
            platform="ios",
            provider="expo",
            token="ExponentPushToken[single-send-token-abcdefghijklmnopqrstuvwxyz]",
            status="active",
            last_seen_at=datetime.now(timezone.utc),
        )
        calls: list[dict[str, object]] = []

        class FakePushProvider:
            async def send(self, *, push_token: str, title: str, body: str, data: dict[str, object]):
                calls.append(
                    {
                        "push_token": push_token,
                        "title": title,
                        "body": body,
                        "data": data,
                    }
                )
                return ProviderSendResult(ok=True, status="sent", response={"provider": "test"})

        service.push_providers["expo"] = FakePushProvider()

        await service._send_to_tokens(
            db,
            tokens=[token],
            title="Test Title",
            body="Test Body",
            data={"type": "score_ready"},
            user_id=seed_org["rep_id"],
            session_id="session-abc",
        )

        delivery = db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.manager_id == seed_org["rep_id"],
                NotificationDelivery.channel == "push",
            )
        )

        assert calls == [
            {
                "push_token": token.token,
                "title": "Test Title",
                "body": "Test Body",
                "data": {"type": "score_ready"},
            }
        ]
        assert delivery is not None
        assert delivery.session_id == "session-abc"
        assert delivery.status == "sent"
        assert delivery.payload["provider"] == "expo"
    finally:
        db.close()
