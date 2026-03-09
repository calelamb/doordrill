from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.types import AssignmentStatus, SessionStatus, TurnSpeaker


def _rep_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}


def _create_session(
    seed_org: dict[str, str],
    *,
    started_at: datetime,
    turns: list[dict] | None = None,
) -> dict[str, list[str] | str]:
    db = SessionLocal()

    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "rep_api_enrichment_test"},
    )
    db.add(assignment)
    db.flush()

    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=seed_org["rep_id"],
        scenario_id=seed_org["scenario_id"],
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        duration_seconds=300,
        status=SessionStatus.GRADED,
    )
    db.add(session)
    db.flush()

    turn_ids: list[str] = []
    for index, turn in enumerate(turns or [], start=1):
        turn_started_at = turn.get("started_at", started_at + timedelta(seconds=index * 10))
        turn_row = SessionTurn(
            session_id=session.id,
            turn_index=int(turn.get("turn_index", index)),
            speaker=turn.get("speaker", TurnSpeaker.REP),
            stage=turn.get("stage", "objection_handling"),
            text=turn.get("text", ""),
            started_at=turn_started_at,
            ended_at=turn.get("ended_at", turn_started_at + timedelta(seconds=5)),
            objection_tags=list(turn.get("objection_tags", [])),
            emotion_before=turn.get("emotion_before"),
            emotion_after=turn.get("emotion_after"),
        )
        db.add(turn_row)
        db.flush()
        turn_ids.append(turn_row.id)

    db.commit()
    session_id = session.id
    db.close()
    return {"session_id": session_id, "turn_ids": turn_ids}


def _add_scorecard(
    session_id: str,
    *,
    overall_score: float,
    category_scores: dict,
    scorecard_schema_version: str = "v1",
    evidence_turn_ids: list[str] | None = None,
    weakness_tags: list[str] | None = None,
) -> None:
    db = SessionLocal()
    db.add(
        Scorecard(
            session_id=session_id,
            overall_score=overall_score,
            scorecard_schema_version=scorecard_schema_version,
            category_scores=category_scores,
            highlights=[
                {"type": "strong", "note": "Strongest moment", "turn_id": (evidence_turn_ids or [None])[0]},
                {"type": "improve", "note": "Primary area to improve", "turn_id": (evidence_turn_ids or [None])[-1]},
            ],
            ai_summary="Rep API enrichment test scorecard.",
            evidence_turn_ids=list(evidence_turn_ids or []),
            weakness_tags=list(weakness_tags or []),
        )
    )
    db.commit()
    db.close()


def _seed_scored_session(
    seed_org: dict[str, str],
    *,
    started_at: datetime,
    overall_score: float,
    category_scores: dict,
    scorecard_schema_version: str = "v1",
) -> str:
    session = _create_session(seed_org, started_at=started_at)
    _add_scorecard(
        str(session["session_id"]),
        overall_score=overall_score,
        category_scores=category_scores,
        scorecard_schema_version=scorecard_schema_version,
    )
    return str(session["session_id"])


def test_session_detail_includes_transcript_when_turns_exist(client, seed_org):
    started_at = datetime.now(timezone.utc) - timedelta(days=1)
    session = _create_session(
        seed_org,
        started_at=started_at,
        turns=[
            {
                "turn_index": 2,
                "speaker": TurnSpeaker.AI,
                "stage": "objection_handling",
                "text": "We already use another company.",
                "objection_tags": ["incumbent_provider"],
                "emotion_before": "skeptical",
            },
            {
                "turn_index": 1,
                "speaker": TurnSpeaker.REP,
                "stage": "opening",
                "text": "Quick question before I go, are bugs getting worse lately?",
                "emotion_after": "neutral",
            },
        ],
    )

    response = client.get(
        f"/rep/sessions/{session['session_id']}",
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["turn_index"] for item in body["transcript"]] == [1, 2]
    assert body["transcript"][0]["rep_text"].startswith("Quick question")
    assert body["transcript"][0]["ai_text"] == ""
    assert body["transcript"][0]["emotion"] == "neutral"
    assert body["transcript"][1]["rep_text"] == ""
    assert body["transcript"][1]["ai_text"] == "We already use another company."
    assert body["transcript"][1]["objection_tags"] == ["incumbent_provider"]


