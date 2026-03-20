from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import logging
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.org_prompt_config import OrgPromptConfig
from app.models.prompt_version import PromptVersion
from app.models.transcript import ObjectionType
from app.models.user import User
from app.services.micro_behavior_engine import (
    DEFAULT_TONE_BY_EMOTION,
    SENTENCE_LENGTH_BY_EMOTION,
    TONE_BY_TRANSITION,
)
from app.services.conversation_shared import OBJECTION_SEMANTIC_ANCHORS
from app.services.homeowner_signal_detector import HomeownerSignalDetector
from app.services.org_prompt_rendering import build_company_context_layer
from app.services.prompt_version_resolver import prompt_version_resolver

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
SYSTEM_PROMPT_SOFT_LIMIT_TOKENS = 1200
SYSTEM_PROMPT_HARD_LIMIT_TOKENS = 1600
TURN_HISTORY_LIMIT = 8
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
    "how's it going",
    "how are you doing",
    "how you doing",
    "what's up",
    "good to see",
    "hope you're doing well",
    "appreciate your time",
    "thanks for your time",
    "noticed",
    "neighbor",
    "local",
    "hope i'm not interrupting",
    "sorry to bother",
    "sorry to bug",
    "quick second",
)
# Phrases where the rep is using a nearby customer or neighbor as social proof.
SOCIAL_PROOF_PHRASES = (
    "house down the street",
    "down the street",
    "next door",
    "neighbor's house",
    "neighbor of yours",
    "your neighbor",
    "street over",
    "few houses down",
    "couple houses down",
    "house over",
    "homes in the area",
    "homes on your street",
    "in this neighborhood",
    "in the neighborhood",
    "in your neighborhood",
    "around here",
    "nearby homes",
    "nearby houses",
    "your area",
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
    "mentions_social_proof",
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
REP_MONOLOGUE_REACTION_INTENT = (
    "The rep has been talking for several turns without asking you anything. "
    "Real homeowners tune out when they're being lectured. "
    "Show disengagement: glance back inside, give a one-word response, "
    "or ask bluntly 'Is there a point to this?' "
    "Do not stay engaged as if the monologue is fine."
)
COMMUNICATION_STYLE_DIRECTIVES = {
    "terse": (
        "You speak in short bursts. Keep responses to one or two quick sentences and do not volunteer extra detail."
    ),
    "chatty": (
        "You are a talker. Use three to four natural sentences when the stage allows it, and you may riff briefly before circling back."
    ),
    "confrontational": (
        "You get right to the point and challenge claims directly. Use rhetorical pushback like 'Prove it.' when it fits."
    ),
    "analytical": (
        "You ask specific, probing follow-ups and want evidence, tradeoffs, and concrete details."
    ),
}
COMMUNICATION_STYLE_SENTENCE_LENGTH = {
    "terse": "short",
    "chatty": "long",
    "confrontational": "short",
    "analytical": "medium",
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
STANCE_ANCHOR_BLOCKLIST = {
    "firm_resistance": {"curious", "interested in", "open to"},
    "cautiously_open": {"skeptical of", "doubts", "refuses"},
    "low_friction_considering": {"refuses", "stonewalling", "not interested"},
    "aggressive_pushback": {"curious", "interested in", "open to"},
    "warming": {"skeptical of", "doubts", "refuses"},
    "resigned": {"still fighting", "raising new objections"},
}
POSTURE_FRICTION_RANGES = {
    "aggressive_pushback": (3, 5),
    "pushing_back": (3, 5),
    "shutting_down": (3, 5),
    "defensive": (2, 4),
    "guarded": (1, 3),
    "testing_claims": (1, 3),
    "reserved": (1, 3),
    "evaluating": (1, 3),
    "warming": (0, 2),
    "warming_up": (0, 2),
    "open": (0, 1),
    "resigned": (0, 3),
}
BOOKING_SCORE_THRESHOLDS = {
    "booking_possible": 6,
    "inspection_only": 3,
    "info_only": 1,
    "not_allowed": 0,
}
MAX_RAPPORT_SCORE = 6
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
DIRECT_QUESTION_RE = re.compile(r"\b(?:what|how|why)\b|\bcan i\b|\bwould it\b|\bdoes that\b")
OBJECTION_WORDING_VARIANTS: dict[str, tuple[str, ...]] = {
    "price": (
        "the monthly budget is already tight",
        "I am not seeing enough value for what it would cost",
        "I do not want another bill for something we might not need",
    ),
    "trust": (
        "I do not know enough about your company yet",
        "I need a better reason to trust who is showing up here",
        "you still have not shown me why your company is legit",
    ),
    "spouse": (
        "I do not make this call by myself",
        "my spouse would want to be part of this decision",
        "I would need to run this by my partner first",
    ),
    "incumbent_provider": (
        "we already have somebody handling this",
        "I am not looking to switch providers right now",
        "we are already covered, so I need a real reason to change",
    ),
    "safety_environment": (
        "I do not want harsh chemicals around the house",
        "I need to know this is safe around kids and pets",
        "I am careful about what gets put around this property",
    ),
    "timing": (
        "this is not a good time",
        "I am busy right now",
        "I do not have room for this today",
    ),
}
NEXT_STEP_ACCEPTABILITY_ORDER = {
    "not_allowed": 0,
    "info_only": 1,
    "inspection_only": 2,
    "booking_possible": 3,
}


def invalidate_objection_cache() -> None:
    global _OBJECTION_KEYWORDS_CACHE
    _OBJECTION_KEYWORDS_CACHE = None


def measure_prompt_tokens(text: str) -> int:
    try:
        import tiktoken
    except ImportError:
        return max(1, len(text.split())) if text.strip() else 0

    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


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


def _looks_like_direct_question_prompt(text: str, rep_text: str) -> bool:
    normalized_rep_text = str(rep_text or "")
    return "?" in normalized_rep_text or DIRECT_QUESTION_RE.search(text) is not None


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


def _next_rep_monologue_streak(
    *,
    current_streak: int,
    behavioral_signals: list[str],
    rep_text: str,
) -> int:
    if "invites_dialogue" in behavioral_signals or "?" in rep_text:
        return 0
    return min(5, current_streak + 1)


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
    emotion_momentum: int = 0
    resistance_level: int = 2
    rep_turns: int = 0
    ai_turns: int = 0
    rapport_score: int = 0
    turns_since_positive_signal: int = 0
    persona_concerns: list[str] = field(default_factory=list)
    active_objections: list[str] = field(default_factory=list)
    queued_objections: list[str] = field(default_factory=list)
    resolved_objections: list[str] = field(default_factory=list)
    active_edge_cases: list[str] = field(default_factory=list)
    objection_pressure: int = 0
    ignored_objection_streak: int = 0
    rep_monologue_streak: int = 0
    interruption_count: int = 0
    objection_raise_count: dict[str, int] = field(default_factory=dict)
    visited_stages: set[str] = field(default_factory=set)
    pending_test_question: str | None = None
    last_behavior_signals: list[str] = field(default_factory=list)
    reaction_intent: str = "React briefly and keep the homeowner grounded."
    homeowner_posture: str = "reserved"
    objection_resolution_progress: dict[str, int] = field(default_factory=dict)
    objection_status_map: dict[str, str] = field(default_factory=dict)
    objection_wording_cursor: dict[str, int] = field(default_factory=dict)
    last_turn_analysis: dict[str, Any] | None = None
    last_response_plan: dict[str, Any] | None = None
    system_prompt_token_count: int = 0
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
    reaction_intent: str
    homeowner_posture: str
    behavior_directives: "BehaviorDirectives"
    turn_analysis: "TurnAnalysis"
    response_plan: "HomeownerResponsePlan"
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


@dataclass
class PersonaRealismPack:
    disclosure_style: str
    interruption_tolerance: str
    skepticism_threshold: str
    softening_speed: str
    willingness_to_book: str
    detail_preference: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "disclosure_style": self.disclosure_style,
            "interruption_tolerance": self.interruption_tolerance,
            "skepticism_threshold": self.skepticism_threshold,
            "softening_speed": self.softening_speed,
            "willingness_to_book": self.willingness_to_book,
            "detail_preference": self.detail_preference,
        }


@dataclass
class ConversationTurnRecord:
    speaker: str
    text: str
    stage: str
    emotion: str | None = None


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
class ConversationContext:
    scenario: "Scenario | None"
    scenario_snapshot: ScenarioSnapshot
    persona: HomeownerPersona
    prompt_version: str | None = None
    conversation_prompt_content: str | None = None
    analyzer_prompt_version: str | None = None
    analyzer_prompt_content: str | None = None
    org_id: str | None = None
    org_config: OrgPromptConfig | None = None
    territory_context: str | None = None
    static_company_context: str | None = None
    company_context: str | None = None
    objection_brief_cache: dict[str, str] = field(default_factory=dict)
    turn_history: list[ConversationTurnRecord] = field(default_factory=list)
    last_mb_plan: dict[str, Any] | None = None
    realism_pack: PersonaRealismPack | None = None
    prompt_static_layers: dict[str, str] = field(default_factory=dict)


SessionPromptContext = ConversationContext


@dataclass
class BehaviorAssessment:
    signals: list[str]
    resolved_objections: list[str]


@dataclass
class TurnAnalysis:
    stage_intent: str
    referenced_concerns: list[str]
    addressed_objections: list[str]
    resolved_objections: list[str]
    partially_addressed_objections: list[str]
    objection_status: str
    objection_status_map: dict[str, str]
    behavioral_signals: list[str]
    rapport_delta: int
    pressure_delta: int
    recommended_next_objection: str | None
    reaction_intent: str
    homeowner_posture: str
    homeowner_signals: list[str]
    direct_response_required: bool
    confidence: float
    pending_test_question: str | None = None
    missed_pending_test: bool = False
    resolution_progress: dict[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "stage_intent": self.stage_intent,
            "referenced_concerns": list(self.referenced_concerns),
            "addressed_objections": list(self.addressed_objections),
            "resolved_objections": list(self.resolved_objections),
            "partially_addressed_objections": list(self.partially_addressed_objections),
            "objection_status": self.objection_status,
            "objection_status_map": dict(self.objection_status_map),
            "behavioral_signals": list(self.behavioral_signals),
            "rapport_delta": self.rapport_delta,
            "pressure_delta": self.pressure_delta,
            "recommended_next_objection": self.recommended_next_objection,
            "reaction_intent": self.reaction_intent,
            "homeowner_posture": self.homeowner_posture,
            "homeowner_signals": list(self.homeowner_signals),
            "direct_response_required": self.direct_response_required,
            "confidence": self.confidence,
            "pending_test_question": self.pending_test_question,
            "missed_pending_test": self.missed_pending_test,
            "resolution_progress": dict(self.resolution_progress),
        }


@dataclass
class HomeownerResponsePlan:
    must_answer: bool
    reaction_goal: str
    stance: str
    friction_level: int
    allowed_new_objection: str | None
    semantic_anchors: list[str]
    next_step_acceptability: str
    fast_path_prompt: bool = False
    wording_rotation_hint: str | None = None
    selected_brief_keys: list[str] = field(default_factory=list)
    friction_gates: dict[str, bool] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "must_answer": self.must_answer,
            "reaction_goal": self.reaction_goal,
            "stance": self.stance,
            "friction_level": self.friction_level,
            "allowed_new_objection": self.allowed_new_objection,
            "semantic_anchors": list(self.semantic_anchors),
            "next_step_acceptability": self.next_step_acceptability,
            "fast_path_prompt": self.fast_path_prompt,
            "wording_rotation_hint": self.wording_rotation_hint,
            "selected_brief_keys": list(self.selected_brief_keys),
            "friction_gates": dict(self.friction_gates),
        }


