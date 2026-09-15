#!/usr/bin/env python3
"""
The Golden Target — reconciliation tool.

Invocation:   python reconcile.py <pack_dir>
Output:       one JSON object on stdout
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

SOURCE_FILES = [
    "source_uniprot.csv",
    "source_chembl.csv",
    "source_bindingdb.csv",
    "source_internal.csv",
    "source_publications.csv",
]

EBI_API = "https://www.ebi.ac.uk/proteins/api/proteins"
UNIPROT_REST = "https://rest.uniprot.org/uniprotkb"
CACHE_DIR = Path(".cache")
CACHE_FILE = CACHE_DIR / "proteins_cache.json"

REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.02
MAX_RETRIES = 2
MAX_WORKERS = 10


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# EBI Proteins API client — cached, batched, retried
# ---------------------------------------------------------------------------

class ProteinAuthority:
    def __init__(self):
        self._cache: dict[str, dict | None] = {}
        self._merge_cache: dict[str, dict | None] = {}
        self._lock = Lock()
        self._load_disk_cache()

    def _load_disk_cache(self) -> None:
        if CACHE_FILE.is_file():
            try:
                with open(CACHE_FILE) as f:
                    data = json.load(f)
                self._cache = data.get("proteins", {})
                self._merge_cache = data.get("merges", {})
                log(f"  Loaded {len(self._cache)} cached protein lookups")
            except Exception:
                pass

    def _save_disk_cache(self) -> None:
        try:
            CACHE_DIR.mkdir(exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump({"proteins": self._cache, "merges": self._merge_cache}, f)
        except Exception:
            pass

    def _http_get_json(self, url: str, headers: dict | None = None) -> tuple[int, dict | None]:
        hdrs = headers or {}
        req = urllib.request.Request(url, headers=hdrs)
        for attempt in range(MAX_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    body = resp.read().decode("utf-8")
                    return resp.status, json.loads(body)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return 404, None
                if e.code == 429:
                    time.sleep(2 + attempt * 2)
                    continue
                if e.code in (500, 502, 503) and attempt < MAX_RETRIES - 1:
                    time.sleep(0.5)
                    continue
                return e.code, None
            except Exception:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5)
                    continue
                return 0, None
        return 0, None

    def _fetch_ebi(self, accession: str) -> dict | None:
        url = f"{EBI_API}/{accession}"
        status, data = self._http_get_json(url, {"Accept": "application/json"})
        if status == 200 and data:
            return self._parse_ebi_response(data, accession)
        return None

    def _fetch_uniprot_inactive(self, accession: str) -> dict | None:
        url = f"{UNIPROT_REST}/{accession}"
        status, data = self._http_get_json(url, {"Accept": "application/json"})
        if status == 200 and data:
            entry_type = data.get("entryType", "")
            if entry_type == "Inactive":
                reason = data.get("inactiveReason", {})
                merge_targets = reason.get("mergeDemergeTo", [])
                if merge_targets:
                    return {"merged_into": merge_targets[0], "reason": reason.get("inactiveReasonType", "MERGED")}
            elif data.get("primaryAccession"):
                return self._parse_uniprot_rest_response(data, accession)
        return None

    def _parse_ebi_response(self, data: dict, queried: str) -> dict:
        primary = data.get("accession", queried)
        secondaries = data.get("secondaryAccession", [])
        genes = data.get("gene", [])
        gene_name = ""
        synonyms = []
        if genes:
            g = genes[0]
            name_obj = g.get("name", {})
            gene_name = name_obj.get("value", "")
            for s in g.get("synonyms", []):
                v = s.get("value", "")
                if v:
                    synonyms.append(v)
            for s in g.get("orderedLocusNames", []):
                v = s.get("value", "")
                if v:
                    synonyms.append(v)
            for s in g.get("orfNames", []):
                v = s.get("value", "")
                if v:
                    synonyms.append(v)

        org = data.get("organism", {})
        org_names = org.get("names", [])
        organism = org_names[0].get("value", "") if org_names else ""
        taxon_id = org.get("taxonomy", 0)

        protein = data.get("protein", {})
        rec_name = protein.get("recommendedName", {})
        full_name = rec_name.get("fullName", {}).get("value", "")
        if not full_name:
            sub_names = protein.get("submittedName", [])
            if sub_names:
                full_name = sub_names[0].get("fullName", {}).get("value", "")

        return {
            "primary_accession": primary,
            "secondary_accessions": secondaries,
            "gene_name": gene_name,
            "gene_synonyms": synonyms,
            "organism": organism,
            "taxon_id": taxon_id,
            "protein_name": full_name,
            "queried_accession": queried,
            "source": f"{EBI_API}/{queried}",
        }

    def _parse_uniprot_rest_response(self, data: dict, queried: str) -> dict:
        primary = data.get("primaryAccession", queried)
        secondaries = data.get("secondaryAccessions", [])
        genes = data.get("genes", [])
        gene_name = ""
        synonyms = []
        if genes:
            g = genes[0]
            gn = g.get("geneName", {})
            gene_name = gn.get("value", "")
            for s in g.get("synonyms", []):
                v = s.get("value", "")
                if v:
                    synonyms.append(v)
            for s in g.get("orderedLocusNames", []):
                v = s.get("value", "")
                if v:
                    synonyms.append(v)
            for s in g.get("orfNames", []):
                v = s.get("value", "")
                if v:
                    synonyms.append(v)

        org = data.get("organism", {})
        organism = org.get("scientificName", "")
        taxon_id = org.get("taxonId", 0)

        desc = data.get("proteinDescription", {})
        rec_name = desc.get("recommendedName", {})
        full_name = rec_name.get("fullName", {}).get("value", "")

        return {
            "primary_accession": primary,
            "secondary_accessions": secondaries,
            "gene_name": gene_name,
            "gene_synonyms": synonyms,
            "organism": organism,
            "taxon_id": taxon_id,
            "protein_name": full_name,
            "queried_accession": queried,
            "source": f"{UNIPROT_REST}/{queried}",
        }

    def resolve(self, accession: str) -> dict | None:
        acc = accession.strip()
        if not acc:
            return None
        with self._lock:
            if acc in self._cache:
                return self._cache[acc]

        time.sleep(REQUEST_DELAY)
        result = self._fetch_ebi(acc)
        if result:
            with self._lock:
                self._cache[acc] = result
            return result

        with self._lock:
            if acc in self._merge_cache:
                merge_info = self._merge_cache[acc]
                if merge_info and "merged_into" in merge_info:
                    primary = merge_info["merged_into"]
                else:
                    self._cache[acc] = None
                    return None
            else:
                primary = None

        if primary:
            primary_result = self.resolve(primary)
            if primary_result:
                merged_result = dict(primary_result)
                merged_result["queried_accession"] = acc
                merged_result["merged_from"] = acc
                merged_result["source"] = f"{UNIPROT_REST}/{acc} -> {EBI_API}/{primary}"
                with self._lock:
                    self._cache[acc] = merged_result
                return merged_result
            with self._lock:
                self._cache[acc] = None
            return None

        time.sleep(REQUEST_DELAY)
        inactive = self._fetch_uniprot_inactive(acc)
        if inactive and "merged_into" in inactive:
            with self._lock:
                self._merge_cache[acc] = inactive
            primary = inactive["merged_into"]
            primary_result = self.resolve(primary)
            if primary_result:
                merged_result = dict(primary_result)
                merged_result["queried_accession"] = acc
                merged_result["merged_from"] = acc
                merged_result["source"] = f"{UNIPROT_REST}/{acc} -> {EBI_API}/{primary}"
                with self._lock:
                    self._cache[acc] = merged_result
                return merged_result
        elif inactive and "primary_accession" in inactive:
            with self._lock:
                self._cache[acc] = inactive
            return inactive

        with self._lock:
            self._cache[acc] = None
            self._merge_cache[acc] = None
        return None

    def resolve_batch(self, accessions: list[str]) -> None:
        unique = set(a.strip() for a in accessions if a.strip())
        with self._lock:
            to_resolve = [a for a in unique if a not in self._cache]
        log(f"  Resolving {len(to_resolve)} accessions ({len(unique)} unique, {len(unique) - len(to_resolve)} cached)")

        completed = 0
        def _resolve_one(acc):
            nonlocal completed
            self.resolve(acc)
            completed += 1
            if completed % 100 == 0:
                log(f"    ...resolved {completed}/{len(to_resolve)}")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_resolve_one, acc): acc for acc in to_resolve}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log(f"    Warning: resolution failed for {futures[future]}: {e}")
        self._save_disk_cache()
        log(f"  Resolution complete. Cache has {len(self._cache)} entries.")


# ---------------------------------------------------------------------------
# CSV Loaders
# ---------------------------------------------------------------------------

def load_sources(pack_dir: Path) -> dict[str, list[dict]]:
    sources = {}
    for fname in SOURCE_FILES:
        path = pack_dir / fname
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                cleaned = {k.strip(): v.strip() if v else "" for k, v in row.items()}
                rows.append(cleaned)
            key = fname.replace("source_", "").replace(".csv", "")
            sources[key] = rows
            log(f"  Loaded {fname}: {len(rows)} rows")
    return sources


def get_accession(row: dict, source: str) -> str:
    acc = ""
    if source == "uniprot":
        acc = row.get("accession", "")
    elif source == "chembl":
        acc = row.get("accession", "")
    elif source == "bindingdb":
        acc = row.get("uniprot_id", "")
    elif source == "internal":
        acc = row.get("uniprot_ref", "")
    if "-" in acc and acc.split("-")[1].isdigit():
        acc = acc.split("-")[0]
    return acc


def get_gene_symbol(row: dict, source: str) -> str:
    if source == "uniprot":
        return row.get("gene_names", "").split()[0] if row.get("gene_names") else ""
    if source in ("chembl", "bindingdb"):
        return row.get("gene_symbol", "")
    if source == "internal":
        return row.get("gene_symbol", "")
    if source == "publications":
        return row.get("target_mention", "")
    return ""


# ---------------------------------------------------------------------------
# Publication Disambiguation
# ---------------------------------------------------------------------------

def disambiguate_publication(mention: str, context: str, gene_symbol_set: set[str]) -> str | None:
    mention_upper = mention.strip().upper()
    if mention_upper in gene_symbol_set:
        return mention.strip()

    ctx_lower = context.lower() if context else ""

    if mention_upper == "PSA":
        npepps_keywords = ["aminopeptidase", "puromycin", "tau", "cytosolic", "brain", "lysate", "degradation"]
        klk3_keywords = ["prostate", "kallikrein", "serum", "biopsy", "prostatectomy", "psa level", "free-to-total"]
        npepps_score = sum(1 for kw in npepps_keywords if kw in ctx_lower)
        klk3_score = sum(1 for kw in klk3_keywords if kw in ctx_lower)
        if klk3_score > npepps_score:
            return "KLK3"
        elif npepps_score > klk3_score:
            return "NPEPPS"
        return "KLK3"

    for sym in gene_symbol_set:
        if sym.upper() == mention_upper:
            return sym

    return mention.strip() if mention.strip() else None


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def is_harmless_organism_variance(value: str) -> bool:
    v = value.strip().lower()
    return v in ("homo sapiens", "h. sapiens", "human", "homo sapiens (human)")


# ---------------------------------------------------------------------------
# Link, Deduplicate, Detect Defects
# ---------------------------------------------------------------------------

def reconcile(pack_dir: Path) -> dict:
    log("Phase 1: Loading sources...")
    sources = load_sources(pack_dir)

    log("Phase 2: Collecting accessions and building index...")
    accession_to_sources: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    all_accessions = set()
    gene_symbol_set: set[str] = set()

    for source_name in ["uniprot", "chembl", "bindingdb", "internal"]:
        for row in sources.get(source_name, []):
            acc = get_accession(row, source_name)
            gene = get_gene_symbol(row, source_name)
            if acc:
                accession_to_sources[acc][source_name].append(row)
                all_accessions.add(acc)
            if gene:
                gene_symbol_set.add(gene.upper())

    gene_to_accessions: dict[str, set[str]] = defaultdict(set)
    for source_name in ["uniprot", "chembl", "bindingdb", "internal"]:
        for row in sources.get(source_name, []):
            acc = get_accession(row, source_name)
            gene = get_gene_symbol(row, source_name)
            if acc and gene:
                gene_to_accessions[gene.upper()].add(acc)

    pub_assignments: dict[int, str | None] = {}
    for i, row in enumerate(sources.get("publications", [])):
        mention = row.get("target_mention", "")
        context = row.get("context_sentence", "")
        resolved = disambiguate_publication(mention, context, gene_symbol_set)
        pub_assignments[i] = resolved

    log(f"  {len(all_accessions)} unique accessions found across 4 sources")

    log("Phase 3: Resolving against EBI Proteins API...")
    authority = ProteinAuthority()
    authority.resolve_batch(list(all_accessions))

    log("Phase 4: Building primary accession map and detecting defects...")
    acc_to_primary: dict[str, str] = {}
    acc_to_authority: dict[str, dict] = {}

    for acc in all_accessions:
        result = authority.resolve(acc)
        if result:
            primary = result["primary_accession"]
            acc_to_primary[acc] = primary
            if primary not in acc_to_authority:
                acc_to_authority[primary] = result
        else:
            acc_to_primary[acc] = acc

    primary_to_sources: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for acc, src_dict in accession_to_sources.items():
        primary = acc_to_primary.get(acc, acc)
        for source_name, rows in src_dict.items():
            primary_to_sources[primary][source_name].extend(rows)

    for i, row in enumerate(sources.get("publications", [])):
        resolved_gene = pub_assignments.get(i)
        if resolved_gene:
            matched_primary = None
            resolved_upper = resolved_gene.upper()
            for primary, auth in acc_to_authority.items():
                if auth["gene_name"].upper() == resolved_upper:
                    matched_primary = primary
                    break
                if resolved_upper in [s.upper() for s in auth.get("gene_synonyms", [])]:
                    matched_primary = primary
                    break
            if not matched_primary:
                for acc, primary in acc_to_primary.items():
                    for source_name in ["uniprot", "chembl", "bindingdb", "internal"]:
                        for r in accession_to_sources.get(acc, {}).get(source_name, []):
                            gs = get_gene_symbol(r, source_name).upper()
                            if gs == resolved_upper:
                                matched_primary = primary
                                break
                        if matched_primary:
                            break
                    if matched_primary:
                        break

            if matched_primary:
                primary_to_sources[matched_primary]["publications"].append(row)

    findings = []
    seen_findings: set[str] = set()

    def add_finding(f: dict) -> None:
        key = f"{f['gene']}|{f['observed']}|{f['correct']}|{f['classification']}"
        if key not in seen_findings:
            seen_findings.add(key)
            findings.append(f)

    for acc in all_accessions:
        result = authority.resolve(acc)
        if not result:
            continue

        primary = result["primary_accession"]
        auth_gene = result["gene_name"]
        auth_synonyms = [s.upper() for s in result.get("gene_synonyms", [])]
        auth_taxon = result.get("taxon_id", 0)
        evidence_source = result.get("source", f"{EBI_API}/{acc}")

        if acc != primary and acc in accession_to_sources:
            merged_from = result.get("merged_from")
            if merged_from:
                gene_for_finding = auth_gene or acc
                evidence_text = (
                    f"Accession {acc} has been merged into {primary}. "
                    f"Authority: gene={auth_gene}, organism={result.get('organism', '')}, taxid={auth_taxon}"
                )
                add_finding({
                    "gene": gene_for_finding,
                    "observed": acc,
                    "correct": primary,
                    "retrieved_evidence": evidence_text,
                    "evidence_source": evidence_source,
                    "severity": "medium",
                    "classification": "stale-but-valid label",
                })
            else:
                if acc in result.get("secondary_accessions", []):
                    gene_for_finding = auth_gene or acc
                    evidence_text = (
                        f"Accession {acc} is a secondary accession of {primary}. "
                        f"Authority: gene={auth_gene}, organism={result.get('organism', '')}, taxid={auth_taxon}"
                    )
                    add_finding({
                        "gene": gene_for_finding,
                        "observed": acc,
                        "correct": primary,
                        "retrieved_evidence": evidence_text,
                        "evidence_source": evidence_source,
                        "severity": "low",
                        "classification": "stale-but-valid label",
                    })

        for source_name, rows in accession_to_sources.get(acc, {}).items():
            for row in rows:
                src_gene = get_gene_symbol(row, source_name)
                if not src_gene or not auth_gene:
                    continue

                if src_gene.upper() != auth_gene.upper():
                    if src_gene.upper() in auth_synonyms:
                        evidence_text = (
                            f"Gene symbol '{src_gene}' is a known synonym/previous name for {auth_gene}. "
                            f"Authority synonyms: {result.get('gene_synonyms', [])}. "
                            f"Accession={primary}, organism={result.get('organism', '')}, taxid={auth_taxon}"
                        )
                        add_finding({
                            "gene": auth_gene,
                            "observed": src_gene,
                            "correct": auth_gene,
                            "retrieved_evidence": evidence_text,
                            "evidence_source": evidence_source,
                            "severity": "low",
                            "classification": "stale-but-valid label",
                        })
                    else:
                        evidence_text = (
                            f"Gene symbol '{src_gene}' does not match authority approved symbol '{auth_gene}' "
                            f"for accession {primary}, and is not listed as a synonym. "
                            f"Authority synonyms: {result.get('gene_synonyms', [])}. "
                            f"Organism={result.get('organism', '')}, taxid={auth_taxon}, "
                            f"protein={result.get('protein_name', '')}"
                        )
                        add_finding({
                            "gene": auth_gene,
                            "observed": src_gene,
                            "correct": auth_gene,
                            "retrieved_evidence": evidence_text,
                            "evidence_source": evidence_source,
                            "severity": "high",
                            "classification": "wrong mapping",
                        })

                if auth_taxon and auth_taxon != 9606:
                    src_org = ""
                    if source_name == "uniprot":
                        src_org = row.get("organism", "")
                    elif source_name == "chembl":
                        src_org = row.get("organism", "")
                    elif source_name == "bindingdb":
                        src_org = row.get("species", "")
                    if src_org and is_harmless_organism_variance(src_org):
                        evidence_text = (
                            f"Accession {primary} belongs to {result.get('organism', '')} (taxid={auth_taxon}), "
                            f"not Homo sapiens (9606). Source claims: '{src_org}'"
                        )
                        add_finding({
                            "gene": auth_gene or src_gene,
                            "observed": f"{src_org} (claimed for {acc})",
                            "correct": f"{result.get('organism', '')} (taxid={auth_taxon})",
                            "retrieved_evidence": evidence_text,
                            "evidence_source": evidence_source,
                            "severity": "high",
                            "classification": "wrong mapping",
                        })

    chembl_ids: dict[str, list[dict]] = defaultdict(list)
    for row in sources.get("chembl", []):
        cid = row.get("chembl_id", "")
        if cid:
            chembl_ids[cid].append(row)

    for cid, rows in chembl_ids.items():
        if len(rows) > 1:
            primaries = set()
            for row in rows:
                acc = row.get("accession", "")
                p = acc_to_primary.get(acc, acc)
                primaries.add(p)
            if len(primaries) > 1:
                for row in rows:
                    acc = row.get("accession", "")
                    gene = row.get("gene_symbol", "")
                    result = authority.resolve(acc)
                    auth_gene = result["gene_name"] if result else gene
                    evidence_text = (
                        f"ChEMBL ID {cid} maps to multiple different proteins: "
                        f"{', '.join(f'{r.get('gene_symbol','')}({r.get('accession','')})' for r in rows)}"
                    )
                    add_finding({
                        "gene": auth_gene,
                        "observed": f"{cid} -> {acc} ({gene})",
                        "correct": f"ChEMBL ID {cid} should map to a single target",
                        "retrieved_evidence": evidence_text,
                        "evidence_source": f"Cross-reference within source_chembl.csv",
                        "severity": "high",
                        "classification": "wrong mapping",
                    })
            elif len(primaries) == 1:
                unique_accs = set(r.get("accession", "") for r in rows)
                if len(unique_accs) > 1:
                    primary = list(primaries)[0]
                    auth = acc_to_authority.get(primary)
                    auth_gene = auth["gene_name"] if auth else rows[0].get("gene_symbol", "")
                    non_primary_accs = [a for a in unique_accs if a != primary]
                    for npa in non_primary_accs:
                        evidence_text = (
                            f"ChEMBL ID {cid} has duplicate entries: accessions {unique_accs} "
                            f"all resolve to primary {primary} ({auth_gene})"
                        )
                        add_finding({
                            "gene": auth_gene,
                            "observed": f"{npa} (duplicate entry for {cid})",
                            "correct": primary,
                            "retrieved_evidence": evidence_text,
                            "evidence_source": f"{EBI_API}/{primary}",
                            "severity": "medium",
                            "classification": "duplicate identity",
                        })

    primary_original_accs: dict[str, set[str]] = defaultdict(set)
    for acc in all_accessions:
        primary = acc_to_primary.get(acc, acc)
        if acc in accession_to_sources:
            primary_original_accs[primary].add(acc)

    for primary, orig_accs in primary_original_accs.items():
        if len(orig_accs) > 1:
            auth = acc_to_authority.get(primary)
            auth_gene = auth["gene_name"] if auth else ""
            non_primary = [a for a in orig_accs if a != primary]
            for npa in non_primary:
                npa_result = authority.resolve(npa)
                if npa_result and npa_result.get("merged_from"):
                    continue
                if npa_result and npa in (npa_result.get("secondary_accessions", [])):
                    continue
                evidence_text = (
                    f"Accessions {sorted(orig_accs)} all resolve to primary {primary} ({auth_gene}). "
                    f"These are duplicate identities."
                )
                add_finding({
                    "gene": auth_gene or primary,
                    "observed": f"{npa} (duplicate of {primary})",
                    "correct": primary,
                    "retrieved_evidence": evidence_text,
                    "evidence_source": f"{EBI_API}/{primary}",
                    "severity": "medium",
                    "classification": "duplicate identity",
                })

    log("Phase 5: Building golden records...")
    golden_records = []
    for primary in sorted(primary_to_sources.keys()):
        auth = acc_to_authority.get(primary)
        gene = auth["gene_name"] if auth else ""

        if not gene:
            for sname in ["uniprot", "chembl", "bindingdb", "internal"]:
                for row in primary_to_sources[primary].get(sname, []):
                    g = get_gene_symbol(row, sname)
                    if g:
                        gene = g
                        break
                if gene:
                    break

        contributing_sources = sorted(primary_to_sources[primary].keys())

        golden_records.append({
            "gene": gene,
            "primary_accession": primary,
            "sources": contributing_sources,
        })

    log(f"  {len(golden_records)} golden records built")
    log(f"  {len(findings)} findings detected")

    result = {
        "unique_target_count": len(golden_records),
        "golden_records": golden_records,
        "findings": findings,
    }
    return result


def validate_pack(pack_dir: Path) -> None:
    if not pack_dir.is_dir():
        sys.exit(f"error: pack_dir not found or not a directory: {pack_dir}")
    missing = [f for f in SOURCE_FILES if not (pack_dir / f).is_file()]
    if missing:
        sys.exit(f"error: missing expected source files in {pack_dir}: {', '.join(missing)}")


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile source extracts into golden target records."
    )
    parser.add_argument("pack_dir", type=Path, help="directory containing the five source_*.csv files")
    args = parser.parse_args(argv)

    validate_pack(args.pack_dir)
    result = reconcile(args.pack_dir)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
