"""
Unit tests for:
- src.postprocessing.redis_barrier  (write barrier pattern)
- src.models.triage_io              (KeywordInText, EnrichedEvidence Pydantic models)
- src.postprocessing.metrics        (Prometheus metrics — no-op and real paths)
- LLM_RESPONSE_SCHEMA               (natively accepts lemma/count/term/… fields)
"""
from __future__ import annotations

import json

import pytest

from src.postprocessing.redis_barrier import (
    NullRedisClient,
    ValidationOutcome,
    WriteBarrierValidationError,
    get_normalized_payload,
    get_raw_payload,
    process_layer_with_barrier,
)


# =============================================================================
# Fixtures
# =============================================================================

class _InMemoryRedis:
    """Minimal in-memory Redis stub for barrier tests."""

    def __init__(self):
        self._store: dict = {}

    def set(self, key: str, value: str, **kwargs) -> None:  # noqa: ARG002
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self._store)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                deleted += 1
        return deleted

    def keys_matching(self, prefix: str) -> list[str]:
        return [k for k in self._store if k.startswith(prefix)]


@pytest.fixture
def redis_stub():
    return _InMemoryRedis()


def _passing_validator(output: dict) -> ValidationOutcome:
    return ValidationOutcome(valid=True, data=output)


def _failing_validator(output: dict) -> ValidationOutcome:  # noqa: ARG001
    return ValidationOutcome(valid=False, errors=["test: mandatory field missing"])


def _identity_layer(input_data: dict) -> dict:
    return {"processed": True, **input_data}


# =============================================================================
# WriteBarrier — happy path
# =============================================================================

class TestWriteBarrierHappyPath:
    def test_returns_normalized_output(self, redis_stub):
        result = process_layer_with_barrier(
            input_data={"msg": "hello"},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=redis_stub,
            run_id="run-001",
            message_id="test@example.it",
            layer_name="test_layer",
        )
        assert result["processed"] is True

    def test_raw_key_persisted(self, redis_stub):
        process_layer_with_barrier(
            input_data={"x": 1},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=redis_stub,
            run_id="run-002",
            message_id="test@example.it",
            layer_name="candidate_generation",
        )
        raw_data = redis_stub.get("run:run-002:msg:test@example.it:layer:candidate_generation:raw")
        assert raw_data is not None
        assert "processed" in raw_data  # JSON string

    def test_normalized_key_persisted(self, redis_stub):
        process_layer_with_barrier(
            input_data={"x": 1},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=redis_stub,
            run_id="run-003",
            message_id="test@example.it",
            layer_name="llm_classification",
        )
        norm_data = redis_stub.get("run:run-003:msg:test@example.it:layer:llm_classification:normalized")
        assert norm_data is not None

    def test_normalizer_fn_applied(self, redis_stub):
        def enrich(output: dict, outcome: ValidationOutcome) -> dict:  # noqa: ARG001
            return {**output, "enriched": True}

        result = process_layer_with_barrier(
            input_data={"x": 1},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            normalizer_fn=enrich,
            redis_client=redis_stub,
            run_id="run-004",
            message_id="test@example.it",
            layer_name="postprocessing",
        )
        assert result.get("enriched") is True

    def test_message_id_with_special_chars_sanitised(self, redis_stub):
        """Angle-bracket IDs shouldn't break Redis key names."""
        process_layer_with_barrier(
            input_data={},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=redis_stub,
            run_id="run-005",
            message_id="<abcd1234@example.it>",
            layer_name="test_layer",
        )
        matching = redis_stub.keys_matching("run:run-005:")
        assert len(matching) == 2  # raw + normalized
        # Keys must not contain literal angle brackets (space/slash replacement)
        for key in matching:
            assert "<" not in key and ">" not in key


# =============================================================================
# WriteBarrier — validation failure blocks propagation
# =============================================================================

