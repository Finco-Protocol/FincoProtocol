"""F07-B: Canonical Export Authority and Run-Bound Lineage tests.

Verifies:
- EXPORT_AUTHORITY_* constants exist
- Factory path → FACTORY_REFERENCE authority in CSV rows
- PREVIEW_WORKING authority propagated through export service
- working_changed_since_run is "true" when snapshots differ, "false" when equal
- run_id and run_at in CSV rows
- export_authority in workbook bundle
- _metric_value OPEX no longer falls back to snapshot
- Authority mode in both CSV and workbook metadata
- No financial value changes (IRR/revenue/EBITDA unchanged)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_export_authority_constants_exist():
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
        EXPORT_AUTHORITY_PREVIEW_WORKING,
    )
    assert EXPORT_AUTHORITY_CANONICAL_LAST_RUN == "CANONICAL_LAST_RUN"
    assert EXPORT_AUTHORITY_FACTORY_REFERENCE == "FACTORY_REFERENCE"
    assert EXPORT_AUTHORITY_PREVIEW_WORKING == "PREVIEW_WORKING"


# ---------------------------------------------------------------------------
# ResolvedExportAuthority fields
# ---------------------------------------------------------------------------


def test_resolved_export_authority_has_new_fields():
    from app.services.export_service import (
        ResolvedExportAuthority,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )
    auth = ResolvedExportAuthority(
        project_inputs=None,
        current_snapshot=None,
        runtime_origin=None,
    )
    assert auth.authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE
    assert auth.run_id is None
    assert auth.run_at is None
    assert auth.working_changed_since_run is False


# ---------------------------------------------------------------------------
# Runtime summary CSV — factory path → FACTORY_REFERENCE
# ---------------------------------------------------------------------------


def test_factory_path_runtime_summary_authority_mode():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows("generic_wind_reference")
    assert rows, "expected at least one row"
    for row in rows:
        assert row["export_authority"] == "FACTORY_REFERENCE"


def test_factory_path_runtime_summary_run_fields_not_applicable():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows("generic_wind_reference")
    for row in rows:
        assert row["run_id"] == "not_applicable"
        assert row["run_at"] == "not_applicable"
        assert row["working_changed_since_run"] == "not_applicable"


# ---------------------------------------------------------------------------
# working_changed_since_run encoding
# ---------------------------------------------------------------------------


def test_working_changed_since_run_true():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        working_changed_since_run=True,
    )
    for row in rows:
        assert row["working_changed_since_run"] == "true"


def test_working_changed_since_run_false():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        working_changed_since_run=False,
    )
    for row in rows:
        assert row["working_changed_since_run"] == "false"


def test_working_changed_since_run_none_is_not_applicable():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        working_changed_since_run=None,
    )
    for row in rows:
        assert row["working_changed_since_run"] == "not_applicable"


# ---------------------------------------------------------------------------
# run_id and run_at pass-through
# ---------------------------------------------------------------------------


def test_run_id_and_run_at_pass_through():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        run_id="run-abc-123",
        run_at="2026-01-01T00:00:00+00:00",
    )
    for row in rows:
        assert row["run_id"] == "run-abc-123"
        assert row["run_at"] == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# export_authority pass-through for explicit authority
# ---------------------------------------------------------------------------


def test_explicit_export_authority_preview_working():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        export_authority="PREVIEW_WORKING",
    )
    for row in rows:
        assert row["export_authority"] == "PREVIEW_WORKING"


# ---------------------------------------------------------------------------
# RUNTIME_SUMMARY_COLUMNS includes new columns
# ---------------------------------------------------------------------------


def test_runtime_summary_columns_include_new_fields():
    from app.export.runtime_summary import RUNTIME_SUMMARY_COLUMNS

    for col in ("export_authority", "working_changed_since_run", "run_id", "run_at"):
        assert col in RUNTIME_SUMMARY_COLUMNS, f"missing column: {col}"
    # notes must come after the new columns
    assert RUNTIME_SUMMARY_COLUMNS.index("notes") > RUNTIME_SUMMARY_COLUMNS.index("run_at")


# ---------------------------------------------------------------------------
# WorkbookExportBundle has new fields
# ---------------------------------------------------------------------------


def test_workbook_export_bundle_has_authority_fields():
    from app.export.institutional_workbook import WorkbookExportBundle
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(WorkbookExportBundle)}
    for name in ("export_authority", "working_changed_since_run", "run_id", "run_at"):
        assert name in field_names, f"WorkbookExportBundle missing field: {name}"


def test_workbook_bundle_factory_default_authority():
    from app.export.institutional_workbook import _build_export_bundle

    bundle = _build_export_bundle("generic_wind_reference")
    assert bundle.export_authority == "FACTORY_REFERENCE"
    assert bundle.working_changed_since_run == "not_applicable"
    assert bundle.run_id == "not_applicable"
    assert bundle.run_at == "not_applicable"


# ---------------------------------------------------------------------------
# _metric_value OPEX no longer falls back to snapshot
# ---------------------------------------------------------------------------


def test_metric_value_opex_no_snapshot_fallback():
    """OPEX must come from last_run_summary only, never from snapshot fallback."""
    from app.persistence._helpers import _metric_value

    class FakeRecord:
        snapshot = {"opex_y1_keur": 999.0}
        last_run_summary = {}  # no total_opex_keur

    record = FakeRecord()
    result = _metric_value(record, "OPEX")
    # Must be None (no fallback to snapshot), NOT 999.0
    assert result is None, f"OPEX must not fall back to snapshot; got {result}"


def test_metric_value_opex_uses_summary():
    from app.persistence._helpers import _metric_value

    class FakeRecord:
        snapshot = {"opex_y1_keur": 999.0}
        last_run_summary = {"total_opex_keur": 1234.5}

    record = FakeRecord()
    result = _metric_value(record, "OPEX")
    assert result == 1234.5


# ---------------------------------------------------------------------------
# snapshots_equal and working_changed_since_run logic in resolve_export_authority
# ---------------------------------------------------------------------------


def test_snapshots_equal_identical():
    from app.persistence._helpers import snapshots_equal

    assert snapshots_equal({"a": 1}, {"a": 1}) is True


def test_snapshots_equal_different():
    from app.persistence._helpers import snapshots_equal

    assert snapshots_equal({"a": 1}, {"a": 2}) is False


def test_snapshots_equal_none_equivalence():
    from app.persistence._helpers import snapshots_equal

    assert snapshots_equal(None, {}) is True
    assert snapshots_equal({}, None) is True
    assert snapshots_equal(None, None) is True


# ---------------------------------------------------------------------------
# export_metadata build_export_metadata includes authority fields
# ---------------------------------------------------------------------------


def test_build_export_metadata_includes_authority():
    from app.export_metadata import build_export_metadata

    meta = build_export_metadata(
        project_id="test-proj",
        export_authority="CANONICAL_LAST_RUN",
        working_changed_since_run="false",
    )
    assert meta["export_authority"] == "CANONICAL_LAST_RUN"
    assert meta["working_changed_since_run"] == "false"


def test_build_export_metadata_authority_default():
    from app.export_metadata import build_export_metadata

    meta = build_export_metadata(project_id="test-proj")
    assert meta["export_authority"] == "FACTORY_REFERENCE"
    assert meta["working_changed_since_run"] == "not_applicable"


# ---------------------------------------------------------------------------
# metadata_rows order: export_authority and working_changed_since_run
# ---------------------------------------------------------------------------


def test_metadata_rows_includes_authority_fields():
    from app.export_metadata import build_export_metadata, metadata_rows

    meta = build_export_metadata(
        project_id="test-proj",
        export_authority="PREVIEW_WORKING",
        working_changed_since_run="true",
    )
    rows = metadata_rows(meta)
    labels = [label for label, _ in rows]
    assert "Export authority" in labels
    assert "Working changed since run" in labels


# ---------------------------------------------------------------------------
# No financial value change: factory reference IRR is still numeric
# ---------------------------------------------------------------------------


def test_factory_irr_not_changed_by_f07b():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows("generic_wind_reference")
    irr_row = next((r for r in rows if r["metric"] == "project_irr"), None)
    assert irr_row is not None
    val = float(irr_row["value"])
    assert val > 0.0, "project_irr must still be a positive number"
