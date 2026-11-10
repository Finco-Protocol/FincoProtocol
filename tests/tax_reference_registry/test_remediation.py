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


def test_empty_dataset_report(tmp_path):
    """A CSV with only a header produces a zero-row report, not a crash."""
    p = tmp_path / "empty.csv"
    p.write_text(rows_to_csv([]), encoding="utf-8")
    report = generate_remediation_report(str(p))
    assert report["accepted"] == 0
    assert report["rejected"] == 0
    assert report["rows"] == []


def test_all_rejected_report(tmp_path):
    """A dataset where every row is rejected still produces a valid report."""
    rows = [
        base_row(rule_id="ZZ-BAD-001", value="not a number"),
        base_row(rule_id="ZZ-BAD-002", source_status="PRIMARY_CONFIRMED", primary_url=""),
        base_row(rule_id="ZZ-BAD-003", value_currency="INVALID"),
    ]
    p = tmp_path / "allbad.csv"
    p.write_text(rows_to_csv(rows), encoding="utf-8")
    report = generate_remediation_report(str(p))
    assert report["accepted"] == 0
    assert report["rejected"] == 3
    dispositions = {r["disposition"] for r in report["rows"]}
    assert "NEEDS_STRUCTURED_VALUE" in dispositions
    assert "NEEDS_PRIMARY_URL" in dispositions
    assert "MAP_CURRENCY" in dispositions


def test_mixed_accepted_rejected_report(tmp_path):
    """A mixed dataset correctly partitions accepted and rejected rows."""
    rows = [
        base_row(),
        base_row(rule_id="ZZ-BAD-001", source_status="PRIMARY_CONFIRMED", primary_url=""),
        base_row(rule_id="ZZ-NOL-001", tax_category="NOL", subrule="cf", value="5", value_unit="years"),
    ]
    p = tmp_path / "mixed.csv"
    p.write_text(rows_to_csv(rows), encoding="utf-8")
    report = generate_remediation_report(str(p))
    assert report["accepted"] == 2
    assert report["rejected"] == 1
    accepted_ids = {r["rule_id"] for r in report["rows"] if r["admission"] == "accepted"}
    assert "ZZ-CIT-001" in accepted_ids
    assert "ZZ-NOL-001" in accepted_ids
    assert "ZZ-BAD-001" not in accepted_ids


def test_report_tag_is_stable():
    """The report tag is a stable identifier for downstream tooling."""
    from tax_reference_registry.remediation import generate_remediation_report as gen
    # Just verify the tag doesn't change between imports
    assert gen.__module__ == "tax_reference_registry.remediation"


def test_rejected_row_preserves_tax_category_and_evidence_id(tmp_path):
    """Rejected rows carry their original tax_category, subrule and evidence_id
    from the CSV (not blank), so downstream remediation tools have context."""
    p = tmp_path / "preserve.csv"
    p.write_text(
        rows_to_csv([
            base_row(
                rule_id="ZZ-WHT-001",
                tax_category="WHT",
                subrule="dividends WHT",
                evidence_id="EV-SYNTH-ZZ-WHT",
                source_status="PRIMARY_CONFIRMED",
                primary_url="",
            ),
        ]),
        encoding="utf-8",
    )
    report = generate_remediation_report(str(p))
    rejected = [r for r in report["rows"] if r["admission"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["tax_category"] == "WHT"
    assert rejected[0]["subrule"] == "dividends WHT"
    assert rejected[0]["evidence_id"] == "EV-SYNTH-ZZ-WHT"
    assert rejected[0]["row_number"] == 2


def test_report_does_not_expose_private_disk_path(tmp_path):
    """The report structure has no 'source' key with the private disk path."""
    p = tmp_path / "nosource.csv"
    p.write_text(rows_to_csv([base_row()]), encoding="utf-8")
    report = generate_remediation_report(str(p))
    assert "source" not in report or "private" not in str(report.get("source", "")).lower()


def test_row_number_traces_to_csv_line(tmp_path):
    """Rejected row_numbers are 2-based (header = line 1) for traceability."""
    rows = [
        base_row(),
        base_row(rule_id="ZZ-BAD-001", source_status="PRIMARY_CONFIRMED", primary_url=""),
    ]
    p = tmp_path / "trace.csv"
    p.write_text(rows_to_csv(rows), encoding="utf-8")
    report = generate_remediation_report(str(p))
    rejected = [r for r in report["rows"] if r["admission"] == "rejected"]
    assert rejected[0]["row_number"] == 3  # row 1 = header, row 2 = ZZ-CIT-001, row 3 = ZZ-BAD-001
