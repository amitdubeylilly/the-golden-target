#!/usr/bin/env python3
"""
The Golden Target — reconciliation tool.

Invocation:   python reconcile.py <pack_dir>
Output:       one JSON object on stdout (contract):
    {
      "unique_target_count": int,
      "golden_records": [{"gene","primary_accession","sources"}],
      "findings": [{"gene","observed","correct","retrieved_evidence",
                    "evidence_source","severity","classification"}]
    }

Authority model
---------------
The nominated authority is the EBI Proteins API (https://www.ebi.ac.uk/proteins/api).
Obsolete / secondary UniProt accessions 404 on the direct endpoint, BUT every current
primary entry lists them in its `secondaryAccession` field. Since the corresponding
primaries are present in the pack, we resolve secondaries *through EBI itself* by
building a secondary->primary index from the primaries we resolve. The UniProt REST
service is used only as a rare, explicit fallback (logged loudly) for the case where a
secondary's primary is not present in the pack. ChEMBL (same host as EBI) is the
authority for ChEMBL-ID collisions.

Constraints honoured: stdlib-only, <5 min budget (threaded + cached + retried),
never fetch/flag pmid, never flag harmless variance, findings carry observed+correct.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
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
EBI_CHEMBL = "https://www.ebi.ac.uk/chembl/api/data/target"
UNIPROT_REST = "https://rest.uniprot.org/uniprotkb"   # rare fallback only

REQUEST_TIMEOUT = 12
MAX_RETRIES = 3
MAX_WORKERS = 10
HUMAN_TAXON = 9606


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _norm(s: str) -> str:
    """Normalise a name for fuzzy comparison: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ---------------------------------------------------------------------------
# Authority client
# ---------------------------------------------------------------------------

