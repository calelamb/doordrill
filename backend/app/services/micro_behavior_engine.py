from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

HESITATION_VARIANTS = {
    "neutral": (
        "Uh...",
        "Well...",
        "Hmm...",
        "I mean...",
        "Let me think...",
        "Okay...",
        "So...",
        "Right...",
    ),
    "skeptical": (
        "Uh...",
        "Well...",
        "I mean...",
        "Hm.",
        "Look...",
        "I don't know...",
        "Right, so...",
        "Okay but...",
    ),
    "curious": (
        "Hmm...",
        "Well...",
        "So...",
        "Interesting...",
        "Oh, okay...",
        "Wait, so...",
        "Huh...",
        "Tell me...",
    ),
    "interested": (
        "Okay...",
        "Well...",
        "So...",
        "Right...",
        "Got it...",
        "Alright...",
        "Yeah...",
        "And...",
    ),
    "annoyed": (
        "Look...",
        "Okay so...",
        "I mean...",
        "Yeah, I heard you...",
        "Alright...",
        "Okay, but...",
    ),
    "hostile": (
        "No...",
        "Look...",
        "Yeah, no...",
        "Okay, stop...",
        "Listen...",
        "Absolutely not...",
    ),
    "considering": (
        "Okay...",
        "Well...",
        "I mean...",
        "Right...",
        "Let me think...",
        "So...",
    ),
}
FILLER_VARIANTS = {
    "neutral": ("you know", "I mean", "like", "sort of", "kind of"),
    "skeptical": ("I mean", "you know", "honestly", "look", "kind of"),
    "curious": ("you know", "like", "actually", "I guess", "kind of"),
    "interested": ("I mean", "you know", "right", "exactly", "yeah"),
    "annoyed": ("look", "I mean", "honestly", "seriously", "okay"),
    "hostile": ("look", "honestly", "seriously", "frankly", "listen"),
    "considering": ("I mean", "you know", "kind of", "I guess", "actually"),
}
INTERRUPTION_VARIANTS = {
    "annoyed": (
        "Hold on,",
        "Wait,",
        "Look,",
        "Okay, stop.",
        "Let me jump in here.",
        "Actually,",
        "No, hang on.",
    ),
    "hostile": (
        "No, hold on,",
        "Sorry, let me stop you there,",
        "Wait a second,",
        "No, stop.",
        "I'm going to cut you off,",
        "Okay, I've heard enough.",
        "That's not it, listen,",
    ),
}
TRAILING_OFF_VARIANTS = {
    "skeptical": (
        "I just don't know...",
        "It's just that...",
        "I'd have to think about it...",
        "I mean, maybe...",
    ),
    "considering": (
        "I guess the thing is...",
        "It's just...",
        "I'm not sure, it's...",
        "Maybe, I just...",
    ),
}
TONE_BY_TRANSITION = {
    ("neutral", "skeptical"): "guarded",
    ("skeptical", "annoyed"): "sharp",
    ("interested", "curious"): "exploratory",
}
DEFAULT_TONE_BY_EMOTION = {
    "neutral": "measured",
    "skeptical": "guarded",
    "annoyed": "sharp",
    "hostile": "confrontational",
    "curious": "exploratory",
    "interested": "warm",
    "considering": "guarded",
}
SENTENCE_LENGTH_BY_EMOTION = {
    "hostile": "short",
    "annoyed": "short",
    "skeptical": "medium",
    "neutral": "medium",
    "curious": "long",
    "interested": "long",
    "considering": "medium",
}
PAUSE_BEFORE_OFFSET_BY_EMOTION = {
    "hostile": -80,
    "annoyed": -40,
    "neutral": 0,
    "skeptical": 60,
    "curious": 120,
    "interested": 160,
    "considering": 80,
}
RECENT_VARIANT_WINDOW = 4
SEMANTIC_KEYWORDS_BY_OBJECTION = {
    "price": ("price", "cost", "expensive", "budget", "monthly"),
    "price_per_month": ("monthly", "payment", "month", "rate"),
    "trust": ("trust", "licensed", "insured", "reviews", "guarantee"),
    "timing": ("busy", "time", "later", "schedule"),
    "not_right_now": ("later", "not now", "another time"),
    "spouse": ("spouse", "partner", "wife", "husband"),
    "incumbent_provider": ("already", "provider", "Orkin", "service"),
    "safety_environment": ("safe", "kids", "pets", "chemical", "environment"),
}


