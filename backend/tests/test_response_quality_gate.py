"""Tests for the response quality gate relevance check."""
from app.voice.ws import check_response_relevance


class TestResponseRelevance:
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

    def test_question_response_when_curious(self):
        score = check_response_relevance(
            rep_text="We've been serving this area for years",
            ai_response="How long exactly?",
            emotion="curious",
        )
        assert score == "engaged"
