"""
Integration tests — full pipeline end-to-end.
"""
import json

import pytest

from src.models.email_document import EmailDocument
from src.models.pipeline_version import PipelineVersion
from src.postprocessing.pipeline import postprocess_and_enrich


class TestPipelineE2E:
    """End-to-end integration tests for the full pipeline."""

    @pytest.fixture
    def full_pipeline_inputs(self):
        doc = EmailDocument(
            message_id="int-test-001@example.it",
            from_raw="Mario Rossi <mario.rossi@example.it>",
            subject="Richiesta urgente contratto ABC",
            body="Buongiorno, vorrei confermare i dati del contratto. "
                 "Ho una fattura da saldare entro il 15 marzo. "
                 "Il mio codice è RSSMRA85M01H501Z. "
                 "Potete contattarmi a mario.rossi@example.it.",
            body_canonical="Buongiorno, vorrei confermare i dati del contratto. "
                           "Ho una fattura da saldare entro il 15 marzo. "
                           "Il mio codice è RSSMRA85M01H501Z. "
                           "Potete contattarmi a mario.rossi@example.it.",
        )

        candidates = [
            {
                "candidateid": "C001",
                "source": "subject",
                "term": "contratto",
                "lemma": "contratto",
                "count": 2,
                "embeddingscore": 0.88,
                "score": 0.70,
            },
            {
                "candidateid": "C002",
                "source": "body",
                "term": "fattura",
                "lemma": "fattura",
                "count": 1,
                "embeddingscore": 0.65,
                "score": 0.55,
            },
        ]

        llm_output = json.dumps({
            "dictionaryversion": 42,
            "sentiment": {"value": "neutral", "confidence": 0.7},
            "priority": {"value": "medium", "confidence": 0.6, "signals": ["scadenza"]},
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.9,
                    "keywordsintext": [{"candidateid": "C001"}],
                    "evidence": [
                        {
                            "quote": "confermare i dati del contratto",
                            "span": [22, 53],
                        },
                    ],
                },
                {
                    "labelid": "FATTURAZIONE",
                    "confidence": 0.7,
                    "keywordsintext": [{"candidateid": "C002"}],
                    "evidence": [
                        {
                            "quote": "fattura da saldare",
                            "span": [62, 80],
                        },
                    ],
                },
            ],
        }, ensure_ascii=False)

        version = PipelineVersion(dictionaryversion=42, modelversion="gpt-4o-test")

        return doc, candidates, llm_output, version

    def test_full_pipeline_produces_valid_output(self, full_pipeline_inputs):
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(
            llm_output_raw=llm_output,
            candidates=candidates,
            document=doc,
            pipeline_version=version,
            nlp_model=None,  # Skip spaCy for integration test
        )

        # Structure checks
        assert "message_id" in result
        assert "pipeline_version" in result
        assert "triage" in result
        assert "entities" in result
        assert "observations" in result
        assert "diagnostics" in result
        assert "processing_metadata" in result

        assert result["message_id"] == "int-test-001@example.it"

    def test_triage_has_required_fields(self, full_pipeline_inputs):
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)
        triage = result["triage"]

        assert "topics" in triage
        assert "sentiment" in triage
        assert "priority" in triage
        assert "customerstatus" in triage

        # Check topic structure (★FIX #2★ naming)
        for topic in triage["topics"]:
            assert "labelid" in topic
            assert "confidence_llm" in topic
            assert "confidence_adjusted" in topic
            assert "keywords" in topic  # ★FIX #4★

    def test_entities_extracted(self, full_pipeline_inputs):
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)

        # Should find at least email and codice fiscale via regex
        entities = result["entities"]
        assert len(entities) >= 1

        labels = [e["label"] for e in entities]
        # At least one of these should be found
        assert any(l in labels for l in ["EMAIL", "CODICEFISCALE"])

    def test_observations_created(self, full_pipeline_inputs):
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)

        observations = result["observations"]
        assert len(observations) >= 1

        for obs in observations:
            assert "obs_id" in obs
            assert "message_id" in obs
            assert "labelid" in obs
            assert "candidateid" in obs

    def test_diagnostics_populated(self, full_pipeline_inputs):
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)

        diag = result["diagnostics"]
        assert "warnings" in diag
        assert "errors" in diag
        assert "validation_retries" in diag
        assert "fallback_applied" in diag
        assert isinstance(diag["warnings"], list)
        assert isinstance(diag["errors"], list)

    def test_processing_metadata(self, full_pipeline_inputs):
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)

        meta = result["processing_metadata"]
        assert "postprocessing_duration_ms" in meta
        assert meta["postprocessing_duration_ms"] >= 0
        assert "span_exact_match_count" in meta
        assert "span_fuzzy_match_count" in meta
        assert "span_not_found_count" in meta
        total = meta["span_exact_match_count"] + meta["span_fuzzy_match_count"] + meta["span_not_found_count"]
        # fixture has 2 evidence items across 2 topics
        assert total == 2

    def test_no_stale_span_mismatch_warnings_after_enrichment(self, full_pipeline_inputs):
        """LLM span mismatches must not appear in diagnostics after server-side correction."""
        doc, candidates, llm_output, version = full_pipeline_inputs

        result = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)

        # None of the final warnings should be a stale "Span mismatch: span=[...]" entry
        for w in result["diagnostics"]["warnings"]:
            assert not w.startswith("Span mismatch: span=["), (
                f"Stale LLM span warning leaked into diagnostics: {w}"
            )

        # Evidence items that were corrected: span_status must be exact_match or fuzzy_match
        for topic in result["triage"]["topics"]:
            for ev in topic.get("evidence", []):
                assert ev["span_status"] in ("exact_match", "fuzzy_match", "not_found")
                assert "text_hash" in ev
                assert ev["text_hash"] is not None


