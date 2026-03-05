from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ConversationState:
    stage: str = "door_knock"
    rep_turns: int = 0
    ai_turns: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RepTurnPlan:
    stage_before: str
    stage_after: str
    stage_changed: bool
    objection_tags: list[str]
    system_prompt: str


class ConversationOrchestrator:
    """State manager for scenario stage progression and prompt scaffolding."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    def get_state(self, session_id: str) -> ConversationState:
        if session_id not in self._states:
            self._states[session_id] = ConversationState()
        return self._states[session_id]

    def prepare_rep_turn(self, session_id: str, rep_text: str) -> RepTurnPlan:
        state = self.get_state(session_id)
        stage_before = state.stage
        stage_after = self._detect_stage(rep_text, state.stage)

        state.rep_turns += 1
        state.stage = stage_after
        state.last_updated = datetime.now(timezone.utc)

        tags = self._extract_objection_tags(rep_text)
        system_prompt = self._build_system_prompt(stage_after=stage_after)

        return RepTurnPlan(
            stage_before=stage_before,
            stage_after=stage_after,
            stage_changed=stage_before != stage_after,
            objection_tags=tags,
            system_prompt=system_prompt,
        )

    def mark_ai_turn(self, session_id: str) -> None:
        state = self.get_state(session_id)
        state.ai_turns += 1
        state.last_updated = datetime.now(timezone.utc)

    def _build_system_prompt(self, stage_after: str) -> str:
        return (
            "You are a homeowner in a door-to-door sales roleplay. "
            "Stay realistic, challenge weak claims, and keep responses concise. "
            f"Current stage: {stage_after}."
        )

    def _detect_stage(self, rep_text: str, current_stage: str) -> str:
        text = rep_text.lower()
        if current_stage == "door_knock" and any(w in text for w in ["name", "company", "hi", "hello"]):
            return "initial_pitch"
        if any(w in text for w in ["price", "already", "provider", "spouse", "think about"]):
            return "objection_handling"
        if any(w in text for w in ["sign", "close", "today", "schedule", "next step"]):
            return "close_attempt"
        return current_stage

    def _extract_objection_tags(self, rep_text: str) -> list[str]:
        text = rep_text.lower()
        tags: list[str] = []
        if "price" in text or "cost" in text:
            tags.append("price")
        if "spouse" in text or "husband" in text or "wife" in text or "partner" in text:
            tags.append("spouse")
        if "already" in text or "provider" in text or "using" in text:
            tags.append("incumbent_provider")
        if "busy" in text or "later" in text or "not now" in text:
            tags.append("timing")
        return tags
