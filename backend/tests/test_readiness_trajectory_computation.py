from __future__ import annotations

from app.services.manager_ai_coaching_service import ManagerAiCoachingService


def test_readiness_trajectory_computation_projects_until_threshold():
    service = ManagerAiCoachingService()
    snapshots = [
        {"skills": {"opening": 6.8, "objection_handling": 5.0, "closing": 5.0}},
        {"skills": {"opening": 6.9, "objection_handling": 5.4, "closing": 5.5}},
        {"skills": {"opening": 7.0, "objection_handling": 5.8, "closing": 6.0}},
        {"skills": {"opening": 7.1, "objection_handling": 6.2, "closing": 6.5}},
    ]
    skill_profile = [
        {"skill": "opening", "score": 7.1, "trend": 0.3, "confidence": 1.0},
        {"skill": "objection_handling", "score": 6.2, "trend": 1.2, "confidence": 1.0},
        {"skill": "closing", "score": 6.5, "trend": 1.5, "confidence": 1.0},
    ]

    trajectory = service._compute_readiness_trajectory(snapshots, skill_profile)

    assert trajectory["sessions_to_readiness"] == 2
    assert trajectory["trajectory_per_skill"]["objection_handling"] == 7.0
    assert trajectory["trajectory_per_skill"]["closing"] == 7.5


def test_readiness_trajectory_computation_returns_none_when_growth_is_stalled():
    service = ManagerAiCoachingService()
    snapshots = [
        {"skills": {"opening": 7.2, "objection_handling": 6.0, "closing": 5.8}},
        {"skills": {"opening": 7.1, "objection_handling": 6.0, "closing": 5.7}},
        {"skills": {"opening": 7.2, "objection_handling": 6.0, "closing": 5.6}},
    ]
    skill_profile = [
        {"skill": "opening", "score": 7.2, "trend": 0.0, "confidence": 1.0},
        {"skill": "objection_handling", "score": 6.0, "trend": 0.0, "confidence": 1.0},
        {"skill": "closing", "score": 5.6, "trend": -0.2, "confidence": 1.0},
    ]

    trajectory = service._compute_readiness_trajectory(snapshots, skill_profile)

    assert trajectory["sessions_to_readiness"] is None
    assert trajectory["trajectory_per_skill"]["closing"] < 5.6
