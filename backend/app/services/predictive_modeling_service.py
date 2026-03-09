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

from app.models.predictive import RepCohortBenchmark, RepRiskScore, RepSkillForecast
from app.models.predictive import ScenarioOutcomeAggregate
from app.models.session import Session as DrillSession
from app.models.training import AdaptiveRecommendationOutcome
from app.models.types import UserRole
from app.models.user import Team, User
from app.models.assignment import Assignment
from app.models.warehouse import DimRep, FactRepDaily


class PredictiveModelingService:
    READINESS_THRESHOLD = 7.0
    MIN_SESSIONS_FOR_REGRESSION = 3
    RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    BENCHMARK_SKILLS = ["overall", "opening", "rapport", "pitch_clarity", "objection_handling", "closing"]

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
        reps = db.execute(
            select(User)
            .join(Team, Team.id == User.team_id)
            .where(
                User.org_id == org_id,
                User.role == UserRole.REP,
                Team.manager_id == manager_id,
            )
            .order_by(User.name.asc(), User.created_at.asc())
        ).scalars().all()

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
