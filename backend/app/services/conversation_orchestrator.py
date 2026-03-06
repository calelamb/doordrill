from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.scenario import Scenario


DEFAULT_STAGE = "door_knock"
DEFAULT_SCENARIO_DESCRIPTION = "A homeowner evaluates a door-to-door sales pitch."
DEFAULT_STAGE_SEQUENCE = [
    DEFAULT_STAGE,
    "initial_pitch",
    "objection_handling",
    "considering",
    "close_attempt",
    "ended",
]
EMOTION_ORDER = ["interested", "curious", "neutral", "skeptical", "annoyed", "hostile"]
MAX_OBJECTION_PRESSURE = 5
ACKNOWLEDGEMENT_PHRASES = (
    "i understand",
    "i get it",
    "that makes sense",
    "totally fair",
    "fair enough",
    "i hear you",
    "understand why",
    "sounds frustrating",
)
RAPPORT_PHRASES = (
    "how are you",
    "hope you're doing well",
    "appreciate your time",
    "thanks for your time",
    "noticed",
    "neighbor",
    "local",
)
VALUE_PHRASES = (
    "save",
    "protect",
    "help",
    "benefit",
    "coverage",
    "service",
    "warranty",
    "inspection",
    "custom",
    "difference",
)
PROOF_PHRASES = (
    "licensed",
    "insured",
    "review",
    "reviews",
    "guarantee",
    "guaranteed",
    "backed",
    "experience",
    "years",
    "local team",
)
LOW_PRESSURE_PHRASES = (
    "no pressure",
    "not asking you to decide today",
    "not asking you to sign today",
    "take your time",
    "when it makes sense",
    "when you're ready",
    "free quote",
    "free inspection",
    "quick look",
    "quick visit",
)
PERSONALIZATION_PHRASES = (
    "your home",
    "your house",
    "your family",
    "your kids",
    "your property",
    "your schedule",
)
PRESSURE_PHRASES = (
    "sign today",
    "right now",
    "need to",
    "only today",
    "close this",
    "just do it",
)
DISMISSIVE_PHRASES = (
    "trust me",
    "obviously",
    "just listen",
    "you need to",
    "you're wrong",
)
OBJECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "price": ("price", "cost", "budget", "expensive", "cheap"),
    "trust": ("trust", "licensed", "insured", "reviews", "guarantee", "reputation"),
    "timing": ("busy", "later", "not now", "quick", "minutes", "schedule", "time"),
    "spouse": ("spouse", "partner", "wife", "husband", "family"),
    "incumbent_provider": ("already", "provider", "switch", "current", "using", "orkin"),
    "safety_environment": ("chemical", "kids", "pet", "environment", "safe", "safety"),
}
ATTITUDE_MARKERS = (
    ("hostile", "hostile"),
    ("angry", "hostile"),
    ("furious", "hostile"),
    ("irritated", "annoyed"),
    ("impatient", "annoyed"),
    ("hurried", "annoyed"),
    ("busy", "annoyed"),
    ("annoyed", "annoyed"),
    ("skeptical", "skeptical"),
    ("guarded", "skeptical"),
    ("protective", "skeptical"),
    ("practical", "neutral"),
    ("neutral", "neutral"),
    ("curious", "curious"),
    ("friendly", "curious"),
    ("open", "curious"),
    ("interested", "interested"),
)
BUY_LIKELIHOOD_BIAS = {
    "high": -1,
    "high-medium": -1,
    "medium-high": -1,
    "medium": 0,
    "medium-low": 1,
    "low-medium": 1,
    "low": 1,
}
HELPFUL_SIGNALS = {
    "acknowledges_concern",
    "builds_rapport",
    "explains_value",
    "provides_proof",
    "reduces_pressure",
    "personalizes_pitch",
    "invites_dialogue",
}
HARMFUL_SIGNALS = {
    "pushes_close",
    "dismisses_concern",
    "ignores_objection",
    "high_difficulty_backfire",
}
OBJECTION_RESOLUTION_SIGNALS: dict[str, frozenset[str]] = {
    "price": frozenset({"acknowledges_concern", "explains_value", "reduces_pressure"}),
    "trust": frozenset({"acknowledges_concern", "builds_rapport", "provides_proof"}),
    "timing": frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"}),
    "spouse": frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"}),
    "incumbent_provider": frozenset({"acknowledges_concern", "explains_value", "provides_proof"}),
    "safety_environment": frozenset({"acknowledges_concern", "provides_proof", "personalizes_pitch"}),
}
EMOTION_RESPONSE_STYLE = {
    "interested": "You are leaning in and want specifics. Ask practical next-step questions if the rep is clear.",
    "curious": "You are open but still evaluating. Ask follow-up questions and invite details.",
    "neutral": "You are polite and measured. Respond naturally without offering extra enthusiasm.",
    "skeptical": "You doubt the pitch and want proof. Push on weak claims and vague benefits.",
    "annoyed": "You are impatient and defensive. Keep responses short and surface objections quickly.",
    "hostile": "You are irritated and close to ending the conversation. Challenge pushiness directly.",
}
EMOTION_TRANSITION_HINTS = {
    "interested": "Stay practical and warm. If the rep becomes pushy or evasive, snap back toward skeptical quickly.",
    "curious": "Stay open while testing for specifics. Good answers can move you toward interested; vague answers move you toward skeptical.",
    "neutral": "Stay measured and reserved. Helpful clarity can open you up; pressure should harden you into skepticism.",
    "skeptical": "Keep asking for proof. Acknowledgement plus specific, low-pressure answers can soften you toward curious.",
    "annoyed": "Be short and impatient. Ignored objections or closing pressure should move you toward hostile fast.",
    "hostile": "You are close to shutting the door. Only a clear de-escalation should move you back to annoyed.",
}


