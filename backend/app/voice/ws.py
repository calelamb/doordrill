from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import re
import time
import uuid
import zlib
from dataclasses import dataclass
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
from app.models.user import User
from app.schemas.knowledge import RetrievedChunk
from app.schemas.ws import WsEvent
from app.services.conversation_orchestrator import BehaviorDirectives, ConversationOrchestrator
from app.services.document_retrieval_service import DocumentRetrievalService
from app.services.ledger_buffer import InMemoryEventBuffer, RedisEventBuffer
from app.services.ledger_service import SessionLedgerService
from app.services.micro_behavior_engine import (
    ConversationalMicroBehaviorEngine,
    MicroBehaviorPlan,
    MicroBehaviorSegment,
)
from app.services.provider_clients import ProviderSuite
from app.services.session_postprocess_service import SessionPostprocessService
from app.services.storage_service import StorageService
from app.utils.latency import TurnLatencyRecord

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
micro_behavior_engine = ConversationalMicroBehaviorEngine()
postprocess_service = SessionPostprocessService()
providers = ProviderSuite.from_settings(settings)
storage_service = StorageService()

SILENCE_FILLER_SECONDS = 4.0
VAD_FINALIZE_DEBOUNCE_MS = 80
MAX_RUNTIME_PAUSE_MS = 60
TTS_STREAM_TIMEOUT_SECONDS = 6
WS_KEEPALIVE_TIMEOUT_SECONDS = 120
WS_KEEPALIVE_INTERVAL_SECONDS = 30


@dataclass
class SessionRuntimeState:
    _vad_end_pending: bool = False
    vad_finalize_task: asyncio.Task[None] | None = None
    turn_latency: TurnLatencyRecord | None = None


def homeowner_token_budget(stage: str) -> int:
    stage_budgets = {
        "door_knock": 15,
        "initial_pitch": 28,
        "objection_handling": 30,
        "considering": 45,
        "close_attempt": 40,
        "ended": 12,
    }
    return stage_budgets.get(stage, 28)


