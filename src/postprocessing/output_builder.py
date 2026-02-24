"""
Output Normalization — ★FIX #4★ mapping keywordsintext → keywords.

Converts internal pipeline representation to the final
POST_PROCESSING_OUTPUT_SCHEMA format.

Reference: post-processing-enrichment-layer.md §10.7
"""
from typing import List


def normalize_topics_keywords(topics: List[dict]) -> List[dict]:
    """
    ★FIX #4★ Convert internal 'keywordsintext' field to 'keywords'
    as required by POST_PROCESSING_OUTPUT_SCHEMA.

    Each keyword gets: candidateid, term, lemma, count, source, embeddingscore.
    """
    for topic in topics:
        kws_in = topic.get("keywordsintext", [])

        topic["keywords"] = [
            {
                "candidateid": kw["candidateid"],
                "term": kw["term"],
                "lemma": kw["lemma"],
                "count": kw["count"],
                "source": kw["source"],
                "embeddingscore": kw.get("embeddingscore", 0.0),
            }
            for kw in kws_in
        ]

    return topics


def build_triage_output_schema(
    triage_with_conf: dict,
    customer_status: dict,
    priority: dict,
) -> dict:
    """
    Build the 'triage' section conforming to POST_PROCESSING_OUTPUT_SCHEMA.

    Args:
        triage_with_conf: Triage data after confidence adjustment
                          (has topics with confidence_llm/confidence_adjusted).
        customer_status: Computed customer status dict.
        priority: Computed priority dict.

    Returns:
        Complete triage dict with topics, sentiment, priority, customerstatus.
    """
    topics = triage_with_conf.get("topics", [])

    # 1. Map keywordsintext → keywords ★FIX #4★
    topics = normalize_topics_keywords(topics)

    # 2. Ensure confidence fields are present and consistent
    for t in topics:
        base_conf = t.get("confidence", 0.0)
        t.setdefault("confidence_llm", base_conf)
        t.setdefault("confidence_adjusted", base_conf)

    triage_output = {
        "topics": topics,
        "sentiment": triage_with_conf.get("sentiment", {}),
        "priority": priority,
        "customerstatus": customer_status,
    }

    return triage_output
