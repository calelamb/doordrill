# Voice Realism & Comprehension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI homeowner fully understand the rep and respond with natural, unscripted-feeling dialogue by fixing STT accuracy and response quality.

**Architecture:** Add a transcript repair layer between STT and orchestrator (fuzzy match + conditional LLM). Overhaul PromptBuilder to remove hard word/sentence caps and add persona life details. Refactor micro-behavior engine to metadata-only (no text transforms). Add AssemblyAI as primary STT provider with domain vocabulary boosting. Add a response quality gate with conditional regeneration.

**Tech Stack:** Python 3.11+, FastAPI, rapidfuzz, AssemblyAI SDK, existing OpenAI/Anthropic clients

**Spec:** `docs/2026-03-20-voice-realism-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `backend/app/data/vocab_pest_control.json` | Pest control domain vocabulary for STT boosting + transcript repair | Create |
| `backend/app/services/transcript_repair_service.py` | Fuzzy match + conditional LLM transcript repair | Create |
| `backend/app/core/config.py` | New settings: ASSEMBLYAI_API_KEY, TRANSCRIPT_REPAIR_MODEL, TRANSCRIPT_REPAIR_ENABLED, RESPONSE_QUALITY_GATE_ENABLED (STT_PROVIDER already exists) | Modify |
| `backend/app/services/provider_clients.py` | AssemblyAI STT client, BaseSttClient interface update, history window expansion | Modify |
| `backend/app/services/micro_behavior_engine.py` | Remove text transforms, keep metadata-only | Modify |
| `backend/app/services/conversation_orchestrator.py` | PromptBuilder overhaul, PersonaEnricher expansion | Modify |
| `backend/app/voice/ws.py` | Wire transcript repair, quality gate, pause cap, token budget | Modify |
| `backend/pyproject.toml` | Add rapidfuzz + assemblyai dependencies | Modify |
| `tests/test_transcript_repair.py` | Tests for transcript repair service | Create |
| `tests/test_prompt_builder_v2.py` | Tests for overhauled PromptBuilder | Create |
| `tests/test_micro_behavior_engine.py` | Update existing tests for metadata-only behavior | Modify |
| `tests/test_assemblyai_stt.py` | Tests for AssemblyAI STT client | Create |
| `tests/test_response_quality_gate.py` | Tests for relevance check + regeneration logic | Create |

---

## Task 1: Add Dependencies and Config

**Files:**
- Modify: `backend/pyproject.toml:6-25`
- Modify: `backend/app/core/config.py:37-62`
- Test: `tests/test_config.py` (if exists, otherwise verify manually)

- [ ] **Step 1: Add rapidfuzz and assemblyai to pyproject.toml**

In `backend/pyproject.toml`, add to the `dependencies` list:

```toml
"rapidfuzz>=3.0.0",
"assemblyai>=0.30.0",
```

- [ ] **Step 2: Add new settings to config.py**

**Note:** `stt_provider` already exists at line 37 of `config.py` with alias `STT_PROVIDER`. Do NOT add it again. Only add these new fields to the `Settings` class after the existing provider fields (around line 62):

```python
    # AssemblyAI (STT_PROVIDER already exists at line 37 — set it to "assemblyai" in .env)
    assemblyai_api_key: str | None = Field(default=None, alias="ASSEMBLYAI_API_KEY")

    # Transcript repair
    transcript_repair_enabled: bool = Field(default=True, alias="TRANSCRIPT_REPAIR_ENABLED")
    transcript_repair_model: str = Field(default="gpt-4o-mini", alias="TRANSCRIPT_REPAIR_MODEL")

    # Response quality gate
    response_quality_gate_enabled: bool = Field(default=True, alias="RESPONSE_QUALITY_GATE_ENABLED")
```

- [ ] **Step 3: Install dependencies**

Run: `cd backend && pip install -e ".[dev]"`
Expected: Installs successfully with rapidfuzz and assemblyai

- [ ] **Step 4: Verify settings load**

Run: `cd backend && python3 -c "from app.core.config import get_settings; s = get_settings(); print(s.transcript_repair_enabled, s.response_quality_gate_enabled, s.assemblyai_api_key)"`
Expected: `True True None`

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/core/config.py
git commit -m "feat: add config for transcript repair, quality gate, and AssemblyAI"
```

---

## Task 2: Domain Vocabulary File

**Files:**
- Create: `backend/app/data/vocab_pest_control.json`
- Test: Validated by Task 3 tests

- [ ] **Step 1: Create the vocabulary file**

Create `backend/app/data/vocab_pest_control.json`:

```json
{
  "species": {
    "terms": [
      "German cockroach", "American cockroach", "brown recluse", "black widow",
      "subterranean termite", "drywood termite", "carpenter ant", "fire ant",
      "bed bug", "house mouse", "Norway rat", "roof rat", "silverfish",
      "earwig", "centipede", "millipede", "brown marmorated stink bug",
      "yellow jacket", "paper wasp", "mud dauber", "flea", "tick",
      "mosquito", "gopher", "vole", "mole"
    ],
    "misrecognitions": {
      "german watches": "German cockroaches",
      "german coach": "German cockroach",
      "german roach": "German cockroach",
      "brown recuse": "brown recluse",
      "brown reclusive": "brown recluse",
      "sub terrain termite": "subterranean termite",
      "sub terranean": "subterranean",
      "carpenter ants": "carpenter ants",
      "fire ants": "fire ants",
      "bed bugs": "bed bugs",
      "roof rats": "roof rats"
    }
  },
  "chemicals": {
    "terms": [
      "bifenthrin", "fipronil", "permethrin", "cypermethrin", "deltamethrin",
      "imidacloprid", "chlorfenapyr", "abamectin", "hydramethylnon",
      "diatomaceous earth", "boric acid", "pyrethrin", "lambda-cyhalothrin",
      "indoxacarb", "spinosad"
    ],
    "misrecognitions": {
      "by fen thin": "bifenthrin",
      "by fenthin": "bifenthrin",
      "fiber nil": "fipronil",
      "fipro nil": "fipronil",
      "permit thin": "permethrin",
      "siper method": "cypermethrin",
      "delta method": "deltamethrin",
      "diamondaceous": "diatomaceous",
      "diatomaceous": "diatomaceous"
    }
  },
  "sales_jargon": {
    "terms": [
      "initial service", "quarterly service", "general pest",
      "perimeter treatment", "interior treatment", "spot treatment",
      "power spray", "granule treatment", "bait station",
      "monitoring station", "exclusion work", "caulking", "sealing",
      "de-webbing", "free inspection", "free estimate", "free quote",
      "service agreement", "annual contract", "pest control plan",
      "integrated pest management", "IPM"
    ],
    "misrecognitions": {
      "parameter treatment": "perimeter treatment",
      "premature treatment": "perimeter treatment",
      "bay station": "bait station",
      "bake station": "bait station",
      "great station": "bait station",
      "deep webbing": "de-webbing",
      "exclusion work": "exclusion work"
    }
  },
  "common_companies": {
    "terms": [
      "Orkin", "Terminix", "Aptive", "ABC Home", "Truly Nolen",
      "HomeTeam", "Massey", "Turner", "Bulwark", "Moxie"
    ],
    "misrecognitions": {
      "or can": "Orkin",
      "or kin": "Orkin",
      "terminate": "Terminix",
      "term mix": "Terminix",
      "active": "Aptive",
      "apt of": "Aptive"
    }
  }
}
```

- [ ] **Step 2: Verify JSON is valid**

