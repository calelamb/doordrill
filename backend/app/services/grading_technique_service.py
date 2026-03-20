from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CATEGORY_KEYS = (
    "opening",
    "pitch_delivery",
    "objection_handling",
    "closing_technique",
    "professionalism",
)

ACKNOWLEDGEMENT_HINTS = (
    "that's fair",
    "that is fair",
    "i get it",
    "totally get it",
    "totally",
    "i hear you",
    "makes sense",
    "i figured",
)
NEIGHBOR_HINTS = (
    "neighbor",
    "neighbors",
    "street",
    "route",
    "on the street",
    "swinging by",
    "same route",
)
QUOTE_PIVOT_HINTS = (
    "leave you with a quote",
    "quick quote",
    "before i take off",
    "before i go",
)
PEST_EVIDENCE_HINTS = (
    "cobweb",
    "cobwebs",
    "wasp",
    "wasps",
    "ant",
    "ants",
    "eaves",
    "foundation",
    "flower bed",
    "flower beds",
    "entry point",
    "entry points",
)
FEATURE_HINTS = (
    "deweb",
    "dewebbing",
    "perimeter",
    "foundation",
    "flower beds",
    "yard",
    "premium yard",
    "initial treatment",
    "inspection",
    "treatment",
)
BENEFIT_HINTS = (
    "break the cycle",
    "never behind",
    "build a barrier",
    "lower your monthly rate",
    "half the cost",
    "pet and kid safe",
    "month to month",
    "cancel anytime",
    "waived",
)
SOFT_CLOSE_HINTS = (
    "right?",
    "does that make sense",
    "sound fair",
    "you've got",
    "any dogs or cats",
)
OPTION_CLOSE_HINTS = (
    "tuesday or thursday",
    "3pm or 5pm",
    "3 or 5",
    "am or pm",
    "which one works",
)
CLOSE_HINTS = (
    "today",
    "schedule",
    "next step",
    "book",
    "move forward",
    "sign up",
    "get started",
)
ASSUMPTIVE_CLOSE_HINTS = (
    "what's your first name",
    "let me get you set up",
    "i'll put you down",
    "confirmation text",
    "does that address look right",
)
LEVEL_UP_HINTS = (
    "we've been talking",
    "give us a shot",
    "what do i need to do",
    "not trying to sign you up for life",
)
BACKYARD_CLOSE_HINTS = (
    "backyard",
    "quick look at your backyard",
    "show you what i'm seeing",
    "fit you in",
    "fill this slot today",
)
DIY_HINTS = (
    "hardware store",
    "residual",
    "barrier",
    "what are you mainly dealing with",
)
COMPETITOR_HINTS = ("aptive", "terminix", "orkin", "switch over", "switch over from", "who do you have")
PRICE_HINTS = ("price", "budget", "monthly", "startup fee", "basic rate", "half the cost")
SERVICE_HINTS = ("need it", "problem", "service", "maintenance", "coverage")
HARD_PRESSURE_HINTS = (
    "sign today",
    "right now",
    "need to fill this slot today",
    "move forward right now",
    "book today",
)
ATTACK_COMPETITOR_HINTS = ("they suck", "they are terrible", "they ripped you off", "they wasted your money")


@dataclass(frozen=True, slots=True)
class TechniqueCue:
    id: str
    label: str
    category: str
    observable_from: str
    weight: float
    kind: str
    applies_when: str
    evidence_rules: str
    cap: float | None = None


@dataclass(slots=True)
class TechniqueCheck:
    id: str
    label: str
    category: str
    status: str
    kind: str
    observable_from: str
    evidence_turn_ids: list[str]
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "status": self.status,
            "kind": self.kind,
            "observable_from": self.observable_from,
            "evidence_turn_ids": list(self.evidence_turn_ids),
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload


