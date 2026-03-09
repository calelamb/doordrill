from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.predictive import ManagerCoachingImpact, RepCohortBenchmark, RepRiskScore, RepSkillForecast, ScenarioOutcomeAggregate
from app.models.scorecard import ManagerCoachingNote, Scorecard
from app.models.scenario import Scenario
from app.models.session import Session as DrillSession
from app.models.training import AdaptiveRecommendationOutcome
from app.models.types import AssignmentStatus, SessionStatus
from app.models.user import Team, User
from app.models.types import UserRole
from app.models.warehouse import DimRep, FactRepDaily, FactSession
from app.services.adaptive_training_service import AdaptiveTrainingService
from app.services.predictive_modeling_service import PredictiveModelingService
from tests.test_adaptive_training import _seed_adaptive_history


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _rep_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}


def _add_rep_to_manager_team(db, seed_org: dict[str, str], *, name: str, email: str) -> User:
    team = db.scalar(select(Team).where(Team.manager_id == seed_org["manager_id"]))
    rep = User(
        org_id=seed_org["org_id"],
        team_id=team.id if team else None,
        role=UserRole.REP,
        name=name,
        email=email,
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)
    return rep


def _seed_outcome_rows(
    db,
    *,
    seed_org: dict[str, str],
    scenario_id: str,
    skill: str,
    recommended_difficulty: int,
    deltas: list[float],
    successes: list[bool],
) -> None:
    for index, (delta, success) in enumerate(zip(deltas, successes), start=1):
        assignment = Assignment(
            scenario_id=scenario_id,
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"adaptive_training": {"source": f"pm3-test-{index}"}},
        )
        db.add(assignment)
        db.flush()
        db.add(
            AdaptiveRecommendationOutcome(
                assignment_id=assignment.id,
                session_id=None,
                rep_id=seed_org["rep_id"],
                manager_id=seed_org["manager_id"],
                recommended_scenario_id=scenario_id,
                recommended_difficulty=recommended_difficulty,
                recommended_focus_skills=[skill],
                baseline_skill_scores={skill: 4.8},
                baseline_overall_score=5.5,
                outcome_skill_scores={skill: round(4.8 + delta, 2)},
                outcome_overall_score=round(5.8 + delta, 2),
                skill_delta={skill: delta},
                recommendation_success=success,
                outcome_written_at=datetime.now(timezone.utc),
            )
        )
    db.commit()


def _seed_cohort_scores(
    db,
    *,
    rep: User,
    org_id: str,
    hire_cohort: date,
    overall_score: float,
    skill_scores: dict[str, float],
) -> None:
    team = db.scalar(select(Team).where(Team.id == rep.team_id)) if rep.team_id else None
    db.add(
        DimRep(
            rep_id=rep.id,
            org_id=org_id,
            team_id=rep.team_id,
            rep_name=rep.name,
            hire_cohort=hire_cohort,
            industry="pest_control",
            is_active=True,
            total_sessions=10,
            first_session_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            last_session_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
            last_refreshed_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        FactRepDaily(
            rep_id=rep.id,
            org_id=org_id,
            manager_id=team.manager_id if team is not None and team.manager_id else rep.id,
            session_date=date(2025, 1, 10),
            session_count=1,
            scored_count=1,
            avg_score=overall_score,
            min_score=overall_score,
            max_score=overall_score,
            avg_objection_handling=skill_scores.get("objection_handling"),
            avg_closing_technique=skill_scores.get("closing"),
            total_duration_seconds=300,
            barge_in_count=0,
            override_count=0,
            coaching_note_count=0,
        )
    )
    for skill, score in skill_scores.items():
        db.add(
            RepSkillForecast(
                rep_id=rep.id,
                org_id=org_id,
                skill=skill,
                current_score=score,
                velocity=0.2,
                sessions_to_readiness=3,
                projected_ready_at_sessions=8,
                readiness_threshold=7.0,
                sample_size=5,
                r_squared=0.9,
                forecast_computed_at=datetime.now(timezone.utc),
            )
        )


def _create_scored_session_for_impact(
    db,
    *,
    seed_org: dict[str, str],
    rep_id: str,
    started_at: datetime,
    overall_score: float,
) -> str:
    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=rep_id,
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "pm5-test"},
    )
    db.add(assignment)
    db.flush()
    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=rep_id,
        scenario_id=seed_org["scenario_id"],
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        duration_seconds=300,
        status=SessionStatus.GRADED,
    )
    db.add(session)
    db.flush()
    db.add(
        Scorecard(
            session_id=session.id,
            overall_score=overall_score,
            category_scores={},
            highlights=[],
            ai_summary="pm5 test scorecard",
            evidence_turn_ids=[],
            weakness_tags=[],
        )
    )
    db.flush()
    return session.id


