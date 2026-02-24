"""
Unit tests for output normalization (★FIX #4★).
"""
import pytest

from src.postprocessing.output_builder import (
    build_triage_output_schema,
    normalize_topics_keywords,
)


class TestNormalizeTopicsKeywords:
    """Tests for ★FIX #4★ keywordsintext → keywords mapping."""

    def test_maps_keywordsintext_to_keywords(self):
        topics = [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [
                    {
                        "candidateid": "ABC123",
                        "term": "contratto",
                        "lemma": "contratto",
                        "count": 3,
                        "source": "subject",
                        "embeddingscore": 0.8,
                    },
                ],
            },
        ]
        result = normalize_topics_keywords(topics)

        assert "keywords" in result[0]
        assert len(result[0]["keywords"]) == 1

        kw = result[0]["keywords"][0]
        assert kw["candidateid"] == "ABC123"
        assert kw["term"] == "contratto"
        assert kw["lemma"] == "contratto"
        assert kw["count"] == 3
        assert kw["source"] == "subject"
        assert kw["embeddingscore"] == 0.8

    def test_empty_keywordsintext(self):
        topics = [{"labelid": "CONTRATTO", "keywordsintext": []}]
        result = normalize_topics_keywords(topics)
        assert result[0]["keywords"] == []

    def test_missing_embeddingscore_defaults(self):
        topics = [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [
                    {
                        "candidateid": "ABC",
                        "term": "t",
                        "lemma": "l",
                        "count": 1,
                        "source": "body",
                    },
                ],
            },
        ]
        result = normalize_topics_keywords(topics)
        assert result[0]["keywords"][0]["embeddingscore"] == 0.0


class TestBuildTriageOutputSchema:
    """Tests for the complete triage output builder."""

    def test_complete_output_structure(self):
        triage = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.85,
                    "confidence_llm": 0.9,
                    "confidence_adjusted": 0.85,
                    "keywordsintext": [
                        {
                            "candidateid": "ABC",
                            "term": "contratto",
                            "lemma": "contratto",
                            "count": 1,
                            "source": "subject",
                            "embeddingscore": 0.8,
                        },
                    ],
                    "evidence": [{"quote": "test evidence"}],
                },
            ],
            "sentiment": {"value": "neutral", "confidence": 0.7},
        }
        customer_status = {"value": "existing", "confidence": 1.0, "source": "crm_exact_match"}
        priority = {"value": "medium", "confidence": 0.75, "signals": ["test"], "rawscore": 2.5}

        result = build_triage_output_schema(triage, customer_status, priority)

        assert "topics" in result
        assert "sentiment" in result
        assert "priority" in result
        assert "customerstatus" in result

        # Check keywords mapping happened
        assert "keywords" in result["topics"][0]
        assert result["customerstatus"]["value"] == "existing"
        assert result["priority"]["value"] == "medium"

    def test_confidence_fields_defaulted(self):
        triage = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.85,
                    "keywordsintext": [],
                    "evidence": [],
                },
            ],
            "sentiment": {"value": "neutral", "confidence": 0.5},
        }

        result = build_triage_output_schema(
            triage,
            {"value": "new", "confidence": 0.8, "source": "no_crm_no_signal"},
            {"value": "low", "confidence": 0.7, "signals": [], "rawscore": 0.0},
        )

        topic = result["topics"][0]
        assert "confidence_llm" in topic
        assert "confidence_adjusted" in topic
