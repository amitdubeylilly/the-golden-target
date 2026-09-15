# The Golden Target — Reconciliation Tool

Reconciles five overlapping biological-target data extracts into one trusted **golden record**
per target, and flags the real data defects — *with proof from an external authority* — without
flagging harmless noise.

---

## ✅ Solution status

This repo contains the **completed** tool. It resolves against the nominated authority (EBI
Proteins API) and finishes the exam pack in **~30 s** (budget: 5 min).

```bash
python reconcile.py data/exam      # prints the contract JSON to stdout
python -m pytest tests/ -q         # 8 tests, self-contained, no network
```

On `data/exam/` it produces **609 golden records** and **55 findings** (3 wrong mappings,
2 duplicate identities, 50 stale-but-valid labels) — every finding NAILED (carries both
`observed` and `correct`) and evidenced against the authority.

**How it resolves identity (worth knowing):** obsolete/secondary UniProt accessions 404 on the
EBI direct endpoint, so the tool resolves every accession once, builds a **secondary→primary
index** from the `secondaryAccession` field of the primaries it retrieves, and resolves the 404s
*through EBI itself* — no second data source is needed on the exam. `rest.uniprot.org` remains
only as a rare, loudly-logged fallback. ChEMBL (same host as EBI) is the authority for
ChEMBL-ID collisions. Output is deterministic and finding order is stable.

---

## ⚠️ Constraints that are easy to miss

Several of these live *only* inside `data/verification_starter.md` (a read-only file that's easy
to overlook). They are surfaced here so the behaviour is unmistakable.

1. **A hidden dataset is what actually gets scored.** The tool is run on a second, **unseen
   dataset with the same schema**, and *all objective points are measured there* → the logic
   must generalise, never overfit to the visible `data/exam/` rows.
2. **5-minute runtime budget per pack** → authority lookups are batched, cached, threaded, and
   retried (cold exam run ≈30 s).
3. **`findings` carry two fields beyond the brief's four** — `severity` and `classification`
   (per `verification_starter.md`). All seven are emitted.
4. **The `pmid` trap.** `source_publications.csv` `pmid` values are **internal reference numbers,
   not PubMed IDs**; some collide with real, unrelated papers. They are **never fetched and never
   flagged**; ambiguous mentions are resolved from `context_sentence` text only.
5. **`data/` is read-only ground truth.** The tool only reads from it. Re-verify findings against
   the authority at submission time — reference databases evolve.

---

## Repository map

```
the-golden-target/
├── README.md              ← this file
├── reconcile.py           ← the tool; `python reconcile.py <pack_dir>`
├── goldentarget_config.json ← grading config (entry, run command, 300 s timeout)
├── requirements.txt       ← dependencies (stdlib-only — no third-party packages)
├── approach-summary.md    ← artifact #3 (7 questions, ≤1,500 words)
├── chat-export.md         ← artifact #2 (the investigation record)
├── .gitignore
├── tests/
│   └── test_reconcile.py  ← 8 self-contained tests (HTTP layer mocked; no network)
└── data/                  ← READ-ONLY validation ground truth (do not modify)
    ├── verification_starter.md   ← official tool contract + runtime budget + hidden-dataset rule
    └── exam/              ← the data pack (~600 targets, ~3,250 rows)
        ├── source_uniprot.csv
        ├── source_chembl.csv
        ├── source_bindingdb.csv
        ├── source_internal.csv
        └── source_publications.csv
```

---

## What the tool does

1. **Ingests** the five CSVs in a pack directory.
2. **Links & deduplicates** rows across sources that refer to the same protein target (join on
   UniProt accession; gene symbol + organism as secondary keys; isoform/secondary/merged
   accessions collapse to their primary).
3. **Builds one golden record per unique target** (canonical gene symbol + primary accession +
   which sources contributed).
4. **Detects real defects** — wrong mappings, stale-but-valid labels, duplicate identities — and
   **proves each one** by resolving the entity against the external authority.
5. **Prints one JSON object** (contract below) to stdout, within the runtime budget, on data it
   has never seen.

---

## Tool contract (authoritative)

Per `data/verification_starter.md` (which extends the official brief's four evidence fields with
`severity` + `classification`).

### Invocation
```
python reconcile.py <pack_dir>     # reads <pack_dir>/source_*.csv  ->  prints JSON to stdout
```

### Output — a single JSON object
```json
{
  "unique_target_count": 123,
  "golden_records": [
    {"gene": "...", "primary_accession": "...", "sources": ["..."]}
  ],
  "findings": [
    {
      "gene": "...",
      "observed": "<the defective value as it appears in the file>",
      "correct": "<the corrected value>",
      "retrieved_evidence": "<what the authority literally returned when you resolved the entity>",
      "evidence_source": "<where you got it (endpoint/connector)>",
      "severity": "...",
      "classification": "..."
    }
  ]
}
```

