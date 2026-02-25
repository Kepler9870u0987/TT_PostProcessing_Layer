"""
Validation & Normalization — multi-stage LLM output validation.

Implements:
- JSON parse
- Schema conformance (jsonschema strict)
- Business rules (candidateid exists, labelid in TOPICS_ENUM)
- Evidence verification ★FIX #7★
- Quality checks (confidence, evidence, keywords)
- Deduplication

References: post-processing-enrichment-layer.md §3.1, §4
"""
import hashlib
import json
import logging
from typing import List

import numpy as np
from jsonschema import ValidationError, validate

from src.config.constants import LABELID_ALIASES, MIN_CONFIDENCE_WARNING, TOPICS_ENUM
from src.config.schemas import LLM_RESPONSE_SCHEMA
from src.models.validation import ValidationResult

logger = logging.getLogger(__name__)


# ======================================================================
# Internal helpers
# ======================================================================

def _normalize_labelid_aliases(data: dict, warnings: List[str]) -> dict:
    """
    Remap LLM-generated labelid variants to canonical TOPICS_ENUM values,
    and strip extra fields from keywordsintext items (schema v3.3 allows
    only `candidateid`).

    Operates on shallow copies so the original dict is not mutated.
    Appends a warning for every alias/strip that is resolved.
    """
    normalized_topics = []
    for topic in data.get("topics", []):
        topic = dict(topic)

        # --- Alias normalization ---
        labelid = topic.get("labelid", "")
        canonical = LABELID_ALIASES.get(labelid)
        if canonical and canonical != labelid:
            warnings.append(
                f"labelid alias resolved: '{labelid}' → '{canonical}'"
            )
            topic["labelid"] = canonical

        # --- Strip extra fields from keywordsintext (schema: only candidateid) ---
        # The LLM naturally mirrors candidate fields (lemma, count, term, source,
        # embeddingscore) from the prompt — this is expected behaviour, not an error.
        # resolve_keywords_from_catalog() will repopulate all fields from the trusted
        # catalog, so we silently discard anything beyond candidateid here.
        # Only warn for truly unexpected fields beyond the known LLM echo set.
        KNOWN_LLM_ECHO_FIELDS = {"candidateid", "lemma", "count", "term", "source", "embeddingscore"}
        clean_kws = []
        for kw in topic.get("keywordsintext", []):
            truly_unexpected = set(kw.keys()) - KNOWN_LLM_ECHO_FIELDS
            if truly_unexpected:
                warnings.append(
                    f"keywordsintext: stripped unexpected fields {sorted(truly_unexpected)} "
                    f"from candidate '{kw.get('candidateid', '?')}'"
                )
            clean_kws.append({"candidateid": kw["candidateid"]})
        topic["keywordsintext"] = clean_kws

        normalized_topics.append(topic)

    if "topics" in data:
        data = {**data, "topics": normalized_topics}
    return data


