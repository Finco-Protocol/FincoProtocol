"""Synthetic tests for the T01-E remediation-report generator (offline)."""
from __future__ import annotations

import pytest

from tax_reference_registry.remediation import generate_remediation_report
from tests.tax_reference_registry.conftest import base_row, rows_to_csv


def test_accepts_valid_row(tmp_path):
    p = tmp_path / "ok.csv"
    p.write_text(rows_to_csv([base_row()]), encoding="utf-8")
    report = generate_remediation_report(str(p))
    assert report["accepted"] == 1
    assert report["rejected"] == 0
    assert report["rows"][0]["disposition"] == "OK"


def test_false_verified_gets_needs_primary_url(tmp_path):
    p = tmp_path / "fv.csv"
    p.write_text(
        rows_to_csv([base_row(source_status="PRIMARY_CONFIRMED", primary_url="")]),
        encoding="utf-8",
    )
    report = generate_remediation_report(str(p))
    assert report["rejected"] == 1
    assert report["rows"][0]["disposition"] == "NEEDS_PRIMARY_URL"


def test_text_value_gets_needs_structured_value(tmp_path):
    p = tmp_path / "tv.csv"
    p.write_text(
        rows_to_csv([base_row(value="23% corporations / 27.5% others")]),
        encoding="utf-8",
    )
    report = generate_remediation_report(str(p))
    assert report["rows"][0]["disposition"] == "NEEDS_STRUCTURED_VALUE"


def test_duplicate_gets_deduplicate(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text(rows_to_csv([base_row(), base_row(value="22")]), encoding="utf-8")
    report = generate_remediation_report(str(p))
    assert report["rejection_reasons"].get("DUPLICATE_RULE_ID", 0) >= 1


def test_missing_provenance_with_evidence_id_passes(tmp_path):
    p = tmp_path / "evid.csv"
    p.write_text(
        rows_to_csv([base_row(primary_url="", professional_source_url="")]),
        encoding="utf-8",
    )
    report = generate_remediation_report(str(p))
    assert report["accepted"] == 1  # evidence_id is present


def test_report_is_deterministic(tmp_path):
    rows = [
        base_row(),
        base_row(rule_id="ZZ-NOL-001", tax_category="NOL", subrule="cf", value="5", value_unit="years"),
        base_row(rule_id="ZZ-VAT-001", tax_category="VAT", subrule="std", value="21", value_unit="pct"),
    ]
    p = tmp_path / "multi.csv"
    p.write_text(rows_to_csv(rows), encoding="utf-8")
    r1 = generate_remediation_report(str(p))
    r2 = generate_remediation_report(str(p))
    assert r1["rows"] == r2["rows"]
    assert r1["rejection_reasons"] == r2["rejection_reasons"]


def test_private_marker_flagged(tmp_path):
    p = tmp_path / "priv.csv"
    p.write_text(
        rows_to_csv([base_row(condition_logic="prepared for ACME Corp review")]),
        encoding="utf-8",
    )
    report = generate_remediation_report(str(p), private_markers=("ACME Corp",))
    assert report["rejected"] == 1


def test_activation_still_blocked():
    from tax_reference_registry import (
        ActivationBlockedError,
        activate_country,
        get_effective_run_profile,
    )
    with pytest.raises(ActivationBlockedError):
        activate_country("ZZ")
    with pytest.raises(ActivationBlockedError):
        get_effective_run_profile("ZZ")
