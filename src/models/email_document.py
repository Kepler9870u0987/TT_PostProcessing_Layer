"""
EmailDocument and RemovedSection — canonical email representation.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class RemovedSection:
    """Tracks what was removed during canonicalization (for audit)."""

    section_type: str       # "quote" | "signature" | "disclaimer" | "reply_header"
    span_start: int
    span_end: int
    content: str


@dataclass(frozen=True)
class EmailDocument:
    """Canonical email ready for pipeline processing."""

    message_id: str
    from_raw: str
    subject: str
    body: str                                           # Original full body
    body_canonical: str                                 # Cleaned body
    removed_sections: tuple = field(default=())         # Tuple[RemovedSection, ...]
    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.2.0"

    @property
    def from_email(self) -> str:
        """Extract bare email address from from_raw."""
        raw = self.from_raw
        if "<" in raw and ">" in raw:
            return raw[raw.index("<") + 1 : raw.index(">")].strip()
        return raw.strip()
