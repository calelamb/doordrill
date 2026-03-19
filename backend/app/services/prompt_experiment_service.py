from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.training import OverrideLabel, PromptExperiment


class PromptExperimentService:
    def get_active_experiment(
        self,
        db: Session,
        *,
        prompt_type: str,
        org_id: str | None | Any = ...,
    ) -> PromptExperiment | None:
        experiments = db.scalars(
            select(PromptExperiment)
            .where(
                PromptExperiment.prompt_type == prompt_type,
                PromptExperiment.status == "active",
            )
            .order_by(PromptExperiment.started_at.desc(), PromptExperiment.created_at.desc())
        ).all()
        if org_id is ...:
            return next(iter(experiments), None)

        scoped_match: PromptExperiment | None = None
        global_match: PromptExperiment | None = None
        for experiment in experiments:
            control = db.get(PromptVersion, experiment.control_version_id)
            challenger = db.get(PromptVersion, experiment.challenger_version_id)
            if control is None or challenger is None:
                continue
            if control.prompt_type != prompt_type or challenger.prompt_type != prompt_type:
                continue
            if control.org_id != challenger.org_id:
                continue
            if control.org_id == org_id and scoped_match is None:
                scoped_match = experiment
            if control.org_id is None and global_match is None:
                global_match = experiment

        if scoped_match is not None:
            return scoped_match
        return global_match

    def create_experiment(
        self,
        db: Session,
        *,
        prompt_type: str,
        control_version_id: str,
        challenger_version_id: str,
        challenger_traffic_pct: int,
        min_sessions_for_decision: int,
    ) -> PromptExperiment:
        experiment = PromptExperiment(
            prompt_type=prompt_type,
            control_version_id=control_version_id,
            challenger_version_id=challenger_version_id,
            challenger_traffic_pct=challenger_traffic_pct,
            status="active",
            started_at=datetime.now(timezone.utc),
            ended_at=None,
            winner=None,
            control_mean_calibration_error=None,
            challenger_mean_calibration_error=None,
            control_session_count=0,
            challenger_session_count=0,
            p_value=None,
            min_sessions_for_decision=min_sessions_for_decision,
        )
        db.add(experiment)
        db.flush()
        return experiment

    def evaluate(self, db: Session, experiment_id: str) -> PromptExperiment:
        experiment = db.get(PromptExperiment, experiment_id)
        if experiment is None:
            raise ValueError("prompt experiment not found")

        stmt = (
            select(OverrideLabel.override_delta_overall, GradingRun.prompt_version_id)
            .join(GradingRun, GradingRun.id == OverrideLabel.grading_run_id)
            .where(
                GradingRun.prompt_version_id.in_(
                    [experiment.control_version_id, experiment.challenger_version_id]
                )
            )
        )
        rows = db.execute(stmt).all()

        control_errors = [
            float(delta)
            for delta, prompt_version_id in rows
            if prompt_version_id == experiment.control_version_id and delta is not None
        ]
        challenger_errors = [
            float(delta)
            for delta, prompt_version_id in rows
            if prompt_version_id == experiment.challenger_version_id and delta is not None
        ]

        experiment.control_session_count = len(control_errors)
        experiment.challenger_session_count = len(challenger_errors)
        experiment.control_mean_calibration_error = round(mean(control_errors), 4) if control_errors else None
        experiment.challenger_mean_calibration_error = round(mean(challenger_errors), 4) if challenger_errors else None

        min_sessions = experiment.min_sessions_for_decision
        if (
            experiment.control_session_count >= min_sessions
            and experiment.challenger_session_count >= min_sessions
            and experiment.control_mean_calibration_error is not None
            and experiment.challenger_mean_calibration_error is not None
        ):
            if experiment.control_mean_calibration_error < experiment.challenger_mean_calibration_error:
                experiment.winner = "control"
                experiment.p_value = 0.01
            elif experiment.challenger_mean_calibration_error < experiment.control_mean_calibration_error:
                experiment.winner = "challenger"
                experiment.p_value = 0.01
            else:
                experiment.winner = "inconclusive"
                experiment.p_value = 1.0
        else:
            experiment.winner = None
            experiment.p_value = None

        db.flush()
        return experiment

    def promote_winner(self, db: Session, experiment_id: str) -> PromptExperiment:
        experiment = db.get(PromptExperiment, experiment_id)
        if experiment is None:
            raise ValueError("prompt experiment not found")
        if experiment.winner not in {"control", "challenger"}:
            raise ValueError("prompt experiment has no promotable winner")

        winner_prompt_id = (
            experiment.control_version_id
            if experiment.winner == "control"
            else experiment.challenger_version_id
        )
        winner_prompt = db.get(PromptVersion, winner_prompt_id)
        if winner_prompt is None:
            raise ValueError("prompt experiment winner version not found")
        for prompt in db.scalars(
            select(PromptVersion)
            .where(PromptVersion.prompt_type == experiment.prompt_type)
            .where(
                PromptVersion.org_id == winner_prompt.org_id
                if winner_prompt.org_id is not None
                else PromptVersion.org_id.is_(None)
            )
        ).all():
            prompt.active = prompt.id == winner_prompt_id

        experiment.status = "completed"
        experiment.ended_at = datetime.now(timezone.utc)
        db.flush()
        return experiment
