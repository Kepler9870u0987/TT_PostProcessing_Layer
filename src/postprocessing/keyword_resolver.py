"""
Keyword Resolution from Catalog — ★FIX #1★

Resolves all keyword fields using ONLY the candidate catalog.
LLM provides: candidateid
Catalog populates: lemma, term, count, source, embeddingscore

This eliminates the entire class of bugs where the LLM invents
or mixes lemma/term/count values.

Reference: post-processing-enrichment-layer.md §3.2
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


def resolve_keywords_from_catalog(
    triage_data: dict,
    candidates: List[dict],
) -> dict:
    """
    ★FIX #1★ Resolve all keyword fields using ONLY the candidate catalog.

    LLM provides: candidateid
    Catalog populates: lemma, term, count, source, embeddingscore

    Args:
        triage_data: Validated triage output (topics with keywordsintext).
        candidates: Full candidate list with all metadata.

    Returns:
        triage_data with keyword fields populated from catalog.

    Raises:
        ValueError: If a candidateid does not exist in the catalog (critical error).
    """
    candidate_map = {c["candidateid"]: c for c in candidates}

    for topic in triage_data.get("topics", []):
        resolved_keywords: list = []
        for kw in topic.get("keywordsintext", []):
            cid = kw["candidateid"]

            if cid not in candidate_map:
                raise ValueError(
                    f"Invented candidateid in keyword resolution: {cid}"
                )

            # Populate all fields from catalog (trusted source)
            cand = candidate_map[cid]
            resolved_kw = {
                "candidateid": cid,
                "lemma": cand["lemma"],
                "term": cand["term"],
                "count": cand["count"],
                "source": cand["source"],
                "embeddingscore": cand.get("embeddingscore", 0.0),
            }

            # ★FIX #6★ Auto-repair count mismatch: log warning if LLM had a different count
            llm_count = kw.get("count")
            if llm_count is not None and llm_count != cand["count"]:
                logger.warning(
                    "Count mismatch for %s: LLM=%d, catalog=%d — using catalog value",
                    cid,
                    llm_count,
                    cand["count"],
                )

            resolved_keywords.append(resolved_kw)

        topic["keywordsintext"] = resolved_keywords

    return triage_data