def _coerce_stage_sequence(stages: list[str] | None) -> list[str]:
    normalized = [str(stage).strip() for stage in stages or [] if str(stage).strip()]
    return normalized or list(DEFAULT_STAGE_SEQUENCE)


@dataclass
class ScenarioSnapshot:
    name: str = "Generic Homeowner"
    description: str = DEFAULT_SCENARIO_DESCRIPTION
    difficulty: int = 1
    persona_payload: dict[str, Any] = field(default_factory=dict)
    stages: list[str] = field(default_factory=lambda: list(DEFAULT_STAGE_SEQUENCE))

    @classmethod
    def from_scenario(cls, scenario: "Scenario | None") -> "ScenarioSnapshot":
        if scenario is None:
            return cls()
        return cls(
            name=str(getattr(scenario, "name", None) or "Generic Homeowner"),
            description=str(getattr(scenario, "description", None) or DEFAULT_SCENARIO_DESCRIPTION),
            difficulty=max(1, int(getattr(scenario, "difficulty", 1) or 1)),
            persona_payload=dict(getattr(scenario, "persona", {}) or {}),
            stages=_coerce_stage_sequence(getattr(scenario, "stages", None)),
        )


@dataclass
class ConversationState:
    stage: str = DEFAULT_STAGE
    emotion: str = "neutral"
    resistance_level: int = 2
    rep_turns: int = 0
    ai_turns: int = 0
    rapport_score: int = 0
    active_objections: list[str] = field(default_factory=list)
    queued_objections: list[str] = field(default_factory=list)
    resolved_objections: list[str] = field(default_factory=list)
    objection_pressure: int = 0
    ignored_objection_streak: int = 0
    last_behavior_signals: list[str] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RepTurnPlan:
    stage_before: str
    stage_after: str
    stage_changed: bool
    emotion_before: str
    emotion_after: str
    emotion_changed: bool
    objection_tags: list[str]
    active_objections: list[str]
    queued_objections: list[str]
    resolved_objections: list[str]
    behavioral_signals: list[str]
    objection_pressure_before: int
    objection_pressure_after: int
    resistance_level: int
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
    scenario_snapshot: ScenarioSnapshot
    persona: HomeownerPersona
    prompt_version: str | None = None


