from app.models.org_prompt_config import OrgPromptConfig
from app.services.transcript_normalization_service import TranscriptNormalizationService


def test_transcript_normalization_corrects_domain_terms_and_keeps_audit_fields():
    service = TranscriptNormalizationService()
    org_config = OrgPromptConfig(
        org_id="org-1",
        company_name="Acme Pest Control",
        product_category="Pest Control",
        competitors=[{"name": "Orkin"}],
        known_objections=[{"objection": "warranty concerns"}],
        pitch_stages=[],
        unique_selling_points=[],
        target_demographics={},
        pricing_framing=None,
        close_style=None,
        rep_tone_guidance=None,
        grading_priorities=[],
        published=True,
    )

    result = service.normalize(
        text="We already use orken and I want a warrenty before switching.",
        provider="deepgram",
        confidence=0.91,
        org_config=org_config,
        active_objections=["incumbent_provider"],
    )

    assert result.raw_text == "We already use orken and I want a warrenty before switching."
    assert "Orkin" in result.normalized_text
    assert "warranty" in result.normalized_text
    assert result.provider == "deepgram"
    assert result.confidence == 0.91


def test_keyword_hints_prioritize_org_and_objection_terms():
    service = TranscriptNormalizationService()
    org_config = OrgPromptConfig(
        org_id="org-2",
        company_name="Acme Pest Control",
        product_category="Pest Control",
        competitors=[{"name": "Terminix"}],
        known_objections=[{"objection": "monthly payment"}],
        pitch_stages=[],
        unique_selling_points=[],
        target_demographics={},
        pricing_framing=None,
        close_style=None,
        rep_tone_guidance=None,
        grading_priorities=[],
        published=True,
    )

    hints = service.keyword_hints(
        org_config=org_config,
        active_objections=["price"],
        queued_objections=["incumbent_provider"],
    )

    assert "Acme Pest Control" in hints
    assert "monthly payment" in hints
    assert any(term.lower() == "terminix" for term in hints)
