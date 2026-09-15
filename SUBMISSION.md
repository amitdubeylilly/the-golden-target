# Submission Guide — The Golden Target

Everything needed to package and submit. The challenge requires **three artifacts**. This
file explains what each one is, how to produce it, and a final pre-submit checklist.

> Sources of truth: `challenge-brief.md` (the ask) and `target-data/verification_starter.md`
> (the tool contract + runtime/hidden-dataset rules). `README.md` is the repo index.

---

## The three required artifacts

### 1. GitHub repository
The tool plus its supporting files, structured like the challenge's sample repo
(`https://github.com/EliLillyCo/Claude-Olympics-Sample-Repo` — private/internal; reconcile
this scaffold's layout with it if it differs).

Must be true of the repo:
- The tool runs as **`<cmd> <pack_dir>`** and prints the contract JSON to **stdout**
  (see `README.md` → *Tool contract* for the exact shape).
- It completes each pack in **under 5 minutes** and works on an **unseen dataset with the
  same schema** (do not overfit to `target-data/exam/`).
- `findings[]` include **`severity`** and **`classification`** (not just the four brief fields).
- It **never fetches or flags `pmid`** values from `source_publications.csv`.

Suggested layout in this scaffold:
```
reconcile.py            # tool entry point
agent_config.json       # grading agent configuration
requirements.txt        # dependencies (stdlib-only)
tests/                  # self-validation (see tests/README.md)
  test_reconcile.py     # 8 tests with mocked API
  fixtures/             # synthetic test packs
README.md               # index / contract
challenge-brief.md      # official brief
approach-summary.md     # artifact #3 (below)
resources/              # domain background
target-data/            # READ-ONLY data pack (do not modify, do not commit changes to)
```

### 2. Claude chat export (markdown)
The graded record of **your own investigation** — how you audited, what you verified and how,
and what you decided *not* to flag and why.

How to produce it:
- Export the Claude conversation as **Markdown (.md)**.
- **Keep it under ~50 pages, text only — exclude images** (per the challenge's upload note).
- Save it in the repo (suggested: `submission/chat-export.md`) or upload it to the submission
  form directly, per the challenge instructions.

### 3. Approach summary (≤ 1,500 words)
Answer the seven questions. Use the template already in **`approach-summary.md`**.

---

## Dependencies — Lilly policy (important)

Per organization policy, **all packages must be pulled from JFrog Artifactory**; public
PyPI/NPM are prohibited. Practical guidance:
- **Prefer the Python standard library** (`csv`, `json`, `argparse`, `urllib`) so the tool
  needs *no* third-party packages — this also helps the 5-minute budget and portability.
- If a dependency is unavoidable, configure `pip` to use the Lilly **Artifactory** index and
  pin it in `requirements.txt`. See the *Artifactory | Developer Platform Front Door* for
  access/setup.

---

## Pre-submission checklist

Correctness & contract
- [ ] Output is a single JSON object with `unique_target_count`, `golden_records[]`, `findings[]`.
- [ ] `golden_records[]` carry `gene`, `primary_accession`, `sources`.
- [ ] `findings[]` carry `gene`, `observed`, `correct`, `retrieved_evidence`, `evidence_source`,
      `severity`, `classification`.
- [ ] Every flagged defect includes **both** `observed` and `correct` (NAILED, not just DETECTED).

Robustness
- [ ] Runs as `<cmd> <pack_dir>` and prints only the JSON to stdout.
- [ ] Completes a pack in **< 5 minutes**.
- [ ] Produces sensible output on a **different, schema-identical** directory (not just `exam/`).
- [ ] Authority lookups are batched/cached/retried; handles missing or slow responses gracefully.

Precision & correctness of judgment
- [ ] `pmid` values are never fetched and never flagged.
- [ ] Harmless variance (e.g. `Homo sapiens` vs `H. sapiens`, case/spacing) is **not** flagged.
- [ ] Findings **re-verified against the authority at submission time** (reference DBs evolve).

Artifacts
- [ ] Repo pushed and structured per the sample repo.
- [ ] Chat export (markdown, text-only, < ~50 pages) included/uploaded.
- [ ] `approach-summary.md` completed, **≤ 1,500 words**.

Hygiene
- [ ] `target-data/` unmodified.
- [ ] No secrets/tokens committed; `.gitignore` in place.
