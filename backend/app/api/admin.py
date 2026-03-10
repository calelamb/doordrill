from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_admin
from app.db.session import get_db
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.training import OverrideLabel, PromptExperiment
from app.services.prompt_experiment_service import PromptExperimentService

router = APIRouter(prefix="/admin", tags=["admin"])
prompt_experiment_service = PromptExperimentService()


class PromptExperimentCreateRequest(BaseModel):
    prompt_type: str = Field(default="grading_v2")
    control_version_id: str
    challenger_version_id: str
    challenger_traffic_pct: int = Field(default=10, ge=0, le=100)
    min_sessions_for_decision: int = Field(default=200, ge=1)


def _to_start_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _to_end_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _turn_payload(turn: SessionTurn) -> dict:
    return {
        "id": turn.id,
        "turn_index": turn.turn_index,
        "speaker": turn.speaker.value,
        "stage": turn.stage,
        "text": turn.text,
        "started_at": turn.started_at.isoformat(),
        "ended_at": turn.ended_at.isoformat(),
        "objection_tags": list(turn.objection_tags or []),
        "emotion_before": turn.emotion_before,
        "emotion_after": turn.emotion_after,
        "emotion_changed": bool(turn.emotion_changed),
        "resistance_level": turn.resistance_level,
        "objection_pressure": turn.objection_pressure,
        "active_objections": list(turn.active_objections or []),
        "queued_objections": list(turn.queued_objections or []),
        "mb_tone": turn.mb_tone,
        "mb_sentence_length": turn.mb_sentence_length,
        "mb_behaviors": list(turn.mb_behaviors or []),
        "mb_interruption_type": turn.mb_interruption_type,
        "mb_realism_score": turn.mb_realism_score,
        "mb_opening_pause_ms": turn.mb_opening_pause_ms,
        "mb_total_pause_ms": turn.mb_total_pause_ms,
        "behavioral_signals": list(turn.behavioral_signals or []),
        "was_graded": bool(turn.was_graded),
        "evidence_for_categories": list(turn.evidence_for_categories or []),
        "is_high_quality": turn.is_high_quality,
    }


def _quality_filter(label_quality: str) -> set[str]:
    if label_quality == "high":
        return {"high"}
    if label_quality == "medium":
        return {"high", "medium"}
    return {"high", "medium", "low"}


def _serialize_prompt_experiment(experiment: PromptExperiment) -> dict:
    return {
        "id": experiment.id,
        "prompt_type": experiment.prompt_type,
        "control_version_id": experiment.control_version_id,
        "challenger_version_id": experiment.challenger_version_id,
        "challenger_traffic_pct": experiment.challenger_traffic_pct,
        "status": experiment.status,
        "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
        "ended_at": experiment.ended_at.isoformat() if experiment.ended_at else None,
        "winner": experiment.winner,
        "control_mean_calibration_error": experiment.control_mean_calibration_error,
        "challenger_mean_calibration_error": experiment.challenger_mean_calibration_error,
        "control_session_count": experiment.control_session_count,
        "challenger_session_count": experiment.challenger_session_count,
        "p_value": experiment.p_value,
        "min_sessions_for_decision": experiment.min_sessions_for_decision,
    }


