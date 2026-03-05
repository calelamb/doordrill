from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionTurn
from app.models.types import AssignmentStatus, EventDirection, SessionStatus, TurnSpeaker
from app.schemas.ws import WsEvent
from app.services.conversation_orchestrator import ConversationOrchestrator
from app.services.grading_service import GradingService
from app.services.ledger_buffer import InMemoryEventBuffer, RedisEventBuffer
from app.services.ledger_service import SessionLedgerService

router = APIRouter(tags=["voice"])
settings = get_settings()
logger = logging.getLogger(__name__)


try:
    event_buffer = RedisEventBuffer(settings.redis_url) if settings.redis_url else InMemoryEventBuffer()
except Exception:
    event_buffer = InMemoryEventBuffer()

ledger = SessionLedgerService(buffer=event_buffer)
orchestrator = ConversationOrchestrator()
grading_service = GradingService()


async def _send_event(websocket: WebSocket, event_type: str, payload: dict[str, Any], sequence: int) -> None:
    await websocket.send_json(
        {
            "type": event_type,
            "sequence": sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
    )


@router.websocket("/ws/sessions/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()

    db = SessionLocal()
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        await websocket.send_json({"type": "server.error", "payload": {"code": "not_found", "message": "session not found"}})
        await websocket.close(code=4404)
        db.close()
        return

    server_sequence = 0
    last_flush = time.monotonic()

    async def maybe_flush(force: bool = False) -> None:
        nonlocal last_flush
        now = time.monotonic()
        interval = settings.ws_flush_interval_ms / 1000
        if force or (now - last_flush) >= interval:
            await ledger.flush_buffered_events(db, session_id=session_id, max_n=settings.max_ws_event_batch)
            last_flush = now

    async def buffer_event(direction: EventDirection, msg: WsEvent) -> None:
        await ledger.buffer_event(
            session_id=session_id,
            event={
                "event_id": msg.event_id,
                "type": msg.type,
                "direction": direction.value,
                "sequence": msg.sequence or 0,
                "timestamp": msg.timestamp.isoformat(),
                "payload": msg.payload,
            },
        )

    try:
        server_sequence += 1
        await _send_event(websocket, "server.session.state", {"state": "connected", "session_id": session_id}, server_sequence)
        await ledger.buffer_event(
            session_id=session_id,
            event={
                "type": "server.session.state",
                "direction": EventDirection.SERVER.value,
                "sequence": server_sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"state": "connected", "session_id": session_id},
            },
        )
        await maybe_flush()

        while True:
            raw = await websocket.receive_json()
            msg = WsEvent.model_validate(raw)

            if msg.type not in {"client.audio.chunk", "client.vad.state", "client.session.end"}:
                server_sequence += 1
                await _send_event(
                    websocket,
                    "server.error",
                    {"code": "bad_event", "message": f"unsupported event type: {msg.type}", "retryable": True},
                    server_sequence,
                )
                continue

            await buffer_event(EventDirection.CLIENT, msg)
            await maybe_flush()

            if msg.type == "client.vad.state":
                speaking = bool(msg.payload.get("speaking", False))
                server_sequence += 1
                await _send_event(
                    websocket,
                    "server.session.state",
                    {"state": "rep_speaking" if speaking else "rep_idle", "session_id": session_id},
                    server_sequence,
                )
                await ledger.buffer_event(
                    session_id=session_id,
                    event={
                        "type": "server.session.state",
                        "direction": EventDirection.SERVER.value,
                        "sequence": server_sequence,
                        "payload": {"state": "rep_speaking" if speaking else "rep_idle"},
                    },
                )
                await maybe_flush()
                continue

            if msg.type == "client.session.end":
                break

            rep_text = str(msg.payload.get("transcript_hint", "")).strip()
            if not rep_text:
                server_sequence += 1
                await _send_event(
                    websocket,
                    "server.stt.partial",
                    {"text": "", "confidence": 0.0, "message": "awaiting transcript"},
                    server_sequence,
                )
                continue

            now = datetime.now(timezone.utc)
            next_turn_index = (db.scalar(select(func.count(SessionTurn.id)).where(SessionTurn.session_id == session_id)) or 0) + 1
            rep_turn = ledger.commit_turn(
                db,
                session_id=session_id,
                turn_index=next_turn_index,
                speaker=TurnSpeaker.REP,
                text=rep_text,
                stage=orchestrator.get_state(session_id).stage,
                started_at=now,
                ended_at=now,
                objection_tags=["price"] if "price" in rep_text.lower() else [],
            )

            server_sequence += 1
            await _send_event(websocket, "server.stt.final", {"text": rep_text, "turn_id": rep_turn.id}, server_sequence)
            await ledger.buffer_event(
                session_id=session_id,
                event={
                    "type": "server.stt.final",
                    "direction": EventDirection.SERVER.value,
                    "sequence": server_sequence,
                    "payload": {"text": rep_text, "turn_id": rep_turn.id},
                },
            )
            await maybe_flush()

            ai_chunks = await orchestrator.generate_ai_response(session_id, rep_text)
            ai_text_parts: list[str] = []
            for chunk in ai_chunks:
                if not chunk:
                    continue
                ai_text_parts.append(chunk)

                server_sequence += 1
                await _send_event(websocket, "server.ai.text.delta", {"token": chunk}, server_sequence)
                await ledger.buffer_event(
                    session_id=session_id,
                    event={
                        "type": "server.ai.text.delta",
                        "direction": EventDirection.SERVER.value,
                        "sequence": server_sequence,
                        "payload": {"token": chunk},
                    },
                )

                server_sequence += 1
                await _send_event(
                    websocket,
                    "server.ai.audio.chunk",
                    {"codec": "pcm16", "payload": "UklGRiQAAABXQVZFZm10"},
                    server_sequence,
                )
                await ledger.buffer_event(
                    session_id=session_id,
                    event={
                        "type": "server.ai.audio.chunk",
                        "direction": EventDirection.SERVER.value,
                        "sequence": server_sequence,
                        "payload": {"codec": "pcm16", "payload": "UklGRiQAAABXQVZFZm10"},
                    },
                )
                await maybe_flush()

            ai_turn = ledger.commit_turn(
                db,
                session_id=session_id,
                turn_index=next_turn_index + 1,
                speaker=TurnSpeaker.AI,
                text="".join(ai_text_parts).strip(),
                stage=orchestrator.get_state(session_id).stage,
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
                objection_tags=[],
            )

            server_sequence += 1
            turn_payload = {
                "rep_turn_id": rep_turn.id,
                "ai_turn_id": ai_turn.id,
                "session_id": session_id,
                "stage": orchestrator.get_state(session_id).stage,
            }
            await _send_event(websocket, "server.turn.committed", turn_payload, server_sequence)
            await ledger.buffer_event(
                session_id=session_id,
                event={
                    "type": "server.turn.committed",
                    "direction": EventDirection.SERVER.value,
                    "sequence": server_sequence,
                    "payload": turn_payload,
                },
            )
            await maybe_flush()

    except WebSocketDisconnect:
        pass
    finally:
        try:
            await maybe_flush(force=True)
            ledger.compact_session(db, session_id)

            db.add(
                SessionArtifact(
                    session_id=session_id,
                    artifact_type="audio",
                    storage_key=f"sessions/{session_id}/session_audio.opus",
                    metadata_json={"codec": "opus", "channels": 1},
                )
            )

            session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
            if session is not None:
                session.status = SessionStatus.PROCESSING
                ended_at = datetime.now(timezone.utc)
                session.ended_at = ended_at
                if session.started_at:
                    started_at = session.started_at
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    session.duration_seconds = int((ended_at - started_at).total_seconds())

            assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id)) if session else None
            if assignment is not None:
                assignment.status = AssignmentStatus.COMPLETED
            db.commit()

            if session is not None:
                await grading_service.grade_session(db, session_id=session_id)
        except Exception:  # pragma: no cover
            logger.exception("Failed to finalize websocket session", extra={"session_id": session_id})
            db.rollback()
        finally:
            db.close()
