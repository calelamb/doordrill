from __future__ import annotations

from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.org_material import OrgKnowledgeDoc, OrgMaterial


def _auth_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {
        "x-user-id": seed_org["manager_id"],
        "x-user-role": "manager",
    }


def test_questionnaire_and_prompt_studio_generate_flow(client, seed_org):
    headers = _auth_headers(seed_org)

    questionnaire_response = client.get(
        f"/admin/orgs/{seed_org['org_id']}/questionnaire",
        headers=headers,
    )
    assert questionnaire_response.status_code == 200
    questionnaire_payload = questionnaire_response.json()
    assert questionnaire_payload["total_questions"] == 12
    assert set(questionnaire_payload["categories"].keys()) == {
        "product",
        "pitch",
        "persona",
        "culture",
        "competitive",
    }

    answers = [
        {"question_key": "product_category", "answer_value": "residential_solar"},
        {
            "question_key": "product_description",
            "answer_value": "We sell residential solar systems that reduce utility bills and improve energy resilience.",
        },
        {
            "question_key": "pricing_framing",
            "answer_value": "Lead with long-term savings and avoid firm numbers until the site survey.",
        },
        {"question_key": "close_style", "answer_value": "consultative"},
        {
            "question_key": "pitch_stages",
            "answer_value": ["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
        },
        {
            "question_key": "key_objections",
            "answer_value": "Too expensive -> anchor on long-term savings\nNeed to think about it -> offer a low-friction next step",
        },
        {"question_key": "target_age_range", "answer_value": "35-55"},
        {"question_key": "target_homeowner_type", "answer_value": "suburban_family_homeowner"},
        {
            "question_key": "common_homeowner_concerns",
            "answer_value": ["cost_monthly_payment", "installation_disruption", "sales_rep_trustworthiness"],
        },
        {"question_key": "rep_tone_guidance", "answer_value": "professional_warm"},
        {
            "question_key": "grading_priorities",
            "answer_value": ["rapport_building", "objection_handling", "close_attempt"],
        },
        {
            "question_key": "main_competitors",
            "answer_value": "Sunrun: we move faster locally\nADT Solar: we offer more consultative install planning",
        },
    ]
    answer_response = client.post(
        f"/admin/orgs/{seed_org['org_id']}/questionnaire/answers",
        headers=headers,
        json=answers,
    )
    assert answer_response.status_code == 200
    assert answer_response.json()["answered"] == 12

    db = SessionLocal()
    material = OrgMaterial(
        org_id=seed_org["org_id"],
        original_filename="battlecard.txt",
        file_type="txt",
        storage_key="tests/materials/prompt-studio.txt",
        extraction_status="complete",
        extracted_at=datetime.now(timezone.utc),
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    db.add_all(
        [
            OrgKnowledgeDoc(
                org_id=seed_org["org_id"],
                material_id=material.id,
                extraction_type="usp",
                content="Battery backup keeps homeowners protected during outages.",
                supporting_quote="Battery backup keeps homeowners protected during outages.",
                confidence=0.95,
                manager_approved=True,
                used_in_config=False,
            ),
            OrgKnowledgeDoc(
                org_id=seed_org["org_id"],
                material_id=material.id,
                extraction_type="objection",
                content="Homeowners worry the switch will be too expensive up front.",
                supporting_quote="too expensive up front",
                confidence=0.9,
                manager_approved=True,
                used_in_config=False,
            ),
            OrgKnowledgeDoc(
                org_id=seed_org["org_id"],
                material_id=material.id,
                extraction_type="rebuttal",
                content="Reframe cost around monthly savings and long-term ownership value.",
                supporting_quote="monthly savings and long-term ownership value",
                confidence=0.88,
                manager_approved=True,
                used_in_config=False,
            ),
            OrgKnowledgeDoc(
                org_id=seed_org["org_id"],
                material_id=material.id,
                extraction_type="competitor",
                content="Sunrun: slower local install scheduling.",
                supporting_quote="Sunrun: slower local install scheduling.",
                confidence=0.84,
                manager_approved=True,
                used_in_config=False,
            ),
        ]
    )
    db.commit()
    db.close()

    generate_response = client.post(
        f"/admin/orgs/{seed_org['org_id']}/prompt-studio/generate",
        headers=headers,
    )
    assert generate_response.status_code == 200
    generated = generate_response.json()
    assert generated["company_name"]
    assert generated["product_category"] == "residential_solar"
    assert generated["close_style"] == "consultative"
    assert generated["rep_tone_guidance"] == "professional_warm"
    assert generated["unique_selling_points"]
    assert generated["known_objections"]

    preview_response = client.get(
        f"/admin/orgs/{seed_org['org_id']}/prompt-studio/preview",
        headers=headers,
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["conversation_prompt"]
    assert preview["system_prompt_token_count"] > 0
