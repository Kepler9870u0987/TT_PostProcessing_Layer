"""
Typed Pydantic models for triage I/O contracts.

Covers the Layer 2 → Layer 3 interface and the enriched post-processing
output, providing type safety where the codebase previously used plain dicts.

Gap fixes:
- G1: KeywordInText typed model
- G3: EnrichedEvidence typed model
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Layer 2 → Layer 3  (LLM output, accepted as-is after schema validation)
# =============================================================================


class KeywordInText(BaseModel):
    """
    A keyword selected by the LLM from the candidate list.

    The LLM naturally echoes candidate metadata fields (lemma, count, …)
    from the prompt — these are accepted here so no pre-validation stripping
    is needed.  Stage 2 (resolve_keywords_from_catalog) overwrites them with
    catalog-authoritative values, producing EnrichedKeyword objects.
    """

    candidateid: str = Field(..., description="MUST match a candidateid from the input candidate list.")
    lemma: Optional[str] = Field(None, description="Lemmatized form echoed by LLM (optional).")
    term: Optional[str] = Field(None, description="Original n-gram echoed by LLM (optional).")
    count: Optional[int] = Field(None, ge=1, description="Occurrence count echoed by LLM (optional).")
    source: Optional[str] = Field(None, description="'subject' | 'body' echoed by LLM (optional).")
    embeddingscore: Optional[float] = Field(None, ge=0.0, le=1.0, description="KeyBERT score echoed by LLM (optional).")


class EvidenceItem(BaseModel):
    """
    A single piece of textual evidence produced by the LLM.

    Span is optional: the LLM may or may not produce one, and it will be
    recomputed server-side by enrich_evidence_with_spans().
    """

    quote: str = Field(..., max_length=200, description="Exact quote from the email supporting this topic.")
    span: Optional[List[int]] = Field(None, description="[start, end] from LLM — optional, may be inaccurate.")

    @field_validator("span")
    @classmethod
    def validate_span(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            if len(v) != 2:
                raise ValueError("span must contain exactly two integers [start, end]")
            if v[0] >= v[1]:
                raise ValueError("span[0] must be strictly less than span[1]")
        return v


# =============================================================================
# Post-Processing output (Layer 3 →  final)
# =============================================================================


class EnrichedKeyword(BaseModel):
    """
    Keyword fully enriched with catalog data and dictionary match metadata.
    Produced by resolve_keywords_from_catalog() in Stage 2.
    """

    candidateid: str
    term: str
    lemma: str
    count: int = Field(..., ge=1)
    source: str
    embeddingscore: float = Field(0.0, ge=0.0, le=1.0)
    # Post-processing additions
    dictionary_match: Optional[str] = Field(None, description="'active' | 'proposed' | None")
    confidence_contribution: float = Field(0.0, ge=0.0)


class EnrichedEvidence(BaseModel):
    """
    Evidence item after server-side span computation.

    Spans are deterministic (computed from quote via body_canonical).
    Original LLM span is preserved as span_llm for audit.
    """

    quote: str = Field(..., max_length=200)
    span: Optional[Tuple[int, int]] = Field(None, description="Server-computed [start, end], None if not found.")
    span_llm: Optional[Tuple[int, int]] = Field(None, description="Original LLM span preserved for audit.")
    span_status: str = Field(..., description="'exact_match' | 'fuzzy_match' | 'not_found'")
    text_hash: str = Field(..., description="SHA-256 of body_canonical used for span computation.")

    @field_validator("span_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"exact_match", "fuzzy_match", "not_found"}
        if v not in allowed:
            raise ValueError(f"span_status must be one of {allowed}, got '{v}'")
        return v


class EnrichedTopic(BaseModel):
    """
    Topic after all post-processing stages (keyword enrichment + confidence
    adjustment + span enrichment).
    """

    labelid: str
    confidence_llm: float = Field(..., ge=0.0, le=1.0)
    confidence_adjusted: float = Field(..., ge=0.0, le=1.0)
    keywords: List[EnrichedKeyword]
    evidence: List[EnrichedEvidence]