def _seed_fact_session(
    db,
    *,
    session_id: str,
    seed_org: dict[str, str],
    rep_id: str,
    session_date: date,
    overall_score: float,
) -> None:
    db.add(
        FactSession(
            session_id=session_id,
            org_id=seed_org["org_id"],
            manager_id=seed_org["manager_id"],
            rep_id=rep_id,
            scenario_id=seed_org["scenario_id"],
            session_date=session_date,
            started_at=datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc),
            ended_at=datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=5),
            duration_seconds=300,
            status="graded",
            overall_score=overall_score,
            turn_count=0,
            rep_turn_count=0,
            ai_turn_count=0,
            objection_count=0,
            barge_in_count=0,
            has_manager_review=False,
            has_coaching_note=False,
            etl_version="1.0",
            etl_written_at=datetime.now(timezone.utc),
        )
    )


def _seed_coaching_note_intervention(
    db,
    *,
    seed_org: dict[str, str],
    rep_id: str,
    intervention_at: datetime,
    pre_scores: list[float],
    post_scores: list[float],
) -> None:
    source_session_id = _create_scored_session_for_impact(
        db,
        seed_org=seed_org,
        rep_id=rep_id,
        started_at=intervention_at,
        overall_score=pre_scores[-1] if pre_scores else 5.0,
    )
    scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == source_session_id))
    assert scorecard is not None
    note = ManagerCoachingNote(
        scorecard_id=scorecard.id,
        reviewer_id=seed_org["manager_id"],
        note="pm5 coaching note",
        visible_to_rep=True,
        weakness_tags=["closing"],
    )
    db.add(note)
    db.flush()
    note.created_at = intervention_at
    for index, score in enumerate(pre_scores, start=1):
        session_id = _create_scored_session_for_impact(
            db,
            seed_org=seed_org,
            rep_id=rep_id,
            started_at=intervention_at - timedelta(days=(len(pre_scores) - index + 1)),
            overall_score=score,
        )
        _seed_fact_session(
            db,
            session_id=session_id,
            seed_org=seed_org,
            rep_id=rep_id,
            session_date=(intervention_at - timedelta(days=(len(pre_scores) - index + 1))).date(),
            overall_score=score,
        )
    for index, score in enumerate(post_scores, start=1):
        session_id = _create_scored_session_for_impact(
            db,
            seed_org=seed_org,
            rep_id=rep_id,
            started_at=intervention_at + timedelta(days=index),
            overall_score=score,
        )
        _seed_fact_session(
            db,
            session_id=session_id,
            seed_org=seed_org,
            rep_id=rep_id,
            session_date=(intervention_at + timedelta(days=index)).date(),
            overall_score=score,
        )
    db.commit()


def test_forecast_computed_and_persisted(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    forecasts = service.compute_and_persist_forecast(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "objection_handling", "score": 6.0, "history": [4.0, 4.5, 5.0, 5.5, 6.0]},
            {"skill": "closing", "score": 5.8, "history": [4.2, 4.6, 5.0, 5.4, 5.8]},
        ],
    )

    rows = db.scalars(
        select(RepSkillForecast)
        .where(RepSkillForecast.rep_id == seed_org["rep_id"])
        .order_by(RepSkillForecast.skill.asc())
    ).all()

    assert len(forecasts) == 2
    assert len(rows) == 2
    assert rows[0].skill == "closing"
    assert rows[1].skill == "objection_handling"
    assert rows[1].sample_size == 5
    assert rows[1].velocity == pytest.approx(0.5, abs=1e-4)
    assert rows[1].r_squared == pytest.approx(1.0, abs=1e-6)

    db.close()


def test_sessions_to_readiness_formula(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    forecasts = service.compute_and_persist_forecast(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "objection_handling", "score": 5.0, "history": [3.0, 3.5, 4.0, 4.5, 5.0]},
        ],
    )

    assert forecasts[0]["velocity"] == pytest.approx(0.5, abs=1e-4)
    assert forecasts[0]["sessions_to_readiness"] == 4
    assert forecasts[0]["projected_ready_at_sessions"] == 9

    db.close()


def test_zero_velocity_returns_none(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    forecasts = service.compute_and_persist_forecast(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "closing", "score": 5.2, "history": [5.2, 5.2, 5.2, 5.2, 5.2]},
        ],
    )

    assert forecasts[0]["velocity"] == pytest.approx(0.0, abs=1e-6)
    assert forecasts[0]["sessions_to_readiness"] is None
    assert forecasts[0]["projected_ready_at_sessions"] is None

    db.close()


def test_team_forecast_aggregation(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    second_rep = _add_rep_to_manager_team(
        db,
        seed_org,
        name="Nina Newell",
        email="nina.predictive@example.com",
    )
    third_rep = _add_rep_to_manager_team(
        db,
        seed_org,
        name="Rico Risk",
        email="rico.predictive@example.com",
    )

    service.compute_and_persist_forecast(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "objection_handling", "score": 7.4, "history": [6.6, 6.9, 7.1, 7.3, 7.4]},
        ],
    )
    service.compute_and_persist_forecast(
        db,
        rep_id=second_rep.id,
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "objection_handling", "score": 5.0, "history": [3.0, 3.5, 4.0, 4.5, 5.0]},
        ],
    )
    service.compute_and_persist_forecast(
        db,
        rep_id=third_rep.id,
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "objection_handling", "score": 5.1, "history": [5.1, 5.1, 5.1, 5.1, 5.1]},
        ],
    )

    forecast = service.get_team_forecast(
        db,
        manager_id=seed_org["manager_id"],
        org_id=seed_org["org_id"],
    )

    assert forecast["team_size"] == 3
    assert forecast["reps_already_ready"] == 1
    assert forecast["reps_on_track"] == 1
    assert forecast["reps_at_risk"] == 1
    assert len(forecast["rep_summaries"]) == 3

    db.close()


