"""
Customer Status — deterministic computation via CRM lookup + text signals.

NOT delegated to LLM. Uses:
1. CRM exact match (email)          → existing, confidence 1.0
2. CRM domain match                 → existing, confidence 0.7
3. Text signal detection            → existing, confidence 0.5
4. No match + no signal             → new, confidence 0.8
5. Lookup failed                    → unknown, confidence 0.2

Reference: post-processing-enrichment-layer.md §5
"""
import logging
from typing import Callable, Tuple

from src.config.constants import EXISTING_CUSTOMER_SIGNALS

logger = logging.getLogger(__name__)


def compute_customer_status(
    from_email: str,
    text_body: str,
    crm_lookup: Callable[[str], Tuple[str, float]],
) -> dict:
    """
    Compute customer status deterministically.

    Args:
        from_email: Sender email address.
        text_body: Canonical email body text.
        crm_lookup: Function(email) → (match_type, match_confidence).
                    match_type in {"exact", "domain", "none"}.

    Returns:
        {
            "value": "new" | "existing" | "unknown",
            "confidence": float [0, 1],
            "source": str
        }
    """
    # 1. CRM Lookup
    try:
        match_type, _match_confidence = crm_lookup(from_email)
    except Exception as e:
        logger.error("CRM lookup error for %s: %s", from_email, e)
        return {
            "value": "unknown",
            "confidence": 0.2,
            "source": "lookup_failed",
        }

    if match_type == "exact":
        return {
            "value": "existing",
            "confidence": 1.0,
            "source": "crm_exact_match",
        }

    if match_type == "domain":
        return {
            "value": "existing",
            "confidence": 0.7,
            "source": "crm_domain_match",
        }

    # 2. Text Signal Detection (only if CRM had no match)
    if match_type == "none":
        text_lower = text_body.lower()
        has_signal = any(sig in text_lower for sig in EXISTING_CUSTOMER_SIGNALS)

        if has_signal:
            return {
                "value": "existing",
                "confidence": 0.5,
                "source": "text_signal",
            }
        else:
            return {
                "value": "new",
                "confidence": 0.8,
                "source": "no_crm_no_signal",
            }

    # 3. Fallback
    return {
        "value": "unknown",
        "confidence": 0.2,
        "source": "lookup_failed",
    }


# ======================================================================
# Mock CRM Lookup (for testing — to be replaced in production)
# ======================================================================

def crm_lookup_mock(email: str) -> Tuple[str, float]:
    """
    Mock CRM for testing.

    TODO Production: Replace with:
    - REST API call with retry logic
    - Timeout handling (max 500ms)
    - Fallback to local cache if CRM is down
    - Error logging and monitoring
    """
    known_emails = {"mario.rossi@example.it", "cliente@acme.com"}
    known_domains = {"acme.com", "partner.it"}

    if email in known_emails:
        return ("exact", 1.0)

    domain = email.split("@")[-1] if "@" in email else ""
    if domain in known_domains:
        return ("domain", 0.7)

    return ("none", 0.0)
