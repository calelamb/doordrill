"""Transcript repair service for fixing domain-specific STT misrecognitions."""
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
FUZZY_THRESHOLD = 82
FUZZY_CONFIDENT_THRESHOLD = 92


@dataclass
class RepairResult:
    repaired_text: str
    original_text: str
    repairs: list[dict[str, str]] = field(default_factory=list)
    all_confident: bool = True


class TranscriptRepairService:
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
        mapping: dict[str, str] = {}
        for category in self.vocabulary.values():
            if isinstance(category, dict) and "misrecognitions" in category:
                for wrong, right in category["misrecognitions"].items():
                    mapping[wrong.lower()] = right
        return mapping

    def _build_term_list(self) -> list[str]:
        terms: list[str] = []
        for category in self.vocabulary.values():
            if isinstance(category, dict) and "terms" in category:
                terms.extend(category["terms"])
        return terms

    def get_boost_terms(self) -> list[str]:
        return list(self._all_terms)

    def deterministic_repair(self, text: str) -> RepairResult:
        original = text
        repairs: list[dict[str, str]] = []
        all_confident = True
        repaired = text

        # Pass 1: exact misrecognition lookup (case-insensitive, multi-word, longest first)
        for wrong, right in sorted(self._misrecognition_map.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(re.escape(wrong), re.IGNORECASE)
            if pattern.search(repaired):
                repaired = pattern.sub(right, repaired)
                repairs.append({"original": wrong, "replacement": right, "method": "exact"})

        # Pass 2: fuzzy match individual tokens
        words = repaired.split()
        for i, word in enumerate(words):
            clean = word.strip(".,!?;:'\"").lower()
            if len(clean) < 4 or clean in _COMMON_WORDS:
                continue
            if any(clean in term.lower() for term in self._all_terms):
                continue

            match = process.extractOne(clean, [t.lower() for t in self._all_terms], scorer=fuzz.ratio)
            if match is None:
                continue

            matched_term, score, _ = match
            if score >= FUZZY_CONFIDENT_THRESHOLD:
                original_term = next((t for t in self._all_terms if t.lower() == matched_term), matched_term)
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
                repairs.append({"original": clean, "replacement": original_term, "method": "fuzzy", "score": score})
            elif score >= FUZZY_THRESHOLD:
                all_confident = False

        repaired = " ".join(words)
        return RepairResult(repaired_text=repaired, original_text=original, repairs=repairs, all_confident=all_confident)

    async def llm_repair(self, text: str, conversation_context: list[dict[str, str]], llm_client: Any, model: str = "gpt-4o-mini") -> str:
        context_str = "\n".join(f"{turn['role']}: {turn['content']}" for turn in conversation_context[-4:])
        system_prompt = (
            "Fix domain-specific speech recognition errors in this pest control sales transcript. "
            "Only change words that are clearly misrecognized. Return the corrected transcript only. "
            "Do not add, remove, or rephrase anything else."
        )
        user_prompt = f"Recent conversation:\n{context_str}\n\nTranscript to fix: {text}"
        try:
            repaired = ""
            async for chunk in llm_client.stream_reply(rep_text=user_prompt, stage="repair", system_prompt=system_prompt, max_tokens=100):
                repaired += str(chunk)
            return repaired.strip() or text
        except Exception as exc:
            logger.warning("LLM repair failed, using deterministic result: %s", exc)
            return text


_COMMON_WORDS = frozenset({
    "the", "and", "that", "this", "with", "from", "your", "have", "been",
    "will", "would", "could", "should", "about", "which", "their", "there",
    "here", "what", "when", "where", "they", "them", "then", "than",
    "some", "more", "much", "very", "also", "just", "like", "know",
    "make", "take", "come", "good", "well", "back", "over", "such",
    "after", "year", "most", "only", "into", "other", "time",
    "long", "look", "want", "does", "doing", "going", "home", "house",
    "door", "said", "tell", "told", "hear", "heard", "talk", "talking",
    "sure", "okay", "yeah", "right", "really", "think", "price", "cost",
    "safe", "kids", "family", "treat", "spray", "service", "company",
    "pest", "control", "bugs", "help", "free", "today", "need",
})
