# Pipeline Email Triage - Analisi Problemi e Soluzioni con Contratti I/O

**Documento tecnico**: Diagnosi problemi pipeline, soluzioni proposte e definizione contratti input/output per layer  
**Data**: 25 Febbraio 2026  
**Sistema**: Email Triage Classifier con dizionari dinamici e determinismo statistico

---

## Executive Summary

La pipeline presenta **due classi di problemi critici** rilevati durante il post-processing:

1. **Schema Mismatch**: campi inattesi (`count`, `lemma`) nell'output LLM Layer che causano warning durante la normalizzazione
2. **Span Mismatch**: offset degli span generati dall'LLM non corrispondono alle quote estratte dal testo canonicalizzato

**Redis non risolve questi problemi**, perché sono errori di **contratto I/O e logica di calcolo**, non di persistenza. Redis può però aiutare a rilevarli prima, renderli riproducibili e impedire propagazione silenziosa.

**Soluzione proposta**: Implementare **contratti I/O versionati** con validazione multi-stadio tra layer, calcolo server-side degli span, e storage dual-payload (raw + normalized) in Redis.

---

## 1. Architettura Pipeline e Layer

### 1.1 Panoramica componenti

```
┌─────────────────────────────────────────────────────────────────┐
│                       EMAIL TRIAGE PIPELINE                      │
└─────────────────────────────────────────────────────────────────┘

INPUT: Email .eml / IMAP

    ↓

┌───────────────────────────────────────────────────────────────┐
│ LAYER 0: Ingestion & Normalization                            │
│ - RFC5322 parsing, MIME decode                                │
│ - Canonicalization (quote/firma removal)                      │
│ - EmailDocument record                                         │
└───────────────────────────────────────────────────────────────┘
    ↓ EmailDocument (body_canonical, removed_sections)

┌───────────────────────────────────────────────────────────────┐
│ LAYER 1: Candidate Generator (Deterministico)                 │
│ - Tokenization n-gram (1-3)                                   │
│ - Lemmatization (spaCy IT)                                    │
│ - KeyBERT embedding scoring                                   │
│ - Filtering (stopwords, blacklist)                            │
│ - Stable ID generation (SHA-1 hash)                           │
└───────────────────────────────────────────────────────────────┘
    ↓ CandidateList (candidateid, term, lemma, count, source, embeddingscore)

┌───────────────────────────────────────────────────────────────┐
│ LAYER 2: LLM Classification                                   │
│ - Structured Outputs / Tool Calling                           │
│ - Model: gemma3:4b / gpt-4o / o1-preview                      │
│ - Multi-label topics + sentiment + priority                   │
│ - keywordsintext: solo candidateid + lemma + count            │
│ - evidence: quote + span (generati dall'LLM)                  │
└───────────────────────────────────────────────────────────────┘
    ↓ TriageResponse (topics, keywordsintext, evidence, sentiment, priority)

┌───────────────────────────────────────────────────────────────┐
│ LAYER 3: Post-Processing & Enrichment                         │
│ - Schema normalization (strip unexpected fields)              │
│ - Confidence adjustment (topic-level)                         │
│ - Entity extraction (RegEx + NER)                             │
│ - Customer status lookup (CRM)                                │
│ - Observation creation                                         │
│ - Span validation (diagnostics)                               │
└───────────────────────────────────────────────────────────────┘
    ↓ FinalOutput (triage normalized, entities, observations, diagnostics)

OUTPUT: JSON persistito + observations per promoter
```

### 1.2 Punti di intervento identificati

**Problema 1 (Schema Mismatch)** si verifica tra **Layer 2 → Layer 3**:
- LLM emette `keywordsintext` con campi `candidateid`, `lemma`, `count` (come nel prompt)
- Post-processing si aspetta solo `candidateid` (secondo contratto previsto)
- Fix: allineare **schema del prompt** con **schema atteso** dal post-processing

**Problema 2 (Span Mismatch)** si verifica in **Layer 2 interno**:
- LLM genera span `[start, end]` basati sulla sua "percezione" del testo
- Span non corrispondono agli offset reali nel `body_canonical`
- Fix: **calcolare span server-side** dopo la risposta LLM, usando `quote` come anchor

---

## 2. Analisi Dettagliata Problemi

### 2.1 Problema 1: Schema Mismatch in `keywordsintext`

#### Sintomi osservati

Dal file `postprocessing_result.json`, sezione `diagnostics.warnings`:

```json
"warnings": [
  "keywordsintext: stripped unexpected fields ['count', 'lemma'] from candidate 'L4CD0keGl10i4l43'",
  "keywordsintext: stripped unexpected fields ['count', 'lemma'] from candidate 't9lOmUSIi6dXny_-'",
  ...
]
```

#### Root Cause

**Output LLM Layer** (`LLM_LayerOutput.json`):
```json
{
  "topics": [
    {
      "labelid": "CONTRATTO",
      "keywordsintext": [
        {
          "candidateid": "L4CD0keGl10i4l43",
          "lemma": "contratto",        ← CAMPO INATTESO
          "count": 2                    ← CAMPO INATTESO
        }
      ]
    }
  ]
}
```

**Schema atteso dal post-processing** (implicito dal codice di validazione):
```python
# Solo candidateid dovrebbe essere presente
{
  "candidateid": "L4CD0keGl10i4l43"
}
```

**Causa radice**: Il **prompt LLM** include nella lista `candidatekeywords` anche i campi `lemma`, `count`, `source`, `embeddingscore` (vedi `CandidateGenerateorDeterministicOutput.json`), e l'LLM li ripete nell'output. Il post-processing rimuove campi non previsti ma genera warning.

#### Impatto

- **Operativo**: Warning ripetuti nei log, rumore diagnostico
- **Semantico**: Perdita di informazione (lemma/count potrebbero essere utili per enrichment)
- **Manutenzione**: Disallineamento tra prompt e validazione aumenta debito tecnico

