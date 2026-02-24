"""
Deterministic Entity Merger.

Merges overlapping entities with fixed priority rules:
1. Source priority: regex > lexicon > ner
2. Same source → longest span wins
3. Same length  → higher confidence wins

Reference: post-processing-enrichment-layer.md §8.6
"""
from typing import List

from src.models.entity import Entity

SOURCE_PRIORITY = {"regex": 0, "lexicon": 1, "ner": 2}


def merge_entities_deterministic(entities: List[Entity]) -> List[Entity]:
    """
    Merge overlapping entities using deterministic rules.

    Priority resolution:
        1. regex > lexicon > ner  (source priority)
        2. If same source, longest span wins
        3. If same length, higher confidence wins

    Args:
        entities: All extracted entities (may overlap).

    Returns:
        Deduplicated, non-overlapping entities sorted by position.
    """
    if not entities:
        return []

    # Sort by start position, then by reverse end (longest first),
    # then by source priority, then by reverse confidence
    entities_sorted = sorted(
        entities,
        key=lambda e: (
            e.start,
            -e.end,
            SOURCE_PRIORITY.get(e.source, 99),
            -e.confidence,
        ),
    )

    merged: List[Entity] = []

    for entity in entities_sorted:
        overlap_found = False

        for i, existing in enumerate(merged):
            if entity.overlaps(existing):
                overlap_found = True

                entity_prio = SOURCE_PRIORITY.get(entity.source, 99)
                existing_prio = SOURCE_PRIORITY.get(existing.source, 99)

                # 1. Higher source priority wins
                if entity_prio < existing_prio:
                    merged[i] = entity
                elif entity_prio == existing_prio:
                    # 2. Longest span wins
                    entity_len = entity.span_length()
                    existing_len = existing.span_length()

                    if entity_len > existing_len:
                        merged[i] = entity
                    elif entity_len == existing_len and entity.confidence > existing.confidence:
                        # 3. Higher confidence wins
                        merged[i] = entity

                break

        if not overlap_found:
            merged.append(entity)

    # Sort final list by position
    merged.sort(key=lambda e: e.start)
    return merged
