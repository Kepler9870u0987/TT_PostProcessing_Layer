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
import json
import logging
from typing import List

import numpy as np
from jsonschema import ValidationError, validate

from src.config.constants import MIN_CONFIDENCE_WARNING, TOPICS_ENUM
from src.config.schemas import LLM_RESPONSE_SCHEMA
from src.models.validation import ValidationResult

logger = logging.getLogger(__name__)


def validate_llm_output_multistage(
    output_json: str,
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
