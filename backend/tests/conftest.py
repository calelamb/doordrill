from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.db.session import SessionLocal, engine
from app.models import Base
from app.models.scenario import Scenario
from app.models.user import Organization, Team, User
from app.models.types import UserRole
from app.services.conversation_orchestrator import invalidate_objection_cache
from app.services.provider_clients import ProviderSuite
from app.voice import ws as voice_ws


@pytest.fixture(autouse=True)
def configure_test_runtime() -> Iterator[None]:
    settings = get_settings()
    original_values = {
        "stt_provider": settings.stt_provider,
        "llm_provider": settings.llm_provider,
        "tts_provider": settings.tts_provider,
        "use_celery": settings.use_celery,
        "whisper_cleanup_enabled": settings.whisper_cleanup_enabled,
        "manager_notification_email_enabled": settings.manager_notification_email_enabled,
        "manager_notification_push_enabled": settings.manager_notification_push_enabled,
    }

    settings.stt_provider = "mock"
    settings.llm_provider = "mock"
    settings.tts_provider = "mock"
    settings.use_celery = False
    settings.whisper_cleanup_enabled = False
    settings.manager_notification_email_enabled = False
    settings.manager_notification_push_enabled = False
    voice_ws.providers = ProviderSuite.from_settings(settings)

    yield

    for key, value in original_values.items():
        setattr(settings, key, value)
    voice_ws.providers = ProviderSuite.from_settings(settings)


@pytest.fixture(autouse=True)
def reset_db(configure_test_runtime) -> None:
    invalidate_objection_cache()
    Base.metadata.drop_all(bind=engine)
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
