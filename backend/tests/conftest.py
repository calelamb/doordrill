from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData

from app.main import app
from app.db.session import SessionLocal, engine
from app.models import Base
from app.models.scenario import Scenario
from app.models.user import Organization, Team, User
from app.models.types import UserRole


@pytest.fixture(autouse=True)
def reset_db() -> None:
    reflected = MetaData()
    reflected.reflect(bind=engine)
    if reflected.tables:
        reflected.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seed_org() -> dict[str, str]:
    db = SessionLocal()
    seed_token = uuid4().hex[:8]

    org = Organization(name=f"Acme D2D {seed_token}", industry="pest_control", plan_tier="pro")
    db.add(org)
    db.commit()
    db.refresh(org)

    manager = User(
        org_id=org.id,
        role=UserRole.MANAGER,
        name="Mia Manager",
        email=f"mia+{seed_token}@example.com",
    )
    rep = User(
        org_id=org.id,
        role=UserRole.REP,
        name="Ray Rep",
        email=f"ray+{seed_token}@example.com",
    )
    db.add_all([manager, rep])
    db.commit()
    db.refresh(manager)
    db.refresh(rep)

    team = Team(org_id=org.id, manager_id=manager.id, name="Summer Team")
    db.add(team)
    db.commit()
    db.refresh(team)

    manager.team_id = team.id
    rep.team_id = team.id
    db.commit()

    scenario = Scenario(
        org_id=org.id,
        name="Skeptical Homeowner",
        industry="pest_control",
        difficulty=2,
        description="Rep handles initial skepticism about monthly service.",
        persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
        rubric={"opening": 10, "pitch": 10, "objections": 10, "closing": 10, "professionalism": 10},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
        created_by_id=manager.id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    db.close()
    return {
        "org_id": org.id,
        "manager_id": manager.id,
        "rep_id": rep.id,
        "scenario_id": scenario.id,
        "seeded_at": datetime.now(timezone.utc).isoformat(),
    }
