from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.transcript import ObjectionType
from app.services.objection_taxonomy_service import CANONICAL_OBJECTION_TYPES, ObjectionTaxonomyService


def test_objection_taxonomy_seed_populates_required_system_defaults():
    db = SessionLocal()
    try:
        service = ObjectionTaxonomyService()

        changed_first = service.ensure_seed_data(db)
        db.commit()
        changed_second = service.ensure_seed_data(db)
        db.commit()

        rows = db.scalars(
            select(ObjectionType)
            .where(ObjectionType.org_id.is_(None), ObjectionType.active.is_(True))
            .order_by(ObjectionType.tag.asc())
        ).all()
        tags = {row.tag for row in rows}

        assert changed_first is True
        assert changed_second is False
        assert {seed.tag for seed in CANONICAL_OBJECTION_TYPES}.issubset(tags)
        assert {
            "price",
            "price_per_month",
            "incumbent_provider",
            "locked_in_contract",
            "timing",
            "not_right_now",
            "trust",
            "skeptical_of_product",
            "need",
            "decision_authority",
        }.issubset(tags)

        price = next(row for row in rows if row.tag == "price")
        assert price.industry == "pest_control"
        assert price.typical_phrases
        assert price.resolution_techniques
    finally:
        db.close()