@dataclass
class BehaviorAssessment:
    signals: list[str]
    resolved_objections: list[str]


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
        "considering": "CONSIDERING",
        "close_attempt": "CLOSE_WINDOW",
        "ended": "ENDED",
    }

    @classmethod
    def template_blueprint(cls) -> str:
        return (
            "Layer 1: hardcoded homeowner immersion contract.\n"
            "Layer 2: persona fields: name, attitude, concerns, objection_queue, buy_likelihood, softening_condition.\n"
            "Layer 3: stage-aware instructions covering DOOR_OPEN, LISTENING, OBJECTING, CONSIDERING, CLOSE_WINDOW, ENDED.\n"
            "Layer 3B: emotional state machine framing with resistance level, objection pressure, active objections, and latent objections.\n"
            "Layer 4: anti-pattern guards for aggressive reps, off-topic reps, and reps asking for hints or coaching."
        )

    def build(
        self,
        scenario: "Scenario | None",
        persona: HomeownerPersona,
        stage: str,
        prompt_version: str | None = None,
        *,
        scenario_snapshot: ScenarioSnapshot | None = None,
        emotion: str | None = None,
        resistance_level: int | None = None,
        objection_pressure: int | None = None,
        active_objections: list[str] | None = None,
        queued_objections: list[str] | None = None,
        resolved_objections: list[str] | None = None,
        behavioral_signals: list[str] | None = None,
    ) -> str:
        snapshot = scenario_snapshot or ScenarioSnapshot.from_scenario(scenario)
        canonical_stage = self._normalize_stage(stage)
        scenario_name = snapshot.name
        scenario_description = snapshot.description
        difficulty = snapshot.difficulty
        stage_instruction = self.STAGE_GUIDANCE.get(canonical_stage, self.STAGE_GUIDANCE["LISTENING"])
        stage_lines = "\n".join(
            f"- {stage_name}: {instruction}"
            for stage_name, instruction in self.STAGE_GUIDANCE.items()
        )
        scenario_stages = ", ".join(snapshot.stages) or ", ".join(DEFAULT_STAGE_SEQUENCE)
        emotional_state = emotion or "neutral"
        unresolved_objections = active_objections or []
        latent_objections = queued_objections or []
        cleared_objections = resolved_objections or []
        observed_signals = behavioral_signals or []
        emotional_guidance = EMOTION_RESPONSE_STYLE.get(emotional_state, EMOTION_RESPONSE_STYLE["neutral"])
        transition_hint = EMOTION_TRANSITION_HINTS.get(emotional_state, EMOTION_TRANSITION_HINTS["neutral"])

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
        layer_three_b = (
            "LAYER 3B - EMOTIONAL CONTEXT\n"
            f"Scenario: {scenario_name}.\n"
            f"Persona attitude: {persona.attitude}.\n"
            f"Current emotional state: {emotional_state}.\n"
            f"Resistance level: {resistance_level if resistance_level is not None else 2}.\n"
            f"Objection pressure: {objection_pressure if objection_pressure is not None else 0}/{MAX_OBJECTION_PRESSURE}.\n"
            f"Active unresolved objections: {', '.join(unresolved_objections) or 'none'}.\n"
            f"Latent objections still available to surface: {', '.join(latent_objections) or 'none'}.\n"
            f"Recently resolved objections: {', '.join(cleared_objections) or 'none'}.\n"
            f"Recent rep behavior signals: {', '.join(observed_signals) or 'none'}.\n"
            f"Response style: {emotional_guidance}\n"
            f"Transition rule: {transition_hint}"
        )
        layer_four = (
            "LAYER 4 - ANTI-PATTERN GUARDS\n"
            "If the rep is aggressive, become shorter, firmer, and more skeptical.\n"
            "If the rep ignores an active objection, escalate the next concern from the latent queue when appropriate.\n"
            "If the rep goes off-topic, redirect them back to your home, your concern, or end the exchange.\n"
            "If the rep asks for hints, coaching, or what to say next, refuse and respond as a homeowner would.\n"
            "If the rep says something unrealistic or false, challenge it like a real homeowner.\n"
            "Do not compliment the rep for technique. Do not expose scoring criteria."
        )
        version_line = f"Prompt version: {prompt_version or 'conversation_v1'}"
        return "\n\n".join([version_line, layer_one, layer_two, layer_three, layer_three_b, layer_four])

    def build_from_scenario(self, scenario: "Scenario | None", stage: str, prompt_version: str | None = None) -> str:
        snapshot = ScenarioSnapshot.from_scenario(scenario)
        persona = HomeownerPersona.from_payload(snapshot.persona_payload)
        return self.build(
            scenario=scenario,
            scenario_snapshot=snapshot,
            persona=persona,
            stage=stage,
            prompt_version=prompt_version,
        )

    def _normalize_stage(self, stage: str) -> str:
        if not stage:
            return "LISTENING"
        upper = stage.upper()
        if upper in self.STAGE_GUIDANCE:
            return upper
        return self.INTERNAL_STAGE_MAP.get(stage, "LISTENING")


