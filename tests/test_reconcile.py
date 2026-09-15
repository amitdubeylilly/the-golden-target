"""
Tests for reconcile.py — each test case uses a fixture directory under
tests/fixtures/<case>/ containing the five source CSV files, and mocks
ProteinAuthority so no network calls are made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import reconcile from the project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import reconcile as reconcile_mod
from reconcile import reconcile

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# ---------------------------------------------------------------------------
# Mock ProteinAuthority helpers
# ---------------------------------------------------------------------------

EBI_API = "https://www.ebi.ac.uk/proteins/api/proteins"


def _authority_entry(
    primary: str,
    gene_name: str,
    *,
    synonyms: list[str] | None = None,
    organism: str = "Homo sapiens",
    taxon_id: int = 9606,
    protein_name: str = "",
    secondary_accessions: list[str] | None = None,
    queried: str | None = None,
    merged_from: str | None = None,
) -> dict:
    """Build a deterministic authority response dict."""
    result = {
        "primary_accession": primary,
        "secondary_accessions": secondary_accessions or [],
        "gene_name": gene_name,
        "gene_synonyms": synonyms or [],
        "organism": organism,
        "taxon_id": taxon_id,
        "protein_name": protein_name,
        "queried_accession": queried or primary,
        "source": f"{EBI_API}/{queried or primary}",
    }
    if merged_from is not None:
        result["merged_from"] = merged_from
    return result


def _make_mock_authority_class(responses: dict):
    """Return a class whose instances behave like ProteinAuthority but use
    a fixed lookup table instead of HTTP calls."""

    class _MockAuthority:
        def __init__(self):
            pass

        def resolve_batch(self, accessions: list[str]) -> None:
            pass  # no-op; everything is in the table

        def resolve(self, accession: str) -> dict | None:
            return responses.get(accession.strip())

    return _MockAuthority


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------

def _assert_valid_output(result: dict) -> None:
    """Check that the reconcile output has the expected top-level shape."""
    assert isinstance(result, dict)
    assert "unique_target_count" in result
    assert "golden_records" in result
    assert "findings" in result
    assert isinstance(result["unique_target_count"], int)
    assert isinstance(result["golden_records"], list)
    assert isinstance(result["findings"], list)
    assert result["unique_target_count"] == len(result["golden_records"])

    # Every golden record must have gene, primary_accession, sources
    for gr in result["golden_records"]:
        assert "gene" in gr
        assert "primary_accession" in gr
        assert "sources" in gr

    # Every finding must have observed and correct
    for f in result["findings"]:
        assert "observed" in f, f"Finding missing 'observed': {f}"
        assert "correct" in f, f"Finding missing 'correct': {f}"
        assert "classification" in f, f"Finding missing 'classification': {f}"

    # Verify JSON-serialisable
    json.dumps(result)


# ===================================================================
# Test cases
# ===================================================================


class TestCleanBaseline:
    """All three targets are consistent across every source.  No defects."""

    RESPONSES = {
        "P00533": _authority_entry(
            "P00533", "EGFR",
            protein_name="Epidermal growth factor receptor",
        ),
        "P38398": _authority_entry(
            "P38398", "BRCA1",
            protein_name="Breast cancer type 1 susceptibility protein",
        ),
        "P04637": _authority_entry(
            "P04637", "TP53",
            protein_name="Cellular tumor antigen p53",
        ),
    }

    def test_clean_baseline(self):
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "clean_baseline")

        _assert_valid_output(result)
        assert result["unique_target_count"] == 3
        assert len(result["golden_records"]) == 3
        assert result["findings"] == [], (
            f"Expected no findings, got: {result['findings']}"
        )


class TestWrongMapping:
    """One source claims gene_symbol MAPK3 for accession P28482, but the
    authority says the gene is MAPK1 and MAPK3 is not a synonym."""

    RESPONSES = {
        "P00533": _authority_entry(
            "P00533", "EGFR",
            protein_name="Epidermal growth factor receptor",
        ),
        "P38398": _authority_entry(
            "P38398", "BRCA1",
            protein_name="Breast cancer type 1 susceptibility protein",
        ),
        "P28482": _authority_entry(
            "P28482", "MAPK1",
            synonyms=["ERK2", "PRKM2"],
            protein_name="Mitogen-activated protein kinase 1",
        ),
    }

    def test_wrong_mapping_detected(self):
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "wrong_mapping")

        _assert_valid_output(result)
        assert result["unique_target_count"] == 3

        wrong = [
            f for f in result["findings"]
            if f["classification"] == "wrong mapping"
        ]
        assert len(wrong) >= 1, (
            f"Expected at least one 'wrong mapping' finding, got: {result['findings']}"
        )
        # The observed value should reference MAPK3, the correct should be MAPK1
        wm = wrong[0]
        assert "MAPK3" in wm["observed"]
        assert "MAPK1" in wm["correct"] or wm["gene"] == "MAPK1"


class TestStaleLabel:
    """One source uses the old symbol ERBA2 for accession P10828, which the
    authority lists as a known synonym of THRB."""

    RESPONSES = {
        "P00533": _authority_entry(
            "P00533", "EGFR",
            protein_name="Epidermal growth factor receptor",
        ),
        "P38398": _authority_entry(
            "P38398", "BRCA1",
            protein_name="Breast cancer type 1 susceptibility protein",
        ),
        "P10828": _authority_entry(
            "P10828", "THRB",
            synonyms=["ERBA2", "THR1", "NR1A2", "THRB1"],
            protein_name="Thyroid hormone receptor beta",
        ),
    }

    def test_stale_label_detected(self):
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "stale_label")

        _assert_valid_output(result)
        assert result["unique_target_count"] == 3

        stale = [
            f for f in result["findings"]
            if f["classification"] == "stale-but-valid label"
        ]
        assert len(stale) >= 1, (
            f"Expected at least one 'stale-but-valid label' finding, "
            f"got: {result['findings']}"
        )
        sl = stale[0]
        assert "ERBA2" in sl["observed"]
        assert "THRB" in sl["correct"] or sl["gene"] == "THRB"


class TestDuplicate:
    """Accessions P29317 and B5A968 both resolve to primary P29317 (EPHA2).
    B5A968 is neither merged nor secondary -- it is a duplicate identity."""

    RESPONSES = {
        "P00533": _authority_entry(
            "P00533", "EGFR",
            protein_name="Epidermal growth factor receptor",
        ),
        "P29317": _authority_entry(
            "P29317", "EPHA2",
            protein_name="Ephrin type-A receptor 2",
        ),
        "B5A968": _authority_entry(
            "P29317", "EPHA2",
            queried="B5A968",
            protein_name="Ephrin type-A receptor 2",
        ),
    }

    def test_duplicate_identity_detected(self):
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "duplicate")

        _assert_valid_output(result)
        # Both accessions collapse to one primary, so 2 unique targets
        assert result["unique_target_count"] == 2, (
            f"Expected 2 unique targets (EGFR + EPHA2), "
            f"got {result['unique_target_count']}"
        )

        dupes = [
            f for f in result["findings"]
            if f["classification"] == "duplicate identity"
        ]
        assert len(dupes) >= 1, (
            f"Expected at least one 'duplicate identity' finding, "
            f"got: {result['findings']}"
        )


class TestHarmlessVariance:
    """Species listed as 'Homo sapiens', 'H. sapiens', 'human' across
    sources.  Authority confirms taxon 9606.  No findings expected."""

    RESPONSES = {
        "P00533": _authority_entry(
            "P00533", "EGFR",
            protein_name="Epidermal growth factor receptor",
        ),
    }

    def test_no_findings(self):
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "harmless_variance")

        _assert_valid_output(result)
        assert result["unique_target_count"] == 1
        assert result["findings"] == [], (
            f"Expected no findings for harmless organism variance, "
            f"got: {result['findings']}"
        )


class TestPmidTrap:
    """Publications carry pmid values -- they should NOT be fetched against
    the protein authority or produce any findings."""

    RESPONSES = {
        "P00533": _authority_entry(
            "P00533", "EGFR",
            protein_name="Epidermal growth factor receptor",
        ),
    }

    def test_pmids_not_flagged(self):
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "pmid_trap")

        _assert_valid_output(result)
        assert result["unique_target_count"] == 1
        assert result["findings"] == [], (
            f"PMIDs should not generate findings, got: {result['findings']}"
        )

    def test_publications_assigned_to_golden_record(self):
        """The publication rows should be assigned to the EGFR golden record."""
        MockAuth = _make_mock_authority_class(self.RESPONSES)
        with patch.object(reconcile_mod, "ProteinAuthority", MockAuth):
            result = reconcile(FIXTURES_DIR / "pmid_trap")

        egfr_records = [
            gr for gr in result["golden_records"]
            if gr["gene"] == "EGFR"
        ]
        assert len(egfr_records) == 1
        assert "publications" in egfr_records[0]["sources"]
