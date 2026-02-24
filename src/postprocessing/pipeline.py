"""
Pipeline Orchestrator — main entry point for post-processing & enrichment.

Executes the 7-stage pipeline:
    1. Validation & Normalization
    2. Keyword Resolution from Catalog ★FIX #1★
    3. Customer Status (deterministic CRM lookup)
    4. Priority Scoring (rule-based)
    5. Confidence Adjustment ★FIX #2★
    6. Entity Extraction (document-level) ★FIX #3★
    7. Output Normalization ★FIX #4★ + Observation Storage

Reference: post-processing-enrichment-layer.md §2.2
"""
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

from src.dictionary.observations import build_observations
from src.entity_extraction.pipeline import extract_all_entities
from src.models.email_document import EmailDocument
from src.models.entity import Entity
from src.models.pipeline_version import PipelineVersion
from src.postprocessing.confidence import (
    adjust_all_topic_confidences,
    build_collision_index,
)
from src.postprocessing.customer_status import compute_customer_status, crm_lookup_mock
from src.postprocessing.keyword_resolver import resolve_keywords_from_catalog
from src.postprocessing.output_builder import build_triage_output_schema
from src.postprocessing.priority_scorer import PriorityScorer, priority_scorer
from src.postprocessing.validation import (
    enforce_evidence_policy,
    validate_llm_output_multistage,
)

logger = logging.getLogger(__name__)


def postprocess_and_enrich(
    llm_output_raw: dict | str,
    candidates: List[dict],
    document: EmailDocument,
    pipeline_version: PipelineVersion,
    crm_lookup: Optional[Callable[[str], Tuple[str, float]]] = None,
    scorer: Optional[PriorityScorer] = None,
    regex_lexicon: Optional[Dict[str, List[dict]]] = None,
    ner_lexicon: Optional[Dict[str, List[dict]]] = None,
    nlp_model=None,
    collision_index: Optional[dict] = None,
    evidence_threshold: float = 0.3,
) -> dict:
    """
    Main post-processing & enrichment pipeline.

    7-stage flow:
        1. Validate & Normalize LLM output
        2. Resolve keywords from catalog (★FIX #1★)
        3. Compute customer status (CRM + text signals)
        4. Score priority (rule-based)
        5. Adjust topic confidences (★FIX #2★)
        6. Extract entities (document-level, ★FIX #3★)
        7. Build output + observations (★FIX #4★)

    Args:
        llm_output_raw: Raw LLM output (JSON string or dict).
        candidates: Candidate keyword list with metadata.
        document: Canonical EmailDocument.
        pipeline_version: PipelineVersion for traceability.
        crm_lookup: CRM lookup function. Defaults to mock.
        scorer: PriorityScorer instance. Defaults to module-level scorer.
        regex_lexicon: Regex patterns for entity extraction.
        ner_lexicon: Gazetteer for lexicon enhancement.
        nlp_model: Pre-loaded spaCy model for NER.
        collision_index: Pre-computed collision index. If None, builds placeholder.
        evidence_threshold: Max acceptable evidence failure rate (default 0.3).

    Returns:
        Complete post-processing output dict conforming to POST_PROCESSING_OUTPUT_SCHEMA.
    """
    start_time = time.monotonic()

    if crm_lookup is None:
        crm_lookup = crm_lookup_mock
    if scorer is None:
        scorer = priority_scorer
    if collision_index is None:
        collision_index = build_collision_index(candidates)

    validation_retries = 0
    fallback_applied = False

    # ==================================================================
    # Stage 1: Validate & Normalize
    # ==================================================================
    validation_result = validate_llm_output_multistage(
        llm_output_raw,
        candidates,
        document.body_canonical,
    )

    if not validation_result.valid:
        logger.error(
            "LLM output validation failed: %s", validation_result.errors
        )
        raise ValueError(
            f"LLM output validation failed: {validation_result.errors}"
        )

    assert validation_result.data is not None
    triage_normalized: dict = validation_result.data

    # Check evidence policy
    if not enforce_evidence_policy(
        triage_normalized.get("topics", []),
        document.body_canonical,
        threshold=evidence_threshold,
    ):
        logger.warning("Evidence policy failed — would trigger retry in production")
        # In production: retry LLM call here

    # ==================================================================
    # Stage 2: Keyword Resolution from Catalog ★FIX #1★
    # ==================================================================
    triage_normalized = resolve_keywords_from_catalog(triage_normalized, candidates)

    # ==================================================================
    # Stage 3: Customer Status (deterministic)
    # ==================================================================
    customer_status = compute_customer_status(
        document.from_email,
        document.body_canonical,
        crm_lookup,
    )

    # ==================================================================
    # Stage 4: Priority Scoring (rule-based)
    # ==================================================================
    priority = scorer.score(
        subject=document.subject,
        body_canonical=document.body_canonical,
        sentiment_value=triage_normalized.get("sentiment", {}).get("value", "neutral"),
        customer_value=customer_status["value"],
        vip_status=False,  # TODO: lookup from external source
    )

    # ==================================================================
    # Stage 5: Confidence Adjustment ★FIX #2★
    # ==================================================================
    triage_with_conf = adjust_all_topic_confidences(
        triage_normalized,
        candidates,
        collision_index,
    )

    # ==================================================================
    # Stage 6: Entity Extraction (document-level) ★FIX #3★
    # ==================================================================
    entities: List[Entity] = extract_all_entities(
        document.body_canonical,
        regex_lexicon=regex_lexicon,
        ner_lexicon=ner_lexicon,
        nlp_model=nlp_model,
    )

    # ==================================================================
    # Stage 7: Observations + Output Normalization ★FIX #4★
    # ==================================================================
    observations = build_observations(
        document.message_id,
        triage_with_conf.get("topics", []),
        candidates,
        pipeline_version.dictionaryversion,
    )

    triage_output = build_triage_output_schema(
        triage_with_conf,
        customer_status,
        priority,
    )

    # ==================================================================
    # Assembly
    # ==================================================================
    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    return {
        "message_id": document.message_id,
        "pipeline_version": pipeline_version.to_dict(),
        "triage": triage_output,
        "entities": [e.to_dict() for e in entities],
        "observations": observations,
        "diagnostics": {
            "warnings": validation_result.warnings,
            "validation_retries": validation_retries,
            "fallback_applied": fallback_applied,
        },
        "processing_metadata": {
            "postprocessing_duration_ms": elapsed_ms,
            "entities_extracted": len(entities),
            "observations_created": len(observations),
            "confidence_adjustments_applied": len(triage_with_conf.get("topics", [])),
        },
    }
