"""
Unit tests for observation storage.
"""
import pytest

from src.dictionary.observations import build_observations


class TestBuildObservations:
    """Tests for build_observations."""

    def test_creates_observations_for_keywords(self, mock_candidates):
        topics = [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [
                    {"candidateid": "ABC123"},
                    {"candidateid": "DEF456"},
                ],
            },
        ]

        observations = build_observations(
            message_id="msg-001",
            topics=topics,
            candidates=mock_candidates,
            dict_version=42,
        )

        assert len(observations) == 2
        assert observations[0]["message_id"] == "msg-001"
        assert observations[0]["labelid"] == "CONTRATTO"
        assert observations[0]["candidateid"] == "ABC123"
        assert observations[0]["lemma"] == "contratto"
        assert observations[0]["dict_version"] == 42
        assert observations[0]["promoted_to_active"] is False
        assert observations[0]["observed_at"] != ""

    def test_observation_has_all_required_fields(self, mock_candidates):
        topics = [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [{"candidateid": "ABC123"}],
            },
        ]
        observations = build_observations("msg-001", topics, mock_candidates, 42)

        required_fields = [
            "obs_id", "message_id", "labelid", "candidateid",
            "lemma", "term", "count", "embeddingscore",
            "dict_version", "promoted_to_active", "observed_at",
        ]

        for field in required_fields:
            assert field in observations[0], f"Missing field: {field}"

    def test_empty_topics_no_observations(self, mock_candidates):
        observations = build_observations("msg-001", [], mock_candidates, 42)
        assert observations == []

    def test_unique_obs_ids(self, mock_candidates):
        topics = [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [
                    {"candidateid": "ABC123"},
                    {"candidateid": "DEF456"},
                ],
            },
        ]
        observations = build_observations("msg-001", topics, mock_candidates, 42)
        obs_ids = [o["obs_id"] for o in observations]
        assert len(set(obs_ids)) == len(obs_ids), "obs_ids must be unique"

    def test_multiple_topics_multiple_observations(self, mock_candidates):
        topics = [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [{"candidateid": "ABC123"}],
            },
            {
                "labelid": "FATTURAZIONE",
                "keywordsintext": [{"candidateid": "DEF456"}],
            },
        ]
        observations = build_observations("msg-001", topics, mock_candidates, 42)
        assert len(observations) == 2
        assert observations[0]["labelid"] == "CONTRATTO"
        assert observations[1]["labelid"] == "FATTURAZIONE"