def test_forecast_endpoints_return_rep_and_team_data(client, seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    second_rep = _add_rep_to_manager_team(
        db,
        seed_org,
        name="Tina Team",
        email="tina.predictive@example.com",
    )
    service.compute_and_persist_forecast(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "objection_handling", "score": 5.5, "history": [4.0, 4.4, 4.8, 5.2, 5.5]},
        ],
    )
    service.compute_and_persist_forecast(
        db,
        rep_id=second_rep.id,
        org_id=seed_org["org_id"],
        skill_profile=[
            {"skill": "closing", "score": 5.0, "history": [4.2, 4.4, 4.6, 4.8, 5.0]},
        ],
    )
    db.close()

    rep_response = client.get(
        f"/rep/{seed_org['rep_id']}/forecast",
        headers=_rep_headers(seed_org),
    )
    team_response = client.get(
        f"/manager/{seed_org['manager_id']}/team-forecast",
        headers=_manager_headers(seed_org),
    )

    assert rep_response.status_code == 200
    assert rep_response.json()["rep_id"] == seed_org["rep_id"]
    assert rep_response.json()["skill_forecasts"][0]["skill"] == "objection_handling"

    assert team_response.status_code == 200
    assert team_response.json()["manager_id"] == seed_org["manager_id"]
    assert team_response.json()["team_size"] == 2


