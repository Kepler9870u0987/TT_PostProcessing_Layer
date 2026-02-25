"""
Prometheus Metrics — pipeline observability.

Exposes counters, histograms, and gauges for:
- Validation errors per layer
- Span matching status distribution
- Layer processing latency
- Redis key counts (optional, polled externally)

All metrics use lazy initialisation guarded by a try/except so the module
remains importable even when prometheus_client is not installed (e.g. in
pure unit-test environments without the extra dependency).

Usage
-----
    from src.postprocessing.metrics import (
        record_validation_error,
        record_span_status,
        layer_processing_time,
        METRICS_AVAILABLE,
    )

    with layer_processing_time.labels(layer_name="postprocessing").time():
        result = postprocess_and_enrich(...)

    record_span_status("exact_match")
    record_validation_error("llm_classification", "schema_mismatch")

References: Pipeline-Problemi-Soluzioni-Contratti.md §8
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import prometheus_client — fail gracefully if missing
# ---------------------------------------------------------------------------
try:
    from prometheus_client import Counter, Histogram, Gauge
    METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover
    METRICS_AVAILABLE = False
    logger.warning(
        "prometheus_client not installed — metrics will be no-ops. "
        "Install with: pip install prometheus-client"
    )


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

if METRICS_AVAILABLE:
    # Total validation errors, labelled by layer and error type.
    VALIDATION_ERRORS: Counter = Counter(
        "pipeline_validation_errors_total",
        "Total validation errors by layer and error type",
        ["layer_name", "error_type"],
    )

    # Distribution of server-side span matching status.
    SPAN_STATUS: Counter = Counter(
        "pipeline_span_status_total",
        "Distribution of span matching status (exact_match / fuzzy_match / not_found)",
        ["status"],
    )

    # Processing latency per layer (seconds).
    LAYER_LATENCY: Histogram = Histogram(
        "pipeline_layer_processing_seconds",
        "Processing time per pipeline layer in seconds",
        ["layer_name"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    )

    # How many times the Redis write barrier blocked propagation.
    BARRIER_BLOCKS: Counter = Counter(
        "pipeline_write_barrier_blocks_total",
        "Times the write barrier blocked propagation due to validation failure",
        ["layer_name"],
    )

    # Gauge: number of active Redis pipeline keys (updated externally).
    REDIS_KEYS: Gauge = Gauge(
        "pipeline_redis_keys_total",
        "Total pipeline keys currently stored in Redis",
        ["layer_name"],
    )
else:
    # Stub objects so callers don't need to guard every usage.
    class _NoOpMetric:
        def labels(self, **_kwargs):  # noqa: ANN001
            return self

        def inc(self, _amount: float = 1) -> None:
            pass

        def observe(self, _value: float) -> None:
            pass

        def set(self, _value: float) -> None:
            pass

        def time(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            pass

    VALIDATION_ERRORS = _NoOpMetric()  # type: ignore[assignment]
    SPAN_STATUS = _NoOpMetric()        # type: ignore[assignment]
    LAYER_LATENCY = _NoOpMetric()      # type: ignore[assignment]
    BARRIER_BLOCKS = _NoOpMetric()     # type: ignore[assignment]
    REDIS_KEYS = _NoOpMetric()         # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def record_validation_error(layer_name: str, error_type: str = "generic") -> None:
    """Increment the validation error counter for *layer_name*."""
    VALIDATION_ERRORS.labels(layer_name=layer_name, error_type=error_type).inc()


def record_span_status(status: str) -> None:
    """Increment the span status counter for *status*."""
    SPAN_STATUS.labels(status=status).inc()


def record_barrier_block(layer_name: str) -> None:
    """Increment the write-barrier block counter for *layer_name*."""
    BARRIER_BLOCKS.labels(layer_name=layer_name).inc()


def update_redis_key_count(layer_name: str, count: int) -> None:
    """Set the Redis key count gauge for *layer_name*."""
    REDIS_KEYS.labels(layer_name=layer_name).set(count)


@contextmanager
def timed_layer(layer_name: str) -> Generator[None, None, None]:
    """
    Context manager that records layer processing latency.

    Usage::

        with timed_layer("postprocessing"):
            result = postprocess_and_enrich(...)
    """
    with LAYER_LATENCY.labels(layer_name=layer_name).time():
        yield