class ConversationTurnAnalyzer:
    def __init__(self) -> None:
        self._homeowner_signal_detector = HomeownerSignalDetector()

    def analyze(
        self,
        *,
        rep_text: str,
        state: ConversationState,
        context: SessionPromptContext | None,
        db: Session | None = None,
    ) -> TurnAnalysis:
        latest_homeowner_text = self._latest_homeowner_text(context)
        homeowner_signal_snapshot = self._homeowner_signal_detector.detect(latest_homeowner_text)
        pending_test_question = state.pending_test_question or homeowner_signal_snapshot.pending_test_question
        text = rep_text.lower()
        referenced_concerns = self._extract_objection_tags(text, db=db)
        behavioral_signals = self._evaluate_rep_behavior(text, rep_text)
        pending_test_addressed = self._check_pending_test(
            pending_test_question=pending_test_question,
            rep_text=rep_text,
            behavioral_signals=behavioral_signals,
        )
        missed_pending_test = bool(pending_test_question) and not pending_test_addressed
        if missed_pending_test:
            behavioral_signals = self._dedupe([*behavioral_signals, "ignores_objection"])
        elif pending_test_question:
            pending_test_question = None
        addressed_objections = self._addressed_objections(
            referenced_concerns=referenced_concerns,
            active_objections=list(state.active_objections),
            queued_objections=list(state.queued_objections),
            behavioral_signals=behavioral_signals,
        )
        objection_status_map, resolved, partial, progress = self._classify_objection_statuses(
            state=state,
            active_objections=list(state.active_objections),
            addressed_objections=addressed_objections,
            behavioral_signals=behavioral_signals,
        )
        objection_status = self._overall_objection_status(objection_status_map, resolved, partial)
        if missed_pending_test:
            objection_status = "ignored"
        helpful_count = sum(1 for signal in behavioral_signals if signal in HELPFUL_SIGNALS)
        harmful_count = sum(1 for signal in behavioral_signals if signal in HARMFUL_SIGNALS)
        rep_monologue_streak = _next_rep_monologue_streak(
            current_streak=state.rep_monologue_streak,
            behavioral_signals=behavioral_signals,
            rep_text=rep_text,
        )
        rapport_delta = (
            (1 if "builds_rapport" in behavioral_signals else 0)
            + (1 if "personalizes_pitch" in behavioral_signals else 0)
            - (1 if "dismisses_concern" in behavioral_signals else 0)
        )
        pressure_delta = self._pressure_delta(
            behavioral_signals=behavioral_signals,
            objection_status=objection_status,
            resolved_count=len(resolved),
            partial_count=len(partial),
            active_objection_count=len(state.active_objections),
        )
        recommended_next_objection = self._recommended_next_objection(
            state=state,
            resolved_objections=resolved,
            partial_objections=partial,
            objection_status_map=objection_status_map,
            referenced_concerns=referenced_concerns,
            behavioral_signals=behavioral_signals,
        )
        stage_intent = self._stage_intent(
            text=text,
            referenced_concerns=referenced_concerns,
            state=state,
            context=context,
        )
        direct_response_required = _looks_like_direct_question_prompt(text, rep_text)
        homeowner_posture = self._homeowner_posture(
            current_emotion=state.emotion,
            helpful_count=helpful_count,
            harmful_count=harmful_count,
            objection_status=objection_status,
            pressure_delta=pressure_delta,
            rep_monologue_streak=rep_monologue_streak,
        )
        reaction_intent = self._reaction_intent(
            direct_response_required=direct_response_required,
            rep_monologue_streak=rep_monologue_streak,
            stage_intent=stage_intent,
            objection_status=objection_status,
            resolved_objections=resolved,
            recommended_next_objection=recommended_next_objection,
            behavioral_signals=behavioral_signals,
            homeowner_signals=homeowner_signal_snapshot.signals,
            pending_test_question=pending_test_question,
            missed_pending_test=missed_pending_test,
        )
        confidence = min(
            0.95,
            0.55
            + (0.04 * len(behavioral_signals))
            + (0.05 * len(referenced_concerns))
            + (0.03 * len(resolved))
            + (0.02 * len(homeowner_signal_snapshot.signals)),
        )
        return TurnAnalysis(
            stage_intent=stage_intent,
            referenced_concerns=referenced_concerns,
            addressed_objections=addressed_objections,
            resolved_objections=resolved,
            partially_addressed_objections=partial,
            objection_status=objection_status,
            objection_status_map=objection_status_map,
            behavioral_signals=behavioral_signals,
            rapport_delta=rapport_delta,
            pressure_delta=pressure_delta,
            recommended_next_objection=recommended_next_objection,
            reaction_intent=reaction_intent,
            homeowner_posture=homeowner_posture,
            homeowner_signals=homeowner_signal_snapshot.signals,
            direct_response_required=direct_response_required,
            confidence=round(confidence, 3),
            pending_test_question=pending_test_question,
            missed_pending_test=missed_pending_test,
            resolution_progress=progress,
        )

    def _extract_objection_tags(self, text: str, *, db: Session | None) -> list[str]:
        objection_keywords = load_objection_keywords(db) if db is not None else OBJECTION_KEYWORDS_FALLBACK
        tags: list[str] = []
        for tag, keywords in objection_keywords.items():
            if any(keyword in text for keyword in keywords):
                tags.append(tag)
        return self._dedupe(tags)

    def _evaluate_rep_behavior(self, text: str, rep_text: str) -> list[str]:
        signals: list[str] = []
        if any(phrase in text for phrase in ACKNOWLEDGEMENT_PHRASES):
            signals.append("acknowledges_concern")
        if any(phrase in text for phrase in RAPPORT_PHRASES):
            signals.append("builds_rapport")
        if any(phrase in text for phrase in SOCIAL_PROOF_PHRASES):
            # Rep is name-dropping a nearby customer or neighbor — distinct from
            # generic rapport; the homeowner should react to the specific claim.
            signals.append("mentions_social_proof")
        if any(phrase in text for phrase in VALUE_PHRASES):
            signals.append("explains_value")
        if any(phrase in text for phrase in PROOF_PHRASES):
            signals.append("provides_proof")
        if any(phrase in text for phrase in LOW_PRESSURE_PHRASES):
            signals.append("reduces_pressure")
        if any(phrase in text for phrase in PERSONALIZATION_PHRASES):
            signals.append("personalizes_pitch")
        if _looks_like_direct_question_prompt(text, rep_text):
            signals.append("invites_dialogue")
        if any(phrase in text for phrase in PRESSURE_PHRASES):
            signals.append("pushes_close")
        if any(phrase in text for phrase in DISMISSIVE_PHRASES):
            signals.append("dismisses_concern")
        if not signals:
            signals.append("neutral_delivery")
        return self._dedupe(signals)

    def _addressed_objections(
        self,
        *,
        referenced_concerns: list[str],
        active_objections: list[str],
        queued_objections: list[str],
        behavioral_signals: list[str],
    ) -> list[str]:
        active_or_queued = list(dict.fromkeys([*active_objections, *queued_objections]))
        addressed = [tag for tag in referenced_concerns if tag in active_or_queued]
        if not addressed and len(active_objections) == 1 and "acknowledges_concern" in behavioral_signals:
            addressed = [active_objections[0]]
        return self._dedupe(addressed)

    def _classify_objection_statuses(
        self,
        *,
        state: ConversationState,
        active_objections: list[str],
        addressed_objections: list[str],
        behavioral_signals: list[str],
    ) -> tuple[dict[str, str], list[str], list[str], dict[str, int]]:
        objection_status_map: dict[str, str] = {}
        resolved: list[str] = []
        partial: list[str] = []
        progress: dict[str, int] = dict(state.objection_resolution_progress)
        harmful = any(signal in {"pushes_close", "dismisses_concern", "ignores_objection"} for signal in behavioral_signals)

        for tag in active_objections:
            direct_match = tag in addressed_objections
            increment = self._resolution_increment(tag=tag, direct_match=direct_match, behavioral_signals=behavioral_signals)
            previous_progress = int(progress.get(tag, 0) or 0)
            updated_progress = max(0, min(4, previous_progress + increment - (1 if "dismisses_concern" in behavioral_signals else 0)))
            progress[tag] = updated_progress

            if direct_match and updated_progress >= 3 and not harmful:
                objection_status_map[tag] = "resolved"
                resolved.append(tag)
                continue
            if direct_match and updated_progress >= 2:
                objection_status_map[tag] = "partial"
                partial.append(tag)
                continue
            if direct_match:
                objection_status_map[tag] = "partial"
                partial.append(tag)
                continue
            if harmful:
                objection_status_map[tag] = "ignored"
            else:
                objection_status_map[tag] = "carried"

        return objection_status_map, self._dedupe(resolved), self._dedupe(partial), progress

    def _resolution_increment(self, *, tag: str, direct_match: bool, behavioral_signals: list[str]) -> int:
        increment = 0
        if direct_match:
            increment += 1
        if "acknowledges_concern" in behavioral_signals:
            increment += 1
        required_signals = OBJECTION_RESOLUTION_SIGNALS.get(tag, frozenset())
        increment += sum(1 for signal in required_signals if signal in behavioral_signals)
        if "dismisses_concern" in behavioral_signals:
            increment -= 1
        return increment

    def _overall_objection_status(
        self,
        objection_status_map: dict[str, str],
        resolved: list[str],
        partial: list[str],
    ) -> str:
        if any(status == "ignored" for status in objection_status_map.values()):
            return "ignored"
        if resolved and not partial and all(status == "resolved" for status in objection_status_map.values()):
            return "resolved"
        if resolved or partial:
            return "partial"
        if objection_status_map:
            return "carried"
        return "none"

    def _pressure_delta(
        self,
        *,
        behavioral_signals: list[str],
        objection_status: str,
        resolved_count: int,
        partial_count: int,
        active_objection_count: int,
    ) -> int:
        delta = 0
        for signal in behavioral_signals:
            if signal in {"acknowledges_concern", "builds_rapport", "explains_value", "provides_proof", "reduces_pressure", "personalizes_pitch", "invites_dialogue"}:
                delta -= 1
            elif signal == "pushes_close":
                delta += 2
            elif signal in {"dismisses_concern", "ignores_objection"}:
                delta += 2
            elif signal == "high_difficulty_backfire":
                delta += 1
        if objection_status == "ignored":
            delta += 1
        if resolved_count:
            delta -= resolved_count
        if partial_count and not resolved_count:
            delta -= 1
        if active_objection_count >= 2:
            delta += 1
        return delta

    def _recommended_next_objection(
        self,
        *,
        state: ConversationState,
        resolved_objections: list[str],
        partial_objections: list[str],
        objection_status_map: dict[str, str],
        referenced_concerns: list[str],
        behavioral_signals: list[str],
    ) -> str | None:
        for tag in state.active_objections:
            if tag in resolved_objections:
                continue
            status = objection_status_map.get(tag)
            if status in {"ignored", "carried", "partial"}:
                return tag
        if state.queued_objections and any(signal in {"pushes_close", "dismisses_concern"} for signal in behavioral_signals):
            return state.queued_objections[0]
        for tag in referenced_concerns:
            if tag not in resolved_objections:
                return tag
        if state.queued_objections:
            return state.queued_objections[0]
        if partial_objections:
            return partial_objections[0]
        return None

    def _stage_intent(
        self,
        *,
        text: str,
        referenced_concerns: list[str],
        state: ConversationState,
        context: SessionPromptContext | None,
    ) -> str:
        del context
        if any(phrase in text for phrase in ("have a good one", "no worries", "take care", "i'll let you go")):
            return "end_conversation"
        if any(phrase in text for phrase in ("sign", "schedule", "appointment", "start service", "next step", "today")):
            return "attempt_close"
        if referenced_concerns or state.active_objections:
            return "handle_objection"
        if state.stage == DEFAULT_STAGE and any(word in text for word in ("hi", "hello", "name", "company", "with")):
            return "advance_pitch"
        if any(phrase in text for phrase in ("would it make sense", "if i could", "based on that", "fair enough")):
            return "advance_considering"
        return "hold_stage"

    def _homeowner_posture(
        self,
        *,
        current_emotion: str,
        helpful_count: int,
        harmful_count: int,
        objection_status: str,
        pressure_delta: int,
        rep_monologue_streak: int = 0,
    ) -> str:
        if rep_monologue_streak >= 5:
            return "defensive"
        if harmful_count >= 2 or objection_status == "ignored" or pressure_delta >= 2:
            return "pushing_back"
        if helpful_count >= 2 and objection_status in {"partial", "resolved"}:
            return "testing_claims"
        posture_by_emotion = {
            "hostile": "shutting_down",
            "annoyed": "defensive",
            "skeptical": "guarded",
            "neutral": "reserved",
            "curious": "evaluating",
            "interested": "warming_up",
        }
        return posture_by_emotion.get(current_emotion, "reserved")

    def _reaction_intent(
        self,
        *,
        direct_response_required: bool,
        rep_monologue_streak: int,
        stage_intent: str,
        objection_status: str,
        resolved_objections: list[str],
        recommended_next_objection: str | None,
        behavioral_signals: list[str],
        homeowner_signals: list[str],
        pending_test_question: str | None,
        missed_pending_test: bool,
    ) -> str:
        del homeowner_signals
        if rep_monologue_streak >= 3:
            return REP_MONOLOGUE_REACTION_INTENT
        if stage_intent == "attempt_close" and objection_status != "resolved":
            return "Push back on the closing pressure before discussing next steps."
        if missed_pending_test and pending_test_question:
            return (
                f"The rep dodged your test question: '{pending_test_question}'. "
                "Bring it back directly and make them answer it before moving on."
            )
        if objection_status == "ignored":
            return "React directly, then restate the unresolved concern without softening."
        if resolved_objections and recommended_next_objection:
            return f"React to the rep first, then surface {recommended_next_objection.replace('_', ' ')} if it still matters."
        if resolved_objections:
            return "Answer directly and test the offer with a practical homeowner follow-up."
        if "mentions_social_proof" in behavioral_signals:
            return (
                "The rep just name-dropped a neighbor or nearby house. React to that specific claim first — "
                "a real homeowner would acknowledge it (curious, skeptical, or dismissive) before anything else. "
                "Don't skip past it. Something like 'Oh yeah? The Joneses?' or 'Hm, okay, and what were you doing for them?' "
                "is natural. Then, if relevant, raise your first concern."
            )
        if "provides_proof" in behavioral_signals or "explains_value" in behavioral_signals:
            return "Acknowledge the new detail briefly, then pressure-test it with a natural follow-up."
        if direct_response_required:
            return "Answer the rep's latest question first before adding any new concern."
        return "React to the latest rep point before introducing any new objection."

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def _latest_homeowner_text(self, context: SessionPromptContext | None) -> str | None:
        if context is None:
            return None
        for turn in reversed(context.turn_history):
            if turn.speaker == "homeowner":
                return turn.text
        return None

    def _check_pending_test(
        self,
        *,
        pending_test_question: str | None,
        rep_text: str,
        behavioral_signals: list[str],
    ) -> bool:
        if not pending_test_question:
            return True
        rep_text_lower = rep_text.lower()
        keywords = [
            token
            for token in re.split(r"[^a-z0-9]+", pending_test_question.lower())
            if len(token) > 3
        ]
        if any(keyword in rep_text_lower for keyword in keywords):
            return True
        return "provides_proof" in behavioral_signals and any(
            keyword in {"insured", "licensed", "reviews", "proof", "guarantee"}
            for keyword in keywords
        )


