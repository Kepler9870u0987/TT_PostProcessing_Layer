"""
ValidationResult — encapsulates multi-stage validation outcome.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ValidationResult:
    """Result of multi-stage LLM output validation."""

    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data: Optional[dict] = None
