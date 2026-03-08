from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.training import AdaptiveRecommendationOutcome
from app.models.types import AssignmentStatus
from app.services.adaptive_training_service import AdaptiveTrainingService
from tests.test_adaptive_training import _seed_adaptive_history


def _seed_outcome_rows(
    db,
    *,
    seed_org: dict[str, str],
    skill: str,
    recommended_difficulty: int,
    success_values: list[bool],
) -> None:
    for index, success in enumerate(success_values, start=1):
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"adaptive_training": {"source": "test"}},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        delta = 0.7 if success else -0.6
        db.add(
            AdaptiveRecommendationOutcome(
                assignment_id=assignment.id,
                session_id=None,
                rep_id=seed_org["rep_id"],
                manager_id=seed_org["manager_id"],
                recommended_scenario_id=seed_org["scenario_id"],
                recommended_difficulty=recommended_difficulty,
                recommended_focus_skills=[skill],
                baseline_skill_scores={skill: 4.8},
                baseline_overall_score=5.6,
                outcome_skill_scores={skill: round(4.8 + delta, 2)},
                outcome_overall_score=6.3 if success else 5.0,
                skill_delta={skill: delta},
                recommendation_success=success,
                outcome_written_at=datetime.now(timezone.utc),
            )
        )
        db.commit()


def test_difficulty_tunes_down_on_failed_outcomes(seed_org):
    _seed_adaptive_history(seed_org)
    db = SessionLocal()
    try:
        service = AdaptiveTrainingService()
        baseline_plan = service.build_plan(db, rep_id=seed_org["rep_id"])
        baseline_difficulty = baseline_plan["recommended_difficulty"]
        weakest_skill = baseline_plan["weakest_skills"][0]

        _seed_outcome_rows(
            db,
            seed_org=seed_org,
            skill=weakest_skill,
            recommended_difficulty=baseline_difficulty,
            success_values=[False, False, False],
        )

        tuned_plan = service.build_plan(db, rep_id=seed_org["rep_id"])
        assert tuned_plan["recommended_difficulty"] == max(1, baseline_difficulty - 1)
    finally:
        db.close()


def test_difficulty_tunes_up_on_successful_outcomes(seed_org):
    _seed_adaptive_history(seed_org)
    db = SessionLocal()
    try:
        service = AdaptiveTrainingService()
        baseline_plan = service.build_plan(db, rep_id=seed_org["rep_id"])
        baseline_difficulty = baseline_plan["recommended_difficulty"]
        weakest_skill = baseline_plan["weakest_skills"][0]

        _seed_outcome_rows(
            db,
            seed_org=seed_org,
            skill=weakest_skill,
            recommended_difficulty=baseline_difficulty,
            success_values=[True, True, True, True, True],
        )

        tuned_plan = service.build_plan(db, rep_id=seed_org["rep_id"])
        assert tuned_plan["recommended_difficulty"] == min(5, baseline_difficulty + 1)
    finally:
        db.close()