### Field reference

| Field | Where | Meaning |
|---|---|---|
| `unique_target_count` | top level | Number of unique target identities after linking/dedup (= number of golden records). |
| `golden_records[].gene` | golden record | The target's canonical (approved) gene symbol. |
| `golden_records[].primary_accession` | golden record | The canonical **primary** UniProt accession. |
| `golden_records[].sources` | golden record | Which source databases contributed (e.g. `["uniprot","chembl",...]`). |
| `findings[].gene` | finding | Gene symbol identifying which target the finding is about. |
| `findings[].observed` | finding | The defective value exactly as it appears in the file. |
| `findings[].correct` | finding | The corrected value. |
| `findings[].retrieved_evidence` | finding | What the authority *literally returned* when the entity was resolved. |
| `findings[].evidence_source` | finding | Where the evidence came from (endpoint/connector). |
| `findings[].severity` | finding | Relative severity of the defect. |
| `findings[].classification` | finding | The **kind** of defect: wrong mapping / stale-but-valid label / duplicate identity. |

> **Grading of each finding is objective:** full marks (**NAILED**) only when it carries *both*
> `observed` **and** `correct`. "Looks wrong" with no correction is **DETECTED** (quarter marks);
> not surfaced is **MISSED**. **Precision counts** — a wrong flag can cost you.

---

## The data pack (`data/exam/`) — schemas at a glance

Five source extracts of the same overlapping set of protein targets, each with its own IDs,
naming style, and curation level, so they disagree. The natural join key is the **UniProt
accession**; gene symbol + organism are secondary/sanity keys.

| File | Columns | Role |
|---|---|---|
| `source_uniprot.csv` | `accession, entry_name, gene_names, protein_name, organism, reviewed, length, database` | **Identity backbone.** `reviewed`/`database` = Swiss-Prot (reviewed) vs TrEMBL (auto). |
| `source_chembl.csv` | `chembl_id, pref_name, target_type, accession, gene_symbol, organism, tax_id, target_confidence` | Curated bioactivity DB. `tax_id` 9606 = human. |
| `source_bindingdb.csv` | `target_name, species, uniprot_id, gene_symbol, assay_count, binding_type` | Measured binding affinities. `binding_type` (Ki/IC50/Kd/EC50) are valid values, not defects. |
| `source_internal.csv` | `internal_id, registered_name, gene_symbol, source_db, external_id, uniprot_ref, registered_by, registration_date, status` | Home-grown registry; `uniprot_ref` is its claimed accession (prone to drift/typos). |
| `source_publications.csv` | `pmid, target_mention, context_sentence, journal, year` | Literature mentions. **`pmid` is internal — do not fetch/flag.** Disambiguate via `context_sentence`. |

**Known harmless variance (do NOT flag):** formatting differences such as `Homo sapiens` vs
`H. sapiens`, capitalisation, spacing, ordering, or binding-type values. Flagging these is a
precision penalty.

---

## The authority (source of truth for proof)

**UniProt, via the EBI Proteins API** (`https://www.ebi.ac.uk/proteins/api/`). Resolving an
entity there establishes, per protein: its **identity / primary accession**, **organism (+ taxon
ID)**, the **approved symbol today**, **former symbols** (synonyms), its **merge history**
(primary vs secondary accession), and **cross-references**. Each defect is proven against this —
the source rows are internally consistent, so nothing looks wrong until checked externally.
ChEMBL (same host) is the authority for ChEMBL-ID collisions.

---

## Scoring (100 pts)

| Dimension | Pts | Notes |
|---|---|---|
| Reconciliation accuracy | 55 | Correct linking/dedup and golden records on the **hidden** data. |
| Defect surfacing | 25 | `observed` + `correct` (NAILED) with evidence; correct classification/severity; high **precision**. |
| Investigation rigor | 20 | Documented in `chat-export.md` + `approach-summary.md`. |

---

## Submission — three artifacts

- **GitHub repo** — the tool (`reconcile.py`), tests, config, and docs (this repo).
- **Claude chat export (markdown)** — `chat-export.md`: the record of the investigation (how the
  audit was run, what was verified and how, and what was deliberately **not** flagged and why).
- **Approach summary (≤1,500 words)** — `approach-summary.md`: the seven challenge questions.

---
*Nothing under `data/` should be modified — it is the read-only validation ground truth. The tool
generalises to an unseen, schema-identical dataset supplied at grading time.*
