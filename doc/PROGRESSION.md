# PROGRESSION.md — Post-Processing & Enrichment Layer

**Ultimo aggiornamento**: 24 Febbraio 2026  
**Status globale**: 🟡 In corso — Fase 0/1 Scaffolding + MVP

---

## Fase 0 — Scaffolding & Infrastruttura
| # | Task | Status | Note |
|---|------|--------|------|
| 0.1 | Creare struttura directory src/ tests/ scripts/ config/ | 🔴 | Come da piano |
| 0.2 | pyproject.toml con dipendenze | 🔴 | |
| 0.3 | .env.example | 🔴 | |
| 0.4 | Dockerfile + docker-compose.yml | 🔴 | |
| 0.5 | Download spaCy it_core_news_lg | 🔴 | Runtime dependency |

## Fase 1 — MVP: Core Post-Processing Pipeline
| # | Task | Status | Note |
|---|------|--------|------|
| 1.1 | Data Models (PipelineVersion, EmailDocument, Entity, ValidationResult, KeywordObservation) + Config (TOPICS_ENUM, schemas) | 🔴 | src/models/ + src/config/ |
| 1.2 | Validation & Normalization (validate_llm_output_multistage, deduplicate_and_normalize, verify_evidence_quotes, enforce_evidence_policy) | 🔴 | FIX #6, #7 inclusi |
| 1.3 | Keyword Resolution from Catalog (resolve_keywords_from_catalog) | 🔴 | FIX #1 |
| 1.4 | Customer Status Deterministico (compute_customer_status, crm_lookup_mock) | 🔴 | 5 livelli match |
| 1.5 | Priority Scoring Rule-Based (PriorityScorer) | 🔴 | Pesi default, bucketing |
| 1.6 | Confidence Adjustment (compute_topic_confidence_adjusted, adjust_all_topic_confidences, build_collision_index placeholder) | 🔴 | FIX #2 |
| 1.7 | Entity Extraction Document-Level (regex + NER + lexicon + merge) | 🔴 | FIX #3 |
| 1.8 | Output Normalization (normalize_topics_keywords, build_triage_output_schema) | 🔴 | FIX #4 |
| 1.9 | Pipeline Orchestrator (postprocess_and_enrich) | 🔴 | 7-stage flow |
| 1.10 | Observation Storage (build_observations) | 🔴 | |
| 1.11 | Unit Tests completi | 🔴 | Target coverage ≥80% |
| 1.12 | Integration Tests (e2e + determinism) | 🔴 | |

## Fase 2 — Dictionary Management & Promoter
| # | Task | Status | Note |
|---|------|--------|------|
| 2.1 | DB Models (label_registry, lexicon_entries, keyword_observations) | 🔴 | SQLAlchemy |
| 2.2 | Keyword Promoter (KeywordPromoter class) | 🔴 | Soglie configurabili |
| 2.3 | Collision Index Reale (build_collision_index_from_db) | 🔴 | Sostituisce placeholder |
| 2.4 | Dictionary Versioning (freeze in-run, X+1 end-of-run) | 🔴 | |
| 2.5 | Batch Job dictionary_update.py | 🔴 | Nightly |

## Fase 3 — Ingestion, LLM Client & API
| # | Task | Status | Note |
|---|------|--------|------|
| 3.1 | Email Ingestion (parser, canonicalization, document builder) | 🔴 | RFC5322, MIME |
| 3.2 | Candidate Generation (tokenizer, ngrams, KeyBERT, filters, safe_lemmatize) | 🔴 | FIX #5 |
| 3.3 | LLM Client (prompt_builder, call_llm_openrouter, retry, instructor/tool calling) | 🔴 | v3 tool calling |
| 3.4 | FastAPI API (POST /triage, GET /health, Pydantic schemas) | 🔴 | |

## Fase 4 — Advanced Features & Production Hardening
| # | Task | Status | Note |
|---|------|--------|------|
| 4.1 | PII Redaction (redact_pii) | 🔴 | GDPR |
| 4.2 | Evaluation Framework (metrics, drift_detection, backtesting) | 🔴 | |
| 4.3 | Learned Priority Weights (LogisticRegression) | 🔴 | |
| 4.4 | CRM Integration Reale | 🔴 | Sostituisce mock |
| 4.5 | Monitoring & Alerting (Grafana, thresholds) | 🔴 | |
| 4.6 | A/B Testing Framework | 🔴 | |
| 4.7 | Docker & CI/CD | 🔴 | |

---

## Legenda
- 🔴 Non iniziato
- 🟡 In corso
- 🟢 Completato
- ⚠️ Bloccato

## Fix Critici Tracciati (v3.3)
| Fix | Descrizione | Task correlato | Status |
|-----|-------------|----------------|--------|
| FIX #1 | Keyword reference-only (resolve_keywords_from_catalog) | 1.3 | 🔴 |
| FIX #2 | Confidence naming (confidence_llm / confidence_adjusted) | 1.6 | 🔴 |
| FIX #3 | Entity extraction document-level (rimosso labelid) | 1.7 | 🔴 |
| FIX #4 | Mapping keywordsintext → keywords | 1.8 | 🔴 |
| FIX #5 | Safe lemmatization (safe_lemmatize) | 3.2 | 🔴 |
| FIX #6 | Auto-repair count mismatch | 1.2 | 🔴 |
| FIX #7 | Evidence verification rafforzata | 1.2 | 🔴 |

## Note di Contesto
- Schema LLM v3.3: keywordsintext richiede SOLO candidateid
- Output schema: usa "keywords" (non "keywordsintext")
- Firma extract_all_entities(): NO parametro labelid
- confidence = alias di confidence_adjusted (retro-compat)
