import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session_module
import app.services.ledger_service as ledger_service_module
from app.models import Base
from app.db.session import SessionLocal
from app.models.session import SessionEvent
from app.services.ledger_buffer import InMemoryEventBuffer
from app.services.ledger_service import SessionLedgerService


def make_ledger() -> SessionLedgerService:
    return SessionLedgerService(buffer=InMemoryEventBuffer())


def make_event(session_id: str, event_type: str = "test.event",
               event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "session_id": session_id,
        "type": event_type,
        "direction": "server",
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "payload": {"x": 1},
    }


@pytest.fixture(scope="session", autouse=True)
def initialize_test_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("ledger-flush-db") / "ledger_flush.sqlite"
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
    patcher.setattr(ledger_service_module, "SessionLocal", testing_session_local)
    patcher.setitem(globals(), "SessionLocal", testing_session_local)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        patcher.undo()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def reset_db(initialize_test_db):
    engine = db_session_module.engine
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


@pytest.mark.asyncio
async def test_flush_empty_buffer_returns_zero():
    ledger = make_ledger()
    db = SessionLocal()
    try:
        result = await ledger.flush_buffered_events(db, "sess-empty")
        assert result == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_flush_persists_events_to_db(reset_db):
    ledger = make_ledger()
    session_id = "sess-persist-" + uuid.uuid4().hex[:6]
    event = make_event(session_id)
    await ledger.buffer_event(session_id, event)

    db = SessionLocal()
    try:
        count = await ledger.flush_buffered_events(db, session_id)
        assert count == 1

        stored = db.scalar(
            select(SessionEvent).where(SessionEvent.event_id == event["event_id"])
        )
        assert stored is not None
        assert stored.session_id == session_id
        assert stored.event_type == "test.event"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_flush_is_idempotent_on_duplicate_event_id(reset_db):
    ledger = make_ledger()
    session_id = "sess-idem-" + uuid.uuid4().hex[:6]
    fixed_event_id = str(uuid.uuid4())
    event = make_event(session_id, event_id=fixed_event_id)

    await ledger.buffer_event(session_id, dict(event))
    await ledger.buffer_event(session_id, dict(event))

    db = SessionLocal()
    try:
        count = await ledger.flush_buffered_events(db, session_id, max_n=10)
        assert count == 1

        rows = db.scalars(
            select(SessionEvent).where(SessionEvent.event_id == fixed_event_id)
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


@pytest.mark.asyncio
async def test_flush_sets_session_id_on_events_from_drain(reset_db):
    """buffer.drain returns events; flush must attach session_id before _flush_sync."""
    ledger = make_ledger()
    session_id = "sess-sid-" + uuid.uuid4().hex[:6]
    raw = {
        "event_id": str(uuid.uuid4()),
        "type": "test.sid",
        "direction": "server",
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "payload": {},
    }
    await ledger.buffer_event(session_id, raw)

    db = SessionLocal()
    try:
        await ledger.flush_buffered_events(db, session_id)
        stored = db.scalar(
            select(SessionEvent).where(SessionEvent.event_id == raw["event_id"])
        )
        assert stored is not None
        assert stored.session_id == session_id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_flush_buffered_events_does_not_block_event_loop(reset_db):
    """Verify the flush runs in an executor and doesn't starve other coroutines."""
    ledger = make_ledger()
    session_id = "sess-nonblock-" + uuid.uuid4().hex[:6]
    for _ in range(5):
        await ledger.buffer_event(session_id, make_event(session_id, event_id=str(uuid.uuid4())))

    side_task_ran = asyncio.Event()

    async def side_task():
        await asyncio.sleep(0)
        side_task_ran.set()

    db = SessionLocal()
    try:
        task = asyncio.create_task(side_task())
        await ledger.flush_buffered_events(db, session_id)
        await task
        assert side_task_ran.is_set(), "side task never ran — event loop was blocked during flush"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_flush_multiple_events_in_one_batch(reset_db):
    ledger = make_ledger()
    session_id = "sess-batch-" + uuid.uuid4().hex[:6]
    event_ids = []
    for _ in range(8):
        eid = str(uuid.uuid4())
        event_ids.append(eid)
        await ledger.buffer_event(session_id, make_event(session_id, event_id=eid))

    db = SessionLocal()
    try:
        count = await ledger.flush_buffered_events(db, session_id, max_n=10)
        assert count == 8

        stored = db.scalars(
            select(SessionEvent).where(SessionEvent.session_id == session_id)
        ).all()
        assert len(stored) == 8
        assert {r.event_id for r in stored} == set(event_ids)
    finally:
        db.close()
