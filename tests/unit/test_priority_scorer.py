"""
Unit tests for priority scoring.
"""
import pytest

from src.postprocessing.priority_scorer import PriorityScorer


class TestPriorityScorer:
    """Tests for the parametric priority scorer."""

    @pytest.fixture
    def scorer(self):
        return PriorityScorer()

    def test_low_priority_basic(self, scorer):
        result = scorer.score(
            subject="Informazioni generali",
            body_canonical="Buongiorno, vorrei sapere gli orari di apertura.",
            sentiment_value="neutral",
            customer_value="new",
        )
        # "new" adds 1.0 → medium (≥2.0)
        assert result["value"] in ("low", "medium")
        assert 0.0 <= result["confidence"] <= 1.0
        assert isinstance(result["signals"], list)
        assert isinstance(result["rawscore"], float)

    def test_urgent_priority_with_keywords(self, scorer):
        result = scorer.score(
            subject="URGENTE: guasto bloccante",
            body_canonical="Il servizio è fermo, richiediamo rimborso immediato. Diffida.",
            sentiment_value="negative",
            customer_value="existing",
        )
        assert result["value"] == "urgent"
        assert result["confidence"] == 0.95
        assert any("urgent_keywords" in s for s in result["signals"])
        assert "negative_sentiment" in result["signals"]

    def test_high_priority_with_problem(self, scorer):
        result = scorer.score(
            subject="Problema con il servizio",
            body_canonical="Non funziona il portale online, necessito assistenza urgente.",
            sentiment_value="negative",
            customer_value="existing",
        )
        assert result["value"] in ("high", "urgent")
        assert result["rawscore"] >= 4.0

    def test_deadline_detection(self, scorer):
        result = scorer.score(
            subject="Scadenza contratto",
            body_canonical="Dobbiamo rinnovare entro il 15 marzo.",
            sentiment_value="neutral",
            customer_value="existing",
        )
        assert "deadline_mentioned" in result["signals"]

    def test_vip_customer_boost(self, scorer):
        result_no_vip = scorer.score(
            subject="Info",
            body_canonical="Richiesta info",
            sentiment_value="neutral",
            customer_value="existing",
        )
        result_vip = scorer.score(
            subject="Info",
            body_canonical="Richiesta info",
            sentiment_value="neutral",
            customer_value="existing",
            vip_status=True,
        )
        assert result_vip["rawscore"] > result_no_vip["rawscore"]
        assert "vip_customer" in result_vip["signals"]

    def test_custom_weights(self):
        custom_weights = {
            "urgent_terms": 10.0,
            "high_terms": 0.0,
            "sentiment_negative": 0.0,
            "customer_new": 0.0,
            "deadline_signal": 0.0,
            "vip_customer": 0.0,
        }
        scorer = PriorityScorer(weights=custom_weights)
        result = scorer.score(
            subject="urgente",
            body_canonical="Test",
            sentiment_value="neutral",
            customer_value="existing",
        )
        assert result["rawscore"] == 10.0
        assert result["value"] == "urgent"

    def test_signals_list_content(self, scorer):
        result = scorer.score(
            subject="Problema urgente",
            body_canonical="Non funziona, urgente!",
            sentiment_value="negative",
            customer_value="new",
        )
        signals = result["signals"]
        assert isinstance(signals, list)
        assert len(signals) > 0
        # All signals should be strings
        assert all(isinstance(s, str) for s in signals)

    def test_bucketing_boundaries(self, scorer):
        """Verify bucketing thresholds are correct."""
        # Use multiple distinct urgent terms to accumulate score
        # Each urgent term contributes 3.0 by default
        # 3 terms × 3.0 = 9.0 → urgent (≥7.0)
        result = scorer.score(
            subject="urgente bloccante diffida guasto",
            body_canonical="",
            sentiment_value="neutral",
            customer_value="existing",
        )
        assert result["value"] == "urgent"
        assert result["rawscore"] >= 7.0
