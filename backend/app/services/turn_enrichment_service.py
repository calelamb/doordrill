from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.transcript import FactTurnEvent


@dataclass
class TimelineState:
    stage: str | None = None
    emotion: str | None = None
    resistance_level: int | None = None
    objection_pressure: int | None = None
    active_objections: list[str] = field(default_factory=list)
    queued_objections: list[str] = field(default_factory=list)
    resolved_objections: list[str] = field(default_factory=list)
    behavioral_signals: list[str] = field(default_factory=list)

    def clone(self) -> "TimelineState":
        return TimelineState(
            stage=self.stage,
            emotion=self.emotion,
            resistance_level=self.resistance_level,
            objection_pressure=self.objection_pressure,
            active_objections=list(self.active_objections),
            queued_objections=list(self.queued_objections),
            resolved_objections=list(self.resolved_objections),
            behavioral_signals=list(self.behavioral_signals),
        )


@dataclass
class StatePoint:
    occurred_at: datetime
    state: TimelineState


@dataclass
class TurnCommitContext:
    occurred_at: datetime
    before_state: TimelineState
    after_state: TimelineState
    rep_turn_id: str | None
    ai_turn_id: str | None
    stage_before: str | None
    stage_after: str | None
    emotion_before: str | None
    emotion_after: str | None
    behavioral_signals: list[str]
    objection_tags: list[str]
    resolved_objections: list[str]
    pressure_before: int | None
    pressure_after: int | None
    interrupted: bool
    interruption: dict[str, Any] | None
    micro_behavior: dict[str, Any]


@dataclass
class ReconstructedTimeline:
    points: list[StatePoint]
    turn_contexts: list[TurnCommitContext]
    turn_context_by_id: dict[str, TurnCommitContext]
    final_state: TimelineState

    def get_state_at(self, occurred_at: datetime) -> TimelineState:
        if not self.points:
            return self.final_state.clone()

        selected = self.points[0].state
        for point in self.points:
            if point.occurred_at > occurred_at:
                break
            selected = point.state
        return selected.clone()


