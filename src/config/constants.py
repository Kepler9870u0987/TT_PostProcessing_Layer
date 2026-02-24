"""
Constants used across the pipeline.
Versioned and pinned for determinism.
"""
from typing import List, Set

# =============================================================================
# Topic Taxonomy (closed enum)
# =============================================================================
TOPICS_ENUM: List[str] = [
    "FATTURAZIONE",
    "ASSISTENZA_TECNICA",
    "RECLAMO",
    "INFO_COMMERCIALI",
    "DOCUMENTI",
    "APPUNTAMENTO",
    "CONTRATTO",
    "GARANZIA",
    "SPEDIZIONE",
    "UNKNOWN_TOPIC",
]

# =============================================================================
# Priority keyword dictionaries
# =============================================================================
URGENT_TERMS: List[str] = [
    "urgente", "bloccante", "diffida", "reclamo", "rimborso",
    "disdetta", "guasto", "fermo", "critico", "SLA",
]

HIGH_TERMS: List[str] = [
    "problema", "errore", "non funziona", "assistenza", "supporto",
]

# =============================================================================
# Stopwords (Italian) - pinned version
# =============================================================================
STOPLIST_VERSION: str = "stopwords-it-2025.2"

STOPWORDS_IT: Set[str] = {
    "grazie", "cordiali", "saluti", "buongiorno", "buonasera",
    "ciao", "distinti", "gentile", "egregio", "spett",
    "il", "lo", "la", "le", "li", "gli", "un", "uno", "una",
    "di", "del", "dello", "della", "dei", "degli", "delle",
    "a", "al", "allo", "alla", "ai", "agli", "alle",
    "da", "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "in", "nel", "nello", "nella", "nei", "negli", "nelle",
    "con", "su", "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "per", "tra", "fra",
    "e", "o", "ma", "che", "non", "se", "come", "più",
    "questo", "quello", "quale", "chi", "cui",
    "sono", "è", "era", "essere", "avere", "ha", "ho", "hanno",
    "fare", "fatto", "stato", "stati", "stata", "stati",
    "io", "tu", "lui", "lei", "noi", "voi", "loro",
    "mio", "tuo", "suo", "nostro", "vostro", "proprio",
    "anche", "ancora", "già", "poi", "dopo", "prima",
    "molto", "poco", "bene", "male", "sempre", "mai",
    "dove", "quando", "perché", "cosa", "tutto", "ogni",
    "re", "fw", "fwd",
}

# =============================================================================
# Blacklist patterns (regex) for candidate filtering
# =============================================================================
BLACKLIST_PATTERNS: List[str] = [
    r"^re:\s*",
    r"^fwd?:\s*",
    r"^\d+$",          # bare numbers
    r"^[a-z]$",        # single characters
]

# =============================================================================
# Customer status text signals (Italian)
# =============================================================================
EXISTING_CUSTOMER_SIGNALS: List[str] = [
    "ho già un contratto",
    "cliente dal",
    "vostro cliente",
    "mio account",
    "precedente ordine",
    "sono già cliente",
]

# =============================================================================
# Canonicalization
# =============================================================================
CANONICALIZATION_VERSION: str = "1.2.0"

# =============================================================================
# Evidence & quality thresholds
# =============================================================================
MIN_CONFIDENCE_WARNING: float = 0.2
MAX_TOPICS: int = 5
MAX_KEYWORDS_PER_TOPIC: int = 15
MAX_EVIDENCE_PER_TOPIC: int = 2
MAX_QUOTE_LENGTH: int = 200