Run: `cd backend && python3 -c "import json; json.load(open('app/data/vocab_pest_control.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add backend/app/data/vocab_pest_control.json
git commit -m "feat: add pest control domain vocabulary for STT boosting and transcript repair"
```

---

## Task 3: Transcript Repair Service

**Files:**
- Create: `backend/app/services/transcript_repair_service.py`
- Create: `backend/tests/test_transcript_repair.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_transcript_repair.py`:

```python
"""Tests for TranscriptRepairService."""
import pytest

from app.services.transcript_repair_service import TranscriptRepairService


@pytest.fixture
def repair_service():
    return TranscriptRepairService()


class TestDeterministicRepair:
    """Tests for the fuzzy-match deterministic pass."""

    def test_exact_misrecognition_match(self, repair_service):
        result = repair_service.deterministic_repair("We treat for german watches")
        assert "German cockroaches" in result.repaired_text

    def test_chemical_misrecognition(self, repair_service):
        result = repair_service.deterministic_repair("We use by fen thin for treatment")
        assert "bifenthrin" in result.repaired_text

    def test_company_misrecognition(self, repair_service):
        result = repair_service.deterministic_repair("Are you with or can")
        assert "Orkin" in result.repaired_text

    def test_no_changes_needed(self, repair_service):
        text = "Hi, I'm here to talk about pest control"
        result = repair_service.deterministic_repair(text)
        assert result.repaired_text == text
        assert result.all_confident is True

    def test_preserves_sentence_structure(self, repair_service):
        result = repair_service.deterministic_repair(
            "The by fen thin we use is safe for kids"
        )
        assert result.repaired_text == "The bifenthrin we use is safe for kids"

    def test_multiple_repairs_in_one_transcript(self, repair_service):
        result = repair_service.deterministic_repair(
            "We use by fen thin for german watches"
        )
        assert "bifenthrin" in result.repaired_text
        assert "German cockroaches" in result.repaired_text

    def test_case_insensitive_matching(self, repair_service):
        result = repair_service.deterministic_repair("GERMAN WATCHES are common here")
        assert "German cockroaches" in result.repaired_text

    def test_fuzzy_match_close_tokens(self, repair_service):
        """Tokens close to domain terms but not exact misrecognitions should flag low confidence."""
        result = repair_service.deterministic_repair("We use bifenthin for pests")
        # Close to "bifenthrin" - should attempt repair
        assert "bifenthrin" in result.repaired_text or not result.all_confident


class TestRepairResult:
    """Tests for the RepairResult dataclass."""

    def test_confident_when_no_repairs(self, repair_service):
        result = repair_service.deterministic_repair("Hello, how are you today")
        assert result.all_confident is True
        assert result.repairs == []

    def test_tracks_repairs_made(self, repair_service):
        result = repair_service.deterministic_repair("We treat for german watches")
        assert len(result.repairs) > 0
        assert result.repairs[0]["original"] == "german watches"
        assert result.repairs[0]["replacement"] == "German cockroaches"


class TestNeedsLlmRepair:
    """Tests for deciding when to invoke the LLM repair pass."""

    def test_no_llm_needed_when_confident(self, repair_service):
        result = repair_service.deterministic_repair("Hi, we do pest control")
        assert result.all_confident is True

    def test_llm_needed_when_low_confidence(self, repair_service):
        result = repair_service.deterministic_repair("We use byfenthn for treatment")
        assert result.all_confident is False


class TestVocabularyLoading:
    """Tests for vocabulary loading from JSON."""

    def test_loads_all_categories(self, repair_service):
        assert "species" in repair_service.vocabulary
        assert "chemicals" in repair_service.vocabulary
        assert "sales_jargon" in repair_service.vocabulary
        assert "common_companies" in repair_service.vocabulary

    def test_boost_terms_returns_flat_list(self, repair_service):
        terms = repair_service.get_boost_terms()
        assert isinstance(terms, list)
        assert "German cockroach" in terms
        assert "bifenthrin" in terms
        assert "Orkin" in terms
        assert len(terms) > 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_transcript_repair.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.transcript_repair_service'`

- [ ] **Step 3: Implement TranscriptRepairService**

Create `backend/app/services/transcript_repair_service.py`:

```python
"""Transcript repair service for fixing domain-specific STT misrecognitions.

Sits between STT output and the conversation orchestrator. Runs a fast
deterministic fuzzy-match pass, and optionally invokes a lightweight LLM
for ambiguous repairs.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

VOCAB_PATH = Path(__file__).resolve().parent.parent / "data" / "vocab_pest_control.json"
FUZZY_THRESHOLD = 82  # minimum similarity score to attempt repair
FUZZY_CONFIDENT_THRESHOLD = 92  # above this, repair is confident (no LLM needed)


@dataclass
class RepairResult:
    repaired_text: str
    original_text: str
    repairs: list[dict[str, str]] = field(default_factory=list)
    all_confident: bool = True


class TranscriptRepairService:
    """Repairs domain-specific STT misrecognitions using fuzzy matching."""

    def __init__(self, vocab_path: Path | None = None) -> None:
        self.vocabulary = self._load_vocabulary(vocab_path or VOCAB_PATH)
        self._misrecognition_map = self._build_misrecognition_map()
        self._all_terms = self._build_term_list()

    def _load_vocabulary(self, path: Path) -> dict[str, Any]:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load vocabulary from %s: %s", path, exc)
            return {}

    def _build_misrecognition_map(self) -> dict[str, str]:
        """Build a lowercase lookup of known misrecognitions -> corrections."""
        mapping: dict[str, str] = {}
        for category in self.vocabulary.values():
            if isinstance(category, dict) and "misrecognitions" in category:
                for wrong, right in category["misrecognitions"].items():
                    mapping[wrong.lower()] = right
        return mapping

    def _build_term_list(self) -> list[str]:
        """Build flat list of all correct domain terms for fuzzy matching."""
        terms: list[str] = []
        for category in self.vocabulary.values():
            if isinstance(category, dict) and "terms" in category:
                terms.extend(category["terms"])
        return terms

    def get_boost_terms(self) -> list[str]:
        """Return flat list of domain terms for STT vocabulary boosting."""
        return list(self._all_terms)

    def deterministic_repair(self, text: str) -> RepairResult:
        """Run fast deterministic repair pass using known misrecognitions and fuzzy matching."""
        original = text
        repairs: list[dict[str, str]] = []
        all_confident = True
        repaired = text

        # Pass 1: exact misrecognition lookup (case-insensitive, multi-word)
        for wrong, right in sorted(
            self._misrecognition_map.items(), key=lambda x: len(x[0]), reverse=True
        ):
            pattern = re.compile(re.escape(wrong), re.IGNORECASE)
            if pattern.search(repaired):
                repaired = pattern.sub(right, repaired)
                repairs.append({"original": wrong, "replacement": right, "method": "exact"})

        # Pass 2: fuzzy match individual tokens against domain terms
        words = repaired.split()
        for i, word in enumerate(words):
            clean = word.strip(".,!?;:'\"").lower()
            if len(clean) < 4:
                continue
            # Skip if word is already a known term
            if any(clean in term.lower() for term in self._all_terms):
                continue
            # Skip common English words
            if clean in _COMMON_WORDS:
                continue

            match = process.extractOne(
                clean, [t.lower() for t in self._all_terms], scorer=fuzz.ratio
            )
            if match is None:
                continue

            matched_term, score, _ = match
            if score >= FUZZY_CONFIDENT_THRESHOLD:
                # Find the original-cased term
                original_term = next(
                    (t for t in self._all_terms if t.lower() == matched_term), matched_term
                )
                # Preserve surrounding punctuation
                prefix = ""
                suffix = ""
                raw = words[i]
                for ch in raw:
                    if ch.isalnum():
                        break
                    prefix += ch
                for ch in reversed(raw):
                    if ch.isalnum():
                        break
                    suffix = ch + suffix
                words[i] = f"{prefix}{original_term}{suffix}"
                repairs.append(
                    {"original": clean, "replacement": original_term, "method": "fuzzy", "score": score}
                )
            elif score >= FUZZY_THRESHOLD:
                all_confident = False

        repaired = " ".join(words)
        return RepairResult(
            repaired_text=repaired,
            original_text=original,
            repairs=repairs,
            all_confident=all_confident,
        )


# Common English words to skip during fuzzy matching (avoids false positives)
_COMMON_WORDS = frozenset({
    "the", "and", "that", "this", "with", "from", "your", "have", "been",
    "will", "would", "could", "should", "about", "which", "their", "there",
    "here", "what", "when", "where", "they", "them", "then", "than",
    "some", "more", "much", "very", "also", "just", "like", "know",
    "make", "take", "come", "good", "well", "back", "over", "such",
    "after", "year", "most", "only", "into", "other", "time", "been",
    "long", "look", "want", "does", "doing", "going", "home", "house",
    "door", "said", "tell", "told", "hear", "heard", "talk", "talking",
    "sure", "okay", "yeah", "right", "really", "think", "price", "cost",
    "safe", "kids", "family", "treat", "spray", "service", "company",
    "pest", "control", "bugs", "help", "free", "today", "need",
})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_transcript_repair.py -v`
Expected: All tests PASS

