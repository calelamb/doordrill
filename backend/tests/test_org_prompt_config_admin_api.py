from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.prompt_version import PromptVersion


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def test_org_prompt_config_preview_and_publish_generate_org_scoped_prompt_versions(client, seed_org):
    headers = _manager_headers(seed_org)
    payload = {
        "company_name": "Acme Solar",
        "product_category": "residential solar",
        "product_description": "Solar panels and battery backup for suburban homeowners.",
        "pitch_stages": ["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
        "unique_selling_points": ["No upfront cost", "Battery backup"],
        "known_objections": [
            {
                "objection": "I need to think about it",
                "preferred_rebuttal_hint": "Acknowledge the hesitation and offer a low-pressure next step.",
            }
        ],
        "target_demographics": {
            "age_range": "35-65",
            "homeowner_type": "suburban",
            "common_concerns": ["cost", "installation disruption"],
        },
        "competitors": [{"name": "SunPower", "key_differentiator": "We include battery backup."}],
        "pricing_framing": "Pricing depends on system size after a site survey.",
        "close_style": "consultative",
        "rep_tone_guidance": "professional_warm",
        "grading_priorities": ["rapport_building", "objection_handling", "close_attempt"],
    }

    update_response = client.put(
        f"/admin/orgs/{seed_org['org_id']}/prompt-config",
        headers=headers,
        json=payload,
    )
    assert update_response.status_code == 200
    assert update_response.json()["published"] is False

    preview_response = client.get(
        f"/admin/orgs/{seed_org['org_id']}/prompt-config/preview",
        headers=headers,
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["config"]["published"] is False
    assert "=== COMPANY CONTEXT ===" in preview["layer_0_preview"]
    assert "Acme Solar" in preview["conversation_prompt"]
    assert preview["system_prompt_token_count"] > 0

    publish_response = client.post(
        f"/admin/orgs/{seed_org['org_id']}/prompt-config/publish",
        headers=headers,
    )
    assert publish_response.status_code == 200
    published = publish_response.json()
    assert published["config"]["published"] is True
    assert set(published["prompt_versions"]) == {"conversation", "grading", "coaching"}
    assert published["prompt_versions"]["conversation"]["org_id"] == seed_org["org_id"]
    assert published["prompt_versions"]["grading"]["prompt_type"] == "grading_v2"
    assert published["prompt_versions"]["coaching"]["active"] is True

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(PromptVersion)
            .where(PromptVersion.org_id == seed_org["org_id"])
            .where(PromptVersion.active.is_(True))
        ).all()
        prompt_map = {row.prompt_type: row for row in rows}
        assert "Acme Solar" in prompt_map["conversation"].content
        assert "rapport_building" in prompt_map["grading_v2"].content
        assert "battery backup" in prompt_map["coaching"].content.lower()
    finally:
        db.close()
