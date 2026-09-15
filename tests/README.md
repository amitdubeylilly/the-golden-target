# Tests — validating the tool before the exam

This maps to challenge question #5 ("How did you validate your tool before running it on the
exam?"). The tests live in `test_reconcile.py` and are **self-contained**: each one builds a tiny
5-file pack in a temporary directory and patches the authority's HTTP layer with canned
EBI/ChEMBL JSON. No on-disk fixtures, no network.

## Why not just test against `target-data/exam/`

The graded run happens on a **hidden dataset with the same schema** that you never see. Passing
on `exam/` proves little if the logic is overfit to it. The tests assert *exact behaviour* on
small, hand-made inputs with known answers instead.

## How the tests work

`test_reconcile.py`:

- `write_pack(tmp_path, rows)` writes the five `source_*.csv` files (correct headers) into a
  pytest `tmp_path`, so each case is an isolated mini "pack".
- `fake_http_json` is patched over `Authority._http_json`, returning canned responses from
  `EBI_DB` / `CHEMBL_DB`. This is a **HTTP-layer** mock, not a whole-class mock, so the real
  response parser, the secondary→primary index, the ChEMBL-collision path, and the
  conflict-direction logic all execute — while staying fast, deterministic, and offline.

Run them with:

```bash
python -m pytest tests/ -q          # expect: 8 passed
```

## What each case covers

1. **clean_baseline** — three consistent targets → golden records, **empty** `findings`.
2. **wrong_mapping (symbol direction)** — gene symbol disagrees with the accession's authority
   gene and the symbol's protein isn't in the pack → `wrong mapping`, correction is the symbol.
3. **stale_label** — an old symbol (`ERBA2`) the authority lists as a synonym of `THRB` →
   `stale-but-valid label` (not treated as wrong).
4. **duplicate_identity** — one ChEMBL ID on two accessions of the same protein
   (`P29317` + secondary `B5A968`) → one golden record + a `duplicate identity` finding;
   asserts the accession is **not** also double-reported as stale.
5. **harmless_variance (negative)** — `Homo sapiens` / `H. sapiens` / `human` → **no** findings.
6. **pmid_trap (negative)** — publications carry `pmid` values → never fetched, never flagged;
   the publication is still attached to the golden record's `sources`.
7. **chembl_collision_flags_only_intruder** — one ChEMBL ID on two *different* proteins; ChEMBL
   is the authority for the true target, so **only the intruder row** is flagged (the correct
   row is not), with a concrete `correct` value.
8. **conflict_accession_direction** — a row labelled `PIM1` with a PIM1 `pref_name` but PIM2's
   accession → corroboration shows the **accession** is the defect (correct = PIM1's accession),
   not the symbol.

## What every case asserts

- Output is valid JSON matching the contract exactly (including `severity`, `classification`).
- `unique_target_count == len(golden_records)`.
- Every finding is NAILED — carries both `observed` and `correct` (plus all seven contract keys).
- Negative cases (harmless variance, pmid trap) produce **no** findings — the precision guard.

## Also verify manually near submission

- Run on `target-data/exam/` and eyeball the output (expect 609 records / 55 findings; no
  fallback or degradation warnings on stderr).
- Re-check a sample of findings against the live EBI / ChEMBL APIs — reference databases evolve.

_Note: never copy or modify `target-data/` — it is the read-only validation ground truth._