class Authority:
    """EBI-first resolver with a secondary->primary index and rare UniProt fallback."""

    def __init__(self, allow_uniprot_fallback: bool = True):
        self._ebi: dict[str, dict | None] = {}      # acc -> facts | None (definitive not-found)
        self._ebi_status: dict[str, str] = {}       # acc -> ok|notfound|error
        self._chembl: dict[str, dict | None] = {}
        self._lock = Lock()
        self.allow_uniprot_fallback = allow_uniprot_fallback
        self.used_fallback: list[str] = []
        self.unresolved_definitive: list[str] = []
        self.unresolved_error: list[str] = []

    # ---- low-level HTTP -------------------------------------------------
    def _http_json(self, url: str) -> tuple[str, dict | list | None]:
        """Return (status, data). status in {'ok','notfound','error'}."""
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        for attempt in range(MAX_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    return "ok", json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return "notfound", None
                if e.code == 429:
                    time.sleep(2 + attempt * 2)
                    continue
                if e.code in (500, 502, 503) and attempt < MAX_RETRIES - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return "error", None
            except Exception:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return "error", None
        return "error", None

    # ---- parsing --------------------------------------------------------
    @staticmethod
    def _parse_ebi(data: dict) -> dict:
        genes = data.get("gene", [])
        gene_name, synonyms = "", []
        if genes:
            g = genes[0]
            gene_name = g.get("name", {}).get("value", "")
            for key in ("synonyms", "orderedLocusNames", "orfNames"):
                for s in g.get(key, []):
                    v = s.get("value", "")
                    if v:
                        synonyms.append(v)
        org = data.get("organism", {})
        organism = (org.get("names", [{}])[0].get("value", "") if org.get("names") else "")
        protein = data.get("protein", {})
        pname = protein.get("recommendedName", {}).get("fullName", {}).get("value", "")
        if not pname and protein.get("submittedName"):
            pname = protein["submittedName"][0].get("fullName", {}).get("value", "")
        return {
            "primary_accession": data.get("accession", ""),
            "secondary_accessions": data.get("secondaryAccession", []),
            "gene_name": gene_name,
            "gene_synonyms": synonyms,
            "organism": organism,
            "taxon_id": org.get("taxonomy", 0),
            "protein_name": pname,
        }

    # ---- EBI single/batch ----------------------------------------------
    def _fetch_ebi(self, acc: str) -> None:
        status, data = self._http_json(f"{EBI_API}/{acc}")
        with self._lock:
            self._ebi_status[acc] = status
            if status == "ok" and isinstance(data, dict):
                self._ebi[acc] = self._parse_ebi(data)
            else:
                self._ebi[acc] = None

    def batch_ebi(self, accessions: list[str]) -> None:
        uniq = sorted({a.strip() for a in accessions if a.strip()})
        todo = [a for a in uniq if a not in self._ebi]
        log(f"  EBI: resolving {len(todo)} accessions ({len(uniq)} unique)")
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(self._fetch_ebi, a): a for a in todo}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    log(f"    warn: EBI failed for {futs[fut]}: {e}")
                done += 1
                if done % 150 == 0:
                    log(f"    ...{done}/{len(todo)}")
        log("  EBI resolution complete.")

    def ebi_facts(self, acc: str) -> dict | None:
        return self._ebi.get(acc)

    def ebi_status(self, acc: str) -> str:
        return self._ebi_status.get(acc, "error")

    # ---- rare UniProt fallback -----------------------------------------
    def uniprot_fallback(self, acc: str) -> dict | None:
        """Return {'merged_into': X} or parsed facts, or None. Logged loudly."""
        if not self.allow_uniprot_fallback:
            return None
        status, data = self._http_json(f"{UNIPROT_REST}/{acc}")
        if status != "ok" or not isinstance(data, dict):
            return None
        self.used_fallback.append(acc)
        if data.get("entryType") == "Inactive":
            tgt = data.get("inactiveReason", {}).get("mergeDemergeTo", [])
            if tgt:
                return {"merged_into": tgt[0]}
            return None
        if data.get("primaryAccession"):
            genes = data.get("genes", [])
            gene_name, synonyms = "", []
            if genes:
                g = genes[0]
                gene_name = g.get("geneName", {}).get("value", "")
                for key in ("synonyms", "orderedLocusNames", "orfNames"):
                    for s in g.get(key, []):
                        v = s.get("value", "")
                        if v:
                            synonyms.append(v)
            org = data.get("organism", {})
            desc = data.get("proteinDescription", {})
            return {
                "primary_accession": data.get("primaryAccession", ""),
                "secondary_accessions": data.get("secondaryAccessions", []),
                "gene_name": gene_name,
                "gene_synonyms": synonyms,
                "organism": org.get("scientificName", ""),
                "taxon_id": org.get("taxonId", 0),
                "protein_name": desc.get("recommendedName", {}).get("fullName", {}).get("value", ""),
            }
        return None

    # ---- ChEMBL (authority for ChEMBL-ID collisions) -------------------
    def chembl_target(self, cid: str) -> dict | None:
        with self._lock:
            if cid in self._chembl:
                return self._chembl[cid]
        status, data = self._http_json(f"{EBI_CHEMBL}/{cid}.json")
        result = None
        if status == "ok" and isinstance(data, dict):
            comps = data.get("target_components", [])
            if comps:
                acc = comps[0].get("accession")
                gsyms = [s.get("component_synonym") for s in comps[0].get("target_component_synonyms", [])
                         if s.get("syn_type") == "GENE_SYMBOL"]
                result = {"accession": acc, "gene": gsyms[0] if gsyms else "",
                          "pref_name": data.get("pref_name", "")}
        with self._lock:
            self._chembl[cid] = result
        return result


# ---------------------------------------------------------------------------
# CSV loading & field access
# ---------------------------------------------------------------------------

def load_sources(pack_dir: Path) -> dict[str, list[dict]]:
    sources = {}
    for fname in SOURCE_FILES:
        with open(pack_dir / fname, newline="", encoding="utf-8") as f:
            rows = [{k.strip(): (v.strip() if v else "") for k, v in row.items()}
                    for row in csv.DictReader(f)]
        sources[fname.replace("source_", "").replace(".csv", "")] = rows
        log(f"  Loaded {fname}: {len(rows)} rows")
    return sources