def test_plateau_detection(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    risk = service.compute_and_persist_risk_score(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        manager_id=seed_org["manager_id"],
        score_history=[5.0] * 8,
        last_session_at=datetime.now(timezone.utc),
    )
    row = db.scalar(select(RepRiskScore).where(RepRiskScore.rep_id == seed_org["rep_id"]))

    assert risk["is_plateauing"] is True
    assert risk["risk_score"] >= 0.4
    assert risk["triggered_alerts"] == ["plateau"]
    assert row is not None
    assert row.plateau_duration_sessions == 8

    db.close()


def test_decline_detection(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    risk = service.compute_and_persist_risk_score(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        manager_id=seed_org["manager_id"],
        score_history=[7, 6.5, 6, 5.5, 5, 4.5, 4, 3.5, 3, 2.5],
        last_session_at=datetime.now(timezone.utc),
    )

    assert risk["is_declining"] is True
    assert risk["decline_slope"] < -0.05
    assert "decline" in risk["triggered_alerts"]

    db.close()


def test_disengagement_30_days(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    risk = service.compute_and_persist_risk_score(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        manager_id=seed_org["manager_id"],
        score_history=[6.0, 6.1, 6.2],
        last_session_at=datetime.now(timezone.utc) - timedelta(days=30),
    )

    assert risk["is_disengaging"] is True
    assert risk["days_since_last_session"] >= 30
    assert "disengaging" in risk["triggered_alerts"]

    db.close()


@pytest.mark.parametrize(
    ("risk_score", "expected"),
    [
        (0.1, "low"),
        (0.3, "medium"),
        (0.55, "high"),
        (0.75, "critical"),
    ],
)
def test_risk_level_thresholds(seed_org, risk_score, expected):
    service = PredictiveModelingService()
    assert service._risk_level_for_score(risk_score) == expected


def test_snooze_suppresses_at_risk_query(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()

    second_rep = _add_rep_to_manager_team(
        db,
        seed_org,
        name="Snoozed Sam",
        email="snoozed.sam@example.com",
    )

    service.compute_and_persist_risk_score(
        db,
        rep_id=seed_org["rep_id"],
        org_id=seed_org["org_id"],
        manager_id=seed_org["manager_id"],
        score_history=[5.0] * 8,
        last_session_at=datetime.now(timezone.utc),
    )
    service.compute_and_persist_risk_score(
        db,
        rep_id=second_rep.id,
        org_id=seed_org["org_id"],
        manager_id=seed_org["manager_id"],
        score_history=[7, 6.5, 6, 5.5, 5, 4.5, 4, 3.5, 3, 2.5],
        last_session_at=datetime.now(timezone.utc),
    )

    service.snooze_risk_alert(db, rep_id=second_rep.id, snooze_days=7)
    at_risk = service.get_at_risk_reps(
        db,
        manager_id=seed_org["manager_id"],
        org_id=seed_org["org_id"],
        min_risk_level="medium",
    )

    assert [item["rep_id"] for item in at_risk] == [seed_org["rep_id"]]

    db.close()


def test_outcome_aggregate_refresh(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        _seed_outcome_rows(
            db,
            seed_org=seed_org,
            scenario_id=seed_org["scenario_id"],
            skill="closing",
            recommended_difficulty=2,
            deltas=[0.8, 0.6, 0.7, 0.5, 0.9],
            successes=[True, True, True, True, True],
        )

        written = service.refresh_scenario_outcome_aggregates(db, org_id=seed_org["org_id"])
        row = db.scalar(
            select(ScenarioOutcomeAggregate).where(
                ScenarioOutcomeAggregate.scenario_id == seed_org["scenario_id"],
                ScenarioOutcomeAggregate.focus_skill == "closing",
                ScenarioOutcomeAggregate.difficulty_bucket == 2,
            )
        )

        assert written == 1
        assert row is not None
        assert row.sample_size == 5
        assert row.success_rate == pytest.approx(1.0, abs=1e-4)
        assert row.avg_skill_delta == pytest.approx(0.7, abs=1e-4)
    finally:
        db.close()


def test_outcome_ranked_returns_sorted(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        scenario_a = Scenario(
            org_id=seed_org["org_id"],
            name="Outcome Ranked A",
            industry="pest_control",
            difficulty=2,
            description="A",
            persona={"attitude": "neutral", "concerns": ["timing"]},
            rubric={"opening": 10},
            stages=["close_attempt"],
            created_by_id=seed_org["manager_id"],
        )
        scenario_b = Scenario(
            org_id=seed_org["org_id"],
            name="Outcome Ranked B",
            industry="pest_control",
            difficulty=2,
            description="B",
            persona={"attitude": "neutral", "concerns": ["timing"]},
            rubric={"opening": 10},
            stages=["close_attempt"],
            created_by_id=seed_org["manager_id"],
        )
        db.add_all([scenario_a, scenario_b])
        db.flush()
        db.add_all(
            [
                ScenarioOutcomeAggregate(
                    scenario_id=scenario_a.id,
                    focus_skill="closing",
                    difficulty_bucket=2,
                    sample_size=4,
                    success_rate=0.75,
                    avg_skill_delta=0.4,
                    avg_outcome_score=6.2,
                    last_refreshed_at=datetime.now(timezone.utc),
                ),
                ScenarioOutcomeAggregate(
                    scenario_id=scenario_b.id,
                    focus_skill="closing",
                    difficulty_bucket=2,
                    sample_size=6,
                    success_rate=0.8,
                    avg_skill_delta=0.9,
                    avg_outcome_score=6.8,
                    last_refreshed_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()

        ranked = service.get_outcome_ranked_scenarios(
            db,
            focus_skill="closing",
            difficulty=2,
            limit=5,
        )

        assert [item["scenario_id"] for item in ranked] == [
            scenario_b.id,
            scenario_a.id,
        ]
    finally:
        db.close()


def test_sample_size_filter(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        db.add(
            ScenarioOutcomeAggregate(
                scenario_id=seed_org["scenario_id"],
                focus_skill="closing",
                difficulty_bucket=2,
                sample_size=2,
                success_rate=1.0,
                avg_skill_delta=0.9,
                avg_outcome_score=6.8,
                last_refreshed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        ranked = service.get_outcome_ranked_scenarios(db, focus_skill="closing", difficulty=2)
        assert ranked == []
    finally:
        db.close()


def test_outcome_boost_applied_to_recommendations(seed_org):
    scenario_ids = _seed_adaptive_history(seed_org)
    db = SessionLocal()
    try:
        service = AdaptiveTrainingService()
        baseline = service.build_plan(db, rep_id=seed_org["rep_id"])
        weakest_skill = baseline["weakest_skills"][0]
        recommended_difficulty = baseline["recommended_difficulty"]
        boosted_scenario_id = (
            scenario_ids["objection_scenario_id"]
            if weakest_skill == "objection_handling"
            else scenario_ids["closing_scenario_id"]
        )
        _seed_outcome_rows(
            db,
            seed_org=seed_org,
            scenario_id=boosted_scenario_id,
            skill=weakest_skill,
            recommended_difficulty=recommended_difficulty,
            deltas=[1.0, 0.9, 1.1, 0.8],
            successes=[True, True, True, True],
        )
        PredictiveModelingService().refresh_scenario_outcome_aggregates(db, org_id=seed_org["org_id"])

        plan = service.build_plan(db, rep_id=seed_org["rep_id"])
        top = plan["recommended_scenarios"][0]

        assert top["scenario_id"] == boosted_scenario_id
        assert top["outcome_boost"] is True
        assert top["avg_skill_delta_historical"] is not None
    finally:
        db.close()


def test_quarter_label():
    service = PredictiveModelingService()
    assert service._quarter_label(date(2025, 2, 15)) == "2025-Q1"
    assert service._quarter_label(date(2025, 7, 1)) == "2025-Q3"


def test_cohort_benchmarks_refresh(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        reps = [db.get(User, seed_org["rep_id"])]
        reps.append(_add_rep_to_manager_team(db, seed_org, name="Cohort Two", email="cohort.two@example.com"))
        reps.append(_add_rep_to_manager_team(db, seed_org, name="Cohort Three", email="cohort.three@example.com"))
        reps.append(_add_rep_to_manager_team(db, seed_org, name="Cohort Four", email="cohort.four@example.com"))
        scores = [5.0, 6.0, 7.0, 8.0]
        for rep, score in zip(reps, scores):
            assert rep is not None
            _seed_cohort_scores(
                db,
                rep=rep,
                org_id=seed_org["org_id"],
                hire_cohort=date(2025, 2, 15),
                overall_score=score,
                skill_scores={
                    "opening": score,
                    "rapport": score,
                    "pitch_clarity": score,
                    "objection_handling": score,
                    "closing": score,
                },
            )
        db.commit()

        written = service.refresh_cohort_benchmarks(db, org_id=seed_org["org_id"])
        row = db.scalar(
            select(RepCohortBenchmark).where(
                RepCohortBenchmark.rep_id == seed_org["rep_id"],
                RepCohortBenchmark.skill == "overall",
            )
        )

        assert written == 24
        assert row is not None
        assert row.cohort_p50 == pytest.approx(6.5, abs=1e-4)
    finally:
        db.close()


def test_percentile_calculation(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        reps = [db.get(User, seed_org["rep_id"])]
        reps.append(_add_rep_to_manager_team(db, seed_org, name="Median Low", email="median.low@example.com"))
        reps.append(_add_rep_to_manager_team(db, seed_org, name="Median High", email="median.high@example.com"))
        scores = [4.0, 5.0, 6.0]
        for rep, score in zip(reps, scores):
            assert rep is not None
            _seed_cohort_scores(
                db,
                rep=rep,
                org_id=seed_org["org_id"],
                hire_cohort=date(2025, 2, 15),
                overall_score=score,
                skill_scores={
                    "opening": score,
                    "rapport": score,
                    "pitch_clarity": score,
                    "objection_handling": score,
                    "closing": score,
                },
            )
        db.commit()

        service.refresh_cohort_benchmarks(db, org_id=seed_org["org_id"])
        benchmark = service.get_rep_benchmarks(db, rep_id=reps[1].id)
        overall = next(item for item in benchmark["skills"] if item["skill"] == "overall")

        assert overall["percentile_in_cohort"] == pytest.approx(50.0, abs=0.1)
    finally:
        db.close()


def test_interpretation_labels():
    service = PredictiveModelingService()
    assert service._benchmark_interpretation(85) == "Top performer"
    assert service._benchmark_interpretation(40) == "Average"


def test_get_rep_benchmarks_returns_all_skills(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        skills = ["overall", "opening", "rapport", "pitch_clarity", "objection_handling", "closing"]
        for skill in skills:
            db.add(
                RepCohortBenchmark(
                    rep_id=seed_org["rep_id"],
                    org_id=seed_org["org_id"],
                    skill=skill,
                    cohort_label="2025-Q1",
                    cohort_size=4,
                    current_score=6.0,
                    cohort_mean=6.0,
                    cohort_p25=5.5,
                    cohort_p50=6.0,
                    cohort_p75=6.5,
                    percentile_in_cohort=50.0,
                    percentile_in_org=50.0,
                    benchmark_computed_at=datetime.now(timezone.utc),
                )
            )
        db.commit()

        benchmark = service.get_rep_benchmarks(db, rep_id=seed_org["rep_id"])
        assert benchmark["cohort_label"] == "2025-Q1"
        assert len(benchmark["skills"]) == 6
    finally:
        db.close()


def test_forecast_endpoint_includes_cohort_benchmarks(client, seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        primary_rep = db.get(User, seed_org["rep_id"])
        second_rep = _add_rep_to_manager_team(db, seed_org, name="Benchmark Two", email="benchmark.two@example.com")
        assert primary_rep is not None
        for rep, score in ((primary_rep, 5.5), (second_rep, 6.5)):
            _seed_cohort_scores(
                db,
                rep=rep,
                org_id=seed_org["org_id"],
                hire_cohort=date(2025, 2, 15),
                overall_score=score,
                skill_scores={
                    "opening": score,
                    "rapport": score,
                    "pitch_clarity": score,
                    "objection_handling": score,
                    "closing": score,
                },
            )
        db.commit()
        service.refresh_cohort_benchmarks(db, org_id=seed_org["org_id"])
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/rep/{seed_org['rep_id']}/forecast",
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cohort_benchmarks"]["rep_id"] == seed_org["rep_id"]
    assert len(body["cohort_benchmarks"]["skills"]) == 6


def test_positive_impact(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        intervention_at = datetime.now(timezone.utc) - timedelta(days=10)
        _seed_coaching_note_intervention(
            db,
            seed_org=seed_org,
            rep_id=seed_org["rep_id"],
            intervention_at=intervention_at,
            pre_scores=[5.0, 5.0, 5.0],
            post_scores=[6.5, 6.5, 6.5],
        )

        processed = service.compute_coaching_impact(
            db,
            manager_id=seed_org["manager_id"],
            org_id=seed_org["org_id"],
        )
        row = db.scalar(select(ManagerCoachingImpact))

        assert processed == 1
        assert row is not None
        assert row.score_delta == pytest.approx(1.5, abs=1e-4)
        assert row.impact_classified == "positive"
    finally:
        db.close()


def test_neutral_impact(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        intervention_at = datetime.now(timezone.utc) - timedelta(days=10)
        _seed_coaching_note_intervention(
            db,
            seed_org=seed_org,
            rep_id=seed_org["rep_id"],
            intervention_at=intervention_at,
            pre_scores=[6.0, 6.0, 6.0],
            post_scores=[6.2, 6.2, 6.2],
        )

        service.compute_coaching_impact(db, manager_id=seed_org["manager_id"], org_id=seed_org["org_id"])
        row = db.scalar(select(ManagerCoachingImpact))

        assert row is not None
        assert row.score_delta == pytest.approx(0.2, abs=1e-4)
        assert row.impact_classified == "neutral"
    finally:
        db.close()


def test_negative_impact(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        intervention_at = datetime.now(timezone.utc) - timedelta(days=10)
        _seed_coaching_note_intervention(
            db,
            seed_org=seed_org,
            rep_id=seed_org["rep_id"],
            intervention_at=intervention_at,
            pre_scores=[7.0, 7.0, 7.0],
            post_scores=[6.0, 6.0, 6.0],
        )

        service.compute_coaching_impact(db, manager_id=seed_org["manager_id"], org_id=seed_org["org_id"])
        row = db.scalar(select(ManagerCoachingImpact))

        assert row is not None
        assert row.score_delta == pytest.approx(-1.0, abs=1e-4)
        assert row.impact_classified == "negative"
    finally:
        db.close()


def test_manager_impact_summary(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        primary_rep = db.get(User, seed_org["rep_id"])
        second_rep = _add_rep_to_manager_team(db, seed_org, name="Impact Two", email="impact.two@example.com")
        assert primary_rep is not None
        for index in range(7):
            session_id = _create_scored_session_for_impact(
                db,
                seed_org=seed_org,
                rep_id=seed_org["rep_id"],
                started_at=datetime.now(timezone.utc) - timedelta(days=index + 1),
                overall_score=6.0,
            )
            db.add(
                ManagerCoachingImpact(
                    manager_id=seed_org["manager_id"],
                    rep_id=seed_org["rep_id"],
                    org_id=seed_org["org_id"],
                    source_session_id=session_id,
                    intervention_type="coaching_note",
                    intervention_at=datetime.now(timezone.utc) - timedelta(days=index + 1),
                    pre_intervention_score=5.0,
                    post_intervention_score=6.0,
                    score_delta=1.0,
                    sessions_observed=3,
                    observation_window_days=14,
                    impact_classified="positive",
                    impact_computed_at=datetime.now(timezone.utc) - timedelta(days=index),
                )
            )
        for index in range(3):
            session_id = _create_scored_session_for_impact(
                db,
                seed_org=seed_org,
                rep_id=second_rep.id,
                started_at=datetime.now(timezone.utc) - timedelta(days=index + 10),
                overall_score=6.0,
            )
            db.add(
                ManagerCoachingImpact(
                    manager_id=seed_org["manager_id"],
                    rep_id=second_rep.id,
                    org_id=seed_org["org_id"],
                    source_session_id=session_id,
                    intervention_type="override_label",
                    intervention_at=datetime.now(timezone.utc) - timedelta(days=index + 10),
                    pre_intervention_score=6.0,
                    post_intervention_score=6.0,
                    score_delta=0.0,
                    sessions_observed=3,
                    observation_window_days=14,
                    impact_classified="neutral",
                    impact_computed_at=datetime.now(timezone.utc) - timedelta(days=index + 10),
                )
            )
        db.commit()

        summary = service.get_manager_impact_summary(db, manager_id=seed_org["manager_id"])
        assert summary["total_interventions_measured"] == 10
        assert summary["positive_impact_rate"] == pytest.approx(0.7, abs=1e-4)
        assert summary["best_impact_rep"]["rep_id"] == seed_org["rep_id"]
        assert len(summary["recent_impacts"]) == 5
    finally:
        db.close()


def test_no_post_sessions(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        intervention_at = datetime.now(timezone.utc) - timedelta(days=10)
        _seed_coaching_note_intervention(
            db,
            seed_org=seed_org,
            rep_id=seed_org["rep_id"],
            intervention_at=intervention_at,
            pre_scores=[5.0, 5.1, 5.2],
            post_scores=[],
        )

        processed = service.compute_coaching_impact(db, manager_id=seed_org["manager_id"], org_id=seed_org["org_id"])
        assert processed == 0
        assert db.scalar(select(ManagerCoachingImpact)) is None
    finally:
        db.close()


def test_coaching_impact_endpoint_returns_summary(client, seed_org):
    db = SessionLocal()
    try:
        session_id = _create_scored_session_for_impact(
            db,
            seed_org=seed_org,
            rep_id=seed_org["rep_id"],
            started_at=datetime.now(timezone.utc) - timedelta(days=1),
            overall_score=6.0,
        )
        db.add(
            ManagerCoachingImpact(
                manager_id=seed_org["manager_id"],
                rep_id=seed_org["rep_id"],
                org_id=seed_org["org_id"],
                source_session_id=session_id,
                intervention_type="coaching_note",
                intervention_at=datetime.now(timezone.utc) - timedelta(days=1),
                pre_intervention_score=5.0,
                post_intervention_score=6.0,
                score_delta=1.0,
                sessions_observed=3,
                observation_window_days=14,
                impact_classified="positive",
                impact_computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/manager/{seed_org['manager_id']}/coaching-impact",
        headers=_manager_headers(seed_org),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manager_id"] == seed_org["manager_id"]
    assert body["total_interventions_measured"] == 1


def test_team_intelligence_snapshot_structure(client, seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        service.compute_and_persist_forecast(
            db,
            rep_id=seed_org["rep_id"],
            org_id=seed_org["org_id"],
            skill_profile=[
                {"skill": "opening", "score": 6.2, "history": [5.0, 5.4, 5.8, 6.0, 6.2]},
                {"skill": "objection_handling", "score": 5.4, "history": [4.8, 5.0, 5.1, 5.2, 5.4]},
            ],
        )
        service.compute_and_persist_risk_score(
            db,
            rep_id=seed_org["rep_id"],
            org_id=seed_org["org_id"],
            manager_id=seed_org["manager_id"],
            score_history=[5.0] * 8,
            last_session_at=datetime.now(timezone.utc),
        )
        db.add(
            RepCohortBenchmark(
                rep_id=seed_org["rep_id"],
                org_id=seed_org["org_id"],
                skill="overall",
                cohort_label="2025-Q1",
                cohort_size=4,
                current_score=5.8,
                cohort_mean=5.5,
                cohort_p25=5.0,
                cohort_p50=5.5,
                cohort_p75=6.0,
                percentile_in_cohort=60.0,
                percentile_in_org=55.0,
                benchmark_computed_at=datetime.now(timezone.utc),
            )
        )
        session_id = _create_scored_session_for_impact(
            db,
            seed_org=seed_org,
            rep_id=seed_org["rep_id"],
            started_at=datetime.now(timezone.utc) - timedelta(days=1),
            overall_score=6.0,
        )
        db.add(
            ManagerCoachingImpact(
                manager_id=seed_org["manager_id"],
                rep_id=seed_org["rep_id"],
                org_id=seed_org["org_id"],
                source_session_id=session_id,
                intervention_type="coaching_note",
                intervention_at=datetime.now(timezone.utc) - timedelta(days=1),
                pre_intervention_score=5.2,
                post_intervention_score=6.0,
                score_delta=0.8,
                sessions_observed=3,
                observation_window_days=14,
                impact_classified="positive",
                impact_computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/manager/{seed_org['manager_id']}/team-intelligence",
        headers=_manager_headers(seed_org),
    )

    assert response.status_code == 200
    body = response.json()
    assert {
        "manager_id",
        "org_id",
        "snapshot_at",
        "team_size",
        "avg_readiness_score",
        "reps_ready",
        "reps_on_track",
        "reps_at_risk",
        "projected_team_readiness_in_sessions",
        "team_skill_averages",
        "weakest_team_skill",
        "strongest_team_skill",
        "at_risk_reps",
        "cohort_comparison",
        "coaching_effectiveness",
        "projection",
    }.issubset(body.keys())
    assert body["manager_id"] == seed_org["manager_id"]
    assert body["at_risk_reps"][0]["name"]
    assert set(body["projection"].keys()) == {"30d", "60d", "90d"}


def test_30_60_90_projection_increases(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        second_rep = _add_rep_to_manager_team(
            db,
            seed_org,
            name="Projection Two",
            email="projection.two@example.com",
        )
        for rep_id, score in ((seed_org["rep_id"], 5.0), (second_rep.id, 5.6)):
            db.add(
                RepSkillForecast(
                    rep_id=rep_id,
                    org_id=seed_org["org_id"],
                    skill="closing",
                    current_score=score,
                    velocity=0.03,
                    sessions_to_readiness=20,
                    projected_ready_at_sessions=30,
                    readiness_threshold=7.0,
                    sample_size=5,
                    r_squared=0.9,
                    forecast_computed_at=datetime.now(timezone.utc),
                )
            )
            db.add(
                RepRiskScore(
                    rep_id=rep_id,
                    org_id=seed_org["org_id"],
                    manager_id=seed_org["manager_id"],
                    risk_score=0.1,
                    risk_level="low",
                    is_plateauing=False,
                    is_declining=False,
                    is_disengaging=False,
                    plateau_duration_sessions=None,
                    decline_slope=None,
                    days_since_last_session=1,
                    session_frequency_7d=7.0,
                    session_frequency_30d=14.0,
                    triggered_alerts=[],
                    risk_computed_at=datetime.now(timezone.utc),
                )
            )
        db.commit()

        snapshot = service.get_team_intelligence_snapshot(
            db,
            manager_id=seed_org["manager_id"],
            org_id=seed_org["org_id"],
        )

        assert snapshot["projection"]["30d"]["reps_reaching_readiness"] == 0
        assert snapshot["projection"]["60d"]["reps_reaching_readiness"] == 1
        assert snapshot["projection"]["90d"]["reps_reaching_readiness"] == 2
    finally:
        db.close()


def test_projection_with_no_velocity(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        db.add(
            RepSkillForecast(
                rep_id=seed_org["rep_id"],
                org_id=seed_org["org_id"],
                skill="closing",
                current_score=6.2,
                velocity=None,
                sessions_to_readiness=None,
                projected_ready_at_sessions=None,
                readiness_threshold=7.0,
                sample_size=2,
                r_squared=None,
                forecast_computed_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            RepRiskScore(
                rep_id=seed_org["rep_id"],
                org_id=seed_org["org_id"],
                manager_id=seed_org["manager_id"],
                risk_score=0.4,
                risk_level="high",
                is_plateauing=True,
                is_declining=False,
                is_disengaging=False,
                plateau_duration_sessions=6,
                decline_slope=None,
                days_since_last_session=1,
                session_frequency_7d=7.0,
                session_frequency_30d=14.0,
                triggered_alerts=["plateau"],
                risk_computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        snapshot = service.get_team_intelligence_snapshot(
            db,
            manager_id=seed_org["manager_id"],
            org_id=seed_org["org_id"],
        )

        assert snapshot["projection"]["30d"]["projected_avg_score"] == pytest.approx(6.2, abs=1e-4)
        assert snapshot["projection"]["60d"]["projected_avg_score"] == pytest.approx(6.2, abs=1e-4)
        assert snapshot["projection"]["90d"]["projected_avg_score"] == pytest.approx(6.2, abs=1e-4)
    finally:
        db.close()


def test_team_intelligence_empty_team(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        empty_manager = User(
            org_id=seed_org["org_id"],
            role=UserRole.MANAGER,
            name="Empty Manager",
            email="empty.manager@example.com",
        )
        db.add(empty_manager)
        db.commit()
        db.refresh(empty_manager)

        snapshot = service.get_team_intelligence_snapshot(
            db,
            manager_id=empty_manager.id,
            org_id=seed_org["org_id"],
        )

        assert snapshot["team_size"] == 0
        assert snapshot["avg_readiness_score"] == 0.0
        assert snapshot["reps_ready"] == 0
        assert snapshot["reps_on_track"] == 0
        assert snapshot["reps_at_risk"] == 0
        assert snapshot["projected_team_readiness_in_sessions"] == 0.0
        assert snapshot["team_skill_averages"] == {}
        assert snapshot["weakest_team_skill"] is None
        assert snapshot["at_risk_reps"] == []
        assert snapshot["projection"]["30d"]["projected_avg_score"] == 0.0
        assert snapshot["projection"]["90d"]["reps_reaching_readiness"] == 0
    finally:
        db.close()


def test_weakest_skill_identification(seed_org):
    db = SessionLocal()
    service = PredictiveModelingService()
    try:
        second_rep = _add_rep_to_manager_team(
            db,
            seed_org,
            name="Weak Skill Two",
            email="weak.skill.two@example.com",
        )
        for rep_id in (seed_org["rep_id"], second_rep.id):
            db.add_all(
                [
                    RepSkillForecast(
                        rep_id=rep_id,
                        org_id=seed_org["org_id"],
                        skill="opening",
                        current_score=7.2,
                        velocity=0.1,
                        sessions_to_readiness=0,
                        projected_ready_at_sessions=10,
                        readiness_threshold=7.0,
                        sample_size=5,
                        r_squared=0.9,
                        forecast_computed_at=datetime.now(timezone.utc),
                    ),
                    RepSkillForecast(
                        rep_id=rep_id,
                        org_id=seed_org["org_id"],
                        skill="objection_handling",
                        current_score=4.1,
                        velocity=0.1,
                        sessions_to_readiness=29,
                        projected_ready_at_sessions=40,
                        readiness_threshold=7.0,
                        sample_size=5,
                        r_squared=0.9,
                        forecast_computed_at=datetime.now(timezone.utc),
                    ),
                    RepSkillForecast(
                        rep_id=rep_id,
                        org_id=seed_org["org_id"],
                        skill="closing",
                        current_score=8.0,
                        velocity=0.1,
                        sessions_to_readiness=0,
                        projected_ready_at_sessions=8,
                        readiness_threshold=7.0,
                        sample_size=5,
                        r_squared=0.9,
                        forecast_computed_at=datetime.now(timezone.utc),
                    ),
                ]
            )
        db.commit()

        snapshot = service.get_team_intelligence_snapshot(
            db,
            manager_id=seed_org["manager_id"],
            org_id=seed_org["org_id"],
        )

        assert snapshot["weakest_team_skill"] == "objection_handling"
        assert snapshot["strongest_team_skill"] == "closing"
    finally:
        db.close()