- [ ] **Step 5: Add conditional LLM repair method**

Add an `async def llm_repair()` method to `TranscriptRepairService` that takes a transcript, conversation context (last 2 turns), and an LLM client, and returns a repaired transcript. This is called from `ws.py` only when `deterministic_repair()` returns `all_confident=False`.

```python
async def llm_repair(
    self,
    text: str,
    conversation_context: list[dict[str, str]],
    llm_client: Any,
    model: str = "gpt-4o-mini",
) -> str:
    """Use a fast LLM to fix ambiguous STT errors the fuzzy matcher couldn't resolve confidently."""
    context_str = "\n".join(
        f"{turn['role']}: {turn['content']}" for turn in conversation_context[-4:]
    )
    system_prompt = (
        "Fix domain-specific speech recognition errors in this pest control sales transcript. "
        "Only change words that are clearly misrecognized. Return the corrected transcript only. "
        "Do not add, remove, or rephrase anything else."
    )
    user_prompt = f"Recent conversation:\n{context_str}\n\nTranscript to fix: {text}"

    try:
        repaired = ""
        async for chunk in llm_client.stream_reply(
            rep_text=user_prompt,
            stage="repair",
            system_prompt=system_prompt,
            max_tokens=100,
        ):
            repaired += str(chunk)
        return repaired.strip() or text
    except Exception as exc:
        logger.warning("LLM repair failed, using deterministic result: %s", exc)
        return text
```

- [ ] **Step 6: Add LLM repair test**

Add to `backend/tests/test_transcript_repair.py`:

```python
import asyncio
from unittest.mock import AsyncMock


class TestLlmRepair:
    """Tests for the conditional LLM repair pass."""

    def test_llm_repair_called_with_context(self, repair_service):
        """LLM repair receives conversation context and returns repaired text."""
        mock_llm = AsyncMock()

        async def fake_stream(*args, **kwargs):
            yield "bifenthrin treatment for German cockroaches"

        mock_llm.stream_reply = fake_stream
        context = [{"role": "user", "content": "Tell me about your treatment"}]

        result = asyncio.get_event_loop().run_until_complete(
            repair_service.llm_repair(
                "byfenthn treatment for german watches",
                context,
                mock_llm,
            )
        )
        assert "bifenthrin" in result or "German cockroaches" in result

    def test_llm_repair_fallback_on_error(self, repair_service):
        """If LLM fails, return original text."""
        mock_llm = AsyncMock()

        async def failing_stream(*args, **kwargs):
            raise RuntimeError("API error")
            yield  # make it a generator

        mock_llm.stream_reply = failing_stream
        original = "some garbled text"

        result = asyncio.get_event_loop().run_until_complete(
            repair_service.llm_repair(original, [], mock_llm)
        )
        assert result == original
```

- [ ] **Step 7: Run all transcript repair tests**

Run: `cd backend && python3 -m pytest tests/test_transcript_repair.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/transcript_repair_service.py backend/tests/test_transcript_repair.py
git commit -m "feat: add transcript repair service with fuzzy matching and conditional LLM repair"
```

---

## Task 4: Update BaseSttClient Interface and Add AssemblyAI Client

**Files:**
- Modify: `backend/app/services/provider_clients.py:24-35` (BaseSttClient), `:117-122` (MockSttClient), `:164-167` (DeepgramSttClient), `:615-664` (ProviderSuite)
- Create: `backend/tests/test_assemblyai_stt.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_assemblyai_stt.py`:

```python
"""Tests for AssemblyAI STT client and updated BaseSttClient interface."""
import pytest

from app.services.provider_clients import (
    AssemblyAiSttClient,
    BaseSttClient,
    DeepgramSttClient,
    MockSttClient,
    ProviderSuite,
)


class TestBaseSttClientInterface:
    """Verify the updated BaseSttClient accepts vocabulary parameter."""

    def test_start_session_accepts_vocabulary(self):
        """BaseSttClient.start_session signature includes vocabulary kwarg."""
        import inspect
        sig = inspect.signature(BaseSttClient.start_session)
        assert "vocabulary" in sig.parameters
        assert sig.parameters["vocabulary"].default is None

    def test_mock_client_accepts_vocabulary(self):
        """MockSttClient.start_session accepts and ignores vocabulary."""
        client = MockSttClient()
        # Should not raise
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            client.start_session("test-session", vocabulary=["bifenthrin", "Orkin"])
        )


class TestAssemblyAiSttClient:
    """Tests for AssemblyAI client construction and mock behavior."""

    def test_instantiation_without_api_key(self):
        """Client can be instantiated (will fail on actual API calls)."""
        client = AssemblyAiSttClient(api_key="test-key")
        assert client.provider_name == "assemblyai"

    def test_provider_name(self):
        client = AssemblyAiSttClient(api_key="test-key")
        assert client.provider_name == "assemblyai"


class TestProviderSuiteResolution:
    """Tests for ProviderSuite resolving AssemblyAI as STT provider."""

    def test_assemblyai_resolved_when_configured(self):
        """When stt_provider='assemblyai', ProviderSuite creates AssemblyAiSttClient."""
        from unittest.mock import MagicMock
        settings = MagicMock()
        settings.stt_provider = "assemblyai"
        settings.assemblyai_api_key = "test-key"
        settings.llm_provider = "mock"
        settings.tts_provider = "mock"
        # Set other required attrs to avoid AttributeError
        settings.openai_api_key = None
        settings.anthropic_api_key = None
        settings.elevenlabs_api_key = None
        settings.openai_model = "gpt-4o-mini"
        settings.anthropic_model = "claude-3-5-sonnet-latest"
        settings.openai_base_url = None
        settings.anthropic_base_url = None
        settings.elevenlabs_voice_id = None
        settings.elevenlabs_model_id = "eleven_flash_v2_5"
        settings.elevenlabs_base_url = None
        settings.deepgram_api_key = None
        settings.deepgram_base_url = "https://api.deepgram.com"
        settings.deepgram_model = "nova-2"
        settings.provider_timeout_seconds = 10.0

        suite = ProviderSuite.from_settings(settings)
        assert isinstance(suite.stt, AssemblyAiSttClient)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_assemblyai_stt.py -v`
