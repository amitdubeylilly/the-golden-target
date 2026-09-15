# The Golden Target — Challenge Repository

**Front door / index for this challenge.** Start here. This file maps every other file,
surfaces the constraints that are easy to miss, and states the exact contract to build to.
It does not solve the challenge — it makes the challenge implementable by anyone.

> **What the challenge is, in one line:** build a tool that reconciles five overlapping
> biological-target data extracts into one trusted "golden record" per target, and flags the
> real data defects — *with proof from an external authority* — without flagging harmless noise.

---

## ✅ Solution status

This repo contains the **completed** tool. It resolves against the nominated authority (EBI
Proteins API) and finishes the exam pack in **~30 s** (budget: 5 min).

```bash
python reconcile.py data/exam      # prints the contract JSON to stdout
python -m pytest tests/ -q                # 8 tests, self-contained, no network
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

## ⚠️ Read this first — five things it's easy to miss

These are non-negotiable and several of them live *only* inside
`data/verification_starter.md` (a read-only file that's easy to overlook). They are
surfaced here so nobody builds the wrong thing.

1. **A hidden dataset is what actually gets scored.** Your tool is run on a second,
   **unseen dataset with the same schema**, and *all objective points are measured there*.
   → Do **not** hardcode or overfit to the visible `data/exam/` rows. The logic must
   generalise.
2. **5-minute runtime budget per pack.** The tool must finish each pack within **5 minutes**
   when graded. → Batch/cache authority lookups; avoid naive per-row slow network calls.
3. **`findings` need two more fields than the brief lists.** The brief's evidence contract
   names four fields; `verification_starter.md` shows the *full* shape also includes
   **`severity`** and **`classification`**. → Emit all of them (see the contract below).
4. **The `pmid` trap.** `source_publications.csv` `pmid` values are **internal reference
   numbers, not PubMed IDs**. Some collide with real, unrelated PubMed papers. → **Never
   fetch them, never flag them.** Resolve ambiguous literature mentions from the shipped
   `context_sentence` text only.
5. **`data/` is read-only ground truth. Do not modify anything under it.** It is the
   source you validate against. Re-verify findings against the authority *at submission time*,
   because reference databases evolve.

---

## Repository map

```
the-golden-target/
├── README.md                     ← YOU ARE HERE — index, constraints, tool contract
├── challenge-brief.md            ← the verbatim official challenge brief (source of truth for the ask)
├── AGENT_INSTRUCTIONS.md         ← complete hand-off brief: give this to any agent to build & submit the whole thing
├── SUBMISSION.md                 ← how to package & submit the 3 artifacts + pre-submit checklist
├── approach-summary.md           ← artifact #3 (7 questions, ≤1,500 words)
├── agent_config.json             ← grading agent configuration (run command, timeout, etc.)
├── reconcile.py                  ← tool entry point; `python reconcile.py <pack_dir>`
├── requirements.txt              ← dependencies (stdlib-only — no third-party packages)
├── .gitignore                    ← standard ignores (keeps data/ tracked)
├── tests/
│   ├── README.md                 ← how the test suite works + what each case asserts
│   └── test_reconcile.py         ← 8 self-contained tests (HTTP layer mocked; no network)
├── resources/
│   ├── data-context.md           ← domain + data background: what the 5 sources are, biology, MDM/DQ framing, glossary
│   ├── BRIDGE 2021 Q2 Seminar - Big Picture Drug Discovery.pdf   ← Lilly drug-discovery pipeline colour
│   └── Discovery onboarding June2024v2.pptx                      ← Lilly discovery-phase / milestone colour
└── data/                  ← READ-ONLY. Do not modify. Validation ground truth.
    ├── verification_starter.md   ← official tool contract + runtime budget + hidden-dataset rule
    └── exam/                      ← the data pack (~600+ targets, 3,000+ rows)
        ├── source_uniprot.csv
        ├── source_chembl.csv
        ├── source_bindingdb.csv
        ├── source_internal.csv
        └── source_publications.csv
