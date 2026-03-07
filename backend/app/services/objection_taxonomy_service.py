from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.transcript import ObjectionType


@dataclass(frozen=True)
class ObjectionSeed:
    tag: str
    display_name: str
    category: str
    difficulty_weight: float
    industry: str | None
    typical_phrases: list[str]
    resolution_techniques: list[str]
    version: str = "1.0"


CANONICAL_OBJECTION_TYPES: list[ObjectionSeed] = [
    ObjectionSeed(
        tag="price",
        display_name="Price Objection",
        category="price",
        difficulty_weight=0.72,
        industry="pest_control",
        typical_phrases=["It's too expensive", "Your price is too high"],
        resolution_techniques=["Acknowledge budget pressure", "Anchor to service value and ongoing protection"],
    ),
    ObjectionSeed(
        tag="price_per_month",
        display_name="Monthly Cost Pushback",
        category="price",
        difficulty_weight=0.66,
        industry="pest_control",
        typical_phrases=["I don't want another monthly bill", "That's too much per month"],
        resolution_techniques=["Break cost into a manageable comparison", "Tie price to convenience and prevention"],
    ),
    ObjectionSeed(
        tag="price_vs_competitor",
        display_name="Competitor Price Comparison",
        category="price",
        difficulty_weight=0.74,
        industry="pest_control",
        typical_phrases=["Another company is cheaper", "I can get this cheaper online"],
        resolution_techniques=["Differentiate service quality", "Explain what cheaper alternatives leave out"],
    ),
    ObjectionSeed(
        tag="incumbent_provider",
        display_name="Already Has a Provider",
        category="incumbent",
        difficulty_weight=0.61,
        industry="pest_control",
        typical_phrases=["We already use someone", "I'm already covered"],
        resolution_techniques=["Uncover service gaps", "Lower the switching-risk perception"],
    ),
    ObjectionSeed(
        tag="locked_in_contract",
        display_name="Locked Into Contract",
        category="incumbent",
        difficulty_weight=0.79,
        industry="pest_control",
        typical_phrases=["We're under contract", "I can't switch right now"],
        resolution_techniques=["Offer future-timing options", "Frame discovery as low commitment"],
    ),
    ObjectionSeed(
        tag="timing",
        display_name="Bad Timing",
        category="timing",
        difficulty_weight=0.58,
        industry="pest_control",
        typical_phrases=["Now isn't a good time", "Maybe later"],
        resolution_techniques=["Shorten the ask", "Offer a concise follow-up step"],
    ),
    ObjectionSeed(
        tag="not_right_now",
        display_name="Not Ready Right Now",
        category="timing",
        difficulty_weight=0.52,
        industry="pest_control",
        typical_phrases=["Not right now", "Come back another time"],
        resolution_techniques=["Reduce urgency pressure", "Earn a future permissioned touchpoint"],
    ),
    ObjectionSeed(
        tag="busy",
        display_name="Too Busy",
        category="timing",
        difficulty_weight=0.49,
        industry="pest_control",
        typical_phrases=["I'm busy", "I don't have time for this"],
        resolution_techniques=["Lead with brevity", "Give one sharp reason to stay engaged"],
    ),
    ObjectionSeed(
        tag="trust",
        display_name="Trust / Credibility Concern",
        category="trust",
        difficulty_weight=0.77,
        industry="pest_control",
        typical_phrases=["How do I know this is legit?", "I don't trust door-to-door sales"],
        resolution_techniques=["Use proof and specificity", "Stay calm and transparent"],
    ),
    ObjectionSeed(
        tag="skeptical_of_product",
        display_name="Skeptical of Product Claims",
        category="trust",
        difficulty_weight=0.71,
        industry="pest_control",
        typical_phrases=["That sounds too good to be true", "I doubt it works that well"],
        resolution_techniques=["Use concrete outcomes", "Explain how service works in practice"],
    ),
    ObjectionSeed(
        tag="skeptical_of_rep",
        display_name="Skeptical of the Rep",
        category="trust",
        difficulty_weight=0.75,
        industry="pest_control",
        typical_phrases=["You all say the same thing", "You just want a sale"],
        resolution_techniques=["Acknowledge skepticism directly", "Shift from pressure to clarity"],
    ),
    ObjectionSeed(
        tag="need",
        display_name="No Need",
        category="need",
        difficulty_weight=0.57,
        industry="pest_control",
        typical_phrases=["We don't have pest problems", "We don't need this"],
        resolution_techniques=["Surface hidden risk", "Explain preventative value without fear tactics"],
    ),
    ObjectionSeed(
        tag="no_pest_problem",
        display_name="No Current Pest Problem",
        category="need",
        difficulty_weight=0.54,
        industry="pest_control",
        typical_phrases=["I haven't seen anything", "We don't have bugs right now"],
        resolution_techniques=["Frame prevention clearly", "Tie service to peace of mind"],
    ),
    ObjectionSeed(
        tag="decision_authority",
        display_name="Needs Another Decision Maker",
        category="spouse",
        difficulty_weight=0.68,
        industry="pest_control",
        typical_phrases=["I need to talk to my spouse", "I need to ask the landlord"],
        resolution_techniques=["Offer a spouse-friendly summary", "Aim for a low-pressure next step"],
    ),
]


class ObjectionTaxonomyService:
    def ensure_seed_data(self, db: Session) -> bool:
        changed = False
        for seed in CANONICAL_OBJECTION_TYPES:
            row = db.scalar(
                select(ObjectionType).where(
                    ObjectionType.org_id.is_(None),
                    ObjectionType.tag == seed.tag,
                )
            )
            if row is None:
                db.add(
                    ObjectionType(
                        org_id=None,
                        tag=seed.tag,
                        display_name=seed.display_name,
                        category=seed.category,
                        difficulty_weight=seed.difficulty_weight,
                        industry=seed.industry,
                        typical_phrases=list(seed.typical_phrases),
                        resolution_techniques=list(seed.resolution_techniques),
                        version=seed.version,
                        active=True,
                    )
                )
                changed = True
                continue

            desired_phrases = list(seed.typical_phrases)
            desired_techniques = list(seed.resolution_techniques)
            if (
                row.display_name != seed.display_name
                or row.category != seed.category
                or row.difficulty_weight != seed.difficulty_weight
                or row.industry != seed.industry
                or row.typical_phrases != desired_phrases
                or row.resolution_techniques != desired_techniques
                or row.version != seed.version
                or row.active is not True
            ):
                row.display_name = seed.display_name
                row.category = seed.category
                row.difficulty_weight = seed.difficulty_weight
                row.industry = seed.industry
                row.typical_phrases = desired_phrases
                row.resolution_techniques = desired_techniques
                row.version = seed.version
                row.active = True
                changed = True
        return changed

    def list_types(self, db: Session, *, org_id: str | None, industry: str | None = None) -> list[ObjectionType]:
        stmt = select(ObjectionType).where(ObjectionType.active.is_(True))
        if org_id:
            stmt = stmt.where(or_(ObjectionType.org_id.is_(None), ObjectionType.org_id == org_id))
        else:
            stmt = stmt.where(ObjectionType.org_id.is_(None))
        if industry:
            stmt = stmt.where(or_(ObjectionType.industry.is_(None), ObjectionType.industry == industry))
        return db.scalars(
            stmt.order_by(ObjectionType.category.asc(), ObjectionType.display_name.asc(), ObjectionType.created_at.asc())
        ).all()
