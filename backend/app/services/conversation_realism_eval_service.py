from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.session import SessionTurn
from app.models.training import ConversationQualitySignal
from app.models.types import TurnSpeaker


_BOOKING_PHRASES = (
    "sounds good",
    "let's do it",
    "let's go ahead",
    "sign me up",
    "go ahead and schedule",
    "that works for me",
)
_PUSHBACK_PHRASES = (
    "not right now",
    "i need more",
    "i'm not ready",
    "i still need",
    "i already have",
    "i'm not looking",
    "i need to talk to",
)


def _normalize_text(text: str | None) -> str:
    return " ".join(str(text or "").lower().split()).strip()


def _word_set(text: str | None) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", _normalize_text(text))
        if len(token) >= 3
    }


@dataclass
class ConversationRealismEvalResult:
    overall_score: float
    directness_score: float
    objection_carryover_score: float
    emotional_consistency_score: float
    closing_resistance_score: float
    interruption_recovery_score: float
    transcript_entity_score: float
    repetition_rate: float
    contradiction_rate: float
    failure_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    turn_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "directness_score": self.directness_score,
            "objection_carryover_score": self.objection_carryover_score,
            "emotional_consistency_score": self.emotional_consistency_score,
            "closing_resistance_score": self.closing_resistance_score,
            "interruption_recovery_score": self.interruption_recovery_score,
            "transcript_entity_score": self.transcript_entity_score,
            "repetition_rate": self.repetition_rate,
            "contradiction_rate": self.contradiction_rate,
            "failure_labels": list(self.failure_labels),
            "notes": list(self.notes),
            "turn_count": self.turn_count,
        }


