"""
Unit tests for validation & normalization (Stage 1).
Tests: validate_llm_output_multistage, deduplicate_and_normalize,
       verify_evidence_quotes, enforce_evidence_policy.
"""
import json

import pytest

from src.postprocessing.validation import (
    deduplicate_and_normalize,
    enforce_evidence_policy,
    validate_llm_output_multistage,
    verify_evidence_quotes,
)


class TestValidateLLMOutputMultistage:
    """Tests for the multi-stage validation function."""

    def test_valid_output_passes(self, mock_llm_output_json, mock_candidates, mock_document):
        result = validate_llm_output_multistage(
            mock_llm_output_json,
            mock_candidates,
            mock_document.body_canonical,
        )
        assert result.valid is True
        assert len(result.errors) == 0
        assert result.data is not None

    def test_invalid_json_fails(self, mock_candidates, mock_document):
        result = validate_llm_output_multistage(
            "not valid json {{{",
            mock_candidates,
            mock_document.body_canonical,
        )
        assert result.valid is False
        assert any("Invalid JSON" in e for e in result.errors)

    def test_invented_candidateid_blocked(self, mock_candidates, mock_document):
        bad_output = {
            "dictionaryversion": 42,
            "sentiment": {"value": "neutral", "confidence": 0.5},
            "priority": {"value": "low", "confidence": 0.5, "signals": []},
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.8,
                    "keywordsintext": [{"candidateid": "INVENTED_ID_999"}],
                    "evidence": [{"quote": "test"}],
                },
            ],
        }
        result = validate_llm_output_multistage(
            json.dumps(bad_output),
            mock_candidates,
            mock_document.body_canonical,
        )
        assert result.valid is False
        assert any("Invented candidateid" in e for e in result.errors)

    def test_invalid_labelid_blocked(self, mock_candidates, mock_document):
        bad_output = {
            "dictionaryversion": 42,
            "sentiment": {"value": "neutral", "confidence": 0.5},
            "priority": {"value": "low", "confidence": 0.5, "signals": []},
            "topics": [
                {
                    "labelid": "NONEXISTENT_TOPIC",
                    "confidence": 0.8,
                    "keywordsintext": [{"candidateid": "ABC123"}],
                    "evidence": [{"quote": "test"}],
                },
            ],
        }
        result = validate_llm_output_multistage(
            json.dumps(bad_output),
            mock_candidates,
            mock_document.body_canonical,
        )
        assert result.valid is False
        # Schema validation catches invalid enum before business rules
        assert any("Schema violation" in e or "Invalid labelid" in e for e in result.errors)

    def test_dict_input_accepted(self, mock_llm_output, mock_candidates, mock_document):
        """Can accept dict directly (not just JSON string)."""
        result = validate_llm_output_multistage(
            mock_llm_output,
            mock_candidates,
            mock_document.body_canonical,
        )
        assert result.valid is True

    def test_low_confidence_generates_warning(self, mock_candidates, mock_document):
        output = {
            "dictionaryversion": 42,
            "sentiment": {"value": "neutral", "confidence": 0.5},
            "priority": {"value": "low", "confidence": 0.5, "signals": []},
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.1,  # Very low
                    "keywordsintext": [{"candidateid": "ABC123"}],
                    "evidence": [{"quote": "test"}],
                },
            ],
        }
        result = validate_llm_output_multistage(
            json.dumps(output),
            mock_candidates,
            mock_document.body_canonical,
        )
        assert result.valid is True
        assert any("Very low confidence" in w for w in result.warnings)


class TestDeduplication:
    """Tests for deduplication & normalization."""

    def test_removes_duplicate_topics(self):
        data = {
            "topics": [
                {"labelid": "CONTRATTO", "confidence": 0.9, "keywordsintext": []},
                {"labelid": "CONTRATTO", "confidence": 0.8, "keywordsintext": []},
                {"labelid": "FATTURAZIONE", "confidence": 0.7, "keywordsintext": []},
            ],
            "sentiment": {"confidence": 0.5},
            "priority": {"confidence": 0.5},
        }
        result = deduplicate_and_normalize(data)
        assert len(result["topics"]) == 2
        assert result["topics"][0]["labelid"] == "CONTRATTO"
        assert result["topics"][0]["confidence"] == 0.9  # Keeps first

    def test_removes_duplicate_keywords(self):
        data = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.9,
                    "keywordsintext": [
                        {"candidateid": "ABC123"},
                        {"candidateid": "ABC123"},  # Duplicate
                        {"candidateid": "DEF456"},
                    ],
                },
            ],
            "sentiment": {"confidence": 0.5},
            "priority": {"confidence": 0.5},
        }
        result = deduplicate_and_normalize(data)
        assert len(result["topics"][0]["keywordsintext"]) == 2

    def test_clamps_confidence_values(self):
        data = {
            "topics": [
                {"labelid": "CONTRATTO", "confidence": 1.5, "keywordsintext": []},
            ],
            "sentiment": {"confidence": -0.3},
            "priority": {"confidence": 2.0},
        }
        result = deduplicate_and_normalize(data)
        assert result["topics"][0]["confidence"] == 1.0
        assert result["sentiment"]["confidence"] == 0.0
        assert result["priority"]["confidence"] == 1.0


class TestEvidenceVerification:
    """Tests for evidence quote verification (★FIX #7★)."""

    def test_valid_quote_no_warning(self):
        text = "Buongiorno, vorrei confermare i dati del contratto."
        topics = [
            {
                "evidence": [
                    {"quote": "confermare i dati del contratto"},
                ],
            },
        ]
        warnings = verify_evidence_quotes(topics, text)
        assert len(warnings) == 0

    def test_missing_quote_generates_warning(self):
        text = "Buongiorno, testo completamente diverso."
        topics = [
            {
                "evidence": [
                    {"quote": "questa frase non esiste"},
                ],
            },
        ]
        warnings = verify_evidence_quotes(topics, text)
        assert len(warnings) == 1
        assert "not found in text" in warnings[0]

    def test_span_mismatch_generates_warning(self):
        text = "Buongiorno, vorrei confermare i dati del contratto."
        topics = [
            {
                "evidence": [
                    {
                        "quote": "confermare i dati del contratto",
                        "span": [0, 10],  # Wrong span
                    },
                ],
            },
        ]
        warnings = verify_evidence_quotes(topics, text)
        assert any("Span mismatch" in w for w in warnings)


class TestEvidencePolicy:
    """Tests for evidence policy enforcement."""

    def test_good_evidence_passes(self):
        text = "Ho un contratto da verificare."
        topics = [
            {"evidence": [{"quote": "contratto da verificare"}]},
        ]
        assert enforce_evidence_policy(topics, text, threshold=0.3) is True

    def test_bad_evidence_fails(self):
        text = "Testo completamente diverso."
        topics = [
            {"evidence": [{"quote": "frase inventata 1"}, {"quote": "frase inventata 2"}]},
        ]
        assert enforce_evidence_policy(topics, text, threshold=0.3) is False

    def test_empty_evidence_passes(self):
        assert enforce_evidence_policy([], "any text", threshold=0.3) is True