### 2.2 Problema 2: Span Mismatch in `evidence`

#### Sintomi osservati

Dal file `postprocessing_result.json`, sezione `diagnostics.warnings`:

```json
"warnings": [
  "Span mismatch: span=[42,64] extracts 'sono corretti: Codice ...' but quote is 'Volevo confermare che i dati s...'",
  "Span mismatch: span=[86,126] extracts '01U come discusso. Ho verifica...' but quote is 'come discusso. Ho verificato t...'",
  ...
]
```

#### Root Cause

**Output LLM Layer** (`LLM_LayerOutput.json`):
```json
{
  "evidence": [
    {
      "quote": "Volevo confermare che i dati sono corretti: Codice Fiscale: RSSMRA80A01H501U",
      "span": [42, 64]
    }
  ]
}
```

**Verifica span**:
Se `body_canonical[42:64]` estrae `"sono corretti: Codice "`, **non corrisponde** alla quote completa.

**Causa radice**:
1. L'LLM "vede" il testo nel prompt e "immagina" offset numerici
2. Non ha accesso agli offset reali (è un modello linguistico, non un parser)
3. Il prompt include `body_canonical` troncato a 8000 caratteri, ma senza indicatori di offset
4. Risultato: span generati sono **euristica/indovinati**, non calcolati

#### Impatto

- **Operativo**: Impossibilità di ricostruire span per highlight in UI o audit
- **Semantico**: Evidence non verificabile, perde valore probatorio
- **Qualità**: Diagnostici pieni di warning, difficile distinguere bug reali da falsi positivi

---

## 3. Soluzioni Proposte

### 3.1 Soluzione Problema 1: Allineamento Schema

#### Approccio: Schema-First con Validazione Multi-Stadio

**Step 1**: Definire schema esplicito per `keywordsintext` **accettando i campi che l'LLM produce naturalmente**

**Opzione A** - Minimal (solo ID):
```python
class KeywordInText(BaseModel):
    candidateid: str
```

**Opzione B** - Full enrichment (accetta tutti i campi):
```python
class KeywordInText(BaseModel):
    candidateid: str
    lemma: Optional[str] = None
    term: Optional[str] = None
    count: Optional[int] = None
    source: Optional[str] = None
    embeddingscore: Optional[float] = None
```

**Raccomandazione**: **Opzione B**. I campi sono utili per:
- `lemma`: matching con dizionario active per validazione
- `count`: confidence adjustment (keyword molto frequente = segnale più forte)
- `embeddingscore`: quality scoring nel promoter

**Step 2**: Arricchire post-processing invece di strippare

```python
def enrich_keywords_from_candidates(
    keywords_in_text: List[KeywordInText],
    candidates: Dict[str, Candidate]
) -> List[EnrichedKeyword]:
    """
    Arricchisce keywords dell'LLM con dati completi dal CandidateGenerator
    """
    enriched = []
    for kw in keywords_in_text:
        candidate = candidates.get(kw.candidateid)
        if not candidate:
            warnings.append(f"Keyword {kw.candidateid} not in candidate list")
            continue
        
        enriched.append(EnrichedKeyword(
            candidateid=kw.candidateid,
            lemma=kw.lemma or candidate.lemma,  # LLM o fallback candidate
            term=candidate.term,
            count=kw.count or candidate.count,
            source=candidate.source,
            embeddingscore=candidate.embeddingscore,
            # Campi aggiuntivi per post-processing
            dictionary_match=check_dictionary_match(candidate.lemma, labelid),
            confidence_contribution=compute_keyword_confidence(candidate)
        ))
    return enriched
```

**Step 3**: Tool Calling con Pydantic (v3 brainstorming)

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class KeywordInTextSchema(BaseModel):
    candidateid: str = Field(..., description="MUST match candidateid from input")
    lemma: Optional[str] = Field(None, description="Lemma form of keyword")
    count: Optional[int] = Field(None, ge=1, description="Occurrences in text")

class TopicSchema(BaseModel):
    labelid: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    keywordsintext: List[KeywordInTextSchema] = Field(..., min_items=1)
    evidence: List[EvidenceSchema] = Field(..., min_items=1)

# Tool calling nativo
from instructor import from_openai

client = from_openai(OpenAI())
response = client.chat.completions.create(
    model="gpt-4o-2025-11-20",
    messages=[...],
    response_model=TriageResponseSchema  # Pydantic model
)
# response è già validato, no parsing manuale
```

#### Benefici

- **Zero warning**: Schema allineato tra prompt e validazione
- **Arricchimento**: Dati LLM + dati deterministici combinati
- **Manutenibilità**: Schema unico Pydantic per prompt + validazione + storage

### 3.2 Soluzione Problema 2: Span Calculation Server-Side

#### Approccio: LLM produce quote, server calcola span

**Step 1**: Modificare schema `evidence` - span diventa opzionale

```python
class EvidenceSchema(BaseModel):
    quote: str = Field(..., max_length=200, description="Exact quote from email")
    span: Optional[Tuple[int, int]] = Field(None, description="Optional [start,end] from LLM")
```

**Step 2**: Post-processing calcola span deterministico

```python
import hashlib
from typing import Optional, Tuple

