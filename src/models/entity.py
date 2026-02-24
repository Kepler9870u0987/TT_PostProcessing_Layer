"""
Entity model for extracted entities (RegEx / NER / Lexicon).
★FIX #3★ — Document-level, no labelid dependency.
"""
from dataclasses import dataclass


@dataclass
class Entity:
    """A single extracted entity with provenance."""

    text: str
    label: str
    start: int
    end: int
    source: str             # "regex" | "ner" | "lexicon"
    confidence: float = 1.0

    def overlaps(self, other: "Entity") -> bool:
        """Check if two entities have overlapping spans."""
        return not (self.end <= other.start or other.end <= self.start)

    def span_length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "source": self.source,
            "confidence": self.confidence,
        }

    def __repr__(self) -> str:
        return f"Entity('{self.text}', {self.label}, [{self.start},{self.end}], {self.source})"
