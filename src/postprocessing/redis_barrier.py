"""
Redis Write Barrier — dual-payload persistence with validation gating.

Pattern: every pipeline layer persists both a RAW payload (LLM/tool output,
unmodified) and a NORMALIZED payload (validated + enriched).  A layer's
normalized output is only written — and only propagated to the next layer —
after validation passes.  This prevents silent error propagation and produces
a complete, versioned audit trail.

Key scheme
----------
  run:{run_id}:msg:{message_id}:layer:{layer_name}:raw         – raw output
  run:{run_id}:msg:{message_id}:layer:{layer_name}:normalized  – validated+enriched

References: Pipeline-Problemi-Soluzioni-Contratti.md §5
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default TTL for pipeline run keys (24 h).
DEFAULT_TTL_SECONDS: int = 86_400


# ---------------------------------------------------------------------------
# Lightweight result type for layer validators
# ---------------------------------------------------------------------------

@dataclass
class ValidationOutcome:
    """Result returned by a layer validator function."""

    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data: Optional[dict] = None  # Normalized output (populated on success)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class WriteBarrierValidationError(Exception):
    """Raised when a layer validator rejects the output."""

    def __init__(self, layer_name: str, errors: List[str]) -> None:
        self.layer_name = layer_name
        self.errors = errors
        super().__init__(f"Validation failed at layer '{layer_name}': {errors}")


# ---------------------------------------------------------------------------
# Core write barrier
# ---------------------------------------------------------------------------

def process_layer_with_barrier(
    *,
    input_data: Any,
    layer_fn: Callable[[Any], dict],
    validator_fn: Callable[[dict], ValidationOutcome],
    normalizer_fn: Optional[Callable[[dict, ValidationOutcome], dict]] = None,
    redis_client: Any,
    run_id: str,
    message_id: str,
    layer_name: str,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> dict:
    """
    Execute a pipeline layer with a Redis write barrier.

    Flow
    ----
    1. Call *layer_fn(input_data)* → raw_output.
    2. Persist raw_output to Redis (``…:raw`` key) for audit.
    3. Call *validator_fn(raw_output)* → ValidationOutcome.
       * On failure: persist error record, raise WriteBarrierValidationError.
    4. Optionally call *normalizer_fn(raw_output, outcome)* to enrich/clean.
    5. Persist normalized output to Redis (``…:normalized`` key).
    6. Return normalized output **only**.

    Args:
        input_data:    Input passed verbatim to layer_fn.
        layer_fn:      The layer callable; must return a JSON-serialisable dict.
        validator_fn:  Validates layer output; returns ValidationOutcome.
        normalizer_fn: Optional enrichment step applied after validation.
                       Defaults to an identity function.
        redis_client:  A redis.Redis (or compatible) instance.
        run_id:        Unique run identifier (e.g. timestamp or UUID).
        message_id:    Email message-id for key namespacing.
        layer_name:    Human-readable layer name for key namespacing.
        ttl:           Key expiry in seconds (default 24 h).

    Returns:
        The normalized (validated + enriched) output dict.

    Raises:
        WriteBarrierValidationError: If validation fails.
    """
    safe_mid = _safe_mid(message_id)
    key_prefix = f"run:{run_id}:msg:{safe_mid}:layer:{layer_name}"
    key_raw = f"{key_prefix}:raw"
    key_normalized = f"{key_prefix}:normalized"
    key_error = f"{key_prefix}:error"

    # ------------------------------------------------------------------
    # 1. Execute layer
    # ------------------------------------------------------------------
    logger.debug("WriteBarrier[%s] executing layer_fn …", layer_name)
    raw_output: dict = layer_fn(input_data)

    # ------------------------------------------------------------------
    # 2. Persist raw (always, even on failure — needed for debugging)
    # ------------------------------------------------------------------
    try:
        redis_client.set(key_raw, json.dumps(raw_output, default=str), ex=ttl)
        logger.debug("WriteBarrier[%s] raw payload persisted → %s", layer_name, key_raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WriteBarrier[%s] failed to persist raw: %s", layer_name, exc)

    # ------------------------------------------------------------------
    # 3. Validate
    # ------------------------------------------------------------------
    outcome = validator_fn(raw_output)

    if not outcome.valid:
        error_payload = {
            "layer": layer_name,
            "message_id": message_id,
            "run_id": run_id,
            "errors": outcome.errors,
            "warnings": outcome.warnings,
        }
        try:
            redis_client.set(key_error, json.dumps(error_payload, default=str), ex=ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("WriteBarrier[%s] failed to persist error record: %s", layer_name, exc)

        try:
            from src.postprocessing.metrics import record_barrier_block, record_validation_error
            record_barrier_block(layer_name)
            for err in outcome.errors:
                _etype = "schema_mismatch" if "schema" in err.lower() else "generic"
                record_validation_error(layer_name, _etype)
        except Exception:  # noqa: BLE001
            pass
        logger.error(
            "WriteBarrier[%s] validation FAILED — blocking propagation. errors=%s",
            layer_name, outcome.errors,
        )
        raise WriteBarrierValidationError(layer_name, outcome.errors)

    # ------------------------------------------------------------------
    # 4. Normalize / enrich
    # ------------------------------------------------------------------
    if normalizer_fn is not None:
        normalized: dict = normalizer_fn(raw_output, outcome)
    else:
        normalized = raw_output

    # ------------------------------------------------------------------
    # 5. Persist normalized (only on success)
    # ------------------------------------------------------------------
    try:
        redis_client.set(key_normalized, json.dumps(normalized, default=str), ex=ttl)
        logger.debug("WriteBarrier[%s] normalized payload persisted → %s", layer_name, key_normalized)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WriteBarrier[%s] failed to persist normalized: %s", layer_name, exc)

    logger.info(
        "WriteBarrier[%s] completed OK (warnings=%d)", layer_name, len(outcome.warnings)
    )
    return normalized


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def _safe_mid(message_id: str) -> str:
    """Strip/replace characters that are unsafe in Redis key names."""
    return (
        message_id
        .replace("<", "")
        .replace(">", "")
        .replace(" ", "_")
        .replace("/", "_")
    )


def get_raw_payload(
    redis_client: Any,
    run_id: str,
    message_id: str,
    layer_name: str,
) -> Optional[dict]:
    """Retrieve the raw payload for a layer run, or None if not found."""
    key = f"run:{run_id}:msg:{_safe_mid(message_id)}:layer:{layer_name}:raw"
    data = redis_client.get(key)
    return json.loads(data) if data else None


def get_normalized_payload(
    redis_client: Any,
    run_id: str,
    message_id: str,
    layer_name: str,
) -> Optional[dict]:
    """Retrieve the normalized payload for a layer run, or None if not found."""
    key = f"run:{run_id}:msg:{_safe_mid(message_id)}:layer:{layer_name}:normalized"
    data = redis_client.get(key)
    return json.loads(data) if data else None


def build_redis_client(url: Optional[str] = None) -> Any:
    """
    Build and return a redis.Redis client.

    Falls back to REDIS_URL from settings if *url* is not provided.
    Raises ImportError if the `redis` package is not installed.
    """
    try:
        import redis as _redis
    except ImportError as exc:
        raise ImportError(
            "The 'redis' package is required for the write barrier. "
            "Install it with: pip install redis"
        ) from exc

    from src.config.settings import REDIS_URL

    target_url = url or REDIS_URL
    client = _redis.Redis.from_url(target_url, decode_responses=True)
    logger.debug("Redis client created for URL: %s", target_url)
    return client


# ---------------------------------------------------------------------------
# Null / no-op client (for testing without a live Redis instance)
# ---------------------------------------------------------------------------

class NullRedisClient:
    """
    Drop-in replacement that discards all writes and returns None on reads.
    Useful in unit tests and local development without a Redis server.
    """

    def set(self, key: str, value: str, **kwargs: Any) -> None:  # noqa: ARG002
        pass

    def get(self, key: str) -> None:  # noqa: ARG002
        return None

    def exists(self, *keys: str) -> int:
        return 0

    def delete(self, *keys: str) -> int:
        return 0
