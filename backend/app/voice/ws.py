from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
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
from app.services.provider_clients import ProviderSuite

router = APIRouter(tags=["voice"])
settings = get_settings()
logger = logging.getLogger(__name__)

SUPPORTED_CLIENT_EVENTS = {"client.audio.chunk", "client.vad.state", "client.session.end"}


try:
    event_buffer = RedisEventBuffer(settings.redis_url) if settings.redis_url else InMemoryEventBuffer()
except Exception:
    event_buffer = InMemoryEventBuffer()

ledger = SessionLedgerService(buffer=event_buffer)
orchestrator = ConversationOrchestrator()
grading_service = GradingService()
providers = ProviderSuite.from_settings(settings)


def _normalize_ts(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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

    incoming: asyncio.Queue[WsEvent] = asyncio.Queue(maxsize=1000)
    disconnected = asyncio.Event()
    server_sequence = 0
    last_flush = time.monotonic()
    audio_frame_count = 0
    total_audio_duration_ms = 0
    barge_in_count = 0

    ai_speaking = False
    ai_speaking_started_at: datetime | None = None
    interrupt_signal_at: datetime | None = None
    interrupt_signal_reason: str | None = None

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
                "timestamp": _normalize_ts(msg.timestamp).isoformat(),
                "payload": msg.payload,
            },
        )

    async def emit_session_state(payload: dict[str, Any]) -> None:
        nonlocal server_sequence
        body = {"session_id": session_id, **payload}
        server_sequence += 1
        await _send_event(websocket, "server.session.state", body, server_sequence)
        await ledger.buffer_event(
            session_id=session_id,
            event={
                "type": "server.session.state",
                "direction": EventDirection.SERVER.value,
                "sequence": server_sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": body,
            },
        )

    def set_interrupt(reason: str, ts: datetime | None = None) -> None:
        nonlocal interrupt_signal_at, interrupt_signal_reason
        if interrupt_signal_at is not None:
            return
        interrupt_signal_at = ts or datetime.now(timezone.utc)
        interrupt_signal_reason = reason

    def consume_interrupt() -> tuple[datetime | None, str | None]:
        nonlocal interrupt_signal_at, interrupt_signal_reason
        at = interrupt_signal_at
        reason = interrupt_signal_reason
        interrupt_signal_at = None
        interrupt_signal_reason = None
        return at, reason

    def _derive_rep_turn_window(msg: WsEvent) -> tuple[datetime, datetime]:
        rep_started_at = _normalize_ts(msg.timestamp)
        duration_ms = int(msg.payload.get("utterance_duration_ms", 0) or 0)
        if duration_ms <= 0:
            duration_ms = max(150, len(str(msg.payload.get("transcript_hint", ""))) * 22)
        rep_ended_at = rep_started_at + timedelta(milliseconds=duration_ms)
        return rep_started_at, rep_ended_at

    async def receive_loop() -> None:
        nonlocal ai_speaking
        while True:
            try:
                raw = await websocket.receive_json()
            except WebSocketDisconnect:
                disconnected.set()
                break
            except Exception:
                disconnected.set()
                logger.exception("WebSocket receive error", extra={"session_id": session_id})
                break

            try:
                msg = WsEvent.model_validate(raw)
            except Exception:
                logger.warning("Dropped malformed websocket message", extra={"session_id": session_id, "raw": raw})
                continue

            if msg.type == "client.vad.state" and bool(msg.payload.get("speaking", False)):
                set_interrupt("vad_speaking", _normalize_ts(msg.timestamp))
            elif ai_speaking and msg.type == "client.audio.chunk":
                set_interrupt("audio_chunk", _normalize_ts(msg.timestamp))

            if msg.type == "client.session.end":
                disconnected.set()

            await incoming.put(msg)

    receiver_task = asyncio.create_task(receive_loop())

    try:
        await emit_session_state({"state": "connected"})
        await maybe_flush()

        while True:
            if disconnected.is_set() and incoming.empty():
                break

            try:
                msg = await asyncio.wait_for(incoming.get(), timeout=0.25)
            except TimeoutError:
                await maybe_flush()
                continue

            if msg.type not in SUPPORTED_CLIENT_EVENTS:
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
                if speaking and ai_speaking:
                    set_interrupt("vad_speaking", _normalize_ts(msg.timestamp))
                await emit_session_state({"state": "rep_speaking" if speaking else "rep_idle"})
                await maybe_flush()
                continue

            if msg.type == "client.session.end":
                break

            consume_interrupt()

            stt_result = await providers.stt.finalize_utterance(msg.payload)
            rep_text = stt_result.text
            if not rep_text:
                server_sequence += 1
                await _send_event(
                    websocket,
                    "server.stt.partial",
                    {
                        "text": "",
                        "confidence": 0.0,
                        "message": "awaiting transcript",
                        "provider": providers.stt.provider_name,
                    },
                    server_sequence,
                )
                continue

            plan = orchestrator.prepare_rep_turn(session_id=session_id, rep_text=rep_text)
            next_turn_index = (db.scalar(select(func.count(SessionTurn.id)).where(SessionTurn.session_id == session_id)) or 0) + 1
            rep_started_at, rep_ended_at = _derive_rep_turn_window(msg)

            rep_turn = ledger.commit_turn(
                db,
                session_id=session_id,
                turn_index=next_turn_index,
                speaker=TurnSpeaker.REP,
                text=rep_text,
                stage=plan.stage_after,
                started_at=rep_started_at,
                ended_at=rep_ended_at,
                objection_tags=plan.objection_tags,
            )

            server_sequence += 1
            stt_final_payload = {
                "text": rep_text,
                "turn_id": rep_turn.id,
                "confidence": stt_result.confidence,
                "provider": stt_result.source,
            }
            await _send_event(websocket, "server.stt.final", stt_final_payload, server_sequence)
            await ledger.buffer_event(
                session_id=session_id,
                event={
                    "type": "server.stt.final",
                    "direction": EventDirection.SERVER.value,
                    "sequence": server_sequence,
                    "payload": stt_final_payload,
                },
            )
            await maybe_flush()

            if plan.stage_changed:
                await emit_session_state(
                    {
                        "state": plan.stage_after,
                        "transition": {"from": plan.stage_before, "to": plan.stage_after},
                    }
                )
                await maybe_flush()

            ai_text_parts: list[str] = []
            ai_started_at: datetime | None = None
            turn_audio_duration_ms = 0
            ai_interrupted = False

            ai_speaking = True
            ai_speaking_started_at = datetime.now(timezone.utc)
            await emit_session_state({"state": "ai_speaking", "stage": plan.stage_after})

            async for chunk in providers.llm.stream_reply(
                rep_text=rep_text,
                stage=plan.stage_after,
                system_prompt=plan.system_prompt,
            ):
                if interrupt_signal_at is not None:
                    ai_interrupted = True
                    break

                if not chunk:
                    continue
                if ai_started_at is None:
                    ai_started_at = datetime.now(timezone.utc)
                ai_text_parts.append(chunk)

                server_sequence += 1
                ai_text_payload = {
                    "token": chunk,
                    "provider": providers.llm.provider_name,
                    "stage": plan.stage_after,
                }
                await _send_event(websocket, "server.ai.text.delta", ai_text_payload, server_sequence)
                await ledger.buffer_event(
                    session_id=session_id,
                    event={
                        "type": "server.ai.text.delta",
                        "direction": EventDirection.SERVER.value,
                        "sequence": server_sequence,
                        "payload": ai_text_payload,
                    },
                )

                async for audio_chunk in providers.tts.stream_audio(chunk):
                    if interrupt_signal_at is not None:
                        ai_interrupted = True
                        break

                    audio_frame_count += 1
                    chunk_duration_ms = int(audio_chunk.get("duration_ms", 0))
                    total_audio_duration_ms += chunk_duration_ms
                    turn_audio_duration_ms += chunk_duration_ms

                    server_sequence += 1
                    ai_audio_payload = {
                        "codec": audio_chunk.get("codec", "pcm16"),
                        "payload": audio_chunk.get("payload", ""),
                        "provider": audio_chunk.get("provider", providers.tts.provider_name),
                        "duration_ms": int(audio_chunk.get("duration_ms", 0)),
                    }
                    await _send_event(websocket, "server.ai.audio.chunk", ai_audio_payload, server_sequence)
                    await ledger.buffer_event(
                        session_id=session_id,
                        event={
                            "type": "server.ai.audio.chunk",
                            "direction": EventDirection.SERVER.value,
                            "sequence": server_sequence,
                            "payload": ai_audio_payload,
                        },
                    )

                if ai_interrupted:
                    break
                await maybe_flush()

            interruption_payload: dict[str, Any] | None = None
            if ai_interrupted:
                barge_at, reason = consume_interrupt()
                barge_at = barge_at or datetime.now(timezone.utc)
                elapsed_ms = max(
                    0,
                    int((barge_at - (ai_speaking_started_at or barge_at)).total_seconds() * 1000),
                )
                barge_in_count += 1
                interruption_payload = {
                    "state": "barge_in_detected",
                    "reason": reason or "unknown",
                    "barge_in_count": barge_in_count,
                    "latency_ms": elapsed_ms,
                    "at": barge_at.isoformat(),
                }
                await emit_session_state(interruption_payload)
            else:
                consume_interrupt()

            ai_speaking = False
            await emit_session_state({"state": "ai_idle", "interrupted": ai_interrupted})

            ai_text = "".join(ai_text_parts).strip()
            if ai_interrupted and not ai_text:
                ai_text = "(response interrupted)"
            orchestrator.mark_ai_turn(session_id=session_id)
            ai_now = datetime.now(timezone.utc)
            ai_started_at = ai_started_at or ai_speaking_started_at or ai_now
            ai_duration_ms = max(120, turn_audio_duration_ms)
            ai_ended_at = ai_started_at + timedelta(milliseconds=ai_duration_ms)
            ai_turn = ledger.commit_turn(
                db,
                session_id=session_id,
                turn_index=next_turn_index + 1,
                speaker=TurnSpeaker.AI,
                text=ai_text,
                stage=plan.stage_after,
                started_at=ai_started_at,
                ended_at=max(ai_ended_at, ai_now),
                objection_tags=[],
            )

            server_sequence += 1
            turn_payload = {
                "rep_turn_id": rep_turn.id,
                "ai_turn_id": ai_turn.id,
                "session_id": session_id,
                "stage": plan.stage_after,
                "objection_tags": plan.objection_tags,
                "interrupted": ai_interrupted,
                "interruption": interruption_payload,
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
        receiver_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            logger.exception("Receiver task cleanup error", extra={"session_id": session_id})

        try:
            await maybe_flush(force=True)
            transcript_artifact = ledger.compact_session(db, session_id)

            db.add(
                SessionArtifact(
                    session_id=session_id,
                    artifact_type="audio",
                    storage_key=f"sessions/{session_id}/session_audio.opus",
                    metadata_json={
                        "codec": "opus",
                        "channels": 1,
                        "frame_count": audio_frame_count,
                        "duration_ms": total_audio_duration_ms,
                        "barge_in_count": barge_in_count,
                        "provider": providers.tts.provider_name,
                    },
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

            logger.info(
                "Session finalized",
                extra={
                    "session_id": session_id,
                    "transcript_artifact": transcript_artifact.storage_key,
                    "audio_frames": audio_frame_count,
                    "barge_in_count": barge_in_count,
                },
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to finalize websocket session", extra={"session_id": session_id})
            db.rollback()
        finally:
            db.close()
