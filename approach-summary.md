# Approach Summary — The Golden Target

---

## 1. Audit strategy — what did you check for every row, and how did you decide that list was complete?

For every row across all five sources the tool checks: (a) whether the UniProt accession is a current primary or a secondary/merged accession; (b) whether the gene symbol matches the authority's approved symbol, is a listed synonym (stale-but-valid), or belongs to a different protein entirely (wrong mapping); and (c) whether the organism/taxon agrees with the authority. For ChEMBL rows it additionally checks whether one ChEMBL ID is reused across rows — either for the same protein under two accessions (duplicate identity) or for two genuinely different proteins (a collision). Publications are matched by `target_mention` and disambiguated from `context_sentence` text only — `pmid` is never fetched.

The checklist is complete because the challenge defines exactly three defect classes (wrong mapping, stale-but-valid label, duplicate identity) and every check maps to at least one. Cross-source and cross-accession checks catch duplicates; an explicit "not-a-defect" list (species formatting, binding types, Swiss-Prot/TrEMBL tier, `pmid`) is excluded to protect precision.

## 2. Identity validation — what fields did you rely on, and where did you cross-check?

The join key is the UniProt accession, resolved against the **EBI Proteins API** (`/proteins/api/proteins/{acc}`). Obsolete/secondary accessions 404 on the direct endpoint, but each *current primary* lists them in its `secondaryAccession` field — so the tool resolves every accession once, builds a **secondary→primary index** from the primaries it retrieves, and uses that index to resolve the 404s **through EBI itself**. On the exam this resolves 100% of accessions with zero calls to any other host. The UniProt REST service is retained only as a rare, explicitly-logged fallback for the edge case where a secondary's primary is absent from the pack; if resolution ever degrades the tool prints a loud `WARNING` rather than silently emitting a corrupted master. From each entry I extract primary accession (settles merges), approved gene name and synonym list (distinguishes stale-but-valid from wrong), organism + taxon (settles species), and protein name (used to decide conflict direction). ChEMBL IDs are validated against ChEMBL's own API (same host as EBI).

## 3. Decision rules — what made something a defect rather than legitimately messy?

- **Wrong mapping (high)**: the gene symbol does not match the authority's approved symbol *and* is not a listed synonym. When symbol and accession disagree, the tool decides *which* is wrong by corroboration — comparing the row's own descriptive name (`pref_name`/`target_name`/`protein_name`) against the authority protein names of the accession vs. the symbol. If the row describes the symbol's protein, the **accession** is the defect (and the correct accession is reported); otherwise the symbol is. A ChEMBL ID pointing at two different proteins is resolved by asking ChEMBL for the true target and flagging **only** the mismatching row.
- **Stale-but-valid label (low–medium)**: a secondary/merged accession, or an old gene symbol present in the authority's synonym list. Outdated, not incorrect.
- **Duplicate identity (medium)**: one ChEMBL ID recorded against two accessions of the same protein (the stale accession is reported; the redundant stale-accession finding is suppressed to avoid double-counting).
- **Not a defect**: species formatting, binding types, Swiss-Prot vs TrEMBL, anything derived from `pmid`.

## 4. One thing you investigated and chose NOT to flag — and why.

The `pmid` column contains values (e.g. 30022350) that coincidentally match real PubMed records for unrelated papers, because they are internal reference numbers, not literature links. Fetching them and flagging the "mismatch" would be a false positive the brief explicitly warns about, so `pmid` is never fetched. Ambiguous mentions are resolved from `context_sentence` instead — and generically: the tool matches the full protein name in the sentence against authority protein names, rather than hard-coding any single case, so it generalises to the hidden dataset. Two genuinely-correct rows were also deliberately **not** flagged: the `PDE7A` row sharing a ChEMBL ID with an intruder (ChEMBL confirms the ID is PDE7A), and legitimate secondary-accession usage that is merely stale.

## 5. How did you validate your tool before running it on the exam?

Eight self-contained tests build tiny 5-CSV packs in a temp dir and patch the authority's **HTTP layer** with canned EBI/ChEMBL JSON — so they exercise the real response parser, the secondary→primary index, the ChEMBL-collision path, and the conflict-direction logic (not just a mocked class), while staying fast and network-free. Cases cover: clean baseline (no findings), wrong-mapping (symbol direction), stale synonym, duplicate identity (with a no-double-count assertion), harmless variance (no findings), the `pmid` trap, a ChEMBL collision (asserts only the intruder is flagged), and an accession-direction conflict. Every test asserts the output contract, that `unique_target_count == len(golden_records)`, and that each finding carries both `observed` and `correct`. I then ran on `target-data/exam/` and cross-checked the key findings against the live EBI and ChEMBL APIs.

## 6. How did you work with Claude — what did you delegate, and what did you verify yourself?

Claude analysed the data, designed the EBI-first pipeline, implemented resolution/detection/assembly with caching, threading and retries, and wrote the tests. I verified the substance against live authorities: that the secondary accessions really are listed under their primaries on EBI (making the second host unnecessary); that `Q9P1W9` is **PIM2** and ChEMBL `CHEMBL2147` is **PIM1** — proving the `CHEMBL2147` row's *accession* is the defect (correct `P11309`), not its symbol; the same accession-direction logic for the `KISS1`/`Q969F8` (KISS1R) row (correct `Q15726`); that `CHEMBL3012` is genuinely **PDE7A**, so only the PDE10A row is flagged, with a concrete correction and ChEMBL evidence. I confirmed the golden records are unchanged (609), all 55 findings cite the nominated authority (`www.ebi.ac.uk`), the output is deterministic, and the cold run is ~27s — well under the 5-minute budget.

## 7. What would you harden before running this in production?

- **Rate limiting**: token-bucket/adaptive throttling on 429s rather than fixed retry sleeps.
- **Cache management**: TTL expiry (UniProt updates) and a real store (SQLite) instead of a JSON file.
- **Resolution SLAs**: the tool already warns loudly and reports the exact accessions when resolution degrades; production would turn that into a hard failure/alert threshold.
- **Schema validation**: validate CSV headers at load with clear errors for renamed/missing columns.
- **Monitoring**: log resolution success rate, cache hit rate and per-class defect counts; diff scheduled re-runs to catch authority-side changes.
- **Conflict direction**: log the corroboration scores so borderline symbol/accession decisions are auditable, and add a human-review queue for low-confidence cases.

---

*Word count: ~890 / 1,500*