TECHNIQUE_CUES: tuple[TechniqueCue, ...] = (
    TechniqueCue(
        id="opening_neighbor_route_frame",
        label="Neighbor / route framing",
        category="opening",
        observable_from="transcript_observable",
        weight=0.8,
        kind="reward",
        applies_when="always",
        evidence_rules="Opening mentions neighbors, street, or route context without pressure.",
    ),
    TechniqueCue(
        id="opening_low_pressure_quote_pivot",
        label="Low-pressure quote pivot",
        category="opening",
        observable_from="reaction_observable",
        weight=0.7,
        kind="reward",
        applies_when="homeowner resists early",
        evidence_rules="After early resistance, rep validates and pivots to a quote or small ask.",
    ),
    TechniqueCue(
        id="opening_posture_neighbor_energy",
        label="Relaxed non-confrontational presence",
        category="professionalism",
        observable_from="unobservable",
        weight=0.0,
        kind="coaching_only",
        applies_when="always",
        evidence_rules="Body language and stance are coaching topics only when not visible in transcript.",
    ),
    TechniqueCue(
        id="pitch_observed_pest_evidence",
        label="Observed property-specific evidence",
        category="pitch_delivery",
        observable_from="transcript_observable",
        weight=0.8,
        kind="reward",
        applies_when="pitch present",
        evidence_rules="Rep points to visible pest evidence or property-specific risk.",
    ),
    TechniqueCue(
        id="pitch_feature_benefit_soft_close",
        label="Feature -> Benefit -> Soft Close",
        category="pitch_delivery",
        observable_from="transcript_observable",
        weight=0.9,
        kind="reward",
        applies_when="pitch present",
        evidence_rules="Rep explains feature, connects benefit, and asks a soft property-specific question.",
    ),
    TechniqueCue(
        id="pitch_bimonthly_value_anchor",
        label="Bimonthly value anchor",
        category="pitch_delivery",
        observable_from="transcript_observable",
        weight=0.6,
        kind="reward",
        applies_when="pricing discussed",
        evidence_rules="Rep frames monthly vs quarterly vs bimonthly or 60/90 day logic.",
    ),
    TechniqueCue(
        id="pitch_relevant_differentiators",
        label="Relevant differentiators",
        category="pitch_delivery",
        observable_from="transcript_observable",
        weight=0.5,
        kind="reward",
        applies_when="stalled but interested homeowner",
        evidence_rules="Rep uses eco-friendly, pet-safe, or no-contract language when it fits the conversation.",
    ),
    TechniqueCue(
        id="objection_validate_then_pivot",
        label="Validate then pivot",
        category="objection_handling",
        observable_from="reaction_observable",
        weight=0.9,
        kind="reward",
        applies_when="homeowner objects early",
        evidence_rules="Rep validates the concern and pivots to a small next step or quote.",
    ),
    TechniqueCue(
        id="objection_competitor_identification",
        label="Competitor identification and soft switchover",
        category="objection_handling",
        observable_from="transcript_observable",
        weight=0.7,
        kind="reward",
        applies_when="homeowner has provider",
        evidence_rules="Rep asks who the homeowner uses and frames soft comparison without attacking.",
    ),
    TechniqueCue(
        id="objection_price_service_fork",
        label="Price vs service fork",
        category="objection_handling",
        observable_from="transcript_observable",
        weight=0.7,
        kind="reward",
        applies_when="homeowner is unsure",
        evidence_rules="Rep isolates whether the issue is price or service confidence.",
    ),
    TechniqueCue(
        id="objection_yes_question_address_close",
        label="YES -> Question -> Address -> CLOSE",
        category="objection_handling",
        observable_from="reaction_observable",
        weight=1.0,
        kind="reward",
        applies_when="real objection appears",
        evidence_rules="Rep acknowledges, questions, addresses one fork, then re-closes.",
    ),
    TechniqueCue(
        id="objection_diy_education",
        label="DIY education with consultative follow-up",
        category="objection_handling",
        observable_from="transcript_observable",
        weight=0.5,
        kind="reward",
        applies_when="homeowner says they do it themselves",
        evidence_rules="Rep educates on residual/barrier and asks what pests they are dealing with.",
    ),
    TechniqueCue(
        id="closing_option_close",
        label="Option close",
        category="closing_technique",
        observable_from="transcript_observable",
        weight=0.8,
        kind="reward",
        applies_when="homeowner is engaged",
        evidence_rules="Rep gives two concrete options instead of a yes/no close.",
    ),
    TechniqueCue(
        id="closing_assumptive_assignment_close",
        label="Assumptive or assignment close",
        category="closing_technique",
        observable_from="transcript_observable",
        weight=0.7,
        kind="reward",
        applies_when="homeowner softens",
        evidence_rules="Rep moves to logistics, confirmation, or setup language.",
    ),
    TechniqueCue(
        id="closing_backyard_close",
        label="Backyard close",
        category="closing_technique",
        observable_from="transcript_observable",
        weight=0.6,
        kind="reward",
        applies_when="stalled but interested homeowner",
        evidence_rules="Rep uses backyard walk/proof/reset-the-close language.",
    ),
    TechniqueCue(
        id="closing_level_up_moment",
        label="Level-up moment",
        category="closing_technique",
        observable_from="transcript_observable",
        weight=0.5,
        kind="reward",
        applies_when="conversation stalls late",
        evidence_rules="Rep names the real progress in the conversation and asks what would make it easy.",
    ),
    TechniqueCue(
        id="penalty_hard_pressure_reactance",
        label="Hard-pressure reactance",
        category="closing_technique",
        observable_from="reaction_observable",
        weight=1.0,
        kind="cap",
        applies_when="pressure spikes after rep push",
        evidence_rules="Rep pushes urgency or hard close language that increases resistance.",
        cap=4.6,
    ),
    TechniqueCue(
        id="penalty_feature_dumping",
        label="Feature dumping without dialogue",
        category="pitch_delivery",
        observable_from="transcript_observable",
        weight=0.8,
        kind="cap",
        applies_when="long pitch monologue",
        evidence_rules="Rep rattles off features without property tie-in or interaction.",
        cap=5.9,
    ),
    TechniqueCue(
        id="penalty_attack_competitor",
        label="Attacks competitor directly",
        category="objection_handling",
        observable_from="transcript_observable",
        weight=0.8,
        kind="cap",
        applies_when="competitor discussion",
        evidence_rules="Rep disparages a competitor instead of soft-comparison framing.",
        cap=5.4,
    ),
    TechniqueCue(
        id="penalty_answers_both_forks",
        label="Answers both objection forks at once",
        category="objection_handling",
        observable_from="transcript_observable",
        weight=0.8,
        kind="cap",
        applies_when="homeowner is unsure",
        evidence_rules="Rep answers price and service confidence together instead of isolating the real objection.",
        cap=6.0,
    ),
    TechniqueCue(
        id="penalty_no_reclose_after_address",
        label="Fails to re-close after addressing",
        category="closing_technique",
        observable_from="reaction_observable",
        weight=0.9,
        kind="cap",
        applies_when="rep addressed a real objection",
        evidence_rules="Rep handles the concern but never asks for the next step.",
        cap=6.1,
    ),
)


