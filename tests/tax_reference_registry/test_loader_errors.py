"""Loader rejection matrix: every per-row error path from the T01-D contract."""
from __future__ import annotations

import pytest

from tax_reference_registry import (
    LawStatus,
    VerificationStatus,
    load_records,
)
from tax_reference_registry.loader import RecordFormatError
from tests.tax_reference_registry.conftest import base_row, rows_to_csv


def _errors(result):
    return {e.reason: e for e in result.errors}


def test_valid_row_loads(zz_single):
    result = load_records(zz_single, source_path="zz")
    assert result.valid == 1
    rec = result.records[0]
    assert rec.verification is VerificationStatus.SECONDARY_ONLY
    assert rec.law_status is LawStatus.IN_FORCE
    # IN_FORCE must never imply verified:
    assert rec.is_verified is False


def test_duplicate_rule_id_rejected(tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text(
        rows_to_csv([base_row(), base_row(value="22")]), encoding="utf-8"
    )
    result = load_records(path)
    assert "DUPLICATE_RULE_ID" in _errors(result)


def test_overlapping_contradictory_windows_rejected(tmp_path):
    path = tmp_path / "overlap.csv"
    path.write_text(
        rows_to_csv(
            [
                base_row(law_effective_from="2024-01-01", law_effective_to="2026-12-31"),
                base_row(rule_id="ZZ-CIT-002", value="22",
                         law_effective_from="2026-06-01", law_effective_to="2027-12-31"),
            ]
        ),
        encoding="utf-8",
    )
    result = load_records(path)
    assert "OVERLAPPING_WINDOWS" in _errors(result)
    # Disjoint windows must NOT raise at registry level
    ok_path = tmp_path / "disjoint.csv"
    ok_path.write_text(
        rows_to_csv(
            [
                base_row(law_effective_from="2024-01-01", law_effective_to="2026-12-31"),
                base_row(rule_id="ZZ-CIT-002", value="22",
                         law_effective_from="2027-01-01", law_effective_to="2027-12-31"),
            ]
        ),
        encoding="utf-8",
    )
    ok = load_records(ok_path)
    assert ok.valid == 2


def test_from_after_to_rejected(tmp_path):
    path = tmp_path / "reversed.csv"
    path.write_text(
        rows_to_csv([base_row(law_effective_from="2026-12-31", law_effective_to="2024-01-01")]),
        encoding="utf-8",
    )
    result = load_records(path)
    assert "CONTRADICTORY_WINDOW" in _errors(result)


def test_text_value_rejected_not_defaulted(tmp_path):
    path = tmp_path / "textval.csv"
    path.write_text(
        rows_to_csv([base_row(value="23% corporations / 27.5% other recipients")]),
        encoding="utf-8",
    )
    result = load_records(path)
    errs = _errors(result)
    assert "VALUE_UNPARSED" in errs
    assert result.valid == 0  # ambiguity never becomes a default tax value


def test_unparsed_unit_rejected(tmp_path):
    path = tmp_path / "unit.csv"
    path.write_text(rows_to_csv([base_row(value_unit="'; DROP TABLE")]), encoding="utf-8")
    result = load_records(path)
    assert "UNIT_UNPARSED" in _errors(result)


def test_unsupported_currency_rejected(tmp_path):
    path = tmp_path / "cur.csv"
    path.write_text(rows_to_csv([base_row(value_currency="ZZZ")]), encoding="utf-8")
    result = load_records(path)
    assert "UNSUPPORTED_CURRENCY" in _errors(result)


def test_false_verified_status_rejected(tmp_path):
    path = tmp_path / "falsever.csv"
    path.write_text(
        rows_to_csv([base_row(source_status="PRIMARY_CONFIRMED", primary_url="")]),
        encoding="utf-8",
    )
    result = load_records(path)
    assert "FALSE_VERIFIED_STATUS" in _errors(result)


def test_missing_provenance_rejected(tmp_path):
    path = tmp_path / "noproven.csv"
    path.write_text(
        rows_to_csv(
            [
                base_row(
                    primary_url="",
                    professional_source_url="",
                    evidence_id="",
                )
            ]
        ),
        encoding="utf-8",
    )
    result = load_records(path)
    assert "MISSING_ESSENTIAL_PROVENANCE" in _errors(result)
    # Evidence-id pointer alone satisfies minimal provenance (private chain):
    ok_path = tmp_path / "evidonly.csv"
    ok_path.write_text(
        rows_to_csv([base_row(primary_url="", professional_source_url="")]),
        encoding="utf-8",
    )
    ok = load_records(ok_path)
    assert ok.valid == 1


def test_unsupported_asset_class_rejected(tmp_path):
    path = tmp_path / "asset.csv"
    path.write_text(rows_to_csv([base_row(asset_class="SOLAR_PANELS_MAGICAL")]), encoding="utf-8")
    result = load_records(path)
    assert "UNSUPPORTED_ASSET_CLASS" in _errors(result)


def test_unknown_tier_and_law_status_rejected(tmp_path):
    path = tmp_path / "badcat.csv"
    path.write_text(rows_to_csv([base_row(tax_category="MYSTERY")]), encoding="utf-8")
    result = load_records(path)
    assert "UNSUPPORTED_TAX_CATEGORY" in _errors(result)
    path2 = tmp_path / "badlaw.csv"
    path2.write_text(rows_to_csv([base_row(law_status="SUPER_IN_FORCE")]), encoding="utf-8")
    result2 = load_records(path2)
    assert "UNSUPPORTED_LAW_STATUS" in _errors(result2)


def test_private_metadata_marker_rejects_row(tmp_path):
    path = tmp_path / "marker.csv"
    path.write_text(
        rows_to_csv([base_row(condition_logic="prepared for CLIENT-X review")]),
        encoding="utf-8",
    )
    result = load_records(path, private_markers=["CLIENT-X"])
    assert "PRIVATE_METADATA_SUSPECTED" in _errors(result)
    # Without the marker configured the row loads (markers are caller-supplied).
    plain = load_records(path)
    assert plain.valid == 1


def test_unknown_extra_column_rejected(tmp_path):
    path = tmp_path / "extra.csv"
    text = rows_to_csv([base_row()])
    header = text.splitlines()[0] + ",client_account_number"
    body = text.splitlines()[1] + ",XX12345"
    path.write_text(header + "\n" + body + "\n", encoding="utf-8")
    with pytest.raises(RecordFormatError):
        load_records(path)


def test_incompatible_file_formats_rejected(tmp_path):
    json_path = tmp_path / "notcsv.json"
    json_path.write_text('{"rows": []}', encoding="utf-8")
    with pytest.raises(RecordFormatError):
        load_records(json_path)
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("", encoding="utf-8")
    with pytest.raises(RecordFormatError):
        load_records(empty_path)
    missing_path = tmp_path / "missing.csv"
    missing_path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(RecordFormatError):
        load_records(missing_path)


def test_non_iso_date_warns_but_preserves(tmp_path):
    path = tmp_path / "date.csv"
    path.write_text(
        rows_to_csv([base_row(law_effective_from="2024 tax year")]),
        encoding="utf-8",
    )
    result = load_records(path)
    assert result.valid == 1
    assert any(w.reason == "DATE_UNPARSED" for w in result.warnings)
    rec = result.records[0]
    assert rec.window.effective_from_raw == "2024 tax year"
    assert rec.window.effective_from is None


def test_corroborated_maps_down_and_preserves_raw(tmp_path):
    path = tmp_path / "corr.csv"
    path.write_text(rows_to_csv([base_row(source_status="CORROBORATED")]), encoding="utf-8")
    result = load_records(path)
    rec = result.records[0]
    assert rec.verification is VerificationStatus.SECONDARY_ONLY
    assert rec.source_status_raw == "CORROBORATED"


def test_proposed_not_law_becomes_draft(tmp_path):
    path = tmp_path / "draft.csv"
    path.write_text(rows_to_csv([base_row(source_status="PROPOSED_NOT_LAW")]), encoding="utf-8")
    result = load_records(path)
    rec = result.records[0]
    assert rec.law_status is LawStatus.DRAFT
    assert rec.verification is VerificationStatus.NOT_TESTED


def test_xk_internal_code_accepted(tmp_path):
    path = tmp_path / "xk.csv"
    path.write_text(
        rows_to_csv([base_row(rule_id="XK-CIT-001", jurisdiction_code="XK")]),
        encoding="utf-8",
    )
    result = load_records(path)
    assert result.valid == 1
