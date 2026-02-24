"""
Unit tests for customer status computation.
"""
import pytest

from src.postprocessing.customer_status import (
    compute_customer_status,
    crm_lookup_mock,
)


class TestComputeCustomerStatus:
    """Tests for compute_customer_status with all 5 match levels."""

    def test_exact_match_existing(self):
        result = compute_customer_status(
            "mario.rossi@example.it",
            "Testo qualsiasi",
            crm_lookup_mock,
        )
        assert result["value"] == "existing"
        assert result["confidence"] == 1.0
        assert result["source"] == "crm_exact_match"

    def test_domain_match_existing(self):
        result = compute_customer_status(
            "nuovoutente@acme.com",
            "Testo qualsiasi",
            crm_lookup_mock,
        )
        assert result["value"] == "existing"
        assert result["confidence"] == 0.7
        assert result["source"] == "crm_domain_match"

    def test_text_signal_existing(self):
        result = compute_customer_status(
            "sconosciuto@gmail.com",
            "Buongiorno, sono già cliente dal 2020",
            crm_lookup_mock,
        )
        assert result["value"] == "existing"
        assert result["confidence"] == 0.5
        assert result["source"] == "text_signal"

    def test_no_match_no_signal_new(self):
        result = compute_customer_status(
            "sconosciuto@gmail.com",
            "Buongiorno, vorrei informazioni sui vostri prodotti.",
            crm_lookup_mock,
        )
        assert result["value"] == "new"
        assert result["confidence"] == 0.8
        assert result["source"] == "no_crm_no_signal"

    def test_crm_failure_unknown(self):
        def failing_lookup(email):
            raise ConnectionError("CRM down")

        result = compute_customer_status(
            "test@test.com",
            "Qualsiasi testo",
            failing_lookup,
        )
        assert result["value"] == "unknown"
        assert result["confidence"] == 0.2
        assert result["source"] == "lookup_failed"

    def test_text_signal_ho_gia_un_contratto(self):
        result = compute_customer_status(
            "nuovo@unknown.com",
            "Salve, ho già un contratto attivo con voi.",
            crm_lookup_mock,
        )
        assert result["value"] == "existing"
        assert result["source"] == "text_signal"

    def test_text_signal_case_insensitive(self):
        result = compute_customer_status(
            "nuovo@unknown.com",
            "SONO GIÀ CLIENTE da anni",
            crm_lookup_mock,
        )
        assert result["value"] == "existing"
        assert result["source"] == "text_signal"


class TestCRMLookupMock:
    """Tests for the mock CRM lookup function."""

    def test_known_email(self):
        match_type, conf = crm_lookup_mock("mario.rossi@example.it")
        assert match_type == "exact"
        assert conf == 1.0

    def test_known_domain(self):
        match_type, conf = crm_lookup_mock("anyone@acme.com")
        assert match_type == "domain"
        assert conf == 0.7

    def test_unknown_email(self):
        match_type, conf = crm_lookup_mock("unknown@random.org")
        assert match_type == "none"
        assert conf == 0.0
