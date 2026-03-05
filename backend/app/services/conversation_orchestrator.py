from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.scenario import Scenario


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


@dataclass
class HomeownerPersona:
    name: str
    attitude: str
    concerns: list[str]
    objection_queue: list[str]
    buy_likelihood: str
    softening_condition: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "HomeownerPersona":
        data = payload or {}
        objections = data.get("objection_queue") or data.get("objections") or []
        concerns = data.get("concerns") or []
        return cls(
            name=str(data.get("name") or "Homeowner"),
            attitude=str(data.get("attitude") or "guarded"),
            concerns=[str(item) for item in concerns if str(item).strip()],
            objection_queue=[str(item) for item in objections if str(item).strip()],
            buy_likelihood=str(data.get("buy_likelihood") or "medium"),
            softening_condition=str(
                data.get("softening_condition")
                or "The rep becomes more credible when they sound specific, calm, and homeowner-focused."
            ),
        )


@dataclass
class SessionPromptContext:
    scenario: "Scenario | None"
    persona: HomeownerPersona
    prompt_version: str | None = None


class PromptBuilder:
    STAGE_GUIDANCE = {
        "DOOR_OPEN": (
            "Open the interaction as a real homeowner answering the door. "
            "Be brief, mildly guarded, and do not hand the rep easy momentum."
        ),
        "LISTENING": (
            "Listen and react to the actual pitch. "
            "Ask a short clarifying question when the rep is vague, generic, or skips credibility."
        ),
        "OBJECTING": (
            "Raise the next realistic objection from your queue. "
            "Force the rep to address the actual concern instead of sliding past it."
        ),
        "CONSIDERING": (
            "You are not sold, but you are willing to consider a low-friction next step. "
            "Warm up only if the rep is specific, credible, and homeowner-focused."
        ),
        "CLOSE_WINDOW": (
            "The rep is trying to close. Decide realistically whether you accept, defer, or decline. "
            "Do not say yes unless the rep has earned trust and reduced friction."
        ),
        "ENDED": (
            "The conversation is over. End it naturally and do not reopen the sale."
        ),
    }
    INTERNAL_STAGE_MAP = {
        "door_knock": "DOOR_OPEN",
        "initial_pitch": "LISTENING",
        "objection_handling": "OBJECTING",
        "close_attempt": "CLOSE_WINDOW",
        "ended": "ENDED",
    }

    @classmethod
    def template_blueprint(cls) -> str:
        return (
            "Layer 1: hardcoded homeowner immersion contract.\n"
            "Layer 2: persona fields: name, attitude, concerns, objection_queue, buy_likelihood, softening_condition.\n"
            "Layer 3: stage-aware instructions covering DOOR_OPEN, LISTENING, OBJECTING, CONSIDERING, CLOSE_WINDOW, ENDED.\n"
            "Layer 4: anti-pattern guards for aggressive reps, off-topic reps, and reps asking for hints or coaching."
        )

    def build(self, scenario: "Scenario | None", persona: HomeownerPersona, stage: str, prompt_version: str | None = None) -> str:
        canonical_stage = self._normalize_stage(stage)
        scenario_name = scenario.name if scenario is not None else "Generic Door-to-Door Roleplay"
        scenario_description = scenario.description if scenario is not None else "A homeowner evaluates a door-to-door sales pitch."
        difficulty = getattr(scenario, "difficulty", 3)
        stage_instruction = self.STAGE_GUIDANCE.get(canonical_stage, self.STAGE_GUIDANCE["LISTENING"])
        stage_lines = "\n".join(
            f"- {stage_name}: {instruction}"
            for stage_name, instruction in self.STAGE_GUIDANCE.items()
        )
        scenario_stages = ", ".join(getattr(scenario, "stages", []) or []) or "door_knock, initial_pitch, objection_handling, considering, close_attempt, ended"

        layer_one = (
            "LAYER 1 - IMMERSION CONTRACT\n"
            "You are a real homeowner in a live door-to-door roleplay.\n"
            "Never break character.\n"
            "Respond in 1-4 sentences.\n"
            "React only to what the rep actually says.\n"
            "Do not volunteer extra information the rep has not earned.\n"
            "Do not narrate internal thoughts, coaching notes, scoring, or model behavior."
        )
        layer_two = (
            "LAYER 2 - PERSONA PROFILE\n"
            f"Scenario: {scenario_name}\n"
            f"Scenario difficulty: {difficulty}\n"
            f"Scenario description: {scenario_description}\n"
            f"Scenario stages: {scenario_stages}\n"
            f"Name: {persona.name}\n"
            f"Attitude: {persona.attitude}\n"
            f"Concerns: {', '.join(persona.concerns) or 'none listed'}\n"
            f"Objection queue: {', '.join(persona.objection_queue) or 'none listed'}\n"
            f"Buy likelihood: {persona.buy_likelihood}\n"
            f"Softening condition: {persona.softening_condition}"
        )
        layer_three = (
            "LAYER 3 - STAGE INSTRUCTIONS\n"
            f"Current stage: {canonical_stage}\n"
            f"Current stage behavior: {stage_instruction}\n"
            "Stage guidance:\n"
            f"{stage_lines}"
        )
        layer_four = (
            "LAYER 4 - ANTI-PATTERN GUARDS\n"
            "If the rep is aggressive, become shorter, firmer, and more skeptical.\n"
            "If the rep goes off-topic, redirect them back to your home, your concern, or end the exchange.\n"
            "If the rep asks for hints, coaching, or what to say next, refuse and respond as a homeowner would.\n"
            "If the rep says something unrealistic or false, challenge it like a real homeowner.\n"
            "Do not compliment the rep for technique. Do not expose scoring criteria."
        )
        version_line = f"Prompt version: {prompt_version or 'conversation_v1'}"
        return "\n\n".join([version_line, layer_one, layer_two, layer_three, layer_four])

    def build_from_scenario(self, scenario: "Scenario | None", stage: str, prompt_version: str | None = None) -> str:
        persona = HomeownerPersona.from_payload(scenario.persona if scenario is not None else None)
        return self.build(scenario=scenario, persona=persona, stage=stage, prompt_version=prompt_version)

    def _normalize_stage(self, stage: str) -> str:
        if not stage:
            return "LISTENING"
        upper = stage.upper()
        if upper in self.STAGE_GUIDANCE:
            return upper
        return self.INTERNAL_STAGE_MAP.get(stage, "LISTENING")