def validate_llm_output_multistage(
    output_json: str | dict,
    candidates: List[dict],
    text_canonical: str,
    allowed_topics: List[str] | None = None,
) -> ValidationResult:
    """
    Multi-stage validation of LLM output.

    Stages:
        1. JSON Parse
        2. Schema conformance
        3. Business rules (candidateid exists, labelid in TOPICS_ENUM)
        4. Evidence verification ★FIX #7★
        5. Quality checks (confidence, keywords, evidence)
        6. Deduplication

    Args:
        output_json: Raw JSON string from LLM.
        candidates: List of candidate keyword dicts.
        text_canonical: Canonical email body text.
        allowed_topics: Allowed topic labels (defaults to TOPICS_ENUM).

    Returns:
        ValidationResult with valid flag, errors, warnings, and cleaned data.
    """
    if allowed_topics is None:
        allowed_topics = TOPICS_ENUM

    errors: List[str] = []
    warnings: List[str] = []

    # ------------------------------------------------------------------
    # Stage 1: Parse JSON
    # ------------------------------------------------------------------
    if isinstance(output_json, dict):
        data = output_json
    else:
        try:
            data = json.loads(output_json)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON: {e}")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

    # ------------------------------------------------------------------
    # Stage 1b: Alias normalization (before schema — cosmetic LLM variants)
    # ------------------------------------------------------------------
    data = _normalize_labelid_aliases(data, warnings)

    # ------------------------------------------------------------------
    # Stage 2: Schema validation
    # ------------------------------------------------------------------
    try:
        validate(instance=data, schema=LLM_RESPONSE_SCHEMA["schema"])
    except ValidationError as e:
        errors.append(f"Schema violation: {e.message}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    # ------------------------------------------------------------------
    # Stage 3: Business rules
    # ------------------------------------------------------------------
    candidate_ids = {c["candidateid"] for c in candidates}

    for topic in data.get("topics", []):
        # Check labelid in enum
        if topic["labelid"] not in allowed_topics:
            errors.append(f"Invalid labelid: {topic['labelid']}")

        # Check candidateid exists in candidate list
        for kw in topic.get("keywordsintext", []):
            cid = kw.get("candidateid")
            if cid not in candidate_ids:
                errors.append(f"Invented candidateid: {cid}")

    # ------------------------------------------------------------------
    # Stage 4: Evidence verification ★FIX #7★
    # ------------------------------------------------------------------
    evidence_warnings = verify_evidence_quotes(data.get("topics", []), text_canonical)
    warnings.extend(evidence_warnings)

    # ------------------------------------------------------------------
    # Stage 5: Quality checks
    # ------------------------------------------------------------------
    for topic in data.get("topics", []):
        conf = topic.get("confidence", 0)
        if conf < MIN_CONFIDENCE_WARNING:
            warnings.append(f"Very low confidence for {topic['labelid']}: {conf}")

        if len(topic.get("keywordsintext", [])) == 0:
            warnings.append(f"No keywords for topic {topic['labelid']}")

        if len(topic.get("evidence", [])) == 0:
            warnings.append(f"No evidence for topic {topic['labelid']}")

    # ------------------------------------------------------------------
    # Stage 6: Deduplication & normalization
    # ------------------------------------------------------------------
    data = deduplicate_and_normalize(data)

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings, data=data)


# ======================================================================
# Evidence Verification ★FIX #7★
# ======================================================================

def verify_evidence_quotes(topics: List[dict], text_canonical: str) -> List[str]:
    """
    Verify that evidence quotes actually appear in the canonical text.
    Also checks span consistency if span is provided.

    Returns:
        List of warning strings for failed verifications.
    """
    warnings: List[str] = []

    for topic in topics:
        for ev in topic.get("evidence", []):
            quote = ev.get("quote", "")
            span = ev.get("span")

            if quote:
                # Check if quote is a substring
                if quote not in text_canonical:
                    warnings.append(
                        f"Evidence quote not found in text: '{quote[:50]}...'"
                    )

                # If span provided, verify consistency
                if span and len(span) == 2:
                    start, end = span
                    if 0 <= start < end <= len(text_canonical):
                        extracted = text_canonical[start:end]
                        if extracted != quote:
                            warnings.append(
                                f"Span mismatch: span=[{start},{end}] extracts "
                                f"'{extracted[:30]}...' but quote is '{quote[:30]}...'"
                            )
                    else:
                        warnings.append(
                            f"Span out of bounds: [{start},{end}] for text length {len(text_canonical)}"
                        )

    return warnings