def _dedupe_retrieved_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: set[str] = set()
    ordered: list[RetrievedChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        ordered.append(chunk)
    return ordered


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


def _compress_prompt(text: str) -> str:
    return base64.b64encode(zlib.compress(text.encode("utf-8"), level=6)).decode("ascii")


async def _send_event(websocket: WebSocket, event_type: str, payload: dict[str, Any], sequence: int) -> None:
    await websocket.send_json(
        {
            "type": event_type,
            "sequence": sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
    )


def _serialize_micro_behavior(plan: MicroBehaviorPlan, *, segment: MicroBehaviorSegment | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tone": plan.tone,
        "sentence_length": plan.sentence_length,
        "behaviors": list(plan.behaviors),
        "interruption_type": plan.interruption_type,
        "pause_profile": dict(plan.pause_profile),
        "realism_score": plan.realism_score,
        "segment_count": len(plan.segments),
    }
    if segment is not None:
        payload.update(
            {
                "segment_index": segment.segment_index,
                "pause_before_ms": segment.pause_before_ms,
                "pause_after_ms": segment.pause_after_ms,
                "allow_barge_in": segment.allow_barge_in,
            }
        )
    return payload


def _serialize_behavior_directives(directives: BehaviorDirectives) -> dict[str, Any]:
    return {
        "tone": directives.tone,
        "sentence_length": directives.sentence_length,
        "interruption_mode": directives.interruption_mode,
    }


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
    rep = db.scalar(select(User).where(User.id == session.rep_id))
    company_context: str | None = None
    company_context_chunk_count = 0
    if rep is not None and rep.org_id:
        retrieval_service = DocumentRetrievalService(settings=settings)
        try:
            if retrieval_service.has_ready_documents(db, org_id=rep.org_id):
                loop = asyncio.get_event_loop()
                context_hint = scenario.name if scenario is not None else ""
                pricing_chunks = await loop.run_in_executor(
                    None,
                    lambda: retrieval_service.retrieve_for_topic(
                        db,
                        org_id=rep.org_id,
                        topic="pest control services pricing monthly plan what is included coverage",
                        context_hint=context_hint,
                        k=3,
                        min_score=0.65,
                    ),
                )
                competitor_chunks = await loop.run_in_executor(
                    None,
                    lambda: retrieval_service.retrieve_for_topic(
                        db,
                        org_id=rep.org_id,
                        topic="competitor comparison why choose us reviews common objections",
                        context_hint=context_hint,
                        k=2,
                        min_score=0.65,
                    ),
                )
                combined_chunks = _dedupe_retrieved_chunks([*pricing_chunks, *competitor_chunks])
                if combined_chunks:
                    formatted_context = retrieval_service.format_for_prompt(combined_chunks, max_tokens=600)
                    if formatted_context.strip():
                        company_context = formatted_context
                        company_context_chunk_count = len(combined_chunks)
        except Exception:
            logger.warning(
                "Failed to load homeowner company context",
                exc_info=True,
                extra={"session_id": session_id, "trace_id": ws_trace_id, "org_id": rep.org_id},
            )
            company_context = None
            company_context_chunk_count = 0
    orchestrator.bind_session_context(
        session_id=session_id,
        scenario=scenario,
        prompt_version=session.prompt_version,
        db=db,
        org_id=rep.org_id if rep is not None else None,
        rep_id=session.rep_id,
        company_context=company_context,
    )
    # Keep STT session-scoped to avoid Deepgram websocket cold starts on every rep turn.
    await providers.stt.start_session(session_id)
    micro_behavior_engine.initialize_session(
        session_id,
        persona=scenario.persona if scenario is not None and isinstance(scenario.persona, dict) else None,
    )

    incoming: asyncio.Queue[WsEvent] = asyncio.Queue(maxsize=1000)
    disconnected = asyncio.Event()
    server_sequence = 0
    last_flush = time.monotonic()
    audio_frame_count = 0
    total_audio_duration_ms = 0
    barge_in_count = 0
    runtime_state = SessionRuntimeState()

    ai_speaking = False
    ai_speaking_started_at: datetime | None = None
    interrupt_signal_at: datetime | None = None
    interrupt_signal_reason: str | None = None

    def _monotonic_ts() -> float:
        return time.monotonic()

    def _should_start_new_turn_latency() -> bool:
        record = runtime_state.turn_latency
        if record is None:
            return True
        return bool(
            ai_speaking
            or record.stt_final_ts is not None
            or record.llm_first_token_ts is not None
            or record.tts_task_created_ts is not None
            or record.first_audio_byte_ts is not None
        )

    def _start_turn_latency(turn_index: int | None = None) -> TurnLatencyRecord:
        record = TurnLatencyRecord(session_id=session_id, turn_index=turn_index or 0)
        runtime_state.turn_latency = record
        return record

    def _get_turn_latency(turn_index: int | None = None) -> TurnLatencyRecord:
        record = runtime_state.turn_latency
        if record is None:
            record = _start_turn_latency(turn_index)
        elif turn_index is not None and record.turn_index <= 0:
            record.turn_index = turn_index
        return record

    def _cancel_vad_finalize_task() -> asyncio.Task[None] | None:
        task = runtime_state.vad_finalize_task
        runtime_state.vad_finalize_task = None
        if task is not None:
            task.cancel()
        return task

    async def _run_vad_finalize_debounce() -> None:
        try:
            await asyncio.sleep(VAD_FINALIZE_DEBOUNCE_MS / 1000)
            if not runtime_state._vad_end_pending:
                return
            runtime_state._vad_end_pending = False
            await providers.stt.trigger_finalization()
        except asyncio.CancelledError:
            raise
        finally:
            if runtime_state.vad_finalize_task is asyncio.current_task():
                runtime_state.vad_finalize_task = None

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
        payload["session_id"] = session_id
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

    async def stream_ai_response(
        *,
        prompt_text: str,
        stage: str,
        system_prompt: str,
        emotion_before: str,
        emotion_after: str,
        behavioral_signals: list[str],
        active_objections: list[str],
    ) -> dict[str, Any]:
        nonlocal audio_frame_count, total_audio_duration_ms
        t0 = asyncio.get_event_loop().time()

        def _elapsed_ms() -> int:
            return int((asyncio.get_event_loop().time() - t0) * 1000)

        logger.info(
            "stream_ai_response_start",
            extra={
                "session_id": session_id,
                "elapsed_ms": 0,
            },
        )
        ai_text_parts: list[str] = []
        llm_started_at = datetime.now(timezone.utc)
        ai_started_at: datetime | None = None
        turn_audio_duration_ms = 0
        ai_interrupted = False
        last_behavior_plan: MicroBehaviorPlan | None = None
        tts_tasks: list[asyncio.Task[None]] = []
        tts_emit_lock = asyncio.Lock()
        persona_voice_id = None
        if scenario is not None and isinstance(scenario.persona, dict):
            raw_voice_id = scenario.persona.get("voice_id")
            if raw_voice_id:
                persona_voice_id = str(raw_voice_id)

        async def maybe_apply_pause(pause_ms: int) -> None:
            if pause_ms <= 0 or interrupt_signal_at is not None:
                return
            await asyncio.sleep(min(pause_ms, MAX_RUNTIME_PAUSE_MS) / 1000)

        def build_behavior_plan(raw_text: str) -> MicroBehaviorPlan:
            try:
                return micro_behavior_engine.apply_to_response(
                    session_id=session_id,
                    raw_text=raw_text,
                    emotion_before=emotion_before,
                    emotion_after=emotion_after,
                    behavioral_signals=behavioral_signals,
                    active_objections=active_objections,
                )
            except Exception as exc:
                logger.exception("Micro-behavior transform failed", extra={"session_id": session_id, "trace_id": ws_trace_id})
                fallback_segment = MicroBehaviorSegment(
                    text=raw_text,
                    pause_before_ms=0,
                    pause_after_ms=0,
                    tone="measured",
                    behaviors=["fallback_mode"],
                    sentence_length="medium",
                    segment_index=0,
                    segment_count=1,
                    interruption_type=None,
                    allow_barge_in=False,
                )
                return MicroBehaviorPlan(
                    transformed_text=raw_text,
                    tone="measured",
                    sentence_length="medium",
                    interruption_type=None,
                    behaviors=["fallback_mode"],
                    pause_profile={"opening_pause_ms": 0, "total_pause_ms": 0, "longest_pause_ms": 0},
                    realism_score=3.0,
                    segments=[fallback_segment],
                )

        async def stream_tts_for_plan(plan: MicroBehaviorPlan) -> None:
            nonlocal audio_frame_count, total_audio_duration_ms, turn_audio_duration_ms, ai_interrupted
            _task_start_time = asyncio.get_event_loop().time()
            sentence_text = plan.transformed_text.strip()
            sentence_chunk_count = 0
            _first_chunk_logged = False
            logger.info(
                "tts_task_started",
                extra={
                    "session_id": session_id,
                    "sentence": plan.transformed_text[:40],
                    "lock_locked": tts_emit_lock.locked(),
                },
            )
            logger.info(
                "stream_tts_for_plan_start",
                extra={
                    "session_id": session_id,
                    "trace_id": ws_trace_id,
                    "sentence_text": sentence_text,
                    "tts_provider": providers.tts.provider_name,
                },
            )
            try:
                async with tts_emit_lock:
                    for segment in plan.segments:
                        if interrupt_signal_at is not None:
                            ai_interrupted = True
                            return

                        await maybe_apply_pause(segment.pause_before_ms)
                        if interrupt_signal_at is not None:
                            ai_interrupted = True
                            return

                        segment_text = segment.text.strip()
                        if not segment_text:
                            continue

                        segment_behavior = _serialize_micro_behavior(plan, segment=segment)
                        tts_text = segment_text
                        if persona_voice_id and tts_text and not tts_text.startswith("[[voice:"):
                            tts_text = f"[[voice:{persona_voice_id}]] {tts_text}"
                        logger.info(
                            "stream_tts_for_plan_stream_audio_call",
                            extra={
                                "session_id": session_id,
                                "trace_id": ws_trace_id,
                                "sentence_text": sentence_text,
                                "segment_index": segment.segment_index,
                                "tts_provider": providers.tts.provider_name,
                                "calling_stream_audio": True,
                                "tts_text": tts_text,
                            },
                        )
                        logger.info(
                            "tts_elevenlabs_call",
                            extra={
                                "session_id": session_id,
                                "sentence": segment_text[:40],
                                "pause_before_ms": segment.pause_before_ms,
                                "pause_after_ms": segment.pause_after_ms,
                                "elapsed_since_task_start_ms": int((asyncio.get_event_loop().time() - _task_start_time) * 1000),
                            },
                        )

                        try:
                            async with asyncio.timeout(TTS_STREAM_TIMEOUT_SECONDS):
                                async for audio_chunk in providers.tts.stream_audio(tts_text):
                                    if interrupt_signal_at is not None:
                                        ai_interrupted = True
                                        return
                                    if not _first_chunk_logged:
                                        _t_before = asyncio.get_event_loop().time()
                                        logger.info(
                                            "tts_before_first_send",
                                            extra={
                                                "session_id": session_id,
                                                "elapsed_from_t0_ms": int((_t_before - _task_start_time) * 1000),
                                            },
                                        )
                                    sentence_chunk_count += 1
                                    chunk_duration_ms = int(audio_chunk.get("duration_ms", 0) or 0)
                                    audio_frame_count += 1
                                    total_audio_duration_ms += chunk_duration_ms
                                    turn_audio_duration_ms += chunk_duration_ms
                                    await emit_server_event(
                                        "server.ai.audio.chunk",
                                        {
                                            "codec": audio_chunk.get("codec", "pcm16"),
                                            "payload": audio_chunk.get("payload", ""),
                                            "provider": audio_chunk.get("provider", providers.tts.provider_name),
                                            "duration_ms": chunk_duration_ms,
                                            "trace_id": ws_trace_id,
                                            "micro_behavior": segment_behavior,
                                        },
                                    )
                                    record = runtime_state.turn_latency
                                    if record is not None and record.first_audio_byte_ts is None:
                                        record.first_audio_byte_ts = _monotonic_ts()
                                        record.log_summary(logger)
                                    if not _first_chunk_logged:
                                        _t_after = asyncio.get_event_loop().time()
                                        logger.info(
                                            "tts_after_first_send",
                                            extra={
                                                "session_id": session_id,
                                                "send_duration_ms": int((_t_after - _t_before) * 1000),
                                                "elapsed_from_t0_ms": int((_t_after - _task_start_time) * 1000),
                                            },
                                        )
                                    await asyncio.sleep(0)
                                    if not _first_chunk_logged:
                                        _first_chunk_logged = True
                        except TimeoutError:
                            logger.warning(
                                "TTS stream exceeded timeout; committing turn with truncated audio",
                                extra={
                                    "session_id": session_id,
                                    "trace_id": ws_trace_id,
                                    "timeout_seconds": TTS_STREAM_TIMEOUT_SECONDS,
                                    "sentence_text": sentence_text,
                                    "segment_index": segment.segment_index,
                                    "tts_provider": providers.tts.provider_name,
                                    "audio_chunks_emitted": sentence_chunk_count,
                                },
                            )
                        except asyncio.CancelledError:
                            return
                        except Exception as exc:
                            logger.exception(
                                "stream_tts_for_plan_exception",
                                extra={
                                    "session_id": session_id,
                                    "trace_id": ws_trace_id,
                                    "sentence_text": sentence_text,
                                    "segment_index": segment.segment_index,
                                    "tts_provider": providers.tts.provider_name,
                                    "audio_chunks_emitted": sentence_chunk_count,
                                    "error": str(exc),
                                },
                            )
                            await emit_error("tts_error", str(exc), retryable=True)
                            await maybe_flush()

                        if ai_interrupted:
                            return

                        await maybe_apply_pause(segment.pause_after_ms)
                        if interrupt_signal_at is not None:
                            ai_interrupted = True
                            return
            finally:
                logger.info(
                    "stream_tts_for_plan_complete",
                    extra={
                        "session_id": session_id,
                        "trace_id": ws_trace_id,
                        "sentence_text": sentence_text,
                        "tts_provider": providers.tts.provider_name,
                        "audio_chunks_emitted": sentence_chunk_count,
                        "ai_interrupted": ai_interrupted,
                    },
                )

        async def process_sentence(raw_sentence: str) -> None:
            nonlocal ai_started_at, last_behavior_plan
            sentence = raw_sentence.strip()
            if not sentence:
                return
            record = runtime_state.turn_latency
            if record is not None and record.first_sentence_ts is None:
                record.first_sentence_ts = _monotonic_ts()
            logger.info(
                "process_sentence_called",
                extra={
                    "session_id": session_id,
                    "sentence": sentence[:40],
                    "elapsed_ms": _elapsed_ms(),
                },
            )
            plan = build_behavior_plan(sentence)
            last_behavior_plan = plan
            orchestrator.update_last_mb_plan(session_id, plan)
            transformed_text = plan.transformed_text.strip()
            if not transformed_text:
                return

            if ai_started_at is None:
                ai_started_at = datetime.now(timezone.utc)

            if ai_text_parts:
                ai_text_parts.append(" ")
            ai_text_parts.append(transformed_text)

            await emit_server_event(
                "server.ai.text.delta",
                {
                    "token": transformed_text,
                    "provider": providers.llm.provider_name,
                    "stage": stage,
                    "trace_id": ws_trace_id,
                    "micro_behavior": _serialize_micro_behavior(plan),
                },
            )
            await maybe_flush()
            if record is not None and record.tts_task_created_ts is None:
                record.tts_task_created_ts = _monotonic_ts()
            tts_tasks.append(asyncio.create_task(stream_tts_for_plan(plan)))
            logger.info(
                "tts_task_created",
                extra={
                    "session_id": session_id,
                    "sentence": sentence[:40],
                    "lock_locked": tts_emit_lock.locked(),
                },
            )

        sentence_buffer = ""
        try:
            async for chunk in providers.llm.stream_reply(
                rep_text=prompt_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=homeowner_token_budget(stage),
            ):
                if interrupt_signal_at is not None:
                    ai_interrupted = True
                    break
                if not chunk:
                    continue
                record = runtime_state.turn_latency
                if record is not None and record.llm_first_token_ts is None:
                    record.llm_first_token_ts = _monotonic_ts()
                sentence_buffer += str(chunk)
                while True:
                    match = re.search(r"[.?!](?:\s|$)", sentence_buffer)
                    if match is None:
                        break
                    sentence = sentence_buffer[:match.end()].strip()
                    sentence_buffer = sentence_buffer[match.end():].lstrip()
                    await process_sentence(sentence)
        except Exception as exc:
            await emit_error("llm_error", str(exc), retryable=True)
            await maybe_flush()

        if sentence_buffer.strip() and not ai_interrupted:
            await process_sentence(sentence_buffer.strip())

        logger.info(
            "emitting_text_done",
            extra={
                "session_id": session_id,
                "elapsed_ms": _elapsed_ms(),
            },
        )
        await emit_server_event(
            "server.ai.text.done",
            {
                "provider": providers.llm.provider_name,
                "stage": stage,
                "trace_id": ws_trace_id,
            },
        )
        await maybe_flush()

        if tts_tasks:
            try:
                await asyncio.gather(*tts_tasks)
            except asyncio.CancelledError:
                for task in tts_tasks:
                    task.cancel()
                await asyncio.gather(*tts_tasks, return_exceptions=True)

        duration_ms = max(
            120,
            int(((datetime.now(timezone.utc)) - (ai_started_at or llm_started_at)).total_seconds() * 1000),
        )
        return {
            "text": "".join(ai_text_parts).strip(),
            "started_at": ai_started_at,
            "duration_ms": duration_ms,
            "interrupted": ai_interrupted,
            "micro_behavior": _serialize_micro_behavior(last_behavior_plan) if last_behavior_plan is not None else None,
        }

    async def maybe_emit_silence_filler() -> bool:
        nonlocal ai_speaking, ai_speaking_started_at, barge_in_count, filler_emitted_for_silence
        if disconnected.is_set() or ai_speaking or not has_rep_audio or filler_emitted_for_silence:
            return False
        if (time.monotonic() - last_rep_audio_at) < SILENCE_FILLER_SECONDS:
            return False

        state = orchestrator.get_state(session_id)
        stage = state.stage
        emotion = state.emotion
        active_objections = list(state.active_objections)
        system_prompt = orchestrator._build_system_prompt(stage_after=stage, session_id=session_id)
        ai_speaking = True
        ai_speaking_started_at = datetime.now(timezone.utc)
        await emit_session_state({"state": "ai_speaking", "stage": stage, "filler": True})
        filler_result = await stream_ai_response(
            prompt_text="generate a natural homeowner filler for awkward silence",
            stage=stage,
            system_prompt=system_prompt,
            emotion_before=emotion,
            emotion_after=emotion,
            behavioral_signals=list(state.last_behavior_signals),
            active_objections=active_objections,
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
            if ai_turn.speaker == TurnSpeaker.AI:
                ai_turn.system_prompt_snapshot = _compress_prompt(system_prompt)
                db.commit()
                db.refresh(ai_turn)
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
                    "emotion_before": emotion,
                    "emotion_after": emotion,
                    "behavioral_signals": list(state.last_behavior_signals),
                    "micro_behavior": filler_result["micro_behavior"],
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

            if msg.type == "client.vad.state":
                speaking = bool(msg.payload.get("speaking", False))
                if speaking:
                    runtime_state._vad_end_pending = False
                    _cancel_vad_finalize_task()
                    set_interrupt("vad_speaking", _normalize_ts(msg.timestamp))
                else:
                    runtime_state._vad_end_pending = True
                    record = _start_turn_latency() if _should_start_new_turn_latency() else _get_turn_latency()
                    if record.vad_end_ts is None:
                        record.vad_end_ts = _monotonic_ts()
                    _cancel_vad_finalize_task()
                    runtime_state.vad_finalize_task = asyncio.create_task(_run_vad_finalize_debounce())
            elif ai_speaking and msg.type == "client.audio.chunk":
                set_interrupt("audio_chunk", _normalize_ts(msg.timestamp))

            if msg.type == "client.session.end":
                disconnected.set()
                runtime_state._vad_end_pending = False
                _cancel_vad_finalize_task()

            await incoming.put(msg)

    has_rep_audio = False
    filler_emitted_for_silence = False
    last_rep_audio_at = time.monotonic()
    receiver_task = asyncio.create_task(receive_loop())

    async def keepalive_loop() -> None:
        while not disconnected.is_set():
            await asyncio.sleep(WS_KEEPALIVE_INTERVAL_SECONDS)
            if disconnected.is_set():
                break
            try:
                await emit_session_state(
                    {
                        "state": "keepalive",
                        "keepalive_timeout_seconds": WS_KEEPALIVE_TIMEOUT_SECONDS,
                    }
                )
                await maybe_flush()
            except Exception:  # pragma: no cover
                logger.exception("WebSocket keepalive failed", extra={"session_id": session_id, "trace_id": ws_trace_id})
                break

    keepalive_task = asyncio.create_task(keepalive_loop())

    try:
        await emit_session_state({"state": "connected", **orchestrator.get_state_payload(session_id)})
        await maybe_flush()
        if company_context is not None:
            await emit_server_event("server.session.rag_context_loaded", {"chunks_loaded": company_context_chunk_count})
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
            if _should_start_new_turn_latency():
                _start_turn_latency()

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

            plan = orchestrator.prepare_rep_turn(session_id=session_id, rep_text=rep_text, db=db)
            if plan.active_edge_cases:
                await emit_server_event("server.edge_case.triggered", {"tags": plan.active_edge_cases})
                await maybe_flush()
            next_turn_index = _next_turn_index()
            turn_latency = _get_turn_latency(next_turn_index + 1)
            if turn_latency.stt_final_ts is None:
                turn_latency.stt_final_ts = _monotonic_ts()
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
                        **orchestrator.get_state_payload(session_id),
                    }
                )
                await maybe_flush()

            await emit_session_state(
                {
                    "state": "homeowner_state_updated",
                    **orchestrator.get_state_payload(session_id),
                    "emotion_before": plan.emotion_before,
                    "emotion_after": plan.emotion_after,
                    "emotion_changed": plan.emotion_changed,
                    "behavioral_signals": plan.behavioral_signals,
                    "behavior_directives": _serialize_behavior_directives(plan.behavior_directives),
                    "objection_tags": plan.objection_tags,
                    "resolved_objections_this_turn": plan.resolved_objections,
                    "objection_pressure_before": plan.objection_pressure_before,
                    "objection_pressure_after": plan.objection_pressure_after,
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
                emotion_before=plan.emotion_before,
                emotion_after=plan.emotion_after,
                behavioral_signals=plan.behavioral_signals,
                active_objections=plan.active_objections,
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
            if ai_turn.speaker == TurnSpeaker.AI:
                ai_turn.system_prompt_snapshot = _compress_prompt(plan.system_prompt)
                db.commit()
                db.refresh(ai_turn)

            turn_payload = {
                "rep_turn_id": rep_turn.id,
                "ai_turn_id": ai_turn.id,
                "session_id": session_id,
                "stage": plan.stage_after,
                "objection_tags": plan.objection_tags,
                "interrupted": ai_result["interrupted"],
                "interruption": interruption_payload,
                "trace_id": ws_trace_id,
                "emotion_before": plan.emotion_before,
                "emotion_after": plan.emotion_after,
                "behavioral_signals": plan.behavioral_signals,
                "micro_behavior": ai_result["micro_behavior"],
            }
            await emit_server_event("server.turn.committed", turn_payload)
            if runtime_state.turn_latency is not None and runtime_state.turn_latency.turn_index == next_turn_index + 1:
                runtime_state.turn_latency = None
            await maybe_flush()

    except WebSocketDisconnect:
        pass
    finally:
        pending_vad_finalize_task = _cancel_vad_finalize_task()
        receiver_task.cancel()
        keepalive_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            logger.exception("Receiver task cleanup error", extra={"session_id": session_id, "trace_id": ws_trace_id})
        if pending_vad_finalize_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await pending_vad_finalize_task
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            logger.exception("Keepalive task cleanup error", extra={"session_id": session_id, "trace_id": ws_trace_id})

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
            micro_behavior_engine.end_session(session_id)
            orchestrator.clear_session_context(session_id)
            await providers.stt.end_session(session_id)
            db.close()