class TestDeterminism:
    """Tests that the pipeline is deterministic (same input → same output)."""

    def test_same_input_same_output(self):
        doc = EmailDocument(
            message_id="det-test-001@example.it",
            from_raw="Test <test@example.it>",
            subject="Test contratto",
            body="Contratto da verificare. Fattura in allegato. Scrivere a test@example.it.",
            body_canonical="Contratto da verificare. Fattura in allegato. Scrivere a test@example.it.",
        )

        candidates = [
            {
                "candidateid": "DET001",
                "source": "body",
                "term": "contratto",
                "lemma": "contratto",
                "count": 1,
                "embeddingscore": 0.7,
                "score": 0.5,
            },
        ]

        llm_output = json.dumps({
            "dictionaryversion": 1,
            "sentiment": {"value": "neutral", "confidence": 0.6},
            "priority": {"value": "low", "confidence": 0.5, "signals": []},
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.8,
                    "keywordsintext": [{"candidateid": "DET001"}],
                    "evidence": [{"quote": "Contratto da verificare"}],
                },
            ],
        })

        version = PipelineVersion(dictionaryversion=1, modelversion="test")

        # Run the pipeline twice
        result1 = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)
        result2 = postprocess_and_enrich(llm_output, candidates, doc, version, nlp_model=None)

        # Remove non-deterministic fields
        for r in [result1, result2]:
            r["processing_metadata"].pop("postprocessing_duration_ms", None)
            for obs in r["observations"]:
                obs.pop("obs_id", None)
                obs.pop("observed_at", None)

        assert result1 == result2


class TestPipelineValidationFailure:
    """Tests for pipeline behavior when LLM output is invalid."""

    def test_invalid_json_raises_value_error(self):
        doc = EmailDocument(
            message_id="err-001",
            from_raw="Test <t@t.com>",
            subject="Test",
            body="Test body",
            body_canonical="Test body",
        )

        with pytest.raises(ValueError, match="LLM output validation failed"):
            postprocess_and_enrich(
                llm_output_raw="INVALID JSON {{{",
                candidates=[],
                document=doc,
                pipeline_version=PipelineVersion(dictionaryversion=1, modelversion="test"),
                nlp_model=None,
            )
