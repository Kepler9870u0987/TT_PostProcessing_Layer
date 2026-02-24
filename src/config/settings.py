"""
Environment settings loaded from .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv()


# --- LLM API ---
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")

# --- Database ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://triage:triage_password@localhost:5432/triage_db")

# --- CRM ---
CRM_API_URL: str = os.getenv("CRM_API_URL", "http://localhost:8081/api/v1")
CRM_API_TIMEOUT_MS: int = int(os.getenv("CRM_API_TIMEOUT_MS", "500"))

# --- Redis ---
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# --- NLP Models ---
SPACY_MODEL: str = os.getenv("SPACY_MODEL", "it_core_news_lg")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-mpnet-base-v2")

# --- Pipeline ---
MAX_LLM_RETRIES: int = int(os.getenv("MAX_LLM_RETRIES", "3"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
EVIDENCE_FAILURE_THRESHOLD: float = float(os.getenv("EVIDENCE_FAILURE_THRESHOLD", "0.3"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- Privacy ---
PII_REDACTION_ENABLED: bool = os.getenv("PII_REDACTION_ENABLED", "true").lower() == "true"
MAX_BODY_LOG_CHARS: int = int(os.getenv("MAX_BODY_LOG_CHARS", "500"))
