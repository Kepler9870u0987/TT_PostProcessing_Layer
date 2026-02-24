"""
Unit tests for entity extraction (★FIX #3★ — document-level).
Tests: regex_matcher, lexicon_enhancer, merger, pipeline.
"""
import pytest

from src.entity_extraction.lexicon_enhancer import enhance_ner_with_lexicon
from src.entity_extraction.merger import merge_entities_deterministic
from src.entity_extraction.pipeline import extract_all_entities
from src.entity_extraction.regex_matcher import extract_entities_regex
from src.models.entity import Entity


class TestEntityOverlaps:
    """Tests for Entity.overlaps() method."""

    def test_no_overlap(self):
        e1 = Entity("a", "L", 0, 5, "regex")
        e2 = Entity("b", "L", 10, 15, "regex")
        assert not e1.overlaps(e2)
        assert not e2.overlaps(e1)

    def test_overlap(self):
        e1 = Entity("a", "L", 0, 10, "regex")
        e2 = Entity("b", "L", 5, 15, "regex")
        assert e1.overlaps(e2)
        assert e2.overlaps(e1)

    def test_contained(self):
        e1 = Entity("a", "L", 0, 20, "regex")
        e2 = Entity("b", "L", 5, 10, "regex")
        assert e1.overlaps(e2)
        assert e2.overlaps(e1)

    def test_adjacent_no_overlap(self):
        e1 = Entity("a", "L", 0, 5, "regex")
        e2 = Entity("b", "L", 5, 10, "regex")
        assert not e1.overlaps(e2)


class TestRegexMatcher:
    """Tests for extract_entities_regex."""

    def test_email_extraction(self, mock_regex_lexicon):
        text = "Contattami a mario.rossi@example.it per info."
        entities = extract_entities_regex(text, mock_regex_lexicon)

        emails = [e for e in entities if e.label == "EMAIL"]
        assert len(emails) == 1
        assert emails[0].text == "mario.rossi@example.it"
        assert emails[0].source == "regex"
        assert emails[0].confidence == 0.95

    def test_codice_fiscale_extraction(self, mock_regex_lexicon):
        text = "Il codice fiscale è RSSMRA85M01H501Z, grazie."
        entities = extract_entities_regex(text, mock_regex_lexicon)

        cfs = [e for e in entities if e.label == "CODICEFISCALE"]
        assert len(cfs) == 1
        assert cfs[0].text == "RSSMRA85M01H501Z"

    def test_no_match_returns_empty(self, mock_regex_lexicon):
        text = "Buongiorno, testo senza entità riconoscibili."
        entities = extract_entities_regex(text, mock_regex_lexicon)
        assert len(entities) == 0

    def test_invalid_regex_skipped(self):
        bad_lexicon = {
            "BAD": [{"regex_pattern": r"[invalid(", "label": "BAD"}],
        }
        text = "Some text"
        entities = extract_entities_regex(text, bad_lexicon)
        assert len(entities) == 0  # No crash, just skipped


class TestLexiconEnhancer:
    """Tests for enhance_ner_with_lexicon."""

    def test_lexicon_match(self, mock_ner_lexicon):
        text = "L'azienda ACME ha inviato la fattura."
        existing = []

        enhanced = enhance_ner_with_lexicon(existing, mock_ner_lexicon, text)

        acme_entities = [e for e in enhanced if "ACME" in e.text]
        assert len(acme_entities) >= 1
        assert acme_entities[0].source == "lexicon"
        assert acme_entities[0].confidence == 0.85

    def test_word_boundary_respected(self, mock_ner_lexicon):
        text = "La parola ACMEEXTRA non è ACME."
        enhanced = enhance_ner_with_lexicon([], mock_ner_lexicon, text)

        # Should match "ACME" at end but NOT "ACMEEXTRA"
        acme_exact = [e for e in enhanced if e.text == "ACME"]
        assert len(acme_exact) >= 1

    def test_preserves_existing_entities(self, mock_ner_lexicon):
        existing = [Entity("Roma", "LOC", 0, 4, "ner", 0.75)]
        text = "Roma è una città. ACME è un'azienda."

        enhanced = enhance_ner_with_lexicon(existing, mock_ner_lexicon, text)

        # Should have both original and new
        assert any(e.text == "Roma" for e in enhanced)
        assert any("ACME" in e.text for e in enhanced)


class TestMerger:
    """Tests for merge_entities_deterministic."""

    def test_no_overlap_keeps_all(self):
        entities = [
            Entity("ACME", "ORG", 0, 4, "regex", 0.95),
            Entity("Roma", "LOC", 10, 14, "ner", 0.75),
        ]
        merged = merge_entities_deterministic(entities)
        assert len(merged) == 2

    def test_regex_wins_over_ner(self):
        entities = [
            Entity("ACME", "ORG", 0, 4, "ner", 0.75),
            Entity("ACME", "ORG", 0, 4, "regex", 0.95),
        ]
        merged = merge_entities_deterministic(entities)
        assert len(merged) == 1
        assert merged[0].source == "regex"

    def test_lexicon_wins_over_ner(self):
        entities = [
            Entity("ACME", "ORG", 0, 4, "ner", 0.90),
            Entity("ACME", "ORG", 0, 4, "lexicon", 0.85),
        ]
        merged = merge_entities_deterministic(entities)
        assert len(merged) == 1
        assert merged[0].source == "lexicon"

    def test_longest_span_wins_same_source(self):
        entities = [
            Entity("ACME", "ORG", 0, 4, "lexicon", 0.85),
            Entity("ACME S.p.A.", "ORG", 0, 11, "lexicon", 0.85),
        ]
        merged = merge_entities_deterministic(entities)
        assert len(merged) == 1
        assert merged[0].text == "ACME S.p.A."

    def test_higher_confidence_wins_same_span(self):
        entities = [
            Entity("ACME", "ORG", 0, 4, "ner", 0.75),
            Entity("ACME", "ORG", 0, 4, "ner", 0.90),
        ]
        merged = merge_entities_deterministic(entities)
        assert len(merged) == 1
        assert merged[0].confidence == 0.90

    def test_empty_input(self):
        assert merge_entities_deterministic([]) == []

    def test_sorted_by_position(self):
        entities = [
            Entity("B", "L", 10, 15, "regex", 0.95),
            Entity("A", "L", 0, 5, "regex", 0.95),
        ]
        merged = merge_entities_deterministic(entities)
        assert merged[0].start < merged[1].start


class TestExtractAllEntities:
    """Tests for the full entity extraction pipeline (★FIX #3★)."""

    def test_document_level_no_labelid(self, mock_regex_lexicon, mock_ner_lexicon):
        """★FIX #3★ Signature has NO labelid parameter."""
        text = "Contattami a mario.rossi@example.it. L'azienda ACME ringrazia."

        # This should work without labelid
        entities = extract_all_entities(
            text,
            regex_lexicon=mock_regex_lexicon,
            ner_lexicon=mock_ner_lexicon,
            nlp_model=None,  # NER disabled for unit test
        )

        # Should find at least email via regex and ACME via lexicon
        assert any(e.label == "EMAIL" for e in entities)
        assert any("ACME" in e.text for e in entities)

    def test_default_lexicon_used(self):
        text = "Inviare a test@example.com i documenti."
        entities = extract_all_entities(text, nlp_model=None)

        emails = [e for e in entities if e.label == "EMAIL"]
        assert len(emails) >= 1