class TurnEnrichmentService:
    """Populate enriched turn columns and fact turn events from the immutable event ledger."""

    def enrich_session(self, db: Session, session_id: str) -> dict[str, int]:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None:
            raise ValueError("session not found")

        events = self._load_ordered_events(db, session_id)
        turns = self._load_turns(db, session_id)
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        evidence_map = self._build_evidence_map(scorecard)
        timeline = self._reconstruct_state_timeline(events)

        for turn in turns:
            context = timeline.turn_context_by_id.get(turn.id)
            fallback_state = timeline.get_state_at(turn.started_at)
            self._enrich_turn(turn=turn, context=context, fallback_state=fallback_state, scorecard=scorecard, evidence_map=evidence_map)

        fact_event_count = self._write_fact_turn_events(
            db,
            session=session,
            timeline=timeline,
        )
        db.commit()
        return {"turn_count": len(turns), "fact_event_count": fact_event_count}

    def _load_ordered_events(self, db: Session, session_id: str) -> list[SessionEvent]:
        return db.scalars(
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.event_ts.asc(), SessionEvent.sequence.asc(), SessionEvent.id.asc())
        ).all()

    def _load_turns(self, db: Session, session_id: str) -> list[SessionTurn]:
        return db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())
        ).all()

    def _reconstruct_state_timeline(self, events: list[SessionEvent]) -> ReconstructedTimeline:
        current_state = TimelineState()
        points: list[StatePoint] = []
        turn_contexts: list[TurnCommitContext] = []
        turn_context_by_id: dict[str, TurnCommitContext] = {}
        pending_turn_context: TurnCommitContext | None = None
        pending_barge_in: dict[str, Any] | None = None

        for event in events:
            payload = self._coerce_dict(event.payload)
            if event.event_type == "server.session.state":
                before_state = current_state.clone()
                state_changed = False
                stage_transition = self._coerce_dict(payload.get("transition"))

                stage = self._coerce_str(payload.get("stage"))
                if stage is not None:
                    current_state.stage = stage
                    state_changed = True

                emotion = self._coerce_str(payload.get("emotion"))
                if emotion is not None:
                    current_state.emotion = emotion
                    state_changed = True

                resistance_level = self._coerce_int(payload.get("resistance_level"))
                if resistance_level is not None:
                    current_state.resistance_level = resistance_level
                    state_changed = True

                pressure_after = self._coerce_int(payload.get("objection_pressure_after"))
                objection_pressure = pressure_after
                if objection_pressure is None:
                    objection_pressure = self._coerce_int(payload.get("objection_pressure"))
                if objection_pressure is not None:
                    current_state.objection_pressure = objection_pressure
                    state_changed = True

                active_objections = self._coerce_list(payload.get("active_objections"))
                if active_objections is not None:
                    current_state.active_objections = active_objections
                    state_changed = True

                queued_objections = self._coerce_list(payload.get("queued_objections"))
                if queued_objections is not None:
                    current_state.queued_objections = queued_objections
                    state_changed = True

                resolved_objections = self._coerce_list(payload.get("resolved_objections"))
                if resolved_objections is not None:
                    current_state.resolved_objections = resolved_objections
                    state_changed = True

                behavioral_signals = self._coerce_list(payload.get("behavioral_signals"))
                if behavioral_signals is not None:
                    current_state.behavioral_signals = behavioral_signals

                if state_changed:
                    points.append(StatePoint(occurred_at=event.event_ts, state=current_state.clone()))

                if payload.get("state") == "barge_in_detected":
                    pending_barge_in = payload

                if any(
                    key in payload
                    for key in (
                        "emotion_before",
                        "emotion_after",
                        "behavioral_signals",
                        "objection_tags",
                        "resolved_objections_this_turn",
                        "objection_pressure_before",
                        "objection_pressure_after",
                    )
                ):
                    pending_turn_context = TurnCommitContext(
                        occurred_at=event.event_ts,
                        before_state=before_state,
                        after_state=current_state.clone(),
                        rep_turn_id=None,
                        ai_turn_id=None,
                        stage_before=self._coerce_str(stage_transition.get("from")) or before_state.stage,
                        stage_after=self._coerce_str(stage_transition.get("to")) or current_state.stage,
                        emotion_before=self._coalesce(
                            self._coerce_str(payload.get("emotion_before")),
                            before_state.emotion,
                            current_state.emotion,
                        ),
                        emotion_after=self._coalesce(
                            self._coerce_str(payload.get("emotion_after")),
                            current_state.emotion,
                        ),
                        behavioral_signals=list(
                            behavioral_signals if behavioral_signals is not None else current_state.behavioral_signals
                        ),
                        objection_tags=list(self._coerce_list(payload.get("objection_tags")) or []),
                        resolved_objections=list(self._coerce_list(payload.get("resolved_objections_this_turn")) or []),
                        pressure_before=self._coalesce_int(
                            self._coerce_int(payload.get("objection_pressure_before")),
                            before_state.objection_pressure,
                        ),
                        pressure_after=self._coalesce_int(
                            self._coerce_int(payload.get("objection_pressure_after")),
                            current_state.objection_pressure,
                        ),
                        interrupted=False,
                        interruption=None,
                        micro_behavior={},
                    )
                continue

            if event.event_type != "server.turn.committed":
                continue

            micro_behavior = self._coerce_dict(payload.get("micro_behavior"))
            fallback_context = pending_turn_context or TurnCommitContext(
                occurred_at=event.event_ts,
                before_state=current_state.clone(),
                after_state=current_state.clone(),
                rep_turn_id=None,
                ai_turn_id=None,
                stage_before=current_state.stage,
                stage_after=current_state.stage,
                emotion_before=current_state.emotion,
                emotion_after=current_state.emotion,
                behavioral_signals=list(current_state.behavioral_signals),
                objection_tags=self._coerce_list(payload.get("objection_tags")) or [],
                resolved_objections=[],
                pressure_before=current_state.objection_pressure,
                pressure_after=current_state.objection_pressure,
                interrupted=False,
                interruption=None,
                micro_behavior={},
            )
            context = TurnCommitContext(
                occurred_at=event.event_ts,
                before_state=fallback_context.before_state.clone(),
                after_state=fallback_context.after_state.clone(),
                rep_turn_id=self._coerce_str(payload.get("rep_turn_id")),
                ai_turn_id=self._coerce_str(payload.get("ai_turn_id")),
                stage_before=fallback_context.stage_before,
                stage_after=self._coalesce(
                    self._coerce_str(payload.get("stage")),
                    fallback_context.stage_after,
                    current_state.stage,
                ),
                emotion_before=self._coalesce(
                    self._coerce_str(payload.get("emotion_before")),
                    fallback_context.emotion_before,
                    fallback_context.before_state.emotion,
                    current_state.emotion,
                ),
                emotion_after=self._coalesce(
                    self._coerce_str(payload.get("emotion_after")),
                    fallback_context.emotion_after,
                    fallback_context.after_state.emotion,
                    current_state.emotion,
                ),
                behavioral_signals=list(
                    self._coerce_list(payload.get("behavioral_signals"))
                    if self._coerce_list(payload.get("behavioral_signals")) is not None
                    else fallback_context.behavioral_signals
                ),
                objection_tags=list(
                    self._coerce_list(payload.get("objection_tags"))
                    if self._coerce_list(payload.get("objection_tags")) is not None
                    else fallback_context.objection_tags
                ),
                resolved_objections=list(fallback_context.resolved_objections),
                pressure_before=fallback_context.pressure_before,
                pressure_after=fallback_context.pressure_after,
                interrupted=bool(payload.get("interrupted")),
                interruption=self._coerce_dict(payload.get("interruption")) or pending_barge_in,
                micro_behavior=micro_behavior,
            )
            turn_contexts.append(context)
            if context.rep_turn_id:
                turn_context_by_id[context.rep_turn_id] = context
            if context.ai_turn_id:
                turn_context_by_id[context.ai_turn_id] = context
            pending_turn_context = None
            pending_barge_in = None

        return ReconstructedTimeline(
            points=points,
            turn_contexts=turn_contexts,
            turn_context_by_id=turn_context_by_id,
            final_state=current_state.clone(),
        )

    def _enrich_turn(
        self,
        *,
        turn: SessionTurn,
        context: TurnCommitContext | None,
        fallback_state: TimelineState,
        scorecard: Scorecard | None,
        evidence_map: dict[str, list[str]],
    ) -> None:
        enriched_state = context.after_state.clone() if context is not None else fallback_state.clone()
        micro_behavior = context.micro_behavior if context is not None else {}
        pause_profile = self._coerce_dict(micro_behavior.get("pause_profile"))
        evidence_categories = evidence_map.get(turn.id, [])
        directly_referenced = bool(scorecard and turn.id in (scorecard.evidence_turn_ids or []))
        active_objections = enriched_state.active_objections if context is not None else fallback_state.active_objections
        queued_objections = enriched_state.queued_objections if context is not None else fallback_state.queued_objections
        behavioral_signals = context.behavioral_signals if context is not None else fallback_state.behavioral_signals

        turn.stage = context.stage_after if context and context.stage_after else enriched_state.stage or turn.stage
        turn.emotion_before = (
            context.emotion_before
            if context and context.emotion_before is not None
            else fallback_state.emotion or enriched_state.emotion or turn.emotion_before
        )
        turn.emotion_after = (
            context.emotion_after
            if context and context.emotion_after is not None
            else enriched_state.emotion or turn.emotion_before or turn.emotion_after
        )
        turn.emotion_changed = bool(turn.emotion_before and turn.emotion_after and turn.emotion_before != turn.emotion_after)
        turn.resistance_level = enriched_state.resistance_level if enriched_state.resistance_level is not None else fallback_state.resistance_level
        turn.objection_pressure = (
            context.pressure_after
            if context and context.pressure_after is not None
            else enriched_state.objection_pressure if enriched_state.objection_pressure is not None else fallback_state.objection_pressure
        )
        turn.active_objections = list(active_objections)
        turn.queued_objections = list(queued_objections)
        turn.mb_tone = self._coerce_str(micro_behavior.get("tone"))
        turn.mb_sentence_length = self._coerce_str(micro_behavior.get("sentence_length"))
        turn.mb_behaviors = self._coerce_list(micro_behavior.get("behaviors")) or []
        turn.mb_interruption_type = self._coerce_str(micro_behavior.get("interruption_type"))
        if turn.mb_interruption_type is None and context and (context.interrupted or context.interruption):
            turn.mb_interruption_type = "barge_in"
        turn.mb_realism_score = self._coerce_float(micro_behavior.get("realism_score"))
        turn.mb_opening_pause_ms = self._coerce_int(pause_profile.get("opening_pause_ms"))
        turn.mb_total_pause_ms = self._coerce_int(pause_profile.get("total_pause_ms"))
        turn.behavioral_signals = list(behavioral_signals)
        turn.was_graded = directly_referenced or bool(evidence_categories)
        turn.evidence_for_categories = list(evidence_categories)
        turn.is_high_quality = (scorecard.overall_score >= 8.0) if turn.was_graded and scorecard is not None else None

    def _build_evidence_map(self, scorecard: Scorecard | None) -> dict[str, list[str]]:
        evidence_map: dict[str, list[str]] = {}
        if scorecard is None or not isinstance(scorecard.category_scores, dict):
            return evidence_map

        for category_key, payload in scorecard.category_scores.items():
            if not isinstance(payload, dict):
                continue
            for turn_id in payload.get("evidence_turn_ids", []):
                if not isinstance(turn_id, str) or not turn_id:
                    continue
                evidence_map.setdefault(turn_id, []).append(category_key)

        for categories in evidence_map.values():
            categories[:] = sorted(set(categories))
        return evidence_map

    def _write_fact_turn_events(
        self,
        db: Session,
        *,
        session: DrillSession,
        timeline: ReconstructedTimeline,
    ) -> int:
        db.execute(delete(FactTurnEvent).where(FactTurnEvent.session_id == session.id))

        org_id = session.rep.org_id if session.rep is not None else None
        items: list[FactTurnEvent] = []

        for context in timeline.turn_contexts:
            primary_turn_id = context.rep_turn_id or context.ai_turn_id
            realism_turn_id = context.ai_turn_id or primary_turn_id
            resistance_delta = self._delta(context.before_state.resistance_level, context.after_state.resistance_level)
            pressure_delta = self._delta(context.pressure_before, context.pressure_after)
            surfaced_objections = sorted(set(context.after_state.active_objections) - set(context.before_state.active_objections))
            resolved_objections = list(context.resolved_objections) or sorted(
                set(context.before_state.active_objections) - set(context.after_state.active_objections)
            )
            realism_score = self._coerce_float(context.micro_behavior.get("realism_score"))
            common = {
                "session_id": session.id,
                "rep_id": session.rep_id,
                "org_id": org_id,
                "emotion_before": context.emotion_before,
                "emotion_after": context.emotion_after,
                "stage_before": context.stage_before or context.before_state.stage,
                "stage_after": context.stage_after or context.after_state.stage,
                "resistance_delta": resistance_delta,
                "pressure_delta": pressure_delta,
                "mb_realism_score": realism_score,
                "signal_tags": list(context.behavioral_signals),
            }

            if context.emotion_before and context.emotion_after and context.emotion_before != context.emotion_after:
                items.append(
                    self._fact_event(
                        event_type="emotion_transition",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"objection_tags": list(context.objection_tags)},
                        **common,
                    )
                )

            for tag in surfaced_objections:
                items.append(
                    self._fact_event(
                        event_type="objection_surfaced",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        objection_tag=tag,
                        objection_resolved=False,
                        context_json={"active_objections": list(context.after_state.active_objections)},
                        **common,
                    )
                )

            for tag in resolved_objections:
                items.append(
                    self._fact_event(
                        event_type="objection_resolved",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        objection_tag=tag,
                        objection_resolved=True,
                        context_json={"resolved_objections": list(resolved_objections)},
                        **common,
                    )
                )

            if common["stage_before"] and common["stage_after"] and common["stage_before"] != common["stage_after"]:
                items.append(
                    self._fact_event(
                        event_type="stage_advance",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"from": common["stage_before"], "to": common["stage_after"]},
                        **common,
                    )
                )
            elif primary_turn_id and (context.behavioral_signals or context.objection_tags):
                items.append(
                    self._fact_event(
                        event_type="stage_stall",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"stage": common["stage_after"]},
                        **common,
                    )
                )

            if resistance_delta is not None and resistance_delta >= 2:
                items.append(
                    self._fact_event(
                        event_type="resistance_spike",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"resistance_before": context.before_state.resistance_level, "resistance_after": context.after_state.resistance_level},
                        **common,
                    )
                )
            elif resistance_delta is not None and resistance_delta < 0:
                items.append(
                    self._fact_event(
                        event_type="resistance_drop",
                        turn_id=primary_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"resistance_before": context.before_state.resistance_level, "resistance_after": context.after_state.resistance_level},
                        **common,
                    )
                )

            if context.interrupted or context.interruption:
                items.append(
                    self._fact_event(
                        event_type="barge_in",
                        turn_id=realism_turn_id,
                        occurred_at=context.occurred_at,
                        context_json=dict(context.interruption or {}),
                        **common,
                    )
                )

            if realism_score is not None and realism_score >= 8.0:
                items.append(
                    self._fact_event(
                        event_type="high_realism_turn",
                        turn_id=realism_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"micro_behavior": dict(context.micro_behavior)},
                        **common,
                    )
                )
            elif realism_score is not None and realism_score <= 3.0:
                items.append(
                    self._fact_event(
                        event_type="low_realism_turn",
                        turn_id=realism_turn_id,
                        occurred_at=context.occurred_at,
                        context_json={"micro_behavior": dict(context.micro_behavior)},
                        **common,
                    )
                )

        final_emotion = timeline.final_state.emotion
        if not final_emotion and timeline.turn_contexts:
            final_emotion = timeline.turn_contexts[-1].emotion_after

        if final_emotion == "hostile":
            items.append(
                self._fact_event(
                    event_type="session_ended_hostile",
                    session_id=session.id,
                    turn_id=None,
                    rep_id=session.rep_id,
                    org_id=org_id,
                    occurred_at=session.ended_at or datetime.now(timezone.utc),
                    emotion_before=None,
                    emotion_after=final_emotion,
                    stage_before=None,
                    stage_after=timeline.final_state.stage,
                    resistance_delta=None,
                    pressure_delta=None,
                    mb_realism_score=None,
                    signal_tags=[],
                    context_json={},
                )
            )
        elif final_emotion in {"interested", "curious"}:
            items.append(
                self._fact_event(
                    event_type="session_ended_interested",
                    session_id=session.id,
                    turn_id=None,
                    rep_id=session.rep_id,
                    org_id=org_id,
                    occurred_at=session.ended_at or datetime.now(timezone.utc),
                    emotion_before=None,
                    emotion_after=final_emotion,
                    stage_before=None,
                    stage_after=timeline.final_state.stage,
                    resistance_delta=None,
                    pressure_delta=None,
                    mb_realism_score=None,
                    signal_tags=[],
                    context_json={},
                )
            )

        db.add_all(items)
        return len(items)

    def _fact_event(
        self,
        *,
        event_type: str,
        session_id: str,
        turn_id: str | None,
        rep_id: str,
        org_id: str | None,
        occurred_at: datetime,
        emotion_before: str | None,
        emotion_after: str | None,
        stage_before: str | None,
        stage_after: str | None,
        resistance_delta: int | None,
        pressure_delta: int | None,
        mb_realism_score: float | None,
        signal_tags: list[str],
        context_json: dict[str, Any],
        objection_tag: str | None = None,
        objection_resolved: bool | None = None,
    ) -> FactTurnEvent:
        return FactTurnEvent(
            session_id=session_id,
            turn_id=turn_id,
            rep_id=rep_id,
            org_id=org_id,
            event_type=event_type,
            occurred_at=occurred_at,
            emotion_before=emotion_before,
            emotion_after=emotion_after,
            objection_tag=objection_tag,
            objection_resolved=objection_resolved,
            stage_before=stage_before,
            stage_after=stage_after,
            resistance_delta=resistance_delta,
            pressure_delta=pressure_delta,
            mb_realism_score=mb_realism_score,
            signal_tags=signal_tags,
            context_json=context_json,
        )

    def _delta(self, before: int | None, after: int | None) -> int | None:
        if before is None or after is None:
            return None
        return after - before

    def _coerce_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _coerce_list(self, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            return []
        items = [str(item).strip() for item in value if str(item).strip()]
        return list(dict.fromkeys(items))

    def _coerce_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_float(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coalesce(self, *values: str | None) -> str | None:
        for value in values:
            if value is not None:
                return value
        return None

    def _coalesce_int(self, *values: int | None) -> int | None:
        for value in values:
            if value is not None:
                return value
        return None
