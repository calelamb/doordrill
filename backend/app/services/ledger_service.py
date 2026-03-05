from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.session import SessionArtifact, SessionEvent, SessionTurn
from app.models.types import EventDirection, TurnSpeaker
from app.services.ledger_buffer import BaseEventBuffer


class SessionLedgerService:
    def __init__(self, buffer: BaseEventBuffer) -> None:
        self.buffer = buffer

    async def buffer_event(self, session_id: str, event: dict[str, Any]) -> None:
        if not event.get("event_id"):
            event["event_id"] = str(uuid.uuid4())
        if not event.get("timestamp"):
            event["timestamp"] = datetime.now(timezone.utc).isoformat()
        await self.buffer.push(session_id, event)

    async def flush_buffered_events(self, db: Session, session_id: str, max_n: int = 200) -> int:
        events = await self.buffer.drain(session_id, max_n=max_n)
        if not events:
            return 0
        persisted = 0
        for raw in events:
            event_id = raw.get("event_id", str(uuid.uuid4()))
            exists = db.scalar(select(SessionEvent).where(SessionEvent.event_id == event_id))
            if exists:
                continue
            direction = raw.get("direction", EventDirection.SYSTEM.value)
            if direction not in {d.value for d in EventDirection}:
                direction = EventDirection.SYSTEM.value
            payload = raw.get("payload", {})
            if not isinstance(payload, dict):
                payload = {"raw": payload}
            db.add(
                SessionEvent(
                    session_id=session_id,
                    event_id=event_id,
                    event_type=raw.get("type", "unknown"),
                    direction=EventDirection(direction),
                    sequence=int(raw.get("sequence", 0)),
                    event_ts=_parse_iso(raw.get("timestamp")),
                    payload=payload,
                )
            )
            persisted += 1
        db.commit()
        return persisted

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
