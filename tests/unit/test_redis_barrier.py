"""
Unit tests for src.postprocessing.redis_barrier.

Covers:
- process_layer_with_barrier() happy path
- Validation failure blocks propagation (write barrier semantics)
- Convenience getters: get_raw_payload / get_normalized_payload
- NullRedisClient drop-in
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _InMemoryRedis:
    """Minimal in-memory Redis stub (no server required)."""

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


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

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
        assert "processed" in raw_data

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

    def test_message_id_angle_brackets_sanitised(self, redis_stub):
        """RFC5322 message-ids (<id@host>) must not break Redis key names."""
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
        for key in matching:
            assert "<" not in key and ">" not in key


# ---------------------------------------------------------------------------
# Validation failure — write barrier semantics
# ---------------------------------------------------------------------------

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

    def test_raw_always_persisted_on_failure(self, redis_stub):
        """Raw key must be saved even when validation rejects the output."""
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
        """Normalized key must NOT be written after a validation failure."""
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
        """Error details must be persisted under the :error key."""
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
        err_raw = redis_stub.get("run:run-fail-004:msg:test@example.it:layer:llm_classification:error")
        assert err_raw is not None
        err_payload = json.loads(err_raw)
        assert err_payload["layer"] == "llm_classification"
        assert "test: mandatory field missing" in err_payload["errors"]


# ---------------------------------------------------------------------------
# Convenience getters
# ---------------------------------------------------------------------------

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

    def test_get_missing_key_returns_none(self, redis_stub):
        result = get_raw_payload(redis_stub, "nonexistent", "x@y.com", "layer_x")
        assert result is None


# ---------------------------------------------------------------------------
# NullRedisClient
# ---------------------------------------------------------------------------

class TestNullRedisClient:
    def test_set_does_not_raise(self):
        NullRedisClient().set("key", "value", ex=60)

    def test_get_always_returns_none(self):
        client = NullRedisClient()
        client.set("key", "value")
        assert client.get("key") is None

    def test_exists_always_returns_zero(self):
        assert NullRedisClient().exists("a", "b") == 0

    def test_barrier_completes_with_null_client(self):
        """Full barrier run must succeed with NullRedisClient (no server)."""
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