class ConversationOrchestrator:
    """State manager for scenario stage progression and prompt scaffolding."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}
        self._contexts: dict[str, SessionPromptContext] = {}
        self._prompt_builder = PromptBuilder()

    def get_state(self, session_id: str) -> ConversationState:
        if session_id not in self._states:
            self._states[session_id] = ConversationState()
        return self._states[session_id]

    def bind_session_context(self, session_id: str, scenario: "Scenario | None", prompt_version: str | None = None) -> None:
        self._contexts[session_id] = SessionPromptContext(
            scenario=scenario,
            persona=HomeownerPersona.from_payload(scenario.persona if scenario is not None else None),
            prompt_version=prompt_version,
        )

    def clear_session_context(self, session_id: str) -> None:
        self._contexts.pop(session_id, None)
        self._states.pop(session_id, None)

    def prepare_rep_turn(self, session_id: str, rep_text: str) -> RepTurnPlan:
        state = self.get_state(session_id)
        stage_before = state.stage
        stage_after = self._detect_stage(rep_text, state.stage)

        state.rep_turns += 1
        state.stage = stage_after
        state.last_updated = datetime.now(timezone.utc)

        tags = self._extract_objection_tags(rep_text)
        system_prompt = self._build_system_prompt(stage_after=stage_after, session_id=session_id)

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

    def _build_system_prompt(self, stage_after: str, session_id: str | None = None) -> str:
        context = self._contexts.get(session_id or "")
        if context is not None:
            return self._prompt_builder.build(
                scenario=context.scenario,
                persona=context.persona,
                stage=stage_after,
                prompt_version=context.prompt_version,
            )

        return self._prompt_builder.build(
            scenario=None,
            persona=HomeownerPersona.from_payload(None),
            stage=stage_after,
            prompt_version="conversation_v1",
        )

    def _detect_stage(self, rep_text: str, current_stage: str) -> str:
        text = rep_text.lower()
        if current_stage == "door_knock" and any(w in text for w in ["name", "company", "hi", "hello"]):
            return "initial_pitch"
        if current_stage in {"initial_pitch", "objection_handling"} and any(
            w in text for w in ["fair", "would it make sense", "if i could", "what if", "so the idea", "based on that"]
        ):
            return "considering"
        if any(w in text for w in ["price", "already", "provider", "spouse", "think about", "cheaper", "busy"]):
            return "objection_handling"
        if any(w in text for w in ["sign", "close", "today", "schedule", "next step", "start service"]):
            return "close_attempt"
        if any(w in text for w in ["have a good one", "no worries", "i'll leave you alone", "take care"]):
            return "ended"
        return current_stage

    def _extract_objection_tags(self, rep_text: str) -> list[str]:
        text = rep_text.lower()
        tags: list[str] = []
        if "price" in text or "cost" in text or "cheap" in text:
            tags.append("price")
        if "spouse" in text or "husband" in text or "wife" in text or "partner" in text:
            tags.append("spouse")
        if "already" in text or "provider" in text or "using" in text or "orkin" in text:
            tags.append("incumbent_provider")
        if "busy" in text or "later" in text or "not now" in text or "time" in text:
            tags.append("timing")
        if "chemical" in text or "kids" in text or "pet" in text or "environment" in text:
            tags.append("safety_environment")
        return tags
