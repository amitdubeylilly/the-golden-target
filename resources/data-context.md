# Data Context — The Golden Target

> **Purpose of this file.** Background so anyone picking up the challenge understands
> *what the data is*, *where it comes from*, *what the words mean*, and *why a "golden
> record" of a drug-discovery target matters*. This is orientation, **not** the solution
> — it does not analyse the exam rows or name specific defects. It exists so that when we
> do the reconciliation, every decision is grounded in what these databases actually are
> and how they behave in the real world.
>
> Compiled from the resource links shared in the announcement plus the two Lilly decks in
> this folder. Sources are listed at the bottom.

---

## 1. The one-paragraph version

A drug-discovery **target** is (almost always) a **protein**, and a protein is the
product of a **gene**. Five different databases each describe an overlapping set of these
protein targets, and each one uses its own identifiers, its own naming style, and its own
level of curation. Because they were built by different people at different times, they
**disagree**. Some disagreements are cosmetic (spacing, capitalisation, an old-but-still-
correct name). Some are real errors that would corrupt a master list (an identifier that
points at the wrong protein, the wrong organism, or a duplicate of a record that already
exists). The task is a **Master Data Management** problem dressed in biology: build one
trustworthy **golden record** per target and flag the real defects — proven against an
authoritative external source (**UniProt via the EBI Proteins API**) — without raising
false alarms on the harmless stuff.

---

## 2. The biology you need (and only that)

### 2.1 Gene → protein → target
- A **gene** is the basic unit of heredity, made of DNA. Some genes carry the instructions
  to build **proteins**. Humans have roughly **~20,000** protein-coding genes.
- Genes are tracked by a long **name** *and* a short **symbol** (e.g. the gene
  "cystic fibrosis transmembrane conductance regulator" has the symbol **CFTR**). This
  name-vs-symbol distinction is central to this challenge: the source files carry gene
  **symbols**, and symbols are exactly the kind of thing that gets abbreviated,
  mistyped, or left at an old value.
- A **biological target** ("drug target") is anything in the body a drug binds to in
  order to change its function. In practice targets are overwhelmingly **proteins** —
  receptors (especially GPCRs), enzymes (kinases, proteases…), ion channels, transporters,
  nuclear receptors — with some nucleic-acid targets. A drug can **agonise** (activate),
  **antagonise** (block), or otherwise modulate its target.

### 2.2 Why identity is slippery
- **Gene symbols change over time.** A protein can have an *approved* symbol today plus a
  list of *previous* symbols and *aliases* it was formerly known by. An old symbol is not
  wrong — it is **stale but valid**. Telling "stale-but-valid" apart from "actually wrong"
  is the crux of precision in this challenge.
- **Organism matters.** The same gene name can exist in human, mouse, rat, etc. Human is
  *Homo sapiens*, **NCBI taxonomy ID 9606**. A record that quietly attaches a human symbol
  to a non-human accession (or vice-versa) is a genuine mapping defect, not a cosmetic one.
- **Accessions get merged.** When two database entries turn out to describe the same
  protein, they are merged; the losing identifier becomes a **secondary accession** that
  still resolves, but the **primary accession** is the canonical one to keep in a golden
  record.

---

## 3. Where "targets" sit in drug discovery (the "why this matters")

From the two Lilly decks in this folder (BRIDGE 2021 "Big Picture Drug Discovery" and the
2024 Discovery onboarding), the R&D pipeline runs:

```
Discovery ─────────────────────────────► Development ──► Manufacturing
 Target → Hit → Lead → Candidate Selection (CS) → First Human Dose (FHD) → Phases I–III → Launch
```

- **Target Identification & Validation is the very first step.** Everything downstream —
  assays, hit generation, lead optimisation, the molecule that eventually reaches patients —
  is built on top of a target the organisation has decided to pursue. Lilly's own milestone
  definition of **"Target"** is: *sufficient evidence that modulating the target will impact
  a disease phenotype, and it fits the therapeutic area's strategy.*
- Targets are proposed and validated by **Therapeutic Area (TA)** teams and supported by
  discovery functions (at Lilly: **BioTDR** / biotech discovery, **DCRT** / chemistry,
  **NTM** / new modalities, etc.). Validation draws on literature, human genetics, patient
  samples, tool molecules, and in-vitro/in-vivo assays.
