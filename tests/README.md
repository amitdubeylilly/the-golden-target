# Tests — validating the tool before the exam

This maps to challenge question #5 ("How did you validate your tool before running it on the
exam?"). It is **guidance for how to test** — the actual tests are for the implementer to write.

## Why you can't just test against `target-data/exam/`

The graded run happens on a **hidden dataset with the same schema** that you never see. Passing
on `exam/` proves little if the logic is overfit to it. Build tests from **small, hand-made
fixtures** with *known* correct answers so you can assert exact behaviour.

## Suggested fixtures (build under `tests/fixtures/<case>/`)

Each fixture is a mini "pack" — a directory holding the five `source_*.csv` files with only a
handful of rows — plus an `expected.json` you assert against.

Recommended cases, one behaviour each:
1. **Clean baseline** — a few consistent targets, no defects → expect golden records, empty `findings`.
2. **Wrong mapping** — an accession/organism that points at a different protein → expect a
   `classification: wrong mapping` finding with both `observed` and `correct`.
3. **Stale-but-valid label** — an old gene symbol that the authority lists as a prior symbol →
   expect `classification: stale-but-valid` (and NOT treated as wrong).
4. **Duplicate identity** — two rows resolving to the same protein → expect one golden record
   and a `duplicate` finding; check `unique_target_count`.
5. **Harmless variance (negative test)** — `Homo sapiens` vs `H. sapiens`, case/spacing →
   expect **no** finding (precision guard).
6. **pmid trap (negative test)** — a `pmid` that collides with a real, unrelated paper →
   expect it is neither fetched nor flagged.

## What to assert

- Output is valid JSON matching the contract exactly (fields incl. `severity`, `classification`).
- `unique_target_count` equals the number of `golden_records`.
- Findings are NAILED (carry both `observed` and `correct`), not just DETECTED.
- Runs well within the **5-minute** budget (mock/stub the authority in tests so they're fast
  and deterministic — don't hit the network in unit tests).

## Also verify manually

- Run on `target-data/exam/` and eyeball the output for sanity.
- Re-verify a sample of findings against the live authority near submission time (reference
  databases evolve).

_Note: keep test fixtures small and synthetic — do not copy or modify `target-data/`._
