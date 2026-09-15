#!/usr/bin/env python3
"""
The Golden Target — reconciliation tool (SCAFFOLD ONLY).

============================================================================
THIS FILE IS A SCAFFOLD. It intentionally contains NO reconciliation or
defect-detection logic. Every pipeline step below raises NotImplementedError
and is marked TODO. It exists to give an implementer a ready frame that
already matches the challenge's tool contract. Fill in the TODOs.
============================================================================

Contract (see README.md and target-data/verification_starter.md):

    Invocation:   <cmd> <pack_dir>        e.g.  python reconcile.py target-data/exam
    Output:       one JSON object on stdout:

        {
          "unique_target_count": <int>,
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

Non-negotiable constraints (do not lose these when implementing):
  * HIDDEN DATASET: graded on unseen, schema-identical data — DO NOT overfit to exam/.
  * RUNTIME: must finish each pack in < 5 minutes — batch/cache/retry authority lookups.
  * AUTHORITY: prove every finding against UniProt / EBI Proteins API
                (https://www.ebi.ac.uk/proteins/api/).
  * pmid TRAP: never fetch or flag `pmid` in source_publications.csv; resolve ambiguous
               literature mentions from `context_sentence` only.
  * PRECISION: do NOT flag harmless variance (e.g. "Homo sapiens" vs "H. sapiens").

Dependencies: prefer the Python standard library only (csv, json, argparse, urllib).
Per Lilly policy, any third-party package must be resolved via JFrog Artifactory
(PyPI/NPM are prohibited).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The five source files expected inside <pack_dir>.
SOURCE_FILES = [
    "source_uniprot.csv",
    "source_chembl.csv",
    "source_bindingdb.csv",
    "source_internal.csv",
    "source_publications.csv",
]


# --------------------------------------------------------------------------
# Pipeline steps — ALL STUBS. Implement each; keep the 5-minute budget in mind.
# --------------------------------------------------------------------------

def load_sources(pack_dir: Path) -> dict:
    """Read the five CSVs from pack_dir into memory.
    TODO: parse each file with csv.DictReader; return {source_name: [rows]}."""
    raise NotImplementedError("TODO: load the five source CSVs from pack_dir")


def link_and_dedupe(sources: dict) -> list:
    """Group rows across sources that refer to the same protein target.
    TODO: join primarily on UniProt accession; use gene symbol + organism as
    secondary keys; collapse duplicates into single target identities."""
    raise NotImplementedError("TODO: link rows across sources and deduplicate")


def resolve_against_authority(entity) -> dict:
    """Resolve one entity against UniProt / EBI Proteins API.
    TODO: return the authority's facts — primary accession, organism (+taxon),
    approved symbol today, prior symbols, merge target, cross-references.
    Batch + cache calls; handle timeouts/missing entries gracefully."""
    raise NotImplementedError("TODO: query the authority and return its facts")


def build_golden_records(linked: list) -> list:
    """Produce one golden record per unique target.
    TODO: choose canonical gene symbol + primary_accession; record contributing
    `sources`. Return list of {"gene", "primary_accession", "sources"}."""
    raise NotImplementedError("TODO: assemble golden records")


def detect_defects(linked: list) -> list:
    """Find real defects and PROVE each against the authority.
    TODO: classify wrong-mapping / stale-but-valid / duplicate; attach severity;
    include observed + correct + retrieved_evidence + evidence_source. Do NOT
    flag harmless variance. Do NOT fetch/flag pmid values."""
    raise NotImplementedError("TODO: detect, classify, and evidence defects")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def reconcile(pack_dir: Path) -> dict:
    """Run the full pipeline and return the contract object.

    NOTE: while this scaffold's steps are unimplemented, this returns an
    empty-but-valid envelope so the output shape is demonstrable. Replace the
    body with the real pipeline (the commented calls below)."""
    # sources = load_sources(pack_dir)
    # linked = link_and_dedupe(sources)
    # golden = build_golden_records(linked)
    # findings = detect_defects(linked)
    # return {
    #     "unique_target_count": len(golden),
    #     "golden_records": golden,
    #     "findings": findings,
    # }

    print(
        "WARNING: reconcile.py is a scaffold — pipeline not implemented; "
        "emitting an empty contract envelope.",
        file=sys.stderr,
    )
    return {"unique_target_count": 0, "golden_records": [], "findings": []}


def validate_pack(pack_dir: Path) -> None:
    """Basic I/O validation (not part of the solution logic)."""
    if not pack_dir.is_dir():
        sys.exit(f"error: pack_dir not found or not a directory: {pack_dir}")
    missing = [f for f in SOURCE_FILES if not (pack_dir / f).is_file()]
    if missing:
        sys.exit(f"error: missing expected source files in {pack_dir}: {', '.join(missing)}")


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile source extracts into golden target records (scaffold)."
    )
    parser.add_argument("pack_dir", type=Path, help="directory containing the five source_*.csv files")
    args = parser.parse_args(argv)

    validate_pack(args.pack_dir)
    result = reconcile(args.pack_dir)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