Expected: FAIL — `ImportError: cannot import name 'AssemblyAiSttClient'`

- [ ] **Step 3: Update BaseSttClient interface**

In `backend/app/services/provider_clients.py`, update `BaseSttClient.start_session` (line 27):

```python
# OLD (line 27-28):
    async def start_session(self, session_id: str) -> None:
        pass

# NEW:
    async def start_session(self, session_id: str, *, vocabulary: list[str] | None = None) -> None:
        pass
```

Update `MockSttClient` to match (around line 117 — add vocabulary param to start_session if it has one, or add the method):

```python
class MockSttClient(BaseSttClient):
    provider_name = "mock_stt"

    async def start_session(self, session_id: str, *, vocabulary: list[str] | None = None) -> None:
        pass
```

Update `DeepgramSttClient.start_session` (line 164) to accept the new interface:

```python
# OLD:
    async def start_session(self, session_id: str, payload: dict | None = None) -> None:

# NEW:
    async def start_session(self, session_id: str, *, vocabulary: list[str] | None = None) -> None:
```

Inside the Deepgram `start_session` method, if `vocabulary` is provided, store it for passing as Deepgram `keywords` in WebSocket connection options. The existing `payload` parameter was only used for the session_id passthrough and is safe to replace.

**Important:** Before making this change, grep for all callers of `start_session` on STT providers:

Run: `cd backend && grep -rn "start_session" app/ tests/ --include="*.py" | grep -i stt`

Verify only `ws.py` calls it. If other callers pass `payload`, update them to use the new `vocabulary` kwarg.

- [ ] **Step 4: Add AssemblyAiSttClient**

In `backend/app/services/provider_clients.py`, add after the `DeepgramSttClient` class (around line 338):

```python
class AssemblyAiSttClient(BaseSttClient):
    """AssemblyAI real-time streaming STT client with domain vocabulary boosting.

    Uses AssemblyAI's real-time WebSocket API for streaming transcription,
    matching Deepgram's latency characteristics (~100-300ms for partials).
    """

    provider_name = "assemblyai"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._sessions: dict[str, Any] = {}
        self._vocabulary: list[str] = []
        self._fallback = MockSttClient()

    async def start_session(self, session_id: str, *, vocabulary: list[str] | None = None) -> None:
        self._vocabulary = vocabulary or []
        self._sessions[session_id] = {"vocabulary": self._vocabulary}

    async def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        """Process audio through AssemblyAI real-time streaming API."""
        import assemblyai as aai

        aai.settings.api_key = self._api_key
        session_id = payload.get("session_id", "")
        # Use _decode_base64_audio — same as DeepgramSttClient — reads payload["audio_base64"]
        audio_bytes = _decode_base64_audio(payload)
        on_partial = payload.get("on_partial")
        hint = str(payload.get("transcript_hint", "")).strip()

        if not audio_bytes:
            if hint:
                if on_partial:
                    on_partial(hint, True)
                return SttTranscript(text=hint, confidence=0.95, is_final=True, source="assemblyai_hint")
            return await self._fallback.finalize_utterance(payload)

        try:
            # Use real-time streaming transcriber for low latency
            final_text = ""
            final_confidence = 0.9

            def on_data(transcript: aai.RealtimeTranscript) -> None:
                nonlocal final_text, final_confidence
                if isinstance(transcript, aai.RealtimeFinalTranscript):
                    final_text = transcript.text
                    final_confidence = transcript.confidence or 0.9
                    if on_partial:
                        on_partial(transcript.text, True)
                elif isinstance(transcript, aai.RealtimePartialTranscript):
                    if on_partial and transcript.text:
                        on_partial(transcript.text, False)

            transcriber = aai.RealtimeTranscriber(
                sample_rate=16_000,
                word_boost=self._vocabulary[:1000] if self._vocabulary else None,
                on_data=on_data,
                on_error=lambda err: logger.error("AssemblyAI RT error: %s", err),
            )
            transcriber.connect()
            # Stream audio in chunks (8KB, matching Deepgram pattern)
            chunk_size = 8192
            for i in range(0, len(audio_bytes), chunk_size):
                transcriber.stream(audio_bytes[i:i + chunk_size])
            transcriber.close()

            if not final_text and hint:
                return SttTranscript(text=hint, confidence=0.5, is_final=True, source="assemblyai_hint_fallback")

            return SttTranscript(
                text=final_text, confidence=final_confidence, is_final=True, source="assemblyai"
            )
        except Exception as exc:
            logger.exception("AssemblyAI finalize_utterance failed: %s", exc)
            if hint:
                return SttTranscript(text=hint, confidence=0.5, is_final=True, source="assemblyai_fallback")
            return await self._fallback.finalize_utterance(payload)
```

**Note:** The `_decode_base64_audio` helper (already exists in provider_clients.py) reads `payload["audio_base64"]` which is the key sent by `ws.py` in the `client.audio.chunk` event. Using this ensures consistency with the Deepgram client.

- [ ] **Step 5: Update ProviderSuite.from_settings()**

In `backend/app/services/provider_clients.py`, update the STT provider resolution block in `from_settings()` (around lines 621-630):

```python
# Add assemblyai case to the STT resolution:
if settings.stt_provider == "assemblyai" and settings.assemblyai_api_key:
    stt = AssemblyAiSttClient(api_key=settings.assemblyai_api_key)
elif settings.stt_provider == "deepgram" and settings.deepgram_api_key:
    stt = DeepgramSttClient(...)
else:
    stt = MockSttClient()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_assemblyai_stt.py -v`
Expected: All tests PASS

- [ ] **Step 7: Run existing tests to verify no regressions**

Run: `cd backend && python3 -m pytest tests/test_provider_clients.py -v`
Expected: All existing tests PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/provider_clients.py backend/tests/test_assemblyai_stt.py
git commit -m "feat: add AssemblyAI STT client and update BaseSttClient interface for vocabulary"
```

---

## Task 5: Micro-Behavior Engine Refactoring

**Files:**
- Modify: `backend/app/services/micro_behavior_engine.py:99-180` (apply_to_response), `:207-218` (_apply_sentence_length), `:239-252` (_insert_filler)
- Modify: `backend/tests/test_micro_behavior_engine.py`

- [ ] **Step 1: Write tests for the new metadata-only behavior**

Add to `backend/tests/test_micro_behavior_engine.py`:

```python
class TestMetadataOnlyBehavior:
    """After refactoring, the engine should not modify text — only produce metadata."""

    def test_transformed_text_equals_input(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="I already have a pest control company.",
            emotion_before="neutral",
            emotion_after="skeptical",
            behavioral_signals=[],
            active_objections=["incumbent_provider"],
        )
        assert plan.transformed_text == "I already have a pest control company."

    def test_no_fillers_injected(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="That seems expensive.",
            emotion_before="skeptical",
            emotion_after="annoyed",
            behavioral_signals=[],
            active_objections=["price"],
        )
        # No "you know", "I mean", "Uh..." added
        assert plan.transformed_text == "That seems expensive."

    def test_no_sentence_truncation(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="I don't think so, we already have someone who comes out.",
            emotion_before="annoyed",
            emotion_after="annoyed",
            behavioral_signals=[],
            active_objections=[],
        )
        # Full text preserved even though emotion is "annoyed" (previously would truncate to short)
        assert plan.transformed_text == "I don't think so, we already have someone who comes out."

    def test_still_produces_metadata(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="What kind of treatment do you use?",
            emotion_before="curious",
            emotion_after="curious",
            behavioral_signals=[],
            active_objections=[],
        )
        assert plan.tone is not None
        assert plan.sentence_length is not None
        assert len(plan.segments) > 0
        assert plan.segments[0].pause_before_ms >= 0
        assert plan.segments[0].tone is not None