- **So a "target master" is foundational infrastructure.** If the single trusted record of
  a target is wrong — wrong protein, wrong organism, a duplicate — that error propagates
  into assay design, screening, competitive intelligence, and portfolio decisions. That is
  precisely why one bad mapping "can corrupt the master," and why proof (not a hunch) is
  required before flagging.

*(The Lilly decks are domain colour, not required reading to solve the task. The useful
takeaway is simply: targets are step one, and trustworthy target identity is load-bearing.)*

---

## 4. The five sources — what each database actually is

The exam ships five CSVs under `target-data/exam/`. Here is what each underlying database
is in the real world, followed by the columns actually present in the file.

### 4.1 UniProt — `source_uniprot.csv`  *(the identity backbone)*
- **What it is:** the Universal Protein Resource — a freely accessible, central repository
  of protein sequence + functional data, maintained by the **EMBL-EBI / SIB / PIR**
  consortium. It is *the* reference for protein identity.
- **Two tiers of curation, and this matters:**
  - **UniProtKB/Swiss-Prot** — **reviewed**, manually curated, high-confidence, non-redundant.
  - **UniProtKB/TrEMBL** — **unreviewed**, automatically annotated.
- **Accessions:** every entry has a stable **accession** (e.g. `Q06418`). Sequences from the
  same gene + species are merged into one entry; superseded accessions live on as
  **secondary accessions**. The **primary accession** is the canonical identifier.
- **Columns in file:** `accession, entry_name, gene_names, protein_name, organism,
  reviewed, length, database`
  - `reviewed` / `database` will say Swiss-Prot (reviewed) vs TrEMBL — a curation-quality signal.
  - `entry_name` looks like `TYRO3_HUMAN` (mnemonic, includes the organism suffix).

### 4.2 ChEMBL — `source_chembl.csv`  *(bioactivity / medicinal chemistry)*
- **What it is:** a **manually curated** database of bioactive molecules with drug-like
  properties, run by EMBL-EBI. It ties chemistry, bioactivity, and genomic/target data
  together to help translate biology into drugs. Part of the ELIXIR core data resources.
- **Target identifier:** `chembl_id` (e.g. `CHEMBL1974`), each carrying its own view of the
  protein target it maps to.
- **Columns in file:** `chembl_id, pref_name, target_type, accession, gene_symbol,
  organism, tax_id, target_confidence`
  - `target_type` here is typically `SINGLE PROTEIN`.
  - `tax_id` is the NCBI taxon (9606 = human); `accession` should agree with UniProt.
  - `target_confidence` is ChEMBL's own confidence score for the target assignment.

### 4.3 BindingDB — `source_bindingdb.csv`  *(measured binding affinities)*
- **What it is:** the first public molecular-recognition database — measured **binding
  affinities** between candidate drug-target proteins and small drug-like ligands
  (hosted at UCSD). It imports well-defined protein targets from ChEMBL, PubChem BioAssays,
  literature, and patents.
- **Affinity vocabulary you'll see in `binding_type`:** `Ki`, `IC50`, `Kd`, `EC50` — all
  standard measures of how tightly a ligand binds / how potent it is. These are legitimate
  value types, **not** defects.
- **Columns in file:** `target_name, species, uniprot_id, gene_symbol, assay_count,
  binding_type`
  - Note `species` may appear as `Homo sapiens` **or** `H. sapiens` — a **formatting**
    inconsistency, i.e. the kind of harmless disagreement not to flag.

### 4.4 Internal target registry — `source_internal.csv`  *(the home-grown system)*
- **What it is:** a company's own hand-maintained target registry. Because it is populated
  manually and over years by different people, it is the most likely to carry typos, stale
  references, and inconsistent cross-links — this mirrors the classic MDM pain of a legacy
  in-house master.
- **Columns in file:** `internal_id, registered_name, gene_symbol, source_db, external_id,
  uniprot_ref, registered_by, registration_date, status`
  - `uniprot_ref` is the internal record's claim about which UniProt accession it maps to —
    a prime place for a cross-reference to have drifted or been mistyped.
  - `external_id` / `source_db` record where the entry was originally pulled from
    (e.g. ChEMBL, Manual).
  - `status` (e.g. `active`) and `registration_date` give provenance/timeliness signals.