def compute_span_from_quote(
    quote: str,
    body_canonical: str,
) -> tuple[list[int] | None, str]:
    """
    Calculate the byte-offset span ``[start, end]`` for *quote* inside
    *body_canonical*.

    Strategy:
        1. Exact substring match — status ``"exact_match"``.
        2. Fuzzy sliding-window match via :func:`difflib.SequenceMatcher`
           with a minimum ratio of 0.85 — status ``"fuzzy_match"``.
        3. Not found — returns ``(None, "not_found")``.

    Returns:
        A ``(span, status)`` tuple where *span* is ``[start, end]`` or
        ``None`` when not found.
    """
    if not quote or not body_canonical:
        return None, "not_found"

    # --- Exact match ---
    start = body_canonical.find(quote)
    if start != -1:
        return [start, start + len(quote)], "exact_match"

    # --- Fuzzy match ---
    from difflib import SequenceMatcher

    best_ratio = 0.0
    best_span: list[int] | None = None
    q_len = len(quote)
    window_size = q_len + 20

    for i in range(max(0, len(body_canonical) - q_len + 1)):
        window = body_canonical[i : i + window_size]
        ratio = SequenceMatcher(None, quote, window, autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_span = [i, i + q_len]

    if best_ratio >= 0.85 and best_span is not None:
        return best_span, "fuzzy_match"

    return None, "not_found"


def enrich_evidence_with_spans(
    topics: List[dict],
    body_canonical: str,
) -> List[dict]:
    """
    Enrich every evidence item in *topics* with a server-computed span.

    For each evidence entry:

    * ``span``        — server-computed ``[start, end]`` (``None`` if not found)
    * ``span_llm``    — original span produced by the LLM (kept for audit)
    * ``span_status`` — one of ``"exact_match"``, ``"fuzzy_match"``, ``"not_found"``
    * ``text_hash``   — SHA-256 of *body_canonical* for verifiability

    The LLM-supplied span (if present) is moved to ``span_llm`` and
    replaced with the server-computed value.

    Returns:
        The (mutated) topics list with enriched evidence dicts.
    """
    text_hash = hashlib.sha256(body_canonical.encode()).hexdigest()

    for topic in topics:
        for ev in topic.get("evidence", []):
            quote = ev.get("quote", "")
            computed_span, status = compute_span_from_quote(quote, body_canonical)

            ev["span_llm"] = ev.get("span")  # preserve original LLM span for audit
            ev["span"] = computed_span
            ev["span_status"] = status
            ev["text_hash"] = text_hash

            if status == "not_found":
                logger.warning(
                    "Server-side span: quote not found in text: '%s...'",
                    quote[:50],
                )

    return topics


def enforce_evidence_policy(topics: List[dict], text_canonical: str, threshold: float = 0.3) -> bool:
    """
    Returns False if >threshold fraction of evidence quotes are unverifiable.
    Use to trigger LLM retry.

    Args:
        topics: List of topic dicts.
        text_canonical: Canonical email text.
        threshold: Maximum acceptable failure rate (default 0.3 = 30%).

    Returns:
        True if evidence quality is acceptable, False if retry needed.
    """
    total_evidence = sum(len(t.get("evidence", [])) for t in topics)
    if total_evidence == 0:
        return True

    warnings = verify_evidence_quotes(topics, text_canonical)
    failure_rate = len(warnings) / total_evidence

    if failure_rate > threshold:
        logger.warning(
            "Evidence policy failed: %.1f%% evidence unverifiable (threshold: %.1f%%)",
            failure_rate * 100,
            threshold * 100,
        )
        return False

    return True


# ======================================================================
# Deduplication & Normalization
# ======================================================================

def deduplicate_and_normalize(triage_data: dict) -> dict:
    """
    Remove duplicate topics/keywords and clamp confidence values.

    - Dedup topics by labelid (stable: keep first occurrence)
    - Dedup keywords within each topic by candidateid
    - Clamp all confidence values to [0.0, 1.0]
    """
    # Dedup topics
    seen_labels: set = set()
    unique_topics: List[dict] = []
    for topic in triage_data.get("topics", []):
        labelid = topic["labelid"]
        if labelid not in seen_labels:
            unique_topics.append(topic)
            seen_labels.add(labelid)
    triage_data["topics"] = unique_topics

    # Dedup keywords within each topic
    for topic in triage_data["topics"]:
        seen_cids: set = set()
        unique_kws: List[dict] = []
        for kw in topic.get("keywordsintext", []):
            cid = kw["candidateid"]
            if cid not in seen_cids:
                unique_kws.append(kw)
                seen_cids.add(cid)
        topic["keywordsintext"] = unique_kws

    # Clamp confidence values
    if "sentiment" in triage_data and "confidence" in triage_data["sentiment"]:
        triage_data["sentiment"]["confidence"] = float(
            np.clip(triage_data["sentiment"]["confidence"], 0.0, 1.0)
        )

    if "priority" in triage_data and "confidence" in triage_data["priority"]:
        triage_data["priority"]["confidence"] = float(
            np.clip(triage_data["priority"]["confidence"], 0.0, 1.0)
        )

    for topic in triage_data["topics"]:
        topic["confidence"] = float(np.clip(topic["confidence"], 0.0, 1.0))

    return triage_data