```

- [ ] **Step 2: Run tests to verify the new tests fail (old behavior still modifies text)**

Run: `cd backend && python3 -m pytest tests/test_micro_behavior_engine.py::TestMetadataOnlyBehavior -v`
Expected: FAIL — `transformed_text` will have fillers/hesitations injected

- [ ] **Step 3: Refactor apply_to_response to stop modifying text**

In `backend/app/services/micro_behavior_engine.py`, modify `apply_to_response()` (lines 99-180):

- Remove calls to `_insert_filler()`, `_apply_sentence_length()`, and hesitation/interruption prefix insertion
- Keep: tone computation, sentence_length computation, pause timing, segment splitting, realism_score
- Set `transformed_text = raw_text` always
- Keep the segment splitting logic but use the original text for each segment

Also remove or comment out `_apply_sentence_length` (lines 207-218) and `_insert_filler` (lines 239-252) method bodies — they are now dead code. Keep the methods as no-ops if other code references them, or remove entirely.

- [ ] **Step 4: Run all micro-behavior tests**

Run: `cd backend && python3 -m pytest tests/test_micro_behavior_engine.py -v`
Expected: New tests PASS. Some old tests may need updating if they asserted filler injection or truncation.

- [ ] **Step 5: Fix any broken existing tests**

Update existing tests that expected fillers/hesitations/truncation in `transformed_text`. These tests should now assert that `transformed_text == raw_text` and that metadata fields are still populated.

- [ ] **Step 6: Run full test suite**

Run: `cd backend && python3 -m pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/micro_behavior_engine.py backend/tests/test_micro_behavior_engine.py
git commit -m "refactor: micro-behavior engine to metadata-only, no more text transforms"
```

---

## Task 6: Prompt Architecture Overhaul

**Files:**
- Modify: `backend/app/services/conversation_orchestrator.py:197-212` (EMOTION dicts), `:348-477` (HomeownerPersona + PersonaEnricher), `:544-716` (PromptBuilder)
- Create: `backend/tests/test_prompt_builder_v2.py`

- [ ] **Step 1: Write failing tests for the new prompt behavior**

Create `backend/tests/test_prompt_builder_v2.py`:

```python
"""Tests for the overhauled PromptBuilder — no word caps, life details, delivery direction."""
import pytest
from unittest.mock import MagicMock

from app.services.conversation_orchestrator import (
    HomeownerPersona,
    PersonaEnricher,
    PromptBuilder,
    ScenarioSnapshot,
)


@pytest.fixture
def builder():
    return PromptBuilder()


@pytest.fixture
def base_persona():
    return HomeownerPersona(
        name="John",
        attitude="skeptical",
        concerns=["price", "safety"],
        objection_queue=["price", "trust"],
        buy_likelihood="medium",
        softening_condition="specific proof of local service",
    )


@pytest.fixture
def snapshot():
    return ScenarioSnapshot(
        name="Pest Control Pitch",
        description="A skeptical homeowner evaluates a pest control pitch.",
        difficulty=3,
        persona_payload={"name": "John", "attitude": "skeptical"},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering", "close_attempt", "ended"],
    )


class TestWordCapRemoval:
    """Verify hard word caps are removed from prompts."""

    def test_no_maximum_words_in_prompt(self, builder, base_persona, snapshot):
        prompt = builder.build(
            scenario=None,
            persona=base_persona,
            stage="initial_pitch",
            scenario_snapshot=snapshot,
        )
        assert "Maximum 10 words" not in prompt
        assert "Maximum 20 words" not in prompt
        assert "Maximum 30 words" not in prompt

    def test_no_one_sentence_only_rule(self, builder, base_persona, snapshot):
        prompt = builder.build(
            scenario=None,
            persona=base_persona,
            stage="objection_handling",
            scenario_snapshot=snapshot,
        )
        assert "one sentence only" not in prompt.lower()
        assert "Respond in one sentence" not in prompt


class TestEmotionLengthGuidance:
    """Verify per-emotion natural length guidance replaces word caps."""

    def test_hostile_gets_short_guidance(self, builder, base_persona, snapshot):
        prompt = builder.build(
            scenario=None, persona=base_persona, stage="objection_handling",
            scenario_snapshot=snapshot, emotion="hostile",
        )
        assert "sharp words" in prompt.lower() or "few" in prompt.lower()

    def test_curious_gets_engaging_guidance(self, builder, base_persona, snapshot):
        prompt = builder.build(
            scenario=None, persona=base_persona, stage="considering",
            scenario_snapshot=snapshot, emotion="curious",
        )
        assert "question" in prompt.lower() or "engaging" in prompt.lower()


class TestDeliveryDirection:
    """Verify delivery direction is included based on emotion."""

    def test_delivery_direction_present(self, builder, base_persona, snapshot):
        prompt = builder.build(
            scenario=None, persona=base_persona, stage="initial_pitch",
            scenario_snapshot=snapshot, emotion="skeptical",
        )
        assert "Delivery:" in prompt or "delivery:" in prompt.lower()

    def test_hostile_delivery_is_direct(self, builder, base_persona, snapshot):
        prompt = builder.build(
            scenario=None, persona=base_persona, stage="objection_handling",
            scenario_snapshot=snapshot, emotion="hostile",
        )
        assert "direct" in prompt.lower() or "clipped" in prompt.lower() or "sharp" in prompt.lower()


class TestPersonaLifeDetails:
    """Verify PersonaEnricher adds life detail fields."""

    def test_enricher_adds_at_home_reason(self):
        persona = HomeownerPersona(
            name="John", attitude="neutral", concerns=[], objection_queue=[],
            buy_likelihood="medium", softening_condition="proof",
            household_type="retired couple",
        )
        enriched = PersonaEnricher.enrich(persona, difficulty=3, description="pest control pitch")
        assert enriched.at_home_reason is not None
        assert len(enriched.at_home_reason) > 0

    def test_enricher_adds_specific_memory(self):
        persona = HomeownerPersona(
            name="Sarah", attitude="skeptical", concerns=["price"], objection_queue=["price"],
            buy_likelihood="low", softening_condition="proof",
            household_type="family with kids",
        )
        enriched = PersonaEnricher.enrich(persona, difficulty=4, description="pest control pitch")
        assert enriched.specific_memory is not None
        assert len(enriched.specific_memory) > 0

    def test_enricher_adds_last_salesperson_experience(self):
        persona = HomeownerPersona(
            name="Mike", attitude="hostile", concerns=[], objection_queue=[],
            buy_likelihood="low", softening_condition="",
        )
        enriched = PersonaEnricher.enrich(persona, difficulty=5, description="pest control pitch")
        assert enriched.last_salesperson_experience is not None

    def test_enricher_adds_current_mood_reason(self):
        persona = HomeownerPersona(
            name="Lisa", attitude="curious", concerns=[], objection_queue=[],
            buy_likelihood="high", softening_condition="",
        )
        enriched = PersonaEnricher.enrich(persona, difficulty=1, description="pest control pitch")
        assert enriched.current_mood_reason is not None

    def test_life_details_appear_in_prompt(self, builder, snapshot):
        persona = HomeownerPersona(
            name="John", attitude="skeptical", concerns=["price"], objection_queue=["price"],
            buy_likelihood="medium", softening_condition="proof",
            household_type="family with kids",
        )
        enriched = PersonaEnricher.enrich(persona, difficulty=3, description="pest control pitch")
        prompt = builder.build(
            scenario=None, persona=enriched, stage="initial_pitch",
            scenario_snapshot=snapshot,
        )
        # At least one life detail should appear in the prompt
        has_life_detail = any(
            field in prompt
            for field in [
                enriched.at_home_reason or "",
                enriched.specific_memory or "",
                enriched.last_salesperson_experience or "",
                enriched.current_mood_reason or "",
            ]
            if field
        )
        assert has_life_detail, "No life details found in prompt"


