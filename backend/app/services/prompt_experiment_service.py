from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.training import ConversationQualitySignal, OverrideLabel, PromptExperiment
from app.models.types import SessionStatus
from app.models.user import User
from app.services.conversation_realism_eval_service import ConversationRealismEvalService


class PromptExperimentService:
    def __init__(self) -> None:
        self.realism_eval_service = ConversationRealismEvalService()

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
        if experiment.prompt_type in {"conversation", "conversation_analyzer"}:
            self._evaluate_conversation_experiment(db, experiment)
            db.flush()
            return experiment

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

    def build_evaluation_summary(self, db: Session, experiment: PromptExperiment) -> dict[str, Any] | None:
        if experiment.prompt_type in {"conversation", "conversation_analyzer"}:
            return self._conversation_summary(db, experiment)
        if experiment.control_mean_calibration_error is None and experiment.challenger_mean_calibration_error is None:
            return None
        return {
            "mode": "grading_calibration",
            "control_mean_calibration_error": experiment.control_mean_calibration_error,
            "challenger_mean_calibration_error": experiment.challenger_mean_calibration_error,
            "control_session_count": experiment.control_session_count,
            "challenger_session_count": experiment.challenger_session_count,
            "winner": experiment.winner,
            "p_value": experiment.p_value,
        }

    def _evaluate_conversation_experiment(self, db: Session, experiment: PromptExperiment) -> None:
        summary = self._conversation_summary(db, experiment)
        if summary is None:
            experiment.control_session_count = 0
            experiment.challenger_session_count = 0
            experiment.winner = None
            experiment.p_value = None
            return

        experiment.control_session_count = int(summary["control"]["session_count"])
        experiment.challenger_session_count = int(summary["challenger"]["session_count"])
        experiment.control_mean_calibration_error = round(float(summary["control"]["overall_score"]), 4)
        experiment.challenger_mean_calibration_error = round(float(summary["challenger"]["overall_score"]), 4)

        min_sessions = experiment.min_sessions_for_decision
        if (
            experiment.control_session_count >= min_sessions
            and experiment.challenger_session_count >= min_sessions
        ):
            control_score = float(summary["control"]["overall_score"])
            challenger_score = float(summary["challenger"]["overall_score"])
            if challenger_score > control_score:
                experiment.winner = "challenger"
                experiment.p_value = 0.01
            elif control_score > challenger_score:
                experiment.winner = "control"
                experiment.p_value = 0.01
            else:
                experiment.winner = "inconclusive"
                experiment.p_value = 1.0
        else:
            experiment.winner = None
            experiment.p_value = None

    def _conversation_summary(self, db: Session, experiment: PromptExperiment) -> dict[str, Any] | None:
        control_prompt = db.get(PromptVersion, experiment.control_version_id)
        challenger_prompt = db.get(PromptVersion, experiment.challenger_version_id)
        if control_prompt is None or challenger_prompt is None:
            return None

        org_id = control_prompt.org_id
        stmt = (
            select(DrillSession)
            .join(User, User.id == DrillSession.rep_id)
            .where(DrillSession.status == SessionStatus.GRADED)
            .order_by(DrillSession.started_at.asc())
        )
        if org_id is not None:
            stmt = stmt.where(User.org_id == org_id)
        sessions = db.scalars(stmt).all()
        if not sessions:
            return {
                "mode": "conversation_realism",
                "control": self._empty_variant_summary(control_prompt.version),
                "challenger": self._empty_variant_summary(challenger_prompt.version),
            }

        session_ids = [session.id for session in sessions]
        turns = db.scalars(
            select(SessionTurn)
            .where(SessionTurn.session_id.in_(session_ids))
            .order_by(SessionTurn.session_id.asc(), SessionTurn.turn_index.asc())
        ).all()
        quality_signals = db.scalars(
            select(ConversationQualitySignal)
            .where(ConversationQualitySignal.session_id.in_(session_ids))
            .order_by(ConversationQualitySignal.session_id.asc(), ConversationQualitySignal.created_at.desc())
        ).all()
        committed_events = db.scalars(
            select(SessionEvent)
            .where(
                SessionEvent.session_id.in_(session_ids),
                SessionEvent.event_type == "server.turn.committed",
            )
            .order_by(SessionEvent.session_id.asc(), SessionEvent.event_ts.asc())
        ).all()

        turns_by_session: dict[str, list[SessionTurn]] = {}
        for turn in turns:
            turns_by_session.setdefault(turn.session_id, []).append(turn)
        signals_by_session: dict[str, ConversationQualitySignal] = {}
        for signal in quality_signals:
            signals_by_session.setdefault(signal.session_id, signal)
        committed_by_session: dict[str, list[dict[str, Any]]] = {}
        for event in committed_events:
            committed_by_session.setdefault(event.session_id, []).append(dict(event.payload or {}))

        control_sessions: list[dict[str, Any]] = []
        challenger_sessions: list[dict[str, Any]] = []
        for session in sessions:
            variant_version = None
            if experiment.prompt_type == "conversation":
                variant_version = session.prompt_version
            else:
                payloads = committed_by_session.get(session.id, [])
                for payload in payloads:
                    raw_version = payload.get("analyzer_prompt_version")
                    if raw_version:
                        variant_version = str(raw_version)
                        break
            if variant_version not in {control_prompt.version, challenger_prompt.version}:
                continue
            eval_result = self.realism_eval_service.evaluate_session(
                turns=turns_by_session.get(session.id, []),
                committed_payloads=committed_by_session.get(session.id, []),
                quality_signal=signals_by_session.get(session.id),
            )
            session_summary = {
                "session_id": session.id,
                "overall_score": eval_result.overall_score,
                "repetition_rate": eval_result.repetition_rate,
                "contradiction_rate": eval_result.contradiction_rate,
                "transcript_entity_score": eval_result.transcript_entity_score,
                "failure_labels": list(eval_result.failure_labels),
            }
            if variant_version == control_prompt.version:
                control_sessions.append(session_summary)
            else:
                challenger_sessions.append(session_summary)

        return {
            "mode": "conversation_realism",
            "control": self._summarize_variant(control_prompt.version, control_sessions),
            "challenger": self._summarize_variant(challenger_prompt.version, challenger_sessions),
        }

    def _empty_variant_summary(self, version: str) -> dict[str, Any]:
        return {
            "version": version,
            "session_count": 0,
            "overall_score": 0.0,
            "repetition_rate": 0.0,
            "contradiction_rate": 0.0,
            "transcript_entity_score": 0.0,
            "failure_buckets": {},
        }

    def _summarize_variant(self, version: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        if not sessions:
            return self._empty_variant_summary(version)
        failure_buckets: dict[str, int] = {}
        for session in sessions:
            for label in session["failure_labels"]:
                failure_buckets[label] = failure_buckets.get(label, 0) + 1
        return {
            "version": version,
            "session_count": len(sessions),
            "overall_score": round(mean(float(item["overall_score"]) for item in sessions), 4),
            "repetition_rate": round(mean(float(item["repetition_rate"]) for item in sessions), 4),
            "contradiction_rate": round(mean(float(item["contradiction_rate"]) for item in sessions), 4),
            "transcript_entity_score": round(mean(float(item["transcript_entity_score"]) for item in sessions), 4),
            "failure_buckets": failure_buckets,
        }

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