class ConversationRealismEvalService:
    def evaluate_session(
        self,
        *,
        turns: list[SessionTurn],
        committed_payloads: list[dict[str, Any]] | None = None,
        quality_signal: ConversationQualitySignal | None = None,
    ) -> ConversationRealismEvalResult:
        committed_by_ai_turn_id = {
            str(payload.get("ai_turn_id")): dict(payload)
            for payload in (committed_payloads or [])
            if payload.get("ai_turn_id")
        }
        ai_turns = [turn for turn in turns if turn.speaker == TurnSpeaker.AI]
        rep_turns = [turn for turn in turns if turn.speaker == TurnSpeaker.REP]
        rep_by_index = {turn.turn_index: turn for turn in rep_turns}

        if not ai_turns:
            return ConversationRealismEvalResult(
                overall_score=0.0,
                directness_score=0.0,
                objection_carryover_score=0.0,
                emotional_consistency_score=0.0,
                closing_resistance_score=0.0,
                interruption_recovery_score=0.0,
                transcript_entity_score=0.0,
                repetition_rate=0.0,
                contradiction_rate=0.0,
                failure_labels=["no_ai_turns"],
                notes=["No homeowner turns were available for realism evaluation."],
                turn_count=0,
            )

        directness_scores: list[float] = []
        carryover_scores: list[float] = []
        emotion_scores: list[float] = []
        close_scores: list[float] = []
        interruption_scores: list[float] = []
        transcript_scores: list[float] = []
        failure_labels: list[str] = []
        notes: list[str] = []
        repeated_turns = 0
        contradictory_turns = 0
        previous_ai_texts: list[str] = []

        for ai_turn in ai_turns:
            rep_turn = rep_by_index.get(ai_turn.turn_index - 1)
            commit_payload = committed_by_ai_turn_id.get(ai_turn.id, {})
            response_plan = self._coerce_dict(commit_payload.get("response_plan"))
            turn_analysis = self._coerce_dict(commit_payload.get("turn_analysis"))
            transcript_quality = self._coerce_dict(commit_payload.get("transcript_quality"))
            ai_text = ai_turn.text or ""
            rep_text = (
                rep_turn.normalized_transcript_text
                if rep_turn is not None and rep_turn.normalized_transcript_text
                else (rep_turn.text if rep_turn is not None else "")
            )

            directness = self._directness_score(
                rep_text=rep_text,
                ai_text=ai_text,
                response_plan=response_plan,
                turn_analysis=turn_analysis,
            )
            carryover = self._carryover_score(
                ai_text=ai_text,
                response_plan=response_plan,
                turn_analysis=turn_analysis,
            )
            emotion = self._emotion_score(
                ai_turn=ai_turn,
                ai_text=ai_text,
                response_plan=response_plan,
            )
            close = self._closing_score(
                ai_text=ai_text,
                response_plan=response_plan,
                rep_text=rep_text,
            )
            interruption = self._interruption_score(
                ai_text=ai_text,
                commit_payload=commit_payload,
            )
            transcript = self._transcript_score(
                rep_turn=rep_turn,
                transcript_quality=transcript_quality,
            )
            repeated = self._is_repetitive(ai_text, previous_ai_texts)
            contradictory = close <= 4.0

            if repeated:
                repeated_turns += 1
                failure_labels.append("repetition")
                notes.append(f"Turn {ai_turn.turn_index} repeated prior homeowner phrasing too closely.")
            if contradictory:
                contradictory_turns += 1
                failure_labels.append("over_softening")
                notes.append(f"Turn {ai_turn.turn_index} softened more than the response plan allowed.")
            if transcript <= 5.5:
                failure_labels.append("transcript_corruption")
            if carryover <= 5.0:
                failure_labels.append("missed_objection")

            directness_scores.append(directness)
            carryover_scores.append(carryover)
            emotion_scores.append(emotion)
            close_scores.append(close)
            interruption_scores.append(interruption)
            transcript_scores.append(transcript)
            previous_ai_texts.append(ai_text)

        repetition_rate = round(repeated_turns / len(ai_turns), 3)
        contradiction_rate = round(contradictory_turns / len(ai_turns), 3)
        overall = (
            (sum(directness_scores) / len(directness_scores)) * 0.22
            + (sum(carryover_scores) / len(carryover_scores)) * 0.22
            + (sum(emotion_scores) / len(emotion_scores)) * 0.16
            + (sum(close_scores) / len(close_scores)) * 0.18
            + (sum(interruption_scores) / len(interruption_scores)) * 0.08
            + (sum(transcript_scores) / len(transcript_scores)) * 0.14
        )
        overall -= repetition_rate * 2.0
        overall -= contradiction_rate * 2.0
        if quality_signal is not None and quality_signal.realism_rating is not None:
            manager_score = max(0.0, min(10.0, (float(quality_signal.realism_rating) / 5.0) * 10.0))
            overall = (overall * 0.8) + (manager_score * 0.2)

        return ConversationRealismEvalResult(
            overall_score=round(max(0.0, min(10.0, overall)), 2),
            directness_score=round(sum(directness_scores) / len(directness_scores), 2),
            objection_carryover_score=round(sum(carryover_scores) / len(carryover_scores), 2),
            emotional_consistency_score=round(sum(emotion_scores) / len(emotion_scores), 2),
            closing_resistance_score=round(sum(close_scores) / len(close_scores), 2),
            interruption_recovery_score=round(sum(interruption_scores) / len(interruption_scores), 2),
            transcript_entity_score=round(sum(transcript_scores) / len(transcript_scores), 2),
            repetition_rate=repetition_rate,
            contradiction_rate=contradiction_rate,
            failure_labels=self._dedupe(failure_labels),
            notes=notes[:8],
            turn_count=len(ai_turns),
        )

    def _directness_score(
        self,
        *,
        rep_text: str,
        ai_text: str,
        response_plan: dict[str, Any],
        turn_analysis: dict[str, Any],
    ) -> float:
        if not ai_text.strip():
            return 0.0
        if not (response_plan.get("must_answer") or turn_analysis.get("direct_response_required")):
            return 8.0
        ai_lower = _normalize_text(ai_text)
        semantic_anchors = [str(item).lower() for item in (response_plan.get("semantic_anchors") or [])]
        overlap = len(_word_set(rep_text) & _word_set(ai_text))
        if semantic_anchors and any(anchor in ai_lower for anchor in semantic_anchors):
            return 9.0
        if overlap >= 2:
            return 8.0
        if "?" in ai_text and overlap == 0:
            return 4.5
        return 6.0

    def _carryover_score(
        self,
        *,
        ai_text: str,
        response_plan: dict[str, Any],
        turn_analysis: dict[str, Any],
    ) -> float:
        ai_lower = _normalize_text(ai_text)
        objection = str(response_plan.get("allowed_new_objection") or turn_analysis.get("recommended_next_objection") or "").strip()
        semantic_anchors = [str(item).lower() for item in (response_plan.get("semantic_anchors") or [])]
        if not objection and not semantic_anchors:
            return 8.0
        anchor_hits = sum(1 for anchor in semantic_anchors if anchor and anchor in ai_lower)
        if objection and objection.replace("_", " ") in ai_lower:
            return 9.0
        if anchor_hits >= 1:
            return 8.0
        return 4.5

    def _emotion_score(
        self,
        *,
        ai_turn: SessionTurn,
        ai_text: str,
        response_plan: dict[str, Any],
    ) -> float:
        emotion = str(ai_turn.emotion_after or "").lower()
        text = _normalize_text(ai_text)
        word_count = len(text.split())
        stance = str(response_plan.get("stance") or "")
        if emotion in {"hostile", "annoyed"}:
            if word_count <= 12 or any(phrase in text for phrase in _PUSHBACK_PHRASES):
                return 8.5
            return 6.0
        if emotion in {"curious", "interested"}:
            if "?" in ai_text or "next step" in text:
                return 8.5
            return 6.5
        if stance == "firm_resistance" and word_count > 22:
            return 5.0
        return 7.5

    def _closing_score(
        self,
        *,
        ai_text: str,
        response_plan: dict[str, Any],
        rep_text: str,
    ) -> float:
        acceptability = str(response_plan.get("next_step_acceptability") or "info_only")
        text = _normalize_text(ai_text)
        accepted = any(phrase in text for phrase in _BOOKING_PHRASES)
        if acceptability in {"not_allowed", "info_only"}:
            if accepted:
                return 2.0
            if any(phrase in text for phrase in _PUSHBACK_PHRASES) or "?" in ai_text:
                return 9.0
            return 7.0
        if acceptability == "inspection_only":
            if accepted and "schedule" not in text:
                return 6.0
            if "quick look" in text or "estimate" in text or "inspection" in text:
                return 8.5
            return 7.0
        if "schedule" in text or accepted or ("next step" in rep_text.lower() and "what" in text):
            return 8.5
        return 6.5

    def _interruption_score(
        self,
        *,
        ai_text: str,
        commit_payload: dict[str, Any],
    ) -> float:
        interrupted = bool(commit_payload.get("interrupted"))
        if not interrupted:
            return 8.0
        if not ai_text.strip():
            return 8.5
        if len(ai_text.split()) <= 8:
            return 7.5
        return 5.0

    def _transcript_score(
        self,
        *,
        rep_turn: SessionTurn | None,
        transcript_quality: dict[str, Any],
    ) -> float:
        confidence = transcript_quality.get("confidence")
        if confidence is None and rep_turn is not None:
            confidence = rep_turn.transcript_confidence
        applied_terms = transcript_quality.get("applied_terms") or []
        if confidence is None:
            return 5.0
        base = max(0.0, min(10.0, float(confidence) * 10.0))
        return min(10.0, base + min(2.0, len(applied_terms) * 0.5))

    def _is_repetitive(self, ai_text: str, previous_ai_texts: list[str]) -> bool:
        if not previous_ai_texts:
            return False
        current_words = _word_set(ai_text)
        if not current_words:
            return False
        for prior in previous_ai_texts[-3:]:
            prior_words = _word_set(prior)
            if not prior_words:
                continue
            overlap = len(current_words & prior_words)
            union = len(current_words | prior_words)
            if union and (overlap / union) >= 0.72:
                return True
        return False

    def _coerce_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered
