# Agent Instructions — Complete "The Golden Target"

You are an autonomous engineering agent. Your job is to **complete this challenge end to end**:
build the reconciliation tool, run it, prove your findings, and produce the three required
submission artifacts. This file is your single source of directions. Follow it exactly.

Everything you need is in this repository. **Do not invent requirements; do not skip the
"Absolute rules."**

---

## 0. Mission (what "done" looks like)

Build a command-line tool that ingests five overlapping biological-target data extracts and:
1. reconciles them into **one trusted "golden record" per unique target**, and
2. **flags the real data defects with proof** from an external authority (UniProt / EBI
   Proteins API), **without flagging harmless variance**.

Then package the results into the three graded artifacts (repo, chat/investigation export,
approach summary).

---

## 1. Read these first, in this order

1. `README.md` — index, the tool contract, and the constraints.
2. `challenge-brief.md` — the official ask, scoring, and the seven approach-summary questions.
3. `target-data/verification_starter.md` — the tool contract + runtime budget + hidden-dataset rule.
4. `resources/data-context.md` — what each database is, the biology, the defect taxonomy, glossary.
5. `reconcile.py` — the scaffold you will implement (logic-free stubs + TODOs).
6. `tests/README.md` — how to validate before running on the exam data.
7. `SUBMISSION.md` — how to package and submit.

Do not start coding until you understand (a) the **`pmid` trap** and (b) the **hidden-dataset**
rule below — both change how you build.

---

## 2. Absolute rules (breaking any one of these fails the task)

1. **Never modify anything under `target-data/`.** It is read-only ground truth. Do not edit,
   move, rename, or "clean" those files. Build test fixtures elsewhere.
2. **The graded run is on a HIDDEN dataset with the same schema.** All objective points are
   measured there. **Do not hardcode answers or overfit to `target-data/exam/`.** Your logic
   must generalise to unseen rows.
3. **5-minute runtime budget per pack.** The tool must finish within 5 minutes when graded.
   Batch, cache, and retry authority lookups; never do a slow network call per row naively.
4. **The `pmid` trap.** `source_publications.csv` `pmid` values are **internal reference
   numbers, not PubMed IDs**. Some coincidentally match real, unrelated papers. **Never fetch
   them and never flag them.** Resolve ambiguous literature mentions from the `context_sentence`
   text only.
5. **Precision counts against you when wrong.** Do **not** flag harmless variance (e.g.
   `Homo sapiens` vs `H. sapiens`, capitalisation, spacing, ordering, valid `binding_type`
   values). A false flag can lose points.
6. **stdout is the contract, and only the contract.** Print exactly one JSON object (the shape
   in §3) to stdout. Send logs/warnings to stderr. No extra prints on stdout.
7. **Dependencies via JFrog Artifactory only** (Lilly policy — PyPI/NPM prohibited). Strongly
   prefer the **Python standard library** (`csv`, `json`, `argparse`, `urllib`) so the tool has
   zero third-party dependencies. If a dep is unavoidable, resolve it from Artifactory and pin it.
8. **Every finding must be NAILED, not merely DETECTED** — it must carry both the `observed`
   value and the `correct` value, plus the authority evidence. "Looks wrong" without a
   retrieved correction earns a quarter of the marks.

---

## 3. The output contract — build to this exactly

**Invocation**
```
<cmd> <pack_dir>          # e.g.  python reconcile.py target-data/exam
```
Reads `<pack_dir>/source_*.csv`; prints ONE JSON object to stdout.

**Shape** (reconciled from the brief + `verification_starter.md`; emit ALL fields, including
`severity` and `classification`):
```json
{
  "unique_target_count": 123,
  "golden_records": [
    {"gene": "...", "primary_accession": "...", "sources": ["..."]}
  ],
  "findings": [
    {
      "gene": "...",
      "observed": "...",
      "correct": "...",
      "retrieved_evidence": "...",
      "evidence_source": "...",
      "severity": "...",
      "classification": "..."
    }
  ]
}
```

**Field reference**

| Field | Meaning |
|---|---|
| `unique_target_count` | Number of unique target identities after linking/dedup (= count of `golden_records`). |
| `golden_records[].gene` | The canonical (approved) gene symbol for the target. |
| `golden_records[].primary_accession` | The canonical **primary** UniProt accession. |
| `golden_records[].sources` | Which source databases contributed (e.g. `["uniprot","chembl",...]`). |
| `findings[].gene` | Gene symbol identifying the target the finding concerns. |
| `findings[].observed` | The defective value exactly as it appears in the file. |
| `findings[].correct` | The corrected value. |
| `findings[].retrieved_evidence` | What the authority *literally returned* (identity / organism / merge target / approved symbol / cross-reference). |
| `findings[].evidence_source` | Where the evidence came from (endpoint/connector, e.g. the EBI Proteins API URL). |
| `findings[].severity` | Impact-based severity (e.g. `high` / `medium` / `low`). |
| `findings[].classification` | Defect type — see the taxonomy in §6. |

---

## 4. The authority (how to prove findings)

**Primary authority: the EBI Proteins API** (`https://www.ebi.ac.uk/proteins/api/`), which
serves UniProt data as JSON. (`https://rest.uniprot.org/uniprotkb/` is an equivalent fallback.)
Confirm the exact response schema by calling it — then rely on these fields:

- **Look up by accession:** `GET https://www.ebi.ac.uk/proteins/api/proteins/{accession}`
  with header `Accept: application/json`.
- **Search by gene + organism:**
  `GET https://www.ebi.ac.uk/proteins/api/proteins?gene={symbol}&taxid=9606`.

From a resolved entry, extract and use:
- **Primary accession** and **secondary accessions** → detect superseded/**merged** accessions
  (a source accession that is now only a *secondary* of another entry has been *merged into* the
  primary).
- **Organism** (scientific name + **taxonomy id**; human = 9606) → detect **organism mismatches**.
- **Approved gene name (recommended)** plus **synonyms / previous names** → distinguish a
  **stale-but-valid** symbol (listed as a synonym/previous name) from a **wrong** one (belongs to
  a different gene/protein).
- **Cross-references** (`dbReferences`) → corroborate identity across databases.

**Engineering requirements for this layer (to meet the 5-minute budget and be robust):**
- **Deduplicate lookups** — resolve each unique accession/gene once, not per row.
- **Cache** responses (in-memory; optionally to a local `.cache/` file) so re-runs are fast.
- **Retry with backoff** on transient errors/timeouts; set sane per-request timeouts.
- **Handle 404 / obsolete / demerged** accessions gracefully — a 404 or a redirect to a merged
  entry is itself *evidence* of a merge/retirement.
- **Fail safe:** if the authority is briefly unreachable for an item, don't crash the whole run;
  degrade gracefully and still emit valid JSON.
- **Re-verify near submission** — reference databases evolve.

*(Environment note: in this workspace, `www.ebi.ac.uk` is reachable for testing. Do not assume
any other network access.)*

---

## 5. Implementation plan (phased)

Implement the stubs in `reconcile.py` (or restructure into a small package if you prefer — but
keep the `<cmd> <pack_dir>` entry point and the exact stdout contract).

**Phase 1 — Profile the data (understand before you code).**
Read each of the five CSVs; note columns, identifier formats, organism conventions, and where
they overlap. Confirm the join keys: **primary = UniProt accession**; **secondary = gene symbol
+ organism**. Record what "normal" looks like so you can tell defects from noise.

**Phase 2 — Link & deduplicate → golden records.**
Group rows across sources that refer to the same protein. Collapse duplicates into one target
identity. For each, choose the canonical **gene symbol** and **primary_accession** and record
the contributing **sources**. Compute `unique_target_count = len(golden_records)`.

**Phase 3 — Authority resolution layer.**
Build the cached/batched/retrying client from §4. Resolve each unique entity once and keep its
facts (primary accession, secondaries, organism+taxid, approved symbol, synonyms, xrefs).

**Phase 4 — Defect detection, classification, and evidence.**
Apply the decision rules in §6. For each real defect, produce a finding with `observed`,
`correct`, `retrieved_evidence` (verbatim authority facts), `evidence_source` (the URL/endpoint),
`severity`, and `classification`. Do **not** flag harmless variance; do **not** touch `pmid`.

**Phase 5 — Assemble & emit.**
Print the single JSON object to stdout (contract in §3). Nothing else on stdout.

**Phase 6 — Validate (see §8 and `tests/README.md`).**
Build tiny synthetic fixtures with known answers (including negative tests), assert exact output,
confirm the run is well under 5 minutes, and confirm it behaves correctly on a *different*,
schema-identical directory.

---

## 6. Defect taxonomy & decision rules

Classify every finding. The three canonical classes (extend only if the data clearly warrants,
and keep labels consistent):

| Classification | What it is | Typical severity |
|---|---|---|
| **wrong mapping** | An identifier points at a *different* protein, or the wrong **organism**. Corrupts the master. | high |
| **stale-but-valid label** | An *old but legitimate* gene symbol / a **secondary** accession — outdated, not incorrect. | low–medium |
| **duplicate identity** | Two records that resolve to the *same* protein. Inflates counts / splits truth. | medium |

**Decision rules (defect vs. legitimately messy):**
- **Symbol differs from the authority's approved symbol** →
  - if the source symbol appears in the authority's **synonyms/previous names** → *stale-but-valid* (report as such, with the current approved symbol as `correct`);
  - if it belongs to a **different gene/protein** → *wrong mapping*.
- **Accession is a secondary of another entry** → *stale-but-valid / merged*; `correct` = the primary accession it was merged into.
- **Organism/taxid disagrees with the authority** for the same accession → *wrong mapping*.
- **Two records resolve to the same primary accession** → *duplicate identity*; keep one golden record.

**Explicitly NOT defects (do not flag):**
- Formatting variance: `Homo sapiens` vs `H. sapiens`, case, spacing, name ordering.
- Valid `binding_type` values (`Ki`, `IC50`, `Kd`, `EC50`).
- Any apparent conflict derived from a `pmid` (internal numbers — off-limits).
- Reviewed vs. unreviewed tier (Swiss-Prot vs TrEMBL) by itself.

---

## 7. Keep an investigation record (this is graded)

Your working transcript is a **required, graded artifact** and must reflect **your own**
investigation. As you work, capture: what you checked on every row and how you decided that
list was complete; which fields you relied on and where you cross-checked; your defect-vs-messy
decision rules; **at least one thing you investigated and chose NOT to flag, and why**; how you
validated the tool; and what you'd harden for production. You will distil this into the approach
summary (the seven questions in `challenge-brief.md`).

---

## 8. Validate before you trust it

- Build synthetic fixtures under `tests/fixtures/<case>/` (mini packs + `expected.json`):
  clean baseline; wrong mapping; stale-but-valid; duplicate; **harmless-variance negative test**;
  **`pmid`-collision negative test**. See `tests/README.md`.
- Mock/stub the authority in unit tests so they're fast and deterministic (no network in tests).
- Assert: valid contract JSON; `unique_target_count == len(golden_records)`; findings carry both
  `observed` and `correct`; harmless cases produce no findings.
- Run on `target-data/exam/` and sanity-check the output by eye.
- Time it: comfortably **under 5 minutes**. Run on a *copied, altered* pack to confirm it doesn't
  overfit to `exam/`.

---

## 9. Deliverables (produce all three)

1. **GitHub repo** — the working tool + supporting files, structured like the challenge sample
   repo (`https://github.com/EliLillyCo/Claude-Olympics-Sample-Repo`; private — mirror it if you
   can access it, otherwise keep this repo's layout). Tool runs as `<cmd> <pack_dir>` and prints
   the contract JSON.
2. **Investigation export (markdown)** — your own working transcript (text only, < ~50 pages,
   no images). Save under `submission/` or upload per the challenge form.
3. **Approach summary** — fill in `approach-summary.md`, answering the seven questions, **≤ 1,500
   words**.

See `SUBMISSION.md` for step-by-step packaging and the final checklist.

---

## 10. Definition of done (acceptance criteria)

- [ ] `python reconcile.py <pack_dir>` prints exactly one valid JSON object matching §3 (incl.
      `severity` + `classification`); stderr-only for logs.
- [ ] `unique_target_count == len(golden_records)`; golden records have `gene`,
      `primary_accession`, `sources`.
- [ ] Every finding is NAILED (has `observed` **and** `correct`) with authority `retrieved_evidence`
      and `evidence_source`, and a sensible `severity` + `classification`.
- [ ] No `pmid` is ever fetched or flagged; no harmless variance is flagged.
- [ ] Runs in **< 5 min**; correct on a **different, schema-identical** pack; authority calls are
      cached/batched/retried and fail safe.
- [ ] `target-data/` is untouched; no secrets committed; `.gitignore` in place; deps (if any) via
      Artifactory.
- [ ] All three artifacts produced; `SUBMISSION.md` checklist fully ticked; findings re-verified
      against the authority at submission time.

---
*Start at §1. When in doubt about a value, resolve it against the authority and let the evidence
decide. Optimise for correctness on unseen data and for precision — a proven, well-classified
finding beats a speculative one.*
