"""
Observation Storage — builds structured observations for the dictionary Promoter.

Observations are facts linking (message_id, labelid, candidateid, keyword metadata)
that feed the batch Promoter job for dictionary auto-update.

Reference: post-processing-enrichment-layer.md §9
"""
import uuid
from datetime import datetime, timezone
from typing import List


def build_observations(
    message_id: str,
    topics: List[dict],
    candidates: List[dict],
    dict_version: int,
) -> List[dict]:
    """
    Extract observation facts from assigned topics.

    For each keyword in each topic, create an observation record
    for batch insert into the observations table.

    Args:
        message_id: Source email message ID.
        topics: List of topic dicts (with keywordsintext populated from catalog).
        candidates: Full candidate list.
        dict_version: Current dictionary version.

    Returns:
        List of observation dicts ready for DB insert.
    """
    observations: List[dict] = []
    candidate_map = {c["candidateid"]: c for c in candidates}

    for topic in topics:
        labelid = topic["labelid"]

        for kw in topic.get("keywordsintext", []):
            cid = kw["candidateid"]
            cand = candidate_map.get(cid)

            if cand:
                obs = {
                    "obs_id": str(uuid.uuid4()),
                    "message_id": message_id,
                    "labelid": labelid,
                    "candidateid": cid,
                    "lemma": cand["lemma"],
                    "term": cand["term"],
                    "count": cand["count"],
                    "embeddingscore": cand.get("embeddingscore", 0.0),
                    "dict_version": dict_version,
                    "promoted_to_active": False,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
                observations.append(obs)

    return observations
