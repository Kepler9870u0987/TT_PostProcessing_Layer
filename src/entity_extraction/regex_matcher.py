"""
RegEx Entity Matcher — high-precision entity extraction.

★FIX #3★ — Document-level: operates on entire document, not per-label.

Reference: post-processing-enrichment-layer.md §8.3
"""
import logging
import re
from typing import Dict, List

from src.models.entity import Entity

logger = logging.getLogger(__name__)


def extract_entities_regex(
    text: str,
    regex_lexicon: Dict[str, List[dict]],
) -> List[Entity]:
    """
    Extract entities using regex patterns from a global entity lexicon.

    ★FIX #3★ Document-level: no labelid parameter.

    Args:
        text: Canonical email body text.
        regex_lexicon: {
            "CODICEFISCALE": [{"regex_pattern": r"...", "label": "CODICEFISCALE"}, ...],
            "EMAIL":         [{"regex_pattern": r"...", "label": "EMAIL"}, ...],
            ...
        }

    Returns:
        List of Entity objects found via regex (source="regex", confidence=0.95).
    """
    entities: List[Entity] = []

    for entity_label, entries in regex_lexicon.items():
        for entry in entries:
            pattern = entry["regex_pattern"]
            label = entry.get("label", entity_label)

            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("Invalid regex pattern '%s': %s", pattern, e)
                continue

            for match in compiled.finditer(text):
                entities.append(
                    Entity(
                        text=match.group(0),
                        label=label,
                        start=match.start(),
                        end=match.end(),
                        source="regex",
                        confidence=0.95,
                    )
                )

    return entities


# ==========================================================================
# Default regex lexicon for common Italian entities
# ==========================================================================
DEFAULT_REGEX_LEXICON: Dict[str, List[dict]] = {
    "EMAIL": [
        {
            "regex_pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "label": "EMAIL",
        },
    ],
    "CODICEFISCALE": [
        {
            "regex_pattern": r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b",
            "label": "CODICEFISCALE",
        },
    ],
    "PARTITAIVA": [
        {
            "regex_pattern": r"\b(IT)?\d{11}\b",
            "label": "PARTITAIVA",
        },
    ],
    "IBAN": [
        {
            "regex_pattern": r"\b[A-Z]{2}\d{2}\s?[A-Z0-9]{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{3}\b",
            "label": "IBAN",
        },
    ],
    "TELEFONO": [
        {
            "regex_pattern": r"\b\+?\d{2,4}[\s.-]?\d{6,10}\b",
            "label": "TELEFONO",
        },
    ],
}
