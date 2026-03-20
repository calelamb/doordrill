import pytest

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


def test_transcript_normalization_applies_phonetic_corrections_before_fuzzy_matching(monkeypatch):
    service = TranscriptNormalizationService()
    seen: dict[str, str] = {}
    original = service._apply_fuzzy_term_corrections

    def wrapped(text, canonical_terms, *, org_specific_terms):
        seen["text"] = text
        return original(text, canonical_terms, org_specific_terms=org_specific_terms)

    monkeypatch.setattr(service, "_apply_fuzzy_term_corrections", wrapped)

    result = service.normalize(
        text="We do free in spec shin after the Or Kin visit.",
        provider="deepgram",
        confidence=0.88,
    )

    assert "free inspection" in seen["text"]
    assert "Orkin" in seen["text"]
    assert "free inspection" in result.normalized_text
    assert "Orkin" in result.normalized_text


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("We already use or kin right now.", "Orkin"),
        ("That pick control service sounds fine.", "pest control"),
        ("Do you do a free in spec shin first?", "free inspection"),
        ("You sprayed an arrow sol around the house.", "aerosol"),
        ("I saw road ants in the garage.", "rodents"),
    ],
)
def test_transcript_normalization_corrects_common_phonetic_stt_errors(raw_text, expected):
    service = TranscriptNormalizationService()

    result = service.normalize(
        text=raw_text,
        provider="deepgram",
        confidence=0.9,
    )

    assert expected in result.normalized_text


def test_transcript_normalization_phonetic_corrections_are_case_insensitive():
    service = TranscriptNormalizationService()

    result = service.normalize(
        text="We already use Or Kin for this.",
        provider="deepgram",
        confidence=0.9,
    )

    assert "Orkin" in result.normalized_text


def test_transcript_normalization_uses_lower_threshold_for_org_specific_terms():
    service = TranscriptNormalizationService()
    org_config = OrgPromptConfig(
        org_id="org-3",
        company_name="Acme",
        product_category="Pest Control",
        competitors=[],
        known_objections=[],
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
        text="Is this acne service monthly?",
        provider="deepgram",
        confidence=0.82,
        org_config=org_config,
    )

    assert "Acme" in result.normalized_text


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
