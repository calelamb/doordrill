from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.types import AssignmentStatus, EventDirection, SessionStatus, TurnSpeaker


def create_assignment_and_session(seed_org: dict[str, str]) -> tuple[str, str]:
    db = SessionLocal()
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "turn_enrichment_test"},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        started_at = datetime.now(timezone.utc) - timedelta(minutes=15)
        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=6),
            duration_seconds=360,
            status=SessionStatus.GRADED,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return assignment.id, session.id
    finally:
        db.close()


def seed_hostile_enrichment_session(seed_org: dict[str, str]) -> dict[str, str]:
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        assert session is not None

        base = session.started_at
        rep_turn_1 = SessionTurn(
            session_id=session.id,
            turn_index=1,
            speaker=TurnSpeaker.REP,
            stage="objection_handling",
            text="Totally fair. A lot of homeowners ask about price first because they want real value.",
            started_at=base + timedelta(minutes=1),
            ended_at=base + timedelta(minutes=1, seconds=12),
            objection_tags=["price"],
        )
        ai_turn_1 = SessionTurn(
            session_id=session.id,
            turn_index=2,
            speaker=TurnSpeaker.AI,
            stage="objection_handling",
            text="Okay, that makes sense. What actually makes your service different?",
            started_at=base + timedelta(minutes=1, seconds=13),
            ended_at=base + timedelta(minutes=1, seconds=28),
            objection_tags=[],
        )
        rep_turn_2 = SessionTurn(
            session_id=session.id,
            turn_index=3,
            speaker=TurnSpeaker.REP,
            stage="close_attempt",
            text="If we can get this started today, would you want to lock it in now?",
            started_at=base + timedelta(minutes=3),
            ended_at=base + timedelta(minutes=3, seconds=8),
            objection_tags=["timing"],
        )
        ai_turn_2 = SessionTurn(
            session_id=session.id,
            turn_index=4,
            speaker=TurnSpeaker.AI,
            stage="close_attempt",
            text="Wait, hold on. I'm not ready to do that right now.",
            started_at=base + timedelta(minutes=3, seconds=9),
            ended_at=base + timedelta(minutes=3, seconds=22),
            objection_tags=[],
        )
        db.add_all([rep_turn_1, ai_turn_1, rep_turn_2, ai_turn_2])
        db.commit()
        for turn in (rep_turn_1, ai_turn_1, rep_turn_2, ai_turn_2):
            db.refresh(turn)

        db.add_all(
            [
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-connected",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=1,
                    event_ts=base,
                    payload={
                        "state": "connected",
                        "stage": "door_knock",
                        "emotion": "skeptical",
                        "resistance_level": 3,
                        "objection_pressure": 3,
                        "active_objections": ["price"],
                        "queued_objections": ["trust"],
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-homeowner-1",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=2,
                    event_ts=base + timedelta(minutes=1, seconds=12),
                    payload={
                        "state": "homeowner_state_updated",
                        "stage": "objection_handling",
                        "emotion": "curious",
                        "resistance_level": 2,
                        "objection_pressure": 1,
                        "active_objections": [],
                        "queued_objections": ["trust"],
                        "emotion_before": "skeptical",
                        "emotion_after": "curious",
                        "behavioral_signals": ["acknowledges_concern", "explains_value"],
                        "objection_tags": ["price"],
                        "resolved_objections_this_turn": ["price"],
                        "objection_pressure_before": 3,
                        "objection_pressure_after": 1,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-commit-1",
                    event_type="server.turn.committed",
                    direction=EventDirection.SERVER,
                    sequence=3,
                    event_ts=base + timedelta(minutes=1, seconds=29),
                    payload={
                        "rep_turn_id": rep_turn_1.id,
                        "ai_turn_id": ai_turn_1.id,
                        "stage": "objection_handling",
                        "emotion_before": "skeptical",
                        "emotion_after": "curious",
                        "behavioral_signals": ["acknowledges_concern", "explains_value"],
                        "objection_tags": ["price"],
                        "interrupted": False,
                        "micro_behavior": {
                            "tone": "warming",
                            "sentence_length": "long",
                            "behaviors": ["tone_shift"],
                            "interruption_type": None,
                            "pause_profile": {"opening_pause_ms": 180, "total_pause_ms": 420},
                            "realism_score": 8.4,
                        },
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-homeowner-2",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=4,
                    event_ts=base + timedelta(minutes=3, seconds=8),
                    payload={
                        "state": "homeowner_state_updated",
                        "stage": "close_attempt",
                        "transition": {"from": "objection_handling", "to": "close_attempt"},
                        "emotion": "hostile",
                        "resistance_level": 5,
                        "objection_pressure": 4,
                        "active_objections": ["timing"],
                        "queued_objections": ["trust", "decision_authority"],
                        "emotion_before": "curious",
                        "emotion_after": "hostile",
                        "behavioral_signals": ["pushes_close", "ignores_objection"],
                        "objection_tags": ["timing"],
                        "resolved_objections_this_turn": [],
                        "objection_pressure_before": 1,
                        "objection_pressure_after": 4,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-barge-in",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=5,
                    event_ts=base + timedelta(minutes=3, seconds=12),
                    payload={
                        "state": "barge_in_detected",
                        "stage": "close_attempt",
                        "emotion": "hostile",
                        "resistance_level": 5,
                        "objection_pressure": 4,
                        "active_objections": ["timing"],
                        "queued_objections": ["trust", "decision_authority"],
                        "reason": "vad_speaking",
                        "barge_in_count": 1,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-commit-2",
                    event_type="server.turn.committed",
                    direction=EventDirection.SERVER,
                    sequence=6,
                    event_ts=base + timedelta(minutes=3, seconds=23),
                    payload={
                        "rep_turn_id": rep_turn_2.id,
                        "ai_turn_id": ai_turn_2.id,
                        "stage": "close_attempt",
                        "emotion_before": "curious",
                        "emotion_after": "hostile",
                        "behavioral_signals": ["pushes_close", "ignores_objection"],
                        "objection_tags": ["timing"],
                        "interrupted": True,
                        "interruption": {"reason": "vad_speaking", "barge_in_count": 1},
                        "micro_behavior": {
                            "tone": "confrontational",
                            "sentence_length": "short",
                            "behaviors": ["interruption"],
                            "interruption_type": "homeowner_cuts_off_rep",
                            "pause_profile": {"opening_pause_ms": 40, "total_pause_ms": 120},
                            "realism_score": 2.7,
                        },
                    },
                ),
                Scorecard(
                    session_id=session.id,
                    overall_score=7.3,
                    category_scores={
                        "opening": {"score": 8.2, "evidence_turn_ids": [rep_turn_1.id]},
                        "pitch_delivery": {"score": 7.6, "evidence_turn_ids": [rep_turn_1.id]},
                        "objection_handling": {"score": 6.1, "evidence_turn_ids": [rep_turn_2.id]},
                        "closing_technique": {"score": 5.4, "evidence_turn_ids": [rep_turn_2.id]},
                        "professionalism": {"score": 7.1, "evidence_turn_ids": [rep_turn_1.id, rep_turn_2.id]},
                    },
                    highlights=[{"type": "improve", "note": "Handle timing before trying to close.", "turn_id": rep_turn_2.id}],
                    ai_summary="Useful rep energy, but the close came too early after objection pressure rose.",
                    evidence_turn_ids=[rep_turn_1.id, rep_turn_2.id],
                    weakness_tags=["objection_handling", "closing_technique"],
                ),
            ]
        )
        db.commit()
        return {
            "session_id": session.id,
            "rep_turn_1_id": rep_turn_1.id,
            "ai_turn_1_id": ai_turn_1.id,
            "rep_turn_2_id": rep_turn_2.id,
            "ai_turn_2_id": ai_turn_2.id,
        }
    finally:
        db.close()


def seed_interested_enrichment_session(seed_org: dict[str, str]) -> dict[str, str]:
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        assert session is not None

        base = session.started_at
        rep_turn = SessionTurn(
            session_id=session.id,
            turn_index=1,
            speaker=TurnSpeaker.REP,
            stage="objection_handling",
            text="That makes sense. If timing is the issue, we can start with a lighter plan and prove it first.",
            started_at=base + timedelta(minutes=1),
            ended_at=base + timedelta(minutes=1, seconds=14),
            objection_tags=["timing"],
        )
        ai_turn = SessionTurn(
            session_id=session.id,
            turn_index=2,
            speaker=TurnSpeaker.AI,
            stage="objection_handling",
            text="Okay, that feels more reasonable. Send me the details and I can look at it tonight.",
            started_at=base + timedelta(minutes=1, seconds=15),
            ended_at=base + timedelta(minutes=1, seconds=30),
            objection_tags=[],
        )
        db.add_all([rep_turn, ai_turn])
        db.commit()
        db.refresh(rep_turn)
        db.refresh(ai_turn)

        db.add_all(
            [
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-interested-connected",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=1,
                    event_ts=base,
                    payload={
                        "state": "connected",
                        "stage": "objection_handling",
                        "emotion": "skeptical",
                        "resistance_level": 4,
                        "objection_pressure": 2,
                        "active_objections": ["timing"],
                        "queued_objections": [],
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-interested-homeowner",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=2,
                    event_ts=base + timedelta(minutes=1, seconds=14),
                    payload={
                        "state": "homeowner_state_updated",
                        "stage": "objection_handling",
                        "emotion": "interested",
                        "resistance_level": 1,
                        "objection_pressure": 0,
                        "active_objections": [],
                        "queued_objections": [],
                        "emotion_before": "skeptical",
                        "emotion_after": "interested",
                        "behavioral_signals": ["asks_for_follow_up", "engaged"],
                        "objection_tags": ["timing"],
                        "resolved_objections_this_turn": ["timing"],
                        "objection_pressure_before": 2,
                        "objection_pressure_after": 0,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-interested-commit",
                    event_type="server.turn.committed",
                    direction=EventDirection.SERVER,
                    sequence=3,
                    event_ts=base + timedelta(minutes=1, seconds=31),
                    payload={
                        "rep_turn_id": rep_turn.id,
                        "ai_turn_id": ai_turn.id,
                        "stage": "objection_handling",
                        "emotion_before": "skeptical",
                        "emotion_after": "interested",
                        "behavioral_signals": ["asks_for_follow_up", "engaged"],
                        "objection_tags": ["timing"],
                        "interrupted": False,
                        "micro_behavior": {
                            "tone": "natural",
                            "sentence_length": "medium",
                            "behaviors": ["pace_match"],
                            "interruption_type": None,
                            "pause_profile": {"opening_pause_ms": 210, "total_pause_ms": 390},
                            "realism_score": 9.1,
                        },
                    },
                ),
                Scorecard(
                    session_id=session.id,
                    overall_score=8.8,
                    category_scores={
                        "objection_handling": {"score": 8.9, "evidence_turn_ids": [rep_turn.id]},
                        "professionalism": {"score": 8.6, "evidence_turn_ids": [rep_turn.id]},
                    },
                    highlights=[{"type": "win", "note": "Rep slowed down and de-pressured the close.", "turn_id": rep_turn.id}],
                    ai_summary="Rep relieved timing pressure and converted the conversation into next-step interest.",
                    evidence_turn_ids=[rep_turn.id],
                    weakness_tags=[],
                ),
            ]
        )
        db.commit()
        return {
            "session_id": session.id,
            "rep_turn_id": rep_turn.id,
            "ai_turn_id": ai_turn.id,
        }
    finally:
        db.close()