```

---

## Suggested reading order

1. **This README** — the map and the constraints.
2. **`challenge-brief.md`** — the full official ask, scoring, and submission requirements.
3. **`data/verification_starter.md`** — the exact tool contract, runtime budget, and
   the hidden-dataset rule (already summarised below, but read the original).
4. **`resources/data-context.md`** — the domain: what UniProt/ChEMBL/BindingDB/the internal
   registry/the literature table are, why target identity is slippery, the defect taxonomy,
   and a glossary. Read this before writing any reconciliation logic.
5. **`resources/*.pdf` / `*.pptx`** — optional Lilly context on where "targets" sit in drug
   discovery (the *why it matters*). Not needed to code, useful for the write-up.

---

## What you're building (plain terms)

A command-line tool that:
1. **Ingests** the five CSVs in a pack directory.
2. **Links & deduplicates** rows across sources that refer to the same protein target
   (join primarily on UniProt accession; use gene symbol + organism as secondary keys).
3. **Builds one golden record per unique target** (canonical gene symbol + primary accession +
   which sources contributed).
4. **Detects real defects** — wrong mappings, stale-but-valid labels, duplicate identities —
   and **proves each one** by resolving the entity against the external authority.
5. **Prints one JSON object** (see contract) and finishes within the runtime budget, on data
   it has never seen.

---

## Tool contract (authoritative — build to this)

Reconciled from `challenge-brief.md` **and** `data/verification_starter.md`. Where they
differ, the fuller `verification_starter.md` shape wins (it adds `severity` + `classification`).

### Invocation
```
<cmd> <pack_dir>        # e.g. reads <pack_dir>/source_*.csv  ->  prints JSON to stdout
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
| `golden_records[].sources` | golden record | Which source databases contributed to this record (e.g. `["uniprot","chembl",...]`). |
| `findings[].gene` | finding | Gene symbol identifying which target the finding is about. |
| `findings[].observed` | finding | The defective value exactly as it appears in the file. |
| `findings[].correct` | finding | The corrected value. |
| `findings[].retrieved_evidence` | finding | What the authority *literally returned* when you resolved the entity (identity / organism / merge target / approved symbol / cross-reference). |
| `findings[].evidence_source` | finding | Where the evidence came from (endpoint/connector). |
| `findings[].severity` | finding | Relative severity of the defect. *(Field required by `verification_starter.md`; the brief notes defect types carry "different severities.")* |
| `findings[].classification` | finding | The **kind** of defect. Align with the brief's guidance: **wrong mapping / stale-but-valid label / duplicate identity** (extend as the data warrants). |

> **Grading of each finding is objective:** full marks (**NAILED**) only when it carries *both*
> `observed` **and** `correct`. "Looks wrong" with no correction is **DETECTED** (quarter marks).
> Not surfaced at all is **MISSED**. **Precision counts** — a wrong flag can cost you.

---

## The data pack (`data/exam/`) — schemas at a glance

Five source extracts of the same overlapping set of protein targets. Each uses its own IDs,
naming style, and curation level, so they disagree. The natural join key is the **UniProt
accession**; gene symbol + organism are secondary/sanity keys.

| File | Columns | Role |
|---|---|---|
| `source_uniprot.csv` | `accession, entry_name, gene_names, protein_name, organism, reviewed, length, database` | **Identity backbone.** `reviewed`/`database` = Swiss-Prot (reviewed) vs TrEMBL (auto). |
| `source_chembl.csv` | `chembl_id, pref_name, target_type, accession, gene_symbol, organism, tax_id, target_confidence` | Manually curated bioactivity DB. `tax_id` 9606 = human. |
| `source_bindingdb.csv` | `target_name, species, uniprot_id, gene_symbol, assay_count, binding_type` | Measured binding affinities. `binding_type` (Ki/IC50/Kd/EC50) are valid values, not defects. |
| `source_internal.csv` | `internal_id, registered_name, gene_symbol, source_db, external_id, uniprot_ref, registered_by, registration_date, status` | Home-grown registry; `uniprot_ref` is its claimed accession (prone to drift/typos). |
| `source_publications.csv` | `pmid, target_mention, context_sentence, journal, year` | Literature mentions. **`pmid` is internal — do not fetch/flag.** Disambiguate via `context_sentence`. |

**Known harmless variance (do NOT flag):** formatting differences such as `Homo sapiens`
vs `H. sapiens`, capitalisation, spacing, ordering. Flagging these is a precision penalty.

Full descriptions of each database, the biology, and the defect taxonomy are in
**`resources/data-context.md`**.

---

## The authority (source of truth for proof)

**UniProt, via the EBI Proteins API** (`https://www.ebi.ac.uk/proteins/api/`; UniProt at
`https://www.uniprot.org`). Resolving an entity there lets you establish, per protein:
its **identity / primary accession**, **organism (+ taxon ID)**, the **approved symbol today**,
**other symbols it was formerly known by**, its **merge history** (primary vs secondary
accession), and its **cross-references** to other databases. Each defect must be proven against
this — the source rows are internally consistent, so nothing looks wrong until checked externally.

---

## Scoring (100 pts) and what it implies

| Dimension | Pts | Implication for the build |
|---|---|---|
| Reconciliation accuracy | 55 | Correct linking/dedup and correct golden records dominate the score — get the count and canonical fields right on the **hidden** data. |
| Defect surfacing | 25 | Emit `observed` + `correct` (NAILED) with evidence; classify by type/severity; keep **precision** high. |
| Investigation rigor | 20 | Documented in the chat export + approach summary (systematic audit, what you verified, what you chose not to flag). |

---

## Submission — three artifacts (per `challenge-brief.md`)

- [ ] **GitHub repo** with the tool (follow the sample repo structure:
  `https://github.com/EliLillyCo/Claude-Olympics-Sample-Repo`).
- [ ] **Claude chat export (markdown)** — the graded record of *your* investigation: how you
  audited, what you verified and how, and what you chose **not** to flag and why.
- [ ] **Approach summary (≤1,500 words)** answering the seven questions in `challenge-brief.md`
  (audit strategy · identity validation · defect-vs-messy decision rules · one thing you did
  NOT flag · how you validated the tool · how you worked with Claude · what you'd harden for
  production).

---

## Where the detail lives

| Need | Open |
|---|---|
| The exact official ask, scoring, submission questions | `challenge-brief.md` |
| The tool contract, runtime budget, hidden-dataset rule (original) | `data/verification_starter.md` |
| What the databases are, the biology, defect taxonomy, glossary | `resources/data-context.md` |
| Where "targets" sit in drug discovery (background colour) | `resources/*.pdf`, `resources/*.pptx` |
| The data to run against | `data/exam/*.csv` **(read-only)** |
| **Full hand-off brief for an implementing agent** | **`AGENT_INSTRUCTIONS.md`** |
| How to package & submit the three artifacts + final checklist | `SUBMISSION.md` |
| The completed approach summary (artifact #3, 7 questions) | `approach-summary.md` |
| The reconciliation tool (entry point) | `reconcile.py` |
| How to self-validate the tool before the exam | `tests/README.md` |

---
*This repository is organised for handoff: `README.md` (this file) is the single entry point;
`challenge-brief.md` and `data/verification_starter.md` are the authoritative sources of
the ask and the contract; `resources/` holds the domain background. Nothing under `data/`
should be modified.*
