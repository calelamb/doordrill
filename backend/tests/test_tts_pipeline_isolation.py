import inspect
import textwrap
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.init_db as init_db_module
import app.db.session as db_session_module
import app.services.ledger_service as ledger_service_module
from app.core.config import get_settings
from app.main import app
from app.models import Base
from app.models.scenario import Scenario
from app.models.types import UserRole
from app.models.user import Organization, Team, User
from app.services.conversation_orchestrator import invalidate_objection_cache
from app.services.provider_clients import MockLlmClient, MockSttClient, MockTtsClient, ProviderSuite
from app.voice import ws as voice_ws


@pytest.fixture(scope="session", autouse=True)
def initialize_test_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("tts-isolation-db") / "tts_isolation.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False,
    )
    patcher = pytest.MonkeyPatch()
    patcher.setattr(db_session_module, "engine", engine)
    patcher.setattr(db_session_module, "SessionLocal", testing_session_local)
    patcher.setattr(init_db_module, "engine", engine)
    patcher.setattr(init_db_module, "SessionLocal", testing_session_local)
    patcher.setattr(voice_ws, "SessionLocal", testing_session_local)
    patcher.setattr(ledger_service_module, "SessionLocal", testing_session_local)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        patcher.undo()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def configure_test_runtime():
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
    voice_ws.providers = ProviderSuite(stt=MockSttClient(), llm=MockLlmClient(), tts=MockTtsClient())

    try:
        yield
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)
        voice_ws.providers = ProviderSuite.from_settings(settings)


@pytest.fixture(autouse=True)
def reset_db(initialize_test_db, configure_test_runtime):
    invalidate_objection_cache()
    engine = db_session_module.engine
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seed_org() -> dict[str, str]:
    db = db_session_module.SessionLocal()
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


def test_stream_tts_for_plan_signature_has_no_first_audio_started_param():
    """Verify the fix: first_audio_started was removed from stream_tts_for_plan."""
    import ast
    import app.voice.ws as ws_module

    src = inspect.getsource(ws_module)
    tree = ast.parse(textwrap.dedent(src))

    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "stream_tts_for_plan":
                arg_names = [a.arg for a in node.args.args]
                assert "first_audio_started" not in arg_names, (
                    "stream_tts_for_plan still accepts first_audio_started — "
                    "the backpressure fix was not applied"
                )
                return

    pytest.fail("stream_tts_for_plan function definition not found in ws.py")


def test_process_sentence_does_not_block_on_tts(seed_org, client):
    """End-to-end: a two-sentence LLM response must not cause the server.turn.committed
    event to be delayed by TTS streaming. server.turn.committed must arrive within
    a reasonable wall-clock window regardless of TTS mock latency."""
    assignment = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
        },
    ).json()

    session_id = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment["id"],
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    ).json()["id"]

    start = time.monotonic()
    turn_committed = False

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json({
            "type": "client.audio.chunk",
            "sequence": 1,
            "payload": {
                "transcript_hint": "Hi there, can I take a moment of your time?",
                "codec": "wav",
            },
        })
        for _ in range(80):
            msg = ws.receive_json()
            if msg["type"] == "server.turn.committed":
                turn_committed = True
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    elapsed = time.monotonic() - start
    assert turn_committed, "server.turn.committed never received"
    assert elapsed < 10.0, f"Turn took {elapsed:.1f}s — possible backpressure regression"