class TestWriteBarrierValidationFailure:
    def test_raises_write_barrier_error(self, redis_stub):
        with pytest.raises(WriteBarrierValidationError) as exc_info:
            process_layer_with_barrier(
                input_data={"x": 1},
                layer_fn=_identity_layer,
                validator_fn=_failing_validator,
                redis_client=redis_stub,
                run_id="run-fail-001",
                message_id="test@example.it",
                layer_name="llm_classification",
            )
        assert exc_info.value.layer_name == "llm_classification"
        assert "test: mandatory field missing" in exc_info.value.errors

    def test_raw_persisted_on_failure(self, redis_stub):
        """Raw output must always be saved, even when validation fails."""
        with pytest.raises(WriteBarrierValidationError):
            process_layer_with_barrier(
                input_data={"x": 1},
                layer_fn=_identity_layer,
                validator_fn=_failing_validator,
                redis_client=redis_stub,
                run_id="run-fail-002",
                message_id="test@example.it",
                layer_name="llm_classification",
            )
        raw = redis_stub.get("run:run-fail-002:msg:test@example.it:layer:llm_classification:raw")
        assert raw is not None

    def test_normalized_not_persisted_on_failure(self, redis_stub):
        """Normalized key must NOT exist when validation fails."""
        with pytest.raises(WriteBarrierValidationError):
            process_layer_with_barrier(
                input_data={"x": 1},
                layer_fn=_identity_layer,
                validator_fn=_failing_validator,
                redis_client=redis_stub,
                run_id="run-fail-003",
                message_id="test@example.it",
                layer_name="llm_classification",
            )
        norm = redis_stub.get("run:run-fail-003:msg:test@example.it:layer:llm_classification:normalized")
        assert norm is None

    def test_error_record_persisted(self, redis_stub):
        """An error record key should be written when validation fails."""
        with pytest.raises(WriteBarrierValidationError):
            process_layer_with_barrier(
                input_data={"x": 1},
                layer_fn=_identity_layer,
                validator_fn=_failing_validator,
                redis_client=redis_stub,
                run_id="run-fail-004",
                message_id="test@example.it",
                layer_name="llm_classification",
            )
        error_key = redis_stub.get("run:run-fail-004:msg:test@example.it:layer:llm_classification:error")
        assert error_key is not None
        err_payload = json.loads(error_key)
        assert err_payload["layer"] == "llm_classification"
        assert "test: mandatory field missing" in err_payload["errors"]


# =============================================================================
# WriteBarrier — convenience getters
# =============================================================================

class TestWriteBarrierGetters:
    def test_get_raw_payload(self, redis_stub):
        process_layer_with_barrier(
            input_data={"z": 99},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=redis_stub,
            run_id="run-get-001",
            message_id="m@example.it",
            layer_name="candidate_generation",
        )
        raw = get_raw_payload(redis_stub, "run-get-001", "m@example.it", "candidate_generation")
        assert raw is not None
        assert raw["z"] == 99

    def test_get_normalized_payload(self, redis_stub):
        process_layer_with_barrier(
            input_data={"z": 99},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=redis_stub,
            run_id="run-get-002",
            message_id="m@example.it",
            layer_name="postprocessing",
        )
        norm = get_normalized_payload(redis_stub, "run-get-002", "m@example.it", "postprocessing")
        assert norm is not None

    def test_get_missing_returns_none(self, redis_stub):
        result = get_raw_payload(redis_stub, "nonexistent", "x@y.com", "layer_x")
        assert result is None


# =============================================================================
# NullRedisClient — drop-in no-op for unit tests
# =============================================================================

class TestNullRedisClient:
    def test_set_does_not_raise(self):
        client = NullRedisClient()
        client.set("key", "value", ex=60)

    def test_get_returns_none(self):
        client = NullRedisClient()
        client.set("key", "value")
        assert client.get("key") is None

    def test_exists_returns_zero(self):
        client = NullRedisClient()
        assert client.exists("a", "b") == 0

    def test_barrier_works_with_null_client(self):
        """Process should complete without errors using NullRedisClient."""
        result = process_layer_with_barrier(
            input_data={"ok": True},
            layer_fn=_identity_layer,
            validator_fn=_passing_validator,
            redis_client=NullRedisClient(),
            run_id="run-null",
            message_id="test@example.it",
            layer_name="test",
        )
        assert result["ok"] is True


# =============================================================================
# KeywordInText model — Pydantic typed model
# =============================================================================

class TestKeywordInTextModel:
    def test_minimal_valid(self):
        from src.models.triage_io import KeywordInText
        kw = KeywordInText(candidateid="ABC123")
        assert kw.candidateid == "ABC123"
        assert kw.lemma is None
        assert kw.count is None

    def test_all_echo_fields_accepted(self):
        from src.models.triage_io import KeywordInText
        kw = KeywordInText(
            candidateid="ABC123",
            lemma="contratto",
            term="contratto",
            count=3,
            source="body",
            embeddingscore=0.85,
        )
        assert kw.lemma == "contratto"
        assert kw.count == 3
        assert kw.embeddingscore == 0.85

    def test_count_must_be_positive(self):
        from pydantic import ValidationError
        from src.models.triage_io import KeywordInText
        with pytest.raises(ValidationError):
            KeywordInText(candidateid="ABC123", count=0)

    def test_embeddingscore_clamped(self):
        from pydantic import ValidationError
        from src.models.triage_io import KeywordInText
        with pytest.raises(ValidationError):
            KeywordInText(candidateid="ABC123", embeddingscore=1.5)


# =============================================================================
# EvidenceItem model
# =============================================================================

