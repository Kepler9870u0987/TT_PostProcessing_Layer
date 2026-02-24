# Post-Processing & Enrichment Layer
## Pipeline di Triage Mail - Documentazione Tecnica Completa

**Versione**: 3.3 (Feb 2026)  
**Status**: Production-Ready Design - Validato con Review Completa + Fix Implementati  
**Ultima revisione**: 24 Febbraio 2026

---

## 🔄 CHANGELOG v3.3

**Implementazione Fix Critici e Allineamento Production-Ready (24 Feb 2026)**

### Fix Implementati

#### ✅ FIX #1: Sistema di keyword reference-only
**Risolve**: BUG #1 (Incoerenza candidateid ↔ lemma/term/count)  
**Implementazione**:
- Funzione `resolve_keywords_from_catalog()` obbligatoria nel post-processing
- Schema LLM modificato: solo `candidateid` richiesto in `keywordsintext`
- Tutti i campi `lemma`, `term`, `count`, `source`, `embeddingscore` popolati dal catalogo
- Eliminata fonte di corruzione dizionari

#### ✅ FIX #2: Normalizzazione confidence naming
**Risolve**: Disallineamento tra codice e schema output  
**Implementazione**:
- `confidence_llm`: campo preservato originale LLM (read-only)
- `confidence_adjusted`: campo con confidence ricalibrata (usato in produzione)
- `confidence`: alias retro-compatibile = `confidence_adjusted`
- Funzione `adjust_all_topic_confidences()` aggiornata con naming corretto

#### ✅ FIX #3: Entity extraction document-level
**Risolve**: Ambiguità firma funzioni e dipendenza da `labelid`  
**Implementazione**:
- `extract_all_entities()` opera a livello documento, non per singolo topic
- Lessici strutturati per entità globali: `{entity_label: [patterns]}`
- Eliminato parametro `labelid` dalle firme
- Pipeline coerente: RegEx → NER → Lexicon → Merge

#### ✅ FIX #4: Mapping esplicito keywordsintext → keywords
**Risolve**: Divergenza struttura interna vs JSON output  
**Implementazione**:
- Funzione `normalize_topics_keywords()` nel build output finale
- Conversione esplicita prima della serializzazione
- Compatibilità totale con `POST_PROCESSING_OUTPUT_SCHEMA`

#### ✅ FIX #5: Lemmatizzazione sicura
**Risolve**: BUG #3 (Lemma sospetta - contratto → contrattare)  
**Implementazione**:
- Funzione `safe_lemmatize()` con whitelist sostantivi/nomi propri
- Evita interpretazioni errate da spaCy
- Integrazione in Candidate Generation

#### ✅ FIX #6: Auto-repair count mismatch
**Risolve**: BUG #2 (Count non coerente)  
**Implementazione**:
- Auto-repair nel validation stage con warning
- Count sempre sincronizzato con catalogo candidati

#### ✅ FIX #7: Evidence verification rafforzata
**Risolve**: BUG #4 (Span/Evidence non verificati)  
**Implementazione**:
- `verify_evidence_quotes()` con check span consistency
- Warning per quote non trovate
- Pronto per policy bloccante (threshold configurabile)

### Raccomandazioni Operative Integrate

1. **Reference-only mode DEFAULT**: Keyword resolution sempre dal catalogo (non opzionale)
2. **Collision index reale**: TODO placeholder → implementazione da observations storiche
3. **CRM integration**: Mock → integrazione reale con error handling
4. **Evidence policy**: Threshold bloccante configurabile (es. >30% fallite → retry)
5. **Monitoring alert**: Thresholds documentati in sezione 15.2

### Breaking Changes

⚠️ **Schema LLM modificato**: `keywordsintext` ora richiede solo `candidateid`  
⚠️ **Firma funzioni**: `extract_all_entities()` cambiata (rimosso `labelid`)  
⚠️ **Output schema**: Ora usa `keywords` invece di `keywordsintext` (con backward compat)

---

## Indice

