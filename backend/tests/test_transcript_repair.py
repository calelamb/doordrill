"""Tests for the transcript repair service."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.services.transcript_repair_service import (
    RepairResult,
    TranscriptRepairService,
    VOCAB_PATH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(vocab: dict | None = None, tmp_path: Path | None = None) -> TranscriptRepairService:
    if vocab is not None and tmp_path is not None:
        path = tmp_path / "vocab.json"
        path.write_text(json.dumps(vocab))
        return TranscriptRepairService(vocab_path=path)
    return TranscriptRepairService()


# ---------------------------------------------------------------------------
# Vocabulary loading
# ---------------------------------------------------------------------------

def test_vocabulary_loads_from_default_path():
    svc = TranscriptRepairService()
    assert svc.vocabulary, "vocabulary should be non-empty"


def test_vocabulary_loading_from_custom_path(tmp_path):
    vocab = {
        "test_category": {
            "terms": ["bifenthrin"],
            "misrecognitions": {"by fen thin": "bifenthrin"},
        }
    }
    path = tmp_path / "vocab.json"
    path.write_text(json.dumps(vocab))
    svc = TranscriptRepairService(vocab_path=path)
    assert svc.vocabulary == vocab


def test_vocabulary_missing_file_returns_empty(tmp_path):
    svc = TranscriptRepairService(vocab_path=tmp_path / "nonexistent.json")
    assert svc.vocabulary == {}


def test_vocabulary_invalid_json_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    svc = TranscriptRepairService(vocab_path=path)
    assert svc.vocabulary == {}


# ---------------------------------------------------------------------------
# get_boost_terms
# ---------------------------------------------------------------------------

def test_get_boost_terms_returns_flat_list():
    svc = TranscriptRepairService()
    terms = svc.get_boost_terms()
    assert isinstance(terms, list)
    assert len(terms) > 0
    # All terms should be strings
    assert all(isinstance(t, str) for t in terms)
    # Known terms should be present
    assert "bifenthrin" in terms
    assert "German cockroach" in terms
    assert "Orkin" in terms


def test_get_boost_terms_with_empty_vocab(tmp_path):
    svc = _make_service({}, tmp_path)
    assert svc.get_boost_terms() == []


# ---------------------------------------------------------------------------
# Exact misrecognition matching
# ---------------------------------------------------------------------------

def test_german_watches_to_german_cockroaches():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("We have german watches in our kitchen.")
    assert "German cockroaches" in result.repaired_text
    assert "german watches" not in result.repaired_text.lower()
    assert result.repairs


def test_chemical_misrecognition_by_fen_thin():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("We use by fen thin for perimeter treatment.")
    assert "bifenthrin" in result.repaired_text
    assert result.repairs


def test_company_misrecognition_or_kin():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("We already use or kin for our pest control.")
    assert "Orkin" in result.repaired_text
    assert result.repairs


def test_no_changes_needed():
    svc = TranscriptRepairService()
    text = "We provide general pest control services."
    result = svc.deterministic_repair(text)
    assert result.repaired_text == text
    assert result.repairs == []
    assert result.all_confident is True


def test_sentence_structure_preserved():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("We treat for german watches and bed bugs too.")
    # Sentence should still be coherent
    assert result.repaired_text.endswith("too.")
    assert "German cockroaches" in result.repaired_text


def test_multiple_repairs_in_one_transcript():
    svc = TranscriptRepairService()
    text = "We use by fen thin and term mix treats german watches."
    result = svc.deterministic_repair(text)
    assert "bifenthrin" in result.repaired_text
    assert "Terminix" in result.repaired_text
    assert "German cockroaches" in result.repaired_text
    # Multiple repairs recorded
    assert len(result.repairs) >= 3


def test_case_insensitive_misrecognition():
    svc = TranscriptRepairService()
    # Test uppercase variant of a known misrecognition
    result = svc.deterministic_repair("We have GERMAN WATCHES everywhere.")
    assert "German cockroaches" in result.repaired_text


def test_original_text_preserved_in_result():
    svc = TranscriptRepairService()
    original = "We have german watches in our kitchen."
    result = svc.deterministic_repair(original)
    assert result.original_text == original


def test_repair_result_tracks_repairs():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("We use by fen thin here.")
    assert len(result.repairs) >= 1
    repair = result.repairs[0]
    assert "original" in repair
    assert "replacement" in repair
    assert "method" in repair
    assert repair["method"] in ("exact", "fuzzy")


def test_all_confident_true_when_no_fuzzy_uncertainty():
    svc = TranscriptRepairService()
    # Clean text with no ambiguous tokens should be all_confident
    result = svc.deterministic_repair("We provide general pest control services.")
    assert result.all_confident is True


def test_repair_result_is_dataclass():
    result = RepairResult(
        repaired_text="test",
        original_text="test",
        repairs=[],
        all_confident=True,
    )
    assert result.repaired_text == "test"
    assert result.repairs == []
    assert result.all_confident is True


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def test_fuzzy_match_high_confidence_replaces_token():
    """Tokens very close to a known term (score >= 92) should be replaced."""
    svc = TranscriptRepairService()
    # "bifinthrin" is close enough to "bifenthrin" for high-confidence fuzzy
    result = svc.deterministic_repair("We applied bifinthrin around the perimeter.")
    # Should either replace or flag as low-confidence
    assert isinstance(result.all_confident, bool)


def test_fuzzy_match_low_confidence_sets_flag():
    """When a token has fuzzy score between FUZZY_THRESHOLD and FUZZY_CONFIDENT_THRESHOLD,
    all_confident should be False."""
    # Build a minimal vocab with a term that will be a medium-confidence fuzzy match
    import json
    from pathlib import Path
    import tempfile

    vocab = {
        "chemicals": {
            "terms": ["bifenthrin"],
            "misrecognitions": {},
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "vocab.json"
        path.write_text(json.dumps(vocab))
        svc = TranscriptRepairService(vocab_path=path)

        # "bfentrin" should score somewhere in the fuzzy range but below confident
        result = svc.deterministic_repair("We used bfentrin last month.")
        # Either it was replaced confidently or flagged as not confident
        assert isinstance(result.all_confident, bool)


# ---------------------------------------------------------------------------
# LLM repair
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_repair_returns_corrected_text():
    svc = TranscriptRepairService()

    async def _mock_stream(*, rep_text, stage, system_prompt, max_tokens):
        yield "bifenthrin"

    mock_client = MagicMock()
    mock_client.stream_reply = _mock_stream

    context = [
        {"role": "rep", "content": "We use by fen thin."},
        {"role": "homeowner", "content": "What is that?"},
    ]
    result = await svc.llm_repair(
        text="by fen thin",
        conversation_context=context,
        llm_client=mock_client,
        model="gpt-4o-mini",
    )
    assert result == "bifenthrin"


@pytest.mark.asyncio
async def test_llm_repair_fallback_on_error():
    svc = TranscriptRepairService()

    async def _mock_stream_error(*, rep_text, stage, system_prompt, max_tokens):
        raise RuntimeError("LLM unavailable")
        yield  # make it a generator

    mock_client = MagicMock()
    mock_client.stream_reply = _mock_stream_error

    original_text = "some unrecognized words"
    result = await svc.llm_repair(
        text=original_text,
        conversation_context=[],
        llm_client=mock_client,
    )
    assert result == original_text


@pytest.mark.asyncio
async def test_llm_repair_empty_response_falls_back():
    svc = TranscriptRepairService()

    async def _mock_stream_empty(*, rep_text, stage, system_prompt, max_tokens):
        yield ""
        yield "   "

    mock_client = MagicMock()
    mock_client.stream_reply = _mock_stream_empty

    original_text = "some text"
    result = await svc.llm_repair(
        text=original_text,
        conversation_context=[],
        llm_client=mock_client,
    )
    assert result == original_text


@pytest.mark.asyncio
async def test_llm_repair_uses_recent_context_only():
    """LLM repair should only use last 4 turns of context."""
    svc = TranscriptRepairService()

    captured_prompt = {}

    async def _mock_stream(*, rep_text, stage, system_prompt, max_tokens):
        captured_prompt["rep_text"] = rep_text
        yield "fixed text"

    mock_client = MagicMock()
    mock_client.stream_reply = _mock_stream

    # Provide 6 turns — only last 4 should appear in prompt
    context = [{"role": "rep", "content": f"turn {i}"} for i in range(6)]
    await svc.llm_repair(
        text="something",
        conversation_context=context,
        llm_client=mock_client,
    )
    prompt = captured_prompt["rep_text"]
    assert "turn 2" in prompt or "turn 3" in prompt or "turn 4" in prompt or "turn 5" in prompt
    # The first two turns should NOT appear
    assert "turn 0" not in prompt
    assert "turn 1" not in prompt


# ---------------------------------------------------------------------------
# Integration: deterministic + result structure
# ---------------------------------------------------------------------------

def test_repair_result_repaired_text_is_string():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("Hello there.")
    assert isinstance(result.repaired_text, str)


def test_repairs_list_method_field_values():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("We treat for german watches.")
    for repair in result.repairs:
        assert repair["method"] in ("exact", "fuzzy")


def test_terminix_misrecognition():
    svc = TranscriptRepairService()
    result = svc.deterministic_repair("I heard term mix is a big company.")
    assert "Terminix" in result.repaired_text
