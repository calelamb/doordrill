from __future__ import annotations

from app.db.session import SessionLocal
from app.models.transcript import ObjectionType
from app.services.objection_taxonomy_service import ObjectionTaxonomyService


def test_objection_types_endpoint_returns_seeded_taxonomy(client, seed_org):
    response = client.get(
        "/scenarios/objection-types",
        params={"industry": "pest_control"},
        headers={
            "x-user-id": seed_org["manager_id"],
            "x-user-role": "manager",
        },
    )

    assert response.status_code == 200
    body = response.json()
    tags = {item["tag"] for item in body}

    assert "price" in tags
    assert "incumbent_provider" in tags
    assert "decision_authority" in tags
    assert all(item["industry"] in {None, "pest_control"} for item in body)


def test_objection_types_endpoint_prefers_org_override_over_system_default(client, seed_org):
    db = SessionLocal()
    try:
        service = ObjectionTaxonomyService()
        if service.ensure_seed_data(db):
            db.commit()

        db.add(
            ObjectionType(
                org_id=seed_org["org_id"],
                tag="price",
                display_name="Custom Price Pushback",
                category="price",
                difficulty_weight=0.91,
                industry="pest_control",
                typical_phrases=["Your monthly rate is still too high for us."],
                resolution_techniques=["Lead with ROI proof"],
                version="2.0",
                active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/scenarios/objection-types",
        params={"industry": "pest_control"},
        headers={
            "x-user-id": seed_org["manager_id"],
            "x-user-role": "manager",
        },
    )

    assert response.status_code == 200
    body = response.json()
    price_rows = [item for item in body if item["tag"] == "price"]

    assert len(price_rows) == 1
    assert price_rows[0]["org_id"] == seed_org["org_id"]
    assert price_rows[0]["display_name"] == "Custom Price Pushback"
