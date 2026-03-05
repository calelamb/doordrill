from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.manager_action import ManagerActionLog
from app.models.scenario import Scenario
from app.models.user import Organization, User
from app.models.types import UserRole


def _create_assignment(client, scenario_id: str, rep_id: str, manager_id: str, headers: dict | None = None):
    return client.post(
        "/manager/assignments",
        json={
            "scenario_id": scenario_id,
            "rep_id": rep_id,
            "assigned_by": manager_id,
            "retry_policy": {"max_attempts": 1},
        },
        headers=headers or {},
    )


def test_cross_org_assignment_blocked(client, seed_org):
    db = SessionLocal()
    other_org = Organization(name="Other Org", industry="solar", plan_tier="pro")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    outsider_rep = User(org_id=other_org.id, role=UserRole.REP, name="Outsider Rep", email="outsider@example.com")
    db.add(outsider_rep)
    db.commit()
    db.refresh(outsider_rep)
    db.close()

    denied = _create_assignment(
        client,
        scenario_id=seed_org["scenario_id"],
        rep_id=outsider_rep.id,
        manager_id=seed_org["manager_id"],
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert denied.status_code == 403
    assert "cross-organization" in denied.text


def test_scenario_org_is_set_by_manager_on_assignment(client, seed_org):
    db = SessionLocal()
    scenario = db.scalar(select(Scenario).where(Scenario.id == seed_org["scenario_id"]))
    assert scenario is not None
    scenario.org_id = None
    db.commit()
    db.close()

    ok = _create_assignment(
        client,
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        manager_id=seed_org["manager_id"],
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert ok.status_code == 200

    db = SessionLocal()
    scenario_after = db.scalar(select(Scenario).where(Scenario.id == seed_org["scenario_id"]))
    assert scenario_after is not None
    assert scenario_after.org_id == seed_org["org_id"]
    db.close()


def test_manager_action_log_written_for_assignment(client, seed_org):
    resp = _create_assignment(
        client,
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        manager_id=seed_org["manager_id"],
    )
    assert resp.status_code == 200
    assignment_id = resp.json()["id"]

    db = SessionLocal()
    logs = db.scalars(
        select(ManagerActionLog)
        .where(ManagerActionLog.target_type == "assignment", ManagerActionLog.target_id == assignment_id)
        .order_by(ManagerActionLog.occurred_at.desc())
    ).all()
    db.close()

    assert logs
    assert logs[0].action_type in {"assignment.created", "assignment.followup_created"}

    actions_resp = client.get(
        "/manager/actions",
        params={"manager_id": seed_org["manager_id"], "limit": 10},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert actions_resp.status_code == 200
    actions = actions_resp.json()["items"]
    assert any(item["action_type"] == "assignment.created" for item in actions)
