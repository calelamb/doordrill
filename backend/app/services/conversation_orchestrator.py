from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import logging
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prompt_version import PromptVersion
from app.models.transcript import ObjectionType
from app.models.user import User
from app.services.micro_behavior_engine import (
    DEFAULT_TONE_BY_EMOTION,
    SENTENCE_LENGTH_BY_EMOTION,
    TONE_BY_TRANSITION,
)

if TYPE_CHECKING:
    from app.models.scenario import Scenario
    from app.services.micro_behavior_engine import MicroBehaviorPlan


logger = logging.getLogger(__name__)


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
OBJECTION_KEYWORDS_FALLBACK: dict[str, tuple[str, ...]] = {
    "price": ("price", "cost", "budget", "expensive", "cheap"),
    "trust": ("trust", "licensed", "insured", "reviews", "guarantee", "reputation"),
    "timing": ("busy", "later", "not now", "quick", "minutes", "schedule", "time"),
    "spouse": ("spouse", "partner", "wife", "husband", "family"),
    "incumbent_provider": ("already", "provider", "switch", "current", "using", "orkin"),
    "safety_environment": ("chemical", "kids", "pet", "environment", "safe", "safety"),
}
_OBJECTION_KEYWORDS_CACHE: dict[str, tuple[str, ...]] | None = None
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
EDGE_CASE_DIRECTIVES = {
    "no_intro": (
        "The rep did not introduce themselves or their company. "
        "Ask who they are with before engaging further. Do not discuss pest control until they answer."
    ),
    "premature_close": (
        "The rep is trying to close before you understand the offer. "
        "Express confusion or mild pushback: 'I don't even know what you're selling yet.'"
    ),
    "ignored_objection_wall": (
        "You have raised concerns that the rep keeps ignoring. "
        "Firmly state you need to go and do not reopen the conversation this turn."
    ),
    "spouse_handoff_eligible": (
        "You are considering but not ready to decide alone. "
        "Tell the rep your partner would need to be part of this conversation."
    ),
}
OBJECTION_RESOLUTION_SIGNALS: dict[str, frozenset[str]] = {
    "price": frozenset({"acknowledges_concern", "explains_value", "reduces_pressure"}),
    "price_per_month": frozenset({"acknowledges_concern", "explains_value", "reduces_pressure"}),
    "trust": frozenset({"acknowledges_concern", "builds_rapport", "provides_proof"}),
    "locked_in_contract": frozenset({"acknowledges_concern", "explains_value", "invites_dialogue"}),
    "timing": frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"}),
    "not_right_now": frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"}),
    "spouse": frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"}),
    "incumbent_provider": frozenset({"acknowledges_concern", "explains_value", "provides_proof"}),
    "skeptical_of_product": frozenset({"acknowledges_concern", "provides_proof", "explains_value"}),
    "need": frozenset({"acknowledges_concern", "explains_value", "personalizes_pitch"}),
    "decision_authority": frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"}),
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


def invalidate_objection_cache() -> None:
    global _OBJECTION_KEYWORDS_CACHE
    _OBJECTION_KEYWORDS_CACHE = None


def _merge_keyword_tuples(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for keyword in group:
            normalized = str(keyword).strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
    return tuple(ordered)


def _expand_keyword_terms(raw_terms: list[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for term in raw_terms:
        normalized = str(term).strip().lower()
        if not normalized:
            continue
        expanded.append(normalized)
        tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 4]
        expanded.extend(tokens)
        expanded.extend(" ".join(tokens[index:index + 2]) for index in range(len(tokens) - 1))
    return _merge_keyword_tuples(tuple(expanded))


def load_objection_keywords(db: Session) -> dict[str, tuple[str, ...]]:
    global _OBJECTION_KEYWORDS_CACHE
    if _OBJECTION_KEYWORDS_CACHE is not None:
        return _OBJECTION_KEYWORDS_CACHE

    try:
        rows = db.scalars(
            select(ObjectionType)
            .where(ObjectionType.is_active.is_(True))
            .order_by(ObjectionType.created_at.asc(), ObjectionType.slug.asc())
        ).all()
    except Exception:
        logger.exception("Failed to load objection keywords from database")
        return OBJECTION_KEYWORDS_FALLBACK

    if not rows:
        return OBJECTION_KEYWORDS_FALLBACK

    keywords: dict[str, tuple[str, ...]] = {}
    for row in rows:
        slug = str(row.slug or "").strip()
        if not slug:
            continue
        trigger_keywords = [str(item) for item in (row.trigger_keywords or []) if str(item).strip()]
        keyword_tuple = _merge_keyword_tuples(
            OBJECTION_KEYWORDS_FALLBACK.get(slug, ()),
            _expand_keyword_terms(trigger_keywords),
        )
        keywords[slug] = _merge_keyword_tuples(keywords.get(slug, ()), keyword_tuple)

    if not keywords:
        return OBJECTION_KEYWORDS_FALLBACK

    _OBJECTION_KEYWORDS_CACHE = keywords
    return _OBJECTION_KEYWORDS_CACHE


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
    persona_concerns: list[str] = field(default_factory=list)
    active_objections: list[str] = field(default_factory=list)
    queued_objections: list[str] = field(default_factory=list)
    resolved_objections: list[str] = field(default_factory=list)
    active_edge_cases: list[str] = field(default_factory=list)
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
    active_edge_cases: list[str]
    behavioral_signals: list[str]
    objection_pressure_before: int
    objection_pressure_after: int
    resistance_level: int
    behavior_directives: "BehaviorDirectives"
    system_prompt: str


@dataclass
class BehaviorDirectives:
    tone: str
    sentence_length: str
    interruption_mode: bool
    directive_text: str


@dataclass
class HomeownerPersona:
    name: str
    attitude: str
    concerns: list[str]
    objection_queue: list[str]
    buy_likelihood: str
    softening_condition: str
    household_type: str | None = None
    home_ownership_years: int | None = None
    pest_history: list[str] = field(default_factory=list)
    price_sensitivity: str | None = None
    communication_style: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "HomeownerPersona":
        # Accepted scenario.persona keys:
        # name, attitude, concerns, objection_queue, objections, buy_likelihood,
        # softening_condition, household_type, home_ownership_years, pest_history,
        # price_sensitivity, communication_style.
        data = payload or {}
        objections = data.get("objection_queue") or data.get("objections") or []
        concerns = data.get("concerns") or []
        pest_history = data.get("pest_history") or []
        home_ownership_years = None
        raw_home_ownership_years = data.get("home_ownership_years")
        if raw_home_ownership_years is not None:
            with_value = str(raw_home_ownership_years).strip()
            if with_value:
                with contextlib.suppress(TypeError, ValueError):
                    home_ownership_years = max(1, min(30, int(with_value)))
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
            household_type=str(data.get("household_type")).strip() if data.get("household_type") else None,
            home_ownership_years=home_ownership_years,
            pest_history=[str(item) for item in pest_history if str(item).strip()],
            price_sensitivity=str(data.get("price_sensitivity")).strip().lower() if data.get("price_sensitivity") else None,
            communication_style=str(data.get("communication_style")).strip().lower() if data.get("communication_style") else None,
        )


class PersonaEnricher:
    @classmethod
    def enrich(
        cls,
        persona: HomeownerPersona,
        difficulty: int,
        scenario_description: str,
    ) -> HomeownerPersona:
        normalized_difficulty = max(1, min(5, int(difficulty or 1)))
        description = scenario_description.lower()
        updates: dict[str, Any] = {}

        if persona.household_type is None:
            updates["household_type"] = cls._default_household_type(persona, description)
        if persona.home_ownership_years is None:
            updates["home_ownership_years"] = cls._default_home_ownership_years(normalized_difficulty)
        if not persona.pest_history:
            updates["pest_history"] = cls._default_pest_history(normalized_difficulty, description)
        if persona.price_sensitivity is None:
            updates["price_sensitivity"] = cls._default_price_sensitivity(normalized_difficulty)
        if persona.communication_style is None:
            updates["communication_style"] = cls._default_communication_style(persona, normalized_difficulty, description)

        if not updates:
            return replace(persona, pest_history=list(persona.pest_history))
        return replace(persona, **updates)

    @staticmethod
    def _default_household_type(persona: HomeownerPersona, description: str) -> str:
        concern_text = " ".join(persona.concerns).lower()
        combined_text = f"{persona.attitude.lower()} {description} {concern_text}"
        if any(marker in combined_text for marker in ("kids", "family")):
            return "family with kids"
        if any(marker in combined_text for marker in ("retired", "senior")):
            return "retired couple"
        if "single" in combined_text:
            return "single homeowner"
        return "homeowner"

    @staticmethod
    def _default_home_ownership_years(difficulty: int) -> int:
        if difficulty <= 1:
            return 12
        if difficulty == 2:
            return 10
        if difficulty == 3:
            return 7
        if difficulty == 4:
            return 4
        return 2

    @staticmethod
    def _default_pest_history(difficulty: int, description: str) -> list[str]:
        pest_topic = PersonaEnricher._infer_pest_topic(description)
        if difficulty <= 2:
            return [f"rarely notices {pest_topic} issues around the home"]
        if difficulty == 3:
            return [f"had {pest_topic} last summer"]
        return [f"has dealt with recurring {pest_topic} recently", "has tried DIY fixes before"]

    @staticmethod
    def _default_price_sensitivity(difficulty: int) -> str:
        return "high" if difficulty >= 4 else "medium"

    @staticmethod
    def _default_communication_style(persona: HomeownerPersona, difficulty: int, description: str) -> str:
        combined_text = f"{persona.attitude.lower()} {description}"
        if difficulty <= 2:
            return "terse"
        if difficulty == 3:
            return "chatty"
        if any(marker in combined_text for marker in ("hostile", "angry", "annoyed", "irritated")):
            return "confrontational"
        return "analytical"

    @staticmethod
    def _infer_pest_topic(description: str) -> str:
        for keyword in ("ants", "spiders", "rodents", "mice", "rats", "termites", "wasps", "bugs", "pests"):
            if keyword in description:
                return keyword
        return "pest"


@dataclass
class SessionPromptContext:
    scenario: "Scenario | None"
    scenario_snapshot: ScenarioSnapshot
    persona: HomeownerPersona
    prompt_version: str | None = None
    conversation_prompt_content: str | None = None
    org_id: str | None = None
    territory_context: str | None = None
    company_context: str | None = None
    last_mb_plan: dict[str, Any] | None = None


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
            "Layer 2: persona fields: name, attitude, concerns, objection_queue, buy_likelihood, softening_condition, household_type, home_ownership_years, pest_history, price_sensitivity, communication_style.\n"
            "Layer 3: stage-aware instructions covering DOOR_OPEN, LISTENING, OBJECTING, CONSIDERING, CLOSE_WINDOW, ENDED.\n"
            "Layer 3B: emotional state machine framing with resistance level, objection pressure, active objections, and latent objections.\n"
            "Layer 3B-CONT: prior-turn behavioral register for tonal continuity.\n"
            "Layer 3C: precomputed behavioral directives for tone, length, and interruption posture.\n"
            "Layer 4: anti-pattern guards for aggressive reps, off-topic reps, and reps asking for hints or coaching.\n"
            "Layer 4B: edge case directives for missing intros, premature close attempts, repeated objection neglect, and spouse handoff moments.\n"
            "Layer 5: optional company context the homeowner may have seen before the interaction."
        )

    def build(
        self,
        scenario: "Scenario | None",
        persona: HomeownerPersona,
        stage: str,
        prompt_version: str | None = None,
        conversation_prompt_content: str | None = None,
        *,
        scenario_snapshot: ScenarioSnapshot | None = None,
        emotion: str | None = None,
        resistance_level: int | None = None,
        objection_pressure: int | None = None,
        active_objections: list[str] | None = None,
        queued_objections: list[str] | None = None,
        resolved_objections: list[str] | None = None,
        active_edge_cases: list[str] | None = None,
        company_context: str | None = None,
        behavioral_signals: list[str] | None = None,
        behavior_directives: BehaviorDirectives | None = None,
        last_mb_context: dict[str, Any] | None = None,
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
        triggered_edge_cases = active_edge_cases or []
        observed_signals = behavioral_signals or []
        emotional_guidance = EMOTION_RESPONSE_STYLE.get(emotional_state, EMOTION_RESPONSE_STYLE["neutral"])
        transition_hint = EMOTION_TRANSITION_HINTS.get(emotional_state, EMOTION_TRANSITION_HINTS["neutral"])
        response_cap = self._response_cap_rule(canonical_stage)
        internal_rule = self._internal_thought_rule(canonical_stage)
        sentence_rule = self._response_sentence_rule(behavior_directives)
        hard_rule_sentence = self._hard_rule_sentence(behavior_directives)
        hard_rule = (
            f"RULE: {hard_rule_sentence} {response_cap} "
            "You are a busy homeowner at your front door. Be blunt and brief."
        )

        layer_one = (
            "LAYER 1 - IMMERSION CONTRACT\n"
            "You are a real homeowner in a live door-to-door roleplay.\n"
            "Never break character.\n"
            f"{sentence_rule}\n"
            f"{response_cap}\n"
            "React only to what the rep actually says.\n"
            "Do not volunteer extra information the rep has not earned.\n"
            f"{internal_rule}"
        )
        layer_two_lines = [
            "LAYER 2 - PERSONA PROFILE",
            f"Scenario: {scenario_name}",
            f"Scenario difficulty: {difficulty}",
            f"Scenario description: {scenario_description}",
            f"Scenario stages: {scenario_stages}",
            f"Name: {persona.name}",
            f"Attitude: {persona.attitude}",
            f"Concerns: {', '.join(persona.concerns) or 'none listed'}",
            f"Objection queue: {', '.join(persona.objection_queue) or 'none listed'}",
            f"Buy likelihood: {persona.buy_likelihood}",
            f"Softening condition: {persona.softening_condition}",
        ]
        if persona.household_type:
            layer_two_lines.append(f"Household: {persona.household_type}")
        if persona.home_ownership_years is not None:
            layer_two_lines.append(f"Owned home for: {persona.home_ownership_years} years")
        if persona.pest_history:
            layer_two_lines.append(f"Pest history: {', '.join(persona.pest_history)}")
        if persona.price_sensitivity:
            layer_two_lines.append(f"Price sensitivity: {persona.price_sensitivity}")
        if persona.communication_style:
            layer_two_lines.append(
                f"Communication style: {persona.communication_style} - respond accordingly."
            )
        layer_two = "\n".join(layer_two_lines)
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
        layer_three_b_cont = None
        if last_mb_context:
            tone = str(last_mb_context.get("tone") or "measured")
            sentence_length = str(last_mb_context.get("sentence_length") or "medium")
            interruption_suffix = ", you interrupted" if last_mb_context.get("interruption_type") else ""
            layer_three_b_cont = (
                "LAYER 3B-CONT - PRIOR TURN REGISTER\n"
                f"In your last response: tone was {tone}, length was {sentence_length}{interruption_suffix}.\n"
                "Maintain tonal continuity unless the rep's behavior explicitly warrants a shift."
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
        layer_four_b = None
        if triggered_edge_cases:
            directives = [
                EDGE_CASE_DIRECTIVES[tag]
                for tag in triggered_edge_cases
                if tag in EDGE_CASE_DIRECTIVES
            ]
            if directives:
                layer_four_b = "LAYER 4B - EDGE CASE DIRECTIVES\n" + "\n".join(directives)
        layer_five_override = None
        if conversation_prompt_content and conversation_prompt_content.strip():
            layer_five_override = (
                "LAYER 5 - PROMPT OVERRIDE DIRECTIVES\n"
                "The following directives apply to this session and take precedence over general guidance above.\n"
                f"{conversation_prompt_content.strip()}"
            )
        layer_five = None
        if company_context and company_context.strip():
            layer_five = (
                "LAYER 5 - WHAT YOU MAY KNOW ABOUT THIS COMPANY\n"
                "Before they knocked, you may have encountered this company through a flyer, neighbor mention, "
                "or a quick online search. The following is what you found. Use it to make your objections "
                "specific and grounded - but speak naturally, not like you memorized it. Express uncertainty "
                "where appropriate ('I think I saw...', 'Someone mentioned...').\n\n"
                f"{company_context.strip()}"
            )
        version_line = f"Prompt version: {prompt_version or 'conversation_v1'}"
        parts = [version_line, layer_one, layer_two, layer_three, layer_three_b]
        if layer_three_b_cont:
            parts.append(layer_three_b_cont)
        if behavior_directives is not None:
            parts.append(behavior_directives.directive_text)
        parts.append(layer_four)
        if layer_four_b:
            parts.append(layer_four_b)
        if layer_five_override:
            parts.append(layer_five_override)
        if layer_five:
            parts.append(layer_five)
        parts.append(hard_rule)
        return "\n\n".join(parts)

    def build_from_scenario(self, scenario: "Scenario | None", stage: str, prompt_version: str | None = None) -> str:
        snapshot = ScenarioSnapshot.from_scenario(scenario)
        persona = PersonaEnricher.enrich(
            HomeownerPersona.from_payload(snapshot.persona_payload),
            snapshot.difficulty,
            snapshot.description,
        )
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

    def _response_cap_rule(self, canonical_stage: str) -> str:
        if canonical_stage in {"DOOR_OPEN", "ENDED"}:
            return "Maximum 10 words."
        if canonical_stage in {"CONSIDERING", "CLOSE_WINDOW"}:
            return "Maximum 30 words. You may think out loud briefly."
        return "Maximum 20 words."

    def _response_sentence_rule(self, behavior_directives: BehaviorDirectives | None) -> str:
        if behavior_directives is None:
            return "Respond in one sentence only."
        if behavior_directives.sentence_length == "short":
            return "Respond in one sentence only."
        if behavior_directives.sentence_length == "medium":
            return "Respond in no more than two sentences."
        return "Respond in no more than three sentences."

    def _hard_rule_sentence(self, behavior_directives: BehaviorDirectives | None) -> str:
        if behavior_directives is None:
            return "Respond in ONE sentence only."
        if behavior_directives.sentence_length == "short":
            return "Respond in ONE sentence only."
        if behavior_directives.sentence_length == "medium":
            return "Respond in no more than two sentences."
        return "Respond in no more than three sentences."

    def _internal_thought_rule(self, canonical_stage: str) -> str:
        if canonical_stage in {"CONSIDERING", "CLOSE_WINDOW"}:
            return "Brief natural thinking out loud is allowed. Do not expose coaching notes, scoring, or model behavior."
        return "Do not narrate internal thoughts, coaching notes, scoring, or model behavior."


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
        org_id: str | None = None,
        territory_context: str | None = None,
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
            org_id=org_id,
            territory_context=territory_context,
        )
        context.persona = self._enrich_persona(context.persona, context.scenario_snapshot)
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

    def bind_session_context(
        self,
        session_id: str,
        scenario: "Scenario | None",
        prompt_version: str | None = None,
        *,
        db: Session | None = None,
        org_id: str | None = None,
        rep_id: str | None = None,
        company_context: str | None = None,
    ) -> None:
        snapshot = ScenarioSnapshot.from_scenario(scenario)
        resolved_org_id = org_id
        if resolved_org_id is None and db is not None and rep_id:
            rep = db.scalar(select(User).where(User.id == rep_id))
            resolved_org_id = rep.org_id if rep is not None else None
        conversation_prompt_content = None
        if db is not None and prompt_version is not None:
            prompt_version_row = db.scalar(
                select(PromptVersion)
                .where(PromptVersion.prompt_type == "conversation")
                .where(PromptVersion.version == prompt_version)
            )
            if prompt_version_row is not None and prompt_version_row.content.strip():
                conversation_prompt_content = prompt_version_row.content
        context = SessionPromptContext(
            scenario=scenario,
            scenario_snapshot=snapshot,
            persona=HomeownerPersona.from_payload(snapshot.persona_payload),
            prompt_version=prompt_version,
            conversation_prompt_content=conversation_prompt_content,
            org_id=resolved_org_id,
            company_context=company_context,
            last_mb_plan=self._contexts.get(session_id).last_mb_plan if session_id in self._contexts else None,
        )
        context.persona = self._enrich_persona(context.persona, context.scenario_snapshot)
        self._contexts[session_id] = context

        if session_id not in self._states:
            self._states[session_id] = self._initialize_state_from_context(context)
            return

        state = self._states[session_id]
        state.persona_concerns = list(context.persona.concerns)

    def clear_session_context(self, session_id: str) -> None:
        self._contexts.pop(session_id, None)
        self._states.pop(session_id, None)

    def end_session(self, session_id: str) -> None:
        self.clear_session_context(session_id)

    def prepare_rep_turn(self, session_id: str, rep_text: str, db: Session | None = None) -> RepTurnPlan:
        state = self.get_state(session_id)
        context = self._contexts.get(session_id)

        stage_before = state.stage
        emotion_before = state.emotion
        objection_pressure_before = state.objection_pressure
        turn_number = state.rep_turns + 1
        active_edge_cases = self._detect_edge_cases(rep_text, state, turn_number)
        state.active_edge_cases = list(active_edge_cases)

        objection_tags = self._extract_objection_tags(rep_text, db=db)
        stage_after = self._detect_stage(rep_text, state, context, objection_tags=objection_tags)
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

        behavior_directives = self.compute_behavior_directives(
            emotion_before=emotion_before,
            emotion_after=state.emotion,
            behavioral_signals=assessment.signals,
            active_objections=list(state.active_objections),
        )
        system_prompt = self._build_system_prompt(
            stage_after=stage_after,
            session_id=session_id,
            behavior_directives=behavior_directives,
            last_mb_context=context.last_mb_plan if context is not None else None,
        )

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
            active_edge_cases=list(state.active_edge_cases),
            behavioral_signals=assessment.signals,
            objection_pressure_before=objection_pressure_before,
            objection_pressure_after=state.objection_pressure,
            resistance_level=state.resistance_level,
            behavior_directives=behavior_directives,
            system_prompt=system_prompt,
        )

    def mark_ai_turn(self, session_id: str) -> None:
        state = self.get_state(session_id)
        state.ai_turns += 1
        state.last_updated = datetime.now(timezone.utc)

    def update_last_mb_plan(self, session_id: str, plan: "MicroBehaviorPlan") -> None:
        context = self._contexts.get(session_id)
        if context is None:
            return
        context.last_mb_plan = {
            "tone": plan.tone,
            "sentence_length": plan.sentence_length,
            "interruption_type": plan.interruption_type,
            "behaviors": list(plan.behaviors),
            "realism_score": plan.realism_score,
        }

    def _initialize_state_from_context(self, context: SessionPromptContext) -> ConversationState:
        context.persona = self._enrich_persona(context.persona, context.scenario_snapshot)
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
            persona_concerns=list(context.persona.concerns),
            active_objections=active_objections,
            queued_objections=queued_objections,
            resolved_objections=[],
            objection_pressure=self._initial_objection_pressure(starting_emotion, active_count),
        )

    def compute_behavior_directives(
        self,
        *,
        emotion_before: str,
        emotion_after: str,
        behavioral_signals: list[str],
        active_objections: list[str],
    ) -> BehaviorDirectives:
        del active_objections

        tone = TONE_BY_TRANSITION.get((emotion_before, emotion_after))
        if tone is None:
            if "ignores_objection" in behavioral_signals and emotion_after in {"annoyed", "hostile"}:
                tone = "cutting"
            elif "acknowledges_concern" in behavioral_signals and emotion_after in {"curious", "interested"}:
                tone = "warming"
            else:
                tone = DEFAULT_TONE_BY_EMOTION.get(emotion_after, "measured")

        sentence_length = SENTENCE_LENGTH_BY_EMOTION.get(emotion_after, "medium")
        if "pushes_close" in behavioral_signals and emotion_after in {"annoyed", "hostile"}:
            sentence_length = "short"

        interruption_mode = emotion_after in {"annoyed", "hostile"} and any(
            signal in {"ignores_objection", "pushes_close", "dismisses_concern"}
            for signal in behavioral_signals
        )

        length_instruction = {
            "short": "One sentence only.",
            "medium": "Two sentences max.",
            "long": "Up to three sentences.",
        }.get(sentence_length, "Two sentences max.")
        interruption_instruction = ""
        if interruption_mode:
            interruption_instruction = (
                "\nInterrupt the rep: Begin your response cutting off whatever they were saying. "
                "Use an opener like 'Hold on,' or 'Wait,' or 'Look,'."
            )
        directive_text = (
            "LAYER 3C - BEHAVIORAL DIRECTIVES\n"
            f"Tone for this response: {tone}. Write in this register throughout.\n"
            f"Response length: {sentence_length}. {length_instruction}"
            f"{interruption_instruction}\n"
            "Do not exceed these constraints. The delivery will match exactly what you write."
        )

        return BehaviorDirectives(
            tone=tone,
            sentence_length=sentence_length,
            interruption_mode=interruption_mode,
            directive_text=directive_text,
        )

    def _build_system_prompt(
        self,
        stage_after: str,
        session_id: str | None = None,
        *,
        behavior_directives: BehaviorDirectives | None = None,
        last_mb_context: dict[str, Any] | None = None,
    ) -> str:
        context = self._contexts.get(session_id or "")
        state = self._states.get(session_id or "")
        resolved_last_mb_context = last_mb_context
        if resolved_last_mb_context is None and context is not None:
            resolved_last_mb_context = context.last_mb_plan

        if context is not None:
            prompt = self._prompt_builder.build(
                scenario=context.scenario,
                scenario_snapshot=context.scenario_snapshot,
                persona=context.persona,
                stage=stage_after,
                prompt_version=context.prompt_version,
                conversation_prompt_content=context.conversation_prompt_content,
                emotion=state.emotion if state is not None else "neutral",
                resistance_level=state.resistance_level if state is not None else 2,
                objection_pressure=state.objection_pressure if state is not None else 0,
                active_objections=list(state.active_objections) if state is not None else [],
                queued_objections=list(state.queued_objections) if state is not None else [],
                resolved_objections=list(state.resolved_objections) if state is not None else [],
                active_edge_cases=list(state.active_edge_cases) if state is not None else [],
                company_context=context.company_context,
                behavioral_signals=list(state.last_behavior_signals) if state is not None else [],
                behavior_directives=behavior_directives,
                last_mb_context=resolved_last_mb_context,
            )
            return prompt

        fallback_snapshot = ScenarioSnapshot()
        fallback_persona = self._enrich_persona(
            HomeownerPersona.from_payload(fallback_snapshot.persona_payload),
            fallback_snapshot,
        )
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
            active_edge_cases=list(state.active_edge_cases) if state is not None else [],
            behavioral_signals=list(state.last_behavior_signals) if state is not None else [],
            behavior_directives=behavior_directives,
            last_mb_context=resolved_last_mb_context,
        )

    def _enrich_persona(self, persona: HomeownerPersona, snapshot: ScenarioSnapshot) -> HomeownerPersona:
        return PersonaEnricher.enrich(persona, snapshot.difficulty, snapshot.description)

    def _detect_edge_cases(self, rep_text: str, state: ConversationState, turn_number: int) -> list[str]:
        text = rep_text.lower()
        edge_cases: list[str] = []

        if turn_number == 1 and not any(phrase in text for phrase in ("my name", "i'm", "i am", "with")):
            edge_cases.append("no_intro")

        if any(phrase in text for phrase in ("sign", "schedule", "appointment", "set up")) and self._is_pre_objection_stage(state.stage):
            edge_cases.append("premature_close")

        if state.ignored_objection_streak >= 3:
            edge_cases.append("ignored_objection_wall")

        concerns_text = " ".join(state.persona_concerns).lower()
        if (
            state.stage == "considering"
            and state.objection_pressure <= 2
            and any(marker in concerns_text for marker in ("husband", "wife", "partner", "spouse"))
        ):
            edge_cases.append("spouse_handoff_eligible")

        return edge_cases

    def _detect_stage(
        self,
        rep_text: str,
        state: ConversationState,
        context: SessionPromptContext | None,
        *,
        objection_tags: list[str] | None = None,
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
        if objection_tags:
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
        for tag, keywords in OBJECTION_KEYWORDS_FALLBACK.items():
            if any(keyword in text for keyword in keywords) and tag not in seeded:
                seeded.append(tag)

        return seeded

    def _extract_objection_tags(self, rep_text: str, db: Session | None = None) -> list[str]:
        text = rep_text.lower()
        objection_keywords = load_objection_keywords(db) if db is not None else OBJECTION_KEYWORDS_FALLBACK
        tags: list[str] = []
        for tag, keywords in objection_keywords.items():
            if any(keyword in text for keyword in keywords):
                tags.append(tag)
        return tags

    def _normalize_objection(self, value: str) -> str | None:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            return None
        if normalized in OBJECTION_KEYWORDS_FALLBACK:
            return normalized
        if normalized in {"monthly_bill", "monthly_cost", "per_month", "price_per_month"}:
            return "price_per_month"
        if normalized in {"contract", "under_contract", "locked_in_contract"}:
            return "locked_in_contract"
        if normalized in {"busy", "later", "not_now", "schedule", "timing"}:
            return "timing"
        if normalized in {"not_right_now", "come_back_later"}:
            return "not_right_now"
        if normalized in {"wife", "husband", "partner", "family", "spouse"}:
            return "spouse"
        if normalized in {"provider", "already", "current_service", "current_provider", "incumbent"}:
            return "incumbent_provider"
        if normalized in {"product_claims", "too_good_to_be_true", "skeptical_of_product"}:
            return "skeptical_of_product"
        if normalized in {"kids", "kid", "pet", "pets", "environment", "chemical", "safety"}:
            return "safety_environment"
        if normalized in {"value", "hidden_fees", "wasted_money", "risk"}:
            return "price"
        if normalized in {"need", "no_need", "dont_need", "don't_need"}:
            return "need"
        if normalized in {"landlord", "decision_maker", "decision_authority"}:
            return "decision_authority"
        return normalized

    def _find_stage(self, stages: list[str], markers: tuple[str, ...], *, fallback: str) -> str:
        for stage in stages:
            lowered = stage.lower()
            if any(marker in lowered for marker in markers):
                return stage
        return fallback

    def _is_pre_objection_stage(self, stage: str) -> bool:
        lowered = stage.lower()
        if any(marker in lowered for marker in ("objection", "consider", "close", "end")):
            return False
        return True

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
