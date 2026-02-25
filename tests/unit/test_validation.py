"""
Unit tests for validation & normalization (Stage 1).
Tests: validate_llm_output_multistage, deduplicate_and_normalize,
       verify_evidence_quotes, enforce_evidence_policy.
"""
import json

import pytest

from src.postprocessing.validation import (
    compute_span_from_quote,
    deduplicate_and_normalize,
    enforce_evidence_policy,
    enrich_evidence_with_spans,
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


# ===========================================================================
# Fix 1 regression — LLM echo fields must NOT generate warnings
# ===========================================================================

class TestSchemaStripNoWarnings:
    """LLM naturally echoes count/lemma/term/source/embeddingscore.
    After Fix 1, only truly unexpected fields should produce warnings."""

    def _make_output(self, kw_fields: dict) -> dict:
        return {
            "dictionaryversion": 42,
            "sentiment": {"value": "neutral", "confidence": 0.5},
            "priority": {"value": "low", "confidence": 0.5, "signals": []},
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.8,
                    "keywordsintext": [{**kw_fields, "candidateid": "ABC123"}],
                    "evidence": [{"quote": "test"}],
                },
            ],
        }

    def test_count_lemma_no_strip_warning(self, mock_candidates, mock_document):
        """count + lemma from LLM must NOT produce a 'stripped unexpected fields' warning."""
        output = self._make_output({"lemma": "contratto", "count": 2})
        result = validate_llm_output_multistage(
            output, mock_candidates, mock_document.body_canonical
        )
        strip_warnings = [w for w in result.warnings if "stripped unexpected fields" in w]
        assert strip_warnings == [], f"Unexpected strip warnings: {strip_warnings}"

    def test_all_known_echo_fields_no_strip_warning(self, mock_candidates, mock_document):
        """All known LLM echo fields must be silently accepted."""
        output = self._make_output({
            "lemma": "contratto",
            "count": 2,
            "term": "contratto",
            "source": "body",
            "embeddingscore": 0.75,
        })
        result = validate_llm_output_multistage(
            output, mock_candidates, mock_document.body_canonical
        )
        strip_warnings = [w for w in result.warnings if "stripped unexpected fields" in w]
        assert strip_warnings == []

    def test_truly_unknown_field_still_warns(self, mock_candidates, mock_document):
        """A genuinely unknown field must still produce a warning."""
        output = self._make_output({"totally_unknown_field": "value"})
        result = validate_llm_output_multistage(
            output, mock_candidates, mock_document.body_canonical
        )
        strip_warnings = [w for w in result.warnings if "stripped unexpected fields" in w]
        assert len(strip_warnings) == 1
        assert "totally_unknown_field" in strip_warnings[0]


# ===========================================================================
# Fix 2 — server-side span computation
# ===========================================================================

class TestComputeSpanFromQuote:
    """Unit tests for compute_span_from_quote()."""

    def test_exact_match(self):
        body = "Buongiorno, vorrei confermare i dati del contratto."
        quote = "confermare i dati del contratto"
        span, status = compute_span_from_quote(quote, body)
        assert status == "exact_match"
        assert span is not None
        assert body[span[0]:span[1]] == quote

    def test_exact_match_at_start(self):
        body = "Codice Fiscale: RSSMRA80A01H501U e altro testo"
        quote = "Codice Fiscale: RSSMRA80A01H501U"
        span, status = compute_span_from_quote(quote, body)
        assert status == "exact_match"
        assert span == [0, len(quote)]

    def test_fuzzy_match_double_space(self):
        body = "verifica  il  documento allegato"
        quote = "verifica il documento allegato"
        span, status = compute_span_from_quote(quote, body)
        assert status in ("exact_match", "fuzzy_match")
        assert span is not None

    def test_not_found(self):
        body = "Testo completamente diverso senza corrispondenza."
        quote = "questa frase non esiste nel testo"
        span, status = compute_span_from_quote(quote, body)
        assert status == "not_found"
        assert span is None

    def test_empty_quote_returns_not_found(self):
        span, status = compute_span_from_quote("", "qualsiasi testo")
        assert status == "not_found"
        assert span is None

    def test_empty_body_returns_not_found(self):
        span, status = compute_span_from_quote("una quote", "")
        assert status == "not_found"
        assert span is None


class TestEnrichEvidenceWithSpans:
    """Unit tests for enrich_evidence_with_spans()."""

    def test_exact_match_sets_span_and_status(self):
        body = "Vorrei confermare i dati del contratto."
        topics = [{"evidence": [{"quote": "confermare i dati del contratto"}]}]
        result = enrich_evidence_with_spans(topics, body)
        ev = result[0]["evidence"][0]
        assert ev["span_status"] == "exact_match"
        assert ev["span"] is not None
        assert body[ev["span"][0]:ev["span"][1]] == "confermare i dati del contratto"

    def test_llm_span_preserved_as_span_llm(self):
        body = "Vorrei confermare i dati del contratto."
        original_llm_span = [0, 5]
        topics = [{"evidence": [{"quote": "confermare i dati del contratto", "span": original_llm_span}]}]
        result = enrich_evidence_with_spans(topics, body)
        ev = result[0]["evidence"][0]
        assert ev["span_llm"] == original_llm_span

    def test_missing_llm_span_stored_as_none(self):
        body = "Testo di prova."
        topics = [{"evidence": [{"quote": "Testo di prova"}]}]
        result = enrich_evidence_with_spans(topics, body)
        ev = result[0]["evidence"][0]
        assert ev["span_llm"] is None

    def test_not_found_sets_span_none(self):
        body = "Testo completamente diverso."
        topics = [{"evidence": [{"quote": "frase inesistente al mondo"}]}]
        result = enrich_evidence_with_spans(topics, body)
        ev = result[0]["evidence"][0]
        assert ev["span_status"] == "not_found"
        assert ev["span"] is None

    def test_multiple_topics_all_enriched(self):
        body = "contratto firmato e fattura pagata."
        topics = [
            {"evidence": [{"quote": "contratto firmato"}]},
            {"evidence": [{"quote": "fattura pagata"}]},
        ]
        result = enrich_evidence_with_spans(topics, body)
        for t in result:
            for ev in t["evidence"]:
                assert "span_status" in ev
                assert "span_llm" in ev

    def test_text_hash_present_and_correct(self):
        import hashlib
        body = "Testo per il test dell'hash SHA-256."
        topics = [{"evidence": [{"quote": "test dell'hash"}]}]
        result = enrich_evidence_with_spans(topics, body)
        ev = result[0]["evidence"][0]
        expected = hashlib.sha256(body.encode()).hexdigest()
        assert "text_hash" in ev
        assert ev["text_hash"] == expected
        assert len(ev["text_hash"]) == 64  # SHA-256 hex digest is 64 chars

    def test_text_hash_consistent_across_evidence_items(self):
        body = "Contratto firmato. Fattura pagata."
        topics = [{
            "evidence": [
                {"quote": "Contratto firmato"},
                {"quote": "Fattura pagata"},
            ]
        }]
        result = enrich_evidence_with_spans(topics, body)
        hashes = [ev["text_hash"] for ev in result[0]["evidence"]]
        # All evidence for the same body_canonical must share the same hash
        assert len(set(hashes)) == 1

    def test_not_found_also_has_text_hash(self):
        body = "Testo completamente diverso."
        topics = [{"evidence": [{"quote": "frase inesistente al mondo"}]}]
        result = enrich_evidence_with_spans(topics, body)
        ev = result[0]["evidence"][0]
        assert ev["span_status"] == "not_found"
        assert "text_hash" in ev
        assert ev["text_hash"] is not None
