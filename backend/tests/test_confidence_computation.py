from __future__ import annotations

from types import SimpleNamespace

from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session

from app.services.grading_service import GradingService


def test_confidence_computation_increases_with_more_evidence():
    service = GradingService()

    def turn(turn_id: str, *, stage: str, text: str, objection_tags: list[str] | None = None):
        return SimpleNamespace(
            id=turn_id,
            stage=stage,
            text=text,
            objection_tags=objection_tags or [],
            speaker=SimpleNamespace(value="rep"),
        )

    low_session = SimpleNamespace(
        turns=[
            turn("t1", stage="opening", text="Hi there"),
            turn("t2", stage="pitch", text="We do pest control"),
        ]
    )
    high_session = SimpleNamespace(
        turns=[
            turn("t1", stage="opening", text="Hi there"),
            turn("t2", stage="pitch", text="We lower your rate with better coverage"),
            turn("t3", stage="objection_handling", text="I hear the price concern", objection_tags=["price"]),
            turn("t4", stage="objection_handling", text="That is exactly why we lock the rate", objection_tags=["price"]),
            turn("t5", stage="close_attempt", text="If that works, we can schedule today"),
            turn("t6", stage="close_attempt", text="The next step is getting the first service booked"),
        ]
    )
    grading = {
        "evidence_turn_ids": ["t1", "t2", "t3", "t4", "t5"],
        "category_scores": {
            "opening": {"score": 7.2},
            "pitch_delivery": {"score": 7.0},
            "objection_handling": {"score": 7.6},
            "closing_technique": {"score": 7.1},
            "professionalism": {"score": 7.5},
        },
    }
    low_grading = {
        "evidence_turn_ids": ["t1"],
        "category_scores": {
            "opening": {"score": 6.5},
            "pitch_delivery": {"score": 6.0},
            "objection_handling": {"score": 0.0},
        },
    }

    low_confidence = service.compute_confidence(low_session, low_grading)
    high_confidence = service.compute_confidence(high_session, grading)

    assert 0.0 <= low_confidence <= 1.0
    assert 0.0 <= high_confidence <= 1.0
    assert high_confidence > low_confidence


def test_confidence_is_stored_on_grading_run_and_categories(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "Hi, I can lower your monthly rate, handle the objection, and book the next step today.",
    )

    scorecard, grading_run = _await_scorecard_and_run(session_id)

    assert 0.0 <= grading_run.confidence_score <= 1.0
    for category_key, category in scorecard.category_scores.items():
        assert "confidence" in category, category_key
        assert 0.0 <= float(category["confidence"]) <= 1.0
