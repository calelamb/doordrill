from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.session import SessionArtifact, SessionEvent, SessionTurn
from app.models.types import EventDirection, TurnSpeaker
from app.services.ledger_buffer import BaseEventBuffer

logger = logging.getLogger(__name__)


class SessionLedgerService:
    def __init__(self, buffer: BaseEventBuffer) -> None:
        self.buffer = buffer

    async def buffer_event(self, session_id: str, event: dict[str, Any]) -> None:
        if not event.get("event_id"):
            event["event_id"] = str(uuid.uuid4())
        if not event.get("timestamp"):
            event["timestamp"] = datetime.now(timezone.utc).isoformat()
        await self.buffer.push(session_id, event)

    def _flush_sync(self, db: Session, events: list[dict[str, Any]]) -> int:
        worker_db = SessionLocal()
        try:
            try:
                persisted = 0
                seen_event_ids: set[str] = set()
                for raw in events:
                    event_id = raw.get("event_id", str(uuid.uuid4()))
                    if event_id in seen_event_ids:
                        continue
                    exists = worker_db.scalar(
                        select(SessionEvent).where(SessionEvent.event_id == event_id)
                    )
                    if exists:
                        continue
                    direction = raw.get("direction", EventDirection.SYSTEM.value)
                    if direction not in {d.value for d in EventDirection}:
                        direction = EventDirection.SYSTEM.value
                    payload = raw.get("payload", {})
                    if not isinstance(payload, dict):
                        payload = {"raw": payload}
                    worker_db.add(
                        SessionEvent(
                            session_id=raw.get("session_id", ""),
                            event_id=event_id,
                            event_type=raw.get("type", "unknown"),
                            direction=EventDirection(direction),
                            sequence=int(raw.get("sequence", 0)),
                            event_ts=_parse_iso(raw.get("timestamp")),
                            payload=payload,
                        )
                    )
                    seen_event_ids.add(event_id)
                    persisted += 1
                worker_db.commit()
                return persisted
            except OperationalError as exc:
                logger.warning(
                    "ledger_flush_db_error",
                    extra={"error": str(exc), "unflushed_events": len(events)},
                )
                return 0
        finally:
            worker_db.close()

    async def flush_buffered_events(self, db: Session, session_id: str, max_n: int = 200) -> int:
        events = await self.buffer.drain(session_id, max_n=max_n)
        if not events:
            return 0
        for event in events:
            event.setdefault("session_id", session_id)
        try:
            loop = asyncio.get_running_loop()
            flush_future = loop.run_in_executor(None, self._flush_sync, db, events)
            try:
                return await asyncio.shield(flush_future)
            except asyncio.CancelledError:
                return await asyncio.shield(flush_future)
        except Exception as exc:
            logger.warning(
                "ledger_flush_unexpected_error",
                extra={"error": str(exc), "session_id": session_id, "unflushed_events": len(events)},
            )
            return 0

    def commit_turn(
        self,
        db: Session,
        *,
        session_id: str,
        turn_index: int,
        speaker: TurnSpeaker,
        text: str,
        stage: str,
        started_at: datetime,
        ended_at: datetime,
        objection_tags: list[str] | None = None,
    ) -> SessionTurn:
        turn = SessionTurn(
            session_id=session_id,
            turn_index=turn_index,
            speaker=speaker,
            stage=stage,
            text=text,
            started_at=started_at,
            ended_at=ended_at,
            objection_tags=objection_tags or [],
        )
        db.add(turn)
        db.commit()
        db.refresh(turn)
        return turn

    def compact_session(self, db: Session, session_id: str) -> SessionArtifact:
        turns = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())
        ).all()
        canonical = [
            {
                "turn_index": t.turn_index,
                "speaker": t.speaker.value,
                "stage": t.stage,
                "text": t.text,
                "started_at": t.started_at.isoformat(),
                "ended_at": t.ended_at.isoformat(),
                "objection_tags": t.objection_tags,
            }
            for t in turns
        ]
        storage_key = f"sessions/{session_id}/canonical_transcript.json"
        artifact = SessionArtifact(
            session_id=session_id,
            artifact_type="canonical_transcript",
            storage_key=storage_key,
            metadata_json={"turn_count": len(canonical), "transcript": canonical},
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        return artifact


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return datetime.now(timezone.utc)