def test_session_detail_transcript_empty_when_no_turns(client, seed_org):
    session = _create_session(
        seed_org,
        started_at=datetime.now(timezone.utc) - timedelta(hours=6),
        turns=[],
    )

    response = client.get(
        f"/rep/sessions/{session['session_id']}",
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    assert response.json()["transcript"] == []


def test_session_detail_includes_improvement_targets_for_v2_scorecard(client, seed_org):
    session = _create_session(
        seed_org,
        started_at=datetime.now(timezone.utc) - timedelta(hours=3),
        turns=[
            {
                "turn_index": 1,
                "speaker": TurnSpeaker.REP,
                "stage": "opening",
                "text": "I can show you how we lower your cost without lowering coverage.",
            }
        ],
    )
    turn_id = str(session["turn_ids"][0])

    _add_scorecard(
        str(session["session_id"]),
        overall_score=5.9,
        scorecard_schema_version="v2",
        evidence_turn_ids=[turn_id],
        weakness_tags=["pitch_delivery", "objection_handling", "opening"],
        category_scores={
            "opening": {
                "score": 6.1,
                "confidence": 0.82,
                "rationale_summary": "Decent opener",
                "rationale_detail": "The rep earned enough attention to continue but took too long to reach value.",
                "evidence_turn_ids": [turn_id],
                "behavioral_signals": ["polite_tone"],
                "improvement_target": "Shorten the setup by one sentence",
            },
            "pitch_delivery": {
                "score": 4.2,
                "confidence": 0.88,
                "rationale_summary": "Value felt generic",
                "rationale_detail": "The rep described the offer broadly instead of anchoring it to one concrete outcome.",
                "evidence_turn_ids": [turn_id],
                "behavioral_signals": ["generic_claim"],
                "improvement_target": "Lead with one proof point",
            },
            "objection_handling": {
                "score": 5.0,
                "confidence": 0.79,
                "rationale_summary": "Pushback answer was soft",
                "rationale_detail": "The rep acknowledged concern but did not reframe the price objection with control.",
                "evidence_turn_ids": [turn_id],
                "behavioral_signals": ["hesitation"],
                "improvement_target": "Answer the price objection directly",
            },
            "closing_technique": {
                "score": 6.8,
                "confidence": 0.77,
                "rationale_summary": "Close was polite",
                "rationale_detail": "The rep asked softly for the next step and left room for the homeowner to disengage.",
                "evidence_turn_ids": [turn_id],
                "behavioral_signals": ["soft_ask"],
                "improvement_target": "Use a direct next-step ask",
            },
            "professionalism": {
                "score": 7.4,
                "confidence": 0.9,
                "rationale_summary": "Calm and respectful",
                "rationale_detail": "Tone stayed composed throughout the exchange.",
                "evidence_turn_ids": [turn_id],
                "behavioral_signals": ["steady_tone"],
                "improvement_target": None,
            },
        },
    )

    response = client.get(
        f"/rep/sessions/{session['session_id']}",
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scorecard"]["scorecard_schema_version"] == "v2"
    assert body["scorecard"]["category_scores"]["pitch_delivery"]["rationale_summary"] == "Value felt generic"
    assert body["scorecard"]["category_scores"]["pitch_delivery"]["behavioral_signals"] == ["generic_claim"]
    assert body["improvement_targets"] == [
        {
            "category": "pitch_delivery",
            "label": "Pitch",
            "target": "Lead with one proof point",
            "score": 4.2,
        },
        {
            "category": "objection_handling",
            "label": "Objection Handling",
            "target": "Answer the price objection directly",
            "score": 5.0,
        },
        {
            "category": "opening",
            "label": "Opening",
            "target": "Shorten the setup by one sentence",
            "score": 6.1,
        },
    ]


def test_session_detail_improvement_targets_empty_for_v1_scorecard(client, seed_org):
    session = _create_session(
        seed_org,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        turns=[],
    )
    _add_scorecard(
        str(session["session_id"]),
        overall_score=6.7,
        scorecard_schema_version="v1",
        category_scores={
            "opening": {"score": 6.1, "evidence_turn_ids": []},
            "pitch_delivery": {"score": 6.5, "evidence_turn_ids": []},
            "objection_handling": {"score": 6.2, "evidence_turn_ids": []},
        },
    )

    response = client.get(
        f"/rep/sessions/{session['session_id']}",
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scorecard"]["scorecard_schema_version"] == "v1"
    assert body["improvement_targets"] == []


def test_progress_trend_returns_correct_session_count(client, seed_org):
    base_time = datetime.now(timezone.utc) - timedelta(days=5)
    for offset, score in enumerate([5.4, 5.9, 6.4, 6.8, 7.2]):
        _seed_scored_session(
            seed_org,
            started_at=base_time + timedelta(days=offset),
            overall_score=score,
            category_scores={
                "opening": score,
                "pitch_delivery": round(score - 0.2, 2),
                "objection_handling": round(score - 0.4, 2),
                "closing_technique": round(score - 0.3, 2),
                "professionalism": round(score + 0.1, 2),
            },
        )

    response = client.get(
        "/rep/progress/trend",
        params={"rep_id": seed_org["rep_id"], "sessions": 3},
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["sessions"]) == 3
    assert [item["overall_score"] for item in body["sessions"]] == [6.4, 6.8, 7.2]
    assert set(body["category_averages"]) >= {"opening", "pitch_delivery", "objection_handling"}


def test_progress_trend_overall_trend_improving(client, seed_org):
    base_time = datetime.now(timezone.utc) - timedelta(days=4)
    for offset, score in enumerate([5.0, 5.5, 6.1, 6.7]):
        _seed_scored_session(
            seed_org,
            started_at=base_time + timedelta(days=offset),
            overall_score=score,
            category_scores={
                "opening": score,
                "pitch_delivery": round(score - 0.1, 2),
                "objection_handling": round(score - 0.2, 2),
                "closing_technique": round(score - 0.3, 2),
                "professionalism": round(score + 0.2, 2),
            },
        )

    response = client.get(
        "/rep/progress/trend",
        params={"rep_id": seed_org["rep_id"], "sessions": 4},
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    assert response.json()["overall_trend"] == "improving"


def test_rep_plan_returns_defaults_on_no_history(client, seed_org):
    response = client.get(
        "/rep/plan",
        params={"rep_id": seed_org["rep_id"]},
        headers=_rep_headers(seed_org),
    )

    assert response.status_code == 200
    assert response.json() == {
        "focus_skills": [],
        "recommended_difficulty": 1,
        "readiness_trajectory": {},
        "next_scenario_suggestion": None,
    }
