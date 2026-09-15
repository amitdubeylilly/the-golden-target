The Golden Target

## Overview

The 'Golden' Target.

## Challenge Brief

Your discovery informatics group is standing up a target master — one trusted "golden record" per drug-discovery target — by reconciling five overlapping source extracts (ChEMBL, UniProt, BindingDB, an internal target registry, and a literature-mention table). The extracts disagree. Some disagreements are harmless. Some are real that can corrupt the master.

**Your job:** Build a reconciliation tool that produces clean golden records and flags the real defects with proof — without crying wolf on the harmless ones.

## What Makes This Challenging

- The data contains defects of distinct kinds.
- Each defective row is internally consistent — nothing looks wrong until you check it against an authoritative external source.

## Choosing an Authority

The EBI Proteins external endpoint as a public source is sufficient. This in itself can help you figure out (including but not limited to):

- what organism it belongs to
- what its approved symbol is today
- what other symbols it has been known by
- what it was merged into, or what has been merged into it
- what it is cross-referenced to in other databases

## What You Receive

| Pack | Contains |
|------|----------|
| exam/ | 5 source files (~600+ targets, 3,000+ rows) |

## Your Task

Build a reconciliation tool that runs as `<cmd> <pack_dir>` and prints exactly:

```json
{
  "unique_target_count": <int>,
  "golden_records": [{"gene": "...", "primary_accession": "...", "sources": ["..."]}],
  "findings": [ <your reported defects — see the evidence contract below> ]
}
```

Run it on exam/, verify every flagged issue against an authoritative source, and report.

Each finding must carry, as data:

- `observed` — the defective value as it appears in the file
- `correct` — the corrected value
- `retrieved_evidence` — what the authority actually returned when you resolved the entity (the identity, organism, merge target, approved symbol, or cross-reference)
- `evidence_source` — where you got it (endpoint/connector)

## IMPORTANT

Grading of defect surfacing is objective:

- A defect scores full marks (**NAILED**) only when your findings contain both the observed and corrected values.
- A finding that says "this looks wrong" without the retrieved correction is **DETECTED**, and earns a quarter of full marks.
- Absent entirely: **MISSED**.

## One Thing That Is NOT a Defect

The `pmid` column in `source_publications.csv` contains internal reference numbers — they are not links to the literature. Fetching them tells you nothing about these rows, and because they are plain numbers, some coincide with real PubMed records for entirely unrelated papers. So a retrieved title, journal, or year that contradicts the row is an artifact of those synthetic numbers, not a data-quality defect: do not fetch them, and do not flag them. Ambiguous literature mentions are resolvable entirely from the `context_sentence` text shipped in the file.

## Sample Repo Reference
<https://github.com/EliLillyCo/Claude-Olympics-Sample-Repo>

## Submission (Three Artifacts)

1. **GitHub repo.**
2. **Claude chat export (markdown)** — your investigation: how you audited systematically, what you verified and how, what you decided not to flag and why. Your transcript must reflect your own investigation — it is a graded artifact and the record of your individual work.
3. **Approach summary** (≤1,500 words total — a ceiling, not a target) answering seven questions:
   1. What was your audit strategy — what did you check for every row, and how did you decide that list was complete?
   2. How did you validate the identities — what fields did you rely on, and where did you cross-check?
   3. State your decision rules: what made something a defect rather than legitimately messy?
   4. Describe one thing you investigated and chose NOT to flag, and why.
   5. How did you validate your tool before running it on the exam?
   6. How did you work with Claude — what did you delegate, and what did you verify yourself?
   7. What would you harden before running this in production?

## Scoring (100 pts)

| Dimension | Pts |
| ----------- | ----- |
| Reconciliation accuracy | 55 |
| Defect surfacing | 25 |
| Investigation rigor | 20 |

## Guidance

- Classify what you find: a wrong mapping, a stale-but-valid label, and a duplicate identity are different problems with different severities.
- Precision can count against you when you get it wrong.
- Make your tool emit its evidence.

**All the Best!**