@dataclass
class MicroBehaviorSessionState:
    recent_fillers: list[str] = field(default_factory=list)
    recent_hesitations: list[str] = field(default_factory=list)
    recent_interruptions: list[str] = field(default_factory=list)
    recent_trailing_offs: list[str] = field(default_factory=list)
    recent_tones: list[str] = field(default_factory=list)
    persona: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0


@dataclass
class MicroBehaviorSegment:
    text: str
    pause_before_ms: int
    pause_after_ms: int
    tone: str
    behaviors: list[str]
    sentence_length: str
    segment_index: int
    segment_count: int
    interruption_type: str | None
    allow_barge_in: bool


@dataclass
class MicroBehaviorPlan:
    transformed_text: str
    tone: str
    sentence_length: str
    interruption_type: str | None
    behaviors: list[str]
    pause_profile: dict[str, int]
    realism_score: float
    segments: list[MicroBehaviorSegment]


class ConversationalMicroBehaviorEngine:
    """Computes TTS metadata (tone, pauses, segments) from LLM output. Does not modify text."""

    def __init__(self) -> None:
        self._states: dict[str, MicroBehaviorSessionState] = {}

    def initialize_session(self, session_id: str, *, persona: dict[str, Any] | None = None) -> MicroBehaviorSessionState:
        state = self._states.get(session_id)
        if state is None:
            state = MicroBehaviorSessionState(persona=persona or {})
            self._states[session_id] = state
        return state

    def end_session(self, session_id: str) -> None:
        self._states.pop(session_id, None)

    def apply_to_response(
        self,
        *,
        session_id: str,
        raw_text: str,
        emotion_before: str,
        emotion_after: str,
        behavioral_signals: list[str],
        active_objections: list[str],
    ) -> MicroBehaviorPlan:
        state = self.initialize_session(session_id)
        state.turn_count += 1

        base_text = self._normalize_text(raw_text)
        tone = self._determine_tone(emotion_before, emotion_after, behavioral_signals)
        sentence_length = self._determine_sentence_length(emotion_after, behavioral_signals, base_text)

        interruption_type: str | None = None
        if self._should_interrupt(emotion_after, behavioral_signals):
            interruption_type = "homeowner_cuts_off_rep"

        behaviors = self._derive_behaviors(
            emotion_before=emotion_before,
            emotion_after=emotion_after,
            behavioral_signals=behavioral_signals,
            active_objections=active_objections,
            interruption_type=interruption_type,
            sentence_length=sentence_length,
            tone=tone,
        )
        segments = self._segment_text(
            base_text,
            tone=tone,
            behaviors=behaviors,
            sentence_length=sentence_length,
            emotion_after=emotion_after,
        )
        pause_profile = self._summarize_pauses(segments)
        realism_score = self._score_realism(
            behaviors=behaviors,
            tone=tone,
            sentence_length=sentence_length,
            pause_profile=pause_profile,
            interruption_type=interruption_type,
            emotion_after=emotion_after,
        )

        self._remember(state.recent_tones, tone)

        return MicroBehaviorPlan(
            transformed_text=base_text,
            tone=tone,
            sentence_length=sentence_length,
            interruption_type=interruption_type,
            behaviors=behaviors,
            pause_profile=pause_profile,
            realism_score=realism_score,
            segments=segments,
        )

    def _normalize_text(self, raw_text: str) -> str:
        compact = re.sub(r"\s+", " ", raw_text).strip()
        if not compact:
            return "..."
        return compact

    def _determine_tone(self, emotion_before: str, emotion_after: str, behavioral_signals: list[str]) -> str:
        if (emotion_before, emotion_after) in TONE_BY_TRANSITION:
            return TONE_BY_TRANSITION[(emotion_before, emotion_after)]
        if "ignores_objection" in behavioral_signals and emotion_after in {"annoyed", "hostile"}:
            return "cutting"
        if "acknowledges_concern" in behavioral_signals and emotion_after in {"curious", "interested"}:
            return "warming"
        return DEFAULT_TONE_BY_EMOTION.get(emotion_after, "measured")

    def _determine_sentence_length(self, emotion_after: str, behavioral_signals: list[str], raw_text: str) -> str:
        preferred = SENTENCE_LENGTH_BY_EMOTION.get(emotion_after, "medium")
        if "pushes_close" in behavioral_signals and emotion_after in {"annoyed", "hostile"}:
            return "short"
        if len(raw_text.split()) <= 7:
            return "short"
        if len(raw_text.split()) >= 18 and preferred == "medium":
            return "long"
        return preferred

    def _apply_sentence_length(self, text: str, sentence_length: str, *, active_objections: list[str] | None = None) -> str:
        # No-op: sentence length is metadata only; text is not modified.
        return text

    def _best_semantic_sentence(self, sentences: list[str], *, active_objections: list[str]) -> str | None:
        if not sentences:
            return None
        scored = sorted(
            sentences,
            key=lambda sentence: (
                self._semantic_sentence_score(sentence, active_objections=active_objections),
                1 if "?" in sentence else 0,
            ),
            reverse=True,
        )
        best = scored[0]
        return best if self._semantic_sentence_score(best, active_objections=active_objections) > 0 else None

    def _select_semantic_sentences(
        self,
        sentences: list[str],
        *,
        limit: int,
        active_objections: list[str],
    ) -> list[str]:
        if len(sentences) <= limit:
            return sentences
        selected = [sentences[0]]
        while len(selected) < limit:
            remaining = [sentence for sentence in sentences if sentence not in selected]
            if not remaining:
                break
            next_sentence = max(
                remaining,
                key=lambda sentence: (
                    self._semantic_sentence_score(sentence, active_objections=active_objections),
                    1 if "?" in sentence else 0,
                ),
            )
            selected.append(next_sentence)
        return [sentence for sentence in sentences if sentence in selected][:limit]

    def _semantic_sentence_score(self, sentence: str, *, active_objections: list[str]) -> int:
        lowered = sentence.lower()
        score = 0
        for objection in active_objections:
            for keyword in SEMANTIC_KEYWORDS_BY_OBJECTION.get(objection, (objection.replace("_", " "),)):
                if keyword.lower() in lowered:
                    score += 2
        if "?" in sentence:
            score += 1
        return score

    def _should_interrupt(self, emotion_after: str, behavioral_signals: list[str]) -> bool:
        if emotion_after not in {"annoyed", "hostile"}:
            return False
        return any(signal in {"ignores_objection", "pushes_close", "dismisses_concern"} for signal in behavioral_signals)

    def _should_hesitate(self, emotion_after: str, behavioral_signals: list[str], text: str) -> bool:
        if emotion_after in {"hostile", "annoyed", "curious"}:
            return False
        if "neutral_delivery" in behavioral_signals:
            return emotion_after in {"neutral", "skeptical", "considering"}
        return len(text.split()) > 6 and emotion_after in {"neutral", "skeptical", "considering"}

    def _should_use_filler(self, emotion_after: str, behavioral_signals: list[str], text: str) -> bool:
        if emotion_after in {"hostile", "annoyed"}:
            return False
        if len(text.split()) < 5:
            return False
        return "explains_value" in behavioral_signals or emotion_after in {"neutral", "curious"}

    def _should_trail_off(
        self,
        *,
        session_id: str,
        emotion_after: str,
        sentence_length: str,
        turn_count: int,
        interruption_type: str | None,
        filler_used: bool,
    ) -> bool:
        if (
            sentence_length != "medium"
            or emotion_after not in TRAILING_OFF_VARIANTS
            or interruption_type is not None
            or filler_used
        ):
            return False
        digest = hashlib.sha256(f"{session_id}:trailing:{emotion_after}:{turn_count}".encode("utf-8")).hexdigest()
        return (int(digest[:8], 16) % 10) < 3

    def _insert_filler(self, text: str, filler: str) -> str:
        # No-op: filler injection is no longer performed; the LLM owns all language choices.
        return text

    def _apply_trailing_off(self, text: str, trailing_variant: str) -> str:
        sentences = self._split_sentences(text)
        if not sentences:
            return trailing_variant
        if len(sentences) == 1:
            base = sentences[0].rstrip(".!? ")
            return f"{base}. {trailing_variant}".strip()
        sentences[-1] = trailing_variant
        return " ".join(sentences).strip()

    def _derive_behaviors(
        self,
        *,
        emotion_before: str,
        emotion_after: str,
        behavioral_signals: list[str],
        active_objections: list[str],
        interruption_type: str | None,
        sentence_length: str,
        tone: str,
    ) -> list[str]:
        behaviors = ["tone_shift", f"tone:{tone}", f"sentence_length:{sentence_length}"]
        if emotion_before != emotion_after:
            behaviors.append(f"emotion_transition:{emotion_before}->{emotion_after}")
        if active_objections:
            behaviors.append("objection_aware")
        if interruption_type:
            behaviors.append(interruption_type)
        if tone in {"guarded", "sharp", "cutting"}:
            behaviors.append("tone_hardening")
        if tone in {"warming", "warm", "exploratory"}:
            behaviors.append("tone_softening")
        if emotion_after in {"neutral", "skeptical", "curious"}:
            behaviors.append("hesitation_mode")
        if emotion_after in {"neutral", "curious", "interested"}:
            behaviors.append("filler_mode")
        if emotion_after in TRAILING_OFF_VARIANTS and sentence_length == "medium":
            behaviors.append("trailing_off_available")
        return behaviors

    def _segment_text(
        self,
        text: str,
        *,
        tone: str,
        behaviors: list[str],
        sentence_length: str,
        emotion_after: str,
    ) -> list[MicroBehaviorSegment]:
        sentences = self._split_sentences(text)
        if not sentences:
            sentences = [text]
        if sentence_length == "short":
            sentences = [" ".join(sentences).strip()]
        segments: list[MicroBehaviorSegment] = []
        count = len(sentences)
        for index, sentence in enumerate(sentences):
            pause_before = self._pause_before_ms(
                index=index,
                tone=tone,
                sentence_length=sentence_length,
                sentence=sentence,
                emotion_after=emotion_after,
            )
            pause_after = self._pause_after_ms(index=index, count=count, tone=tone)
            segments.append(
                MicroBehaviorSegment(
                    text=sentence,
                    pause_before_ms=pause_before,
                    pause_after_ms=pause_after,
                    tone=tone,
                    behaviors=list(behaviors),
                    sentence_length=sentence_length,
                    segment_index=index,
                    segment_count=count,
                    interruption_type="homeowner_cuts_off_rep" if index == 0 and "homeowner_cuts_off_rep" in behaviors else None,
                    allow_barge_in=count > 1 or sentence_length == "long",
                )
            )
        return segments

    def _pause_before_ms(
        self,
        *,
        index: int,
        tone: str,
        sentence_length: str,
        sentence: str,
        emotion_after: str,
    ) -> int:
        if index == 0 and tone in {"exploratory", "guarded", "measured"}:
            base_pause = 320
        elif index == 0 and tone in {"sharp", "cutting", "confrontational"}:
            base_pause = 80
        elif sentence.startswith(tuple({variant for values in HESITATION_VARIANTS.values() for variant in values})):
            base_pause = 420
        elif sentence_length == "long":
            base_pause = 260 if index > 0 else 360
        else:
            base_pause = 180 if index > 0 else 140
        return max(40, base_pause + PAUSE_BEFORE_OFFSET_BY_EMOTION.get(emotion_after, 0))

    def _pause_after_ms(self, *, index: int, count: int, tone: str) -> int:
        if index == count - 1:
            return 180
        if tone in {"exploratory", "warming"}:
            return 300
        return 220

    def _summarize_pauses(self, segments: list[MicroBehaviorSegment]) -> dict[str, int]:
        if not segments:
            return {"opening_pause_ms": 0, "total_pause_ms": 0, "longest_pause_ms": 0}
        pauses = [segment.pause_before_ms + segment.pause_after_ms for segment in segments]
        return {
            "opening_pause_ms": segments[0].pause_before_ms,
            "total_pause_ms": sum(pauses),
            "longest_pause_ms": max(max(segment.pause_before_ms, segment.pause_after_ms) for segment in segments),
        }

    def _score_realism(
        self,
        *,
        behaviors: list[str],
        tone: str,
        sentence_length: str,
        pause_profile: dict[str, int],
        interruption_type: str | None,
        emotion_after: str,
    ) -> float:
        score = 5.0
        if "hesitation_mode" in behaviors:
            score += 0.8
        if "filler_mode" in behaviors:
            score += 0.7
        if sentence_length in {"short", "long"}:
            score += 0.6
        if tone in {"guarded", "sharp", "exploratory", "warming", "cutting"}:
            score += 0.8
        if pause_profile["opening_pause_ms"] >= 300:
            score += 0.7
        if interruption_type:
            score += 0.9
        if emotion_after in {"annoyed", "hostile"} and tone in {"sharp", "cutting", "confrontational"}:
            score += 0.7
        return round(max(1.0, min(10.0, score)), 1)

    def _split_sentences(self, text: str) -> list[str]:
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]

    def _pick_variant(self, session_id: str, namespace: str, options: tuple[str, ...], recent: list[str]) -> str:
        candidates = [option for option in options if option not in recent[-RECENT_VARIANT_WINDOW:]] or list(options)
        digest = hashlib.sha256(f"{session_id}:{namespace}:{len(recent)}".encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(candidates)
        return candidates[index]

    def _remember(self, bucket: list[str], value: str) -> None:
        bucket.append(value)
        if len(bucket) > RECENT_VARIANT_WINDOW * 2:
            del bucket[0]