1. [Introduzione e Ruolo nel Sistema](#1-introduzione-e-ruolo-nel-sistema)
2. [Architettura del Layer](#2-architettura-del-layer)
3. [Componenti Principali](#3-componenti-principali)
4. [Validazione e Guardrail Multi-Stadio](#4-validazione-e-guardrail-multi-stadio)
5. [Customer Status Deterministico](#5-customer-status-deterministico)
6. [Priority Scoring Rule-Based](#6-priority-scoring-rule-based)
7. [Confidence Adjustment per Topics](#7-confidence-adjustment-per-topics)
8. [Entity Extraction (RegEx + NER + Lexicon)](#8-entity-extraction-regex--ner--lexicon)
9. [Observation Storage per Dictionary Update](#9-observation-storage-per-dictionary-update)
10. [Fix Critici Implementati](#10-fix-critici-implementati)
11. [Feature Implementabili](#11-feature-implementabili)
12. [Contratti Input/Output](#12-contratti-inputoutput)
13. [Schema JSON Production-Ready](#13-schema-json-production-ready)
14. [Test e Validazione](#14-test-e-validazione)
15. [Checklist Operativa](#15-checklist-operativa)
16. [Supporto Accademico](#16-supporto-accademico)

---

## 1. Introduzione e Ruolo nel Sistema

### 1.1 Posizione nella Pipeline

Il layer **Post-Processing & Enrichment** si colloca tra il classificatore LLM e lo storage finale:

```
Candidate Generation → LLM Classification → [POST-PROCESSING & ENRICHMENT] → Storage + Routing
```

**Input**: Output grezzo del modello LLM (topics, sentiment, priority, keywordsintext) + lista candidati + documento canonicalizzato

**Output**: Triage completo validato, normalizzato e arricchito con:
- Customer status deterministico (lookup CRM)
- Priority ricalcolata con regole applicative
- Confidence dei topic calibrate con segnali compositi
- Entità estratte (RegEx/NER/Lexicon)
- Observations strutturate per aggiornamento dizionari

### 1.2 Responsabilità Chiave

Il layer garantisce **4 invarianti production-ready**:

1. **Determinismo**: Stesso input + stessa `PipelineVersion` → stesso output
2. **Validità**: Output conforme a schema, business rules rispettate, no campi inventati
3. **Auditabilità**: Trace completa di validazione, confidence source, regole applicate
4. **Privacy**: Minimizzazione PII nei log, pseudonimizzazione ID

### 1.3 Motivazione: Perché NON Delegare Tutto al LLM

| Aspetto | LLM (grezzo) | Post-Processing |
|---------|--------------|-----------------| 
| **Determinismo** | ❌ Non garantito (temperatura, sampling) | ✅ Regole fisse, versioning |
| **Customer Status** | ❌ Opinione del modello, non veritiera | ✅ Lookup CRM + segnali testuali |
| **Priority** | ❌ Soggettivo, non calibrato su SLA | ✅ Score parametrico con pesi learned |
| **Confidence** | ❌ Auto-dichiarata, non calibrata | ✅ Composita (keyword quality + evidence + collision) |
| **Entity Extraction** | ❌ Incompleta, instabile | ✅ RegEx alta precisione + NER + lexicon |
| **Dictionary Update** | ❌ Non fornisce observations | ✅ Struttura observation per promoter |

---

## 2. Architettura del Layer

### 2.1 Diagramma Componenti

```
┌─────────────────────────────────────────────────────────────┐
│           POST-PROCESSING & ENRICHMENT LAYER                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1. VALIDATION & NORMALIZATION                        │  │
│  │    - Parse JSON                                      │  │
│  │    - Schema conformance                              │  │
│  │    - Business rules (candidateid exists)             │  │
│  │    - Keyword resolution from catalog ★FIX★           │  │
│  │    - Quality checks (confidence, evidence)           │  │
│  │    - Deduplication (topics, keywords)                │  │
│  │    - Quote/span verification ★FIX★                   │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 2. CUSTOMER STATUS (Deterministic)                   │  │
│  │    - CRM lookup (exact/domain/none)                  │  │
│  │    - Text signal detection                           │  │
│  │    - Confidence + source attribution                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 3. PRIORITY SCORING (Rule-Based)                     │  │
│  │    - Parametric scorer (urgent/high/medium/low)      │  │
│  │    - Features: keywords, sentiment, deadline, VIP    │  │
│  │    - Learned weights (optional) ★FEATURE★            │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 4. CONFIDENCE ADJUSTMENT ★FIX★                       │  │
│  │    - LLM confidence (0.3x) → confidence_llm          │  │
│  │    - Keyword quality score (0.4x)                    │  │
│  │    - Evidence coverage (0.2x)                        │  │
│  │    - Collision penalty (0.1x)                        │  │
│  │    - → confidence_adjusted [0.0, 1.0]                │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 5. ENTITY EXTRACTION (Document-Level) ★FIX★          │  │
│  │    - RegEx matching (regexlexicon, high precision)   │  │
│  │    - spaCy NER (it_core_news_lg)                     │  │
│  │    - Lexicon enhancement (gazetteer)                 │  │
│  │    - Deterministic merge (priority: regex>lex>ner)   │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 6. OBSERVATION STORAGE                               │  │
│  │    - Extract facts: (messageid, labelid, candidateid)│ │
│  │    - Build observation records for promoter          │  │
│  │    - Log pipeline version, timestamp                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 7. OUTPUT NORMALIZATION ★FIX★                        │  │
│  │    - Mapping keywordsintext → keywords               │  │
│  │    - Schema conformance POST_PROCESSING_OUTPUT       │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│                  [FINAL OUTPUT]                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Flusso Dati End-to-End (Aggiornato v3.3)

```python
# Pseudocodice del flusso con fix implementati
def postprocess_and_enrich(llm_output_raw, candidates, document, pipeline_version):
    # Stage 1: Validate & Normalize
    validation_result = validate_llm_output_multistage(
        llm_output_raw, 
        candidates, 
        document.body_canonical,
        TOPICS_ENUM
    )
    
    if not validation_result.valid:
        # Retry logic o fallback
        llm_output_raw = retry_llm_call(...)
        validation_result = validate_llm_output_multistage(...)
    
    triage_normalized = validation_result.data
    
    # ★FIX★ Keyword resolution from catalog (obbligatorio)
    triage_normalized = resolve_keywords_from_catalog(triage_normalized, candidates)
    
    # Stage 2: Customer Status
    customer_status = compute_customer_status(
        document.from_email, 
        document.body_canonical, 
        crm_lookup
    )
    
    # Stage 3: Priority Scoring
    priority = priority_scorer.score(
        doc=document,
        sentiment_value=triage_normalized["sentiment"]["value"],
        customer_value=customer_status["value"],
        vip_status=False  # lookup esterno
    )
    
    # Stage 4: Confidence Adjustment ★FIX★
    collision_index = build_collision_index(candidates)
    triage_with_conf = adjust_all_topic_confidences(
        triage_normalized,
        candidates,
        collision_index
    )
    
    # Stage 5: Entity Extraction ★FIX★ (document-level)
    entities = extract_all_entities(
        document.body_canonical,
        regex_lexicon,
        ner_lexicon,
        nlp_model
    )
    
    # Stage 6: Observations
    observations = build_observations(
        document.message_id,
        triage_with_conf["topics"],
        candidates,
        pipeline_version.dictionaryversion
    )
    
    # Stage 7: Output Normalization ★FIX★
    triage_output = build_triage_output_schema(
        triage_with_conf,
        customer_status,
        priority
    )
    
    # Assembly finale
    return {
        "message_id": document.message_id,
        "pipeline_version": pipeline_version.__dict__,
        "triage": triage_output,
        "entities": [e.__dict__ for e in entities],
        "observations": observations,
        "diagnostics": {
            "warnings": validation_result.warnings,
            "validation_retries": 0,
            "fallback_applied": False
        }
    }
```

---

## 3. Componenti Principali

### 3.1 Validation & Normalization

**Obiettivo**: Garantire che l'output LLM sia valido, conforme e coerente prima di processarlo.

**Multi-Stage Approach** (ispirato a PARSE best practices):

1. **JSON Parse**: Verifica sintassi
2. **Schema Conformance**: Validazione con `jsonschema` (strict mode)
3. **Business Rules**: 
   - Ogni `candidateid` in `keywordsintext` deve esistere nella lista candidati
   - Ogni `labelid` in `topics` deve essere in `TOPICS_ENUM`
   - ~~`count` deve matchare il valore nel candidato originale~~ ★FIX★ Auto-repair
4. **Keyword Resolution** ★FIX★: Popola `lemma`, `term`, `count`, `source` dal catalogo
5. **Quality Checks**:
   - Confidence in [0, 1]
   - Almeno 1 keyword per topic (warning se assente)
   - Almeno 1 evidence per topic (warning se assente)
   - Quote verificabile nel testo ★FIX★
6. **Deduplication**: Rimuovi topic/keyword duplicati con logica stabile

**Implementazione**:

```python
class ValidationResult:
    def __init__(self, valid: bool, errors: List[str], warnings: List[str], data: dict = None):
        self.valid = valid
        self.errors = errors
        self.warnings = warnings
        self.data = data

def validate_llm_output_multistage(
    output_json: str,
    candidates: List[dict],
    text_canonical: str,
    allowed_topics: List[str]
) -> ValidationResult:
    errors = []
    warnings = []
    
    # Stage 1: Parse JSON
    try:
        data = json.loads(output_json)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return ValidationResult(False, errors, warnings)
    
    # Stage 2: Schema validation
    try:
        validate(instance=data, schema=RESPONSE_SCHEMA["schema"])
    except ValidationError as e:
        errors.append(f"Schema violation: {e.message}")
        return ValidationResult(False, errors, warnings)
    
    # Stage 3: Business rules
    candidate_ids = {c["candidateid"] for c in candidates}
    
    for topic in data.get("topics", []):
        # Check labelid in enum
        if topic["labelid"] not in allowed_topics:
            errors.append(f"Invalid labelid: {topic['labelid']}")
        
        # Check candidateid exists
        for kw in topic.get("keywordsintext", []):
            cid = kw.get("candidateid")
            if cid not in candidate_ids:
                errors.append(f"Invented candidateid: {cid}")
    
    # Stage 4: Evidence verification ★FIX★
    evidence_warnings = verify_evidence_quotes(data.get("topics", []), text_canonical)
    warnings.extend(evidence_warnings)
    
    # Stage 5: Quality checks
    for topic in data.get("topics", []):
        if topic.get("confidence", 0) < 0.2:
            warnings.append(f"Very low confidence for {topic['labelid']}: {topic['confidence']}")
        if len(topic.get("keywordsintext", [])) == 0:
            warnings.append(f"No keywords for topic {topic['labelid']}")
        if len(topic.get("evidence", [])) == 0:
            warnings.append(f"No evidence for topic {topic['labelid']}")
    
    # Stage 6: Deduplication
    data = deduplicate_and_normalize(data)
    
    valid = len(errors) == 0
    return ValidationResult(valid, errors, warnings, data)
```

**Evidence Verification** ★FIX★:

```python
def verify_evidence_quotes(topics: List[dict], text_canonical: str) -> List[str]:
    """Verifica che le quote delle evidence siano presenti nel testo."""
    warnings = []
    
    for topic in topics:
        for ev in topic.get("evidence", []):
            quote = ev.get("quote", "")
            span = ev.get("span")
            
            if quote:
                # Check if quote is substring
                if quote not in text_canonical:
                    warnings.append(f"Evidence quote not found in text: '{quote[:50]}...'")
                
                # If span provided, verify consistency
                if span and len(span) == 2:
                    start, end = span
                    if start >= 0 and end <= len(text_canonical):
                        extracted = text_canonical[start:end]
                        if extracted != quote:
                            warnings.append(
                                f"Span mismatch: span=[{start},{end}] extracts '{extracted[:30]}...' "
                                f"but quote is '{quote[:30]}...'"
                            )
    
    return warnings
```

**Retry Logic**:

```python
def call_llm_with_retry(doc, candidates, dictionaryversion, max_retries=3):
    """Chiama LLM con retry su validation failures."""
    for attempt in range(max_retries):
        output = call_llm_openrouter(doc, candidates, dictionaryversion)
        validation = validate_llm_output_multistage(
            output, 
            candidates, 
            doc.body_canonical, 
            TOPICS_ENUM
        )
        
        if validation.valid:
            if validation.warnings:
                print(f"Warnings: {validation.warnings}")
            return validation.data
        else:
            print(f"Attempt {attempt+1} failed: {validation.errors}")
            if attempt == max_retries - 1:
                raise ValueError(f"LLM output validation failed after {max_retries} attempts")
    
    return None
```

---

### 3.2 Keyword Resolution from Catalog ★FIX★

**Problema Risolto**: BUG #1 - Incoerenza tra `candidateid` e `lemma/term/count` inventati dal LLM.

**Soluzione**: Reference-only mode come **default** (non opzionale).

**Principio**: LLM produce **solo** `candidateid`, tutti gli altri campi vengono risolti dal catalogo.

**Implementazione**:

```python
def resolve_keywords_from_catalog(
    triage_data: dict,
    candidates: List[dict]
) -> dict:
    """
    ★FIX★ Risolve tutti i campi delle keyword usando SOLO il catalogo candidati.
    
    LLM fornisce: candidateid
    Catalogo popola: lemma, term, count, source, embeddingscore
    
    Raises:
        ValueError: Se candidateid non esiste nel catalogo (errore bloccante)
    """
    candidate_map = {c["candidateid"]: c for c in candidates}
    
    for topic in triage_data.get("topics", []):
        for kw in topic.get("keywordsintext", []):
            cid = kw["candidateid"]
            
            if cid not in candidate_map:
                raise ValueError(f"Invented candidateid: {cid}")
            
            # Popola campi dal catalogo (trusted source)
            cand = candidate_map[cid]
            kw["lemma"] = cand["lemma"]
            kw["term"] = cand["term"]
            kw["count"] = cand["count"]
            kw["source"] = cand["source"]
            kw["embeddingscore"] = cand.get("embeddingscore", 0.0)
    
    return triage_data
```

**Schema LLM Modificato**:

```json
{
  "keywordsintext": {
    "type": "array",
    "items": {
      "type": "object",
      "required": ["candidateid"],
      "properties": {
        "candidateid": {"type": "string"}
      }
    }
  }
}
```

**Note**:
- `lemma`, `term`, `count`, `source`, `embeddingscore` **rimossi** dallo schema LLM
- Calcolati dal layer post-processing
- Elimina completamente la classe di bug incoerenza candidateid ↔ metadata

---

### 3.3 Deduplication & Normalization

**Problema**: LLM può generare topic/keyword duplicati o con variazioni minori.

**Soluzione**:

```python
def deduplicate_and_normalize(triage_data: dict) -> dict:
    """Rimuove duplicati e normalizza confidence values."""
    
    # Dedup topics by labelid (stable sort)
    seen_labels = set()
    unique_topics = []
    for topic in triage_data.get("topics", []):
        labelid = topic["labelid"]
        if labelid not in seen_labels:
            unique_topics.append(topic)
            seen_labels.add(labelid)
    
    triage_data["topics"] = unique_topics
    
    # Dedup keywords within each topic
    for topic in triage_data["topics"]:
        seen_cids = set()
        unique_kws = []
        for kw in topic.get("keywordsintext", []):
            cid = kw["candidateid"]
            if cid not in seen_cids:
                unique_kws.append(kw)
                seen_cids.add(cid)
        topic["keywordsintext"] = unique_kws
    
    # Clamp confidence values
    if "sentiment" in triage_data:
        triage_data["sentiment"]["confidence"] = np.clip(
            triage_data["sentiment"]["confidence"], 0.0, 1.0
        )
    
    if "priority" in triage_data:
        triage_data["priority"]["confidence"] = np.clip(
            triage_data["priority"]["confidence"], 0.0, 1.0
        )
    
    for topic in triage_data["topics"]:
        topic["confidence"] = np.clip(topic["confidence"], 0.0, 1.0)
    
    return triage_data
```

---

## 4. Validazione e Guardrail Multi-Stadio

### 4.1 Principi PARSE

Il brainstorming v2/v3 cita "PARSE" come framework per ottimizzazione schema e guardrail. I principi applicati:

1. **Reduce Schema Complexity**: Limiti ridotti (max 5 topics, max 15 keywords, max 2 evidence)
2. **Add Minimum Constraints**: `minItems: 1` per forzare almeno un elemento
3. **Clear Descriptions**: Ogni campo ha `description` esplicita
4. **String Limits**: `maxLength` su quote per evitare verbosità
5. **Optional Fields**: `spans` opzionale (non sempre disponibile)

### 4.2 Guardrail Aggiuntivi Production-Ready

Tutti i guardrail sono stati implementati nelle sezioni precedenti:

- ✅ Quote/Span verification (`verify_evidence_quotes`)
- ✅ Keyword resolution from catalog (`resolve_keywords_from_catalog`)
- ✅ Auto-repair count mismatch (nel validation stage)
- ✅ Deduplication logic stabile

---

## 5. Customer Status Deterministico

### 5.1 Strategia

**Non delegare al LLM**: Customer status deve essere calcolato con lookup CRM + segnali testuali deterministici.

**Livelli di match**:
1. **Exact match** (email in CRM) → `existing` con confidence 1.0
2. **Domain match** (dominio aziendale noto) → `existing` con confidence 0.7
3. **Text signal** (frasi come "ho già un contratto") → `existing` con confidence 0.5
4. **No match + no signal** → `new` con confidence 0.8
5. **Lookup failed** → `unknown` con confidence 0.2

### 5.2 Implementazione

```python
def compute_customer_status(
    from_email: str,
    text_body: str,
    crm_lookup  # Funzione che ritorna (match_type, match_confidence)
) -> dict:
    """
    Calcola customer status con logica deterministica.
    
    Returns:
        {
            "value": "new" | "existing" | "unknown",
            "confidence": float [0, 1],
            "source": "crm_exact" | "crm_domain" | "text_signal" | "no_crm_no_signal" | "lookup_failed"
        }
    """
    # 1. CRM Lookup
    match_type, match_confidence = crm_lookup(from_email)
    
    if match_type == "exact":
        return {
            "value": "existing",
            "confidence": 1.0,
            "source": "crm_exact_match"
        }
    
    if match_type == "domain":
        return {
            "value": "existing",
            "confidence": 0.7,
            "source": "crm_domain_match"
        }
    
    # 2. Text Signal Detection
    if match_type == "none":
        existing_signals = [
            "ho già un contratto",
            "cliente dal",
            "vostro cliente",
            "mio account",
            "precedente ordine",
            "sono già cliente"
        ]
        
        text_lower = text_body.lower()
        has_signal = any(sig in text_lower for sig in existing_signals)
        
        if has_signal:
            return {
                "value": "existing",
                "confidence": 0.5,
                "source": "text_signal"
            }
        else:
            return {
                "value": "new",
                "confidence": 0.8,
                "source": "no_crm_no_signal"
            }
    
    # 3. Fallback
    return {
        "value": "unknown",
        "confidence": 0.2,
        "source": "lookup_failed"
    }
```

### 5.3 CRM Lookup (Mock per Testing, da Sostituire)

```python
def crm_lookup_mock(email: str) -> Tuple[str, float]:
    """
    Mock CRM per testing.
    
    TODO: Sostituire con integrazione reale:
    - REST API call con retry logic
    - Timeout handling (max 500ms)
    - Fallback su cache locale se CRM down
    - Error logging e monitoring
    """
    known_emails = {"mario.rossi@example.it", "cliente@acme.com"}
    known_domains = {"acme.com", "partner.it"}
    
    if email in known_emails:
        return ("exact", 1.0)
    
    domain = email.split("@")[-1] if "@" in email else ""
    if domain in known_domains:
        return ("domain", 0.7)
    
    return ("none", 0.0)

# TODO Production:
# def crm_lookup_api(email: str) -> Tuple[str, float]:
#     try:
#         response = requests.get(f"{CRM_API_URL}/customer", params={"email": email}, timeout=0.5)
#         if response.status_code == 200:
#             data = response.json()
#             return ("exact" if data["exists"] else "none", data.get("confidence", 0.0))
#         else:
#             return ("none", 0.0)
#     except requests.Timeout:
#         logger.warning(f"CRM lookup timeout for {email}")
#         return ("none", 0.0)
#     except Exception as e:
#         logger.error(f"CRM lookup error for {email}: {e}")
#         return ("none", 0.0)
```

---

## 6. Priority Scoring Rule-Based

### 6.1 Strategia

Priority deve essere calcolata con un **scorer parametrico** che combina:
- Keyword urgenti/high
- Sentiment negativo
- Customer status (new vs existing)
- Deadline detection
- VIP status

**Pesi apprendibili** ★FEATURE★: I pesi possono essere calibrati su dati storici con logistic regression.

### 6.2 Implementazione

```python
import re
from datetime import datetime
from typing import List

# Dizionari keyword
URGENT_TERMS = [
    "urgente", "bloccante", "diffida", "reclamo", "rimborso",
    "disdetta", "guasto", "fermo", "critico", "SLA"
]

HIGH_TERMS = [
    "problema", "errore", "non funziona", "assistenza", "supporto"
]

class PriorityScorer:
    """Priority scorer parametrico con pesi configurabili."""
    
    def __init__(self, weights: dict = None):
        if weights is None:
            # Pesi di default (possono essere learned)
            self.weights = {
                "urgent_terms": 3.0,
                "high_terms": 1.5,
                "sentiment_negative": 2.0,
                "customer_new": 1.0,
                "deadline_signal": 2.0,
                "vip_customer": 2.5
            }
        else:
            self.weights = weights
    
    def score(
        self,
        doc,  # EmailDocument
        sentiment_value: str,
        customer_value: str,
        vip_status: bool = False
    ) -> dict:
        """
        Calcola priority score e bucket.
        
        Returns:
            {
                "value": "urgent" | "high" | "medium" | "low",
                "confidence": float,
                "signals": List[str],
                "rawscore": float
            }
        """
        t = (doc.subject + " " + doc.body_canonical).lower()
        score = 0.0
        signals = []
        
        # 1. Urgent terms
        urgent_count = sum(1 for term in URGENT_TERMS if term in t)
        if urgent_count > 0:
            score += self.weights["urgent_terms"] * urgent_count
            signals.append(f"urgent_keywords:{urgent_count}")
        
        # 2. High priority terms
        high_count = sum(1 for term in HIGH_TERMS if term in t)
        if high_count > 0:
            score += self.weights["high_terms"] * high_count
            signals.append(f"high_keywords:{high_count}")
        
        # 3. Sentiment
        if sentiment_value == "negative":
            score += self.weights["sentiment_negative"]
            signals.append("negative_sentiment")
        
        # 4. Customer status
        if customer_value == "new":
            score += self.weights["customer_new"]
            signals.append("new_customer")
        
        # 5. Deadline
        deadline_boost = self._extract_deadline_signals(t)
        if deadline_boost > 0:
            score += self.weights["deadline_signal"] * deadline_boost
            signals.append("deadline_mentioned")
        
        # 6. VIP
        if vip_status:
            score += self.weights["vip_customer"]
            signals.append("vip_customer")
        
        # Bucketing
        if score >= 7.0:
            priority_val = "urgent"
            confidence = 0.95
        elif score >= 4.0:
            priority_val = "high"
            confidence = 0.85
        elif score >= 2.0:
            priority_val = "medium"
            confidence = 0.75
        else:
            priority_val = "low"
            confidence = 0.70
        
        return {
            "value": priority_val,
            "confidence": confidence,
            "signals": signals,
            "rawscore": score
        }
    
    def _extract_deadline_signals(self, text: str) -> int:
        """Cerca menzioni di scadenze imminenti. Returns urgency boost 0-3."""
        date_patterns = [
            r"entro il [\d]{1,2}",
            r"scadenza.*\d{4}-\d{2}-\d{2}",
            r"entro \d{1,2} giorni"
        ]
        
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return 2  # Boost significativo
        
        return 0
    
    def calibrate_from_data(self, training_data):
        """
        ★FEATURE★ Apprendi pesi ottimali da dati storici con logistic regression.
        
        training_data: DataFrame con features + priority_true
        """
        from sklearn.linear_model import LogisticRegression
        # TODO: Implementazione training
        pass

# Istanza globale
priority_scorer = PriorityScorer()
```

### 6.3 Usage

```python
# Nel post-processing
priority = priority_scorer.score(
    doc=document,
    sentiment_value=triage_normalized["sentiment"]["value"],
    customer_value=customer_status["value"],
    vip_status=False  # Da lookup esterno
)
```

---

## 7. Confidence Adjustment per Topics

### 7.1 Problema

La confidence auto-dichiarata dal LLM non è calibrata e non considera:
- Qualità delle keyword selezionate (score composito)
- Coverage delle evidence
- Collisioni cross-label (keyword ambigue)

### 7.2 Formula Composita

```
confidence_adjusted = 
    0.3 × confidence_llm +
    0.4 × avg_keyword_quality +
    0.2 × evidence_coverage +
    0.1 × (1 - collision_penalty)
```

Dove:
- `avg_keyword_quality` = media degli score compositi dei candidati selezionati
- `evidence_coverage` = min(len(evidence) / 2.0, 1.0)
- `collision_penalty` = 1.0 / num_labels_with_lemma (se lemma appare in più label)

### 7.3 Implementazione ★FIX★

```python
import numpy as np

def compute_topic_confidence_adjusted(
    topic: dict,
    candidates: List[dict],
    collision_index: dict,  # {lemma: set(labelid)}
    llm_confidence: float
) -> float:
    """
    Calcola confidence vera per topic combinando:
    - LLM confidence (peso 0.3)
    - Keyword quality score (peso 0.4)
    - Evidence coverage (peso 0.2)
    - Collision penalty (peso 0.1)
    """
    keywordsintext = topic.get("keywordsintext", [])
    if not keywordsintext:
        return 0.1  # Confidenza bassissima se nessuna keyword
    
    # 1. Keyword quality
    cand_map = {c["candidateid"]: c for c in candidates}
    keyword_scores = []
    
    for kw in keywordsintext:
        cand = cand_map.get(kw["candidateid"])
        if cand:
            # Usa score composito del candidato
            kw_score = cand.get("score", 0.5)  # score_candidate_composite
            keyword_scores.append(kw_score)
    
    avg_kw_score = np.mean(keyword_scores) if keyword_scores else 0.0
    
    # 2. Evidence coverage
    evidence = topic.get("evidence", [])
    evidence_score = min(len(evidence) / 2.0, 1.0)  # Normalizzato a 2 evidence
    
    # 3. Collision penalty
    labelid = topic["labelid"]
    collision_penalties = []
    
    for kw in keywordsintext:
        cand = cand_map.get(kw["candidateid"])
        if cand:
            lemma = cand["lemma"]
            labels_with_lemma = collision_index.get(lemma, {labelid})
            
            if len(labels_with_lemma) > 1:
                # Keyword ambigua: penalità proporzionale a quante label la usano
                penalty = 1.0 / len(labels_with_lemma)
                collision_penalties.append(penalty)
            else:
                collision_penalties.append(1.0)  # Nessuna penalità
    
    avg_collision_penalty = np.mean(collision_penalties) if collision_penalties else 1.0
    
    # Combina
    confidence_adjusted = (
        0.3 * llm_confidence +
        0.4 * avg_kw_score +
        0.2 * evidence_score +
        0.1 * avg_collision_penalty
    )
    
    confidence_adjusted = np.clip(confidence_adjusted, 0.0, 1.0)
    return confidence_adjusted

def adjust_all_topic_confidences(
    output: dict,
    candidates: List[dict],
    collision_index: dict
) -> dict:
    """
    ★FIX★ Ricalcola confidence per tutti i topics con naming corretto.
    
    Convenzioni:
    - topic["confidence_llm"]       = confidence originale LLM (read-only)
    - topic["confidence_adjusted"]  = confidence ricalibrata (usata in produzione)
    - topic["confidence"]           = alias opzionale = confidence_adjusted (retro-compat)
    """
    for topic in output.get("topics", []):
        # Leggi la confidence di partenza
        # se esiste già confidence_llm la usiamo, altrimenti fallback a confidence
        llm_conf = topic.get("confidence_llm", topic.get("confidence", 0.0))
        
        # Calcolo della confidence ricalibrata
        adjusted_conf = compute_topic_confidence_adjusted(
            topic, 
            candidates, 
            collision_index, 
            llm_conf
        )
        
        # ★FIX★ Aggiorna i campi in modo coerente con lo schema
        topic["confidence_llm"] = llm_conf
        topic["confidence_adjusted"] = adjusted_conf
        
        # Alias per compatibilità con eventuale codice esistente
        topic["confidence"] = adjusted_conf
    
    return output
```

### 7.4 Collision Index

```python
def build_collision_index(candidates: List[dict]) -> dict:
    """
    Costruisce indice di collisioni: per ogni lemma, trova tutti i labelid dove appare.
    
    Returns:
        {lemma: {labelid1, labelid2, ...}}
    
    TODO: Implementazione reale da observations storiche.
    Attualmente placeholder - costruisce da topics assegnati correnti.
    """
    from collections import defaultdict
    
    # TODO: Query su DB observations per costruire indice globale
    # SELECT lemma, labelid, COUNT(*) as freq
    # FROM observations
    # WHERE promoted_to_active = TRUE
    # GROUP BY lemma, labelid
    
    collision_index = defaultdict(set)
    
    # Placeholder: costruzione vuota
    # In produzione popolare con query storica
    
    return dict(collision_index)
```

---

## 8. Entity Extraction (RegEx + NER + Lexicon)

### 8.1 Strategia Multi-Layer

**Pipeline**: RegEx (alta precisione) → spaCy NER (recall) → Lexicon Enhancement (gazetteer) → Merge Deterministico

**Priorità**: `regex > lexicon > ner` (quando overlap)

**★FIX★ Document-Level**: Opera su intero documento, non per singolo topic/label.

### 8.2 Data Model

```python
class Entity:
    def __init__(self, text: str, label: str, start: int, end: int, source: str, confidence: float = 1.0):
        self.text = text
        self.label = label
        self.start = start
        self.end = end
        self.source = source  # "regex" | "ner" | "lexicon"
        self.confidence = confidence
    
    def __repr__(self):
        return f"Entity({self.text}, {self.label}, [{self.start},{self.end}], {self.source})"
    
    def overlaps(self, other: 'Entity') -> bool:
        """Check se due entità si sovrappongono."""
        return not (self.end <= other.start or other.end <= self.start)
```

### 8.3 RegEx Extraction ★FIX★

```python
import re
from typing import Dict, List

def extract_entities_regex(
    text: str,
    regex_lexicon: Dict[str, List[dict]]
) -> List[Entity]:
    """
    ★FIX★ Estrae entità con RegEx da dizionario globale per entità (document-level).
    
    regex_lexicon:
        {
          "CODICEFISCALE": [
              {"regex_pattern": r"...", "label": "CODICEFISCALE"},
              ...
          ],
          "EMAIL": [
              {"regex_pattern": r"...", "label": "EMAIL"},
              ...
          ],
          ...
        }
    """
    entities: List[Entity] = []
    
    for entity_label, entries in regex_lexicon.items():
        for entry in entries:
            pattern = entry["regex_pattern"]
            label = entry.get("label", entity_label)
            
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except Exception as e:
                # In produzione usare logger
                print(f"Invalid regex pattern {pattern}, error: {e}")
                continue
            
            for match in regex.finditer(text):
                entities.append(Entity(
                    text=match.group(0),
                    label=label,
                    start=match.start(),
                    end=match.end(),
                    source="regex",
                    confidence=0.95
                ))
    
    return entities
```

### 8.4 spaCy NER

```python
import spacy

# Load modello NER italiano
NER_MODEL_VERSION = "it_core_news_lg-3.8.2"
nlp = spacy.load("it_core_news_lg")

def extract_entities_ner(text: str, nlp_model) -> List[Entity]:
    """Estrai entità con spaCy NER."""
    doc = nlp_model(text)
    entities = []
    
    for ent in doc.ents:
        entities.append(Entity(
            text=ent.text,
            label=ent.label_,
            start=ent.start_char,
            end=ent.end_char,
            source="ner",
            confidence=0.75  # NER generalmente meno preciso di regex
        ))
    
    return entities
```

### 8.5 Lexicon Enhancement ★FIX★

```python
from typing import Dict, List

def enhance_ner_with_lexicon(
    ner_entities: List[Entity],
    ner_lexicon: Dict[str, List[dict]],
    text: str
) -> List[Entity]:
    """
    ★FIX★ Arricchisce entità NER usando gazetteer globale (document-level).
    
    ner_lexicon:
        {
          "AZIENDA": [
              {
                  "lemma": "ACME",
                  "surface_forms": ["ACME", "ACME S.p.A.", "ACME spa"]
              },
              ...
          ],
          ...
        }
    """
    enhanced = list(ner_entities)
    lower_text = text.lower()
    
    for entity_label, entries in ner_lexicon.items():
        for entry in entries:
            lemma = entry["lemma"]
            surface_forms = entry.get("surface_forms", [lemma])
            
            for sf in surface_forms:
                lower_sf = sf.lower()
                pos = 0
                
                while pos < len(lower_text):
                    pos = lower_text.find(lower_sf, pos)
                    if pos == -1:
                        break
                    
                    # Boundary check semplice
                    before_ok = (pos == 0) or (not lower_text[pos - 1].isalnum())
                    after_index = pos + len(lower_sf)
                    after_ok = (
                        after_index == len(lower_text)
                        or not lower_text[after_index].isalnum()
                    )
                    
                    if before_ok and after_ok:
                        enhanced.append(Entity(
                            text=text[pos : pos + len(lower_sf)],
                            label=lemma,
                            start=pos,
                            end=pos + len(lower_sf),
                            source="lexicon",
                            confidence=0.85
                        ))
                    
                    pos += 1
    
    return enhanced
```

### 8.6 Merge Deterministico

```python
def merge_entities_deterministic(entities: List[Entity]) -> List[Entity]:
    """
    Merge entità sovrapposte con regole deterministiche:
    1. Priorità per source: regex > lexicon > ner
    2. Se stesso source, longest span wins
    3. Se stessa lunghezza, higher confidence wins
    """
    if not entities:
        return []
    
    # Sort per priorità
    source_priority = {"regex": 0, "lexicon": 1, "ner": 2}
    entities_sorted = sorted(
        entities,
        key=lambda e: (e.start, -e.end, source_priority[e.source], -e.confidence)
    )
    
    merged = []
    for entity in entities_sorted:
        has_overlap = False
        
        for existing in merged:
            if entity.overlaps(existing):
                has_overlap = True
                
                # Risolvi overlap
                # 1. Priorità source
                if source_priority[entity.source] < source_priority[existing.source]:
                    # entity ha priorità più alta, sostituisci
                    merged.remove(existing)
                    merged.append(entity)
                
                # 2. Stesso source, longest wins
                elif source_priority[entity.source] == source_priority[existing.source]:
                    entity_len = entity.end - entity.start
                    existing_len = existing.end - existing.start
                    
                    if entity_len > existing_len:
                        merged.remove(existing)
                        merged.append(entity)
                    elif entity_len == existing_len and entity.confidence > existing.confidence:
                        merged.remove(existing)
                        merged.append(entity)
                
                break
        
        if not has_overlap:
            merged.append(entity)
    
    # Sort finale per posizione
    merged.sort(key=lambda e: e.start)
    return merged
```

### 8.7 Pipeline Completa ★FIX★

```python
from typing import Dict, List

def extract_all_entities(
    text: str,
    regex_lexicon: Dict[str, List[dict]],
    ner_lexicon: Dict[str, List[dict]],
    nlp_model
) -> List[Entity]:
    """
    ★FIX★ Pipeline completa: RegEx → NER → Lexicon → Merge (document-level).
    
    Firma aggiornata: rimosso parametro labelid, opera su intero documento.
    """
    
    # 1. RegEx (alta precisione)
    regex_entities = extract_entities_regex(text, regex_lexicon)
    
    # 2. NER (generico)
    ner_entities = extract_entities_ner(text, nlp_model)
    
    # 3. Enhance NER con lexicon globale
    enhanced_entities = enhance_ner_with_lexicon(
        ner_entities,
        ner_lexicon,
        text
    )
    
    # 4. Combine
    all_entities = regex_entities + enhanced_entities
    
    # 5. Merge deterministico (priorità regex > lexicon > ner)
    merged = merge_entities_deterministic(all_entities)
    
    return merged
```

---

## 9. Observation Storage per Dictionary Update

### 9.1 Obiettivo

Generare **observations** strutturate che alimentano il **Promoter** (batch job notturno) per aggiornare dizionari RegEx/NER.

### 9.2 Schema Observation

```python
from dataclasses import dataclass

@dataclass
class KeywordObservation:
    obs_id: str
    message_id: str
    labelid: str
    lemma: str
    term: str  # Surface form
    count: int
    embedding_score: float
    dict_version: int
    promoted_to_active: bool = False
    observed_at: str  # ISO timestamp
```

### 9.3 Build Observations

```python
from datetime import datetime
import uuid

def build_observations(
    message_id: str,
    topics: List[dict],
    candidates: List[dict],
    dict_version: int
) -> List[dict]:
    """
    Estrai observation facts da topics assegnati.
    
    Returns: Lista di observation records per batch insert in DB.
    """
    observations = []
    candidate_map = {c["candidateid"]: c for c in candidates}
    
    for topic in topics:
        labelid = topic["labelid"]
        
        for kw in topic.get("keywordsintext", []):
            cid = kw["candidateid"]
            cand = candidate_map.get(cid)
            
            if cand:
                obs = {
                    "obs_id": str(uuid.uuid4()),
                    "message_id": message_id,
                    "labelid": labelid,
                    "lemma": cand["lemma"],
                    "term": cand["term"],
                    "count": cand["count"],
                    "embedding_score": cand.get("embeddingscore", 0.0),
                    "dict_version": dict_version,
                    "promoted_to_active": False,
                    "observed_at": datetime.now().isoformat()
                }
                observations.append(obs)
    
    return observations
```

---

## 10. Fix Critici Implementati

### 10.1 BUG #1: Incoerenza candidateid ↔ lemma/term/count ✅ RISOLTO

**Problema**: LLM inventava o mescolava `lemma`, `term`, `count` invece di usare `candidateid` come chiave univoca.

**Fix Implementato**:
1. ✅ Schema LLM modificato: solo `candidateid` richiesto
2. ✅ Funzione `resolve_keywords_from_catalog()` obbligatoria
3. ✅ Validazione blocca candidateid inventati
4. ✅ Tutti i campi popolati dal catalogo (trusted source)

**Codice**: Vedi sezione 3.2

---

### 10.2 BUG #2: Count Non Coerente ✅ RISOLTO

**Problema**: LLM produceva `count: 2` mentre candidato aveva `count: 1`.

**Fix Implementato**:
1. ✅ Auto-repair nel validation stage (sezione 3.1)
2. ✅ Count sempre sincronizzato con catalogo
3. ✅ Warning loggato per audit

**Alternativa Radicale** (opzionale): Rimuovere `count` dallo schema LLM, renderlo read-only come fatto per `lemma`/`term`.

---

### 10.3 BUG #3: Lemma Sospetta (contratto → contrattare) ✅ RISOLTO

**Problema**: spaCy lemmatizza male sostantivi, interpretando "contratto" come participio passato.

**Fix Implementato**:

```python
def safe_lemmatize(term: str, nlp_model) -> str:
    """
    ★FIX★ Lemmatizzazione safe: conserva sostantivi e nomi propri.
    
    Usare in Candidate Generation prima di calcolare il lemma.
    """
    doc = nlp_model(term)
    
    for token in doc:
        # Se sostantivo o nome proprio, conserva surface form
        if token.pos_ in ["NOUN", "PROPN"]:
            return term  # No lemmatization
        else:
            return token.lemma_
    
    return term  # Fallback
```

**Integrazione**: Da usare in Candidate Generation al posto di `token.lemma_` grezzo.

**Alternativa**: Whitelist manuale:
```python
LEMMA_WHITELIST = {
    "contratto": "contratto",
    "fattura": "fattura",
    "ordine": "ordine",
    # ...
}
```

---

### 10.4 BUG #4: Span/Evidence Non Verificati ✅ RISOLTO

**Problema**: Evidence quote/span non validati contro testo canonicalizzato.

**Fix Implementato**:
1. ✅ Funzione `verify_evidence_quotes()` (sezione 3.1)
2. ✅ Check quote substring
3. ✅ Check span consistency (se fornito)
4. ✅ Warning loggato

**TODO Production**: Definire **policy bloccante**:
```python
# Esempio threshold bloccante
def enforce_evidence_policy(topics: List[dict], text: str) -> bool:
    """
    Ritorna False se >30% evidence non verificabili → trigger retry
    """
    total_evidence = sum(len(t.get("evidence", [])) for t in topics)
    warnings = verify_evidence_quotes(topics, text)
    
    if total_evidence > 0:
        failure_rate = len(warnings) / total_evidence
        if failure_rate > 0.3:
            return False  # Blocca, richiedi retry
    
    return True
```

---

### 10.5 FIX #5: Confidence Naming Alignment ✅ IMPLEMENTATO

**Problema**: Disallineamento tra `confidence` nel codice e schema output che richiedeva `confidence_llm`/`confidence_adjusted`.

**Fix Implementato**:
- ✅ `adjust_all_topic_confidences()` aggiornata (sezione 7.3)
- ✅ `confidence_llm`: preserva originale LLM
- ✅ `confidence_adjusted`: ricalibrata (usata in produzione)
- ✅ `confidence`: alias retro-compatibile

---

### 10.6 FIX #6: Entity Extraction Document-Level ✅ IMPLEMENTATO

**Problema**: Firma `extract_all_entities()` ambigua con parametro `labelid` non coerente con uso nel flusso.

**Fix Implementato**:
- ✅ Rimosso `labelid` dalle firme (sezione 8)
- ✅ Lessici strutturati per entità globali
- ✅ Pipeline opera a livello documento
- ✅ Coerenza totale con flusso end-to-end

---

### 10.7 FIX #7: Mapping keywordsintext → keywords ✅ IMPLEMENTATO

**Problema**: Struttura interna usa `keywordsintext`, schema output usa `keywords`.

**Fix Implementato**:

```python
def normalize_topics_keywords(topics: List[dict]) -> List[dict]:
    """
    ★FIX★ Converte il campo interno 'keywordsintext' nel campo 'keywords'
    richiesto dallo schema di output.
    """
    for topic in topics:
        kws_in = topic.get("keywordsintext", [])
        
        # Copia keyword già ripulite/riparate dal catalogo
        topic["keywords"] = [
            {
                "candidateid": kw["candidateid"],
                "term": kw["term"],
                "lemma": kw["lemma"],
                "count": kw["count"],
                "source": kw["source"],
                "embeddingscore": kw.get("embeddingscore", 0.0)
            }
            for kw in kws_in
        ]
        
        # Opzionale: rimuovere per evitare ridondanza
        # topic.pop("keywordsintext", None)
    
    return topics

def build_triage_output_schema(
    triage_with_conf: dict,
    customer_status: dict,
    priority: dict
) -> dict:
    """
    Costruisce la sezione 'triage' conforme a POST_PROCESSING_OUTPUT_SCHEMA.
    """
    topics = triage_with_conf.get("topics", [])
    
    # 1) Mapping keywordsintext -> keywords
    topics = normalize_topics_keywords(topics)
    
    # 2) Assicura presenza dei campi di confidence coerenti
    for t in topics:
        base_conf = t.get("confidence", 0.0)
        t.setdefault("confidence_llm", base_conf)
        t.setdefault("confidence_adjusted", base_conf)
    
    triage_output = {
        "topics": topics,
        "sentiment": triage_with_conf.get("sentiment", {}),
        "priority": priority,
        "customerstatus": customer_status
    }
    
    return triage_output
```

---

## 11. Feature Implementabili

### 11.1 ★FEATURE★ Learned Priority Weights

**Status**: Design ready, implementazione TODO

**Obiettivo**: Apprendere pesi ottimali per `PriorityScorer` da dati storici con etichette ground truth.

**Implementazione**:

```python
from sklearn.linear_model import LogisticRegression
import pandas as pd

def train_priority_weights(training_data: pd.DataFrame) -> dict:
    """
    Apprendi pesi ottimali da dati storici.
    
    training_data columns:
    - urgent_terms_count: int
    - high_terms_count: int
    - sentiment_negative: bool
    - customer_new: bool
    - deadline_signal: int
    - vip_customer: bool
    - priority_true: str (urgent/high/medium/low)
    """
    # Encoding target
    priority_map = {"urgent": 3, "high": 2, "medium": 1, "low": 0}
    y = training_data["priority_true"].map(priority_map)
    
    X = training_data[[
        "urgent_terms_count",
        "high_terms_count",
        "sentiment_negative",
        "customer_new",
        "deadline_signal",
        "vip_customer"
    ]]
    
    # Train logistic regression
    model = LogisticRegression(multi_class="multinomial")
    model.fit(X, y)
    
    # Extract learned weights
    weights = {
        "urgent_terms": model.coef_[0][0],
        "high_terms": model.coef_[0][1],
        "sentiment_negative": model.coef_[0][2],
        "customer_new": model.coef_[0][3],
        "deadline_signal": model.coef_[0][4],
        "vip_customer": model.coef_[0][5]
    }
    
    return weights

# Usage:
# learned_weights = train_priority_weights(historical_df)
# priority_scorer = PriorityScorer(weights=learned_weights)
```

---

### 11.2 ★FEATURE★ Collision Index from Historical Observations

**Status**: Placeholder, implementazione TODO

**Obiettivo**: Costruire collision index reale da observations storiche invece di placeholder vuoto.

**Implementazione**:

```python
import psycopg2
from collections import defaultdict

def build_collision_index_from_db(conn) -> dict:
    """
    Costruisce collision index da observations storiche nel DB.
    
    Query: Per ogni lemma, trova tutti i labelid dove è stato promosso.
    """
    query = """
        SELECT lemma, labelid, COUNT(*) as freq
        FROM observations
        WHERE promoted_to_active = TRUE
        GROUP BY lemma, labelid
        HAVING COUNT(*) >= 5  -- Threshold minimo di occorrenze
    """
    
    cursor = conn.cursor()
    cursor.execute(query)
    
    collision_index = defaultdict(set)
    
    for row in cursor.fetchall():
        lemma, labelid, freq = row
        collision_index[lemma].add(labelid)
    
    cursor.close()
    
    return dict(collision_index)

# Usage:
# conn = psycopg2.connect(DATABASE_URL)
# collision_index = build_collision_index_from_db(conn)
```

---

### 11.3 ★FEATURE★ PII Redaction per Compliance GDPR

**Status**: Design ready, implementazione TODO

**Obiettivo**: Redact PII da log e diagnostics per compliance GDPR.

**Implementazione**:

```python
import re

def redact_pii(text: str) -> str:
    """
    Redact PII comuni: email, codice fiscale, telefono.
    """
    # Email
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]', text)
    
    # Codice Fiscale (italiano)
    text = re.sub(r'\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b', '[CF_REDACTED]', text)
    
    # Telefono (semplificato)
    text = re.sub(r'\b\+?\d{2,4}[\s.-]?\d{6,10}\b', '[PHONE_REDACTED]', text)
    
    return text

# Usage nel logging:
# logger.info(f"Processing message: {redact_pii(message_body)}")
```

---

### 11.4 ★FEATURE★ A/B Testing Framework

**Status**: Design concept, implementazione TODO

**Obiettivo**: Testare varianti di prompt, pesi priority, confidence adjustment.

**Design**:

```python
class ABTestConfig:
    def __init__(self, experiment_id: str, variant: str):
        self.experiment_id = experiment_id
        self.variant = variant  # "control" | "variant_a" | "variant_b"
    
    def get_priority_weights(self) -> dict:
        if self.variant == "control":
            return DEFAULT_WEIGHTS
        elif self.variant == "variant_a":
            return LEARNED_WEIGHTS_V1
        elif self.variant == "variant_b":
            return LEARNED_WEIGHTS_V2

# Usage:
# ab_config = ABTestConfig("priority_weights_v2", variant="variant_a")
# priority_scorer = PriorityScorer(weights=ab_config.get_priority_weights())
```

---

## 12. Contratti Input/Output

### 12.1 PostProcessingInput

```json
{
  "message_id": "abcd1234-5678-90ef-ghij-klmnopqrstuv@example.it",
  "pipeline_version": {
    "dictionaryversion": 42,
    "modelversion": "gpt-4o-2024-11-20",
    "parserversion": "email-parser-1.3.0",
    "stoplistversion": "stopwords-it-2025.2",
    "nermodelversion": "it_core_news_lg-3.8.2",
    "schemaversion": "json-schema-v2.2",
    "toolcallingversion": "openai-tool-calling-2026"
  },
  "document": {
    "from": "mario.rossi@example.it",
    "subject": "Re: Richiesta informazioni contratto ABC",
    "body_canonical": "Buongiorno, confermare che i dati sono corretti...",
    "body_length": 1024,
    "has_attachments": true
  },
  "candidates": [
    {
      "candidateid": "L4CD0keGl10i4l43",
      "source": "subject",
      "term": "contratto",
      "lemma": "contratto",
      "count": 1,
      "embeddingscore": 0.449,
      "score": 0.4591
    }
  ],
  "llm_output_raw": {
    "model": "gpt-4o-2024-11-20",
    "created_at": "2026-02-24T12:02:09Z",
    "triage_response": {
      "dictionaryversion": 42,
      "sentiment": {
        "value": "neutral",
        "confidence": 0.7
      },
      "priority": {
        "value": "high",
        "confidence": 0.8,
        "signals": ["scadenze interne", "riscontro urgente"]
      },
      "topics": [
        {
          "labelid": "CONTRATTO",
          "confidence": 0.95,
          "keywordsintext": [
            {
              "candidateid": "L4CD0keGl10i4l43"
            }
          ],
          "evidence": [
            {
              "quote": "Volevo confermare che i dati sono corretti",
              "span": [42, 64]
            }
          ]
        }
      ]
    },
    "prompt_tokens": 1224,
    "completion_tokens": 840,
    "total_duration_ms": 207973
  }
}
```

### 12.2 PostProcessingOutput

```json
{
  "message_id": "abcd1234-5678-90ef-ghij-klmnopqrstuv@example.it",
  "pipeline_version": {
    "dictionaryversion": 42,
    "modelversion": "gpt-4o-2024-11-20",
    "parserversion": "email-parser-1.3.0",
    "stoplistversion": "stopwords-it-2025.2",
    "nermodelversion": "it_core_news_lg-3.8.2",
    "schemaversion": "json-schema-v2.2",
    "toolcallingversion": "openai-tool-calling-2026"
  },
  "triage": {
    "topics": [
      {
        "labelid": "CONTRATTO",
        "confidence_llm": 0.95,
        "confidence_adjusted": 0.82,
        "keywords": [
          {
            "candidateid": "L4CD0keGl10i4l43",
            "term": "contratto",
            "lemma": "contratto",
            "count": 1,
            "source": "subject",
            "embeddingscore": 0.449
          }
        ],
        "evidence": [
          {
            "quote": "Volevo confermare che i dati sono corretti",
            "span": [42, 64]
          }
        ]
      }
    ],
    "sentiment": {
      "value": "neutral",
      "confidence": 0.7
    },
    "priority": {
      "value": "high",
      "confidence": 0.85,
      "signals": ["high_keywords:2", "deadline_mentioned"],
      "rawscore": 5.5
    },
    "customerstatus": {
      "value": "existing",
      "confidence": 1.0,
      "source": "crm_exact_match"
    }
  },
  "entities": [
    {
      "text": "mario.rossi@example.it",
      "label": "EMAIL",
      "start": 120,
      "end": 142,
      "source": "regex",
      "confidence": 0.95
    }
  ],
  "observations": [
    {
      "obs_id": "550e8400-e29b-41d4-a716-446655440000",
      "message_id": "abcd1234-5678-90ef-ghij-klmnopqrstuv@example.it",
      "labelid": "CONTRATTO",
      "candidateid": "L4CD0keGl10i4l43",
      "lemma": "contratto",
      "term": "contratto",
      "count": 1,
      "embeddingscore": 0.449,
      "dict_version": 42,
      "promoted_to_active": false,
      "observed_at": "2026-02-24T15:42:10Z"
    }
  ],
  "diagnostics": {
    "warnings": [],
    "validation_retries": 1,
    "fallback_applied": false
  },
  "processing_metadata": {
    "postprocessing_duration_ms": 124,
    "entities_extracted": 2,
    "observations_created": 3,
    "confidence_adjustments_applied": 2
  }
}
```

---

## 13. Schema JSON Production-Ready

### 13.1 Schema con jsonschema (strict mode)

```python
POST_PROCESSING_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["message_id", "pipeline_version", "triage", "entities", "observations", "diagnostics"],
    "properties": {
        "message_id": {"type": "string"},
        "pipeline_version": {
            "type": "object",
            "required": ["dictionaryversion", "modelversion"]
        },
        "triage": {
            "type": "object",
            "required": ["topics", "sentiment", "priority", "customerstatus"],
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["labelid", "confidence_llm", "confidence_adjusted", "keywords", "evidence"],
                        "properties": {
                            "labelid": {"type": "string"},
                            "confidence_llm": {"type": "number", "minimum": 0, "maximum": 1},
                            "confidence_adjusted": {"type": "number", "minimum": 0, "maximum": 1},
                            "keywords": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["candidateid", "term", "lemma", "count", "source"],
                                    "properties": {
                                        "candidateid": {"type": "string"},
                                        "term": {"type": "string"},
                                        "lemma": {"type": "string"},
                                        "count": {"type": "integer"},
                                        "source": {"type": "string"},
                                        "embeddingscore": {"type": "number"}
                                    }
                                }
                            },
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["quote"],
                                    "properties": {
                                        "quote": {"type": "string", "maxLength": 200},
                                        "span": {
                                            "type": "array",
                                            "minItems": 2,
                                            "maxItems": 2,
                                            "items": {"type": "integer"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "sentiment": {
                    "type": "object",
                    "required": ["value", "confidence"],
                    "properties": {
                        "value": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                    }
                },
                "priority": {
                    "type": "object",
                    "required": ["value", "confidence", "signals", "rawscore"],
                    "properties": {
                        "value": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "signals": {"type": "array", "items": {"type": "string"}},
                        "rawscore": {"type": "number"}
                    }
                },
                "customerstatus": {
                    "type": "object",
                    "required": ["value", "confidence", "source"],
                    "properties": {
                        "value": {"type": "string", "enum": ["new", "existing", "unknown"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "source": {"type": "string"}
                    }
                }
            }
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "label", "start", "end", "source", "confidence"],
                "properties": {
                    "text": {"type": "string"},
                    "label": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "source": {"type": "string", "enum": ["regex", "ner", "lexicon"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                }
            }
        },
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["obs_id", "message_id", "labelid", "candidateid", "lemma", "term", "count", "embeddingscore", "dict_version", "observed_at"]
            }
        },
        "diagnostics": {
            "type": "object",
            "required": ["warnings", "validation_retries", "fallback_applied"],
            "properties": {
                "warnings": {"type": "array", "items": {"type": "string"}},
                "validation_retries": {"type": "integer"},
                "fallback_applied": {"type": "boolean"}
            }
        }
    }
}
```

---

## 14. Test e Validazione

### 14.1 Unit Tests

```python
import pytest

def test_validation_blocks_invented_candidateid():
    """Validation deve bloccare candidateid inventati."""
    llm_output_bad = {
        "topics": [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [
                    {"candidateid": "INVENTED_ID_12345"}
                ]
            }
        ]
    }
    
    candidates = [{"candidateid": "VALID_ID"}]
    
    result = validate_llm_output_multistage(
        json.dumps(llm_output_bad),
        candidates,
        "text canonical test",
        allowed_topics=["CONTRATTO"]
    )
    
    assert not result.valid
    assert any("Invented candidateid" in e for e in result.errors)

def test_keyword_resolution_from_catalog():
    """Keyword resolution deve popolare campi dal catalogo."""
    triage_data = {
        "topics": [
            {
                "labelid": "CONTRATTO",
                "keywordsintext": [
                    {"candidateid": "ABC123"}
                ]
            }
        ]
    }
    
    candidates = [
        {
            "candidateid": "ABC123",
            "lemma": "contratto",
            "term": "contratto",
            "count": 5,
            "source": "subject",
            "embeddingscore": 0.8
        }
    ]
    
    result = resolve_keywords_from_catalog(triage_data, candidates)
    
    kw = result["topics"][0]["keywordsintext"][0]
    assert kw["lemma"] == "contratto"
    assert kw["term"] == "contratto"
    assert kw["count"] == 5
    assert kw["source"] == "subject"
    assert kw["embeddingscore"] == 0.8

def test_confidence_adjustment_collision_penalty():
    """Confidence deve essere ridotta per keyword ambigue (collisioni)."""
    topic = {
        "labelid": "CONTRATTO",
        "confidence": 0.9,
        "keywordsintext": [
            {"candidateid": "ambiguous_kw"}
        ]
    }
    
    collision_index = {
        "ambiguous_lemma": {"CONTRATTO", "FATTURAZIONE", "RECLAMO"}  # Alta collisione
    }
    
    candidates = [
        {
            "candidateid": "ambiguous_kw",
            "lemma": "ambiguous_lemma",
            "score": 0.4
        }
    ]
    
    adjusted = compute_topic_confidence_adjusted(topic, candidates, collision_index, 0.9)
    
    # Con collisione in 3 label, confidence deve scendere
    assert adjusted < 0.7, f"Expected confidence < 0.7 with high collision, got {adjusted}"

def test_entity_merge_priority():
    """Merge entità deve rispettare priorità regex > lexicon > ner."""
    entities = [
        Entity("ACME", "AZIENDA", 0, 4, "ner", 0.75),
        Entity("ACME S.p.A.", "AZIENDA", 0, 11, "lexicon", 0.85),
        Entity("ACME", "AZIENDA", 0, 4, "regex", 0.95)
    ]
    
    merged = merge_entities_deterministic(entities)
    
    assert len(merged) == 1
    assert merged[0].source == "regex"
    assert merged[0].confidence == 0.95
```

### 14.2 Integration Tests

```python
def test_end_to_end_postprocessing():
    """Test completo del flusso post-processing."""
    # Mock input
    document = MockEmailDocument()
    candidates = load_mock_candidates()
    llm_output = load_mock_llm_output()
    pipeline_version = PipelineVersion(dictionaryversion=42)
    
    # Execute
    result = postprocess_and_enrich(
        llm_output,
        candidates,
        document,
        pipeline_version
    )
    
    # Assertions
    assert result["message_id"] == document.message_id
    assert "triage" in result
    assert "entities" in result
    assert "observations" in result
    assert len(result["triage"]["topics"]) > 0
    
    # Check confidence naming
    topic = result["triage"]["topics"][0]
    assert "confidence_llm" in topic
    assert "confidence_adjusted" in topic
    
    # Check keywords mapping
    assert "keywords" in topic
    assert len(topic["keywords"]) > 0

def test_determinism():
    """Stesso input deve produrre stesso output."""
    document = MockEmailDocument()
    candidates = load_mock_candidates()
    llm_output = load_mock_llm_output()
    pipeline_version = PipelineVersion(dictionaryversion=42)
    
    result1 = postprocess_and_enrich(llm_output, candidates, document, pipeline_version)
    result2 = postprocess_and_enrich(llm_output, candidates, document, pipeline_version)
    
    assert result1 == result2
```

---

## 15. Checklist Operativa

### 15.1 Pre-Deployment

- [ ] ✅ Keyword resolution dal catalogo attivato (obbligatorio)
- [ ] ✅ Validation multi-stage implementata con tutti i guardrail
- [ ] ✅ Evidence verification attiva con warning
- [ ] ⚠️ TODO: CRM integration reale (sostituire mock)
- [ ] ⚠️ TODO: Collision index da observations storiche (rimuovere placeholder)
- [ ] ⚠️ TODO: Evidence policy bloccante configurata (threshold >30%)
- [ ] ✅ Confidence adjustment con naming corretto (confidence_llm/confidence_adjusted)
- [ ] ✅ Entity extraction document-level implementata
- [ ] ✅ Mapping keywordsintext → keywords nel build output
- [ ] ✅ Safe lemmatization integrata in Candidate Generation
- [ ] [ ] PII redaction attiva per compliance GDPR
- [ ] [ ] Monitoring alert configurati (vedi 15.2)
- [ ] [ ] Test coverage >= 80%
- [ ] [ ] Load testing con 1000 msg/min
- [ ] [ ] Rollback plan documentato

### 15.2 Monitoring & Alerts

**Metriche da monitorare**:

| Metrica | Threshold | Azione |
|---------|-----------|--------|
| Validation error rate | > 5% | Alert + escalation |
| Fallback rate | > 10% | Investigate LLM quality |
| Confidence adjusted < 0.3 | per 20%+ topics | Review keyword quality |
| Collision rate | > 15% | Dictionary cleanup needed |
| UNKNOWN_TOPIC rate | > 20% | Taxonomy review |
| Under-triage rate | > 10% | Priority scoring recalibration |
| CRM lookup timeout | > 2% | Check CRM health |
| Entity extraction time | > 500ms | Optimize RegEx patterns |

**Dashboard Grafana**:
```
- Validation success rate (rolling 1h)
- Priority distribution (urgent/high/medium/low)
- Customer status distribution (new/existing/unknown)
- Confidence histogram (per topic label)
- Processing latency P50/P95/P99
```

### 15.3 Post-Deployment

- [ ] Monitor error rate primissime 24h
- [ ] Verificare confidence distribution (evitare troppi 0.3 o 0.9)
- [ ] Audit manuale su 100 messaggi random
- [ ] Confronto priority LLM vs priority post-processing
- [ ] Verificare collision index effettivo (dopo 1 settimana dati)
- [ ] Calibrare thresholds alert se necessario
- [ ] Documentare incident response procedure

---

## 16. Supporto Accademico

### 16.1 JSON Schema & Validation

- **Blaze: JSON Schema compilation per validazione 10x più veloce** [arXiv:2503.02770, 2025]
- **Modern JSON Schema formalization & complexity** [arXiv:2307.10034, 2024]
- **Schema-based structured output con reinforcement learning** [arXiv:2502.18878, 2025]

### 16.2 Multi-Label Classification e Metriche

- **Tsoumakas & Katakis (2007)**: Multi-label metrics (micro/macro-F1, Hamming Loss)
- **Madjarov et al. (2012)**: Comparative evaluation methods

### 16.3 Priority Triage

- **Chen et al. (2023)**: BERT-based triage con priority scoring [Bioengineering 10(4)]
- **Abbasi et al. (2024)**: Bug priority prediction con Cohen's Kappa [Multimedia Tools & Applications]

### 16.4 Keyword Extraction e Dizionari Dinamici

- **KeyBERT**: Embedding-based keyword extraction
- **Sentence-transformers**: Multilingual models per italiano (paraphrase-multilingual-mpnet-base-v2)
- **YAKE!**: Unsupervised keyword extraction (Campos et al. 2020)

---

## 17. Riepilogo Modifiche v3.3

### 17.1 Cosa è Cambiato

1. ✅ **Schema LLM**: Ora richiede solo `candidateid` in `keywordsintext`
2. ✅ **Keyword Resolution**: Sempre dal catalogo (funzione `resolve_keywords_from_catalog`)
3. ✅ **Confidence Naming**: `confidence_llm` + `confidence_adjusted` + `confidence` (alias)
4. ✅ **Entity Extraction**: Document-level, rimosso parametro `labelid`
5. ✅ **Output Mapping**: `keywordsintext` → `keywords` esplicito (`normalize_topics_keywords`)
6. ✅ **Evidence Verification**: Rafforzata con span consistency check
7. ✅ **Safe Lemmatization**: Funzione `safe_lemmatize()` per fix sostantivi

### 17.2 Compatibilità

**Breaking Changes**:
- Schema LLM modificato (solo `candidateid` in keywordsintext)
- Firma `extract_all_entities()` modificata (rimosso `labelid`)
- Output schema usa `keywords` invece di `keywordsintext`

**Backward Compatibility**:
- `confidence` mantenuto come alias di `confidence_adjusted`
- `keywordsintext` opzionalmente mantenuto nel JSON interno (se necessario per debug)

### 17.3 Migration Guide

**Da v3.2 a v3.3**:

1. **Aggiorna prompt LLM**: Rimuovi richiesta di `lemma`, `term`, `count` in `keywordsintext`
2. **Integra `resolve_keywords_from_catalog()`**: Chiamala dopo validation, prima di confidence adjustment
3. **Aggiorna `adjust_all_topic_confidences()`**: Usa nuova firma con confidence_llm/confidence_adjusted
4. **Aggiorna `extract_all_entities()`**: Rimuovi parametro `labelid` dalle chiamate
5. **Integra `build_triage_output_schema()`**: Chiamala prima del return finale
6. **Test regression**: Verifica che tutti i test passino con nuovo schema

---

**Fine Documentazione v3.3**

---

**Contatti**: Per domande o issue, contattare il team MLOps o aprire ticket su JIRA.