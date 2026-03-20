from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.org_prompt_config import OrgPromptConfig
    from app.models.scenario import Scenario


MULTISPACE_RE = re.compile(r"\s+")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:?!])")
TOKEN_RE = re.compile(r"\b[a-z0-9][a-z0-9&'.-]*\b", re.IGNORECASE)
DEFAULT_PRICING_TERMS = (
    "monthly plan",
    "monthly payment",
    "service plan",
    "free inspection",
    "free quote",
    "warranty",
    "guarantee",
    "discount",
    "contract",
)
DEFAULT_DOMAIN_TERMS = (
    "pest control",
    "service agreement",
    "recurring service",
    "exterior treatment",
    "interior treatment",
    "yard treatment",
)
PHONETIC_CORRECTION_TABLE: dict[str, str] = {
    "or kin": "Orkin",
    "orkin's": "Orkin",
    "pick control": "pest control",
    "pick controlled": "pest control",
    "arrow sol": "aerosol",
    "arrow sols": "aerosols",
    "ante": "ant",
    "aunty": "ant",
    "the ante": "the ant",
    "termite inspection": "termite inspection",
    "road ant": "rodent",
    "road ants": "rodents",
    "the road": "the rodent",
    "home warning": "home warranty",
    "free in spec shin": "free inspection",
    "free inspect shin": "free inspection",
    "in spec shun": "inspection",
    "ex terminator": "exterminator",
    "ex terminate": "exterminate",
    "service agreement": "service agreement",
    "serve is": "service",
}
DEFAULT_FUZZY_MATCH_THRESHOLD = 0.8
ORG_SPECIFIC_FUZZY_MATCH_THRESHOLD = 0.75


@dataclass
class TranscriptNormalizationResult:
    raw_text: str
    normalized_text: str
    provider: str
    confidence: float
    applied_terms: list[str] = field(default_factory=list)
    normalization_source: str = "heuristic"


