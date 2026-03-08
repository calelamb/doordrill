from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.training import OverrideLabel
from app.models.types import AssignmentStatus, ReviewReason, SessionStatus, TurnSpeaker
from app.models.user import User
from app.services.manager_action_service import ManagerActionService


def _seed_exportable_override(seed_org: dict[str, str]) -> dict[str, str]:
    db = SessionLocal()
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "training_export_test"},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=5),
            duration_seconds=300,
            status=SessionStatus.GRADED,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        db.add_all(
            [
                SessionTurn(
                    session_id=session.id,
                    turn_index=1,
                    speaker=TurnSpeaker.REP,
                    stage="objection_handling",
                    text="I hear you on price. Let me show you why the monthly plan saves repeat headaches.",
                    started_at=started_at + timedelta(minutes=1),
                    ended_at=started_at + timedelta(minutes=1, seconds=12),
                    objection_tags=["price"],
                    emotion_before="skeptical",
                    emotion_after="curious",
                    emotion_changed=True,
                    resistance_level=2,
                    objection_pressure=1,
                    active_objections=[],
                    queued_objections=["trust"],
                    mb_tone="steady",
                    mb_sentence_length="medium",
                    mb_behaviors=["acknowledges_concern"],
                    mb_interruption_type=None,
                    mb_realism_score=8.2,
                    mb_opening_pause_ms=120,
                    mb_total_pause_ms=340,
                    behavioral_signals=["acknowledges_concern", "anchors_value"],
                    was_graded=True,
                    evidence_for_categories=["objection_handling"],
                    is_high_quality=True,
                ),
                SessionTurn(
                    session_id=session.id,
                    turn_index=2,
                    speaker=TurnSpeaker.AI,
                    stage="objection_handling",
                    text="That helps. If the service is really consistent, I could be open to it.",
                    started_at=started_at + timedelta(minutes=1, seconds=13),
                    ended_at=started_at + timedelta(minutes=1, seconds=28),
                    objection_tags=[],
                    emotion_before="curious",
                    emotion_after="interested",
                    emotion_changed=True,
                    resistance_level=1,
                    objection_pressure=0,
                    active_objections=[],
                    queued_objections=[],
                    mb_tone="natural",
                    mb_sentence_length="medium",
                    mb_behaviors=["engaged"],
                    mb_interruption_type=None,
                    mb_realism_score=8.9,
                    mb_opening_pause_ms=180,
                    mb_total_pause_ms=360,
                    behavioral_signals=["engaged"],
                    was_graded=False,
                    evidence_for_categories=[],
                    is_high_quality=None,
                ),
            ]
        )

        scorecard = Scorecard(
            session_id=session.id,
            overall_score=6.1,
            scorecard_schema_version="v2",
            category_scores={
                "opening": {
                    "score": 6.0,
                    "confidence": 0.66,
                    "rationale_summary": "Adequate opener",
                    "rationale_detail": "The rep got to the point but could have earned more trust first.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": [],
                    "improvement_target": "Lead with context",
                },
                "pitch_delivery": {
                    "score": 6.4,
                    "confidence": 0.7,
                    "rationale_summary": "Clear enough",
                    "rationale_detail": "Value was present but still somewhat generic.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": ["anchors_value"],
                    "improvement_target": "Use specifics",
                },
                "objection_handling": {
                    "score": 6.8,
                    "confidence": 0.78,
                    "rationale_summary": "Decent reframing",
                    "rationale_detail": "The rep acknowledged the objection and reframed to value.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": ["acknowledges_concern"],
                    "improvement_target": "Confirm agreement",
                },
                "closing_technique": {
                    "score": 5.5,
                    "confidence": 0.61,
                    "rationale_summary": "Weak close",
                    "rationale_detail": "No concrete next step was secured.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": [],
                    "improvement_target": "Ask for next step",
                },
                "professionalism": {
                    "score": 6.7,
                    "confidence": 0.74,
                    "rationale_summary": "Professional tone",
                    "rationale_detail": "The rep stayed calm and credible throughout the turn.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": ["acknowledges_concern"],
                    "improvement_target": None,
                },
            },
            highlights=[
                {"type": "strong", "note": "You acknowledged the concern quickly.", "turn_id": None},
                {"type": "improve", "note": "Push to a clearer next step.", "turn_id": None},
            ],
            ai_summary="You handled the objection reasonably well but did not convert it into a concrete close.",
            evidence_turn_ids=[],
            weakness_tags=["closing_technique"],
        )
        db.add(scorecard)

        prompt_version = db.scalar(
            select(PromptVersion).where(
                PromptVersion.prompt_type == "grading_v2",
                PromptVersion.version == "1.0.0",
            )
        )
        assert prompt_version is not None
        db.commit()
        db.refresh(scorecard)

        grading_run = GradingRun(
            session_id=session.id,
            scorecard_id=scorecard.id,
            prompt_version_id=prompt_version.id,
            model_name="gpt-test",
            model_latency_ms=120,
            input_token_count=400,
            output_token_count=250,
            status="success",
            raw_llm_response="{}",
            parse_error=None,
            overall_score=6.1,
            confidence_score=0.72,
            started_at=started_at + timedelta(minutes=4),
            completed_at=started_at + timedelta(minutes=4, seconds=4),
        )
        db.add(grading_run)
        db.commit()
        db.refresh(grading_run)

        manager = db.get(User, seed_org["manager_id"])
        assert manager is not None

        review = ManagerActionService().submit_review(
            db,
            reviewer=manager,
            scorecard=scorecard,
            source_session=session,
            reason_code=ReviewReason.MANAGER_COACHING,
            override_score=8.0,
            notes="Manager gave more credit for objection handling than the model.",
        )
        db.commit()
        db.refresh(review)

        label = db.scalar(select(OverrideLabel).where(OverrideLabel.review_id == review.id))
        assert label is not None
        return {"session_id": session.id, "review_id": review.id, "label_id": label.id}
    finally:
        db.close()


def test_training_signal_export_returns_valid_jsonl_and_marks_labels_exported(client, seed_org):
    seeded = _seed_exportable_override(seed_org)

    response = client.get(
        "/admin/training-signals/export",
        params={"quality": "all", "prompt_type": "grading_v2", "format": "jsonl"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.strip()]
    assert lines

    record = json.loads(lines[0])
    assert "input" in record
    assert "ai_output" in record
    assert "human_correction" in record
    assert record["input"]["transcript"]
    assert "emotion_before" in record["input"]["transcript"][0]
    assert "mb_realism_score" in record["input"]["transcript"][0]
    assert record["ai_output"]["category_scores"]["objection_handling"]["score"] == 6.8
    assert record["human_correction"]["override_overall_score"] == 8.0
    assert record["human_correction"]["delta"] >= 1.0

    db = SessionLocal()
    try:
        label = db.scalar(select(OverrideLabel).where(OverrideLabel.id == seeded["label_id"]))
        assert label is not None
        assert label.exported_at is not None
        assert label.export_batch_id
    finally:
        db.close()
