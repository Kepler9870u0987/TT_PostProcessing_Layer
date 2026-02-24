"""
Priority Scoring — rule-based parametric scorer.

Computes priority by combining:
- Urgent/High keyword detection
- Sentiment polarity
- Customer status
- Deadline detection (regex)
- VIP status

Pesi (weights) are configurable and can be learned from historical data.

Reference: post-processing-enrichment-layer.md §6
"""
import re
from typing import List, Optional

from src.config.constants import HIGH_TERMS, URGENT_TERMS

# Default weights (can be learned — see calibrate_from_data)
DEFAULT_WEIGHTS: dict = {
    "urgent_terms": 3.0,
    "high_terms": 1.5,
    "sentiment_negative": 2.0,
    "customer_new": 1.0,
    "deadline_signal": 2.0,
    "vip_customer": 2.5,
}

# Deadline regex patterns (Italian)
DEADLINE_PATTERNS: List[str] = [
    r"entro il [\d]{1,2}",
    r"scadenza.*\d{4}-\d{2}-\d{2}",
    r"entro \d{1,2} giorni",
]


class PriorityScorer:
    """
    Parametric priority scorer with configurable weights.

    Bucket thresholds:
        >= 7.0  → urgent   (confidence 0.95)
        >= 4.0  → high     (confidence 0.85)
        >= 2.0  → medium   (confidence 0.75)
        <  2.0  → low      (confidence 0.70)
    """

    def __init__(self, weights: Optional[dict] = None):
        self.weights = weights if weights is not None else DEFAULT_WEIGHTS.copy()

    def score(
        self,
        subject: str,
        body_canonical: str,
        sentiment_value: str,
        customer_value: str,
        vip_status: bool = False,
    ) -> dict:
        """
        Compute priority score and bucket.

        Args:
            subject: Email subject.
            body_canonical: Canonical email body.
            sentiment_value: "positive" | "neutral" | "negative".
            customer_value: "new" | "existing" | "unknown".
            vip_status: Whether the sender is a VIP customer.

        Returns:
            {
                "value": "urgent" | "high" | "medium" | "low",
                "confidence": float,
                "signals": List[str],
                "rawscore": float,
            }
        """
        text = f"{subject} {body_canonical}".lower()
        raw_score = 0.0
        signals: List[str] = []

        # 1. Urgent terms
        urgent_count = sum(1 for term in URGENT_TERMS if term in text)
        if urgent_count > 0:
            raw_score += self.weights["urgent_terms"] * urgent_count
            signals.append(f"urgent_keywords:{urgent_count}")

        # 2. High priority terms
        high_count = sum(1 for term in HIGH_TERMS if term in text)
        if high_count > 0:
            raw_score += self.weights["high_terms"] * high_count
            signals.append(f"high_keywords:{high_count}")

        # 3. Sentiment
        if sentiment_value == "negative":
            raw_score += self.weights["sentiment_negative"]
            signals.append("negative_sentiment")

        # 4. Customer status
        if customer_value == "new":
            raw_score += self.weights["customer_new"]
            signals.append("new_customer")

        # 5. Deadline
        deadline_boost = self._extract_deadline_signals(text)
        if deadline_boost > 0:
            raw_score += self.weights["deadline_signal"] * deadline_boost
            signals.append("deadline_mentioned")

        # 6. VIP
        if vip_status:
            raw_score += self.weights["vip_customer"]
            signals.append("vip_customer")

        # Bucketing
        if raw_score >= 7.0:
            priority_val = "urgent"
            confidence = 0.95
        elif raw_score >= 4.0:
            priority_val = "high"
            confidence = 0.85
        elif raw_score >= 2.0:
            priority_val = "medium"
            confidence = 0.75
        else:
            priority_val = "low"
            confidence = 0.70

        return {
            "value": priority_val,
            "confidence": confidence,
            "signals": signals,
            "rawscore": raw_score,
        }

    def _extract_deadline_signals(self, text: str) -> int:
        """
        Detect mentions of imminent deadlines in text.

        Returns:
            Urgency boost (0 = none, 2 = deadline found).
        """
        for pattern in DEADLINE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return 2
        return 0

    def calibrate_from_data(self, training_data) -> None:
        """
        ★FEATURE★ Learn optimal weights from historical data with logistic regression.

        TODO: Implement with sklearn.linear_model.LogisticRegression.
        training_data: DataFrame with features + priority_true column.
        """
        pass


# Module-level default scorer instance
priority_scorer = PriorityScorer()