def compute_span_from_quote(
    quote: str,
    body_canonical: str,
    text_hash: str  # Hash del testo di riferimento
) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    Calcola span [start, end] cercando quote nel body_canonical
    
    Returns:
        (span, status) dove status = "exact_match" | "fuzzy_match" | "not_found"
    """
    # Exact match
    start = body_canonical.find(quote)
    if start != -1:
        return (start, start + len(quote)), "exact_match"
    
    # Fuzzy match con difflib per gestire variazioni minori
    from difflib import SequenceMatcher
    
    best_ratio = 0.0
    best_span = None
    window_size = len(quote) + 20  # Quote + margine
    
    for i in range(len(body_canonical) - len(quote) + 1):
        window = body_canonical[i:i + window_size]
        ratio = SequenceMatcher(None, quote, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_span = (i, i + len(quote))
    
    if best_ratio >= 0.85:  # Threshold fuzzy match
        return best_span, "fuzzy_match"
    
    return None, "not_found"

def enrich_evidence_with_spans(
    evidence_list: List[Evidence],
    body_canonical: str,
    text_hash: str
) -> List[EnrichedEvidence]:
    """
    Arricchisce evidence LLM con span calcolati server-side
    """
    enriched = []
    for ev in evidence_list:
        span, status = compute_span_from_quote(ev.quote, body_canonical, text_hash)
        
        enriched.append(EnrichedEvidence(
            quote=ev.quote,
            span=span,  # Calcolato server-side
            span_llm=ev.span,  # Original LLM span per audit
            span_status=status,
            text_hash=text_hash  # Reference hash per verificabilità
        ))
        
        if status == "not_found":
            warnings.append(f"Quote not found in text: {ev.quote[:50]}...")
    
    return enriched
```

**Step 3**: Storage span con text reference

```python
class EnrichedEvidence(BaseModel):
    quote: str
    span: Optional[Tuple[int, int]]  # Server-computed
    span_llm: Optional[Tuple[int, int]]  # LLM original per audit
    span_status: str  # "exact_match" | "fuzzy_match" | "not_found"
    text_hash: str  # SHA-256 del body_canonical di riferimento
```

#### Strategia di Migrazione

**Fase 1**: Dual-tracking (mantieni entrambi gli span)
- Salva `span_llm` (originale) e `span_computed` (server-side)
- Compara accuracy con ground truth da annotazioni manuali
- Logging: `span_mismatch_rate` come metrica

**Fase 2**: Rimozione span dal prompt LLM
- Dopo validazione accuracy, rimuovi campo `span` da `EvidenceSchema`
- LLM produce solo `quote`, server calcola span
- Prompt più semplice, riduzione token, meno errori LLM

#### Benefici

- **Correttezza**: Span sempre verificabili, no più mismatch
- **Determinismo**: Stessa quote produce stesso span (a parità di body_canonical)
- **Audit trail**: Text hash permette verifica a posteriori
- **Resilienza**: Fuzzy match gestisce quote con variazioni minori (spazi, punteggiatura)

---

## 4. Contratti I/O per Layer

### 4.1 Contratto Layer 0 → Layer 1

**Output**: `EmailDocument`

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass(frozen=True)
class RemovedSection:
    """Traccia sezioni rimosse durante canonicalization"""
    type: str  # "quote" | "signature" | "disclaimer" | "reply_header"
    span_start: int
    span_end: int
    content: str

@dataclass(frozen=True)
class EmailDocument:
    """Record email canonicalizzato"""
    message_id: str
    from_raw: str
    subject: str
    body: str  # Testo originale completo
    body_canonical: str  # Testo pulito per analisi
    removed_sections: List[RemovedSection]
    parser_version: str  # es. "email-parser-1.3.0"
    canonicalization_version: str  # es. "1.2.0"
```

**Validazione Input → Layer 1**:
- `message_id` non vuoto, formato RFC5322
- `body_canonical` non vuoto dopo stripping
- `parser_version` e `canonicalization_version` presenti (per determinismo)

### 4.2 Contratto Layer 1 → Layer 2

**Output**: `CandidateList`

**Schema JSON** (da `CandidateGenerateorDeterministicOutput.json`):

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class Candidate(BaseModel):
    """Singolo candidato keyword deterministico"""
    candidateid: str = Field(..., description="Stable SHA-1 hash ID")
    source: str = Field(..., description="'subject' | 'body'")
    term: str = Field(..., description="Original n-gram (1-3 tokens)")
    lemma: str = Field(..., description="Lemmatized form")
    count: int = Field(..., ge=1, description="Occurrences in text")
    embeddingscore: float = Field(..., ge=0.0, le=1.0, description="KeyBERT similarity")
    score: float = Field(..., description="Composite score (count+embedding+source)")

class CandidateMetadata(BaseModel):
    """Metadati generazione candidati"""
    total_candidates_raw: int
    total_candidates_filtered: int
    filter_stats: Dict[str, int]  # stopwords removed, blacklist, etc.
    timings_ms: Dict[str, float]
    pipeline_version: Dict[str, str]  # dict_version, model, parser, etc.
    metrics: Dict[str, float]  # avg_score, coverage, etc.

class CandidateGeneratorOutput(BaseModel):
    """Output completo Layer 1"""
    message_id: str
    candidates: List[Candidate] = Field(..., max_items=100)
    metadata: CandidateMetadata
```

**Validazione Output Layer 1**:
- `candidateid` unico per ogni candidate
- `candidateid` stabile: stesso testo + source → stesso ID
- `count >= 1` per tutti i candidati
- `lemma` non vuoto, non in stopwords
- `score` calcolato correttamente (verificabile con formula)

**Validazione Input → Layer 2**:
- Almeno 5 candidati (o warning se testo troppo corto)
- `candidateid` non duplicati
- `embeddingscore` presente per almeno 70% dei candidati (coverage check)

### 4.3 Contratto Layer 2 → Layer 3

**Output**: `TriageResponse`

**Schema JSON** (da `LLM_LayerOutput.json` allineato con fix Problema 1):

```python
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal

class KeywordInText(BaseModel):
    """Keyword selezionata dall'LLM (con arricchimento opzionale)"""
    candidateid: str = Field(..., description="MUST match candidate from input")
    lemma: Optional[str] = Field(None, description="Lemma from LLM or candidate")
    term: Optional[str] = None
    count: Optional[int] = Field(None, ge=1)
    source: Optional[str] = None
    embeddingscore: Optional[float] = None

