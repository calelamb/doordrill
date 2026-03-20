from __future__ import annotations

import re
from dataclasses import dataclass, field


HOMEOWNER_WARMING_PHRASES = (
    "okay, that makes sense",
    "i guess i could",
    "tell me more",
    "how does that work",
    "what would that look like",
    "that's fair",
)
HOMEOWNER_HARDENING_PHRASES = (
    "i told you",
    "i already said",
    "not interested",
    "please just",
    "i need to go",
    "i'm not going to",
)
HOMEOWNER_TESTING_PHRASES = (
    "what if",
    "how do i know",
    "can you prove",
    "show me",
    "what's the catch",
)


def _normalize_text(text: str | None) -> str:
    return " ".join(str(text or "").lower().split()).strip()


@dataclass
class HomeownerSignalSnapshot:
    signals: list[str] = field(default_factory=list)
    warming_hits: list[str] = field(default_factory=list)
    hardening_hits: list[str] = field(default_factory=list)
    testing_hits: list[str] = field(default_factory=list)
    pending_test_question: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "signals": list(self.signals),
            "warming_hits": list(self.warming_hits),
            "hardening_hits": list(self.hardening_hits),
            "testing_hits": list(self.testing_hits),
            "pending_test_question": self.pending_test_question,
        }


class HomeownerSignalDetector:
    def detect(self, text: str | None) -> HomeownerSignalSnapshot:
        normalized = _normalize_text(text)
        warming_hits = [phrase for phrase in HOMEOWNER_WARMING_PHRASES if phrase in normalized]
        hardening_hits = [phrase for phrase in HOMEOWNER_HARDENING_PHRASES if phrase in normalized]
        testing_hits = [phrase for phrase in HOMEOWNER_TESTING_PHRASES if phrase in normalized]

        signals: list[str] = []
        if warming_hits:
            signals.append("warming")
        if hardening_hits:
            signals.append("hardening")
        if testing_hits:
            signals.append("testing")

        pending_test_question = self._extract_pending_test_question(text) if testing_hits else None
        return HomeownerSignalSnapshot(
            signals=signals,
            warming_hits=warming_hits,
            hardening_hits=hardening_hits,
            testing_hits=testing_hits,
            pending_test_question=pending_test_question,
        )

    def _extract_pending_test_question(self, text: str | None) -> str | None:
        raw = " ".join(str(text or "").split()).strip()
        if not raw:
            return None
        question_match = re.search(r"([^?]+\?)", raw)
        if question_match:
            return question_match.group(1).strip()
        sentences = re.split(r"(?<=[.!])\s+", raw)
        for sentence in sentences:
            normalized = _normalize_text(sentence)
            if any(phrase in normalized for phrase in HOMEOWNER_TESTING_PHRASES):
                return sentence.strip()
        return raw
