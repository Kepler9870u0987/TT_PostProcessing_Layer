"""
JSON Schemas for LLM response validation and post-processing output.

Two schemas:
1. LLM_RESPONSE_SCHEMA  — what the LLM must produce (v3.3: only candidateid)
2. POST_PROCESSING_OUTPUT_SCHEMA — final enriched output

References:
- post-processing-enrichment-layer.md §13
- Brainstorming v2 §3.2 (PARSE-optimized)
"""
from src.config.constants import TOPICS_ENUM

# =============================================================================
# 1. LLM Response Schema (v3.3 — ★FIX #1★ candidateid-only in keywordsintext)
# =============================================================================
LLM_RESPONSE_SCHEMA: dict = {
    "name": "email_triage_v3",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["dictionaryversion", "topics", "sentiment", "priority"],
        "properties": {
            "dictionaryversion": {
                "type": "integer",
                "description": "Version of keyword dictionary used",
            },
            "sentiment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "confidence"],
                "properties": {
                    "value": {
                        "type": "string",
                        "enum": ["positive", "neutral", "negative"],
                        "description": "Overall email sentiment",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
            "priority": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "confidence", "signals"],
                "properties": {
                    "value": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "Priority level: urgent=immediate, high=same day, medium=1-2d, low=routine",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "signals": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string"},
                        "description": "Phrases/keywords that justify priority (for audit)",
                    },
                },
            },
            "topics": {
                "type": "array",
                "maxItems": 5,
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["labelid", "confidence", "keywordsintext", "evidence"],
                    "properties": {
                        "labelid": {
                            "type": "string",
                            "enum": TOPICS_ENUM,
                            "description": "Topic label from closed taxonomy",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "keywordsintext": {
                            "type": "array",
                            "maxItems": 15,
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["candidateid"],
                                "properties": {
                                    "candidateid": {
                                        "type": "string",
                                        "description": "MUST match a candidateid from input candidate list. Do NOT invent.",
                                    },
                                },
                            },
                            "description": "Keywords ONLY from candidate list that support this topic",
                        },
                        "evidence": {
                            "type": "array",
                            "maxItems": 2,
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["quote"],
                                "properties": {
                                    "quote": {
                                        "type": "string",
                                        "maxLength": 200,
                                        "description": "Exact quote from email supporting this topic",
                                    },
                                    "span": {
                                        "type": "array",
                                        "minItems": 2,
                                        "maxItems": 2,
                                        "items": {"type": "integer"},
                                    },
                                },
                            },
                            "description": "Text evidence justifying topic assignment",
                        },
                    },
                },
            },
        },
    },
}


# =============================================================================
# 2. Post-Processing Output Schema (final enriched output)
# =============================================================================
POST_PROCESSING_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["message_id", "pipeline_version", "triage", "entities", "observations", "diagnostics"],
    "properties": {
        "message_id": {"type": "string"},
        "pipeline_version": {
            "type": "object",
            "required": ["dictionaryversion", "modelversion"],
        },
        "triage": {
            "type": "object",
            "required": ["topics", "sentiment", "priority", "customerstatus"],
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "labelid",
                            "confidence_llm",
                            "confidence_adjusted",
                            "keywords",
                            "evidence",
                        ],
                        "properties": {
                            "labelid": {"type": "string"},
                            "confidence_llm": {"type": "number", "minimum": 0, "maximum": 1},
                            "confidence_adjusted": {"type": "number", "minimum": 0, "maximum": 1},
                            "keywords": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["candidateid", "term", "lemma", "count", "source"],
                                    "properties": {
                                        "candidateid": {"type": "string"},
                                        "term": {"type": "string"},
                                        "lemma": {"type": "string"},
                                        "count": {"type": "integer"},
                                        "source": {"type": "string"},
                                        "embeddingscore": {"type": "number"},
                                    },
                                },
                            },
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["quote"],
                                    "properties": {
                                        "quote": {"type": "string", "maxLength": 200},
                                        "span": {
                                            "type": "array",
                                            "minItems": 2,
                                            "maxItems": 2,
                                            "items": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
                "sentiment": {
                    "type": "object",
                    "required": ["value", "confidence"],
                    "properties": {
                        "value": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
                "priority": {
                    "type": "object",
                    "required": ["value", "confidence", "signals", "rawscore"],
                    "properties": {
                        "value": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "signals": {"type": "array", "items": {"type": "string"}},
                        "rawscore": {"type": "number"},
                    },
                },
                "customerstatus": {
                    "type": "object",
                    "required": ["value", "confidence", "source"],
                    "properties": {
                        "value": {"type": "string", "enum": ["new", "existing", "unknown"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "source": {"type": "string"},
                    },
                },
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "label", "start", "end", "source", "confidence"],
                "properties": {
                    "text": {"type": "string"},
                    "label": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "source": {"type": "string", "enum": ["regex", "ner", "lexicon"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "obs_id",
                    "message_id",
                    "labelid",
                    "candidateid",
                    "lemma",
                    "term",
                    "count",
                    "embeddingscore",
                    "dict_version",
                    "observed_at",
                ],
            },
        },
        "diagnostics": {
            "type": "object",
            "required": ["warnings", "validation_retries", "fallback_applied"],
            "properties": {
                "warnings": {"type": "array", "items": {"type": "string"}},
                "validation_retries": {"type": "integer"},
                "fallback_applied": {"type": "boolean"},
            },
        },
    },
}