class Evidence(BaseModel):
    """Evidenza testuale per topic"""
    quote: str = Field(..., max_length=200, description="Exact quote from text")
    span: Optional[List[int]] = Field(None, description="[start,end] optional from LLM")
    
    @validator('span')
    def validate_span(cls, v):
        if v is not None and len(v) != 2:
            raise ValueError("Span must be [start, end]")
        if v is not None and v[0] >= v[1]:
            raise ValueError("Span start must be < end")
        return v

class Topic(BaseModel):
    """Topic assegnato (multi-label)"""
    labelid: str = Field(..., description="From closed taxonomy enum")
    confidence: float = Field(..., ge=0.0, le=1.0)
    keywordsintext: List[KeywordInText] = Field(..., min_items=1, max_items=15)
    evidence: List[Evidence] = Field(..., min_items=1, max_items=3)

class Sentiment(BaseModel):
    value: Literal["positive", "neutral", "negative"]
    confidence: float = Field(..., ge=0.0, le=1.0)

class Priority(BaseModel):
    value: Literal["low", "medium", "high", "urgent"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    signals: List[str] = Field(default_factory=list, max_items=6)

class TriageResponse(BaseModel):
    """Output completo LLM Layer"""
    dictionaryversion: int
    topics: List[Topic] = Field(..., min_items=1, max_items=5)
    sentiment: Sentiment
    priority: Priority
    customerstatus: dict  # Opzionale, può essere None se non disponibile
```

**Validazione Output Layer 2**:
- Ogni `candidateid` in `keywordsintext` esiste nella `CandidateList` di input
- Almeno un topic (anche `UNKNOWN_TOPIC` se necessario)
- `labelid` in enum chiuso (registry attivo)
- Quote in `evidence` non vuote
- Span LLM (se presente) con start < end

**Validazione Input → Layer 3**:
- Schema conforme (Pydantic validator automatico)
- Nessun campo extra non previsto
- `dictionaryversion` corrisponde a versione attuale pipeline

### 4.4 Contratto Layer 3 → Output Finale

**Output**: `PostProcessingResult`

**Schema JSON** (da `postprocessing_result.json` migliorato):

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
import uuid

class EnrichedKeyword(BaseModel):
    """Keyword arricchita con dati candidate + validazione dizionario"""
    candidateid: str
    term: str
    lemma: str
    count: int
    source: str
    embeddingscore: float
    # Arricchimenti post-processing
    dictionary_match: Optional[str] = None  # "active" | "proposed" | None
    confidence_contribution: float = 0.0

class EnrichedEvidence(BaseModel):
    """Evidence con span calcolati server-side"""
    quote: str
    span: Optional[List[int]]  # Server-computed (None se not_found)
    span_llm: Optional[List[int]]  # LLM original per audit
    span_status: str  # "exact_match" | "fuzzy_match" | "not_found"
    text_hash: str  # SHA-256 del body_canonical

class EnrichedTopic(BaseModel):
    """Topic con confidence adjusted e keywords arricchite"""
    labelid: str
    confidence_llm: float
    confidence_adjusted: float  # Dopo adjustment (embeddingscore, dictionary_match)
    keywords: List[EnrichedKeyword]
    evidence: List[EnrichedEvidence]

class Entity(BaseModel):
    """Entità estratta (RegEx + NER)"""
    text: str
    label: str  # "CODICE_FISCALE" | "P_IVA" | "EMAIL" | etc.
    start: int
    end: int
    source: str  # "regex" | "ner" | "lexicon"
    confidence: float

class Observation(BaseModel):
    """Observation per promoter dizionari"""
    obs_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str
    labelid: str
    candidateid: str
    lemma: str
    term: str
    count: int
    embeddingscore: float
    dict_version: int
    promoted_to_active: bool = False
    observed_at: datetime = Field(default_factory=datetime.utcnow)

class Diagnostics(BaseModel):
    """Diagnostici per debugging e monitoring"""
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    validation_retries: int = 0
    fallback_applied: bool = False

class PostProcessingResult(BaseModel):
    """Output finale pipeline"""
    message_id: str
    pipeline_version: Dict[str, str]
    triage: Dict[str, any]  # topics enriched, sentiment, priority, customerstatus
    entities: List[Entity]
    observations: List[Observation]
    diagnostics: Diagnostics
    processing_metadata: Dict[str, any]
```

**Validazione Output Layer 3**:
- Tutti gli span in `evidence` sono verificati (`span_status != "error"`)
- `confidence_adjusted` sempre >= 0 e <= 1
- Observations non duplicate per `(labelid, candidateid, message_id)`
- Text hash consistente per tutte le evidence della stessa email

---

## 5. Redis come Layer di Persistenza e Validazione

### 5.1 Architettura Storage Dual-Payload

**Pattern proposto**: Per ogni layer, salvare **due payload**:

```python
# Chiave Redis con versioning
KEY_PATTERN = "run:{run_id}:msg:{message_id}:layer:{layer_name}:v:{schema_version}"

# Payload RAW (output grezzo LLM/layer)
redis.set(f"{KEY_PATTERN}:raw", json.dumps(raw_output))

# Payload NORMALIZED (validato + arricchito)
redis.set(f"{KEY_PATTERN}:normalized", json.dumps(normalized_output))
```

**Esempio concreto** per Layer 2 → 3:

```python
run_id = "202602250945"
message_id = "<abcd1234@example.it>"
schema_v = "v3.3"

# Raw LLM output (con campi extra, span LLM)
redis.set(
    f"run:{run_id}:msg:{message_id}:layer:llm_classification:v:{schema_v}:raw",
    json.dumps(llm_raw_response),
    ex=86400  # TTL 24h
)

# Normalized output (dopo validazione + enrichment)
redis.set(
    f"run:{run_id}:msg:{message_id}:layer:llm_classification:v:{schema_v}:normalized",
    json.dumps(triage_normalized),
    ex=86400
)
```

### 5.2 Write Barrier Pattern

**Regola chiave**: Solo payload **normalized e validati** passano al layer successivo.

```python
def process_layer_with_validation(
    input_data: dict,
    layer_function: callable,
    validator: callable,
    redis_client: Redis,
    run_id: str,
    message_id: str,
    layer_name: str
) -> dict:
    """
    Esegue layer con write barrier: valida prima di persistere
    """
    # 1. Esegui layer
    raw_output = layer_function(input_data)
    
    # 2. Salva raw per audit
    redis_client.set(
        f"run:{run_id}:msg:{message_id}:layer:{layer_name}:raw",
        json.dumps(raw_output)
    )
    
    # 3. Valida output
    validation_result = validator(raw_output)
    
    if not validation_result.valid:
        # Log errori, raise exception, NON propagare
        logger.error(f"Validation failed for {layer_name}: {validation_result.errors}")
        raise ValidationError(f"Layer {layer_name} output invalid", validation_result.errors)
    
    # 4. Normalizza (strip campi extra, enrichment, span calculation)
    normalized_output = normalize_output(raw_output, validation_result)
    
    # 5. Salva normalized per layer successivo
    redis_client.set(
        f"run:{run_id}:msg:{message_id}:layer:{layer_name}:normalized",
        json.dumps(normalized_output)
    )
    
    # 6. Propaga SOLO normalized
    return normalized_output
```

### 5.3 Benefici Redis + Write Barrier

**Tracciabilità**:
- Ogni layer produce output persistito con timestamp e versione
- Audit trail completo: raw + normalized per ogni step
- Replay: ripeti singolo layer da input salvato

**Rilevamento early**:
- Validazione fallisce subito → pipeline si ferma
- No propagazione silenziosa di errori
- Diagnostici precisi: quale layer, quale campo, quale email

**Determinismo**:
- Chiavi immutabili con `run_id` + `message_id` + `schema_version`
- Nessun overwrite, solo append
- Ricostruibile: stesso input + versioni → stesso output

**Performance**:
- Redis in-memory: latenza ms per lettura/scrittura
- TTL per cleanup automatico (24h-7d retention operativa)
- PostgreSQL per retention long-term (audit, backtesting)

### 5.4 Storage Durable Complementare

**Redis**: Stati intermedi, code, eventi (ephemeral)  
**PostgreSQL**: Record definitivi, observations, dizionari (durable)

```python
# Dopo pipeline completa
def persist_final_output(result: PostProcessingResult, db: PostgreSQL):
    """
    Salva output finale in PostgreSQL per retention e analytics
    """
    # 1. Triage result
    db.execute("""
        INSERT INTO triage_results 
        (message_id, run_id, topics, sentiment, priority, pipeline_version, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (result.message_id, run_id, json.dumps(result.triage), ...))
    
    # 2. Observations per promoter
    for obs in result.observations:
        db.execute("""
            INSERT INTO observations
            (obs_id, message_id, labelid, candidateid, lemma, term, count, 
             embeddingscore, dict_version, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (obs.obs_id, obs.message_id, ...))
    
    # 3. Entities
    for entity in result.entities:
        db.execute("""
            INSERT INTO extracted_entities
            (message_id, text, label, start, end, source, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (result.message_id, entity.text, ...))
```

---

## 6. Modifiche alla Pipeline per Implementazione

### 6.1 Layer 2: LLM Classification

**File**: `src/classification/llm_client.py`

**Modifiche**:

1. **Schema allineato con enrichment**

```python
# Prima (causa warning)
class KeywordInTextOld(BaseModel):
    candidateid: str

# Dopo (accetta campi LLM)
class KeywordInText(BaseModel):
    candidateid: str
    lemma: Optional[str] = None
    count: Optional[int] = None
```

2. **Rimozione span dal prompt** (opzionale, dopo validazione Fase 2)

```python
# Prima
class Evidence(BaseModel):
    quote: str
    span: List[int]  # LLM genera span

# Dopo
class Evidence(BaseModel):
    quote: str
    # Span rimosso, calcolato server-side
```

3. **Tool calling con Pydantic** (upgrade v3)

```python
from instructor import from_openai

client = from_openai(OpenAI(api_key=api_key))

response = client.chat.completions.create(
    model="gpt-4o-2025-11-20",
    messages=[...],
    response_model=TriageResponseSchema  # Pydantic automatico
)
# response già validato, type-safe
```

### 6.2 Layer 3: Post-Processing

**File**: `src/enrichment/postprocessing.py`

**Modifiche**:

1. **Enrichment keywords** (invece di stripping)

```python
def enrich_keywords(
    topics: List[Topic],
    candidates: Dict[str, Candidate]
) -> List[EnrichedTopic]:
    """
    Arricchisce keywords LLM con dati candidate completi
    """
    enriched_topics = []
    
    for topic in topics:
        enriched_keywords = []
        
        for kw in topic.keywordsintext:
            candidate = candidates.get(kw.candidateid)
            if not candidate:
                warnings.append(f"Keyword {kw.candidateid} not in candidates")
                continue
            
            # Combina dati LLM + candidate
            enriched_keywords.append(EnrichedKeyword(
                candidateid=kw.candidateid,
                lemma=kw.lemma or candidate.lemma,
                term=candidate.term,
                count=kw.count or candidate.count,
                source=candidate.source,
                embeddingscore=candidate.embeddingscore,
                dictionary_match=check_dict_match(candidate.lemma, topic.labelid),
                confidence_contribution=compute_contribution(candidate)
            ))
        
        enriched_topics.append(EnrichedTopic(
            labelid=topic.labelid,
            confidence_llm=topic.confidence,
            confidence_adjusted=adjust_confidence(topic, enriched_keywords),
            keywords=enriched_keywords,
            evidence=topic.evidence  # Enrichment span a step successivo
        ))
    
    return enriched_topics
```

2. **Span calculation server-side**

```python
def compute_spans_for_evidence(
    evidence_list: List[Evidence],
    body_canonical: str,
    text_hash: str
) -> List[EnrichedEvidence]:
    """
    Calcola span reali da quote usando body_canonical come reference
    """
    enriched = []
    
    for ev in evidence_list:
        # Exact match
        start = body_canonical.find(ev.quote)
        
        if start != -1:
            span = [start, start + len(ev.quote)]
            status = "exact_match"
        else:
            # Fuzzy match con difflib
            span, status = fuzzy_match_quote(ev.quote, body_canonical)
        
        enriched.append(EnrichedEvidence(
            quote=ev.quote,
            span=span,
            span_llm=ev.span if hasattr(ev, 'span') else None,
            span_status=status,
            text_hash=text_hash
        ))
    
    return enriched
```

3. **Write barrier con Redis**

```python
def process_postprocessing_with_barrier(
    llm_output: TriageResponse,
    candidates: Dict[str, Candidate],
    body_canonical: str,
    redis_client: Redis,
    run_id: str,
    message_id: str
) -> PostProcessingResult:
    """
    Post-processing con write barrier pattern
    """
    # 1. Salva LLM raw
    redis_client.set(
        f"run:{run_id}:msg:{message_id}:layer:llm:raw",
        json.dumps(llm_output.dict())
    )
    
    # 2. Validazione
    validation = validate_llm_output(llm_output, candidates)
    if not validation.valid:
        raise ValidationError(validation.errors)
    
    # 3. Enrichment
    enriched_topics = enrich_keywords(llm_output.topics, candidates)
    text_hash = hashlib.sha256(body_canonical.encode()).hexdigest()
    
    for topic in enriched_topics:
        topic.evidence = compute_spans_for_evidence(
            topic.evidence, body_canonical, text_hash
        )
    
    # 4. Salva normalized
    normalized = PostProcessingResult(
        message_id=message_id,
        triage={"topics": enriched_topics, ...},
        ...
    )
    
    redis_client.set(
        f"run:{run_id}:msg:{message_id}:layer:postprocessing:normalized",
        normalized.json()
    )
    
    return normalized
```

### 6.3 Orchestrator Main

**File**: `src/api/main.py`

**Modifiche**:

```python
@app.post("/classify_email")
async def classify_email(email: EmailInput, redis: Redis = Depends(get_redis)):
    """
    Pipeline orchestrator con Redis write barriers
    """
    run_id = generate_run_id()
    message_id = email.message_id
    
    try:
        # Layer 0: Parsing
        doc = parse_email(email.raw)
        
        # Layer 1: Candidates
        candidates = process_layer_with_validation(
            input_data=doc,
            layer_function=generate_candidates,
            validator=validate_candidates,
            redis_client=redis,
            run_id=run_id,
            message_id=message_id,
            layer_name="candidate_generation"
        )
        
        # Layer 2: LLM
        llm_output = process_layer_with_validation(
            input_data={"doc": doc, "candidates": candidates},
            layer_function=call_llm,
            validator=validate_llm_output,
            redis_client=redis,
            run_id=run_id,
            message_id=message_id,
            layer_name="llm_classification"
        )
        
        # Layer 3: Post-processing
        final_result = process_layer_with_validation(
            input_data={"llm_output": llm_output, "candidates": candidates, "doc": doc},
            layer_function=postprocess,
            validator=validate_final_output,
            redis_client=redis,
            run_id=run_id,
            message_id=message_id,
            layer_name="postprocessing"
        )
        
        # Persist to PostgreSQL
        persist_to_db(final_result)
        
        return final_result
        
    except ValidationError as e:
        logger.error(f"Validation failed at {e.layer}: {e.errors}")
        # Salva failure in Redis per debugging
        redis.set(f"run:{run_id}:msg:{message_id}:error", json.dumps({
            "layer": e.layer,
            "errors": e.errors,
            "timestamp": datetime.utcnow().isoformat()
        }))
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 7. Testing e Validazione

### 7.1 Unit Test per Span Calculation

**File**: `tests/test_span_calculation.py`

```python
import pytest
from src.enrichment.span_calculator import compute_span_from_quote

def test_exact_match():
    body = "Volevo confermare che i dati sono corretti: Codice Fiscale: RSSMRA80A01H501U"
    quote = "Codice Fiscale: RSSMRA80A01H501U"
    
    span, status = compute_span_from_quote(quote, body, text_hash="dummy")
    
    assert status == "exact_match"
    assert span == [44, 76]
    assert body[span[0]:span[1]] == quote

def test_fuzzy_match():
    body = "Volevo confermare che i dati sono corretti: Codice  Fiscale"
    quote = "Codice Fiscale"  # Doppio spazio in body, singolo in quote
    
    span, status = compute_span_from_quote(quote, body, text_hash="dummy")
    
    assert status == "fuzzy_match"
    assert body[span[0]:span[1]].strip() == quote.strip()

def test_not_found():
    body = "Testo completamente diverso"
    quote = "Quote che non esiste"
    
    span, status = compute_span_from_quote(quote, body, text_hash="dummy")
    
    assert status == "not_found"
    assert span is None
```

### 7.2 Integration Test per Write Barrier

**File**: `tests/test_write_barrier.py`

```python
import pytest
from src.api.orchestrator import process_layer_with_validation
from unittest.mock import Mock

def test_validation_blocks_invalid_output(redis_mock):
    """Verifica che validation error blocchi propagazione"""
    
    # Layer function che produce output invalido
    def invalid_layer(input_data):
        return {"candidateid": "INVALID_NO_EXISTS"}
    
    # Validator che rileva errore
    def validator(output):
        return ValidationResult(valid=False, errors=["candidateid not in candidates"])
    
    with pytest.raises(ValidationError) as exc_info:
        process_layer_with_validation(
            input_data={},
            layer_function=invalid_layer,
            validator=validator,
            redis_client=redis_mock,
            run_id="test_run",
            message_id="test@example.it",
            layer_name="test_layer"
        )
    
    assert "candidateid not in candidates" in str(exc_info.value)
    
    # Verifica che raw sia stato salvato, ma normalized NO
    assert redis_mock.exists("run:test_run:msg:test@example.it:layer:test_layer:raw")
    assert not redis_mock.exists("run:test_run:msg:test@example.it:layer:test_layer:normalized")
```

### 7.3 End-to-End Test con Real Data

**File**: `tests/test_e2e_pipeline.py`

```python
import pytest
from src.api.main import classify_email

@pytest.fixture
def real_email():
    """Email reale dal dataset annotato"""
    return EmailInput(
        message_id="<abcd1234@example.it>",
        raw=open("tests/fixtures/email_sample.eml", "rb").read()
    )

def test_full_pipeline_with_redis(real_email, redis_client, db_session):
    """Test end-to-end con validazione span e enrichment"""
    
    result = classify_email(real_email, redis=redis_client)
    
    # 1. Verifica topics assegnati
    assert len(result.triage["topics"]) >= 1
    assert all(t.labelid in VALID_LABELS for t in result.triage["topics"])
    
    # 2. Verifica keywords arricchite
    for topic in result.triage["topics"]:
        for kw in topic.keywords:
            assert kw.lemma is not None
            assert kw.term is not None
            assert kw.embeddingscore >= 0.0
    
    # 3. Verifica span calcolati
    for topic in result.triage["topics"]:
        for ev in topic.evidence:
            assert ev.span_status in ["exact_match", "fuzzy_match", "not_found"]
            if ev.span_status != "not_found":
                # Verifica span effettivamente estrae quote
                body = get_body_canonical(real_email)
                extracted = body[ev.span[0]:ev.span[1]]
                assert similarity(extracted, ev.quote) >= 0.85
    
    # 4. Verifica Redis persistence
    assert redis_client.exists(f"run:*:msg:{real_email.message_id}:layer:candidate_generation:normalized")
    assert redis_client.exists(f"run:*:msg:{real_email.message_id}:layer:llm_classification:normalized")
    
    # 5. Verifica PostgreSQL persistence
    db_result = db_session.query(TriageResult).filter_by(message_id=real_email.message_id).first()
    assert db_result is not None
    assert len(db_result.observations) >= 1
```

---

## 8. Metriche e Monitoring

### 8.1 Metriche per Span Quality

```python
class SpanQualityMetrics:
    """Metriche qualità span calculation"""
    
    def __init__(self):
        self.total_evidence = 0
        self.exact_matches = 0
        self.fuzzy_matches = 0
        self.not_found = 0
    
    def compute(self, enriched_evidence_list: List[EnrichedEvidence]):
        for ev in enriched_evidence_list:
            self.total_evidence += 1
            if ev.span_status == "exact_match":
                self.exact_matches += 1
            elif ev.span_status == "fuzzy_match":
                self.fuzzy_matches += 1
            else:
                self.not_found += 1
    
    def report(self) -> dict:
        return {
            "exact_match_rate": self.exact_matches / self.total_evidence,
            "fuzzy_match_rate": self.fuzzy_matches / self.total_evidence,
            "not_found_rate": self.not_found / self.total_evidence,
            "total_evidence": self.total_evidence
        }
```

**Target KPI**:
- `exact_match_rate >= 0.85` (85% span perfetti)
- `not_found_rate <= 0.05` (max 5% quote non trovate)

### 8.2 Metriche per Schema Conformance

```python
class SchemaConformanceMetrics:
    """Metriche conformità schema I/O"""
    
    def __init__(self):
        self.validation_attempts = 0
        self.validation_failures = 0
        self.unexpected_fields_count = 0
        self.missing_fields_count = 0
    
    def track_validation(self, validation_result: ValidationResult):
        self.validation_attempts += 1
        if not validation_result.valid:
            self.validation_failures += 1
        
        # Parse errors per tipo
        for error in validation_result.errors:
            if "unexpected field" in error.lower():
                self.unexpected_fields_count += 1
            elif "missing field" in error.lower():
                self.missing_fields_count += 1
    
    def report(self) -> dict:
        return {
            "validation_success_rate": 1 - (self.validation_failures / self.validation_attempts),
            "unexpected_fields_count": self.unexpected_fields_count,
            "missing_fields_count": self.missing_fields_count
        }
```

**Target KPI**:
- `validation_success_rate >= 0.98` (98% output conformi)
- `unexpected_fields_count = 0` dopo fix Problema 1

### 8.3 Alerting Dashboard

**Prometheus metrics** da esporre:

```python
from prometheus_client import Counter, Histogram, Gauge

# Contatori errori per layer
validation_errors = Counter(
    'pipeline_validation_errors_total',
    'Total validation errors by layer',
    ['layer_name', 'error_type']
)

# Distribuzione span status
span_status_distribution = Counter(
    'span_status_total',
    'Distribution of span matching status',
    ['status']  # exact_match, fuzzy_match, not_found
)

# Latency per layer
layer_processing_time = Histogram(
    'layer_processing_seconds',
    'Processing time per layer',
    ['layer_name']
)

# Gauge per Redis key count
redis_key_count = Gauge(
    'redis_pipeline_keys_total',
    'Total pipeline keys in Redis',
    ['layer_name']
)
```

**Alert rules** (Grafana):

```yaml
alerts:
  - name: HighValidationErrorRate
    condition: rate(pipeline_validation_errors_total[5m]) > 0.1
    severity: critical
    message: "Validation error rate > 10% in last 5 minutes"
  
  - name: HighSpanNotFoundRate
    condition: (span_status_total{status="not_found"} / span_status_total) > 0.1
    severity: warning
    message: "Span not_found rate > 10%"
  
  - name: RedisKeyExplosion
    condition: redis_pipeline_keys_total > 100000
    severity: warning
    message: "Redis key count exceeds 100k, check TTL cleanup"
```

---

## 9. Roadmap Implementazione

### Fase 1: Fix Immediati (1-2 giorni)

**Obiettivo**: Eliminare warning attuali

- [ ] **Schema alignment**: Aggiornare `KeywordInText` per accettare `lemma`, `count`
- [ ] **Enrichment keywords**: Modificare post-processing da "strip" a "enrich"
- [ ] **Test regression**: Verificare zero warning su dataset test
- [ ] **Deploy**: Staging con monitoring warning rate

**Deliverable**: Zero `keywordsintext: stripped unexpected fields` warning

### Fase 2: Span Calculation Server-Side (3-5 giorni)

**Obiettivo**: Span sempre verificabili

- [ ] **Span calculator**: Implementare `compute_span_from_quote()` con fuzzy match
- [ ] **Evidence enrichment**: Aggiungere `span_status`, `text_hash`
- [ ] **Dual-tracking**: Salvare `span_llm` + `span_computed` per validazione
- [ ] **Test accuracy**: Comparare vs ground truth annotato (target: exact_match >= 85%)
- [ ] **Deploy**: Production con metric `span_status_distribution`

**Deliverable**: Zero `Span mismatch` warning, span verificabili al 95%

### Fase 3: Redis Write Barriers (5-7 giorni)

**Obiettivo**: Tracciabilità e early detection

- [ ] **Redis integration**: Setup cluster Redis + chiavi versionabili
- [ ] **Write barrier logic**: Implementare `process_layer_with_validation()`
- [ ] **Dual-payload storage**: raw + normalized per ogni layer
- [ ] **Orchestrator refactor**: Propagare solo payload validated
- [ ] **Alerting**: Prometheus metrics + Grafana dashboard
- [ ] **Retention policy**: TTL 24h Redis, long-term PostgreSQL

**Deliverable**: Audit trail completo, validation blocking su errori

### Fase 4: Tool Calling Upgrade (2-3 giorni)

**Obiettivo**: Schema-first con Pydantic

- [ ] **Instructor integration**: Upgrade a `instructor` library
- [ ] **Pydantic schemas**: Convertire JSON Schema → Pydantic models
- [ ] **LLM client refactor**: Tool calling nativo OpenAI/Anthropic
- [ ] **Validation automatica**: Rimuovere validation manuale (Pydantic built-in)
- [ ] **Test conformance**: Verificare 98%+ output conformi

**Deliverable**: -80% codice validation, 95%+ conformità JSON

### Fase 5: Monitoring & Optimization (ongoing)

**Obiettivo**: Production-ready, alta qualità

- [ ] **E2E tests**: Dataset annotato con ground truth span
- [ ] **Performance**: Latency < 2s per email, throughput 100+ email/min
- [ ] **Cost**: Ottimizzazione token LLM (rimuovere span da prompt)
- [ ] **Drift detection**: Weekly chi-square test su label distribution
- [ ] **Human review queue**: Email con `confidence < 0.3` o `span_status = not_found`

**Deliverable**: Sistema production con SLO 99.5% uptime

---

## 10. Checklist Pre-Deploy

### 10.1 Schema Validation

- [ ] Tutti i Pydantic models definiti con field descriptions
- [ ] Validators per constraints (`min_items`, `max_items`, range confidence)
- [ ] Nessun campo `additionalProperties: true` in schema
- [ ] Unit test per ogni schema con input validi e invalidi

### 10.2 Contratti I/O

- [ ] Contratto scritto per ogni layer (input/output types)
- [ ] Validation function per ogni contratto
- [ ] Integration test con mock input/output
- [ ] Documentazione schema versioning strategy

### 10.3 Redis Persistence

- [ ] Chiavi con pattern versionabile (`run:X:msg:Y:layer:Z:v:V`)
- [ ] TTL configurato (24h default, parametrizzabile)
- [ ] Dual-payload (raw + normalized) per audit
- [ ] Cleanup job per chiavi expired

### 10.4 Monitoring

- [ ] Prometheus metrics esposte (`/metrics` endpoint)
- [ ] Grafana dashboard importato con panels per:
  - Validation error rate per layer
  - Span status distribution
  - Latency per layer
  - Redis key count
- [ ] Alert rules configurate (PagerDuty/Slack integration)
- [ ] Logging strutturato (JSON format, context con run_id/message_id)

### 10.5 Testing

- [ ] Unit tests per span calculation (exact/fuzzy/not_found)
- [ ] Integration tests per write barrier (block on validation failure)
- [ ] E2E test con real email dataset (100+ samples)
- [ ] Load test (100 email/min concurrent)
- [ ] Regression test per determinismo (same input → same output)

---

## 11. Conclusioni

### Problemi Identificati

1. **Schema Mismatch**: Disallineamento tra prompt LLM e schema validazione
2. **Span Mismatch**: Span generati dall'LLM non corrispondono a offset reali

### Soluzioni Implementate

1. **Schema alignment + enrichment**: Accettare campi LLM, arricchire invece di strippare
2. **Span calculation server-side**: LLM produce quote, server calcola span deterministici
3. **Redis write barriers**: Validazione multi-stadio, dual-payload storage, propagazione solo di output normalizzati

### Benefici Attesi

- **Zero warning** su schema mismatch
- **95%+ span verificabili** (exact o fuzzy match)
- **Audit trail completo** con Redis dual-payload
- **Early detection** errori con validation blocking
- **Determinismo migliorato** con contratti I/O versionati

### Next Steps

1. Implementare Fase 1 (fix immediati) → deploy staging
2. Validare span accuracy su dataset annotato
3. Rollout progressivo con A/B test (10% traffic)
4. Monitoring 7 giorni, tuning threshold fuzzy match
5. Production release completo

---

**Documento preparato da**: Pipeline Analysis Team  
**Per domande**: Vedere sezioni specifiche o contattare team engineering  
**Ultima revisione**: 25 Febbraio 2026