@router.post("/prompt-experiments")
def create_prompt_experiment(
    payload: PromptExperimentCreateRequest,
    actor: Actor = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    control = db.get(PromptVersion, payload.control_version_id)
    challenger = db.get(PromptVersion, payload.challenger_version_id)
    if control is None or challenger is None:
        raise HTTPException(status_code=404, detail="prompt version not found")
    if control.prompt_type != payload.prompt_type or challenger.prompt_type != payload.prompt_type:
        raise HTTPException(status_code=400, detail="prompt versions must match prompt_type")

    experiment = prompt_experiment_service.create_experiment(
        db,
        prompt_type=payload.prompt_type,
        control_version_id=payload.control_version_id,
        challenger_version_id=payload.challenger_version_id,
        challenger_traffic_pct=payload.challenger_traffic_pct,
        min_sessions_for_decision=payload.min_sessions_for_decision,
    )
    db.commit()
    db.refresh(experiment)
    return _serialize_prompt_experiment(experiment)


@router.get("/prompt-experiments/{experiment_id}")
def get_prompt_experiment(
    experiment_id: str,
    actor: Actor = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    experiment = db.get(PromptExperiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="prompt experiment not found")
    return _serialize_prompt_experiment(experiment)


@router.post("/prompt-experiments/{experiment_id}/evaluate")
def evaluate_prompt_experiment(
    experiment_id: str,
    actor: Actor = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        experiment = prompt_experiment_service.evaluate(db, experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    db.refresh(experiment)
    return _serialize_prompt_experiment(experiment)


@router.post("/prompt-experiments/{experiment_id}/promote")
def promote_prompt_experiment_winner(
    experiment_id: str,
    actor: Actor = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        experiment = prompt_experiment_service.promote_winner(db, experiment_id)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    db.commit()
    db.refresh(experiment)
    return _serialize_prompt_experiment(experiment)


@router.get("/training-signals/export")
def export_training_signals(
    actor: Actor = Depends(require_admin),
    db: Session = Depends(get_db),
    quality: Literal["high", "medium", "all"] = Query(default="all"),
    prompt_type: str = Query(default="grading_v2"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    format: Literal["jsonl", "json"] = Query(default="jsonl"),
) -> Response:
    batch_id = str(uuid.uuid4())
    allowed_qualities = _quality_filter(quality)
    start_at = _to_start_of_day(from_date)
    end_at = _to_end_of_day(to_date)

    stmt = (
        select(OverrideLabel, GradingRun, PromptVersion, DrillSession, Scorecard, Scenario)
        .join(GradingRun, GradingRun.id == OverrideLabel.grading_run_id)
        .join(PromptVersion, PromptVersion.id == GradingRun.prompt_version_id)
        .join(DrillSession, DrillSession.id == OverrideLabel.session_id)
        .join(Scorecard, Scorecard.session_id == DrillSession.id)
        .outerjoin(Scenario, Scenario.id == DrillSession.scenario_id)
        .where(PromptVersion.prompt_type == prompt_type)
    )
    if actor.org_id is not None:
        stmt = stmt.where(OverrideLabel.org_id == actor.org_id)
    if quality != "all":
        stmt = stmt.where(OverrideLabel.label_quality.in_(allowed_qualities))
    if start_at is not None:
        stmt = stmt.where(OverrideLabel.created_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(OverrideLabel.created_at <= end_at)

    rows = db.execute(stmt.order_by(OverrideLabel.created_at.asc())).all()
    session_ids = [row.OverrideLabel.session_id for row in rows]
    turns_by_session: dict[str, list[SessionTurn]] = {}
    if session_ids:
        turn_rows = db.scalars(
            select(SessionTurn)
            .where(SessionTurn.session_id.in_(session_ids))
            .order_by(SessionTurn.session_id.asc(), SessionTurn.turn_index.asc())
        ).all()
        for turn in turn_rows:
            turns_by_session.setdefault(turn.session_id, []).append(turn)

    examples: list[dict] = []
    exported_at = datetime.now(timezone.utc)
    for row in rows:
        label, grading_run, prompt_version_row, session, scorecard, scenario = row

        label.exported_at = exported_at
        label.export_batch_id = batch_id

        examples.append(
            {
                "input": {
                    "session_id": session.id,
                    "transcript": [_turn_payload(turn) for turn in turns_by_session.get(session.id, [])],
                    "prompt_version": prompt_version_row.version,
                    "scenario": (
                        {
                            "id": scenario.id,
                            "name": scenario.name,
                            "industry": scenario.industry,
                            "difficulty": scenario.difficulty,
                            "description": scenario.description,
                            "stages": list(scenario.stages or []),
                        }
                        if scenario is not None
                        else None
                    ),
                },
                "ai_output": {
                    "overall_score": label.ai_overall_score,
                    "category_scores": label.ai_category_scores,
                    "ai_summary": scorecard.ai_summary,
                    "grading_run_id": grading_run.id,
                },
                "human_correction": {
                    "override_overall_score": label.override_overall_score,
                    "override_category_scores": label.override_category_scores,
                    "delta": label.override_delta_overall,
                    "manager_id": label.manager_id,
                    "label_quality": label.label_quality,
                    "reason_text": label.override_reason_text,
                },
            }
        )

    db.commit()

    if format == "json":
        return Response(content=json.dumps(examples, ensure_ascii=True), media_type="application/json")

    body = "\n".join(json.dumps(item, ensure_ascii=True) for item in examples)
    return Response(content=body, media_type="application/x-ndjson")
