"""
Tests for reconcile.py — self-contained (no on-disk fixtures, no network).

Each test writes a tiny 5-file pack into a temp dir and patches the Authority HTTP
layer (`Authority._http_json`) with canned EBI/ChEMBL JSON. This exercises the real
response parsing, the secondary->primary index, ChEMBL-collision resolution and the
conflict-direction logic — the parts most likely to break.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import reconcile as R
from reconcile import reconcile

HDR = {
    "uniprot": "accession,entry_name,gene_names,protein_name,organism,reviewed,length,database",
    "chembl": "chembl_id,pref_name,target_type,accession,gene_symbol,organism,tax_id,target_confidence",
    "bindingdb": "target_name,species,uniprot_id,gene_symbol,assay_count,binding_type",
    "internal": "internal_id,registered_name,gene_symbol,source_db,external_id,uniprot_ref,registered_by,registration_date,status",
    "publications": "pmid,target_mention,context_sentence,journal,year",
}


def write_pack(tmp_path: Path, rows: dict[str, list[str]]) -> Path:
    for src, hdr in HDR.items():
        body = [hdr] + rows.get(src, [])
        (tmp_path / f"source_{src}.csv").write_text("\n".join(body) + "\n")
    return tmp_path


# ---- canned authority ----------------------------------------------------
def ebi(acc, gene, prot, synonyms=None, taxon=9606, organism="Homo sapiens", secondary=None):
    return {"accession": acc,
            "gene": [{"name": {"value": gene}, "synonyms": [{"value": s} for s in (synonyms or [])]}],
            "organism": {"taxonomy": taxon, "names": [{"type": "scientific", "value": organism}]},
            "protein": {"recommendedName": {"fullName": {"value": prot}}},
            "secondaryAccession": secondary or []}


EBI_DB = {
    "P00533": ebi("P00533", "EGFR", "Epidermal growth factor receptor"),
    "P38398": ebi("P38398", "BRCA1", "Breast cancer type 1 susceptibility protein"),
    "P04637": ebi("P04637", "TP53", "Cellular tumor antigen p53"),
    "P28482": ebi("P28482", "MAPK1", "Mitogen-activated protein kinase 1", synonyms=["ERK", "PRKM2"]),
    "P10828": ebi("P10828", "THRB", "Thyroid hormone receptor beta", synonyms=["ERBA2", "NR1A2", "THR1"]),
    "P29317": ebi("P29317", "EPHA2", "Ephrin type-A receptor 2", secondary=["B5A968"]),
    "Q13946": ebi("Q13946", "PDE7A", "High affinity cAMP-specific phosphodiesterase 7A"),
    "Q9Y233": ebi("Q9Y233", "PDE10A", "cGMP phosphodiesterase 10A"),
    "P11309": ebi("P11309", "PIM1", "Serine/threonine-protein kinase pim-1"),
    "Q9P1W9": ebi("Q9P1W9", "PIM2", "Serine/threonine-protein kinase pim-2"),
}
CHEMBL_DB = {
    "CHEMBL9999": {"pref_name": "PDE7A", "target_components": [
        {"accession": "Q13946",
         "target_component_synonyms": [{"syn_type": "GENE_SYMBOL", "component_synonym": "PDE7A"}]}]},
}


def fake_http_json(self, url):
    if "/chembl/api/data/target/" in url:
        cid = url.split("/target/")[1].split(".json")[0]
        return ("ok", CHEMBL_DB[cid]) if cid in CHEMBL_DB else ("notfound", None)
    if "/proteins?" in url or ("?" in url and "/proteins" in url):
        return ("ok", [])  # gene-search fallback not needed here
    acc = url.rstrip("/").rsplit("/", 1)[-1]
    return ("ok", EBI_DB[acc]) if acc in EBI_DB else ("notfound", None)


def run(tmp_path, rows):
    write_pack(tmp_path, rows)
    with patch.object(R.Authority, "_http_json", fake_http_json):
        return reconcile(tmp_path)


def assert_contract(res):
    assert set(res) == {"unique_target_count", "golden_records", "findings"}
    assert res["unique_target_count"] == len(res["golden_records"])
    for g in res["golden_records"]:
        assert g["gene"] and g["primary_accession"] and g["sources"]
    for f in res["findings"]:
        for k in ("gene", "observed", "correct", "retrieved_evidence",
                  "evidence_source", "severity", "classification"):
            assert k in f and f[k] != "", f"missing {k}: {f}"
    json.dumps(res)  # serialisable


CLEAN = {
    "uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot",
                "P38398,BRCA1_HUMAN,BRCA1,BRCA1 protein,Homo sapiens,reviewed,1863,Swiss-Prot",
                "P04637,P53_HUMAN,TP53,Cellular tumor antigen p53,Homo sapiens,reviewed,393,Swiss-Prot"],
    "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,Homo sapiens,9606,9",
               "CHEMBL3217,BRCA1,SINGLE PROTEIN,P38398,BRCA1,Homo sapiens,9606,9",
               "CHEMBL4096,p53,SINGLE PROTEIN,P04637,TP53,Homo sapiens,9606,9"],
    "bindingdb": ["EGFR,Homo sapiens,P00533,EGFR,1500,Ki", "BRCA1,Homo sapiens,P38398,BRCA1,200,IC50"],
    "internal": ["INT001,EGFR,EGFR,chembl,CHEMBL203,P00533,jdoe,2024-01-15,active"],
    "publications": ["12345678,EGFR,EGFR is overexpressed in cancers,Nature,2023"],
}


def test_clean_baseline(tmp_path):
    r = run(tmp_path, CLEAN)
    assert_contract(r)
    assert r["unique_target_count"] == 3
    assert r["findings"] == [], r["findings"]


def test_wrong_mapping_symbol_direction(tmp_path):
    rows = {"uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot",
                        "P28482,MK01_HUMAN,MAPK1,Mitogen-activated protein kinase 1,Homo sapiens,reviewed,360,Swiss-Prot"],
            "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,Homo sapiens,9606,9",
                       "CHEMBL4040,MAP kinase,SINGLE PROTEIN,P28482,MAPK3,Homo sapiens,9606,9"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    wm = [f for f in r["findings"] if f["classification"] == "wrong mapping"]
    assert wm and "MAPK3" in wm[0]["observed"] and ("MAPK1" in wm[0]["correct"] or wm[0]["gene"] == "MAPK1")


def test_stale_label_symbol(tmp_path):
    rows = {"uniprot": ["P10828,THRB_HUMAN,THRB,Thyroid hormone receptor beta,Homo sapiens,reviewed,461,Swiss-Prot"],
            "chembl": ["CHEMBL1940,Thyroid hormone receptor beta,SINGLE PROTEIN,P10828,ERBA2,Homo sapiens,9606,9"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    assert any(f["classification"] == "stale-but-valid label" and "ERBA2" in f["observed"] and "THRB" in f["correct"]
               for f in r["findings"]), r["findings"]


def test_duplicate_identity(tmp_path):
    rows = {"uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot",
                        "P29317,EPHA2_HUMAN,EPHA2,Ephrin type-A receptor 2,Homo sapiens,reviewed,976,Swiss-Prot"],
            "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,Homo sapiens,9606,9",
                       "CHEMBL2068,Ephrin type-A receptor 2,SINGLE PROTEIN,P29317,EPHA2,Homo sapiens,9606,9",
                       "CHEMBL2068,Ephrin type-A receptor 2,SINGLE PROTEIN,B5A968,EPHA2,Homo sapiens,9606,8"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    assert r["unique_target_count"] == 2  # EGFR + EPHA2 (B5A968 collapses into P29317)
    assert any(f["classification"] == "duplicate identity" and f["observed"] == "B5A968" and f["correct"] == "P29317"
               for f in r["findings"]), r["findings"]
    assert not any(f["classification"] == "stale-but-valid label" and f["observed"] == "B5A968"
                   for f in r["findings"])  # no double-report


def test_harmless_variance_no_findings(tmp_path):
    rows = {"uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot"],
            "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,H. sapiens,9606,9"],
            "bindingdb": ["Epidermal growth factor receptor,human,P00533,EGFR,1500,Ki"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    assert r["unique_target_count"] == 1 and r["findings"] == []


def test_pmid_trap(tmp_path):
    rows = {"uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot"],
            "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,Homo sapiens,9606,9"],
            "publications": ["99990001,EGFR,Targeting EGFR in NSCLC patients,Lancet,2024",
                             "99990002,EGFR,EGFR amplification in glioblastoma,Neuro-Oncology,2023"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    assert r["findings"] == [], r["findings"]  # pmids never flagged
    egfr = [g for g in r["golden_records"] if g["gene"] == "EGFR"][0]
    assert "publications" in egfr["sources"]


def test_chembl_collision_flags_only_intruder(tmp_path):
    rows = {"uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot",
                        "Q13946,PDE7A_HUMAN,PDE7A,High affinity cAMP-specific phosphodiesterase 7A,Homo sapiens,reviewed,482,Swiss-Prot",
                        "Q9Y233,PDE10_HUMAN,PDE10A,cGMP phosphodiesterase 10A,Homo sapiens,reviewed,779,Swiss-Prot"],
            "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,Homo sapiens,9606,9",
                       "CHEMBL9999,PDE7A,SINGLE PROTEIN,Q13946,PDE7A,Homo sapiens,9606,9",
                       "CHEMBL9999,PDE10A,SINGLE PROTEIN,Q9Y233,PDE10A,Homo sapiens,9606,8"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    wm = [f for f in r["findings"] if f["classification"] == "wrong mapping"]
    assert len(wm) == 1, wm                       # only the intruder
    assert "Q9Y233" in wm[0]["observed"] and "Q13946" in wm[0]["correct"]
    assert "chembl" in wm[0]["evidence_source"]
    assert not any("Q13946" in f["observed"] for f in wm)  # correct PDE7A row not flagged


def test_conflict_accession_direction(tmp_path):
    # Row labeled PIM1 with a PIM1 pref_name but PIM2's accession -> the ACCESSION is the defect.
    rows = {"uniprot": ["P00533,EGFR_HUMAN,EGFR,Epidermal growth factor receptor,Homo sapiens,reviewed,1210,Swiss-Prot",
                        "P11309,PIM1_HUMAN,PIM1,Serine/threonine-protein kinase pim-1,Homo sapiens,reviewed,313,Swiss-Prot"],
            "chembl": ["CHEMBL203,EGFR,SINGLE PROTEIN,P00533,EGFR,Homo sapiens,9606,9",
                       "CHEMBL2147,Serine/threonine-protein kinase pim-1,SINGLE PROTEIN,Q9P1W9,PIM1,Homo sapiens,9606,7"]}
    r = run(tmp_path, rows)
    assert_contract(r)
    wm = [f for f in r["findings"] if f["classification"] == "wrong mapping"]
    assert wm, r["findings"]
    assert "Q9P1W9" in wm[0]["observed"] and wm[0]["correct"] == "P11309" and wm[0]["gene"] == "PIM1"
