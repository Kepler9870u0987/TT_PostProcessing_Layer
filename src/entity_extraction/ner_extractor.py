"""
spaCy NER Entity Extractor.

Uses it_core_news_lg for Italian named entity recognition.
Entities are extracted at document-level (★FIX #3★).

Reference: post-processing-enrichment-layer.md §8.4
"""
import logging
from typing import List, Optional

from src.models.entity import Entity

logger = logging.getLogger(__name__)

# Lazy-loaded spaCy model
_nlp_model = None


def _get_nlp_model():
    """Lazy-load spaCy model to avoid import-time cost."""
    global _nlp_model
    if _nlp_model is None:
        try:
            import spacy  # type: ignore[import-untyped]
            _nlp_model = spacy.load("it_core_news_lg")
            logger.info("Loaded spaCy model: it_core_news_lg")
        except (OSError, ImportError):
            logger.warning(
                "spaCy model 'it_core_news_lg' not found. "
                "Install with: python -m spacy download it_core_news_lg"
            )
            _nlp_model = None
    return _nlp_model


def extract_entities_ner(text: str, nlp_model=None) -> List[Entity]:
    """
    Extract entities using spaCy NER.

    Args:
        text: Canonical email body text.
        nlp_model: Optional pre-loaded spaCy model. If None, loads default.

    Returns:
        List of Entity objects (source="ner", confidence=0.75).
    """
    if nlp_model is None:
        nlp_model = _get_nlp_model()

    if nlp_model is None:
        logger.warning("No NER model available, returning empty entities")
        return []

    doc = nlp_model(text)
    entities: List[Entity] = []

    for ent in doc.ents:
        entities.append(
            Entity(
                text=ent.text,
                label=ent.label_,
                start=ent.start_char,
                end=ent.end_char,
                source="ner",
                confidence=0.75,
            )
        )

    return entities