class GradingTechniqueService:
    def evaluate(
        self,
        *,
        turns: list[Any],
        session_context: dict[str, Any],
        inflection_points: list[dict[str, Any]],
        base_scores: dict[str, float],
    ) -> dict[str, Any]:
        rep_turns = [turn for turn in turns if getattr(getattr(turn, "speaker", None), "value", "") == "rep"]
        ai_turns = [turn for turn in turns if getattr(getattr(turn, "speaker", None), "value", "") == "ai"]
        technique_checks = [
            self._evaluate_cue(
                cue=cue,
                turns=turns,
                rep_turns=rep_turns,
                ai_turns=ai_turns,
                session_context=session_context,
                inflection_points=inflection_points,
            )
            for cue in TECHNIQUE_CUES
        ]

        bands = {
            key: {
                "floor": round(max(0.0, min(10.0, float(base_scores.get(key, 6.0)) - 0.8)), 2),
                "ceiling": round(max(0.0, min(10.0, float(base_scores.get(key, 6.0)) + 0.8)), 2),
            }
            for key in CATEGORY_KEYS
        }

        for check in technique_checks:
            cue = next(item for item in TECHNIQUE_CUES if item.id == check.id)
            band = bands[cue.category]
            if cue.kind == "coaching_only" or cue.observable_from == "unobservable":
                continue
            if check.status == "hit":
                if cue.kind == "reward":
                    band["floor"] += cue.weight * 0.75
                    band["ceiling"] += cue.weight * 0.45
                elif cue.kind == "cap" and cue.cap is not None:
                    band["ceiling"] = min(band["ceiling"], cue.cap)
                    band["floor"] -= cue.weight * 0.35
            elif check.status == "partial":
                if cue.kind == "reward":
                    band["floor"] += cue.weight * 0.35
                    band["ceiling"] += cue.weight * 0.20
                elif cue.kind == "cap" and cue.cap is not None:
                    band["ceiling"] = min(band["ceiling"], cue.cap + 0.4)
            elif check.status == "miss":
                if cue.kind == "reward":
                    band["ceiling"] -= cue.weight * 0.40
                elif cue.kind == "cap" and cue.cap is not None:
                    band["ceiling"] = min(band["ceiling"], cue.cap)
                    band["floor"] -= cue.weight * 0.45

        call_quality, call_quality_score = self._compute_call_quality(
            rep_turns=rep_turns,
            ai_turns=ai_turns,
            technique_checks=technique_checks,
        )
        max_width = {"strong": 0.4, "moderate": 0.8, "weak": 1.2}[call_quality]
        provisional = call_quality == "weak"

        anchor_scores: dict[str, float] = {}
        for key, band in bands.items():
            floor = max(0.0, min(10.0, float(band["floor"])))
            ceiling = max(0.0, min(10.0, float(band["ceiling"])))
            if ceiling < floor:
                ceiling = floor
            width = ceiling - floor
            if width > max_width:
                floor = max(floor, ceiling - max_width)
            anchor_scores[key] = round((floor + ceiling) / 2.0, 1)
            band["floor"] = round(floor, 2)
            band["ceiling"] = round(ceiling, 2)
            band["anchor"] = anchor_scores[key]
            band["max_width"] = max_width

        message = (
            "This grade is provisional because the call evidence is thin."
            if provisional
            else "This grade is grounded in technique checks against the playbook."
        )
        return {
            "technique_checks": [check.to_dict() for check in technique_checks],
            "bands": bands,
            "anchor_scores": anchor_scores,
            "call_quality": call_quality,
            "call_quality_score": round(call_quality_score, 3),
            "provisional": provisional,
            "message": message,
        }

    def _evaluate_cue(
        self,
        *,
        cue: TechniqueCue,
        turns: list[Any],
        rep_turns: list[Any],
        ai_turns: list[Any],
        session_context: dict[str, Any],
        inflection_points: list[dict[str, Any]],
    ) -> TechniqueCheck:
        if cue.observable_from == "unobservable":
            return TechniqueCheck(
                id=cue.id,
                label=cue.label,
                category=cue.category,
                status="unknown",
                kind=cue.kind,
                observable_from=cue.observable_from,
                evidence_turn_ids=[],
                notes="Not directly observable from transcript or reaction data.",
            )

        cue_id = cue.id
        if cue_id == "opening_neighbor_route_frame":
            first_turn = rep_turns[0] if rep_turns else None
            if first_turn is None:
                return self._simple_check(cue, "miss", [])
            text = self._turn_text(first_turn)
            signals = self._turn_signals(first_turn)
            if self._contains_any(text, NEIGHBOR_HINTS) and ("mentions_social_proof" in signals or "builds_rapport" in signals):
                return self._simple_check(cue, "hit", [first_turn.id])
            if "mentions_social_proof" in signals or self._contains_any(text, NEIGHBOR_HINTS):
                return self._simple_check(cue, "partial", [first_turn.id])
            return self._simple_check(cue, "miss", [first_turn.id])

        if cue_id == "opening_low_pressure_quote_pivot":
            trigger_turn = self._find_turn(ai_turns, ("not interested", "not interested.", "no thanks"))
            if trigger_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            pivot_turn = self._find_following_turn(rep_turns, trigger_turn, QUOTE_PIVOT_HINTS)
            if pivot_turn is not None:
                return self._simple_check(cue, "hit", [pivot_turn.id])
            validating_turn = self._find_following_turn(rep_turns, trigger_turn, ACKNOWLEDGEMENT_HINTS)
            if validating_turn is not None:
                return self._simple_check(cue, "partial", [validating_turn.id])
            return self._simple_check(cue, "miss", [])

        if cue_id == "pitch_observed_pest_evidence":
            evidence_turns = [turn.id for turn in rep_turns if self._contains_any(self._turn_text(turn), PEST_EVIDENCE_HINTS)]
            if evidence_turns:
                return self._simple_check(cue, "hit", evidence_turns[:2])
            if any("explains_value" in self._turn_signals(turn) for turn in rep_turns):
                return self._simple_check(cue, "partial", [turn.id for turn in rep_turns[:1]])
            return self._simple_check(cue, "miss", [])

        if cue_id == "pitch_feature_benefit_soft_close":
            hits: list[str] = []
            partial = False
            for turn in rep_turns:
                text = self._turn_text(turn)
                has_feature = self._contains_any(text, FEATURE_HINTS)
                has_benefit = self._contains_any(text, BENEFIT_HINTS) or "explains_value" in self._turn_signals(turn)
                has_soft_close = "?" in text or self._contains_any(text, SOFT_CLOSE_HINTS)
                if has_feature and has_benefit and has_soft_close:
                    hits.append(turn.id)
                elif (has_feature and has_benefit) or (has_feature and has_soft_close):
                    partial = True
            if hits:
                return self._simple_check(cue, "hit", hits[:2])
            if partial:
                return self._simple_check(cue, "partial", [rep_turns[0].id] if rep_turns else [])
            return self._simple_check(cue, "miss", [])

        if cue_id == "pitch_bimonthly_value_anchor":
            pricing_turn = self._find_turn(rep_turns, ("60 days", "90 days", "bimonthly", "quarterly", "monthly"))
            if pricing_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            text = self._turn_text(pricing_turn)
            if ("monthly" in text and "quarterly" in text) or "bimonthly" in text or "60 days" in text:
                return self._simple_check(cue, "hit", [pricing_turn.id])
            if self._contains_any(text, PRICE_HINTS):
                return self._simple_check(cue, "partial", [pricing_turn.id])
            return self._simple_check(cue, "miss", [pricing_turn.id])

        if cue_id == "pitch_relevant_differentiators":
            relevant_turn = self._find_turn(rep_turns, ("pet", "kid safe", "no annual contract", "month to month", "cancel anytime"))
            if relevant_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            text = self._turn_text(relevant_turn)
            if self._contains_any(text, ("pet", "kid safe", "month to month", "cancel anytime")):
                return self._simple_check(cue, "hit", [relevant_turn.id])
            return self._simple_check(cue, "partial", [relevant_turn.id])

        if cue_id == "objection_validate_then_pivot":
            early_objection = self._find_turn(ai_turns, ("not interested", "no thanks", "already have a guy"))
            if early_objection is None:
                return self._simple_check(cue, "not_applicable", [])
            response = self._find_following_turn(rep_turns, early_objection, ACKNOWLEDGEMENT_HINTS)
            if response is None:
                return self._simple_check(cue, "miss", [])
            if self._contains_any(self._turn_text(response), QUOTE_PIVOT_HINTS) or "?" in self._turn_text(response):
                return self._simple_check(cue, "hit", [response.id])
            return self._simple_check(cue, "partial", [response.id])

        if cue_id == "objection_competitor_identification":
            competitor_turn = self._find_turn(ai_turns, ("have a guy", "another company", "already use", "already have service"))
            if competitor_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            follow = self._find_following_turn(rep_turns, competitor_turn, ("who do you have", "how long have you been with"))
            if follow is not None:
                return self._simple_check(cue, "hit", [follow.id])
            soft_compare = self._find_following_turn(rep_turns, competitor_turn, COMPETITOR_HINTS)
            if soft_compare is not None:
                return self._simple_check(cue, "partial", [soft_compare.id])
            return self._simple_check(cue, "miss", [])

        if cue_id == "objection_price_service_fork":
            unsure_turn = self._find_turn(ai_turns, ("not sure", "maybe later", "budget", "don't know if i need"))
            if unsure_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            follow = self._find_following_turn(rep_turns, unsure_turn, ("is it the price", "price or", "what's the main thing"))
            if follow is not None:
                return self._simple_check(cue, "hit", [follow.id])
            if self._find_following_turn(rep_turns, unsure_turn, PRICE_HINTS + SERVICE_HINTS) is not None:
                return self._simple_check(cue, "partial", [])
            return self._simple_check(cue, "miss", [])

        if cue_id == "objection_yes_question_address_close":
            objection_turns = [turn for turn in ai_turns if self._looks_like_objection(turn)]
            if not objection_turns:
                return self._simple_check(cue, "not_applicable", [])
            evidence: list[str] = []
            for objection_turn in objection_turns:
                response = self._find_following_turn(rep_turns, objection_turn, ACKNOWLEDGEMENT_HINTS)
                if response is None:
                    continue
                text = self._turn_text(response)
                if "?" in text and self._contains_any(text, CLOSE_HINTS):
                    evidence.append(response.id)
            if evidence:
                return self._simple_check(cue, "hit", evidence[:2])
            if any(self._find_following_turn(rep_turns, objection_turn, ACKNOWLEDGEMENT_HINTS) for objection_turn in objection_turns):
                return self._simple_check(cue, "partial", [])
            return self._simple_check(cue, "miss", [])

        if cue_id == "objection_diy_education":
            diy_turn = self._find_turn(ai_turns, ("do it ourselves", "do it myself", "do it ourselves already"))
            if diy_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            response = self._find_following_turn(rep_turns, diy_turn, DIY_HINTS)
            if response is not None:
                text = self._turn_text(response)
                if "what are you mainly dealing with" in text or "ants" in text or "spiders" in text:
                    return self._simple_check(cue, "hit", [response.id])
                return self._simple_check(cue, "partial", [response.id])
            return self._simple_check(cue, "miss", [])

        if cue_id == "closing_option_close":
            close_turn = self._find_turn(rep_turns, OPTION_CLOSE_HINTS)
            if close_turn is not None:
                return self._simple_check(cue, "hit", [close_turn.id])
            generic_close = self._find_turn(rep_turns, CLOSE_HINTS)
            if generic_close is not None:
                return self._simple_check(cue, "partial", [generic_close.id])
            return self._simple_check(cue, "miss", [])

        if cue_id == "closing_assumptive_assignment_close":
            close_turn = self._find_turn(rep_turns, ASSUMPTIVE_CLOSE_HINTS)
            if close_turn is not None:
                return self._simple_check(cue, "hit", [close_turn.id])
            return self._simple_check(cue, "not_applicable", [])

        if cue_id == "closing_backyard_close":
            close_turn = self._find_turn(rep_turns, BACKYARD_CLOSE_HINTS)
            if close_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            return self._simple_check(cue, "hit", [close_turn.id])

        if cue_id == "closing_level_up_moment":
            close_turn = self._find_turn(rep_turns, LEVEL_UP_HINTS)
            if close_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            return self._simple_check(cue, "hit", [close_turn.id])

        if cue_id == "penalty_hard_pressure_reactance":
            hard_turn = next(
                (
                    turn
                    for turn in rep_turns
                    if "pushes_close" in self._turn_signals(turn) or self._contains_any(self._turn_text(turn), HARD_PRESSURE_HINTS)
                ),
                None,
            )
            if hard_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            increased_resistance = any(point.get("direction") == "negative" for point in inflection_points)
            return self._simple_check(cue, "hit" if increased_resistance else "partial", [hard_turn.id])

        if cue_id == "penalty_feature_dumping":
            dump_turn = next(
                (
                    turn
                    for turn in rep_turns
                    if len(self._turn_text(turn)) >= 180 and "?" not in self._turn_text(turn) and "," in self._turn_text(turn)
                ),
                None,
            )
            if dump_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            return self._simple_check(cue, "hit", [dump_turn.id])

        if cue_id == "penalty_attack_competitor":
            attack_turn = self._find_turn(rep_turns, ATTACK_COMPETITOR_HINTS)
            if attack_turn is None:
                return self._simple_check(cue, "not_applicable", [])
            return self._simple_check(cue, "hit", [attack_turn.id])

        if cue_id == "penalty_answers_both_forks":
            candidate = next(
                (
                    turn
                    for turn in rep_turns
                    if self._contains_any(self._turn_text(turn), PRICE_HINTS)
                    and self._contains_any(self._turn_text(turn), SERVICE_HINTS)
                ),
                None,
            )
            if candidate is None:
                return self._simple_check(cue, "not_applicable", [])
            return self._simple_check(cue, "hit", [candidate.id])

        if cue_id == "penalty_no_reclose_after_address":
            objection_present = any(self._looks_like_objection(turn) for turn in ai_turns)
            if not objection_present:
                return self._simple_check(cue, "not_applicable", [])
            addressed = any(
                "acknowledges_concern" in self._turn_signals(turn) or self._contains_any(self._turn_text(turn), ACKNOWLEDGEMENT_HINTS)
                for turn in rep_turns
            )
            if not addressed:
                return self._simple_check(cue, "not_applicable", [])
            close_present = any(
                "close_attempt" in str(getattr(turn, "stage", ""))
                or self._contains_any(self._turn_text(turn), CLOSE_HINTS + OPTION_CLOSE_HINTS + ASSUMPTIVE_CLOSE_HINTS)
                for turn in rep_turns
            )
            if close_present:
                return self._simple_check(cue, "not_applicable", [])
            return self._simple_check(cue, "hit", [rep_turns[-1].id] if rep_turns else [])

        return self._simple_check(cue, "unknown", [])

    def _compute_call_quality(
        self,
        *,
        rep_turns: list[Any],
        ai_turns: list[Any],
        technique_checks: list[TechniqueCheck],
    ) -> tuple[str, float]:
        if not rep_turns:
            return "weak", 0.0
        rep_turn_count = len(rep_turns)
        stage_hits = {
            "opening": any(str(getattr(turn, "stage", "")) in {"door_knock", "opening", "initial_pitch"} for turn in rep_turns),
            "pitch_delivery": any(str(getattr(turn, "stage", "")) in {"pitch", "initial_pitch", "value_prop"} for turn in rep_turns),
            "objection_handling": any(str(getattr(turn, "stage", "")) == "objection_handling" or bool(getattr(turn, "objection_tags", None)) for turn in rep_turns + ai_turns),
            "closing_technique": any(str(getattr(turn, "stage", "")) in {"close_attempt", "closing"} for turn in rep_turns),
        }
        stage_coverage = sum(1 for value in stage_hits.values() if value) / float(len(stage_hits))
        transcript_confidences = [
            float(getattr(turn, "transcript_confidence", 0.0) or 0.0)
            for turn in rep_turns
            if getattr(turn, "transcript_confidence", None) is not None
        ]
        transcript_quality = sum(transcript_confidences) / len(transcript_confidences) if transcript_confidences else 0.55
        evidence_count = sum(len(check.evidence_turn_ids) for check in technique_checks if check.status in {"hit", "partial"})
        evidence_density = min(1.0, evidence_count / max(1.0, rep_turn_count * 1.5))
        reaction_clarity = min(
            1.0,
            len(
                [
                    turn
                    for turn in ai_turns
                    if getattr(turn, "emotion_before", None)
                    or getattr(turn, "emotion_after", None)
                    or getattr(turn, "objection_pressure", None) is not None
                ]
            )
            / max(1.0, len(ai_turns)),
        ) if ai_turns else 0.5
        score = min(
            1.0,
            (min(1.0, rep_turn_count / 8.0) * 0.25)
            + (stage_coverage * 0.25)
            + (evidence_density * 0.20)
            + (reaction_clarity * 0.15)
            + (transcript_quality * 0.15),
        )
        if score >= 0.72:
            return "strong", score
        if score >= 0.45:
            return "moderate", score
        return "weak", score

    def _simple_check(self, cue: TechniqueCue, status: str, evidence_turn_ids: list[str]) -> TechniqueCheck:
        return TechniqueCheck(
            id=cue.id,
            label=cue.label,
            category=cue.category,
            status=status,
            kind=cue.kind,
            observable_from=cue.observable_from,
            evidence_turn_ids=list(dict.fromkeys(evidence_turn_ids)),
        )

    def _find_turn(self, turns: list[Any], hints: tuple[str, ...]) -> Any | None:
        for turn in turns:
            if self._contains_any(self._turn_text(turn), hints):
                return turn
        return None

    def _find_following_turn(self, rep_turns: list[Any], trigger_turn: Any, hints: tuple[str, ...]) -> Any | None:
        trigger_index = int(getattr(trigger_turn, "turn_index", 0) or 0)
        for turn in rep_turns:
            if int(getattr(turn, "turn_index", 0) or 0) <= trigger_index:
                continue
            if self._contains_any(self._turn_text(turn), hints):
                return turn
        return None

    def _looks_like_objection(self, turn: Any) -> bool:
        text = self._turn_text(turn)
        return bool(
            getattr(turn, "objection_tags", None)
            or self._contains_any(
                text,
                (
                    "not interested",
                    "already have",
                    "already use",
                    "budget",
                    "not sure",
                    "think about it",
                    "talk to my spouse",
                    "do it ourselves",
                ),
            )
        )

    def _turn_text(self, turn: Any) -> str:
        return str(getattr(turn, "text", "") or "").strip().lower()

    def _turn_signals(self, turn: Any) -> set[str]:
        values: list[str] = []
        for source in (getattr(turn, "behavioral_signals", None) or [], getattr(turn, "mb_behaviors", None) or []):
            if isinstance(source, list):
                values.extend(str(item).strip().lower() for item in source if str(item).strip())
        return set(values)

    def _contains_any(self, text: str, hints: tuple[str, ...]) -> bool:
        return any(hint in text for hint in hints)
