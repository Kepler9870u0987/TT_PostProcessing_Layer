"""
Unit tests for confidence adjustment (★FIX #2★).
"""
import pytest

from src.postprocessing.confidence import (
    adjust_all_topic_confidences,
    build_collision_index,
    compute_topic_confidence_adjusted,
)


class TestComputeTopicConfidenceAdjusted:
    """Tests for the composite confidence formula."""

    def test_basic_confidence_calculation(self, mock_candidates):
        topic = {
            "labelid": "CONTRATTO",
            "confidence": 0.9,
            "keywordsintext": [{"candidateid": "ABC123"}],
            "evidence": [{"quote": "test evidence"}],
        }
        collision_index = {}

        adjusted = compute_topic_confidence_adjusted(
            topic, mock_candidates, collision_index, 0.9
        )

        assert 0.0 <= adjusted <= 1.0
        # With good keyword score (0.72), 1 evidence, no collision:
        # 0.3*0.9 + 0.4*0.72 + 0.2*0.5 + 0.1*1.0 = 0.27+0.288+0.1+0.1 = 0.758
        assert adjusted > 0.5

    def test_no_keywords_very_low_confidence(self, mock_candidates):
        topic = {
            "labelid": "CONTRATTO",
            "confidence": 0.9,
            "keywordsintext": [],
            "evidence": [{"quote": "test"}],
        }
        adjusted = compute_topic_confidence_adjusted(
            topic, mock_candidates, {}, 0.9
        )
        assert adjusted == 0.1

    def test_collision_penalty_reduces_confidence(self, mock_candidates, mock_collision_index):
        topic = {
            "labelid": "CONTRATTO",
            "confidence": 0.9,
            "keywordsintext": [{"candidateid": "ABC123"}],  # "contratto" collides
            "evidence": [{"quote": "test"}],
        }

        # Without collision
        conf_no_collision = compute_topic_confidence_adjusted(
            topic, mock_candidates, {}, 0.9
        )

        # With collision (contratto → CONTRATTO + FATTURAZIONE)
        conf_with_collision = compute_topic_confidence_adjusted(
            topic, mock_candidates, mock_collision_index, 0.9
        )

        assert conf_with_collision < conf_no_collision

    def test_more_evidence_increases_confidence(self, mock_candidates):
        topic_1_ev = {
            "labelid": "CONTRATTO",
            "confidence": 0.8,
            "keywordsintext": [{"candidateid": "ABC123"}],
            "evidence": [{"quote": "ev1"}],
        }
        topic_2_ev = {
            "labelid": "CONTRATTO",
            "confidence": 0.8,
            "keywordsintext": [{"candidateid": "ABC123"}],
            "evidence": [{"quote": "ev1"}, {"quote": "ev2"}],
        }

        conf_1 = compute_topic_confidence_adjusted(topic_1_ev, mock_candidates, {}, 0.8)
        conf_2 = compute_topic_confidence_adjusted(topic_2_ev, mock_candidates, {}, 0.8)

        assert conf_2 > conf_1


class TestAdjustAllTopicConfidences:
    """Tests for adjust_all_topic_confidences (★FIX #2★ naming)."""

    def test_naming_convention(self, mock_candidates):
        output = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.85,
                    "keywordsintext": [{"candidateid": "ABC123"}],
                    "evidence": [{"quote": "test"}],
                },
            ],
        }

        result = adjust_all_topic_confidences(output, mock_candidates, {})
        topic = result["topics"][0]

        # ★FIX #2★ Check all three naming fields
        assert "confidence_llm" in topic
        assert "confidence_adjusted" in topic
        assert "confidence" in topic

        # confidence_llm = original
        assert topic["confidence_llm"] == 0.85

        # confidence = confidence_adjusted (backward compat alias)
        assert topic["confidence"] == topic["confidence_adjusted"]

    def test_multiple_topics_adjusted(self, mock_candidates):
        output = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.9,
                    "keywordsintext": [{"candidateid": "ABC123"}],
                    "evidence": [{"quote": "ev1"}],
                },
                {
                    "labelid": "FATTURAZIONE",
                    "confidence": 0.7,
                    "keywordsintext": [{"candidateid": "DEF456"}],
                    "evidence": [{"quote": "ev2"}],
                },
            ],
        }

        result = adjust_all_topic_confidences(output, mock_candidates, {})

        assert len(result["topics"]) == 2
        for topic in result["topics"]:
            assert "confidence_llm" in topic
            assert "confidence_adjusted" in topic
            assert 0.0 <= topic["confidence_adjusted"] <= 1.0


class TestBuildCollisionIndex:
    """Tests for collision index builder (placeholder)."""

    def test_returns_empty_dict(self, mock_candidates):
        index = build_collision_index(mock_candidates)
        assert isinstance(index, dict)
        # Placeholder returns empty — no historical data yet
        assert len(index) == 0