### 4.5 Literature mentions — `source_publications.csv`  *(free-text target mentions)*
- **What it is:** a table of target *mentions* pulled from text, used to associate targets
  with the literature.
- **Columns in file:** `pmid, target_mention, context_sentence, journal, year`
- **⚠️ Critical trap — do NOT chase the `pmid`.** In this dataset the `pmid` column holds
  **internal reference numbers, not real PubMed IDs.** Because they are plain integers, some
  will coincidentally collide with real (unrelated) PubMed records. Fetching them tells you
  nothing true about the row, and any title/journal/year "conflict" you'd find is an artefact
  of that coincidence — **not** a data-quality defect.
- **The resolvable signal is `context_sentence`.** Ambiguous literature mentions are meant to
  be disambiguated entirely from the sentence text shipped in the file (which typically spells
  out the full protein name), not by looking anything up externally.

---

## 5. The authority — UniProt via the EBI Proteins API

The challenge nominates the **EBI Proteins external endpoint** (the programmatic front door
to UniProt) as a sufficient public source of truth. When you resolve an entity there you can
establish, per protein:

- **Identity** — the canonical entry and its **primary accession**.
- **Organism** — species name and NCBI **taxon ID** (human = 9606).
- **Approved symbol today** — the current gene symbol, plus…
- **Other symbols it has been known by** — previous names / synonyms (this is how you prove
  something is *stale-but-valid* rather than *wrong*).
- **Merge history** — what an accession **was merged into**, or what has been merged into it
  (i.e. primary vs **secondary accession** relationships).
- **Cross-references** — how the entry links out to other databases.

This is the correct arbiter precisely because each source file is *internally* consistent —
nothing looks wrong until you check it against this external ground truth.

*(EBI also hosts ChEMBL and, through UniProt, cross-references to many other resources; the
UniProt layer is the one that adjudicates protein identity.)*

---

## 6. The framing — Master Data Management & Data Quality

The task is a textbook **Master Data Management (MDM)** exercise applied to biology.

### 6.1 Golden records & MDM
- **MDM** is the discipline of making an organisation's shared master data uniform, accurate,
  and consistent — one authoritative version instead of many siloed copies.
- A **golden record** (a.k.a. **single version of the truth**) is the one trusted, consolidated
  record for an entity, built by matching and merging the best fields across sources.
- Core MDM operations that map directly onto this challenge:
  - **Record linkage / matching** — deciding that records in different files refer to the same
    protein (may need fuzzy matching for names, exact matching on accession).
  - **Deduplication** — collapsing multiple records of the same identity into one.
  - **Reconciliation** — resolving the disagreements between matched records.
  - **Source of record / authority** — deferring to UniProt when sources conflict.
  - **Data stewardship** — the judgement layer that decides what is a defect vs. acceptable variance.

### 6.2 Data-quality dimensions (the lens for classifying findings)
Standard data-quality dimensions, and how they show up here:

| Dimension | In this dataset |
|---|---|
| **Accuracy / correctness** | Does the accession/symbol actually denote this protein? (wrong mapping) |
| **Validity** | Is the value a real, resolvable identifier at all? |
| **Consistency** | Do the sources agree with each other and with UniProt? |
| **Uniqueness** | Is the same identity registered more than once? (duplicate) |
| **Completeness** | Are required identifiers present? |
| **Timeliness / currency** | Is a label current, or stale-but-valid (an old symbol)? |

### 6.3 A working defect taxonomy (severity differs — the brief says to classify)
- **Wrong mapping** — an identifier points at a *different* protein or the *wrong organism*.
  High severity: it actively corrupts the master.
- **Stale-but-valid label** — an old-but-legitimate gene symbol / a secondary accession.
  Lower severity: outdated, not incorrect.
- **Duplicate identity** — two records that resolve to the same protein.
  Medium severity: inflates counts, splits truth.
- **Harmless variance (NOT a defect)** — formatting differences like `Homo sapiens` vs
  `H. sapiens`, capitalisation, spacing, ordering. Flagging these is a **precision penalty**.