def base_accession(acc: str) -> str:
    """Strip an isoform suffix like -3 (but keep hyphens that are not isoforms)."""
    if "-" in acc:
        head, _, tail = acc.partition("-")
        if tail.isdigit():
            return head
    return acc


def get_accession(row: dict, source: str) -> str:
    field = {"uniprot": "accession", "chembl": "accession",
             "bindingdb": "uniprot_id", "internal": "uniprot_ref"}.get(source, "")
    return base_accession(row.get(field, "")) if field else ""


def get_gene_symbol(row: dict, source: str) -> str:
    if source == "uniprot":
        gn = row.get("gene_names", "")
        return gn.split()[0] if gn else ""
    if source in ("chembl", "bindingdb", "internal"):
        return row.get("gene_symbol", "")
    if source == "publications":
        return row.get("target_mention", "")
    return ""


def get_row_name(row: dict, source: str) -> str:
    return {
        "uniprot": row.get("protein_name", ""),
        "chembl": row.get("pref_name", ""),
        "bindingdb": row.get("target_name", ""),
        "internal": row.get("registered_name", ""),
    }.get(source, "")


def get_row_ref(row: dict, source: str) -> str:
    return {
        "uniprot": row.get("entry_name", ""),
        "chembl": row.get("chembl_id", ""),
        "bindingdb": row.get("target_name", ""),
        "internal": row.get("internal_id", ""),
    }.get(source, "")


HARMLESS_ORGANISM = {"homo sapiens", "h. sapiens", "human", "homo sapiens (human)"}


def is_harmless_organism(value: str) -> bool:
    return value.strip().lower() in HARMLESS_ORGANISM


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

STRUCT_SOURCES = ["uniprot", "chembl", "bindingdb", "internal"]


