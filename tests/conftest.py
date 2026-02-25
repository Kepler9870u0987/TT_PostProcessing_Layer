"""
Shared test fixtures for the post-processing test suite.
"""
import json

import pytest

from src.models.email_document import EmailDocument
from src.models.pipeline_version import PipelineVersion


# ==========================================================================
# Pipeline Version
# ==========================================================================

@pytest.fixture
def pipeline_version():
    return PipelineVersion(
        dictionaryversion=42,
        modelversion="gpt-4o-2024-11-20",
    )


# ==========================================================================
# Candidates
# ==========================================================================

@pytest.fixture
def mock_candidates():
    return [
        {
            "candidateid": "ABC123",
            "source": "subject",
            "term": "contratto",
            "lemma": "contratto",
            "count": 3,
            "embeddingscore": 0.85,
            "score": 0.72,
        },
        {
            "candidateid": "DEF456",
            "source": "body",
            "term": "fattura",
            "lemma": "fattura",
            "count": 2,
            "embeddingscore": 0.65,
            "score": 0.55,
        },
        {
            "candidateid": "GHI789",
            "source": "body",
            "term": "rimborso",
            "lemma": "rimborso",
            "count": 1,
            "embeddingscore": 0.45,
            "score": 0.40,
        },
        {
            "candidateid": "JKL012",
            "source": "body",
            "term": "assistenza",
            "lemma": "assistenza",
            "count": 1,
            "embeddingscore": 0.50,
            "score": 0.42,
        },
    ]


# ==========================================================================
# Email Document
# ==========================================================================

@pytest.fixture
def mock_document():
    return EmailDocument(
        message_id="test-msg-001@example.it",
        from_raw="Mario Rossi <mario.rossi@example.it>",
        subject="Re: Richiesta informazioni contratto ABC",
        body="Buongiorno, vorrei confermare i dati del contratto. Ho una fattura da saldare. Grazie.",
        body_canonical="Buongiorno, vorrei confermare i dati del contratto. Ho una fattura da saldare.",
    )


# ==========================================================================
# LLM Output (valid)
# ==========================================================================

@pytest.fixture
def mock_llm_output(mock_candidates):
    return {
        "dictionaryversion": 42,
        "sentiment": {
            "value": "neutral",
            "confidence": 0.75,
        },
        "priority": {
            "value": "medium",
            "confidence": 0.7,
            "signals": ["scadenza contratto"],
        },
        "topics": [
            {
                "labelid": "CONTRATTO",
                "confidence": 0.9,
                "keywordsintext": [
                    {"candidateid": "ABC123"},
                ],
                "evidence": [
                    {
                        "quote": "confermare i dati del contratto",
                        "span": [22, 53],
                    },
                ],
            },
            {
                "labelid": "FATTURAZIONE",
                "confidence": 0.7,
                "keywordsintext": [
                    {"candidateid": "DEF456"},
                ],
                "evidence": [
                    {
                        "quote": "Ho una fattura da saldare",
                        "span": [55, 80],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def mock_llm_output_json(mock_llm_output):
    return json.dumps(mock_llm_output, ensure_ascii=False)


# ==========================================================================
# Regex & NER Lexicons
# ==========================================================================

@pytest.fixture
def mock_regex_lexicon():
    return {
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
    }


@pytest.fixture
def mock_ner_lexicon():
    return {
        "AZIENDA": [
            {
                "lemma": "ACME",
                "surface_forms": ["ACME", "ACME S.p.A.", "ACME spa"],
            },
        ],
    }


# ==========================================================================
# Collision Index
# ==========================================================================

@pytest.fixture
def mock_collision_index():
    """Collision index with one ambiguous keyword."""
    return {
        "contratto": {"CONTRATTO", "FATTURAZIONE"},
    }


@pytest.fixture
def empty_collision_index():
    return {}