### 6.4 The evidence bar (why "it looks wrong" isn't enough)
The grading rewards *proven* corrections. A finding is strongest when it carries both the
**observed** (defective) value and the **correct** value, plus the **retrieved evidence** from
the authority and **where** that evidence came from. "This looks wrong" without the retrieved
correction is only partial credit. This is the data-quality principle that a finding must be
**actionable and traceable**, not just a flag.

---

## 7. Field crosswalk (how the sources join up)

The natural join key across sources is the **UniProt accession**; gene symbol + organism are
secondary keys used for matching and for sanity-checking the accession.

| Concept | UniProt | ChEMBL | BindingDB | Internal | Publications |
|---|---|---|---|---|---|
| Protein accession | `accession` | `accession` | `uniprot_id` | `uniprot_ref` | — |
| Gene symbol | `gene_names` | `gene_symbol` | `gene_symbol` | `gene_symbol` | `target_mention` |
| Protein name | `protein_name` | `pref_name` | `target_name` | `registered_name` | `context_sentence` |
| Organism | `organism` | `organism`/`tax_id` | `species` | — | — |
| Source's own ID | `entry_name` | `chembl_id` | — | `internal_id`/`external_id` | `pmid` (internal!) |
| Curation/quality hint | `reviewed` | `target_confidence` | `assay_count` | `status`/`source_db` | — |

---

## 8. Mini-glossary

**Accession** — stable UniProt identifier for a protein entry (e.g. `Q06418`). **Primary** =
canonical; **secondary** = superseded-but-still-resolves. •
**Agonist / antagonist** — a molecule that activates / blocks a target. •
**BindingDB** — public DB of measured protein–ligand binding affinities. •
**ChEMBL** — manually curated bioactivity/medicinal-chemistry database (EMBL-EBI). •
**EBI (EMBL-EBI)** — European Bioinformatics Institute; hosts UniProt, ChEMBL, the Proteins API. •
**Gene symbol** — short abbreviation of a gene name; has an approved current form + previous forms/aliases. •
**Golden record** — the single trusted, consolidated record for an entity. •
**IC50 / EC50 / Ki / Kd** — standard potency/affinity measures (legitimate values). •
**MDM** — Master Data Management; the discipline of one authoritative shared dataset. •
**Organism / taxon ID** — species; human = *Homo sapiens* = **9606**. •
**PMID** — normally a PubMed ID; **in this dataset it is an internal number — do not fetch it.** •
**Record linkage** — matching records across sources that refer to the same entity. •
**Swiss-Prot vs TrEMBL** — UniProt's reviewed (manual) vs unreviewed (automatic) tiers. •
**Target** — the biological entity (usually a protein) a drug acts on; first milestone in discovery. •
**UniProt** — the Universal Protein Resource; the identity authority for this challenge.

---

## 9. Sources reviewed

Domain / data references (from the announcement):
- Biological target — https://en.wikipedia.org/wiki/Biological_target
- Drug discovery — https://en.wikipedia.org/wiki/Drug_discovery
- What is a gene? (MedlinePlus) — https://medlineplus.gov/genetics/understanding/basics/gene/
- UniProt — https://en.wikipedia.org/wiki/UniProt
- ChEMBL — https://www.ebi.ac.uk/chembl/
- BindingDB — https://www.bindingdb.org/rwd/bind/info.jsp
- Master data management — https://en.wikipedia.org/wiki/Master_data_management
- Data quality — https://en.wikipedia.org/wiki/Data_quality
- Authority endpoint (nominated by the brief) — EBI Proteins API / UniProt (https://www.ebi.ac.uk/proteins/api/, https://www.uniprot.org)

Lilly domain colour (in this folder):
- `BRIDGE 2021 Q2 Seminar - Big Picture Drug Discovery.pdf` — discovery pipeline overview
  (Target → Hit → Lead → CS → FHD), TA role, BioTDR/DCRT/NTM, the Lilly acronym list.
- `Discovery onboarding June2024v2.pptx` — Discovery phase definition, milestone definitions
  (Target, Hit, PE, Lead, CS), and where target identity feeds portfolio decisions.

---
*This document is context only. It deliberately stops short of auditing the exam rows or
naming specific defects — that is the reconciliation step.*