class TestTokenBudgetRemoval:
    """Verify the hard token budget is replaced with a generous ceiling."""

    def test_build_does_not_use_old_budget_function(self):
        """The PromptBuilder should not reference homeowner_token_budget."""
        import inspect
        source = inspect.getsource(PromptBuilder.build)
        assert "homeowner_token_budget" not in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_prompt_builder_v2.py -v`
Expected: FAIL — old word caps still present, no life details, no delivery direction

- [ ] **Step 3: Add life detail fields to HomeownerPersona**

In `backend/app/services/conversation_orchestrator.py`, add new fields to the `HomeownerPersona` dataclass (around line 348):

```python
@dataclass
class HomeownerPersona:
    name: str
    attitude: str
    concerns: list[str]
    objection_queue: list[str]
    buy_likelihood: str
    softening_condition: str
    household_type: str | None = None
    home_ownership_years: int | None = None
    pest_history: list[str] = field(default_factory=list)  # keep as list, not Optional — existing code iterates without None check
    price_sensitivity: str | None = None
    communication_style: str | None = None
    # Life details for natural responses
    at_home_reason: str | None = None
    last_salesperson_experience: str | None = None
    specific_memory: str | None = None
    current_mood_reason: str | None = None
```

Update `from_payload()` to read these from scenario persona dict if provided.

- [ ] **Step 4: Add life detail generation to PersonaEnricher**

In `PersonaEnricher.enrich()` (around line 398), add template-based generation for the new fields. Use `hash(persona.name + str(difficulty))` for deterministic selection:

```python
# Template tables
_AT_HOME_REASON = {
    "family with kids": ["stay-at-home parent", "working from home today", "kids are at school so catching up on things"],
    "retired couple": ["retired, home most days", "enjoying the morning at home"],
    "single homeowner": ["day off work", "working from home", "just got back from errands"],
}
_AT_HOME_DEFAULT = ["at home today", "just around the house"]

_SALESPERSON_EXPERIENCE = {
    1: ["doesn't get many solicitors", "hasn't had anyone knock in a while"],
    2: ["occasionally gets door-to-door salespeople", "had a lawn care guy come by last month"],
    3: ["gets salespeople every few weeks", "had a solar company knock last week"],
    4: ["getting tired of constant solicitors", "had a pushy solar guy last week who wouldn't leave"],
    5: ["fed up with door-to-door salespeople", "last one was rude and wouldn't take no for an answer"],
}

_MEMORY_TEMPLATES = [
    "neighbor {name} had {pest} last year and it cost around ${cost}",
    "saw a {pest} in the {room} {timeframe}",
    "read something online about {pest} in this area recently",
    "friend mentioned they use {company} and it's been fine",
]
_MEMORY_NAMES = ["Bob", "Karen", "Dave", "Maria", "Jim", "Susan"]
_MEMORY_PESTS = ["termites", "roaches", "ants", "mice", "spiders"]
_MEMORY_ROOMS = ["garage", "kitchen", "basement", "backyard", "bathroom"]
_MEMORY_TIMEFRAMES = ["last month", "a few weeks ago", "last summer"]
_MEMORY_COSTS = ["1,500", "2,000", "3,000", "800", "4,500"]
_MEMORY_COMPANIES = ["Orkin", "Terminix", "a local company", "some pest company"]

_MOOD_REASON = {
    1: ["relaxing at home", "just finished lunch", "was reading in the living room"],
    2: ["in the middle of something but not urgent", "was tidying up the house"],
    3: ["working on a project around the house", "was about to make a phone call"],
    4: ["in the middle of making lunch", "about to leave for an errand"],
    5: ["dealing with a stressful day", "was on an important phone call"],
}
```

Use `hash() % len(list)` to pick deterministically from each list.

- [ ] **Step 5: Overhaul PromptBuilder.build()**

In `PromptBuilder` (line 544+):

1. **Remove** `_response_cap_rule()` method (lines 705-710)
2. **Remove** references to `response_cap` and the `hard_rule` that enforces "one sentence only" and word limits
3. **Replace** with emotion-based length guidance in Layer 1:

```python
EMOTION_LENGTH_GUIDANCE = {
    "hostile": "You want this over. A few sharp words, maybe a sentence.",
    "annoyed": "Keep it short and impatient. One sentence, maybe two if you're making a point.",
    "skeptical": "You're testing them. A pointed question or a short challenge.",
    "neutral": "Polite but measured. A sentence or two.",
    "curious": "You're engaging now. Ask a real question or share a thought.",
    "interested": "You're warming up. You might think out loud for a couple sentences.",
}

DELIVERY_DIRECTION = {
    "hostile": "Delivery: direct and cutting -- no pleasantries, you want them gone.",
    "annoyed": "Delivery: impatient and clipped -- you have better things to do.",
    "skeptical": "Delivery: guarded and probing -- you're looking for holes in what they say.",
    "neutral": "Delivery: measured and reserved -- neither warm nor cold.",
    "curious": "Delivery: open but cautious -- you're interested but not sold.",
    "interested": "Delivery: warm and engaged -- you might hesitate or think aloud naturally.",
}
```

4. **Add life details** to Layer 2 if present on the persona:

```python
if persona.at_home_reason:
    layer_two_lines.append(f"You are home because: {persona.at_home_reason}")
if persona.last_salesperson_experience:
    layer_two_lines.append(f"Recent salesperson experience: {persona.last_salesperson_experience}")
if persona.specific_memory:
    layer_two_lines.append(f"Something on your mind: {persona.specific_memory}")
if persona.current_mood_reason:
    layer_two_lines.append(f"You were just: {persona.current_mood_reason}")
```

5. **Update Layer 1** to use emotion guidance + delivery direction instead of word caps:

```python
length_guidance = EMOTION_LENGTH_GUIDANCE.get(emotional_state, EMOTION_LENGTH_GUIDANCE["neutral"])
delivery = DELIVERY_DIRECTION.get(emotional_state, DELIVERY_DIRECTION["neutral"])

layer_one = (
    "LAYER 1 - IMMERSION CONTRACT\n"
    "You are a real homeowner in a live door-to-door roleplay.\n"
    "Never break character.\n"
    f"Response length: {length_guidance}\n"
    f"{delivery}\n"
    "React only to what the rep actually says.\n"
    "Do not volunteer extra information the rep has not earned.\n"
    f"{internal_rule}"
)
```

- [ ] **Step 6: Run new prompt tests**

Run: `cd backend && python3 -m pytest tests/test_prompt_builder_v2.py -v`
Expected: All tests PASS

- [ ] **Step 7: Run existing orchestrator tests**

Run: `cd backend && python3 -m pytest tests/test_conversation_orchestrator.py -v`
Expected: PASS (may need minor updates if tests asserted word cap strings)

- [ ] **Step 8: Fix any broken existing tests**

Update tests that checked for "Maximum 10 words" or "one sentence only" in prompts.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation_orchestrator.py backend/tests/test_prompt_builder_v2.py backend/tests/test_conversation_orchestrator.py
git commit -m "feat: overhaul PromptBuilder with emotion-driven guidance, life details, delivery direction"
```