class TestEvidenceItemModel:
    def test_valid_without_span(self):
        from src.models.triage_io import EvidenceItem
        ev = EvidenceItem(quote="test quote")
        assert ev.span is None

    def test_valid_with_span(self):
        from src.models.triage_io import EvidenceItem
        ev = EvidenceItem(quote="test quote", span=[10, 25])
        assert ev.span == [10, 25]

    def test_span_wrong_length_rejected(self):
        from pydantic import ValidationError
        from src.models.triage_io import EvidenceItem
        with pytest.raises(ValidationError):
            EvidenceItem(quote="test", span=[10])

    def test_span_start_gte_end_rejected(self):
        from pydantic import ValidationError
        from src.models.triage_io import EvidenceItem
        with pytest.raises(ValidationError):
            EvidenceItem(quote="test", span=[50, 30])


# =============================================================================
# EnrichedEvidence model
# =============================================================================

class TestEnrichedEvidenceModel:
    def test_valid_exact_match(self):
        from src.models.triage_io import EnrichedEvidence
        ev = EnrichedEvidence(
            quote="some quote from email",
            span=(13, 34),
            span_llm=(42, 64),
            span_status="exact_match",
            text_hash="b65ab80abc1234",
        )
        assert ev.span_status == "exact_match"
        assert ev.span_llm == (42, 64)

    def test_not_found_with_null_span(self):
        from src.models.triage_io import EnrichedEvidence
        ev = EnrichedEvidence(
            quote="missing quote",
            span=None,
            span_llm=None,
            span_status="not_found",
            text_hash="abc",
        )
        assert ev.span is None

    def test_invalid_status_rejected(self):
        from pydantic import ValidationError
        from src.models.triage_io import EnrichedEvidence
        with pytest.raises(ValidationError):
            EnrichedEvidence(
                quote="q",
                span=None,
                span_llm=None,
                span_status="unknown_status",
                text_hash="abc",
            )


# =============================================================================
# LLM_RESPONSE_SCHEMA — natively accepts echo fields (G2 fix)
# =============================================================================

class TestLLMResponseSchemaEchoFields:
    """
    Verify the updated LLM_RESPONSE_SCHEMA accepts lemma/count/term/
    source/embeddingscore without raising, so pre-validation stripping
    is no longer needed.
    """

    def _base_payload(self, extra_kw_fields: dict) -> dict:
        return {
            "dictionaryversion": 42,
            "sentiment": {"value": "neutral", "confidence": 0.5},
            "priority": {"value": "low", "confidence": 0.5, "signals": []},
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "confidence": 0.8,
                    "keywordsintext": [{"candidateid": "ABC123", **extra_kw_fields}],
                    "evidence": [{"quote": "test quote"}],
                }
            ],
        }

    def test_candidateid_only_passes(self):
        from jsonschema import validate
        from src.config.schemas import LLM_RESPONSE_SCHEMA
        payload = self._base_payload({})
        validate(instance=payload, schema=LLM_RESPONSE_SCHEMA["schema"])  # must not raise

    def test_lemma_and_count_accepted(self):
        from jsonschema import validate
        from src.config.schemas import LLM_RESPONSE_SCHEMA
        payload = self._base_payload({"lemma": "contratto", "count": 2})
        validate(instance=payload, schema=LLM_RESPONSE_SCHEMA["schema"])  # must not raise

    def test_all_echo_fields_accepted(self):
        from jsonschema import validate
        from src.config.schemas import LLM_RESPONSE_SCHEMA
        payload = self._base_payload({
            "lemma": "contratto",
            "term": "contratto",
            "count": 2,
            "source": "body",
            "embeddingscore": 0.85,
        })
        validate(instance=payload, schema=LLM_RESPONSE_SCHEMA["schema"])  # must not raise

    def test_truly_unknown_field_rejected(self):
        """A field NOT in the allowed set must still be rejected."""
        from jsonschema import ValidationError as JSchemaError
        from jsonschema import validate
        from src.config.schemas import LLM_RESPONSE_SCHEMA
        payload = self._base_payload({"invented_field": "should_fail"})
        with pytest.raises(JSchemaError):
            validate(instance=payload, schema=LLM_RESPONSE_SCHEMA["schema"])


# =============================================================================
# Prometheus metrics — availability and no-op behaviour
# =============================================================================

class TestPrometheusMetrics:
    def test_metrics_module_importable(self):
        import src.postprocessing.metrics as m
        assert hasattr(m, "METRICS_AVAILABLE")

    def test_record_span_status_does_not_raise(self):
        from src.postprocessing.metrics import record_span_status
        record_span_status("exact_match")
        record_span_status("fuzzy_match")
        record_span_status("not_found")

    def test_record_validation_error_does_not_raise(self):
        from src.postprocessing.metrics import record_validation_error
        record_validation_error("test_layer", "schema_mismatch")

    def test_record_barrier_block_does_not_raise(self):
        from src.postprocessing.metrics import record_barrier_block
        record_barrier_block("test_layer")

    def test_timed_layer_context_manager_does_not_raise(self):
        from src.postprocessing.metrics import timed_layer
        with timed_layer("test_layer"):
            pass  # no exception
