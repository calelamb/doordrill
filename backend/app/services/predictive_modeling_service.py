from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median, pstdev
from typing import Any
from collections import defaultdict

try:
    import numpy as np
except ImportError:  # pragma: no cover - fallback stays deterministic when numpy is absent
    np = None
try:
    from scipy.stats import percentileofscore
except ImportError:  # pragma: no cover - fallback stays deterministic when scipy is absent
    percentileofscore = None

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.predictive import ManagerCoachingImpact, RepCohortBenchmark, RepRiskScore, RepSkillForecast
from app.models.predictive import ScenarioOutcomeAggregate
from app.models.scorecard import ManagerCoachingNote, Scorecard
from app.models.session import Session as DrillSession
from app.models.training import AdaptiveRecommendationOutcome, OverrideLabel
from app.models.types import UserRole
from app.models.user import Team, User
from app.models.assignment import Assignment
from app.models.warehouse import DimRep, FactRepDaily, FactSession


class PredictiveModelingService:
    READINESS_THRESHOLD = 7.0
    MIN_SESSIONS_FOR_REGRESSION = 3
    RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    BENCHMARK_SKILLS = ["overall", "opening", "rapport", "pitch_clarity", "objection_handling", "closing"]
    IMPACT_WINDOW_DAYS = 14

    def _get_manager_reps(self, db: Session, *, manager_id: str, org_id: str) -> list[User]:
        return db.execute(
            select(User)
            .join(Team, Team.id == User.team_id)
            .where(
                User.org_id == org_id,
                User.role == UserRole.REP,
                Team.manager_id == manager_id,
            )
            .order_by(User.name.asc(), User.created_at.asc())
        ).scalars().all()

    def compute_and_persist_forecast(
        self,
        db: Session,
        *,
        rep_id: str,
        org_id: str,
        skill_profile: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        computed_at = datetime.now(timezone.utc)
        forecasts: list[dict[str, Any]] = []
        rep = db.scalar(
            select(User)
            .where(User.id == rep_id, User.org_id == org_id)
        )
        manager_id = None
        last_session_at = None
        if rep is not None and rep.team_id:
            team = db.scalar(select(Team).where(Team.id == rep.team_id))
            manager_id = team.manager_id if team is not None else None
        last_session_at = db.scalar(
            select(func.max(DrillSession.ended_at))
            .where(DrillSession.rep_id == rep_id)
        ) or db.scalar(
            select(func.max(DrillSession.started_at))
            .where(DrillSession.rep_id == rep_id)
        )

        for node in skill_profile:
            skill = str(node.get("skill") or "").strip()
            if not skill:
                continue

            history = [
                float(score)
                for score in (node.get("history") or [])
                if isinstance(score, (int, float))
            ]
            current_score = self._safe_float(node.get("score"))
            velocity: float | None = None
            r_squared: float | None = None
            sessions_to_readiness: int | None = None

            if len(history) >= self.MIN_SESSIONS_FOR_REGRESSION:
                velocity, _, r_squared = self._linear_regression(
                    list(range(len(history))),
                    history,
                )
                if velocity is not None and abs(velocity) < 1e-6:
                    velocity = 0.0

            if current_score is not None and current_score >= self.READINESS_THRESHOLD:
                sessions_to_readiness = 0
            elif (
                current_score is not None
                and velocity is not None
                and velocity > 0
            ):
                sessions_to_readiness = max(
                    0,
                    math.ceil((self.READINESS_THRESHOLD - current_score) / velocity),
                )

            projected_ready_at_sessions = (
                len(history) + sessions_to_readiness
                if sessions_to_readiness is not None
                else None
            )

            row = db.scalar(
                select(RepSkillForecast).where(
                    RepSkillForecast.rep_id == rep_id,
                    RepSkillForecast.skill == skill,
                )
            )
            if row is None:
                row = RepSkillForecast(
                    rep_id=rep_id,
                    org_id=org_id,
                    skill=skill,
                    forecast_computed_at=computed_at,
                )
                db.add(row)

            row.org_id = org_id
            row.current_score = current_score
            row.velocity = velocity
            row.sessions_to_readiness = sessions_to_readiness
            row.projected_ready_at_sessions = projected_ready_at_sessions
            row.readiness_threshold = self.READINESS_THRESHOLD
            row.sample_size = len(history)
            row.r_squared = r_squared
            row.forecast_computed_at = computed_at

            forecasts.append(
                self._serialize_skill_forecast(row)
            )
        if manager_id:
            proxy_history = next(
                (
                    [float(score) for score in (node.get("history") or []) if isinstance(score, (int, float))]
                    for node in skill_profile
                    if isinstance(node, dict) and node.get("history")
                ),
                [],
            )
            self.compute_and_persist_risk_score(
                db,
                rep_id=rep_id,
                org_id=org_id,
                manager_id=manager_id,
                score_history=proxy_history,
                last_session_at=last_session_at,
            )

        db.commit()
        return forecasts

    def _linear_regression(self, x: list[float], y: list[float]) -> tuple[float, float, float]:
        if len(x) != len(y):
            raise ValueError("x and y must be the same length")
        if len(x) < 2:
            return 0.0, y[0] if y else 0.0, 0.0

        if np is not None:
            slope, intercept = np.polyfit(x, y, 1)
            y_hat = [(float(slope) * value) + float(intercept) for value in x]
        else:
            x_mean = sum(x) / len(x)
            y_mean = sum(y) / len(y)
            denominator = sum((value - x_mean) ** 2 for value in x)
            slope = 0.0 if denominator == 0 else sum((xv - x_mean) * (yv - y_mean) for xv, yv in zip(x, y)) / denominator
            intercept = y_mean - (slope * x_mean)
            y_hat = [(slope * value) + intercept for value in x]

        y_mean = sum(y) / len(y)
        ss_res = sum((actual - predicted) ** 2 for actual, predicted in zip(y, y_hat))
        ss_tot = sum((actual - y_mean) ** 2 for actual in y)
        r_squared = 1.0 if ss_tot == 0 else 1 - (ss_res / ss_tot)
        return float(slope), float(intercept), float(r_squared)

    def get_rep_forecast(self, db: Session, *, rep_id: str) -> dict[str, Any]:
        cohort_benchmarks = self.get_rep_benchmarks(db, rep_id=rep_id)
        rows = db.scalars(
            select(RepSkillForecast)
            .where(RepSkillForecast.rep_id == rep_id)
            .order_by(RepSkillForecast.skill.asc())
        ).all()

        if not rows:
            return {
                "rep_id": rep_id,
                "readiness_score": None,
                "overall_velocity": None,
                "overall_sessions_to_readiness": None,
                "skill_forecasts": [],
                "forecast_computed_at": None,
                "cohort_benchmarks": cohort_benchmarks,
            }

        readiness_score = self._mean_optional(
            row.current_score for row in rows if row.current_score is not None
        )
        velocities = [row.velocity for row in rows if row.velocity is not None]
        pending_sessions = [
            row.sessions_to_readiness
            for row in rows
            if row.sessions_to_readiness is not None and (row.current_score or 0.0) < self.READINESS_THRESHOLD
        ]
        overall_sessions_to_readiness: int | None
        if pending_sessions:
            overall_sessions_to_readiness = max(pending_sessions)
        elif readiness_score is not None and readiness_score >= self.READINESS_THRESHOLD:
            overall_sessions_to_readiness = 0
        else:
            overall_sessions_to_readiness = None

        latest_computed_at = max(row.forecast_computed_at for row in rows if row.forecast_computed_at is not None)
        return {
            "rep_id": rep_id,
            "readiness_score": round(readiness_score, 2) if readiness_score is not None else None,
            "overall_velocity": round(mean(velocities), 4) if velocities else None,
            "overall_sessions_to_readiness": overall_sessions_to_readiness,
            "skill_forecasts": [self._serialize_skill_forecast(row) for row in rows],
            "forecast_computed_at": latest_computed_at.isoformat() if latest_computed_at else None,
            "cohort_benchmarks": cohort_benchmarks,
        }

    def get_team_forecast(self, db: Session, *, manager_id: str, org_id: str) -> dict[str, Any]:
        reps = self._get_manager_reps(db, manager_id=manager_id, org_id=org_id)

        rep_summaries: list[dict[str, Any]] = []
        readiness_sessions: list[int] = []
        reps_already_ready = 0
        reps_on_track = 0
        reps_at_risk = 0

        for rep in reps:
            forecast = self.get_rep_forecast(db, rep_id=rep.id)
            readiness_score = self._safe_float(forecast.get("readiness_score"))
            overall_velocity = self._safe_float(forecast.get("overall_velocity"))
            sessions_to_readiness = forecast.get("overall_sessions_to_readiness")
            if not isinstance(sessions_to_readiness, int):
                sessions_to_readiness = None

            if readiness_score is not None and readiness_score >= self.READINESS_THRESHOLD:
                reps_already_ready += 1
            elif (
                overall_velocity is not None
                and overall_velocity > 0
                and sessions_to_readiness is not None
                and sessions_to_readiness <= 20
            ):
                reps_on_track += 1
            elif (
                overall_velocity is None
                or overall_velocity <= 0
                or sessions_to_readiness is None
                or sessions_to_readiness > 30
            ):
                reps_at_risk += 1
            if sessions_to_readiness is not None:
                readiness_sessions.append(sessions_to_readiness)

            rep_summaries.append(
                {
                    "rep_id": rep.id,
                    "name": rep.name,
                    "readiness_score": readiness_score,
                    "sessions_to_readiness": sessions_to_readiness,
                    "velocity": overall_velocity,
                    "forecast_computed_at": forecast.get("forecast_computed_at"),
                }
            )

        avg_sessions = round(mean(readiness_sessions), 2) if readiness_sessions else None
        median_sessions = median(readiness_sessions) if readiness_sessions else None
        return {
            "manager_id": manager_id,
            "team_size": len(reps),
            "avg_sessions_to_readiness": avg_sessions,
            "median_sessions_to_readiness": median_sessions,
            "reps_already_ready": reps_already_ready,
            "reps_on_track": reps_on_track,
            "reps_at_risk": reps_at_risk,
            "rep_summaries": rep_summaries,
        }

    def get_team_intelligence_snapshot(self, db: Session, *, manager_id: str, org_id: str) -> dict[str, Any]:
        snapshot_at = datetime.now(timezone.utc)
        team_forecast = self.get_team_forecast(db, manager_id=manager_id, org_id=org_id)
        at_risk_rows = self.get_at_risk_reps(
            db,
            manager_id=manager_id,
            org_id=org_id,
            min_risk_level="medium",
        )
        impact_summary = self.get_manager_impact_summary(db, manager_id=manager_id)

        rep_summaries = list(team_forecast.get("rep_summaries") or [])
        rep_ids = [str(summary["rep_id"]) for summary in rep_summaries if summary.get("rep_id")]
        rep_names = {
            str(summary["rep_id"]): str(summary.get("name") or summary["rep_id"])
            for summary in rep_summaries
            if summary.get("rep_id")
        }

        forecast_rows = db.scalars(
            select(RepSkillForecast)
            .where(RepSkillForecast.rep_id.in_(rep_ids))
            .order_by(RepSkillForecast.skill.asc())
        ).all() if rep_ids else []
        risk_models = db.scalars(
            select(RepRiskScore)
            .where(RepRiskScore.rep_id.in_(rep_ids))
            .order_by(RepRiskScore.risk_computed_at.desc())
        ).all() if rep_ids else []
        cohort_rows = db.scalars(
            select(RepCohortBenchmark)
            .where(
                RepCohortBenchmark.rep_id.in_(rep_ids),
                RepCohortBenchmark.skill == "overall",
            )
        ).all() if rep_ids else []

        skill_scores: dict[str, list[float]] = defaultdict(list)
        for row in forecast_rows:
            if row.current_score is not None:
                skill_scores[row.skill].append(float(row.current_score))
        team_skill_averages = {
            skill: round(mean(scores), 2)
            for skill, scores in sorted(skill_scores.items())
            if scores
        }

        weakest_team_skill = None
        strongest_team_skill = None
        if team_skill_averages:
            weakest_team_skill = min(team_skill_averages.items(), key=lambda item: (item[1], item[0]))[0]
            strongest_team_skill = max(team_skill_averages.items(), key=lambda item: (item[1], item[0]))[0]

        latest_risk_by_rep: dict[str, RepRiskScore] = {}
        for row in risk_models:
            if row.rep_id not in latest_risk_by_rep:
                latest_risk_by_rep[row.rep_id] = row

        avg_readiness_values = [
            readiness_score
            for readiness_score in (
                self._safe_float(summary.get("readiness_score"))
                for summary in rep_summaries
            )
            if readiness_score is not None
        ]
        median_sessions = self._safe_float(team_forecast.get("median_sessions_to_readiness"))
        cohort_percentiles = [
            float(row.percentile_in_cohort)
            for row in cohort_rows
            if row.percentile_in_cohort is not None
        ]

        projection: dict[str, dict[str, Any]] = {}
        for horizon_days in (30, 60, 90):
            projected_scores: list[float] = []
            reps_reaching_readiness = 0
            for summary in rep_summaries:
                rep_id = str(summary["rep_id"])
                current_score = self._safe_float(summary.get("readiness_score"))
                if current_score is None:
                    continue
                velocity = self._safe_float(summary.get("velocity"))
                risk_row = latest_risk_by_rep.get(rep_id)
                session_frequency_7d = (
                    self._safe_float(risk_row.session_frequency_7d)
                    if risk_row is not None
                    else None
                )
                sessions_per_day = (session_frequency_7d / 7) if session_frequency_7d is not None else 0.5
                projected_score = current_score
                if velocity is not None:
                    projected_score += velocity * (sessions_per_day * horizon_days)
                projected_scores.append(projected_score)
                if projected_score >= self.READINESS_THRESHOLD:
                    reps_reaching_readiness += 1
            projection[f"{horizon_days}d"] = {
                "projected_avg_score": round(mean(projected_scores), 2) if projected_scores else 0.0,
                "reps_reaching_readiness": reps_reaching_readiness,
            }

        return {
            "manager_id": manager_id,
            "org_id": org_id,
            "snapshot_at": snapshot_at.isoformat(),
            "team_size": team_forecast.get("team_size", 0),
            "avg_readiness_score": round(mean(avg_readiness_values), 2) if avg_readiness_values else 0.0,
            "reps_ready": team_forecast.get("reps_already_ready", 0),
            "reps_on_track": team_forecast.get("reps_on_track", 0),
            "reps_at_risk": team_forecast.get("reps_at_risk", 0),
            "projected_team_readiness_in_sessions": round(median_sessions, 2) if median_sessions is not None else 0.0,
            "team_skill_averages": team_skill_averages,
            "weakest_team_skill": weakest_team_skill,
            "strongest_team_skill": strongest_team_skill,
            "at_risk_reps": [
                {
                    "rep_id": row["rep_id"],
                    "name": rep_names.get(row["rep_id"], row["rep_id"]),
                    "risk_level": row["risk_level"],
                    "triggered_alerts": list(row.get("triggered_alerts") or []),
                    "days_since_last_session": row.get("days_since_last_session"),
                }
                for row in at_risk_rows
            ],
            "cohort_comparison": {
                "reps_above_cohort_median": sum(1 for percentile in cohort_percentiles if percentile >= 50),
                "reps_below_cohort_median": sum(1 for percentile in cohort_percentiles if percentile < 50),
            },
            "coaching_effectiveness": {
                "avg_score_delta": round(self._safe_float(impact_summary.get("avg_score_delta")) or 0.0, 4),
                "positive_impact_rate": round(self._safe_float(impact_summary.get("positive_impact_rate")) or 0.0, 4),
            },
            "projection": projection,
        }

    def compute_and_persist_risk_score(
        self,
        db: Session,
        *,
        rep_id: str,
        org_id: str,
        manager_id: str,
        score_history: list[float],
        last_session_at: datetime | None,
    ) -> dict[str, Any]:
        computed_at = datetime.now(timezone.utc)
        plateau_window = score_history[-8:]
        plateau_duration_sessions = len(plateau_window) if plateau_window else None
        score_volatility = pstdev(plateau_window) if len(plateau_window) >= 2 else 0.0
        is_plateauing = len(plateau_window) >= 5 and score_volatility < 0.3
        plateau_score = 0.4 if is_plateauing else 0.0

        decline_window = score_history[-10:]
        decline_slope: float | None = None
        is_declining = False
        decline_score = 0.0
        if len(decline_window) >= 2:
            decline_slope, _, _ = self._linear_regression(
                list(range(len(decline_window))),
                decline_window,
            )
            if abs(decline_slope) < 1e-6:
                decline_slope = 0.0
            is_declining = decline_slope < -0.05
            decline_score = min(0.4, abs(decline_slope) * 4) if is_declining else 0.0

        normalized_last_session = self._as_utc(last_session_at)
        days_since_last_session = (
            max(0, (computed_at - normalized_last_session).days)
            if normalized_last_session is not None
            else None
        )
        is_disengaging = days_since_last_session is None or days_since_last_session > 7
        if days_since_last_session is None:
            disengagement_score = 0.2
        elif days_since_last_session <= 7:
            disengagement_score = 0.0
        else:
            disengagement_score = min(0.2, ((days_since_last_session - 7) / 14) * 0.2)

        risk_score = min(1.0, plateau_score + decline_score + disengagement_score)
        risk_level = self._risk_level_for_score(risk_score)
        triggered_alerts = [
            label
            for label, active in (
                ("plateau", is_plateauing),
                ("decline", is_declining),
                ("disengaging", is_disengaging),
            )
            if active
        ]

        row = db.scalar(select(RepRiskScore).where(RepRiskScore.rep_id == rep_id))
        if row is None:
            row = RepRiskScore(
                rep_id=rep_id,
                org_id=org_id,
                manager_id=manager_id,
                risk_computed_at=computed_at,
            )
            db.add(row)

        row.org_id = org_id
        row.manager_id = manager_id
        row.risk_score = round(risk_score, 4)
        row.risk_level = risk_level
        row.is_plateauing = is_plateauing
        row.is_declining = is_declining
        row.is_disengaging = is_disengaging
        row.plateau_duration_sessions = plateau_duration_sessions if is_plateauing else None
        row.decline_slope = round(decline_slope, 4) if decline_slope is not None else None
        row.days_since_last_session = days_since_last_session
        row.session_frequency_7d = self._session_frequency(score_history, 7)
        row.session_frequency_30d = self._session_frequency(score_history, 30)
        row.triggered_alerts = triggered_alerts
        row.risk_computed_at = computed_at
        if row.suppressed_until is None or row.suppressed_until <= computed_at:
            row.alert_sent_at = computed_at if triggered_alerts else None
        db.flush()

        return self._serialize_risk_score(row)

    def get_at_risk_reps(
        self,
        db: Session,
        *,
        manager_id: str,
        org_id: str,
        min_risk_level: str = "medium",
    ) -> list[dict[str, Any]]:
        threshold = self.RISK_ORDER.get(min_risk_level, self.RISK_ORDER["medium"])
        now = datetime.now(timezone.utc)
        rows = db.scalars(
            select(RepRiskScore)
            .where(
                RepRiskScore.manager_id == manager_id,
                RepRiskScore.org_id == org_id,
            )
            .order_by(RepRiskScore.risk_score.desc(), RepRiskScore.risk_computed_at.desc())
        ).all()

        return [
            self._serialize_risk_score(row)
            for row in rows
            if self.RISK_ORDER.get(row.risk_level, 0) >= threshold
            and not (
                row.suppressed_until is not None
                and self._as_utc(row.suppressed_until) is not None
                and self._as_utc(row.suppressed_until) > now
            )
        ]

    def snooze_risk_alert(
        self,
        db: Session,
        *,
        rep_id: str,
        snooze_days: int = 7,
    ) -> None:
        row = db.scalar(select(RepRiskScore).where(RepRiskScore.rep_id == rep_id))
        if row is None:
            return
        row.suppressed_until = datetime.now(timezone.utc) + timedelta(days=max(1, snooze_days))
        db.commit()

    def refresh_scenario_outcome_aggregates(self, db: Session, *, org_id: str | None = None) -> int:
        if org_id is None:
            rows = db.execute(
                select(AdaptiveRecommendationOutcome)
                .where(AdaptiveRecommendationOutcome.outcome_written_at.is_not(None))
            ).scalars().all()
        else:
            rows = db.execute(
                select(AdaptiveRecommendationOutcome)
                .join(Assignment, Assignment.id == AdaptiveRecommendationOutcome.assignment_id)
                .join(User, User.id == Assignment.rep_id)
                .where(
                    AdaptiveRecommendationOutcome.outcome_written_at.is_not(None),
                    User.org_id == org_id,
                )
            ).scalars().all()
        grouped: dict[tuple[str, str, int], list[AdaptiveRecommendationOutcome]] = defaultdict(list)
        for outcome in rows:
            focus_skills = [str(skill) for skill in (outcome.recommended_focus_skills or []) if isinstance(skill, str) and skill]
            if not focus_skills or not outcome.recommended_scenario_id:
                continue
            key = (
                str(outcome.recommended_scenario_id),
                focus_skills[0],
                int(outcome.recommended_difficulty or 1),
            )
            grouped[key].append(outcome)

        refreshed_at = datetime.now(timezone.utc)
        written = 0
        for (scenario_id, focus_skill, difficulty_bucket), outcomes in grouped.items():
            success_values = [
                1.0 if outcome.recommendation_success else 0.0
                for outcome in outcomes
                if outcome.recommendation_success is not None
            ]
            delta_values = [
                float((outcome.skill_delta or {}).get(focus_skill))
                for outcome in outcomes
                if isinstance((outcome.skill_delta or {}).get(focus_skill), (int, float))
            ]
            outcome_scores = [
                float(outcome.outcome_overall_score)
                for outcome in outcomes
                if isinstance(outcome.outcome_overall_score, (int, float))
            ]
            row = db.scalar(
                select(ScenarioOutcomeAggregate).where(
                    ScenarioOutcomeAggregate.scenario_id == scenario_id,
                    ScenarioOutcomeAggregate.focus_skill == focus_skill,
                    ScenarioOutcomeAggregate.difficulty_bucket == difficulty_bucket,
                )
            )
            if row is None:
                row = ScenarioOutcomeAggregate(
                    scenario_id=scenario_id,
                    focus_skill=focus_skill,
                    difficulty_bucket=difficulty_bucket,
                    last_refreshed_at=refreshed_at,
                )
                db.add(row)
            row.sample_size = len(outcomes)
            row.success_rate = round(mean(success_values), 4) if success_values else None
            row.avg_skill_delta = round(mean(delta_values), 4) if delta_values else None
            row.avg_outcome_score = round(mean(outcome_scores), 4) if outcome_scores else None
            row.last_refreshed_at = refreshed_at
            written += 1

        db.flush()
        return written

    def get_outcome_ranked_scenarios(
        self,
        db: Session,
        *,
        focus_skill: str,
        difficulty: int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(ScenarioOutcomeAggregate)
            .where(
                ScenarioOutcomeAggregate.focus_skill == focus_skill,
                ScenarioOutcomeAggregate.difficulty_bucket == difficulty,
                ScenarioOutcomeAggregate.sample_size >= 3,
            )
            .order_by(
                ScenarioOutcomeAggregate.avg_skill_delta.desc(),
                ScenarioOutcomeAggregate.success_rate.desc(),
                ScenarioOutcomeAggregate.sample_size.desc(),
            )
            .limit(limit)
        ).all()
        return [
            {
                "scenario_id": row.scenario_id,
                "focus_skill": row.focus_skill,
                "difficulty_bucket": row.difficulty_bucket,
                "sample_size": row.sample_size,
                "success_rate": round(row.success_rate, 4) if row.success_rate is not None else None,
                "avg_skill_delta": round(row.avg_skill_delta, 4) if row.avg_skill_delta is not None else None,
                "avg_outcome_score": round(row.avg_outcome_score, 4) if row.avg_outcome_score is not None else None,
            }
            for row in rows
        ]

    def refresh_cohort_benchmarks(self, db: Session, *, org_id: str) -> int:
        reps = db.scalars(
            select(DimRep)
            .where(
                DimRep.org_id == org_id,
                DimRep.is_active.is_(True),
                DimRep.hire_cohort.is_not(None),
            )
            .order_by(DimRep.hire_cohort.asc(), DimRep.rep_name.asc())
        ).all()
        if not reps:
            return 0

        forecasts = db.scalars(
            select(RepSkillForecast)
            .where(RepSkillForecast.org_id == org_id)
        ).all()
        forecasts_by_rep: dict[str, dict[str, float | None]] = defaultdict(dict)
        for row in forecasts:
            forecasts_by_rep[row.rep_id][row.skill] = row.current_score

        latest_overall_rows = db.execute(
            select(FactRepDaily.rep_id, FactRepDaily.avg_score, FactRepDaily.session_date)
            .where(FactRepDaily.org_id == org_id)
            .order_by(FactRepDaily.rep_id.asc(), FactRepDaily.session_date.desc())
        ).all()
        overall_by_rep: dict[str, float | None] = {}
        for rep_id, avg_score, _ in latest_overall_rows:
            if rep_id not in overall_by_rep:
                overall_by_rep[str(rep_id)] = float(avg_score) if isinstance(avg_score, (int, float)) else None

        cohort_groups: dict[str, list[DimRep]] = defaultdict(list)
        for rep in reps:
            if rep.hire_cohort is None:
                continue
            cohort_groups[self._quarter_label(rep.hire_cohort)].append(rep)

        refreshed_at = datetime.now(timezone.utc)
        written = 0
        for cohort_label, cohort_reps in cohort_groups.items():
            for skill in self.BENCHMARK_SKILLS:
                cohort_scores = [
                    self._rep_skill_score(rep.rep_id, skill, forecasts_by_rep, overall_by_rep)
                    for rep in cohort_reps
                ]
                valid_cohort_scores = [score for score in cohort_scores if score is not None]
                org_scores = [
                    self._rep_skill_score(rep.rep_id, skill, forecasts_by_rep, overall_by_rep)
                    for rep in reps
                ]
                valid_org_scores = [score for score in org_scores if score is not None]
                cohort_percentiles = self._percentile_stats(valid_cohort_scores)
                cohort_mean = round(mean(valid_cohort_scores), 4) if valid_cohort_scores else None

                for rep in cohort_reps:
                    current_score = self._rep_skill_score(rep.rep_id, skill, forecasts_by_rep, overall_by_rep)
                    row = db.scalar(
                        select(RepCohortBenchmark).where(
                            RepCohortBenchmark.rep_id == rep.rep_id,
                            RepCohortBenchmark.skill == skill,
                        )
                    )
                    if row is None:
                        row = RepCohortBenchmark(
                            rep_id=rep.rep_id,
                            org_id=org_id,
                            skill=skill,
                            cohort_label=cohort_label,
                            benchmark_computed_at=refreshed_at,
                        )
                        db.add(row)

                    row.org_id = org_id
                    row.skill = skill
                    row.cohort_label = cohort_label
                    row.cohort_size = len(cohort_reps)
                    row.current_score = current_score
                    row.cohort_mean = cohort_mean
                    row.cohort_p25 = cohort_percentiles["p25"]
                    row.cohort_p50 = cohort_percentiles["p50"]
                    row.cohort_p75 = cohort_percentiles["p75"]
                    row.percentile_in_cohort = (
                        self._percentile_of_score(valid_cohort_scores, current_score)
                        if current_score is not None
                        else None
                    )
                    row.percentile_in_org = (
                        self._percentile_of_score(valid_org_scores, current_score)
                        if current_score is not None
                        else None
                    )
                    row.benchmark_computed_at = refreshed_at
                    written += 1

        db.flush()
        return written

    def get_rep_benchmarks(self, db: Session, *, rep_id: str) -> dict[str, Any]:
        rows = db.scalars(
            select(RepCohortBenchmark)
            .where(RepCohortBenchmark.rep_id == rep_id)
            .order_by(RepCohortBenchmark.skill.asc())
        ).all()
        if not rows:
            return {
                "rep_id": rep_id,
                "cohort_label": None,
                "cohort_size": 0,
                "skills": [],
            }

        ordered = {skill: None for skill in self.BENCHMARK_SKILLS}
        for row in rows:
            ordered[row.skill] = row

        first = rows[0]
        return {
            "rep_id": rep_id,
            "cohort_label": first.cohort_label,
            "cohort_size": first.cohort_size,
            "skills": [
                self._serialize_benchmark(row)
                for row in ordered.values()
                if row is not None
            ],
        }

    def compute_coaching_impact(
        self,
        db: Session,
        *,
        manager_id: str,
        org_id: str,
        lookback_days: int = 60,
    ) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        note_rows = db.execute(
            select(ManagerCoachingNote, Scorecard)
            .join(Scorecard, Scorecard.id == ManagerCoachingNote.scorecard_id)
            .join(DrillSession, DrillSession.id == Scorecard.session_id)
            .where(
                ManagerCoachingNote.reviewer_id == manager_id,
                ManagerCoachingNote.created_at >= cutoff,
                DrillSession.rep_id.is_not(None),
            )
        ).all()
        override_rows = db.scalars(
            select(OverrideLabel)
            .where(
                OverrideLabel.manager_id == manager_id,
                OverrideLabel.org_id == org_id,
                OverrideLabel.created_at >= cutoff,
            )
        ).all()

        processed = 0
        for note, scorecard in note_rows:
            processed += self._upsert_coaching_impact_row(
                db,
                manager_id=manager_id,
                org_id=org_id,
                rep_id=self._session_rep_id(db, scorecard.session_id),
                source_session_id=scorecard.session_id,
                intervention_type="coaching_note",
                intervention_at=self._as_utc(note.created_at) or datetime.now(timezone.utc),
            )

        for label in override_rows:
            processed += self._upsert_coaching_impact_row(
                db,
                manager_id=manager_id,
                org_id=org_id,
                rep_id=self._session_rep_id(db, label.session_id),
                source_session_id=label.session_id,
                intervention_type="override_label",
                intervention_at=self._as_utc(label.created_at) or datetime.now(timezone.utc),
            )

        db.flush()
        return processed

    def get_manager_impact_summary(self, db: Session, *, manager_id: str) -> dict[str, Any]:
        rows = db.scalars(
            select(ManagerCoachingImpact)
            .where(
                ManagerCoachingImpact.manager_id == manager_id,
                ManagerCoachingImpact.impact_computed_at.is_not(None),
            )
            .order_by(ManagerCoachingImpact.impact_computed_at.desc(), ManagerCoachingImpact.created_at.desc())
        ).all()
        measured = [row for row in rows if row.score_delta is not None]
        deltas = [float(row.score_delta) for row in measured]
        coaching_note_deltas = [float(row.score_delta) for row in measured if row.intervention_type == "coaching_note"]
        override_label_deltas = [float(row.score_delta) for row in measured if row.intervention_type == "override_label"]
        positive = [row for row in measured if (row.score_delta or 0.0) > 0.3]

        rep_groups: dict[str, list[float]] = defaultdict(list)
        for row in measured:
            rep_groups[row.rep_id].append(float(row.score_delta))

        best_impact_rep = None
        if rep_groups:
            best_rep_id, best_deltas = max(rep_groups.items(), key=lambda item: mean(item[1]))
            rep = db.scalar(select(User).where(User.id == best_rep_id))
            best_impact_rep = {
                "rep_id": best_rep_id,
                "name": rep.name if rep is not None else best_rep_id,
                "avg_delta": round(mean(best_deltas), 4),
            }

        return {
            "manager_id": manager_id,
            "total_interventions_measured": len(measured),
            "avg_score_delta": round(mean(deltas), 4) if deltas else None,
            "positive_impact_rate": round(len(positive) / len(measured), 4) if measured else 0.0,
            "best_impact_rep": best_impact_rep,
            "coaching_note_avg_delta": round(mean(coaching_note_deltas), 4) if coaching_note_deltas else None,
            "override_label_avg_delta": round(mean(override_label_deltas), 4) if override_label_deltas else None,
            "recent_impacts": [self._serialize_manager_impact(row) for row in rows[:5]],
        }

    def _serialize_skill_forecast(self, row: RepSkillForecast) -> dict[str, Any]:
        return {
            "skill": row.skill,
            "current_score": round(row.current_score, 2) if row.current_score is not None else None,
            "velocity": round(row.velocity, 4) if row.velocity is not None else None,
            "sessions_to_readiness": row.sessions_to_readiness,
            "projected_ready_at_sessions": row.projected_ready_at_sessions,
            "readiness_threshold": round(row.readiness_threshold, 2),
            "sample_size": row.sample_size,
            "r_squared": round(row.r_squared, 4) if row.r_squared is not None else None,
            "forecast_computed_at": row.forecast_computed_at.isoformat() if row.forecast_computed_at else None,
        }

    def _serialize_risk_score(self, row: RepRiskScore) -> dict[str, Any]:
        return {
            "rep_id": row.rep_id,
            "manager_id": row.manager_id,
            "risk_score": round(row.risk_score, 4),
            "risk_level": row.risk_level,
            "is_plateauing": row.is_plateauing,
            "is_declining": row.is_declining,
            "is_disengaging": row.is_disengaging,
            "triggered_alerts": list(row.triggered_alerts or []),
            "decline_slope": round(row.decline_slope, 4) if row.decline_slope is not None else None,
            "days_since_last_session": row.days_since_last_session,
            "plateau_duration_sessions": row.plateau_duration_sessions,
            "session_frequency_7d": row.session_frequency_7d,
            "session_frequency_30d": row.session_frequency_30d,
            "risk_computed_at": row.risk_computed_at.isoformat() if row.risk_computed_at else None,
            "suppressed_until": row.suppressed_until.isoformat() if row.suppressed_until else None,
        }

    def _serialize_benchmark(self, row: RepCohortBenchmark) -> dict[str, Any]:
        percentile = round(row.percentile_in_cohort, 2) if row.percentile_in_cohort is not None else None
        return {
            "skill": row.skill,
            "current_score": round(row.current_score, 2) if row.current_score is not None else None,
            "cohort_mean": round(row.cohort_mean, 2) if row.cohort_mean is not None else None,
            "cohort_p25": round(row.cohort_p25, 2) if row.cohort_p25 is not None else None,
            "cohort_p50": round(row.cohort_p50, 2) if row.cohort_p50 is not None else None,
            "cohort_p75": round(row.cohort_p75, 2) if row.cohort_p75 is not None else None,
            "percentile_in_cohort": percentile,
            "percentile_in_org": round(row.percentile_in_org, 2) if row.percentile_in_org is not None else None,
            "interpretation": self._benchmark_interpretation(percentile),
        }

    def _serialize_manager_impact(self, row: ManagerCoachingImpact) -> dict[str, Any]:
        return {
            "rep_id": row.rep_id,
            "source_session_id": row.source_session_id,
            "intervention_type": row.intervention_type,
            "intervention_at": row.intervention_at.isoformat() if row.intervention_at else None,
            "pre_intervention_score": round(row.pre_intervention_score, 2) if row.pre_intervention_score is not None else None,
            "post_intervention_score": round(row.post_intervention_score, 2) if row.post_intervention_score is not None else None,
            "score_delta": round(row.score_delta, 4) if row.score_delta is not None else None,
            "sessions_observed": row.sessions_observed,
            "observation_window_days": row.observation_window_days,
            "impact_classified": row.impact_classified,
            "impact_computed_at": row.impact_computed_at.isoformat() if row.impact_computed_at else None,
        }

    def _quarter_label(self, hire_date: date) -> str:
        quarter = ((hire_date.month - 1) // 3) + 1
        return f"{hire_date.year}-Q{quarter}"

    def _rep_skill_score(
        self,
        rep_id: str,
        skill: str,
        forecasts_by_rep: dict[str, dict[str, float | None]],
        overall_by_rep: dict[str, float | None],
    ) -> float | None:
        if skill == "overall":
            return overall_by_rep.get(rep_id)
        return forecasts_by_rep.get(rep_id, {}).get(skill)

    def _percentile_stats(self, values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"p25": None, "p50": None, "p75": None}
        if np is not None:
            p25, p50, p75 = np.percentile(values, [25, 50, 75])
            return {
                "p25": round(float(p25), 4),
                "p50": round(float(p50), 4),
                "p75": round(float(p75), 4),
            }
        sorted_values = sorted(values)
        return {
            "p25": round(self._linear_percentile(sorted_values, 25), 4),
            "p50": round(self._linear_percentile(sorted_values, 50), 4),
            "p75": round(self._linear_percentile(sorted_values, 75), 4),
        }

    def _linear_percentile(self, values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])
        position = (len(values) - 1) * (percentile / 100)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return float(values[int(position)])
        weight = position - lower
        return float(values[lower] + ((values[upper] - values[lower]) * weight))

    def _percentile_of_score(self, values: list[float], score: float | None) -> float | None:
        if score is None or not values:
            return None
        if percentileofscore is not None:
            return round(float(percentileofscore(values, score, kind="mean")), 4)
        less = sum(1 for value in values if value < score)
        equal = sum(1 for value in values if value == score)
        return round((((less + (0.5 * equal)) / len(values)) * 100), 4)

    def _benchmark_interpretation(self, percentile_in_cohort: float | None) -> str | None:
        if percentile_in_cohort is None:
            return None
        if percentile_in_cohort >= 80:
            return "Top performer"
        if percentile_in_cohort >= 55:
            return "Above average"
        if percentile_in_cohort >= 35:
            return "Average"
        return "Below average"

    def _impact_classification(self, score_delta: float | None) -> str | None:
        if score_delta is None:
            return None
        if score_delta > 0.5:
            return "positive"
        if score_delta > -0.3:
            return "neutral"
        return "negative"

    def _session_rep_id(self, db: Session, session_id: str) -> str | None:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        return session.rep_id if session is not None else None

    def _upsert_coaching_impact_row(
        self,
        db: Session,
        *,
        manager_id: str,
        org_id: str,
        rep_id: str | None,
        source_session_id: str,
        intervention_type: str,
        intervention_at: datetime,
    ) -> int:
        if not rep_id:
            return 0
        anchor_date = (self._as_utc(intervention_at) or datetime.now(timezone.utc)).date()
        pre_rows = db.scalars(
            select(FactSession)
            .where(
                FactSession.rep_id == rep_id,
                FactSession.manager_id == manager_id,
                FactSession.session_date < anchor_date,
                FactSession.overall_score.is_not(None),
            )
            .order_by(FactSession.session_date.desc(), FactSession.started_at.desc())
            .limit(3)
        ).all()
        post_rows = db.scalars(
            select(FactSession)
            .where(
                FactSession.rep_id == rep_id,
                FactSession.manager_id == manager_id,
                FactSession.session_date > anchor_date,
                FactSession.session_date <= (anchor_date + timedelta(days=self.IMPACT_WINDOW_DAYS)),
                FactSession.overall_score.is_not(None),
            )
            .order_by(FactSession.session_date.asc(), FactSession.started_at.asc())
            .limit(3)
        ).all()
        if not post_rows:
            return 0

        pre_scores = [float(row.overall_score) for row in reversed(pre_rows) if row.overall_score is not None]
        post_scores = [float(row.overall_score) for row in post_rows if row.overall_score is not None]
        pre_score = round(mean(pre_scores), 4) if pre_scores else self._safe_float(
            db.scalar(select(Scorecard.overall_score).where(Scorecard.session_id == source_session_id))
        )
        post_score = round(mean(post_scores), 4) if post_scores else None
        score_delta = round(post_score - pre_score, 4) if pre_score is not None and post_score is not None else None

        row = db.scalar(
            select(ManagerCoachingImpact).where(
                ManagerCoachingImpact.manager_id == manager_id,
                ManagerCoachingImpact.source_session_id == source_session_id,
                ManagerCoachingImpact.intervention_type == intervention_type,
            )
        )
        if row is None:
            row = ManagerCoachingImpact(
                manager_id=manager_id,
                rep_id=rep_id,
                org_id=org_id,
                source_session_id=source_session_id,
                intervention_type=intervention_type,
                intervention_at=intervention_at,
            )
            db.add(row)

        row.rep_id = rep_id
        row.org_id = org_id
        row.source_session_id = source_session_id
        row.intervention_type = intervention_type
        row.intervention_at = intervention_at
        row.pre_intervention_score = pre_score
        row.post_intervention_score = post_score
        row.score_delta = score_delta
        row.sessions_observed = len(post_rows)
        row.observation_window_days = self.IMPACT_WINDOW_DAYS
        row.impact_classified = self._impact_classification(score_delta)
        row.impact_computed_at = datetime.now(timezone.utc)
        db.flush()
        return 1

    def _risk_level_for_score(self, risk_score: float) -> str:
        if risk_score < 0.2:
            return "low"
        if risk_score < 0.4:
            return "medium"
        if risk_score < 0.7:
            return "high"
        return "critical"

    def _session_frequency(self, score_history: list[float], window_days: int) -> float:
        if not score_history:
            return 0.0
        return round(len(score_history[-window_days:]) / max(1, window_days), 4)

    def _mean_optional(self, values) -> float | None:
        items = [float(value) for value in values]
        if not items:
            return None
        return mean(items)

    def _as_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _safe_float(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
