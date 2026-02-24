"""
KeywordObservation — structured observation for dictionary promoter.
"""
from dataclasses import dataclass


@dataclass
class KeywordObservation:
    """A single keyword observation for batch promoter processing."""

    obs_id: str
    message_id: str
    labelid: str
    candidateid: str
    lemma: str
    term: str               # surface form
    count: int
    embeddingscore: float
    dict_version: int
    promoted_to_active: bool = False
    observed_at: str = ""   # ISO-8601 timestamp

    def to_dict(self) -> dict:
        return {
            "obs_id": self.obs_id,
            "message_id": self.message_id,
            "labelid": self.labelid,
            "candidateid": self.candidateid,
            "lemma": self.lemma,
            "term": self.term,
            "count": self.count,
            "embeddingscore": self.embeddingscore,
            "dict_version": self.dict_version,
            "promoted_to_active": self.promoted_to_active,
            "observed_at": self.observed_at,
        }
