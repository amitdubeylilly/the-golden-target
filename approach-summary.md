# Approach Summary — The Golden Target

---

## 1. Audit strategy — what did you check for every row, and how did you decide that list was complete?

For every row across all five sources, the tool checks: (a) whether the UniProt accession resolves to a current primary accession or is secondary/merged, (b) whether the gene symbol matches the authority's approved symbol or is a known synonym, and (c) whether the organism/taxon agrees with the authority. For ChEMBL rows, it additionally checks whether the same ChEMBL ID maps to multiple different proteins (ID collision). For publications, it matches `target_mention` against known gene symbols and disambiguates ambiguous mentions (e.g., "PSA") using `context_sentence` keywords — never by fetching `pmid` values.

The checklist was complete because the challenge's defect taxonomy defines exactly three defect classes (wrong mapping, stale-but-valid label, duplicate identity), and each check maps to at least one class. Cross-source checks (same primary accession from different original accessions) catch duplicates. The "not-a-defect" list (species formatting, binding types, pmid, review status) was explicitly excluded.

## 2. Identity validation — what fields did you rely on, and where did you cross-check?

The primary join key is the UniProt accession. Each source's accession column (`accession`, `uniprot_id`, `uniprot_ref`) is resolved against the EBI Proteins API (`/proteins/api/proteins/{accession}`). For 404 responses (obsolete/merged), the UniProt REST API (`rest.uniprot.org`) provides the merge target. From each resolved entry, I extract: the primary accession (settles merges), the approved gene name (settles symbol currency), the synonym list (distinguishes stale-but-valid from wrong), and organism + taxonomy ID (settles organism mismatches). Gene symbol + organism serve as secondary keys for matching publications to golden records.

## 3. Decision rules — what made something a defect rather than legitimately messy?

- **Wrong mapping (high)**: the source's gene symbol does not match the authority's approved symbol AND is not listed in the authority's synonyms/previous names — it belongs to a different protein. Also: a ChEMBL ID mapping to two different primary accessions.
- **Stale-but-valid label (low–medium)**: the source uses a secondary/merged accession (authority's primary differs from what the source claims) or an old gene symbol that appears in the authority's synonym list. Outdated, not incorrect.
- **Duplicate identity (medium)**: two records in the same or different sources resolve to the same primary accession after authority lookup.
- **Not a defect**: species formatting variance (`Homo sapiens` vs `H. sapiens` vs `human`), binding type values, Swiss-Prot vs TrEMBL tier, anything derived from `pmid`.

## 4. One thing you investigated and chose NOT to flag — and why.

The `pmid` column in `source_publications.csv` contains values like 30022350 that coincidentally match real PubMed records. I confirmed that fetching these returns titles/journals for completely unrelated papers — because the values are internal reference numbers, not literature links. Flagging the apparent "mismatch" between the context sentence and a fetched PubMed title would be a false positive. The challenge brief explicitly warns about this trap. Instead, I resolved ambiguous target mentions (e.g., "PSA") entirely from the `context_sentence` text, using domain keywords (prostate/kallikrein → KLK3, aminopeptidase/puromycin → NPEPPS).

## 5. How did you validate your tool before running it on the exam?

I built six synthetic test fixtures under `tests/fixtures/`, each a minimal 5-CSV pack with known answers: (1) clean baseline — no defects expected; (2) wrong mapping — planted gene/accession mismatch; (3) stale-but-valid — old synonym; (4) duplicate identity — two accessions resolving to one primary; (5) harmless variance — species formatting differences only; (6) pmid trap — pmid collision with real paper. Tests mock the API client so they're fast, deterministic, and network-independent. I verified the output JSON shape, that `unique_target_count` equals `len(golden_records)`, that every finding is NAILED (has both `observed` and `correct`), and that negative tests produce no findings. I also ran on `target-data/exam/` and spot-checked findings against the live EBI API.

## 6. How did you work with Claude — what did you delegate, and what did you verify yourself?

I used Claude to: analyze the data files and identify planted defects (cross-source accession mismatches, ChEMBL ID collisions, BindingDB secondary accessions, publication ambiguities); design the reconciliation pipeline (loading, linking, API resolution, defect detection, golden record assembly); implement the tool with proper caching, threading for API calls, and retry logic; and generate test fixtures. I verified myself: the API response shape (by making test curl calls), the correctness of key findings against the live EBI Proteins API (PIM1/PIM2 swap, KISS1/KISS1R confusion, CHEMBL3012 collision), the cold-start runtime (2:42, well under 5 minutes), and that the output contract matched the specification exactly.

## 7. What would you harden before running this in production?

- **Rate limiting**: implement token-bucket or sliding-window rate limiting instead of fixed delay, monitoring for 429 responses and adapting.
- **Cache management**: add TTL-based cache expiry (e.g., 24h), since UniProt entries get updated. Persist to a proper store (SQLite or Redis) instead of a JSON file.
- **Schema validation**: validate input CSV schemas at load time, with clear error messages for missing/renamed columns.
- **Monitoring & alerting**: log metrics (resolution success rate, cache hit rate, defect counts per class), alert on sudden changes.
- **Re-verification pipeline**: scheduled re-runs that diff against previous results to catch authority-side changes.
- **Parallelism tuning**: adjust thread pool size based on API rate limits; consider async I/O for higher throughput.
- **Input sanitization**: handle malformed accessions, empty rows, and encoding issues more robustly.

---

*Word count: ~830 / 1,500*