---

## Task 7: Wire Transcript Repair and Quality Gate into ws.py

**Files:**
- Modify: `backend/app/voice/ws.py:59` (MAX_RUNTIME_PAUSE_MS), `:65-74` (homeowner_token_budget), `:219` (start_session), `:309-355` (run_stt result usage), `:682-687` (stream_reply max_tokens)
- Create: `backend/tests/test_response_quality_gate.py`

- [ ] **Step 1: Write quality gate tests**

Create `backend/tests/test_response_quality_gate.py`:

```python
"""Tests for the response quality gate relevance check."""
from app.voice.ws import check_response_relevance


class TestResponseRelevance:
    """Tests for the heuristic relevance scorer."""

    def test_engaged_response(self):
        score = check_response_relevance(
            rep_text="We offer a free inspection of your home",
            ai_response="What does the inspection cover?",
            emotion="curious",
        )
        assert score == "engaged"

    def test_deflection_when_hostile(self):
        score = check_response_relevance(
            rep_text="Can I tell you about our quarterly service?",
            ai_response="I need to go.",
            emotion="hostile",
        )
        assert score == "deflection"

    def test_deflection_when_annoyed(self):
        score = check_response_relevance(
            rep_text="We have great reviews online",
            ai_response="Look, I'm busy right now.",
            emotion="annoyed",
        )
        assert score == "deflection"

    def test_disconnected_response(self):
        score = check_response_relevance(
            rep_text="We use bifenthrin which is safe for kids and pets",
            ai_response="I'm not interested in whatever you're selling.",
            emotion="neutral",
        )
        assert score == "disconnected"

    def test_response_referencing_rep_keywords(self):
        score = check_response_relevance(
            rep_text="The quarterly service runs about forty dollars a month",
            ai_response="Forty dollars? That seems steep for quarterly.",
            emotion="skeptical",
        )
        assert score == "engaged"

    def test_short_dismissal_always_valid_when_hostile(self):
        score = check_response_relevance(
            rep_text="Let me explain our guarantee program",
            ai_response="No thanks.",
            emotion="hostile",
        )
        assert score == "deflection"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_response_quality_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_response_relevance' from 'app.voice.ws'`

- [ ] **Step 3: Update constants in ws.py**

In `backend/app/voice/ws.py`:

```python
# Line 59: Update pause cap
MAX_RUNTIME_PAUSE_MS = 300  # was 60

# Lines 65-74: Replace homeowner_token_budget with generous ceiling
HOMEOWNER_MAX_TOKENS = 100  # generous ceiling, prompt guides natural length
```

- [ ] **Step 4: Add check_response_relevance function to ws.py**

Add near the top of `backend/app/voice/ws.py` (after imports):

```python
import re
from collections import Counter


def check_response_relevance(
    rep_text: str, ai_response: str, emotion: str
) -> str:
    """Score whether the AI response engages with what the rep said.

    Returns: 'engaged', 'deflection', or 'disconnected'.
    """
    # Deflection is always valid for hostile/annoyed emotions
    dismissal_phrases = {"i need to go", "no thanks", "not interested", "i'm busy", "look, i'm busy", "gotta go"}
    response_lower = ai_response.lower().strip().rstrip(".")
    if emotion in ("hostile", "annoyed") and (
        len(ai_response.split()) <= 8
        or any(phrase in response_lower for phrase in dismissal_phrases)
    ):
        return "deflection"

    # Extract meaningful words from rep's text (4+ chars, skip common words)
    stop_words = {"the", "and", "that", "this", "with", "from", "your", "have",
                  "been", "will", "would", "could", "about", "just", "like",
                  "here", "there", "what", "they", "them", "some", "more"}
    rep_words = {
        w.lower().strip(".,!?;:'\"")
        for w in rep_text.split()
        if len(w.strip(".,!?;:'\"")) >= 4 and w.lower().strip(".,!?;:'\"") not in stop_words
    }

    response_lower_full = ai_response.lower()
    # Check if response references any of the rep's key words
    overlap = sum(1 for w in rep_words if w in response_lower_full)

    if overlap >= 1:
        return "engaged"

    # Check for semantic engagement (question responding to statement, etc.)
    if "?" in ai_response and emotion in ("curious", "interested", "neutral", "skeptical"):
        return "engaged"

    return "disconnected"
```

- [ ] **Step 5: Wire transcript repair into the voice pipeline**

In `backend/app/voice/ws.py`, after the STT imports, add:

```python
from app.services.transcript_repair_service import TranscriptRepairService

transcript_repair = TranscriptRepairService()
```

Update the `start_session` call (line 219) to pass vocabulary:

```python
boost_terms = transcript_repair.get_boost_terms()
# Add scenario-specific terms if available
if scenario and isinstance(scenario.persona, dict):
    company = scenario.persona.get("company_name", "")
    if company:
        boost_terms.append(company)
await providers.stt.start_session(session_id, vocabulary=boost_terms)
```

After `run_stt()` returns a transcript and before it's used by the orchestrator, add the repair step:

```python
# After getting stt_result from run_stt():
if stt_result and stt_result.text and settings.transcript_repair_enabled:
    repair_result = transcript_repair.deterministic_repair(stt_result.text)
    repaired_text = repair_result.repaired_text

    # If deterministic pass wasn't fully confident, try LLM repair
    if not repair_result.all_confident:
        conversation_context = []  # get last 2 turns from orchestrator state if available
        try:
            repaired_text = await transcript_repair.llm_repair(
                repair_result.repaired_text,
                conversation_context,
                providers.llm,
                model=settings.transcript_repair_model,
            )
        except Exception as exc:
            logger.warning("LLM transcript repair failed: %s", exc)

    if repair_result.repairs or repaired_text != stt_result.text:
        logger.info(
            "transcript_repaired",
            extra={
                "session_id": session_id,
                "original": stt_result.text,
                "repaired": repaired_text,
                "repairs": repair_result.repairs,
                "used_llm": not repair_result.all_confident,
            },
        )
    stt_result = SttTranscript(
        text=repaired_text,
        confidence=stt_result.confidence,
        is_final=stt_result.is_final,
        source=stt_result.source,
    )
```

- [ ] **Step 6: Wire quality gate into the response pipeline**

In the `stream_ai_response` function, after all LLM sentences are processed and before TTS tasks are awaited, add the quality gate check:

```python
# After the LLM streaming loop completes, before awaiting remaining TTS:
full_ai_text = "".join(ai_text_parts).strip()
if (
    settings.response_quality_gate_enabled
    and full_ai_text
    and len(tts_tasks) > 0
    and not ai_interrupted
):
    relevance = check_response_relevance(prompt_text, full_ai_text, emotion_after)
    if relevance == "disconnected":
        logger.warning(
            "response_quality_gate_triggered",
            extra={
                "session_id": session_id,
                "rep_text": prompt_text,
                "ai_response": full_ai_text,
                "emotion": emotion_after,
            },
        )
        # Cancel pending TTS tasks that haven't started emitting audio.
        # IMPORTANT: tts_emit_lock serializes TTS emission — cancelling a task
        # that holds the lock could leave it locked. Use asyncio.wait with a
        # short timeout to let in-flight tasks release the lock gracefully,
        # then cancel any remaining.
        for task in tts_tasks:
            if not task.done():
                task.cancel()
        # Wait briefly for cancellations to propagate
        if tts_tasks:
            await asyncio.gather(*tts_tasks, return_exceptions=True)
        tts_tasks.clear()
        ai_text_parts.clear()

        # Regenerate with augmented prompt
        augmented_system = (
            system_prompt + "\n\nCRITICAL: The rep just said: '"
            + prompt_text
            + "'. Your response MUST directly address what they said. "
            "React to their specific words, not to a generic pitch."
        )
        sentence_buffer = ""
        async for chunk in providers.llm.stream_reply(
            rep_text=prompt_text,
            stage=stage,
            system_prompt=augmented_system,
            max_tokens=HOMEOWNER_MAX_TOKENS,
        ):
            if interrupt_signal_at is not None:
                ai_interrupted = True
                break
            if not chunk:
                continue
            sentence_buffer += str(chunk)
            while True:
                match = re.search(r"[.?!](?:\s|$)", sentence_buffer)
                if match is None:
                    break
                sentence = sentence_buffer[:match.end()].strip()
                sentence_buffer = sentence_buffer[match.end():]
                if sentence:
                    await process_sentence(sentence)
        if sentence_buffer.strip() and not ai_interrupted:
            await process_sentence(sentence_buffer.strip())
```

