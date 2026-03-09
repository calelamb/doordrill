from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.user import User
from app.services.notification_service import NotificationService

DEFAULT_NOTIFICATION_PREFERENCES = {
    "score_ready": True,
    "assignment_created": True,
    "assignment_due_soon": True,
    "coaching_note": True,
    "streak_nudge": True,
}


def test_notification_preferences_endpoints_return_defaults_and_persist_updates(client, seed_org):
    headers = {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}

    response = client.get("/rep/notification-preferences", headers=headers)
    assert response.status_code == 200
    assert response.json() == DEFAULT_NOTIFICATION_PREFERENCES

    updated_preferences = {
        **DEFAULT_NOTIFICATION_PREFERENCES,
        "assignment_due_soon": False,
        "streak_nudge": False,
    }
    update_response = client.put("/rep/notification-preferences", headers=headers, json=updated_preferences)
    assert update_response.status_code == 200
    assert update_response.json() == updated_preferences

    second_read = client.get("/rep/notification-preferences", headers=headers)
    assert second_read.status_code == 200
    assert second_read.json() == updated_preferences

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert user is not None
        assert user.notification_preferences == updated_preferences
    finally:
        db.close()


@pytest.mark.asyncio
async def test_rep_notification_method_skips_send_when_preference_disabled(seed_org, monkeypatch):
    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        rep.notification_preferences = {"score_ready": False}
        db.commit()

        service = NotificationService()
        active_tokens_called = False
        send_called = False

        async def fake_get_active_tokens(_db, *, user_id: str):
            nonlocal active_tokens_called
            active_tokens_called = True
            assert user_id == seed_org["rep_id"]
            return []

        async def fake_send_to_tokens(*args, **kwargs):
            nonlocal send_called
            send_called = True
            return []

        monkeypatch.setattr(service, "_get_active_tokens", fake_get_active_tokens)
        monkeypatch.setattr(service, "_send_to_tokens", fake_send_to_tokens)

        result = await service.notify_rep_score_ready(
            db,
            rep_id=seed_org["rep_id"],
            session_id="session-disabled-pref",
            scenario_name="Warm Lead",
            overall_score=8.7,
        )

        assert result is None
        assert active_tokens_called is False
        assert send_called is False
    finally:
        db.close()