class TranscriptNormalizationService:
    """Normalize raw STT text using org, scenario, and objection vocabulary."""

    def keyword_hints(
        self,
        *,
        scenario: "Scenario | None" = None,
        org_config: "OrgPromptConfig | None" = None,
        active_objections: list[str] | None = None,
        queued_objections: list[str] | None = None,
        max_terms: int = 12,
    ) -> list[str]:
        terms = self._canonical_terms(
            scenario=scenario,
            org_config=org_config,
            active_objections=active_objections,
            queued_objections=queued_objections,
        )
        return terms[:max_terms]

    def normalize(
        self,
        *,
        text: str,
        provider: str,
        confidence: float,
        scenario: "Scenario | None" = None,
        org_config: "OrgPromptConfig | None" = None,
        active_objections: list[str] | None = None,
        queued_objections: list[str] | None = None,
    ) -> TranscriptNormalizationResult:
        raw_text = " ".join(str(text or "").split()).strip()
        normalized_text = raw_text
        applied_terms: list[str] = []

        if normalized_text:
            normalized_text = MULTISPACE_RE.sub(" ", normalized_text)
            normalized_text = SPACE_BEFORE_PUNCT_RE.sub(r"\1", normalized_text)

        canonical_terms = self._canonical_terms(
            scenario=scenario,
            org_config=org_config,
            active_objections=active_objections,
            queued_objections=queued_objections,
        )
        org_specific_terms = self._org_specific_terms(org_config)
        if normalized_text and canonical_terms:
            normalized_text, phonetic_terms = self._apply_phonetic_corrections(normalized_text)
            normalized_text, applied_terms = self._apply_fuzzy_term_corrections(
                normalized_text,
                canonical_terms,
                org_specific_terms=org_specific_terms,
            )
            applied_terms = list(dict.fromkeys([*phonetic_terms, *applied_terms]))

        normalized_text = normalized_text.strip()
        return TranscriptNormalizationResult(
            raw_text=raw_text,
            normalized_text=normalized_text or raw_text,
            provider=provider,
            confidence=round(float(confidence or 0.0), 4),
            applied_terms=applied_terms,
        )

    def _canonical_terms(
        self,
        *,
        scenario: "Scenario | None",
        org_config: "OrgPromptConfig | None",
        active_objections: list[str] | None,
        queued_objections: list[str] | None,
    ) -> list[str]:
        ordered: list[str] = []

        def add_term(value: Any) -> None:
            normalized = " ".join(str(value or "").split()).strip()
            if len(normalized) < 3:
                return
            lowered = normalized.lower()
            if lowered not in {existing.lower() for existing in ordered}:
                ordered.append(normalized)

        if org_config is not None:
            add_term(org_config.company_name)
            add_term(org_config.product_category)
            add_term(org_config.close_style)
            add_term(org_config.rep_tone_guidance)
            for competitor in org_config.competitors or []:
                if isinstance(competitor, dict):
                    add_term(competitor.get("name"))
                    add_term(competitor.get("key_differentiator"))
            for objection in org_config.known_objections or []:
                if isinstance(objection, dict):
                    add_term(objection.get("objection"))
                    add_term(objection.get("preferred_rebuttal_hint"))

        if scenario is not None:
            add_term(getattr(scenario, "name", None))
            persona = dict(getattr(scenario, "persona", {}) or {})
            add_term(persona.get("name"))
            for key in ("concerns", "objection_queue", "objections", "pest_history"):
                for item in persona.get(key, []) or []:
                    add_term(item)

        for objection in active_objections or []:
            add_term(str(objection).replace("_", " "))
        for objection in queued_objections or []:
            add_term(str(objection).replace("_", " "))

        for term in DEFAULT_PRICING_TERMS:
            add_term(term)
        for term in DEFAULT_DOMAIN_TERMS:
            add_term(term)

        return ordered

    def _org_specific_terms(self, org_config: "OrgPromptConfig | None") -> set[str]:
        if org_config is None:
            return set()

        terms: set[str] = set()

        def add_term(value: Any) -> None:
            normalized = " ".join(str(value or "").split()).strip()
            if len(normalized) >= 3:
                terms.add(normalized.lower())

        add_term(org_config.company_name)
        add_term(org_config.product_category)
        for competitor in org_config.competitors or []:
            if isinstance(competitor, dict):
                add_term(competitor.get("name"))
                add_term(competitor.get("key_differentiator"))

        return terms

    def _apply_phonetic_corrections(self, text: str) -> tuple[str, list[str]]:
        rewritten = text
        applied_terms: list[str] = []

        for wrong, correct in sorted(
            PHONETIC_CORRECTION_TABLE.items(),
            key=lambda item: (-len(item[0].split()), -len(item[0])),
        ):
            if wrong.lower() == correct.lower():
                continue
            pattern = re.compile(r"\b" + re.escape(wrong) + r"\b", re.IGNORECASE)
            if not pattern.search(rewritten):
                continue
            rewritten = pattern.sub(correct, rewritten)
            applied_terms.append(correct)

        return rewritten, list(dict.fromkeys(applied_terms))

    def _apply_fuzzy_term_corrections(
        self,
        text: str,
        canonical_terms: list[str],
        *,
        org_specific_terms: set[str] | None = None,
    ) -> tuple[str, list[str]]:
        tokens = list(TOKEN_RE.finditer(text))
        if not tokens:
            return text, []

        rewritten = text
        applied_terms: list[str] = []

        single_token_terms = {
            term.lower(): term
            for term in canonical_terms
            if len(term.split()) == 1 and len(term) >= 4
        }
        multi_token_terms = [term for term in canonical_terms if len(term.split()) > 1]

        # Rewrite obvious multi-word phrases only when the phrase already appears.
        for canonical in multi_token_terms:
            flexible_pattern = re.compile(
                r"\b" + r"\s+".join(re.escape(part) for part in canonical.split()) + r"\b",
                re.IGNORECASE,
            )
            if flexible_pattern.search(rewritten):
                rewritten = flexible_pattern.sub(canonical, rewritten)
                applied_terms.append(canonical)

        if not single_token_terms:
            return rewritten, applied_terms

        updated_parts: list[str] = []
        last_end = 0
        for match in TOKEN_RE.finditer(rewritten):
            updated_parts.append(rewritten[last_end:match.start()])
            token = match.group(0)
            replacement = self._closest_token_match(
                token,
                single_token_terms,
                org_specific_terms=org_specific_terms or set(),
            )
            updated_parts.append(replacement or token)
            if replacement and replacement != token:
                applied_terms.append(replacement)
            last_end = match.end()
        updated_parts.append(rewritten[last_end:])

        normalized = "".join(updated_parts)
        deduped_applied_terms = list(dict.fromkeys(applied_terms))
        return normalized, deduped_applied_terms

    def _closest_token_match(
        self,
        token: str,
        single_token_terms: dict[str, str],
        *,
        org_specific_terms: set[str],
    ) -> str | None:
        lowered = token.lower()
        if lowered in single_token_terms:
            return single_token_terms[lowered]
        if len(lowered) < 4:
            return None

        best: tuple[float, str] | None = None
        for normalized, canonical in single_token_terms.items():
            ratio = SequenceMatcher(None, lowered, normalized).ratio()
            threshold = (
                ORG_SPECIFIC_FUZZY_MATCH_THRESHOLD
                if normalized in org_specific_terms
                else DEFAULT_FUZZY_MATCH_THRESHOLD
            )
            if ratio < threshold:
                continue
            if best is None or ratio > best[0]:
                best = (ratio, canonical)
        return best[1] if best is not None else None