- [ ] **Step 7: Update stream_reply call to use HOMEOWNER_MAX_TOKENS**

In `ws.py`, change the `stream_reply` call (around line 682-687):

```python
# OLD:
max_tokens=homeowner_token_budget(stage),

# NEW:
max_tokens=HOMEOWNER_MAX_TOKENS,
```

Remove or deprecate the `homeowner_token_budget()` function.

- [ ] **Step 8: Run quality gate tests**

Run: `cd backend && python3 -m pytest tests/test_response_quality_gate.py -v`
Expected: All tests PASS

- [ ] **Step 9: Run full test suite**

Run: `cd backend && python3 -m pytest -v`
Expected: All tests PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/voice/ws.py backend/tests/test_response_quality_gate.py
git commit -m "feat: wire transcript repair, quality gate, and updated token budget into voice pipeline"
```

---

## Task 8: Expand Conversation History Window

**Files:**
- Modify: `backend/app/services/provider_clients.py:90-114` (_TaskConversationHistoryMixin)

- [ ] **Step 1: Write failing test for expanded window**

Add to `backend/tests/test_provider_clients.py`:

```python
class TestExpandedHistoryWindow:
    """Verify the conversation history window is expanded to 24 turns."""

    def test_history_retains_24_turns(self):
        """History should keep 24 entries, not 12."""
        import asyncio
        from app.services.provider_clients import _TaskConversationHistoryMixin

        class TestClient(_TaskConversationHistoryMixin):
            pass

        client = TestClient()
        task = asyncio.current_task() or asyncio.ensure_future(asyncio.sleep(0))

        # Add 30 exchanges — note: _remember_exchange uses keyword-only args
        for i in range(30):
            client._remember_exchange(user_text=f"user message {i}", assistant_text=f"assistant response {i}")

        history = client._history_for_current_task()
        # Should retain 24, not 12
        assert len(history) == 24
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_provider_clients.py::TestExpandedHistoryWindow -v`
Expected: FAIL — `assert 12 == 24`

- [ ] **Step 3: Update the rolling window size**

In `backend/app/services/provider_clients.py`, line 113:

```python
# OLD:
if len(history) > 12: del history[:-12]

# NEW:
if len(history) > 24: del history[:-24]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_provider_clients.py::TestExpandedHistoryWindow -v`
Expected: PASS

- [ ] **Step 5: Add async context summary for long drills**

Add a `context_summary` field to the history mixin. After turn 24, and every 4 turns thereafter, generate a 2-3 sentence summary of the oldest turns being dropped. This runs asynchronously after the current turn completes (does NOT block the response).

In `_TaskConversationHistoryMixin`, add:

```python
_summary_by_task: weakref.WeakKeyDictionary[asyncio.Task[Any], str]

def _get_context_summary(self) -> str:
    """Return the summary of turns that fell off the rolling window."""
    task = asyncio.current_task()
    if task is None:
        return ""
    return self._summary_by_task.get(task, "")

async def _maybe_update_summary(self, llm_client: Any, model: str = "gpt-4o-mini") -> None:
    """Generate summary of dropped turns. Called async after turn completes."""
    history = self._history_for_current_task()
    task = asyncio.current_task()
    if task is None or len(history) < 24:
        return
    # Only update every 4 turns after the window fills
    turn_count = len(history) // 2  # each exchange is 2 entries
    if turn_count % 4 != 0:
        return
    # Summarize turns that are about to be dropped
    # (implementation: send oldest 8 entries to fast LLM for summary)
```

The summary is prepended to the system prompt as context: `"Earlier in this conversation: {summary}"`.

Uses `TRANSCRIPT_REPAIR_MODEL` (same fast model) for the summary call.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_provider_clients.py::TestExpandedHistoryWindow -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/provider_clients.py backend/tests/test_provider_clients.py
git commit -m "feat: expand conversation history window from 12 to 24 turns with async summary"
```

---

## Task 9: Integration Test and Full Verification

**Files:**
- All modified files
- Existing test suite

- [ ] **Step 1: Run the full test suite**

Run: `cd backend && python3 -m pytest -v --tb=short`
Expected: All tests PASS with no regressions

- [ ] **Step 2: Verify transcript repair end-to-end**

Run: `cd backend && python3 -c "
from app.services.transcript_repair_service import TranscriptRepairService
svc = TranscriptRepairService()
r = svc.deterministic_repair('We use by fen thin to treat for german watches around the parameter of your home')
print('Input:', r.original_text)
print('Output:', r.repaired_text)
print('Repairs:', r.repairs)
print('Confident:', r.all_confident)
"`
Expected: Output shows "bifenthrin", "German cockroaches", "perimeter" corrections

- [ ] **Step 3: Verify prompt output**

Run: `cd backend && python3 -c "
from app.services.conversation_orchestrator import PromptBuilder, HomeownerPersona, PersonaEnricher, ScenarioSnapshot
persona = HomeownerPersona(name='John', attitude='skeptical', concerns=['price'], objection_queue=['price', 'trust'], buy_likelihood='medium', softening_condition='proof', household_type='family with kids')
enriched = PersonaEnricher.enrich(persona, difficulty=3, description='pest control pitch')
snapshot = ScenarioSnapshot(name='Test', description='Test scenario', difficulty=3, persona_payload={}, stages=['door_knock', 'initial_pitch', 'objection_handling', 'considering', 'close_attempt', 'ended'])
prompt = PromptBuilder().build(scenario=None, persona=enriched, stage='initial_pitch', scenario_snapshot=snapshot, emotion='skeptical')
print(prompt[:2000])
print('---')
print('Has life details:', any(x in prompt for x in [enriched.at_home_reason or '', enriched.specific_memory or ''] if x))
print('Has delivery direction:', 'Delivery:' in prompt)
print('No word caps:', 'Maximum' not in prompt and 'one sentence only' not in prompt.lower())
"`
Expected: Shows prompt with life details, delivery direction, no word caps

- [ ] **Step 4: Verify quality gate function**

Run: `cd backend && python3 -c "
from app.voice.ws import check_response_relevance
print(check_response_relevance('We offer free inspections', 'What does that include?', 'curious'))
print(check_response_relevance('We offer free inspections', 'I need to go.', 'hostile'))
print(check_response_relevance('We use bifenthrin for German cockroaches', 'I am not interested in whatever you are selling.', 'neutral'))
"`
Expected: `engaged`, `deflection`, `disconnected`

- [ ] **Step 5: Final commit with all test updates**

```bash
git add -A
git status  # verify no sensitive files
git commit -m "test: integration verification for voice realism enhancements"
```