class ConversationOrchestrator:
    """State manager for scenario stage progression, emotion, and objection escalation."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}
        self._contexts: dict[str, SessionPromptContext] = {}
        self._prompt_builder = PromptBuilder()

    def initialize_session(
        self,
        session_id: str,
        *,
        scenario_name: str | None = None,
        scenario_description: str | None = None,
        difficulty: int | None = None,
        persona: dict[str, Any] | None = None,
        stages: list[str] | None = None,
        prompt_version: str | None = None,
    ) -> ConversationState:
        context = SessionPromptContext(
            scenario=None,
            scenario_snapshot=ScenarioSnapshot(
                name=scenario_name or "Generic Homeowner",
                description=scenario_description or DEFAULT_SCENARIO_DESCRIPTION,
                difficulty=max(1, int(difficulty or 1)),
                persona_payload=dict(persona or {}),
                stages=_coerce_stage_sequence(stages),
            ),
            persona=HomeownerPersona.from_payload(persona),
            prompt_version=prompt_version,
        )
        self._contexts[session_id] = context

        state = self._states.get(session_id)
        if state is None:
            state = self._initialize_state_from_context(context)
            self._states[session_id] = state
        return state

    def get_state(self, session_id: str) -> ConversationState:
        state = self._states.get(session_id)
        if state is not None:
            return state

        context = self._contexts.get(session_id)
        if context is None:
            return self.initialize_session(session_id)

        state = self._initialize_state_from_context(context)
        self._states[session_id] = state
        return state

    def get_state_payload(self, session_id: str) -> dict[str, Any]:
        state = self.get_state(session_id)
        return {
            "stage": state.stage,
            "emotion": state.emotion,
            "resistance_level": state.resistance_level,
            "objection_pressure": state.objection_pressure,
            "active_objections": list(state.active_objections),
            "queued_objections": list(state.queued_objections),
            "resolved_objections": list(state.resolved_objections),
        }

    def bind_session_context(self, session_id: str, scenario: "Scenario | None", prompt_version: str | None = None) -> None:
        snapshot = ScenarioSnapshot.from_scenario(scenario)
        context = SessionPromptContext(
            scenario=scenario,
            scenario_snapshot=snapshot,
            persona=HomeownerPersona.from_payload(snapshot.persona_payload),
            prompt_version=prompt_version,
        )
        self._contexts[session_id] = context

        if session_id not in self._states:
            self._states[session_id] = self._initialize_state_from_context(context)

    def clear_session_context(self, session_id: str) -> None:
        self._contexts.pop(session_id, None)
        self._states.pop(session_id, None)

    def end_session(self, session_id: str) -> None:
        self.clear_session_context(session_id)

    def prepare_rep_turn(self, session_id: str, rep_text: str) -> RepTurnPlan:
        state = self.get_state(session_id)
        context = self._contexts.get(session_id)

        stage_before = state.stage
        emotion_before = state.emotion
        objection_pressure_before = state.objection_pressure

        objection_tags = self._extract_objection_tags(rep_text)
        stage_after = self._detect_stage(rep_text, state, context)
        assessment = self._evaluate_rep_behavior(rep_text, state, objection_tags, context)

        state.rep_turns += 1
        state.stage = stage_after

        resolved_objections = self._apply_resolved_objections(state, assessment.resolved_objections)
        state.ignored_objection_streak = self._next_ignored_objection_streak(
            current_streak=state.ignored_objection_streak,
            signals=assessment.signals,
            resolved_objections=resolved_objections,
            has_active_objections=bool(state.active_objections),
        )
        self._surface_escalated_objections(state, assessment.signals)
        state.objection_pressure = self._next_objection_pressure(
            current_pressure=objection_pressure_before,
            signals=assessment.signals,
            resolved_count=len(resolved_objections),
            active_count=len(state.active_objections),
            ignored_streak=state.ignored_objection_streak,
        )
        state.emotion = self._transition_emotion(
            current_emotion=emotion_before,
            pressure_before=objection_pressure_before,
            pressure_after=state.objection_pressure,
            signals=assessment.signals,
            resolved_count=len(resolved_objections),
        )
        state.resistance_level = self._emotion_to_resistance(state.emotion)
        state.last_behavior_signals = assessment.signals
        state.last_updated = datetime.now(timezone.utc)

        system_prompt = self._build_system_prompt(stage_after=stage_after, session_id=session_id)

        return RepTurnPlan(
            stage_before=stage_before,
            stage_after=stage_after,
            stage_changed=stage_before != stage_after,
            emotion_before=emotion_before,
            emotion_after=state.emotion,
            emotion_changed=emotion_before != state.emotion,
            objection_tags=objection_tags,
            active_objections=list(state.active_objections),
            queued_objections=list(state.queued_objections),
            resolved_objections=list(resolved_objections),
            behavioral_signals=assessment.signals,
            objection_pressure_before=objection_pressure_before,
            objection_pressure_after=state.objection_pressure,
            resistance_level=state.resistance_level,
            system_prompt=system_prompt,
        )

    def mark_ai_turn(self, session_id: str) -> None:
        state = self.get_state(session_id)
        state.ai_turns += 1
        state.last_updated = datetime.now(timezone.utc)

    def _initialize_state_from_context(self, context: SessionPromptContext) -> ConversationState:
        starting_emotion = self._determine_starting_emotion(context.scenario_snapshot)
        seeded_objections = self._seed_objections(
            context.scenario_snapshot.persona_payload,
            context.scenario_snapshot.description,
        )
        active_count = self._initial_active_objection_count(
            starting_emotion=starting_emotion,
            difficulty=context.scenario_snapshot.difficulty,
            seeded_objection_count=len(seeded_objections),
        )
        active_objections = seeded_objections[:active_count]
        queued_objections = seeded_objections[active_count:]
        stage = context.scenario_snapshot.stages[0] if context.scenario_snapshot.stages else DEFAULT_STAGE
        return ConversationState(
            stage=stage,
            emotion=starting_emotion,
            resistance_level=self._emotion_to_resistance(starting_emotion),
            active_objections=active_objections,
            queued_objections=queued_objections,
            resolved_objections=[],
            objection_pressure=self._initial_objection_pressure(starting_emotion, active_count),
        )

    def _build_system_prompt(self, stage_after: str, session_id: str | None = None) -> str:
        context = self._contexts.get(session_id or "")
        state = self._states.get(session_id or "")

        if context is not None:
            return self._prompt_builder.build(
                scenario=context.scenario,
                scenario_snapshot=context.scenario_snapshot,
                persona=context.persona,
                stage=stage_after,
                prompt_version=context.prompt_version,
                emotion=state.emotion if state is not None else "neutral",
                resistance_level=state.resistance_level if state is not None else 2,
                objection_pressure=state.objection_pressure if state is not None else 0,
                active_objections=list(state.active_objections) if state is not None else [],
                queued_objections=list(state.queued_objections) if state is not None else [],
                resolved_objections=list(state.resolved_objections) if state is not None else [],
                behavioral_signals=list(state.last_behavior_signals) if state is not None else [],
            )

        fallback_snapshot = ScenarioSnapshot()
        fallback_persona = HomeownerPersona.from_payload(fallback_snapshot.persona_payload)
        return self._prompt_builder.build(
            scenario=None,
            scenario_snapshot=fallback_snapshot,
            persona=fallback_persona,
            stage=stage_after,
            prompt_version="conversation_v1",
            emotion=state.emotion if state is not None else "neutral",
            resistance_level=state.resistance_level if state is not None else 2,
            objection_pressure=state.objection_pressure if state is not None else 0,
            active_objections=list(state.active_objections) if state is not None else [],
            queued_objections=list(state.queued_objections) if state is not None else [],
            resolved_objections=list(state.resolved_objections) if state is not None else [],
            behavioral_signals=list(state.last_behavior_signals) if state is not None else [],
        )

    def _detect_stage(
        self,
        rep_text: str,
        state: ConversationState,
        context: SessionPromptContext | None,
    ) -> str:
        text = rep_text.lower()
        stages = context.scenario_snapshot.stages if context is not None else list(DEFAULT_STAGE_SEQUENCE)
        first_stage = stages[0] if stages else DEFAULT_STAGE
        pitch_stage = self._find_stage(stages, ("pitch", "listen"), fallback="initial_pitch")
        objection_stage = self._find_stage(stages, ("objection",), fallback="objection_handling")
        considering_stage = self._find_stage(stages, ("consider",), fallback="considering")
        close_stage = self._find_stage(stages, ("close",), fallback="close_attempt")
        ended_stage = self._find_stage(stages, ("end",), fallback="ended")

        if any(phrase in text for phrase in ("have a good one", "no worries", "i'll leave you alone", "take care")):
            return ended_stage
        if any(phrase in text for phrase in ("sign", "close", "today", "schedule", "next step", "start service")):
            return close_stage
        if state.stage in {pitch_stage, objection_stage, considering_stage} and any(
            phrase in text for phrase in ("fair", "would it make sense", "if i could", "what if", "so the idea", "based on that")
        ):
            return considering_stage
        if any(keyword in text for keywords in OBJECTION_KEYWORDS.values() for keyword in keywords):
            return objection_stage
        if state.stage == first_stage and any(word in text for word in ("name", "company", "hi", "hello")):
            return pitch_stage
        return state.stage

    def _evaluate_rep_behavior(
        self,
        rep_text: str,
        state: ConversationState,
        objection_tags: list[str],
        context: SessionPromptContext | None,
    ) -> BehaviorAssessment:
        text = rep_text.lower()
        signals: list[str] = []

        if any(phrase in text for phrase in ACKNOWLEDGEMENT_PHRASES):
            signals.append("acknowledges_concern")

        if any(phrase in text for phrase in RAPPORT_PHRASES):
            signals.append("builds_rapport")
            state.rapport_score += 1

        if any(phrase in text for phrase in VALUE_PHRASES):
            signals.append("explains_value")

        if any(phrase in text for phrase in PROOF_PHRASES):
            signals.append("provides_proof")

        if any(phrase in text for phrase in LOW_PRESSURE_PHRASES):
            signals.append("reduces_pressure")

        if any(phrase in text for phrase in PERSONALIZATION_PHRASES):
            signals.append("personalizes_pitch")

        if "?" in rep_text or any(phrase in text for phrase in ("what ", "how ", "why ", "would it", "does that")):
            signals.append("invites_dialogue")

        if any(phrase in text for phrase in PRESSURE_PHRASES):
            signals.append("pushes_close")

        if any(phrase in text for phrase in DISMISSIVE_PHRASES):
            signals.append("dismisses_concern")

        active_or_queued = set(state.active_objections) | set(state.queued_objections)
        resolved_objections = [
            tag
            for tag in objection_tags
            if tag in active_or_queued and self._is_objection_resolved(tag, signals)
        ]

        objection_stage = self._find_stage(
            context.scenario_snapshot.stages if context is not None else list(DEFAULT_STAGE_SEQUENCE),
            ("objection",),
            fallback="objection_handling",
        )
        if state.active_objections and not resolved_objections:
            addressed_active = any(tag in state.active_objections for tag in objection_tags)
            if not addressed_active and ("pushes_close" in signals or state.stage == objection_stage):
                signals.append("ignores_objection")

        scenario_difficulty = context.scenario_snapshot.difficulty if context is not None else 1
        if scenario_difficulty >= 4 and any(signal in {"pushes_close", "dismisses_concern"} for signal in signals):
            signals.append("high_difficulty_backfire")

        if not signals:
            signals.append("neutral_delivery")

        return BehaviorAssessment(
            signals=self._dedupe(signals),
            resolved_objections=self._dedupe(resolved_objections),
        )

    def _determine_starting_emotion(self, snapshot: ScenarioSnapshot) -> str:
        persona = snapshot.persona_payload or {}
        attitude_text = str(persona.get("attitude", "neutral")).strip().lower()
        description = snapshot.description.lower()
        combined_text = f"{attitude_text} {description}"
        seeded_objections = self._seed_objections(persona, snapshot.description)

        base = self._emotion_from_text(attitude_text)
        if base == "neutral":
            base = self._emotion_from_text(description)

        pressure_bias = 0
        if snapshot.difficulty >= 4:
            pressure_bias += 1
        if snapshot.difficulty >= 5:
            pressure_bias += 1
        elif snapshot.difficulty <= 1:
            pressure_bias -= 1

        buy_likelihood = str(persona.get("buy_likelihood", "medium")).lower()
        pressure_bias += BUY_LIKELIHOOD_BIAS.get(buy_likelihood, 0)

        if len(seeded_objections) >= 3:
            pressure_bias += 1

        if any(marker in combined_text for marker in ("bad experience", "wasted my money", "high-friction", "hard to win over")):
            pressure_bias += 1

        if any(marker in combined_text for marker in ("friendly", "open to hearing", "curious", "receptive")):
            pressure_bias -= 1

        if "hostile" in combined_text or "angry" in combined_text:
            return "hostile"

        if pressure_bias > 0:
            return self._harden_emotion(base, pressure_bias)
        if pressure_bias < 0:
            return self._soften_emotion(base, abs(pressure_bias))
        return base

    def _seed_objections(self, persona: dict[str, Any], description: str) -> list[str]:
        seeded: list[str] = []
        concerns = persona.get("concerns", [])
        queue = persona.get("objection_queue") or persona.get("objections") or []

        if isinstance(concerns, list):
            for concern in concerns:
                normalized = self._normalize_objection(str(concern))
                if normalized and normalized not in seeded:
                    seeded.append(normalized)

        if isinstance(queue, list):
            for objection in queue:
                normalized = self._normalize_objection(str(objection))
                if normalized and normalized not in seeded:
                    seeded.append(normalized)

        text = description.lower()
        for tag, keywords in OBJECTION_KEYWORDS.items():
            if any(keyword in text for keyword in keywords) and tag not in seeded:
                seeded.append(tag)

        return seeded

    def _extract_objection_tags(self, rep_text: str) -> list[str]:
        text = rep_text.lower()
        tags: list[str] = []
        for tag, keywords in OBJECTION_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                tags.append(tag)
        return tags

    def _normalize_objection(self, value: str) -> str | None:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            return None
        if normalized in OBJECTION_KEYWORDS:
            return normalized
        if normalized in {"busy", "later", "not_now", "schedule", "timing"}:
            return "timing"
        if normalized in {"wife", "husband", "partner", "family", "spouse"}:
            return "spouse"
        if normalized in {"provider", "already", "current_service", "current_provider", "incumbent"}:
            return "incumbent_provider"
        if normalized in {"kids", "kid", "pet", "pets", "environment", "chemical", "safety"}:
            return "safety_environment"
        if normalized in {"value", "hidden_fees", "wasted_money", "risk"}:
            return "price"
        return normalized

    def _find_stage(self, stages: list[str], markers: tuple[str, ...], *, fallback: str) -> str:
        for stage in stages:
            lowered = stage.lower()
            if any(marker in lowered for marker in markers):
                return stage
        return fallback

    def _initial_active_objection_count(self, *, starting_emotion: str, difficulty: int, seeded_objection_count: int) -> int:
        if seeded_objection_count == 0:
            return 0
        if starting_emotion in {"hostile", "annoyed"}:
            return min(2, seeded_objection_count)
        if starting_emotion == "skeptical":
            return min(2, seeded_objection_count)
        if difficulty >= 4:
            return 1
        if starting_emotion == "neutral":
            return 1
        return 0

    def _initial_objection_pressure(self, emotion: str, active_objection_count: int) -> int:
        pressure = active_objection_count
        if emotion in {"skeptical", "annoyed", "hostile"} and active_objection_count:
            pressure += 1
        return max(0, min(MAX_OBJECTION_PRESSURE, pressure))

    def _apply_resolved_objections(self, state: ConversationState, resolved_objections: list[str]) -> list[str]:
        applied: list[str] = []
        for tag in resolved_objections:
            if tag in state.active_objections:
                state.active_objections.remove(tag)
            if tag in state.queued_objections:
                state.queued_objections.remove(tag)
            if tag not in state.resolved_objections:
                state.resolved_objections.append(tag)
            applied.append(tag)
        return applied

    def _next_ignored_objection_streak(
        self,
        *,
        current_streak: int,
        signals: list[str],
        resolved_objections: list[str],
        has_active_objections: bool,
    ) -> int:
        if any(signal in {"ignores_objection", "dismisses_concern"} for signal in signals):
            return min(3, current_streak + 1)
        if resolved_objections or any(signal in {"acknowledges_concern", "reduces_pressure"} for signal in signals):
            return 0
        if not has_active_objections:
            return 0
        return current_streak

    def _surface_escalated_objections(self, state: ConversationState, signals: list[str]) -> None:
        if "dismisses_concern" in signals:
            self._activate_objection(state, "trust")

        should_surface_next = any(signal in {"ignores_objection", "dismisses_concern"} for signal in signals)
        if not should_surface_next and not ("pushes_close" in signals and state.active_objections):
            return

        if state.queued_objections:
            self._activate_objection(state, state.queued_objections[0])

    def _activate_objection(self, state: ConversationState, tag: str) -> None:
        if tag in state.active_objections:
            return
        if tag in state.queued_objections:
            state.queued_objections.remove(tag)
        if tag in state.resolved_objections:
            state.resolved_objections.remove(tag)
        state.active_objections.append(tag)

    def _next_objection_pressure(
        self,
        *,
        current_pressure: int,
        signals: list[str],
        resolved_count: int,
        active_count: int,
        ignored_streak: int,
    ) -> int:
        pressure = current_pressure
        if "acknowledges_concern" in signals:
            pressure -= 1
        if "builds_rapport" in signals:
            pressure -= 1
        if "explains_value" in signals:
            pressure -= 1
        if "provides_proof" in signals:
            pressure -= 1
        if "reduces_pressure" in signals:
            pressure -= 1
        if "personalizes_pitch" in signals:
            pressure -= 1
        if "invites_dialogue" in signals:
            pressure -= 1
        if "pushes_close" in signals:
            pressure += 1
        if "dismisses_concern" in signals:
            pressure += 2
        if "ignores_objection" in signals:
            pressure += 2
        if "high_difficulty_backfire" in signals:
            pressure += 1
        pressure -= resolved_count
        if active_count >= 2:
            pressure += 1
        if ignored_streak >= 2:
            pressure += 1
        if active_count == 0:
            pressure -= 1
        return max(0, min(MAX_OBJECTION_PRESSURE, pressure))

    def _transition_emotion(
        self,
        *,
        current_emotion: str,
        pressure_before: int,
        pressure_after: int,
        signals: list[str],
        resolved_count: int,
    ) -> str:
        helpful_count = sum(1 for signal in signals if signal in HELPFUL_SIGNALS)
        harmful_count = sum(1 for signal in signals if signal in HARMFUL_SIGNALS)

        if "dismisses_concern" in signals and pressure_after >= 4:
            return "hostile"
        if "ignores_objection" in signals and "pushes_close" in signals and pressure_after >= 4:
            return "hostile"
        if pressure_after >= MAX_OBJECTION_PRESSURE:
            return "hostile"
        if pressure_after >= 4:
            return "hostile" if current_emotion == "annoyed" and harmful_count >= 2 else "annoyed"

        if resolved_count > 0 and helpful_count >= 3 and pressure_after <= 1:
            if current_emotion in {"skeptical", "neutral", "curious", "interested"}:
                return "interested"
            return self._soften_emotion(current_emotion, 2)

        if resolved_count > 0 and helpful_count >= 2:
            return self._soften_emotion(current_emotion, 2 if current_emotion != "hostile" else 1)

        if helpful_count >= 2 and pressure_after < pressure_before:
            return self._soften_emotion(current_emotion, 1)

        if harmful_count >= 2:
            return self._harden_emotion(current_emotion, 1)

        if pressure_after > pressure_before:
            return self._harden_emotion(current_emotion, 1)

        if pressure_after < pressure_before:
            return self._soften_emotion(current_emotion, 1)

        if current_emotion == "neutral" and helpful_count >= 1:
            return "curious"
        if current_emotion == "neutral" and harmful_count >= 1:
            return "skeptical"
        return current_emotion

    def _is_objection_resolved(self, tag: str, signals: list[str]) -> bool:
        required_signals = OBJECTION_RESOLUTION_SIGNALS.get(tag, frozenset({"acknowledges_concern", "explains_value"}))
        return len(required_signals.intersection(signals)) >= 2 or (
            "acknowledges_concern" in signals and bool(required_signals.intersection(signals))
        )

    def _emotion_from_text(self, text: str) -> str:
        lowered = text.lower()
        for marker, emotion in ATTITUDE_MARKERS:
            if marker in lowered:
                return emotion
        return "neutral"

    def _soften_emotion(self, emotion: str, steps: int) -> str:
        return self._shift_emotion(emotion, -abs(steps))

    def _harden_emotion(self, emotion: str, steps: int) -> str:
        return self._shift_emotion(emotion, abs(steps))

    def _shift_emotion(self, emotion: str, delta: int) -> str:
        index = self._emotion_to_resistance(emotion)
        shifted = max(0, min(len(EMOTION_ORDER) - 1, index + delta))
        return EMOTION_ORDER[shifted]

    def _emotion_to_resistance(self, emotion: str) -> int:
        try:
            return EMOTION_ORDER.index(emotion)
        except ValueError:
            return EMOTION_ORDER.index("neutral")

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
