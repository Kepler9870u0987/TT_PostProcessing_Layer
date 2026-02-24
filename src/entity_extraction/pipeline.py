"""
Entity Extraction Pipeline — orchestrates RegEx + NER + Lexicon + Merge.

★FIX #3★ — Document-level: no labelid parameter in signature.

Pipeline:
    1. RegEx (high precision, confidence 0.95)
    2. spaCy NER (recall, confidence 0.75)
    3. Lexicon enhancement / gazetteer (confidence 0.85)
    4. Deterministic merge (priority: regex > lexicon > ner)

Reference: post-processing-enrichment-layer.md §8.7
"""
from typing import Dict, List

from src.entity_extraction.lexicon_enhancer import enhance_ner_with_lexicon
from src.entity_extraction.merger import merge_entities_deterministic
from src.entity_extraction.ner_extractor import extract_entities_ner
from src.entity_extraction.regex_matcher import (
    DEFAULT_REGEX_LEXICON,
    extract_entities_regex,
)
from src.models.entity import Entity


def extract_all_entities(
    text: str,
    regex_lexicon: Dict[str, List[dict]] | None = None,
    ner_lexicon: Dict[str, List[dict]] | None = None,
    nlp_model=None,
) -> List[Entity]:
    """
    ★FIX #3★ Full entity extraction pipeline (document-level).

    Signature updated: removed labelid parameter, operates on entire document.

    Args:
        text: Canonical email body text.
        regex_lexicon: {entity_label: [{"regex_pattern": ..., "label": ...}]}.
                       Defaults to DEFAULT_REGEX_LEXICON.
        ner_lexicon: {entity_label: [{"lemma": ..., "surface_forms": [...]}]}.
                     Defaults to empty dict (no gazetteer).
        nlp_model: Pre-loaded spaCy model. If None, lazy-loaded.

    Returns:
        Merged, deduplicated list of Entity objects.
    """
    if regex_lexicon is None:
        regex_lexicon = DEFAULT_REGEX_LEXICON
    if ner_lexicon is None:
        ner_lexicon = {}

    # 1. RegEx (high precision)
    regex_entities = extract_entities_regex(text, regex_lexicon)

    # 2. NER (recall)
    ner_entities = extract_entities_ner(text, nlp_model)

    # 3. Enhance NER with lexicon (gazetteer)
    enhanced_entities = enhance_ner_with_lexicon(ner_entities, ner_lexicon, text)

    # 4. Combine all
    all_entities = regex_entities + enhanced_entities

    # 5. Merge deterministic (priority: regex > lexicon > ner)
    merged = merge_entities_deterministic(all_entities)

    return merged
