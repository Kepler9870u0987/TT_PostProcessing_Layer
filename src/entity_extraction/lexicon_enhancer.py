"""
Lexicon Enhancement — gazetteer-based entity enrichment.

★FIX #3★ — Document-level: operates on entire text, not per-label.

Reference: post-processing-enrichment-layer.md §8.5
"""
from typing import Dict, List

from src.models.entity import Entity


def enhance_ner_with_lexicon(
    ner_entities: List[Entity],
    ner_lexicon: Dict[str, List[dict]],
    text: str,
) -> List[Entity]:
    """
    Enhance NER entities using a gazetteer lexicon.

    ★FIX #3★ Document-level: no labelid parameter.

    Args:
        ner_entities: Entities already found by NER.
        ner_lexicon: Global gazetteer structured as:
            {
                "AZIENDA": [
                    {"lemma": "ACME", "surface_forms": ["ACME", "ACME S.p.A."]},
                    ...
                ],
                ...
            }
        text: Canonical email body text.

    Returns:
        Combined list: original NER entities + lexicon-matched entities.
    """
    enhanced = list(ner_entities)
    lower_text = text.lower()

    for entity_label, entries in ner_lexicon.items():
        for entry in entries:
            lemma = entry["lemma"]
            surface_forms = entry.get("surface_forms", [lemma])

            for sf in surface_forms:
                lower_sf = sf.lower()
                pos = 0

                while pos < len(lower_text):
                    pos = lower_text.find(lower_sf, pos)
                    if pos == -1:
                        break

                    # Word boundary check
                    before_ok = (pos == 0) or (not lower_text[pos - 1].isalnum())
                    after_index = pos + len(lower_sf)
                    after_ok = (
                        after_index == len(lower_text)
                        or not lower_text[after_index].isalnum()
                    )

                    if before_ok and after_ok:
                        enhanced.append(
                            Entity(
                                text=text[pos : pos + len(sf)],
                                label=lemma,
                                start=pos,
                                end=pos + len(sf),
                                source="lexicon",
                                confidence=0.85,
                            )
                        )

                    pos += 1

    return enhanced