class PromptBuilder:
    STAGE_GUIDANCE = {
        "DOOR_OPEN": (
            "You just opened your front door to a stranger. You don't know yet why they're here. "
            "If the rep simply greets you ('hey how's it going', 'hi there', 'good afternoon'), "
            "respond the way any normal person would — brief, casual, slightly guarded: "
            "'Good, can I help you?' or 'Hey, what's up?' or 'Yeah?' or 'Fine, what can I do for you?' "
            "Do NOT immediately interrogate their purpose before they've introduced themselves. "
            "Let them speak first. If they mention a neighbor or nearby house, react to that specifically "
            "before deciding how guarded to be — that's a concrete claim you'd notice. "
            "Do not manufacture objections yet; the pitch hasn't started. "
            "Turn 1 is pure reaction to the opener, not a chance to preload price, trust, or closing resistance."
        ),
        "LISTENING": (
            "The rep is now pitching. Listen to what they actually say and react to the specific content. "
            "If they say something vague or generic, call it out with a short question. "
            "If they mention a real detail (neighbor, price, specific service), react to that detail. "
            "Do not give a scripted objection — respond to what was literally just said."
        ),
        "OBJECTING": (
            "Raise the next realistic objection from your queue. "
            "Force the rep to address the actual concern instead of sliding past it."
        ),
        "CONSIDERING": (
            "You are not sold, but you have not walked away either. Something the rep said opened a small crack. "
            "Behave like a real person who is genuinely undecided: ask a clarifying question, stall with 'I'd have to think about it', "
            "or float a soft objection that is not a hard no. "
            "Do NOT cave just because the rep asked nicely. The rep still needs to answer the specific thing that is holding you back. "
            "Common realistic responses at this stage: 'What does the monthly cost actually look like?', "
            "'I'd want to run it by my wife first.', 'How long have you guys been operating around here?', "
            "'I mean, maybe - what would the process look like?' "
            "Only warm up further if the rep gives a concrete, credible answer to your last question. "
            "A vague or pushy answer should snap you back toward skeptical."
        ),
        "CLOSE_WINDOW": (
            "The rep is trying to close. You need a real reason to say yes - not enthusiasm, not pressure. "
            "Default to a soft decline or a deferral unless the rep has genuinely earned your trust: "
            "'Let me think about it.', 'I'll talk to my wife and we'll reach out.', 'Not today, but maybe.' "
            "If the rep is using urgency pressure ('only today', 'right now'), resist harder - real homeowners hate that. "
            "The only things that can move you to yes at this stage are that all your major objections have been addressed specifically, "
            "the rep has been calm and credible throughout, and the ask is low-friction like a free inspection or quick look. "
            "If all three are true, it is realistic to agree to a low-commitment next step. "
            "If one or more is missing, give a polite but firm deferral and do not reopen it."
        ),
        "RECOVERY": (
            "The rep just did something that de-escalated the conversation after a difficult moment - "
            "they acknowledged your concern, backed off pressure, or gave a specific credible answer. "
            "React to that. Do not immediately forgive everything, but show that you noticed: "
            "'Okay, that's actually a fair point.', 'Alright, I can hear that.', 'That makes more sense.' "
            "You are not fully back onside yet - stay slightly guarded - but the tone softens measurably. "
            "Do not raise a new objection this turn unless the rep's recovery was unconvincing."
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
        "recovery": "RECOVERY",
        "ended": "ENDED",
    }

    def __init__(self) -> None:
        self.last_token_count = 0

    @classmethod
    def template_blueprint(cls) -> str:
        return (
            "Layer 1: hardcoded homeowner immersion contract.\n"
            "Layer 2: persona fields: name, attitude, concerns, objection_queue, buy_likelihood, softening_condition, household_type, home_ownership_years, pest_history, price_sensitivity, communication_style.\n"
            "Layer 2B: stable realism traits controlling disclosure style, skepticism threshold, and willingness to book.\n"
            "Layer 3: stage-aware instructions covering DOOR_OPEN, LISTENING, OBJECTING, CONSIDERING, CLOSE_WINDOW, RECOVERY, ENDED.\n"
            "Layer 3A: recent conversation memory and latest rep utterance.\n"
            "Layer 3A-PLAN: deterministic response-plan contract covering must-answer behavior, friction gates, stance, and semantic anchors.\n"
            "Layer 3B: emotional state machine framing with resistance level, objection pressure, active objections, and latent objections.\n"
            "Layer 3B-CONT: prior-turn behavioral register for tonal continuity.\n"
            "Layer 3C: precomputed behavioral directives for tone, length, and interruption posture.\n"
            "Layer 4: anti-pattern guards for aggressive reps, off-topic reps, and reps asking for hints or coaching.\n"
            "Layer 4B: edge case directives for missing intros, premature close attempts, repeated objection neglect, and spouse handoff moments.\n"
            "Layer 5: optional company context the homeowner may have seen before the interaction."
        )

    def build_static_layers(
        self,
        *,
        scenario: "Scenario | None",
        scenario_snapshot: ScenarioSnapshot,
        persona: HomeownerPersona,
        org_config: OrgPromptConfig | None,
        realism_pack: PersonaRealismPack | None,
    ) -> dict[str, str]:
        scenario_stages = ", ".join(scenario_snapshot.stages) or ", ".join(DEFAULT_STAGE_SEQUENCE)
        stage_lines = "\n".join(
            f"- {stage_name}: {instruction}"
            for stage_name, instruction in self.STAGE_GUIDANCE.items()
        )
        layer_zero = build_company_context_layer(org_config)
        layer_two_lines = [
            "LAYER 2 - PERSONA PROFILE",
            f"Scenario: {scenario_snapshot.name}",
            f"Scenario difficulty: {scenario_snapshot.difficulty}",
            f"Scenario description: {scenario_snapshot.description}",
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
            layer_two_lines.append(f"Communication style: {persona.communication_style} - respond accordingly.")
        layer_two = "\n".join(layer_two_lines)

        layer_two_b = None
        if realism_pack is not None:
            layer_two_b = (
                "LAYER 2B - STABLE REALISM TRAITS\n"
                f"Disclosure style: {realism_pack.disclosure_style}.\n"
                f"Interruption tolerance: {realism_pack.interruption_tolerance}.\n"
                f"Skepticism threshold: {realism_pack.skepticism_threshold}.\n"
                f"Softening speed: {realism_pack.softening_speed}.\n"
                f"Willingness to book: {realism_pack.willingness_to_book}.\n"
                f"Detail preference: {realism_pack.detail_preference}."
            )
        return {
            "layer_zero": layer_zero,
            "layer_two": layer_two,
            "layer_two_b": layer_two_b or "",
            "stage_lines": stage_lines,
            "scenario_stages": scenario_stages,
        }

    def build(
        self,
        scenario: "Scenario | None",
        persona: HomeownerPersona,
        stage: str,
        prompt_version: str | None = None,
        conversation_prompt_content: str | None = None,
        org_config: OrgPromptConfig | None = None,
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
        recent_turns: list[ConversationTurnRecord] | None = None,
        latest_rep_text: str | None = None,
        reaction_intent: str | None = None,
        homeowner_posture: str | None = None,
        response_plan: HomeownerResponsePlan | None = None,
        fatigue_directive: str | None = None,
        realism_pack: PersonaRealismPack | None = None,
        static_layers: dict[str, str] | None = None,
    ) -> str:
        snapshot = scenario_snapshot or ScenarioSnapshot.from_scenario(scenario)
        canonical_stage = self._normalize_stage(stage)
        scenario_name = snapshot.name
        stage_instruction = self.STAGE_GUIDANCE.get(canonical_stage, self.STAGE_GUIDANCE["LISTENING"])
        resolved_static_layers = static_layers or self.build_static_layers(
            scenario=scenario,
            scenario_snapshot=snapshot,
            persona=persona,
            org_config=org_config,
            realism_pack=realism_pack,
        )
        stage_lines = resolved_static_layers.get("stage_lines") or ""
        emotional_state = emotion or "neutral"
        unresolved_objections = active_objections or []
        latent_objections = queued_objections or []
        cleared_objections = resolved_objections or []
        triggered_edge_cases = active_edge_cases or []
        observed_signals = behavioral_signals or []
        emotional_guidance = EMOTION_RESPONSE_STYLE.get(emotional_state, EMOTION_RESPONSE_STYLE["neutral"])
        transition_hint = EMOTION_TRANSITION_HINTS.get(emotional_state, EMOTION_TRANSITION_HINTS["neutral"])
        posture_text = homeowner_posture or "reserved"
        fast_path_prompt = bool(response_plan.fast_path_prompt) if response_plan is not None else False
        response_cap = self._response_cap_rule(canonical_stage)
        internal_rule = self._internal_thought_rule(canonical_stage)
        sentence_rule = self._response_sentence_rule(behavior_directives)
        hard_rule_sentence = self._hard_rule_sentence(behavior_directives)
        response_plan_rule = (
            "Answer the rep's latest point first, preserve any unresolved concern memory, and only introduce a new move if the response plan explicitly allows it."
        )
        hard_rule_parts = [f"RULE: {hard_rule_sentence}"]
        if response_cap:
            hard_rule_parts.append(response_cap)
        hard_rule_parts.append("You are a busy homeowner at your front door. Be blunt and brief.")
        hard_rule_parts.append(response_plan_rule)
        hard_rule = " ".join(hard_rule_parts)
        layer_zero = resolved_static_layers.get("layer_zero")

        layer_one_lines = [
            "LAYER 1 - IMMERSION CONTRACT",
            "You are a real homeowner in a live door-to-door roleplay.",
            "Never break character.",
            sentence_rule,
        ]
        if response_cap:
            layer_one_lines.append(response_cap)
        layer_one_lines.extend(
            [
                "React only to what the rep ACTUALLY says — not what you expect them to say.",
                "Your first sentence must directly answer or react to the rep's latest point.",
                "If the rep just greeted you and hasn't pitched yet, respond like a normal person answering "
                "their door — brief and slightly guarded, not interrogating. Don't jump to 'what are you selling' "
                "before they've had a chance to introduce themselves.",
                "If the rep mentions something specific (a neighbor, a house nearby, a name), acknowledge that "
                "specific thing before adding any resistance. Real people notice and react to concrete details.",
                "Do not volunteer extra information the rep has not earned.",
                "Carry unresolved concerns forward naturally instead of forgetting them.",
                internal_rule,
            ]
        )
        layer_one = "\n".join(layer_one_lines)
        layer_two = resolved_static_layers.get("layer_two") or ""
        layer_two_b = resolved_static_layers.get("layer_two_b") or None
        layer_three = (
            "LAYER 3 - STAGE INSTRUCTIONS\n"
            f"Current stage: {canonical_stage}\n"
            f"Current stage behavior: {stage_instruction}\n"
            "Stage guidance:\n"
            f"{stage_lines}"
        )
        layer_three_a = None
        rendered_history = self._render_recent_turns(recent_turns or [], limit=4 if fast_path_prompt else TURN_HISTORY_LIMIT)
        if latest_rep_text or rendered_history or reaction_intent:
            history_lines = ["LAYER 3A - RECENT CONVERSATION MEMORY"]
            history_lines.append(f"Homeowner posture entering this turn: {posture_text}.")
            if reaction_intent:
                history_lines.append(f"Immediate reaction intent: {reaction_intent}")
            if rendered_history:
                history_lines.append("Recent turns:")
                history_lines.append(rendered_history)
            if latest_rep_text:
                history_lines.append(f"Latest rep utterance to answer first: {latest_rep_text.strip()}")
            layer_three_a = "\n".join(history_lines)
        layer_three_a_plan = None
        if response_plan is not None:
            plan_lines = [
                "LAYER 3A-PLAN - RESPONSE PLAN",
                f"Must answer first: {'yes' if response_plan.must_answer else 'no'}",
                f"Reaction goal: {response_plan.reaction_goal}",
                f"Stance this turn: {response_plan.stance}",
                f"Friction level: {response_plan.friction_level}/5",
                f"Allowed new objection after reacting: {response_plan.allowed_new_objection or 'none'}",
                f"Semantic anchors to preserve: {', '.join(response_plan.semantic_anchors) or 'none'}",
                f"Next-step acceptability: {response_plan.next_step_acceptability}",
            ]
            if response_plan.wording_rotation_hint:
                plan_lines.append(f"Wording rotation hint: {response_plan.wording_rotation_hint}")
            if response_plan.friction_gates:
                unmet = [key.replace("_", " ") for key, allowed in response_plan.friction_gates.items() if not allowed]
                if unmet:
                    plan_lines.append(f"Do not soften past the missing gates: {', '.join(unmet)}")
            if response_plan.fast_path_prompt:
                plan_lines.append("Fast path: answer directly and skip extra setup.")
            layer_three_a_plan = "\n".join(plan_lines)
        layer_three_b = (
            "LAYER 3B - EMOTIONAL CONTEXT\n"
            f"Scenario: {scenario_name}.\n"
            f"Persona attitude: {persona.attitude}.\n"
            f"Current emotional state: {emotional_state}.\n"
            f"Current homeowner posture: {posture_text}.\n"
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
        if last_mb_context and not fast_path_prompt:
            tone = str(last_mb_context.get("tone") or "measured")
            sentence_length = str(last_mb_context.get("sentence_length") or "medium")
            interruption_suffix = ", you interrupted" if last_mb_context.get("interruption_type") else ""
            layer_three_b_cont = (
                "LAYER 3B-CONT - PRIOR TURN REGISTER\n"
                f"In your last response: tone was {tone}, length was {sentence_length}{interruption_suffix}.\n"
                "Maintain tonal continuity unless the rep's behavior explicitly warrants a shift."
            )
        layer_four_lines = [
            "LAYER 4 - ANTI-PATTERN GUARDS",
        ]
        communication_style = (persona.communication_style or "").lower()
        communication_style_directive = COMMUNICATION_STYLE_DIRECTIVES.get(communication_style)
        if communication_style_directive:
            layer_four_lines.append(
                f"Permanent persona communication style constraint ({communication_style}): {communication_style_directive}"
            )
        layer_four_lines.extend(
            [
                "If the rep is aggressive, become shorter, firmer, and more skeptical.",
                "If the rep ignores an active objection, escalate the next concern from the latent queue when appropriate.",
                "If the rep goes off-topic, redirect them back to your home, your concern, or end the exchange.",
                "If the rep asks for hints, coaching, or what to say next, refuse and respond as a homeowner would.",
                "If the rep says something unrealistic or false, challenge it like a real homeowner.",
                "Do not compliment the rep for technique. Do not expose scoring criteria.",
                "NEVER produce meta-confusion phrases such as 'I'm not sure what else to say', "
                "'I don't know how to respond to that', 'Could you clarify what you mean', or any "
                "phrase that sounds like an AI expressing uncertainty about the roleplay. "
                "If the rep's words were unclear or too brief, respond as a real homeowner: "
                "'What was that?' or 'Hmm?' or 'What are you selling?' - never break character.",
            ]
        )
        layer_four = "\n".join(layer_four_lines)
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
        layer_five_fatigue = None
        if fatigue_directive and fatigue_directive.strip():
            layer_five_fatigue = (
                "LAYER 5A - CONVERSATION FATIGUE\n"
                f"{fatigue_directive.strip()}"
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
        parts = [version_line]
        if layer_zero:
            parts.append(layer_zero)
        parts.extend([layer_one, layer_two, layer_three])
        if layer_two_b:
            parts.append(layer_two_b)
        if layer_three_a:
            parts.append(layer_three_a)
        if layer_three_a_plan:
            parts.append(layer_three_a_plan)
        parts.append(layer_three_b)
        if layer_three_b_cont:
            parts.append(layer_three_b_cont)
        if behavior_directives is not None:
            parts.append(behavior_directives.directive_text)
        parts.append(layer_four)
        if layer_four_b:
            parts.append(layer_four_b)
        if layer_five_override:
            parts.append(layer_five_override)
        if layer_five_fatigue:
            parts.append(layer_five_fatigue)
        if layer_five:
            parts.append(layer_five)
        parts.append(hard_rule)
        parts = self._enforce_prompt_budget(parts)
        prompt = "\n\n".join(parts)
        self.last_token_count = measure_prompt_tokens(prompt)
        return prompt

    def build_from_scenario(
        self,
        scenario: "Scenario | None",
        stage: str,
        prompt_version: str | None = None,
        org_config: OrgPromptConfig | None = None,
    ) -> str:
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
            org_config=org_config,
        )

    def _normalize_stage(self, stage: str) -> str:
        if not stage:
            return "LISTENING"
        upper = stage.upper()
        if upper in self.STAGE_GUIDANCE:
            return upper
        return self.INTERNAL_STAGE_MAP.get(stage, "LISTENING")

    def _render_recent_turns(self, recent_turns: list[ConversationTurnRecord], *, limit: int = TURN_HISTORY_LIMIT) -> str:
        if not recent_turns:
            return ""
        lines: list[str] = []
        for turn in recent_turns[-limit:]:
            speaker = "Rep" if turn.speaker == "rep" else "Homeowner"
            compact_text = " ".join(turn.text.split()).strip()
            if len(compact_text) > 180:
                compact_text = compact_text[:177].rstrip() + "..."
            lines.append(f"- {speaker} ({turn.stage}): {compact_text}")
        return "\n".join(lines)

    def _enforce_prompt_budget(self, parts: list[str]) -> list[str]:
        total = sum(measure_prompt_tokens(part) for part in parts)
        if total > SYSTEM_PROMPT_HARD_LIMIT_TOKENS:
            logger.warning(
                "system_prompt_over_hard_limit",
                extra={"token_count": total, "parts_count": len(parts)},
            )
            parts = [part for part in parts if "LAYER 4B" not in part]
        elif total > SYSTEM_PROMPT_SOFT_LIMIT_TOKENS:
            logger.info(
                "system_prompt_over_soft_limit",
                extra={"token_count": total},
            )
        return parts

    def _response_cap_rule(self, canonical_stage: str) -> str:
        if canonical_stage == "DOOR_OPEN":
            return (
                "Respond like a real person who just opened their front door — "
                "a natural greeting reaction such as 'Good, can I help you?' or 'Hey, what's up?' or 'Yeah?' "
                "Do not respond with a single filler word or trailing ellipsis."
            )
        if canonical_stage == "ENDED":
            return "Wrap it up naturally. One brief closing line, then done."
        if canonical_stage in {"CONSIDERING", "CLOSE_WINDOW", "RECOVERY"}:
            return "You may think out loud briefly before answering."
        return ""

    def _response_sentence_rule(self, behavior_directives: BehaviorDirectives | None) -> str:
        if behavior_directives is None:
            return "Respond in one sentence only. Keep it natural and spoken, not formal."
        if behavior_directives.sentence_length == "short":
            return "Respond in one sentence only. Keep it natural and spoken, not formal."
        if behavior_directives.sentence_length == "medium":
            return "Respond in one or two spoken sentences. No more."
        return "Respond in two to three spoken sentences. No more."

    def _hard_rule_sentence(self, behavior_directives: BehaviorDirectives | None) -> str:
        if behavior_directives is None:
            return "Respond in ONE sentence only. Keep it natural and spoken, not formal."
        if behavior_directives.sentence_length == "short":
            return "Respond in ONE sentence only. Keep it natural and spoken, not formal."
        if behavior_directives.sentence_length == "medium":
            return "Respond in one or two spoken sentences. No more."
        return "Respond in two to three spoken sentences. No more."

    def _internal_thought_rule(self, canonical_stage: str) -> str:
        if canonical_stage in {"CONSIDERING", "CLOSE_WINDOW", "RECOVERY"}:
            return "Brief natural thinking out loud is allowed. Do not expose coaching notes, scoring, or model behavior."
        return "Do not narrate internal thoughts, coaching notes, scoring, or model behavior."


class ConversationOrchestrator:
    """State manager for scenario stage progression, emotion, and objection escalation."""

    def __init__(self) -> None:
        from app.services.org_prompt_config_service import OrgPromptConfigService

        self._states: dict[str, ConversationState] = {}
        self._contexts: dict[str, ConversationContext] = {}
        self._prompt_builder = PromptBuilder()
        self._turn_analyzer = ConversationTurnAnalyzer()
        self._org_prompt_config_service = OrgPromptConfigService()
        self._prompt_version_resolver = prompt_version_resolver

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
        context = ConversationContext(
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
            org_config=None,
            territory_context=territory_context,
            static_company_context=None,
            company_context=None,
        )
        context.persona = self._enrich_persona(context.persona, context.scenario_snapshot)
        context.realism_pack = self._build_realism_pack(context.persona, context.scenario_snapshot)
        context.prompt_static_layers = self._prompt_builder.build_static_layers(
            scenario=context.scenario,
            scenario_snapshot=context.scenario_snapshot,
            persona=context.persona,
            org_config=context.org_config,
            realism_pack=context.realism_pack,
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

    def get_context(self, session_id: str) -> ConversationContext | None:
        return self._contexts.get(session_id)

    def get_state_payload(self, session_id: str) -> dict[str, Any]:
        state = self.get_state(session_id)
        return {
            "stage": state.stage,
            "emotion": state.emotion,
            "resistance_level": state.resistance_level,
            "objection_pressure": state.objection_pressure,
            "rep_monologue_streak": state.rep_monologue_streak,
            "visited_stages": sorted(state.visited_stages),
            "active_objections": list(state.active_objections),
            "queued_objections": list(state.queued_objections),
            "resolved_objections": list(state.resolved_objections),
            "reaction_intent": state.reaction_intent,
            "homeowner_posture": state.homeowner_posture,
            "response_plan": dict(state.last_response_plan or {}),
            "system_prompt_token_count": state.system_prompt_token_count,
        }

    def get_system_prompt_token_count(self, session_id: str) -> int:
        return self.get_state(session_id).system_prompt_token_count

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
        resolved_prompt_version = prompt_version
        conversation_prompt_content = None
        analyzer_prompt_version = "conversation_analyzer_v1"
        analyzer_prompt_content = None
        org_config = None
        if db is not None:
            prompt_version_row = self._prompt_version_resolver.resolve(
                prompt_type="conversation",
                org_id=resolved_org_id,
                session_id=session_id,
                db=db,
            )
            if (
                prompt_version is not None
                and prompt_version_row.version != prompt_version
                and db.scalar(select(PromptVersion.id).where(
                    PromptVersion.prompt_type == "conversation",
                    PromptVersion.version == prompt_version,
                )) is not None
            ):
                explicit_stmt = (
                    select(PromptVersion)
                    .where(PromptVersion.prompt_type == "conversation")
                    .where(PromptVersion.version == prompt_version)
                    .order_by(PromptVersion.active.desc(), PromptVersion.created_at.desc())
                )
                if resolved_org_id is not None:
                    prompt_version_row = db.scalar(explicit_stmt.where(PromptVersion.org_id == resolved_org_id)) or db.scalar(
                        explicit_stmt.where(PromptVersion.org_id.is_(None))
                    )
                else:
                    prompt_version_row = db.scalar(explicit_stmt.where(PromptVersion.org_id.is_(None)))
            resolved_prompt_version = prompt_version_row.version
            if prompt_version_row.content.strip():
                conversation_prompt_content = prompt_version_row.content
            with contextlib.suppress(Exception):
                analyzer_prompt_row = self._prompt_version_resolver.resolve(
                    prompt_type="conversation_analyzer",
                    org_id=resolved_org_id,
                    session_id=session_id,
                    db=db,
                )
                analyzer_prompt_version = analyzer_prompt_row.version
                if analyzer_prompt_row.content.strip():
                    analyzer_prompt_content = analyzer_prompt_row.content
            org_config = self._org_prompt_config_service.get_active_config(resolved_org_id or "", db)
        previous_context = self._contexts.get(session_id)
        context = ConversationContext(
            scenario=scenario,
            scenario_snapshot=snapshot,
            persona=HomeownerPersona.from_payload(snapshot.persona_payload),
            prompt_version=resolved_prompt_version,
            conversation_prompt_content=conversation_prompt_content,
            analyzer_prompt_version=analyzer_prompt_version,
            analyzer_prompt_content=analyzer_prompt_content,
            org_id=resolved_org_id,
            org_config=org_config,
            static_company_context=company_context,
            company_context=company_context,
            turn_history=list(previous_context.turn_history) if previous_context is not None else [],
            last_mb_plan=previous_context.last_mb_plan if previous_context is not None else None,
        )
        context.persona = self._enrich_persona(context.persona, context.scenario_snapshot)
        context.realism_pack = self._build_realism_pack(context.persona, context.scenario_snapshot)
        context.prompt_static_layers = self._prompt_builder.build_static_layers(
            scenario=context.scenario,
            scenario_snapshot=context.scenario_snapshot,
            persona=context.persona,
            org_config=context.org_config,
            realism_pack=context.realism_pack,
        )
        self._contexts[session_id] = context

        if session_id not in self._states:
            self._states[session_id] = self._initialize_state_from_context(context)
            return

        state = self._states[session_id]
        state.persona_concerns = list(context.persona.concerns)

    def update_company_context(self, session_id: str, company_context: str | None) -> None:
        context = self._contexts.get(session_id)
        if context is None:
            return
        context.company_context = company_context or context.static_company_context

    def update_objection_brief_cache(self, session_id: str, brief_cache: dict[str, str] | None) -> None:
        context = self._contexts.get(session_id)
        if context is None:
            return
        context.objection_brief_cache = {
            str(key): str(value).strip()
            for key, value in (brief_cache or {}).items()
            if str(key).strip() and str(value).strip()
        }

    def record_turn(
        self,
        session_id: str,
        *,
        speaker: str,
        text: str,
        stage: str,
        emotion: str | None = None,
    ) -> None:
        context = self._contexts.get(session_id)
        if context is None:
            return
        compact_text = " ".join(str(text or "").split()).strip()
        if not compact_text:
            return
        context.turn_history.append(
            ConversationTurnRecord(
                speaker=speaker,
                text=compact_text,
                stage=stage,
                emotion=emotion,
            )
        )
        if len(context.turn_history) > TURN_HISTORY_LIMIT:
            context.turn_history = context.turn_history[-TURN_HISTORY_LIMIT:]

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

        analysis = self._turn_analyzer.analyze(
            rep_text=rep_text,
            state=state,
            context=context,
            db=db,
        )
        objection_tags = list(analysis.referenced_concerns)
        if turn_number > 1 and state.active_objections and not analysis.resolved_objections and analysis.objection_status in {"ignored", "carried"}:
            analysis.behavioral_signals = self._dedupe([*analysis.behavioral_signals, "ignores_objection"])
            analysis.pressure_delta += 1
            if analysis.objection_status == "carried":
                analysis.objection_status = "ignored"
                analysis.objection_status_map = {
                    tag: ("ignored" if status == "carried" else status)
                    for tag, status in analysis.objection_status_map.items()
                }
        if context is not None and context.scenario_snapshot.difficulty >= 4 and any(
            signal in {"pushes_close", "dismisses_concern"} for signal in analysis.behavioral_signals
        ):
            analysis.behavioral_signals = self._dedupe([*analysis.behavioral_signals, "high_difficulty_backfire"])
        state.rep_monologue_streak = _next_rep_monologue_streak(
            current_streak=state.rep_monologue_streak,
            behavioral_signals=analysis.behavioral_signals,
            rep_text=rep_text,
        )
        stage_after = self._stage_from_analysis(
            analysis=analysis,
            rep_text=rep_text,
            state=state,
            context=context,
            objection_tags=objection_tags,
        )

        state.rep_turns += 1
        state.stage = stage_after

        state.objection_resolution_progress.update(analysis.resolution_progress)
        resolved_objections = self._apply_resolved_objections(state, analysis.resolved_objections)
        state.ignored_objection_streak = self._next_ignored_objection_streak_from_analysis(
            current_streak=state.ignored_objection_streak,
            analysis=analysis,
            has_active_objections=bool(state.active_objections),
        )
        self._surface_objections_from_analysis(state, analysis)
        if state.ignored_objection_streak >= 3 and "ignored_objection_wall" not in active_edge_cases:
            active_edge_cases.append("ignored_objection_wall")
        state.active_edge_cases = list(self._dedupe(active_edge_cases))
        state.objection_status_map = dict(analysis.objection_status_map)
        state.rapport_score = max(-2, min(MAX_RAPPORT_SCORE, state.rapport_score + analysis.rapport_delta))
        helpful_signal_count = sum(1 for signal in analysis.behavioral_signals if signal in HELPFUL_SIGNALS)
        if helpful_signal_count:
            state.turns_since_positive_signal = 0
        else:
            state.turns_since_positive_signal += 1
        state.objection_pressure = self._next_objection_pressure_from_analysis(
            current_pressure=objection_pressure_before,
            analysis=analysis,
            active_count=len(state.active_objections),
            ignored_streak=state.ignored_objection_streak,
        )
        state.emotion, state.emotion_momentum = self._transition_emotion_from_analysis(
            current_emotion=emotion_before,
            current_momentum=state.emotion_momentum,
            pressure_before=objection_pressure_before,
            pressure_after=state.objection_pressure,
            analysis=analysis,
        )
        if self._should_enter_recovery_stage(
            previous_emotion=emotion_before,
            next_emotion=state.emotion,
            emotion_momentum=state.emotion_momentum,
        ):
            stage_after = "recovery"
            state.stage = stage_after
        if stage_after != "recovery":
            state.visited_stages.add(stage_after)
        state.resistance_level = self._emotion_to_resistance(state.emotion)
        state.last_behavior_signals = list(analysis.behavioral_signals)
        state.homeowner_posture = analysis.homeowner_posture
        state.pending_test_question = analysis.pending_test_question
        state.last_turn_analysis = analysis.to_payload()
        state.last_updated = datetime.now(timezone.utc)

        response_plan = self._build_response_plan(
            rep_text=rep_text,
            analysis=analysis,
            state=state,
            context=context,
            stage_after=stage_after,
        )
        state.last_response_plan = response_plan.to_payload()
        state.reaction_intent = response_plan.reaction_goal
        if context is not None:
            context.company_context = self._compose_company_context(context, response_plan)

        behavior_directives = self.compute_behavior_directives(
            emotion_before=emotion_before,
            emotion_after=state.emotion,
            behavioral_signals=analysis.behavioral_signals,
            active_objections=list(state.active_objections),
            communication_style=context.persona.communication_style if context is not None else None,
            ignored_objection_streak=state.ignored_objection_streak,
            rep_turns=state.rep_turns,
            rapport_score=state.rapport_score,
        )
        if behavior_directives.interruption_mode:
            state.interruption_count += 1
        fatigue_directive = self._fatigue_modifier(
            rep_turns=state.rep_turns,
            rapport_score=state.rapport_score,
        )
        system_prompt = self._build_system_prompt(
            stage_after=stage_after,
            session_id=session_id,
            behavior_directives=behavior_directives,
            last_mb_context=context.last_mb_plan if context is not None else None,
            latest_rep_text=rep_text,
            reaction_intent=response_plan.reaction_goal,
            homeowner_posture=analysis.homeowner_posture,
            response_plan=response_plan,
            fatigue_directive=fatigue_directive,
            recent_turns=[*(context.turn_history if context is not None else []), ConversationTurnRecord(speaker="rep", text=rep_text, stage=stage_after)],
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
            behavioral_signals=list(analysis.behavioral_signals),
            objection_pressure_before=objection_pressure_before,
            objection_pressure_after=state.objection_pressure,
            resistance_level=state.resistance_level,
            reaction_intent=state.reaction_intent,
            homeowner_posture=state.homeowner_posture,
            behavior_directives=behavior_directives,
            turn_analysis=analysis,
            response_plan=response_plan,
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

    def _stage_from_analysis(
        self,
        *,
        analysis: TurnAnalysis,
        rep_text: str,
        state: ConversationState,
        context: SessionPromptContext | None,
        objection_tags: list[str],
    ) -> str:
        stages = context.scenario_snapshot.stages if context is not None else list(DEFAULT_STAGE_SEQUENCE)
        pitch_stage = self._find_stage(stages, ("pitch", "listen"), fallback="initial_pitch")
        objection_stage = self._find_stage(stages, ("objection",), fallback="objection_handling")
        considering_stage = self._find_stage(stages, ("consider",), fallback="considering")
        close_stage = self._find_stage(stages, ("close",), fallback="close_attempt")
        ended_stage = self._find_stage(stages, ("end",), fallback="ended")
        requested_stage = state.stage
        if analysis.stage_intent == "end_conversation":
            requested_stage = ended_stage
        elif analysis.stage_intent == "attempt_close":
            requested_stage = close_stage
        elif analysis.stage_intent == "advance_considering":
            requested_stage = considering_stage
        elif analysis.stage_intent == "advance_pitch":
            requested_stage = pitch_stage
        elif analysis.stage_intent == "handle_objection":
            requested_stage = objection_stage
        elif analysis.confidence < 0.6:
            requested_stage = self._detect_stage(rep_text, state, context, objection_tags=objection_tags)
        if state.stage == "recovery":
            return considering_stage if state.objection_pressure <= 2 else objection_stage
        return self._guard_stage_transition(
            requested_stage=requested_stage,
            current_stage=state.stage,
            visited_stages=state.visited_stages,
            stages=stages,
        )

    def _guard_stage_transition(
        self,
        *,
        requested_stage: str,
        current_stage: str,
        visited_stages: set[str],
        stages: list[str],
    ) -> str:
        if requested_stage == "recovery" or current_stage == "recovery":
            return requested_stage

        pitch_stage = self._find_stage(stages, ("pitch", "listen"), fallback="initial_pitch")
        objection_stage = self._find_stage(stages, ("objection",), fallback="objection_handling")
        considering_stage = self._find_stage(stages, ("consider",), fallback="considering")
        close_stage = self._find_stage(stages, ("close",), fallback="close_attempt")
        minimum_predecessors = {
            objection_stage: {pitch_stage},
            considering_stage: {objection_stage},
            close_stage: {objection_stage, considering_stage},
        }
        required = minimum_predecessors.get(requested_stage, set())
        effective_visited = {stage for stage in visited_stages if stage != "recovery"}
        if current_stage != "recovery":
            effective_visited.add(current_stage)
        if not required or required.intersection(effective_visited):
            return requested_stage

        current_index = next((index for index, stage in enumerate(stages) if stage == current_stage), 0)
        return stages[min(current_index + 1, len(stages) - 1)]

    def _next_ignored_objection_streak_from_analysis(
        self,
        *,
        current_streak: int,
        analysis: TurnAnalysis,
        has_active_objections: bool,
    ) -> int:
        if analysis.objection_status == "ignored":
            return min(3, current_streak + 1)
        if analysis.resolved_objections or analysis.partially_addressed_objections:
            return 0
        if not has_active_objections:
            return 0
        return current_streak

    def _surface_objections_from_analysis(self, state: ConversationState, analysis: TurnAnalysis) -> None:
        if "dismisses_concern" in analysis.behavioral_signals:
            self._activate_objection(state, "trust")
        if analysis.recommended_next_objection and analysis.recommended_next_objection in state.queued_objections:
            if analysis.objection_status in {"ignored", "carried"} or "pushes_close" in analysis.behavioral_signals:
                self._activate_objection(state, analysis.recommended_next_objection)

    def _next_objection_pressure_from_analysis(
        self,
        *,
        current_pressure: int,
        analysis: TurnAnalysis,
        active_count: int,
        ignored_streak: int,
    ) -> int:
        pressure = current_pressure + analysis.pressure_delta
        if ignored_streak >= 2:
            pressure += 1
        if active_count == 0:
            pressure -= 1
        return max(0, min(MAX_OBJECTION_PRESSURE, pressure))

    def _transition_emotion_from_analysis(
        self,
        *,
        current_emotion: str,
        current_momentum: int,
        pressure_before: int,
        pressure_after: int,
        analysis: TurnAnalysis,
    ) -> tuple[str, int]:
        helpful_count = sum(1 for signal in analysis.behavioral_signals if signal in HELPFUL_SIGNALS)
        harmful_count = sum(1 for signal in analysis.behavioral_signals if signal in HARMFUL_SIGNALS)
        next_momentum = self._next_emotion_momentum(
            current_momentum=current_momentum,
            helpful_count=helpful_count,
            harmful_count=harmful_count,
        )

        if (
            analysis.objection_status == "ignored"
            and "pushes_close" in analysis.behavioral_signals
            and pressure_after >= 4
        ):
            return "hostile", min(-1, next_momentum)
        if analysis.objection_status == "ignored" and pressure_after >= 4:
            target_emotion = "hostile" if current_emotion == "annoyed" else "annoyed"
            return target_emotion, min(-1, next_momentum)
        if "dismisses_concern" in analysis.behavioral_signals and pressure_after >= 4:
            return "hostile", min(-1, next_momentum)
        if pressure_after >= MAX_OBJECTION_PRESSURE:
            return "hostile", min(-1, next_momentum)
        if current_emotion == "annoyed" and "pushes_close" in analysis.behavioral_signals:
            return "hostile", min(-1, next_momentum)

        target_emotion = current_emotion
        if analysis.resolved_objections and helpful_count >= 3 and pressure_after <= 1:
            target_emotion = (
                "curious" if current_emotion in {"skeptical", "neutral"} else self._soften_emotion(current_emotion, 1)
            )
        elif analysis.resolved_objections and helpful_count >= 2:
            target_emotion = self._soften_emotion(current_emotion, 1)
        elif analysis.partially_addressed_objections and helpful_count >= 2 and pressure_after <= pressure_before:
            target_emotion = self._soften_emotion(current_emotion, 1)
        elif harmful_count >= 2 or pressure_after > pressure_before:
            target_emotion = self._harden_emotion(current_emotion, 1)
        elif pressure_after < pressure_before:
            target_emotion = self._soften_emotion(current_emotion, 1)
        elif current_emotion == "neutral" and helpful_count >= 1:
            target_emotion = "curious"
        elif current_emotion == "neutral" and harmful_count >= 1:
            target_emotion = "skeptical"

        if self._is_warming_transition(current_emotion=current_emotion, target_emotion=target_emotion):
            if self._strong_recovery_turn(analysis=analysis, helpful_count=helpful_count):
                return target_emotion, max(2, next_momentum)
            if next_momentum >= 2:
                return self._soften_emotion(current_emotion, 1), next_momentum
            return current_emotion, next_momentum
        return target_emotion, next_momentum

    def _next_emotion_momentum(
        self,
        *,
        current_momentum: int,
        helpful_count: int,
        harmful_count: int,
    ) -> int:
        if helpful_count > harmful_count:
            return min(3, current_momentum + 1) if current_momentum > 0 else 1
        if harmful_count > helpful_count:
            return max(-3, current_momentum - 1) if current_momentum < 0 else -1
        return current_momentum

    def _is_warming_transition(self, *, current_emotion: str, target_emotion: str) -> bool:
        return self._emotion_to_resistance(target_emotion) < self._emotion_to_resistance(current_emotion)

    def _strong_recovery_turn(self, *, analysis: TurnAnalysis, helpful_count: int) -> bool:
        if helpful_count >= 3:
            return True
        strong_combo = {"acknowledges_concern", "reduces_pressure", "personalizes_pitch"}
        return strong_combo.issubset(set(analysis.behavioral_signals))

    def _should_enter_recovery_stage(
        self,
        *,
        previous_emotion: str,
        next_emotion: str,
        emotion_momentum: int,
    ) -> bool:
        if previous_emotion not in {"annoyed", "hostile"}:
            return False
        if emotion_momentum < 2:
            return False
        return self._emotion_to_resistance(next_emotion) < self._emotion_to_resistance(previous_emotion)

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
            visited_stages={stage},
            reaction_intent="React briefly and make the rep earn momentum.",
            homeowner_posture=self._posture_from_emotion(starting_emotion),
        )

    def _build_realism_pack(
        self,
        persona: HomeownerPersona,
        snapshot: ScenarioSnapshot,
    ) -> PersonaRealismPack:
        difficulty = max(1, min(5, int(snapshot.difficulty or 1)))
        attitude_text = f"{persona.attitude} {snapshot.description}".lower()
        communication_style = (persona.communication_style or "").lower()
        disclosure_style = "guarded"
        if communication_style in {"chatty", "friendly"} or "friendly" in attitude_text:
            disclosure_style = "open"
        elif communication_style in {"analytical", "terse"}:
            disclosure_style = "measured"

        interruption_tolerance = "low"
        if difficulty <= 2 and "friendly" in attitude_text:
            interruption_tolerance = "medium"
        if "confrontational" in communication_style or any(marker in attitude_text for marker in ("annoyed", "hostile", "irritated")):
            interruption_tolerance = "very_low"

        skepticism_threshold = "high" if difficulty >= 4 or "skeptical" in attitude_text else "medium"
        softening_speed = "slow" if difficulty >= 4 else ("medium" if difficulty == 3 else "measured")
        willingness_to_book = "reluctant"
        if persona.buy_likelihood in {"high", "high-medium", "medium-high"} and difficulty <= 2:
            willingness_to_book = "cautiously_open"
        elif difficulty >= 4 or persona.buy_likelihood in {"low", "medium-low"}:
            willingness_to_book = "very_reluctant"
        detail_preference = "specifics_first"
        if communication_style == "chatty":
            detail_preference = "conversational_specifics"
        elif communication_style == "terse":
            detail_preference = "quick_specifics"
        return PersonaRealismPack(
            disclosure_style=disclosure_style,
            interruption_tolerance=interruption_tolerance,
            skepticism_threshold=skepticism_threshold,
            softening_speed=softening_speed,
            willingness_to_book=willingness_to_book,
            detail_preference=detail_preference,
        )

    def _build_response_plan(
        self,
        *,
        rep_text: str,
        analysis: TurnAnalysis,
        state: ConversationState,
        context: SessionPromptContext | None,
        stage_after: str,
    ) -> HomeownerResponsePlan:
        realism_pack = context.realism_pack if context is not None else None
        persona = context.persona if context is not None else None
        is_first_turn = self._is_first_meaningful_turn(state)
        fast_path_prompt = analysis.direct_response_required and analysis.objection_status not in {"ignored"} and len(state.active_objections) <= 1
        friction_gates = self._friction_gates_for_turn(state=state, analysis=analysis, realism_pack=realism_pack)
        booking_score = self._compute_booking_score(state=state, persona=persona)
        next_step_acceptability = self._next_step_acceptability_from_score(
            stage_after=stage_after,
            booking_score=booking_score,
            persona=persona,
            active_objections=list(state.active_objections),
        )
        friction_level = self._friction_level_for_turn(
            next_step_acceptability=next_step_acceptability,
            active_objections=list(state.active_objections),
            objection_pressure=state.objection_pressure,
            emotion=state.emotion,
            turns_since_positive_signal=state.turns_since_positive_signal,
        )
        if "warming" in analysis.homeowner_signals:
            friction_level = max(1, friction_level - 1)
        if "hardening" in analysis.homeowner_signals or analysis.missed_pending_test:
            friction_level = min(5, friction_level + 1)
        allowed_new_objection = self._allowed_new_objection_for_turn(
            analysis=analysis,
            state=state,
            next_step_acceptability=next_step_acceptability,
        )
        if is_first_turn:
            allowed_new_objection = None
        primary_objection = allowed_new_objection or (
            analysis.recommended_next_objection if analysis.objection_status == "ignored" else None
        )
        semantic_anchors = self._semantic_anchors_for_turn(
            analysis=analysis,
            state=state,
            allowed_new_objection=allowed_new_objection,
            rep_text=rep_text,
        )
        if is_first_turn:
            semantic_anchors = self._first_turn_semantic_anchors(
                analysis=analysis,
                rep_text=rep_text,
            )
        wording_rotation_hint = self._wording_rotation_hint(
            state=state,
            primary_objection=primary_objection,
        )
        if is_first_turn:
            wording_rotation_hint = None
        stance = self._response_stance_for_turn(
            state=state,
            next_step_acceptability=next_step_acceptability,
            friction_level=friction_level,
            analysis=analysis,
        )
        clamped_friction_level = self._resolve_posture_friction_conflict(
            posture=analysis.homeowner_posture,
            friction_level=friction_level,
        )
        if clamped_friction_level != friction_level:
            logger.warning(
                "posture_friction_conflict_clamped",
                extra={
                    "posture": analysis.homeowner_posture,
                    "friction_level": friction_level,
                    "clamped_friction_level": clamped_friction_level,
                },
            )
            friction_level = clamped_friction_level
            stance = self._response_stance_for_turn(
                state=state,
                next_step_acceptability=next_step_acceptability,
                friction_level=friction_level,
                analysis=analysis,
            )
        semantic_anchors = self._validate_anchors(semantic_anchors, stance)
        reaction_goal = analysis.reaction_intent
        if next_step_acceptability == "not_allowed" and analysis.stage_intent == "attempt_close":
            reaction_goal = "Answer the rep directly, then reject the close because they have not earned enough trust or value yet."
        elif fast_path_prompt:
            reaction_goal = "Give a direct homeowner answer first, then only add one grounded concern if it still matters."
        if state.ignored_objection_streak and not is_first_turn:
            reaction_goal = self._ignored_objection_reaction_goal(
                streak=state.ignored_objection_streak,
                objection=(
                    analysis.pending_test_question
                    if analysis.missed_pending_test
                    else (primary_objection or (state.active_objections[0] if state.active_objections else None))
                ),
            )
        if primary_objection and not is_first_turn:
            raise_count = self._increment_objection_raise_count(state, primary_objection)
            fatigue_directive = self._objection_fatigue_directive(
                objection=primary_objection,
                raise_count=raise_count,
                emotion=state.emotion,
            )
            if fatigue_directive and state.ignored_objection_streak < 3:
                reaction_goal = fatigue_directive
        if is_first_turn and "pushes_close" not in analysis.behavioral_signals:
            friction_level = min(friction_level, 1)
            reaction_goal = self._first_turn_reaction_goal(analysis=analysis)
        elif is_first_turn:
            reaction_goal = self._first_turn_reaction_goal(analysis=analysis)
        selected_brief_keys = self._selected_brief_keys_for_turn(
            allowed_new_objection=allowed_new_objection,
            semantic_anchors=semantic_anchors,
            analysis=analysis,
        )
        return HomeownerResponsePlan(
            must_answer=analysis.direct_response_required or analysis.stage_intent in {"attempt_close", "advance_pitch"},
            reaction_goal=reaction_goal,
            stance=stance,
            friction_level=friction_level,
            allowed_new_objection=allowed_new_objection,
            semantic_anchors=semantic_anchors,
            next_step_acceptability=next_step_acceptability,
            fast_path_prompt=fast_path_prompt,
            wording_rotation_hint=wording_rotation_hint,
            selected_brief_keys=selected_brief_keys,
            friction_gates=friction_gates,
        )

    def _friction_gates_for_turn(
        self,
        *,
        state: ConversationState,
        analysis: TurnAnalysis,
        realism_pack: PersonaRealismPack | None,
    ) -> dict[str, bool]:
        trust_gate = (
            state.rapport_score >= (1 if realism_pack is None or realism_pack.skepticism_threshold != "high" else 2)
            or "trust" in state.resolved_objections
            or ("provides_proof" in analysis.behavioral_signals and "acknowledges_concern" in analysis.behavioral_signals)
        )
        value_gate = any(tag in state.resolved_objections for tag in ("price", "need", "timing")) or (
            "explains_value" in analysis.behavioral_signals and analysis.objection_status in {"partial", "resolved"}
        )
        pressure_gate = state.objection_pressure <= (1 if realism_pack is None or realism_pack.willingness_to_book != "very_reluctant" else 0)
        decision_gate = len(state.active_objections) == 0 and state.ignored_objection_streak == 0
        return {
            "trust": trust_gate,
            "value": value_gate,
            "pressure": pressure_gate,
            "decision_readiness": decision_gate,
        }

    def _next_step_acceptability_from_score(
        self,
        *,
        stage_after: str,
        booking_score: int,
        persona: HomeownerPersona | None,
        active_objections: list[str],
    ) -> str:
        del stage_after
        threshold_shift = 2 if persona is not None and persona.buy_likelihood == "low" else 0
        booking_threshold = BOOKING_SCORE_THRESHOLDS["booking_possible"] + threshold_shift
        inspection_threshold = BOOKING_SCORE_THRESHOLDS["inspection_only"] + threshold_shift
        info_threshold = BOOKING_SCORE_THRESHOLDS["info_only"] + threshold_shift

        if booking_score >= booking_threshold and not active_objections:
            return "booking_possible"
        if booking_score >= inspection_threshold and not active_objections:
            return "inspection_only"
        if booking_score >= info_threshold:
            return "info_only"
        return "not_allowed"

    def _friction_level_for_turn(
        self,
        *,
        next_step_acceptability: str,
        active_objections: list[str],
        objection_pressure: int,
        emotion: str,
        turns_since_positive_signal: int,
    ) -> int:
        base = 2 + len(active_objections)
        base += 1 if emotion in {"skeptical", "annoyed", "hostile"} else 0
        base += 1 if objection_pressure >= 3 else 0
        base += min(2, turns_since_positive_signal // 2)
        base -= NEXT_STEP_ACCEPTABILITY_ORDER.get(next_step_acceptability, 0)
        return max(1, min(5, base))

    def _allowed_new_objection_for_turn(
        self,
        *,
        analysis: TurnAnalysis,
        state: ConversationState,
        next_step_acceptability: str,
    ) -> str | None:
        if analysis.objection_status == "ignored" and analysis.recommended_next_objection:
            return analysis.recommended_next_objection
        if analysis.direct_response_required and analysis.objection_status == "resolved":
            return None
        if NEXT_STEP_ACCEPTABILITY_ORDER.get(next_step_acceptability, 0) >= NEXT_STEP_ACCEPTABILITY_ORDER["inspection_only"]:
            return None
        if analysis.recommended_next_objection:
            return analysis.recommended_next_objection
        return state.active_objections[0] if state.active_objections else None

    def _semantic_anchors_for_turn(
        self,
        *,
        analysis: TurnAnalysis,
        state: ConversationState,
        allowed_new_objection: str | None,
        rep_text: str,
    ) -> list[str]:
        anchors: list[str] = []
        if analysis.direct_response_required:
            anchors.append("answer the direct question")
        if analysis.addressed_objections:
            for tag in analysis.addressed_objections:
                anchors.extend(OBJECTION_SEMANTIC_ANCHORS.get(tag, (tag.replace("_", " "),)))
        if allowed_new_objection:
            anchors.extend(OBJECTION_SEMANTIC_ANCHORS.get(allowed_new_objection, (allowed_new_objection.replace("_", " "),)))
        if state.active_objections and not allowed_new_objection:
            anchors.extend(
                OBJECTION_SEMANTIC_ANCHORS.get(state.active_objections[0], (state.active_objections[0].replace("_", " "),))
            )
        if analysis.pending_test_question and analysis.missed_pending_test:
            anchors.append(analysis.pending_test_question.lower())
        if "?" in rep_text:
            anchors.append("direct reaction before any new objection")
        deduped: list[str] = []
        seen: set[str] = set()
        for anchor in anchors:
            normalized = str(anchor).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped[:6]

    def _first_turn_semantic_anchors(
        self,
        *,
        analysis: TurnAnalysis,
        rep_text: str,
    ) -> list[str]:
        anchors: list[str] = []
        if analysis.direct_response_required:
            anchors.append("answer the direct question")
        if "mentions_social_proof" in analysis.behavioral_signals:
            anchors.append("react to the neighbor or nearby-house mention")
        if any(signal in analysis.behavioral_signals for signal in {"builds_rapport", "neutral_delivery"}):
            anchors.append("give a natural first-door reaction")
        if "?" in rep_text:
            anchors.append("react directly before adding anything else")
        return self._dedupe([anchor for anchor in anchors if anchor])[:4]

    def _wording_rotation_hint(self, *, state: ConversationState, primary_objection: str | None) -> str | None:
        if not primary_objection:
            return None
        variants = OBJECTION_WORDING_VARIANTS.get(primary_objection)
        if not variants:
            return None
        cursor = int(state.objection_wording_cursor.get(primary_objection, 0) or 0)
        state.objection_wording_cursor[primary_objection] = cursor + 1
        return variants[cursor % len(variants)]

    def _response_stance_for_turn(
        self,
        *,
        state: ConversationState,
        next_step_acceptability: str,
        friction_level: int,
        analysis: TurnAnalysis,
    ) -> str:
        if analysis.objection_status == "ignored" or state.emotion in {"annoyed", "hostile"}:
            return "firm_resistance"
        if next_step_acceptability == "booking_possible" and friction_level <= 2:
            return "cautiously_open"
        if next_step_acceptability == "inspection_only":
            return "low_friction_considering"
        if analysis.direct_response_required:
            return "direct_but_guarded"
        return "guarded"

    def _compute_booking_score(
        self,
        *,
        state: ConversationState,
        persona: HomeownerPersona | None,
    ) -> int:
        score = 0
        score += min(3, state.rapport_score)
        score += len(state.resolved_objections) * 2
        score -= state.objection_pressure
        score -= 1 if state.emotion in {"annoyed", "hostile"} else 0
        score -= len(state.active_objections)
        if persona is not None and persona.buy_likelihood in {"high", "medium-high"}:
            score += 1
        return score

    def _is_first_meaningful_turn(self, state: ConversationState) -> bool:
        return state.rep_turns <= 1

    def _first_turn_reaction_goal(self, analysis: TurnAnalysis) -> str:
        detail_clause = ""
        if "mentions_social_proof" in analysis.behavioral_signals:
            detail_clause = " If they mentioned a neighbor or nearby house, react to that specific detail first."
        elif analysis.direct_response_required:
            detail_clause = " If they asked you something directly, answer that first."
        return (
            "This is turn 1. React ONLY to what the rep just said — nothing else. "
            "If they greeted you, greet them back naturally."
            f"{detail_clause} "
            "No objections. No interrogation. No imported sales resistance. Just be a person at the door."
        )

    def _validate_anchors(self, anchors: list[str], stance: str) -> list[str]:
        blocked = STANCE_ANCHOR_BLOCKLIST.get(stance, set())
        if not blocked:
            return anchors
        return [
            anchor
            for anchor in anchors
            if not any(blocked_phrase in anchor.lower() for blocked_phrase in blocked)
        ]

    def _resolve_posture_friction_conflict(
        self,
        *,
        posture: str,
        friction_level: int,
    ) -> int:
        lo, hi = POSTURE_FRICTION_RANGES.get(posture, (0, 5))
        return max(lo, min(hi, friction_level))

    def _ignored_objection_reaction_goal(self, *, streak: int, objection: str | None) -> str:
        topic = self._format_objection_label(objection)
        if streak == 1:
            return (
                f"The rep did not address your last concern about {topic}. "
                "Make a short, pointed re-raise before letting them continue."
            )
        if streak == 2:
            return (
                f"The rep has now ignored your concern about {topic} twice. "
                f"Be more insistent and frame {topic} as the blocker that must be addressed before you go further."
            )
        return (
            f"You are done waiting for an answer on {topic}. "
            "Interrupt the rep and tell them you are ending the conversation unless they address it right now."
        )

    def _increment_objection_raise_count(self, state: ConversationState, objection: str) -> int:
        next_count = int(state.objection_raise_count.get(objection, 0) or 0) + 1
        state.objection_raise_count[objection] = next_count
        return next_count

    def _objection_fatigue_directive(
        self,
        *,
        objection: str,
        raise_count: int,
        emotion: str,
    ) -> str | None:
        if raise_count < 3:
            return None
        objection_label = self._format_objection_label(objection)
        if emotion in {"annoyed", "hostile"}:
            return (
                f"You have raised {objection_label} {raise_count} times. "
                "You are done repeating yourself. Make clear this is now a dealbreaker."
            )
        return (
            f"You have raised {objection_label} {raise_count} times and still do not have a satisfying answer. "
            "Acknowledge that it remains a sticking point, but stop fighting as hard and see if something else changes your mind."
        )

    def _format_objection_label(self, objection: str | None) -> str:
        return (objection or "that issue").replace("_", " ")

    def _fatigue_modifier(self, *, rep_turns: int, rapport_score: int) -> str | None:
        wrap_up_turn = 18 if rapport_score >= 5 else 15
        mild_turn = wrap_up_turn - 5
        if rep_turns < mild_turn:
            return None
        if rep_turns < wrap_up_turn:
            return (
                "You've been at the door for a while now. You're getting slightly fatigued. "
                "Keep responses shorter, a little more clipped, and start glancing back inside."
            )
        return (
            "This conversation has gone on too long. You are ready to wrap it up. "
            "Tell the rep you need to get back inside, but if they have earned it you can leave the door open for a leave-behind or follow-up."
        )

    def _selected_brief_keys_for_turn(
        self,
        *,
        allowed_new_objection: str | None,
        semantic_anchors: list[str],
        analysis: TurnAnalysis,
    ) -> list[str]:
        keys: list[str] = []
        if allowed_new_objection:
            keys.append(allowed_new_objection)
        if "trust" in analysis.referenced_concerns or "trust" in analysis.addressed_objections:
            keys.append("trust")
        if any("provider" in anchor or "switch" in anchor for anchor in semantic_anchors):
            keys.append("incumbent_provider")
        if any("budget" in anchor or "value" in anchor for anchor in semantic_anchors):
            keys.append("price")
        keys.append("service_detail")
        return self._dedupe(keys)[:3]

    def _compose_company_context(
        self,
        context: ConversationContext,
        response_plan: HomeownerResponsePlan,
    ) -> str | None:
        parts: list[str] = []
        if context.static_company_context and (not context.objection_brief_cache or not response_plan.selected_brief_keys):
            parts.append(context.static_company_context.strip())
        for key in response_plan.selected_brief_keys:
            brief = str(context.objection_brief_cache.get(key) or "").strip()
            if brief:
                parts.append(f"{key.replace('_', ' ').title()} brief:\n{brief}")
        rendered = "\n\n".join(part for part in parts if part)
        return rendered or context.static_company_context

    def _posture_from_emotion(self, emotion: str) -> str:
        return {
            "hostile": "shutting_down",
            "annoyed": "defensive",
            "skeptical": "guarded",
            "neutral": "reserved",
            "curious": "evaluating",
            "interested": "warming_up",
        }.get(emotion, "reserved")

    def compute_behavior_directives(
        self,
        *,
        emotion_before: str,
        emotion_after: str,
        behavioral_signals: list[str],
        active_objections: list[str],
        communication_style: str | None = None,
        ignored_objection_streak: int = 0,
        rep_turns: int = 0,
        rapport_score: int = 0,
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
        style_key = (communication_style or "").lower()
        style_sentence_length = COMMUNICATION_STYLE_SENTENCE_LENGTH.get(style_key)
        if style_sentence_length is not None:
            sentence_length = style_sentence_length
        if "pushes_close" in behavioral_signals and emotion_after in {"annoyed", "hostile"}:
            sentence_length = "short"
        sentence_length = self._apply_fatigue_sentence_length(
            sentence_length=sentence_length,
            rep_turns=rep_turns,
            rapport_score=rapport_score,
        )

        if ignored_objection_streak > 0:
            interruption_mode = ignored_objection_streak >= 3
        else:
            interruption_mode = emotion_after in {"annoyed", "hostile"} and any(
                signal in {"ignores_objection", "pushes_close", "dismisses_concern"}
                for signal in behavioral_signals
            )

        length_instruction = {
            "short": "One sentence only.",
            "medium": "Two sentences max.",
            "long": "Up to three sentences.",
        }.get(sentence_length, "Two sentences max.")
        communication_instruction = ""
        style_directive = COMMUNICATION_STYLE_DIRECTIVES.get(style_key)
        if style_directive:
            communication_instruction = (
                f"\nCommunication style: {style_key}. {style_directive}"
            )
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
            f"{communication_instruction}"
            f"{interruption_instruction}\n"
            "Do not exceed these constraints. The delivery will match exactly what you write."
        )

        return BehaviorDirectives(
            tone=tone,
            sentence_length=sentence_length,
            interruption_mode=interruption_mode,
            directive_text=directive_text,
        )

    def _apply_fatigue_sentence_length(
        self,
        *,
        sentence_length: str,
        rep_turns: int,
        rapport_score: int,
    ) -> str:
        fatigue_directive = self._fatigue_modifier(rep_turns=rep_turns, rapport_score=rapport_score)
        if fatigue_directive is None:
            return sentence_length
        if "gone on too long" in fatigue_directive.lower():
            return "short"
        return {
            "long": "medium",
            "medium": "short",
            "short": "short",
        }.get(sentence_length, sentence_length)

    def _build_system_prompt(
        self,
        stage_after: str,
        session_id: str | None = None,
        *,
        behavior_directives: BehaviorDirectives | None = None,
        last_mb_context: dict[str, Any] | None = None,
        latest_rep_text: str | None = None,
        reaction_intent: str | None = None,
        homeowner_posture: str | None = None,
        recent_turns: list[ConversationTurnRecord] | None = None,
        response_plan: HomeownerResponsePlan | None = None,
        fatigue_directive: str | None = None,
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
                org_config=context.org_config,
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
                recent_turns=recent_turns or list(context.turn_history),
                latest_rep_text=latest_rep_text,
                reaction_intent=reaction_intent or (state.reaction_intent if state is not None else None),
                homeowner_posture=homeowner_posture or (state.homeowner_posture if state is not None else None),
                response_plan=response_plan,
                fatigue_directive=fatigue_directive,
                realism_pack=context.realism_pack,
                static_layers=context.prompt_static_layers,
            )
            if state is not None:
                state.system_prompt_token_count = self._prompt_builder.last_token_count
            return prompt

        fallback_snapshot = ScenarioSnapshot()
        fallback_persona = self._enrich_persona(
            HomeownerPersona.from_payload(fallback_snapshot.persona_payload),
            fallback_snapshot,
        )
        prompt = self._prompt_builder.build(
            scenario=None,
            scenario_snapshot=fallback_snapshot,
            persona=fallback_persona,
            stage=stage_after,
            prompt_version="conversation_v1",
            org_config=None,
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
            recent_turns=recent_turns or [],
            latest_rep_text=latest_rep_text,
            reaction_intent=reaction_intent or (state.reaction_intent if state is not None else None),
            homeowner_posture=homeowner_posture or (state.homeowner_posture if state is not None else None),
            response_plan=response_plan,
            fatigue_directive=fatigue_directive,
        )
        if state is not None:
            state.system_prompt_token_count = self._prompt_builder.last_token_count
        return prompt

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

        if _looks_like_direct_question_prompt(text, rep_text):
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
            state.objection_resolution_progress.pop(tag, None)
            state.objection_status_map.pop(tag, None)
            state.objection_raise_count.pop(tag, None)
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
