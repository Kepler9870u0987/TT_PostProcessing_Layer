"""
Unit tests for keyword resolution from catalog (★FIX #1★).
"""
import pytest

from src.postprocessing.keyword_resolver import resolve_keywords_from_catalog


class TestKeywordResolution:
    """Tests for resolve_keywords_from_catalog."""

    def test_resolves_all_fields_from_catalog(self, mock_candidates):
        triage_data = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "keywordsintext": [{"candidateid": "ABC123"}],
                },
            ],
        }
        result = resolve_keywords_from_catalog(triage_data, mock_candidates)
        kw = result["topics"][0]["keywordsintext"][0]

        assert kw["candidateid"] == "ABC123"
        assert kw["lemma"] == "contratto"
        assert kw["term"] == "contratto"
        assert kw["count"] == 3
        assert kw["source"] == "subject"
        assert kw["embeddingscore"] == 0.85

    def test_multiple_keywords_resolved(self, mock_candidates):
        triage_data = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "keywordsintext": [
                        {"candidateid": "ABC123"},
                        {"candidateid": "DEF456"},
                    ],
                },
            ],
        }
        result = resolve_keywords_from_catalog(triage_data, mock_candidates)
        keywords = result["topics"][0]["keywordsintext"]

        assert len(keywords) == 2
        assert keywords[0]["lemma"] == "contratto"
        assert keywords[1]["lemma"] == "fattura"

    def test_invented_candidateid_raises(self, mock_candidates):
        triage_data = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "keywordsintext": [{"candidateid": "INVENTED_999"}],
                },
            ],
        }
        with pytest.raises(ValueError, match="Invented candidateid"):
            resolve_keywords_from_catalog(triage_data, mock_candidates)

    def test_empty_topics_no_error(self, mock_candidates):
        triage_data = {"topics": []}
        result = resolve_keywords_from_catalog(triage_data, mock_candidates)
        assert result["topics"] == []

    def test_missing_embeddingscore_defaults_to_zero(self):
        candidates = [
            {
                "candidateid": "NO_EMB",
                "lemma": "test",
                "term": "test",
                "count": 1,
                "source": "body",
                # No embeddingscore
            },
        ]
        triage_data = {
            "topics": [
                {
                    "labelid": "CONTRATTO",
                    "keywordsintext": [{"candidateid": "NO_EMB"}],
                },
            ],
        }
        result = resolve_keywords_from_catalog(triage_data, candidates)
        assert result["topics"][0]["keywordsintext"][0]["embeddingscore"] == 0.0
