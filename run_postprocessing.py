"""
Script di esecuzione del Post-Processing & Enrichment Layer.

Legge:
  - inference_layer_i_o/pipeline_last_output.json  (Candidate Generation Layer)
  - inference_layer_i_o/triage_result_gemma.json   (LLM Layer)

Produce:
  - inference_layer_i_o/postprocessing_result.json
"""
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("run_postprocessing")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
IO_DIR = ROOT / "inference_layer_i_o"

CANDIDATES_FILE = IO_DIR / "pipeline_last_output.json"
TRIAGE_FILE     = IO_DIR / "triage_result_gemma.json"
OUTPUT_FILE     = IO_DIR / "postprocessing_result.json"

# ---------------------------------------------------------------------------
# Load inputs
# ---------------------------------------------------------------------------
logger.info("Caricamento input...")

with open(CANDIDATES_FILE, encoding="utf-8") as f:
    pipeline_output: dict = json.load(f)

with open(TRIAGE_FILE, encoding="utf-8") as f:
    triage_raw: dict = json.load(f)

# ---------------------------------------------------------------------------
# Estrae i dati necessari
# ---------------------------------------------------------------------------
message_id: str   = pipeline_output["message_id"]
candidates: list  = pipeline_output["candidates"]

# La triage_response è il corpo del messaggio LLM
triage_response: dict = triage_raw["triage_response"]
dict_version: int     = triage_response["dictionaryversion"]
model_name: str       = triage_raw["model"]

logger.info("message_id        : %s", message_id)
logger.info("model LLM         : %s", model_name)
logger.info("dictionaryversion : %d", dict_version)
logger.info("candidates        : %d", len(candidates))

# ---------------------------------------------------------------------------
# Ricostruzione EmailDocument
# Nota: i JSON di input sono output di layer precedenti; il corpo originale
# non viene trasportato. Viene ricostruito un body_canonical rappresentativo
# dai quote di evidenza presenti nella triage_response.
# ---------------------------------------------------------------------------
from src.models.email_document import EmailDocument

evidence_quotes = []
for topic in triage_response.get("topics", []):
    for ev in topic.get("evidence", []):
        q = ev.get("quote", "").strip()
        if q and q not in evidence_quotes:
            evidence_quotes.append(q)

# Body sintetico assemblato dai quote di evidenza
reconstructed_body = (
    "Buongiorno,\n\n"
    + " ".join(evidence_quotes)
    + "\n\nCordiali saluti,\nMario Rossi"
)

# Subject: ricostruito dai term sorgente "subject" nel pipeline output
subject_terms = [
    c["term"]
    for c in candidates
    if c.get("source") == "subject"
]
# Prende il termine più lungo come proxy del subject
subject_proxy = max(subject_terms, key=len) if subject_terms else "Richiesta informazioni contratto"

document = EmailDocument(
    message_id=message_id,
    from_raw="Mario Rossi <mario.rossi@example.it>",
    subject=subject_proxy,
    body=reconstructed_body,
    body_canonical=reconstructed_body,
)

logger.info("subject (proxy)   : %s", document.subject)
logger.info("body_canonical    : %d chars", len(document.body_canonical))

# ---------------------------------------------------------------------------
# PipelineVersion
# ---------------------------------------------------------------------------
from src.models.pipeline_version import PipelineVersion

pipeline_version = PipelineVersion(
    dictionaryversion=dict_version,
    modelversion=model_name,
    model_type="chat",
)

# ---------------------------------------------------------------------------
# Regex lexicon (EU-standard: email + codice fiscale italiano + IBAN)
# ---------------------------------------------------------------------------
regex_lexicon = {
    "EMAIL": [
        {
            "regex_pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "label": "EMAIL",
        }
    ],
    "CODICEFISCALE": [
        {
            "regex_pattern": r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b",
            "label": "CODICEFISCALE",
        }
    ],
    "IBAN": [
        {
            "regex_pattern": r"\bIT\d{2}[A-Z0-9]{23}\b",
            "label": "IBAN",
        }
    ],
    "TELEFONO": [
        {
            "regex_pattern": r"\b(?:\+39[\s\-]?)?(?:0\d{1,4}[\s\-]?\d{5,8}|3\d{2}[\s\-]?\d{6,7})\b",
            "label": "TELEFONO",
        }
    ],
}

# ---------------------------------------------------------------------------
# Esecuzione pipeline
# ---------------------------------------------------------------------------
from src.postprocessing.pipeline import postprocess_and_enrich

logger.info("Avvio pipeline post-processing...")

result = postprocess_and_enrich(
    llm_output_raw=triage_response,       # già un dict con triage_response
    candidates=candidates,
    document=document,
    pipeline_version=pipeline_version,
    regex_lexicon=regex_lexicon,
    nlp_model=None,                        # spaCy opzionale — skip per performance
)

logger.info("Pipeline completata in %d ms", result["processing_metadata"]["postprocessing_duration_ms"])
logger.info("Entità estratte   : %d", result["processing_metadata"]["entities_extracted"])
logger.info("Osservazioni      : %d", result["processing_metadata"]["observations_created"])

# ---------------------------------------------------------------------------
# Salvataggio output
# ---------------------------------------------------------------------------
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

logger.info("Output salvato in: %s", OUTPUT_FILE)

# ---------------------------------------------------------------------------
# Stampa riepilogo a video
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("POST-PROCESSING RESULT — RIEPILOGO")
print("=" * 70)
print(f"message_id  : {result['message_id']}")
print(f"model       : {result['pipeline_version']['modelversion']}")

triage = result["triage"]
print(f"\nSentiment   : {triage['sentiment']['value']} (conf={triage['sentiment']['confidence']:.2f})")
print(f"Priority    : {triage['priority']['value']} (conf={triage['priority']['confidence']:.2f})")
print(f"Customer    : {triage['customerstatus']['value']} (conf={triage['customerstatus']['confidence']:.2f})")

print(f"\nTopics ({len(triage['topics'])}):")
for t in triage["topics"]:
    kw_count = len(t.get("keywordsintext", []))
    ev_count = len(t.get("evidence", []))
    print(f"  [{t['labelid']:20s}] conf={t['confidence']:.2f}  kw={kw_count}  evidence={ev_count}")

if result["entities"]:
    print(f"\nEntità estratte ({len(result['entities'])}):")
    for e in result["entities"]:
        print(f"  {e['label']:16s} → {e['text']}")

diag = result["diagnostics"]
if diag.get("warnings"):
    print(f"\nWarning: {diag['warnings']}")

print("=" * 70)
print(f"Output: {OUTPUT_FILE}")
print("=" * 70 + "\n")
