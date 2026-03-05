from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ConversationState:
    stage: str = "door_knock"
    rep_turns: int = 0
    ai_turns: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationOrchestrator:
    """Stateful session orchestrator with provider-agnostic streaming hooks."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    def get_state(self, session_id: str) -> ConversationState:
        if session_id not in self._states:
            self._states[session_id] = ConversationState()
        return self._states[session_id]

    async def generate_ai_response(self, session_id: str, rep_text: str) -> list[str]:
        state = self.get_state(session_id)
        state.rep_turns += 1
        state.stage = self._detect_stage(rep_text, state.stage)
        state.last_updated = datetime.now(timezone.utc)

        # Placeholder for LLM token streaming. Keep it short and natural for low latency.
        starter = "I hear you. "
        if "price" in rep_text.lower():
            body = "That sounds expensive for us right now."
        elif "spouse" in rep_text.lower() or "partner" in rep_text.lower():
            body = "I need to discuss this with my spouse before deciding."
        else:
            body = "Can you explain how this would help my home specifically?"
        tail = ""

        await asyncio.sleep(0.02)
        state.ai_turns += 1
        return [starter, body, tail]

    def _detect_stage(self, rep_text: str, current_stage: str) -> str:
        text = rep_text.lower()
        if current_stage == "door_knock" and any(w in text for w in ["name", "company", "hi", "hello"]):
            return "initial_pitch"
        if "objection" in text or "price" in text or "already" in text:
            return "objection_handling"
        if any(w in text for w in ["sign", "close", "today", "schedule"]):
            return "close_attempt"
        return current_stage
