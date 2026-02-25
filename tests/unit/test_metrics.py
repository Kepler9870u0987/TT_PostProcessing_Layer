"""
Unit tests for src.postprocessing.metrics.

Verifies that all helpers work both when prometheus_client is installed
(real counters) and when it is absent (no-op stubs), so the module is
safe to import in any environment.
"""
from __future__ import annotations


class TestMetricsAvailability:
    def test_module_importable(self):
        import src.postprocessing.metrics as m
        assert hasattr(m, "METRICS_AVAILABLE")
        # METRICS_AVAILABLE is a bool regardless of whether prometheus is installed
        assert isinstance(m.METRICS_AVAILABLE, bool)

    def test_all_public_helpers_present(self):
        from src.postprocessing import metrics as m
        for name in (
            "record_span_status",
            "record_validation_error",
            "record_barrier_block",
            "update_redis_key_count",
            "timed_layer",
            "VALIDATION_ERRORS",
            "SPAN_STATUS",
            "LAYER_LATENCY",
            "BARRIER_BLOCKS",
            "REDIS_KEYS",
        ):
            assert hasattr(m, name), f"Missing public symbol: {name}"


class TestMetricHelpers:
    """Every helper must be callable without raising regardless of install state."""

    def test_record_span_status_all_values(self):
        from src.postprocessing.metrics import record_span_status
        for status in ("exact_match", "fuzzy_match", "not_found"):
            record_span_status(status)  # must not raise

    def test_record_validation_error(self):
        from src.postprocessing.metrics import record_validation_error
        record_validation_error("llm_classification", "schema_mismatch")
        record_validation_error("postprocessing", "generic")

    def test_record_barrier_block(self):
        from src.postprocessing.metrics import record_barrier_block
        record_barrier_block("candidate_generation")

    def test_update_redis_key_count(self):
        from src.postprocessing.metrics import update_redis_key_count
        update_redis_key_count("postprocessing", 42)

    def test_timed_layer_context_manager(self):
        from src.postprocessing.metrics import timed_layer
        with timed_layer("postprocessing"):
            x = 1 + 1  # noqa: F841  — just exercises the context manager

    def test_timed_layer_does_not_suppress_exceptions(self):
        import pytest
        from src.postprocessing.metrics import timed_layer
        with pytest.raises(ValueError, match="test error"):
            with timed_layer("test_layer"):
                raise ValueError("test error")
