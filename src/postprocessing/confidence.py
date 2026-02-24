"""
Confidence Adjustment — ★FIX #2★ composite confidence with proper naming.

Formula:
    confidence_adjusted =
        0.3 × confidence_llm +
        0.4 × avg_keyword_quality +
        0.2 × evidence_coverage +
        0.1 × (1 - collision_penalty)

Naming convention:
    - confidence_llm        : original LLM-declared confidence (read-only)
    - confidence_adjusted   : recalibrated confidence (used in production)
    - confidence            : alias = confidence_adjusted (backward compat)

Reference: post-processing-enrichment-layer.md §7
"""
import logging
from collections import defaultdict
from typing import Dict, List, Set

import numpy as np

logger = logging.getLogger(__name__)


def compute_topic_confidence_adjusted(
    topic: dict,
    candidates: List[dict],
    collision_index: Dict[str, Set[str]],
    llm_confidence: float,
) -> float:
    """
    Compute calibrated confidence for a single topic.

    Components:
        1. LLM confidence (weight 0.3)
        2. Keyword quality — avg composite score of selected candidates (weight 0.4)
        3. Evidence coverage — min(len(evidence) / 2.0, 1.0) (weight 0.2)
        4. Collision penalty — 1/num_labels per ambiguous keyword (weight 0.1)

    Args:
        topic: Single topic dict with keywordsintext and evidence.
        candidates: Full candidate list.
        collision_index: {lemma: set(labelid)} from historical observations.
        llm_confidence: Original LLM-declared confidence.

    Returns:
        Adjusted confidence in [0.0, 1.0].
    """
    keywordsintext = topic.get("keywordsintext", [])
    if not keywordsintext:
        return 0.1  # Very low confidence if no keywords

    cand_map = {c["candidateid"]: c for c in candidates}

    # 1. Keyword quality score
    keyword_scores: List[float] = []
    for kw in keywordsintext:
        cand = cand_map.get(kw["candidateid"])
        if cand:
            kw_score = cand.get("score", cand.get("embeddingscore", 0.5))
            keyword_scores.append(kw_score)
    avg_kw_score = float(np.mean(keyword_scores)) if keyword_scores else 0.0

    # 2. Evidence coverage
    evidence = topic.get("evidence", [])
    evidence_score = min(len(evidence) / 2.0, 1.0)

    # 3. Collision penalty
    labelid = topic["labelid"]
    collision_penalties: List[float] = []
    for kw in keywordsintext:
        cand = cand_map.get(kw["candidateid"])
        if cand:
            lemma = cand["lemma"]
            labels_with_lemma = collision_index.get(lemma, {labelid})
            if len(labels_with_lemma) > 1:
                penalty = 1.0 / len(labels_with_lemma)
                collision_penalties.append(penalty)
            else:
                collision_penalties.append(1.0)

    avg_collision_penalty = float(np.mean(collision_penalties)) if collision_penalties else 1.0

    # Composite formula
    confidence_adjusted = (
        0.3 * llm_confidence
        + 0.4 * avg_kw_score
        + 0.2 * evidence_score
        + 0.1 * avg_collision_penalty
    )

    return float(np.clip(confidence_adjusted, 0.0, 1.0))


def adjust_all_topic_confidences(
    output: dict,
    candidates: List[dict],
    collision_index: Dict[str, Set[str]],
) -> dict:
    """
    ★FIX #2★ Recalculate confidence for all topics with correct naming.

    Sets:
        topic["confidence_llm"]       = original LLM confidence (read-only)
        topic["confidence_adjusted"]  = recalibrated confidence (production)
        topic["confidence"]           = alias = confidence_adjusted (backward compat)
    """
    for topic in output.get("topics", []):
        # Read the starting confidence
        llm_conf = topic.get("confidence_llm", topic.get("confidence", 0.0))

        # Calculate recalibrated confidence
        adjusted_conf = compute_topic_confidence_adjusted(
            topic, candidates, collision_index, llm_conf
        )

        # ★FIX #2★ Update fields with consistent naming
        topic["confidence_llm"] = llm_conf
        topic["confidence_adjusted"] = adjusted_conf
        topic["confidence"] = adjusted_conf  # backward compat alias

    return output


def build_collision_index(candidates: List[dict]) -> Dict[str, Set[str]]:
    """
    Build collision index: for each lemma, find all labelids where it appears.

    TODO: Replace with build_collision_index_from_db() in Fase 2
    (query on historical observations with promoted_to_active = TRUE).

    Currently returns empty dict (placeholder — no historical data yet).
    """
    collision_index: Dict[str, Set[str]] = defaultdict(set)
    # Placeholder: empty. In production, populate from DB query:
    # SELECT lemma, labelid, COUNT(*) FROM observations
    #   WHERE promoted_to_active = TRUE GROUP BY lemma, labelid
    return dict(collision_index)
