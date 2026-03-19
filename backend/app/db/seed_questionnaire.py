from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.questionnaire import QuestionnaireQuestion


QUESTION_BANK: list[dict] = [
    {
        "question_key": "product_category",
        "question_text": "What does your company sell?",
        "question_type": "single_choice",
        "options": [
            {"value": "residential_solar", "label": "Residential Solar"},
            {"value": "home_security", "label": "Home Security"},
            {"value": "pest_control", "label": "Pest Control"},
            {"value": "fiber_internet", "label": "Fiber Internet"},
            {"value": "hvac", "label": "HVAC"},
            {"value": "other", "label": "Other"},
        ],
        "display_order": 1,
        "category": "product",
        "required": True,
        "maps_to_config_field": "product_category",
        "active": True,
    },
    {
        "question_key": "product_description",
        "question_text": "In 2–3 sentences, describe what you sell and the core value to homeowners.",
        "question_type": "long_text",
        "options": None,
        "display_order": 2,
        "category": "product",
        "required": True,
        "maps_to_config_field": "product_description",
        "active": True,
    },
    {
        "question_key": "pricing_framing",
        "question_text": "How should reps describe pricing on the door? (e.g., 'never quote numbers until site survey', 'lead with monthly savings')",
        "question_type": "long_text",
        "options": None,
        "display_order": 3,
        "category": "product",
        "required": True,
        "maps_to_config_field": "pricing_framing",
        "active": True,
    },
    {
        "question_key": "close_style",
        "question_text": "How would you describe your reps' closing approach?",
        "question_type": "single_choice",
        "options": [
            {"value": "consultative", "label": "Consultative (build trust, let homeowner decide)"},
            {"value": "assumptive", "label": "Assumptive (confidently move toward yes)"},
            {"value": "urgency_based", "label": "Urgency-based (limited offer / time pressure)"},
        ],
        "display_order": 4,
        "category": "pitch",
        "required": True,
        "maps_to_config_field": "close_style",
        "active": True,
    },
    {
        "question_key": "pitch_stages",
        "question_text": "Which stages does your pitch typically include?",
        "question_type": "multi_choice",
        "options": [
            {"value": "door_knock", "label": "Door approach"},
            {"value": "initial_pitch", "label": "Initial value pitch"},
            {"value": "objection_handling", "label": "Objection handling"},
            {"value": "considering", "label": "Consideration pause"},
            {"value": "close_attempt", "label": "Close attempt"},
            {"value": "follow_up_scheduling", "label": "Follow-up scheduling"},
        ],
        "display_order": 5,
        "category": "pitch",
        "required": True,
        "maps_to_config_field": "pitch_stages",
        "active": True,
    },
    {
        "question_key": "key_objections",
        "question_text": "List the 3–5 most common objections your reps face and how they should respond.",
        "question_type": "long_text",
        "options": None,
        "display_order": 6,
        "category": "pitch",
        "required": True,
        "maps_to_config_field": None,
        "active": True,
    },
    {
        "question_key": "target_age_range",
        "question_text": "What age range are you typically targeting?",
        "question_type": "single_choice",
        "options": [
            {"value": "25-40", "label": "25–40"},
            {"value": "35-55", "label": "35–55"},
            {"value": "45-65", "label": "45–65"},
            {"value": "55_plus", "label": "55+"},
            {"value": "mixed", "label": "Mixed"},
        ],
        "display_order": 7,
        "category": "persona",
        "required": True,
        "maps_to_config_field": None,
        "active": True,
    },
    {
        "question_key": "target_homeowner_type",
        "question_text": "Describe your typical homeowner.",
        "question_type": "single_choice",
        "options": [
            {"value": "suburban_family_homeowner", "label": "Suburban family homeowner"},
            {"value": "rural_property_owner", "label": "Rural property owner"},
            {"value": "urban_condo_townhome_owner", "label": "Urban condo/townhome owner"},
            {"value": "mixed", "label": "Mixed"},
        ],
        "display_order": 8,
        "category": "persona",
        "required": True,
        "maps_to_config_field": None,
        "active": True,
    },
    {
        "question_key": "common_homeowner_concerns",
        "question_text": "What are the most common homeowner concerns?",
        "question_type": "multi_choice",
        "options": [
            {"value": "cost_monthly_payment", "label": "Cost / monthly payment"},
            {"value": "installation_disruption", "label": "Installation disruption"},
            {"value": "hoa_restrictions", "label": "HOA restrictions"},
            {"value": "product_reliability", "label": "Product reliability"},
            {"value": "sales_rep_trustworthiness", "label": "Sales rep trustworthiness"},
            {"value": "contract_length", "label": "Contract length"},
        ],
        "display_order": 9,
        "category": "persona",
        "required": True,
        "maps_to_config_field": None,
        "active": True,
    },
    {
        "question_key": "rep_tone_guidance",
        "question_text": "What tone should your reps project?",
        "question_type": "single_choice",
        "options": [
            {"value": "professional_warm", "label": "Professional and warm"},
            {"value": "casual_friendly", "label": "Casual and friendly"},
            {"value": "technical_expert", "label": "Technical expert"},
            {"value": "high_energy_enthusiastic", "label": "High energy and enthusiastic"},
        ],
        "display_order": 10,
        "category": "culture",
        "required": True,
        "maps_to_config_field": "rep_tone_guidance",
        "active": True,
    },
    {
        "question_key": "grading_priorities",
        "question_text": "Rank what matters most when grading a rep's performance.",
        "question_type": "multi_choice",
        "options": [
            {"value": "rapport_building", "label": "Rapport building"},
            {"value": "objection_handling", "label": "Objection handling"},
            {"value": "value_prop_clarity", "label": "Value prop clarity"},
            {"value": "close_attempt", "label": "Close attempt"},
            {"value": "professionalism", "label": "Professionalism"},
            {"value": "listening_skills", "label": "Listening skills"},
        ],
        "display_order": 11,
        "category": "culture",
        "required": True,
        "maps_to_config_field": "grading_priorities",
        "active": True,
    },
    {
        "question_key": "main_competitors",
        "question_text": "Who are your main competitors and what's your key differentiator against each?",
        "question_type": "long_text",
        "options": None,
        "display_order": 12,
        "category": "competitive",
        "required": True,
        "maps_to_config_field": None,
        "active": True,
    },
]


def seed_questionnaire_questions(db: Session) -> None:
    existing = {
        row.question_key: row
        for row in db.scalars(select(QuestionnaireQuestion)).all()
    }
    for payload in QUESTION_BANK:
        row = existing.get(payload["question_key"])
        if row is None:
            row = QuestionnaireQuestion(question_key=payload["question_key"])
            db.add(row)
        row.question_text = payload["question_text"]
        row.question_type = payload["question_type"]
        row.options = json.loads(json.dumps(payload["options"])) if payload["options"] is not None else None
        row.display_order = int(payload["display_order"])
        row.category = payload["category"]
        row.required = bool(payload["required"])
        row.maps_to_config_field = payload["maps_to_config_field"]
        row.active = bool(payload["active"])
