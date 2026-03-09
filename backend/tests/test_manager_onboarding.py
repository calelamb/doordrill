from sqlalchemy import select

import app.api.manager as manager_api
from app.db.session import SessionLocal
from app.models.user import User


def test_manager_onboarding_status_progresses_and_sets_completed_at(client, seed_org, monkeypatch):
    monkeypatch.setattr(manager_api, "_send_invitation_email", lambda **_kwargs: None)

    initial = client.get(
        "/manager/onboarding-status",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert initial.status_code == 200
    initial_body = initial.json()
    assert initial_body["is_complete"] is False
    assert [step["id"] for step in initial_body["steps"]] == ["org_profile", "first_scenario", "first_invite"]
    assert initial_body["steps"][0]["is_complete"] is True
    assert initial_body["steps"][1]["is_complete"] is True
    assert initial_body["steps"][2]["is_complete"] is False

    invite = client.post(
        "/manager/invitations",
        json={"email": "first-rep@example.com"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert invite.status_code == 200

    completed = client.get(
        "/manager/onboarding-status",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["is_complete"] is True
    assert all(step["is_complete"] for step in completed_body["steps"])
    assert completed_body["onboarding_completed_at"] is not None

    db = SessionLocal()
    try:
        manager = db.scalar(select(User).where(User.id == seed_org["manager_id"]))
        assert manager is not None
        assert manager.onboarding_completed_at is not None
    finally:
        db.close()


def test_manager_can_update_organization_profile(client, seed_org):
    response = client.put(
        "/manager/organization",
        json={"name": "Peak Pest", "industry": "solar"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Peak Pest"
    assert body["industry"] == "solar"


def test_inviting_same_email_twice_returns_already_invited(client, seed_org, monkeypatch):
    monkeypatch.setattr(manager_api, "_send_invitation_email", lambda **_kwargs: None)

    first = client.post(
        "/manager/invitations",
        json={"email": "duplicate-rep@example.com"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert first.status_code == 200

    second = client.post(
        "/manager/invitations",
        json={"email": "duplicate-rep@example.com"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "email already invited"
