from __future__ import annotations

from sqlalchemy import select

from app.api import rep as rep_api
from app.db.session import SessionLocal
from app.models.prompt_version import PromptVersion
from app.models.session import Session as DrillSession
from app.services.prompt_experiment_service import PromptExperimentService


def _rep_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {
        "x-user-id": seed_org["rep_id"],
        "x-user-role": "rep",
        "x-request-id": "conversation-ab-routing-request",
        "x-trace-id": "conversation-ab-routing-test",
    }


class _RepUuidStub:
    def __init__(self, values: list[str]) -> None:
        self._values = iter(values)

    def uuid4(self) -> str:
        return next(self._values)


def _seed_conversation_versions() -> tuple[PromptVersion, PromptVersion]:
    db = SessionLocal()
    try:
        control = PromptVersion(
            prompt_type="conversation",
            version="conversation_control",
            content="control prompt",
            active=True,
        )
        challenger = PromptVersion(
            prompt_type="conversation",
            version="conversation_challenger",
            content="challenger prompt",
            active=False,
        )
        db.add_all([control, challenger])
        db.commit()
        db.refresh(control)
        db.refresh(challenger)
        return control, challenger
    finally:
        db.close()


def test_conversation_prompt_routing_is_deterministic(seed_org):
    db = SessionLocal()
    try:
        control = PromptVersion(
            prompt_type="conversation",
            version="conversation_control",
            content="control prompt",
            active=True,
        )
        challenger = PromptVersion(
            prompt_type="conversation",
            version="conversation_challenger",
            content="challenger prompt",
            active=False,
        )
        db.add_all([control, challenger])
        db.commit()
        db.refresh(control)
        db.refresh(challenger)

        PromptExperimentService().create_experiment(
            db,
            prompt_type="conversation",
            control_version_id=control.id,
            challenger_version_id=challenger.id,
            challenger_traffic_pct=50,
            min_sessions_for_decision=2,
        )
        db.commit()

        session_id = "session-deterministic-route"
        first = rep_api._select_conversation_prompt_version(db, session_id=session_id)
        second = rep_api._select_conversation_prompt_version(db, session_id=session_id)

        assert first is not None
        assert second is not None
        assert first.id == second.id

        routed_ids = {
            rep_api._select_conversation_prompt_version(db, session_id=f"session-{index}").id
            for index in range(200)
        }
        assert control.id in routed_ids
        assert challenger.id in routed_ids

        same_again = {
            f"session-{index}": rep_api._select_conversation_prompt_version(db, session_id=f"session-{index}").id
            for index in range(20)
        }
        repeated = {
            f"session-{index}": rep_api._select_conversation_prompt_version(db, session_id=f"session-{index}").id
            for index in range(20)
        }
        assert same_again == repeated
    finally:
        db.close()


def test_create_session_stamps_experiment_selected_prompt_version(client, seed_org, monkeypatch):
    db = SessionLocal()
    try:
        control = PromptVersion(
            prompt_type="conversation",
            version="conversation_control",
            content="control prompt",
            active=True,
        )
        challenger = PromptVersion(
            prompt_type="conversation",
            version="conversation_challenger",
            content="challenger prompt",
            active=False,
        )
        db.add_all([control, challenger])
        db.commit()
        db.refresh(control)
        db.refresh(challenger)

        PromptExperimentService().create_experiment(
            db,
            prompt_type="conversation",
            control_version_id=control.id,
            challenger_version_id=challenger.id,
            challenger_traffic_pct=50,
            min_sessions_for_decision=2,
        )
        db.commit()

        routed_session_ids: dict[str, str] = {}
        for index in range(500):
            session_id = f"conversation-route-{index}"
            selected = rep_api._select_conversation_prompt_version(db, session_id=session_id)
            assert selected is not None
            routed_session_ids.setdefault(selected.version, session_id)
            if control.version in routed_session_ids and challenger.version in routed_session_ids:
                break
        assert control.version in routed_session_ids
        assert challenger.version in routed_session_ids
    finally:
        db.close()

    monkeypatch.setattr(
        rep_api,
        "uuid",
        _RepUuidStub(
            [
                routed_session_ids[control.version],
                routed_session_ids[challenger.version],
            ]
        ),
    )

    headers = _rep_headers(seed_org)
    control_response = client.post(
        "/rep/sessions",
        headers=headers,
        json={
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    challenger_response = client.post(
        "/rep/sessions",
        headers=headers,
        json={
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )

    assert control_response.status_code == 200
    assert challenger_response.status_code == 200

    db = SessionLocal()
    try:
        control_session = db.get(DrillSession, routed_session_ids[control.version])
        challenger_session = db.get(DrillSession, routed_session_ids[challenger.version])
        assert control_session is not None
        assert challenger_session is not None
        assert control_session.prompt_version == control.version
        assert challenger_session.prompt_version == challenger.version
    finally:
        db.close()


def test_create_session_falls_back_to_active_conversation_version_without_experiment(client, seed_org, monkeypatch):
    db = SessionLocal()
    try:
        for row in db.scalars(
            select(PromptVersion).where(PromptVersion.prompt_type == "conversation")
        ).all():
            row.active = False
        active = PromptVersion(
            prompt_type="conversation",
            version="conversation_active_fallback",
            content="active prompt",
            active=True,
        )
        inactive = PromptVersion(
            prompt_type="conversation",
            version="conversation_inactive",
            content="inactive prompt",
            active=False,
        )
        db.add_all([active, inactive])
        db.commit()
        db.refresh(active)
        active_version = active.version
    finally:
        db.close()

    session_id = "conversation-fallback-session"
    monkeypatch.setattr(rep_api, "uuid", _RepUuidStub([session_id]))

    response = client.post(
        "/rep/sessions",
        headers=_rep_headers(seed_org),
        json={
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == session_id

    db = SessionLocal()
    try:
        session = db.get(DrillSession, session_id)
        assert session is not None
        assert session.prompt_version == active_version
    finally:
        db.close()