def reconcile(pack_dir: Path) -> dict:
    log("Phase 1: Loading sources...")
    sources = load_sources(pack_dir)

    # Index rows by accession
    acc_rows: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    all_accs: set[str] = set()
    for sname in STRUCT_SOURCES:
        for row in sources.get(sname, []):
            acc = get_accession(row, sname)
            if acc:
                acc_rows[acc][sname].append(row)
                all_accs.add(acc)
    log(f"Phase 2: {len(all_accs)} unique accessions across structured sources")

    # ---- Resolve against authority (EBI-first) ----
    log("Phase 3: Resolving against EBI Proteins API...")
    auth = Authority()
    auth.batch_ebi(list(all_accs))

    # secondary -> primary index from every EBI primary we resolved
    sec_index: dict[str, str] = {}
    for acc in list(auth._ebi.keys()):
        facts = auth.ebi_facts(acc)
        if facts and facts.get("primary_accession"):
            for sec in facts.get("secondary_accessions", []):
                sec_index.setdefault(sec, facts["primary_accession"])

    # Resolve every source accession -> (primary, facts, status, evidence_url)
    resinfo: dict[str, dict] = {}
    for acc in sorted(all_accs):
        facts = auth.ebi_facts(acc)
        if facts:  # resolved directly on EBI (a current primary)
            resinfo[acc] = {"primary": facts["primary_accession"], "facts": facts,
                            "status": "primary", "evidence_url": f"{EBI_API}/{facts['primary_accession']}"}
            continue
        if acc in sec_index:  # secondary of a primary already in the pack -> resolved via EBI
            primary = sec_index[acc]
            pf = auth.ebi_facts(primary)
            resinfo[acc] = {"primary": primary, "facts": pf, "status": "secondary",
                            "evidence_url": f"{EBI_API}/{primary}"}
            continue
        # rare fallback
        fb = auth.uniprot_fallback(acc)
        if fb and "merged_into" in fb:
            primary = fb["merged_into"]
            pf = auth.ebi_facts(primary)
            if pf is None:
                auth._fetch_ebi(primary)
                pf = auth.ebi_facts(primary)
            if pf:
                resinfo[acc] = {"primary": primary, "facts": pf, "status": "merged",
                                "evidence_url": f"{UNIPROT_REST}/{acc} -> {EBI_API}/{primary}"}
                continue
        if fb and fb.get("primary_accession"):
            resinfo[acc] = {"primary": fb["primary_accession"], "facts": fb, "status": "secondary",
                            "evidence_url": f"{UNIPROT_REST}/{acc}"}
            continue
        # unresolved
        resinfo[acc] = {"primary": acc, "facts": None, "status": "unresolved",
                        "evidence_url": ""}
        if auth.ebi_status(acc) == "notfound":
            auth.unresolved_definitive.append(acc)
        else:
            auth.unresolved_error.append(acc)

    # Loud reporting of degraded resolution
    if auth.used_fallback:
        log(f"  NOTE: used rest.uniprot.org fallback for {len(auth.used_fallback)} accession(s): "
            f"{sorted(set(auth.used_fallback))}")
    if auth.unresolved_error:
        log(f"  WARNING: {len(auth.unresolved_error)} accession(s) unresolved due to NETWORK/ERROR "
            f"(results may be degraded): {sorted(set(auth.unresolved_error))[:20]}")
    if auth.unresolved_definitive:
        log(f"  WARNING: {len(auth.unresolved_definitive)} accession(s) have NO current UniProt entry: "
            f"{sorted(set(auth.unresolved_definitive))[:20]}")
    resolved_frac = 1.0 - (len(auth.unresolved_error) / max(1, len(all_accs)))
    if resolved_frac < 0.9:
        log(f"  *** WARNING: only {resolved_frac:.0%} of accessions resolved — MASTER MAY BE DEGRADED ***")

    # Maps for downstream logic
    acc_to_primary = {a: resinfo[a]["primary"] for a in all_accs}
    primary_facts: dict[str, dict] = {}
    for a in all_accs:
        r = resinfo[a]
        if r["facts"]:
            primary_facts.setdefault(r["primary"], r["facts"])
    # authoritative gene symbol -> primary (for conflict-direction resolution)
    authgene_to_primary: dict[str, str] = {}
    for p, f in primary_facts.items():
        if f.get("gene_name"):
            authgene_to_primary.setdefault(f["gene_name"].upper(), p)

    # ---- Findings ----
    log("Phase 4: Detecting defects...")
    findings: list[dict] = []
    seen: set[tuple] = set()
    dup_covered: set[str] = set()  # accessions accounted for by duplicate-identity findings

    def add(f: dict) -> None:
        key = (f["gene"], f["observed"], f["correct"], f["classification"])
        if key not in seen:
            seen.add(key)
            findings.append(f)

    # (A) ChEMBL-ID collisions & duplicate rows -------------------------
    chembl_by_id: dict[str, list[dict]] = defaultdict(list)
    for row in sources.get("chembl", []):
        cid = row.get("chembl_id", "")
        if cid:
            chembl_by_id[cid].append(row)

    for cid, rows in chembl_by_id.items():
        if len(rows) < 2:
            continue
        primaries = {acc_to_primary.get(base_accession(r.get("accession", "")),
                                        base_accession(r.get("accession", ""))) for r in rows}
        if len(primaries) == 1:
            # same protein under >1 accession -> duplicate identity
            primary = next(iter(primaries))
            pf = primary_facts.get(primary, {})
            gene = pf.get("gene_name") or rows[0].get("gene_symbol", "")
            for r in rows:
                a = base_accession(r.get("accession", ""))
                if a and a != primary:
                    dup_covered.add(a)
                    add({"gene": gene, "observed": a, "correct": primary,
                         "retrieved_evidence": (f"ChEMBL ID {cid} appears on {len(rows)} rows; accessions "
                                                f"{sorted({base_accession(x.get('accession','')) for x in rows})} "
                                                f"all resolve to primary {primary} ({gene}) — duplicate identity."),
                         "evidence_source": f"{EBI_API}/{primary}",
                         "severity": "medium", "classification": "duplicate identity"})
        else:
            # one ChEMBL ID -> different proteins: ask ChEMBL which is the true target
            truth = auth.chembl_target(cid)
            if truth and truth.get("accession"):
                true_primary = acc_to_primary.get(truth["accession"], truth["accession"])
                true_gene = truth.get("gene") or (primary_facts.get(true_primary, {}) or {}).get("gene_name", "")
                for r in rows:
                    a = base_accession(r.get("accession", ""))
                    rp = acc_to_primary.get(a, a)
                    rgene = r.get("gene_symbol", "")
                    if rp == true_primary:
                        continue  # this row is correct — do NOT flag
                    add({"gene": rgene or (primary_facts.get(rp, {}) or {}).get("gene_name", ""),
                         "observed": f"{cid} -> {a} ({rgene})",
                         "correct": f"{cid} -> {true_gene} ({truth['accession']})",
                         "retrieved_evidence": (f"Per ChEMBL, target {cid} is {true_gene} "
                                                f"({truth['accession']}); this row wrongly assigns {cid} to "
                                                f"{rgene} ({a})."),
                         "evidence_source": f"{EBI_CHEMBL}/{cid}.json",
                         "severity": "high", "classification": "wrong mapping"})
            else:
                # ChEMBL unavailable: report the collision without asserting a specific fix
                listing = ", ".join(f"{r.get('gene_symbol','')}({base_accession(r.get('accession',''))})" for r in rows)
                add({"gene": rows[0].get("gene_symbol", ""),
                     "observed": f"{cid} maps to multiple proteins: {listing}",
                     "correct": "(one mapping is wrong; ChEMBL authority unavailable to determine which)",
                     "retrieved_evidence": f"ChEMBL ID {cid} appears on rows with distinct proteins: {listing}.",
                     "evidence_source": f"{EBI_CHEMBL}/{cid}.json",
                     "severity": "high", "classification": "wrong mapping"})

    # (B) Per-accession: stale accession, symbol staleness/conflict, organism ----
    for acc in sorted(all_accs):
        r = resinfo[acc]
        facts = r["facts"]
        if not facts:
            continue
        primary = r["primary"]
        auth_gene = facts.get("gene_name", "")
        synonyms = {s.upper() for s in facts.get("gene_synonyms", [])}
        taxon = facts.get("taxon_id", 0)
        ev_url = r["evidence_url"]

        # stale/secondary/merged accession (skip if already a duplicate-identity finding)
        if r["status"] in ("secondary", "merged") and acc != primary and acc not in dup_covered:
            sev = "medium" if r["status"] == "merged" else "low"
            verb = "has been merged into" if r["status"] == "merged" else "is a secondary accession of"
            add({"gene": auth_gene or acc, "observed": acc, "correct": primary,
                 "retrieved_evidence": (f"Accession {acc} {verb} {primary}. Authority: gene={auth_gene}, "
                                        f"organism={facts.get('organism','')}, taxid={taxon}."),
                 "evidence_source": ev_url,
                 "severity": sev, "classification": "stale-but-valid label"})

        # per-row symbol / organism checks
        for sname, rows in acc_rows.get(acc, {}).items():
            for row in rows:
                sgene = get_gene_symbol(row, sname)
                if sgene and auth_gene and sgene.upper() != auth_gene.upper():
                    if sgene.upper() in synonyms:
                        add({"gene": auth_gene, "observed": sgene, "correct": auth_gene,
                             "retrieved_evidence": (f"Gene symbol '{sgene}' is a known synonym/previous name for "
                                                    f"{auth_gene} (accession {primary}). Authority synonyms: "
                                                    f"{facts.get('gene_synonyms', [])}."),
                             "evidence_source": ev_url,
                             "severity": "low", "classification": "stale-but-valid label"})
                    else:
                        _emit_conflict(add, row, sname, acc, primary, facts,
                                       authgene_to_primary, primary_facts, auth)

                # organism mismatch (source looks human but authority says otherwise)
                if taxon and taxon != HUMAN_TAXON:
                    sorg = (row.get("organism", "") if sname in ("uniprot", "chembl")
                            else row.get("species", "") if sname == "bindingdb" else "")
                    if sorg and is_harmless_organism(sorg):
                        add({"gene": auth_gene or sgene,
                             "observed": f"{sorg} (claimed for {acc})",
                             "correct": f"{facts.get('organism','')} (taxid={taxon})",
                             "retrieved_evidence": (f"Accession {primary} belongs to {facts.get('organism','')} "
                                                    f"(taxid={taxon}), not Homo sapiens (9606)."),
                             "evidence_source": ev_url,
                             "severity": "high", "classification": "wrong mapping"})

    # ---- Publications: assign to golden records (no findings) ----
    log("Phase 5: Matching publications...")
    pub_sources_for: dict[str, bool] = defaultdict(bool)
    # symbol/synonym -> primary
    sym_to_primary: dict[str, str] = dict(authgene_to_primary)
    for p, f in primary_facts.items():
        for s in f.get("gene_synonyms", []):
            sym_to_primary.setdefault(s.upper(), p)
    for sname in STRUCT_SOURCES:
        for row in sources.get(sname, []):
            g = get_gene_symbol(row, sname)
            a = get_accession(row, sname)
            if g and a in acc_to_primary:
                sym_to_primary.setdefault(g.upper(), acc_to_primary[a])
    pname_to_primary = {_norm(f.get("protein_name", "")): p for p, f in primary_facts.items() if f.get("protein_name")}

    for row in sources.get("publications", []):
        mention = row.get("target_mention", "").strip()
        context = row.get("context_sentence", "")
        primary = _match_publication(mention, context, sym_to_primary, pname_to_primary, primary_facts)
        if primary:
            pub_sources_for[primary] = True

    # ---- Golden records ----
    log("Phase 6: Building golden records...")
    primary_to_srcs: dict[str, set[str]] = defaultdict(set)
    for acc in all_accs:
        p = acc_to_primary.get(acc, acc)
        for sname in acc_rows.get(acc, {}):
            primary_to_srcs[p].add(sname)
    for p, has in pub_sources_for.items():
        if has and p in primary_to_srcs:
            primary_to_srcs[p].add("publications")

    golden = []
    for primary in sorted(primary_to_srcs):
        f = primary_facts.get(primary)
        gene = f.get("gene_name") if f else ""
        if not gene:  # fall back to a source-provided symbol
            for sname in STRUCT_SOURCES:
                for acc in all_accs:
                    if acc_to_primary.get(acc) == primary:
                        for row in acc_rows.get(acc, {}).get(sname, []):
                            g = get_gene_symbol(row, sname)
                            if g:
                                gene = g
                                break
                    if gene:
                        break
                if gene:
                    break
        golden.append({"gene": gene, "primary_accession": primary,
                       "sources": sorted(primary_to_srcs[primary])})

    findings.sort(key=lambda x: (x["classification"], x["gene"], x["observed"], x["correct"]))
    log(f"  {len(golden)} golden records, {len(findings)} findings")
    return {"unique_target_count": len(golden), "golden_records": golden, "findings": findings}


