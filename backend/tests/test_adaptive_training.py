from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.types import AssignmentStatus, EventDirection, SessionStatus, TurnSpeaker


def _seed_adaptive_history(seed_org: dict[str, str]) -> dict[str, str]:
    db = SessionLocal()

    objection_scenario = Scenario(
        name="Layered Objections Homeowner",
        industry="pest_control",
        difficulty=3,
        description="Homeowner is skeptical, already uses a provider, and pushes back on price.",
        persona={"attitude": "skeptical", "concerns": ["price", "trust", "provider"]},
        rubric={"opening": 10, "pitch": 10, "objections": 10, "closing": 10, "professionalism": 10},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
        created_by_id=seed_org["manager_id"],
    )
    closing_scenario = Scenario(
        name="Short Patience Close Attempt",
        industry="pest_control",
        difficulty=2,
        description="Homeowner is busy and wants a quick reason to move forward or end the conversation.",
        persona={"attitude": "busy", "concerns": ["timing", "spouse"]},
        rubric={"opening": 10, "pitch": 10, "objections": 10, "closing": 10, "professionalism": 10},
        stages=["door_knock", "initial_pitch", "close_attempt"],
        created_by_id=seed_org["manager_id"],
    )
    db.add_all([objection_scenario, closing_scenario])
    db.commit()
    db.refresh(objection_scenario)
    db.refresh(closing_scenario)

    historical_rows = [
        {
            "scenario_id": objection_scenario.id,
            "ended_at": datetime.now(timezone.utc) - timedelta(days=3),
            "emotion_start": "skeptical",
            "emotion_end": "annoyed",
            "scores": {
                "opening": 8.1,
                "pitch_delivery": 6.3,
                "objection_handling": 4.8,
                "closing_technique": 4.1,
                "professionalism": 7.5,
            },
            "objection_tags": ["price", "incumbent_provider"],
        },
        {
            "scenario_id": closing_scenario.id,
            "ended_at": datetime.now(timezone.utc) - timedelta(days=1),
            "emotion_start": "annoyed",
            "emotion_end": "skeptical",
            "scores": {
                "opening": 8.6,
                "pitch_delivery": 6.8,
                "objection_handling": 5.3,
                "closing_technique": 4.4,
                "professionalism": 7.9,
            },
            "objection_tags": ["timing", "spouse"],
        },
    ]

    for index, row in enumerate(historical_rows, start=1):
        assignment = Assignment(
            scenario_id=row["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "historical"},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        started_at = row["ended_at"] - timedelta(minutes=8)
        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=row["scenario_id"],
            started_at=started_at,
            ended_at=row["ended_at"],
            duration_seconds=480,
            status=SessionStatus.GRADED,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        db.add_all(
            [
                SessionEvent(
                    session_id=session.id,
                    event_id=f"adaptive-{index}-connected",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=1,
                    event_ts=started_at,
                    payload={"state": "connected", "emotion": row["emotion_start"], "stage": "door_knock"},
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id=f"adaptive-{index}-commit",
                    event_type="server.turn.committed",
                    direction=EventDirection.SERVER,
                    sequence=2,
                    event_ts=row["ended_at"],
                    payload={
                        "stage": "close_attempt",
                        "emotion": row["emotion_end"],
                        "micro_behavior": {
                            "tone": "guarded",
                            "sentence_length": "medium",
                            "behaviors": ["tone_shift"],
                            "interruption_type": None,
                            "pause_profile": {"opening_pause_ms": 220, "total_pause_ms": 420, "longest_pause_ms": 220},
                            "realism_score": 7.3,
                        },
                    },
                ),
                SessionTurn(
                    session_id=session.id,
                    turn_index=1,
                    speaker=TurnSpeaker.REP,
                    stage="objection_handling",
                    text="We can lower your price and help with service coverage.",
                    started_at=started_at + timedelta(minutes=1),
                    ended_at=started_at + timedelta(minutes=1),
                    objection_tags=row["objection_tags"],
                ),
                SessionTurn(
                    session_id=session.id,
                    turn_index=2,
                    speaker=TurnSpeaker.AI,
                    stage="close_attempt",
                    text="I'm not sure this is worth switching for.",
                    started_at=started_at + timedelta(minutes=2),
                    ended_at=started_at + timedelta(minutes=2),
                    objection_tags=[],
                ),
                Scorecard(
                    session_id=session.id,
                    overall_score=round(sum(row["scores"].values()) / len(row["scores"]), 2),
                    category_scores=row["scores"],
                    highlights=[{"type": "improve", "note": "Needs more confident close."}],
                    ai_summary="Adaptive test scorecard.",
                    evidence_turn_ids=[],
                    weakness_tags=["objection_handling", "closing_technique"],
                ),
            ]
        )
        db.commit()

    db.close()
    return {
        "objection_scenario_id": objection_scenario.id,
        "closing_scenario_id": closing_scenario.id,
    }


def test_manager_can_fetch_adaptive_plan(client, seed_org):
    scenario_ids = _seed_adaptive_history(seed_org)

    response = client.get(
        f"/manager/reps/{seed_org['rep_id']}/adaptive-plan",
        params={"manager_id": seed_org["manager_id"]},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["rep_id"] == seed_org["rep_id"]
    assert body["session_count"] == 2
    assert body["recommended_difficulty"] >= 1
    assert set(body["weakest_skills"]).intersection({"objection_handling", "closing"})
    assert len(body["skill_profile"]) == 5
    assert body["recommended_scenarios"]
    assert any(
        recommendation["scenario_id"] in {scenario_ids["objection_scenario_id"], scenario_ids["closing_scenario_id"]}
        for recommendation in body["recommended_scenarios"]
    )


def test_manager_can_create_adaptive_assignment(client, seed_org):
    _seed_adaptive_history(seed_org)

    response = client.post(
        f"/manager/reps/{seed_org['rep_id']}/adaptive-assignment",
        json={"assigned_by": seed_org["manager_id"], "retry_policy": {"max_attempts": 3}},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["assignment"]["rep_id"] == seed_org["rep_id"]
    assert body["selected_scenario"]["scenario_id"] == body["assignment"]["scenario_id"]
    adaptive_metadata = body["assignment"]["retry_policy"]["adaptive_training"]
    assert adaptive_metadata["source"] == "adaptive_training_engine"
    assert adaptive_metadata["selected_scenario_id"] == body["selected_scenario"]["scenario_id"]
    assert adaptive_metadata["recommended_difficulty"] == body["adaptive_plan"]["recommended_difficulty"]


def test_manager_can_force_specific_adaptive_scenario(client, seed_org):
    scenario_ids = _seed_adaptive_history(seed_org)

    response = client.post(
        f"/manager/reps/{seed_org['rep_id']}/adaptive-assignment",
        json={
            "assigned_by": seed_org["manager_id"],
            "scenario_id": scenario_ids["closing_scenario_id"],
            "retry_policy": {"max_attempts": 1},
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["selected_scenario"]["scenario_id"] == scenario_ids["closing_scenario_id"]
    assert body["assignment"]["scenario_id"] == scenario_ids["closing_scenario_id"]
