from __future__ import annotations

from app.schemas.scorecard import CategoryScoreV2, StructuredScorecardPayloadV2


def test_category_score_v2_schema_accepts_expected_fields():
    payload = StructuredScorecardPayloadV2(
        category_scores={
            "opening": CategoryScoreV2(
                score=7.4,
                confidence=0.81,
                rationale_summary="Solid opener",
                rationale_detail="The rep opened cleanly and earned enough attention to continue the conversation.",
                evidence_turn_ids=["turn-1"],
                behavioral_signals=["confident_intro", "polite_tone"],
                improvement_target="Shorten setup",
            )
        },
        overall_score=7.4,
        highlights=[
            {"type": "strong", "note": "You opened with confidence.", "turn_id": "turn-1"},
            {"type": "improve", "note": "Move to value slightly faster.", "turn_id": "turn-1"},
        ],
        ai_summary="You opened well and created enough trust to stay in the conversation.",
        weakness_tags=["closing_technique"],
        evidence_quality="moderate",
        session_complexity=3,
    )

    opening = payload.category_scores["opening"]
    assert opening.score == 7.4
    assert opening.confidence == 0.81
    assert opening.rationale_summary == "Solid opener"
    assert opening.rationale_detail
    assert opening.evidence_turn_ids == ["turn-1"]
    assert opening.behavioral_signals == ["confident_intro", "polite_tone"]
    assert opening.improvement_target == "Shorten setup"


def test_category_score_v2_schema_exposes_expected_json_shape():
    schema = StructuredScorecardPayloadV2.model_json_schema()
    category_schema = schema["$defs"]["CategoryScoreV2"]
    properties = category_schema["properties"]

    assert "confidence" in properties
    assert "rationale_summary" in properties
    assert "rationale_detail" in properties
    assert "evidence_turn_ids" in properties
    assert "behavioral_signals" in properties
    assert "improvement_target" in properties