def _emit_conflict(add, row, sname, acc, primary, facts, authgene_to_primary, primary_facts, auth):
    """Gene symbol conflicts with the accession's authority gene. Decide which is wrong
    using corroboration from the row's descriptive name & fields."""
    sgene = get_gene_symbol(row, sname)
    auth_gene = facts.get("gene_name", "")
    n_acc = facts.get("protein_name", "")
    d = get_row_name(row, sname)
    row_ref = get_row_ref(row, sname)

    # symbol's own accession (prefer data; else EBI gene search)
    a_sym = authgene_to_primary.get(sgene.upper())
    if not a_sym:
        a_sym = _gene_search_primary(auth, sgene)
    n_sym = (primary_facts.get(a_sym, {}) or {}).get("protein_name", "") if a_sym else ""
    if not n_sym and a_sym:
        f2 = auth.ebi_facts(a_sym)
        n_sym = f2.get("protein_name", "") if f2 else ""

    # score: does the row's descriptive name match the symbol's protein or the accession's?
    s_score = a_score = 0
    nd = _norm(d)
    if nd and n_sym and nd == _norm(n_sym):
        s_score += 3
    elif nd and n_sym and (nd in _norm(n_sym) or _norm(n_sym) in nd) and len(nd) > 4:
        s_score += 1
    if nd and n_acc and nd == _norm(n_acc):
        a_score += 3
    elif nd and n_acc and (nd in _norm(n_acc) or _norm(n_acc) in nd) and len(nd) > 4:
        a_score += 1
    # a second field (e.g. bindingdb target_name) literally equal to the symbol corroborates it
    if _norm(d) == _norm(sgene):
        s_score += 2

    accession_is_wrong = a_sym is not None and s_score > a_score

    if accession_is_wrong:
        add({"gene": sgene, "observed": f"{acc} ({sname} row {row_ref}, labeled {sgene})",
             "correct": a_sym,
             "retrieved_evidence": (f"Row identifies {sgene} (\"{d}\"), but accession {acc} is {auth_gene} "
                                    f"(\"{n_acc}\"). The correct accession for {sgene} is {a_sym} (\"{n_sym}\")."),
             "evidence_source": f"{EBI_API}/{acc} ; {EBI_API}/{a_sym}",
             "severity": "high", "classification": "wrong mapping"})
    else:
        add({"gene": auth_gene, "observed": sgene, "correct": auth_gene,
             "retrieved_evidence": (f"Accession {primary} is {auth_gene} (\"{n_acc}\"); stated gene symbol "
                                    f"'{sgene}' does not match and is not a listed synonym "
                                    f"(synonyms: {facts.get('gene_synonyms', [])}). Row name=\"{d}\"."),
             "evidence_source": f"{EBI_API}/{primary}",
             "severity": "high", "classification": "wrong mapping"})


