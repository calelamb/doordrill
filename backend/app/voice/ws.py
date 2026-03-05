from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.core.auth import resolve_ws_actor_with_query
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionTurn
from app.models.types import AssignmentStatus, EventDirection, SessionStatus, TurnSpeaker
from app.schemas.ws import WsEvent
from app.services.conversation_orchestrator import ConversationOrchestrator
from app.services.ledger_buffer import InMemoryEventBuffer, RedisEventBuffer
from app.services.ledger_service import SessionLedgerService
from app.services.provider_clients import ProviderSuite
from app.services.session_postprocess_service import SessionPostprocessService
from app.services.storage_service import StorageService

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
postprocess_service = SessionPostprocessService()
providers = ProviderSuite.from_settings(settings)
storage_service = StorageService()

SILENCE_FILLER_SECONDS = 4.0
TTS_SEGMENT_MIN_CHARS = 24


def _normalize_ts(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _resolve_trace_id(headers: Any) -> str:
    traceparent = headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) == 4 and len(parts[1]) == 32:
            return parts[1]
    trace_id = headers.get("x-trace-id")
    if trace_id:
        return trace_id
    return uuid.uuid4().hex


async def _send_event(websocket: WebSocket, event_type: str, payload: dict[str, Any], sequence: int) -> None:
    await websocket.send_json(
        {
            "type": event_type,
            "sequence": sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
    )


def _should_flush_tts_segment(buffer: str) -> bool:
    text = buffer.strip()
    if not text:
        return False
    if len(text) >= TTS_SEGMENT_MIN_CHARS:
        return True
    return text.endswith((".", "!", "?", ";", ":"))


@router.websocket("/ws/sessions/{session_id}")
@router.websocket("/ws/session/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    db = SessionLocal()
    actor = resolve_ws_actor_with_query(websocket.headers, websocket.query_params, db)
    if actor is None:
        await websocket.close(code=4401)
        db.close()
        return
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        await websocket.close(code=4404)
        db.close()
        return
    if actor.role == "rep" and actor.user_id and actor.user_id != session.rep_id:
        await websocket.close(code=4403)
        db.close()
        return
    if actor.role == "manager":
        await websocket.close(code=4403)
        db.close()
        return

    await websocket.accept()
    ws_trace_id = _resolve_trace_id(websocket.headers)

    scenario = db.scalar(select(Scenario).where(Scenario.id == session.scenario_id))
    orchestrator.bind_session_context(
        session_id=session_id,
        scenario=scenario,
        prompt_version=session.prompt_version,
    )

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

    async def emit_server_event(event_type: str, payload: dict[str, Any]) -> None:
        nonlocal server_sequence
        server_sequence += 1
        await _send_event(websocket, event_type, payload, server_sequence)
        await ledger.buffer_event(
            session_id=session_id,
            event={
                "type": event_type,
                "direction": EventDirection.SERVER.value,
                "sequence": server_sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            },
        )

    async def emit_session_state(payload: dict[str, Any]) -> None:
        await emit_server_event("server.session.state", {"session_id": session_id, "trace_id": ws_trace_id, **payload})

    async def emit_error(code: str, message: str, *, retryable: bool = True, details: dict[str, Any] | None = None) -> None:
        payload = {"code": code, "message": message, "retryable": retryable, "trace_id": ws_trace_id}
        if details:
            payload["details"] = details
        await emit_server_event("server.error", payload)

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

    def _next_turn_index() -> int:
        return (db.scalar(select(func.count(SessionTurn.id)).where(SessionTurn.session_id == session_id)) or 0) + 1

    async def run_stt(msg: WsEvent):
        partials: asyncio.Queue[str] = asyncio.Queue()
        payload = dict(msg.payload)
        last_partial = ""

        def on_partial(transcript: str, _: bool) -> None:
            text = str(transcript).strip()
            if not text:
                return
            with contextlib.suppress(asyncio.QueueFull):
                partials.put_nowait(text)

        payload["on_partial"] = on_partial
        if providers.stt.provider_name == "mock_stt":
            hint = str(payload.get("transcript_hint", "")).strip()
            if hint:
                on_partial(hint, False)

        stt_task = asyncio.create_task(providers.stt.finalize_utterance(payload))
        while not stt_task.done() or not partials.empty():
            try:
                partial = await asyncio.wait_for(partials.get(), timeout=0.05)
            except TimeoutError:
                await maybe_flush()
                continue

            partial = partial.strip()
            if not partial or partial == last_partial:
                continue
            last_partial = partial
            await emit_server_event(
                "server.stt.partial",
                {
                    "text": partial,
                    "confidence": 0.0,
                    "provider": providers.stt.provider_name,
                    "trace_id": ws_trace_id,
                },
            )
            await maybe_flush()

        try:
            return await stt_task
        except Exception as exc:
            await emit_error("stt_error", str(exc), retryable=True)
            return None

    async def stream_ai_response(*, prompt_text: str, stage: str, system_prompt: str) -> dict[str, Any]:
        nonlocal audio_frame_count, total_audio_duration_ms
        ai_text_parts: list[str] = []
        ai_started_at: datetime | None = None
        turn_audio_duration_ms = 0
        ai_interrupted = False
        output_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        tts_segments: asyncio.Queue[str | None] = asyncio.Queue()
        persona_voice_id = None
        if scenario is not None and isinstance(scenario.persona, dict):
            raw_voice_id = scenario.persona.get("voice_id")
            if raw_voice_id:
                persona_voice_id = str(raw_voice_id)

        async def llm_worker() -> None:
            segment_buffer = ""
            try:
                async for chunk in providers.llm.stream_reply(
                    rep_text=prompt_text,
                    stage=stage,
                    system_prompt=system_prompt,
                ):
                    if interrupt_signal_at is not None:
                        return
                    if not chunk:
                        continue
                    await output_queue.put(("text", chunk))
                    segment_buffer += chunk
                    if _should_flush_tts_segment(segment_buffer):
                        await tts_segments.put(segment_buffer)
                        segment_buffer = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await output_queue.put(("error", {"code": "llm_error", "message": str(exc)}))
            finally:
                if segment_buffer.strip():
                    await tts_segments.put(segment_buffer)
                await tts_segments.put(None)

        async def tts_worker() -> None:
            try:
                while True:
                    segment = await tts_segments.get()
                    if segment is None:
                        return
                    if interrupt_signal_at is not None:
                        return

                    segment_text = segment.strip()
                    if persona_voice_id and segment_text and not segment_text.startswith("[[voice:"):
                        segment_text = f"[[voice:{persona_voice_id}]] {segment_text}"

                    async for audio_chunk in providers.tts.stream_audio(segment_text):
                        if interrupt_signal_at is not None:
                            return
                        await output_queue.put(("audio", audio_chunk))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await output_queue.put(("error", {"code": "tts_error", "message": str(exc)}))

        llm_task = asyncio.create_task(llm_worker())
        tts_task = asyncio.create_task(tts_worker())
        try:
            while True:
                if interrupt_signal_at is not None:
                    ai_interrupted = True
                    llm_task.cancel()
                    tts_task.cancel()
                    break
                if llm_task.done() and tts_task.done() and output_queue.empty():
                    break
                try:
                    kind, payload = await asyncio.wait_for(output_queue.get(), timeout=0.05)
                except TimeoutError:
                    await maybe_flush()
                    continue

                if kind == "error":
                    await emit_error(payload.get("code", "provider_error"), payload.get("message", "provider failure"), retryable=True)
                    await maybe_flush()
                    continue

                if ai_started_at is None:
                    ai_started_at = datetime.now(timezone.utc)

                if kind == "text":
                    token = str(payload)
                    ai_text_parts.append(token)
                    await emit_server_event(
                        "server.ai.text.delta",
                        {
                            "token": token,
                            "provider": providers.llm.provider_name,
                            "stage": stage,
                            "trace_id": ws_trace_id,
                        },
                    )
                elif kind == "audio":
                    chunk_duration_ms = int(payload.get("duration_ms", 0) or 0)
                    audio_frame_count += 1
                    total_audio_duration_ms += chunk_duration_ms
                    turn_audio_duration_ms += chunk_duration_ms
                    await emit_server_event(
                        "server.ai.audio.chunk",
                        {
                            "codec": payload.get("codec", "pcm16"),
                            "payload": payload.get("payload", ""),
                            "provider": payload.get("provider", providers.tts.provider_name),
                            "duration_ms": chunk_duration_ms,
                            "trace_id": ws_trace_id,
                        },
                    )
                await maybe_flush()
        finally:
            for task in (llm_task, tts_task):
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        return {
            "text": "".join(ai_text_parts).strip(),
            "started_at": ai_started_at,
            "duration_ms": max(120, turn_audio_duration_ms),
            "interrupted": ai_interrupted,
        }

    async def maybe_emit_silence_filler() -> bool:
        nonlocal ai_speaking, ai_speaking_started_at, barge_in_count, filler_emitted_for_silence
        if disconnected.is_set() or ai_speaking or not has_rep_audio or filler_emitted_for_silence:
            return False
        if (time.monotonic() - last_rep_audio_at) < SILENCE_FILLER_SECONDS:
            return False

        stage = orchestrator.get_state(session_id).stage
        system_prompt = orchestrator._build_system_prompt(stage_after=stage, session_id=session_id)
        ai_speaking = True
        ai_speaking_started_at = datetime.now(timezone.utc)
        await emit_session_state({"state": "ai_speaking", "stage": stage, "filler": True})
        filler_result = await stream_ai_response(
            prompt_text="generate a natural homeowner filler for awkward silence",
            stage=stage,
            system_prompt=system_prompt,
        )

        interruption_payload: dict[str, Any] | None = None
        if filler_result["interrupted"]:
            barge_at, reason = consume_interrupt()
            barge_at = barge_at or datetime.now(timezone.utc)
            barge_in_count += 1
            interruption_payload = {
                "state": "barge_in_detected",
                "reason": reason or "unknown",
                "barge_in_count": barge_in_count,
                "latency_ms": max(0, int((barge_at - (ai_speaking_started_at or barge_at)).total_seconds() * 1000)),
                "at": barge_at.isoformat(),
                "trace_id": ws_trace_id,
                "filler": True,
            }
            await emit_session_state(interruption_payload)
        else:
            consume_interrupt()

        ai_speaking = False
        await emit_session_state({"state": "ai_idle", "interrupted": filler_result["interrupted"], "filler": True})

        ai_text = filler_result["text"]
        if filler_result["interrupted"] and not ai_text:
            filler_emitted_for_silence = True
            return True

        if ai_text:
            orchestrator.mark_ai_turn(session_id=session_id)
            now = datetime.now(timezone.utc)
            ai_started_at = filler_result["started_at"] or ai_speaking_started_at or now
            ai_turn = ledger.commit_turn(
                db,
                session_id=session_id,
                turn_index=_next_turn_index(),
                speaker=TurnSpeaker.AI,
                text=ai_text,
                stage=stage,
                started_at=ai_started_at,
                ended_at=max(ai_started_at + timedelta(milliseconds=filler_result["duration_ms"]), now),
                objection_tags=["silence_filler"],
            )
            await emit_server_event(
                "server.turn.committed",
                {
                    "rep_turn_id": None,
                    "ai_turn_id": ai_turn.id,
                    "session_id": session_id,
                    "stage": stage,
                    "objection_tags": ["silence_filler"],
                    "interrupted": filler_result["interrupted"],
                    "interruption": interruption_payload,
                    "trace_id": ws_trace_id,
                    "filler": True,
                },
            )
            await maybe_flush()

        filler_emitted_for_silence = True
        return True

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
                logger.exception("WebSocket receive error", extra={"session_id": session_id, "trace_id": ws_trace_id})
                break

            try:
                msg = WsEvent.model_validate(raw)
            except Exception:
                logger.warning(
                    "Dropped malformed websocket message",
                    extra={"session_id": session_id, "trace_id": ws_trace_id, "raw": raw},
                )
                continue

            if msg.type == "client.vad.state" and bool(msg.payload.get("speaking", False)):
                set_interrupt("vad_speaking", _normalize_ts(msg.timestamp))
            elif ai_speaking and msg.type == "client.audio.chunk":
                set_interrupt("audio_chunk", _normalize_ts(msg.timestamp))

            if msg.type == "client.session.end":
                disconnected.set()

            await incoming.put(msg)

    has_rep_audio = False
    filler_emitted_for_silence = False
    last_rep_audio_at = time.monotonic()
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
                if await maybe_emit_silence_filler():
                    await maybe_flush()
                    continue
                await maybe_flush()
                continue

            if msg.type not in SUPPORTED_CLIENT_EVENTS:
                await emit_error("bad_event", f"unsupported event type: {msg.type}", retryable=True)
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

            has_rep_audio = True
            filler_emitted_for_silence = False
            last_rep_audio_at = time.monotonic()
            consume_interrupt()

            stt_result = await run_stt(msg)
            if stt_result is None:
                continue
            rep_text = stt_result.text
            if not rep_text:
                await emit_server_event(
                    "server.stt.partial",
                    {
                        "text": "",
                        "confidence": 0.0,
                        "message": "awaiting transcript",
                        "provider": providers.stt.provider_name,
                        "trace_id": ws_trace_id,
                    },
                )
                continue

            plan = orchestrator.prepare_rep_turn(session_id=session_id, rep_text=rep_text)
            next_turn_index = _next_turn_index()
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

            stt_final_payload = {
                "text": rep_text,
                "turn_id": rep_turn.id,
                "confidence": stt_result.confidence,
                "provider": stt_result.source,
                "trace_id": ws_trace_id,
            }
            await emit_server_event("server.stt.final", stt_final_payload)
            await maybe_flush()

            if plan.stage_changed:
                await emit_session_state(
                    {
                        "state": plan.stage_after,
                        "transition": {"from": plan.stage_before, "to": plan.stage_after},
                    }
                )
                await maybe_flush()

            ai_speaking = True
            ai_speaking_started_at = datetime.now(timezone.utc)
            await emit_session_state({"state": "ai_speaking", "stage": plan.stage_after})
            ai_result = await stream_ai_response(
                prompt_text=rep_text,
                stage=plan.stage_after,
                system_prompt=plan.system_prompt,
            )

            interruption_payload: dict[str, Any] | None = None
            if ai_result["interrupted"]:
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
                    "trace_id": ws_trace_id,
                }
                await emit_session_state(interruption_payload)
            else:
                consume_interrupt()

            ai_speaking = False
            await emit_session_state({"state": "ai_idle", "interrupted": ai_result["interrupted"]})

            ai_text = ai_result["text"]
            if ai_result["interrupted"] and not ai_text:
                ai_text = "(response interrupted)"
            orchestrator.mark_ai_turn(session_id=session_id)
            ai_now = datetime.now(timezone.utc)
            ai_started_at = ai_result["started_at"] or ai_speaking_started_at or ai_now
            ai_duration_ms = ai_result["duration_ms"]
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

            turn_payload = {
                "rep_turn_id": rep_turn.id,
                "ai_turn_id": ai_turn.id,
                "session_id": session_id,
                "stage": plan.stage_after,
                "objection_tags": plan.objection_tags,
                "interrupted": ai_result["interrupted"],
                "interruption": interruption_payload,
                "trace_id": ws_trace_id,
            }
            await emit_server_event("server.turn.committed", turn_payload)
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
            logger.exception("Receiver task cleanup error", extra={"session_id": session_id, "trace_id": ws_trace_id})

        try:
            await maybe_flush(force=True)
            transcript_artifact = ledger.compact_session(db, session_id)
            audio_storage_key = f"sessions/{session_id}/session_audio.opus"
            audio_upload = storage_service.upload_audio(audio_storage_key, content_type="audio/ogg")

            db.add(
                SessionArtifact(
                    session_id=session_id,
                    artifact_type="audio",
                    storage_key=audio_storage_key,
                    metadata_json={
                        "codec": "opus",
                        "channels": 1,
                        "frame_count": audio_frame_count,
                        "duration_ms": total_audio_duration_ms,
                        "barge_in_count": barge_in_count,
                        "provider": providers.tts.provider_name,
                        "upload": audio_upload,
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

            postprocess_result = None
            if session is not None:
                postprocess_result = await postprocess_service.enqueue_or_run(db, session_id=session_id)

            logger.info(
                "Session finalized",
                extra={
                    "session_id": session_id,
                    "transcript_artifact": transcript_artifact.storage_key,
                    "audio_frames": audio_frame_count,
                    "barge_in_count": barge_in_count,
                    "postprocess_mode": postprocess_result["mode"] if postprocess_result else "none",
                    "trace_id": ws_trace_id,
                },
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to finalize websocket session", extra={"session_id": session_id, "trace_id": ws_trace_id})
            db.rollback()
        finally:
            orchestrator.clear_session_context(session_id)
            db.close()