def _gene_search_primary(auth: "Authority", symbol: str) -> str | None:
    """Resolve a gene symbol to its reviewed human primary accession via EBI search."""
    try:
        q = urllib.parse.urlencode({"offset": 0, "size": 5, "gene": symbol,
                                    "taxid": HUMAN_TAXON, "reviewed": "true"})
        status, data = auth._http_json(f"{EBI_API}?{q}")
        if status == "ok" and isinstance(data, list):
            for e in data:
                g = (e.get("gene", [{}])[0].get("name", {}).get("value", "") or "").upper()
                if g == symbol.upper():
                    return e.get("accession")
            if data:
                return data[0].get("accession")
    except Exception:
        pass
    return None


def _match_publication(mention, context, sym_to_primary, pname_to_primary, primary_facts):
    """Assign a publication mention to a primary. Ambiguity resolved from context text
    (generic — matches the full protein name in the sentence), never from pmid."""
    if not mention:
        return None
    key = mention.upper()
    # direct unique symbol match
    if key in sym_to_primary:
        # check ambiguity: multiple primaries whose approved gene == mention
        cands = [p for p, f in primary_facts.items() if f.get("gene_name", "").upper() == key]
        if len(cands) <= 1:
            return sym_to_primary[key]
        # ambiguous approved symbol: disambiguate by protein name appearing in context
        nctx = _norm(context)
        best = None
        for p in cands:
            pn = _norm(primary_facts[p].get("protein_name", ""))
            if pn and pn in nctx:
                best = p
                break
        return best or sym_to_primary[key]
    # mention not a known symbol: match the protein name from the context sentence
    nctx = _norm(context)
    best_p, best_len = None, 0
    for pn, p in pname_to_primary.items():
        if pn and pn in nctx and len(pn) > best_len:
            best_p, best_len = p, len(pn)
    return best_p


def validate_pack(pack_dir: Path) -> None:
    if not pack_dir.is_dir():
        sys.exit(f"error: pack_dir not found or not a directory: {pack_dir}")
    missing = [f for f in SOURCE_FILES if not (pack_dir / f).is_file()]
    if missing:
        sys.exit(f"error: missing source files in {pack_dir}: {', '.join(missing)}")


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile source extracts into golden target records.")
    ap.add_argument("pack_dir", type=Path, help="directory with the five source_*.csv files")
    args = ap.parse_args(argv)
    validate_pack(args.pack_dir)
    result = reconcile(args.pack_dir)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
