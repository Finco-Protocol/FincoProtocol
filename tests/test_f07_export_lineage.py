"""F07 — export completeness / lineage tests.

Audit finding: exported artifacts (runtime summary CSV and institutional
workbook) carry ``scenario_id = unavailable`` and no scenario identity even
when the exporter knows the exact active scenario of the exported working
copy. The DB-side export lineage record had the identity; the artifact a
counterparty receives did not.

The fix threads the resolved authority's active scenario identity into the
artifact rows (the CSV/workbook schema already had scenario_id/scenario_name
columns — they were simply never populated). Factory paths keep the
NOT_APPLICABLE-style markers exactly as before. No financial calculation,
schema, or engine change.

All scenario ids/names in this file are synthetic fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.export.runtime_summary import build_runtime_summary_rows
from app.persistence.provenance import NOT_APPLICABLE, UNAVAILABLE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fake_result() -> SimpleNamespace:
    """Presentation-only ModelResult stand-in for the row assembler."""
    return SimpleNamespace(
        project_irr=0.081,
        equity_irr=0.105,
        total_revenue_keur=1000.0,
        total_ebitda_keur=600.0,
        total_opex_keur=250.0,
        actual_avg_dscr=1.35,
        actual_min_dscr=1.12,
        periods=[],
    )


def _rows(**kwargs) -> list[dict[str, str]]:
    """One assembler pass over the real wind-reference inputs with a fake
    result — zero financial calculation, presentation assembly only."""
    from app.project_factories import create_generic_wind_reference
    kwargs.setdefault("_precomputed", (create_generic_wind_reference(), _fake_result()))
    kwargs.setdefault("runtime_origin", "saved_state")
    return build_runtime_summary_rows("generic_wind_reference", **kwargs)


# ---------------------------------------------------------------------------
# Factory/default paths are byte-compatible with pre-fix behavior
# ---------------------------------------------------------------------------

def test_rows_without_scenario_keep_unavailable_markers():
    rows = _rows()
    assert rows, "assembler must produce rows"
    for row in rows:
        assert row["scenario_id"] == NOT_APPLICABLE
        assert row["scenario_name"] == NOT_APPLICABLE
        assert row["scenario_revision"] == NOT_APPLICABLE


def test_runtime_origin_still_recorded():
    rows = _rows()
    assert rows[0]["runtime_origin"] == "saved_state"


# ---------------------------------------------------------------------------
# The fix: scenario identity is bound into the artifact
# ---------------------------------------------------------------------------

def test_rows_carry_scenario_identity_when_authority_knows_it():
    rows = _rows(scenario_id="sc-f07-0001", scenario_name="F07 Test Downside")
    for row in rows:
        assert row["scenario_id"] == "sc-f07-0001"
        assert row["scenario_name"] == "F07 Test Downside"
        # existing provenance convention: revision defaults to scenario id
        assert row["scenario_revision"] == "sc-f07-0001"


def test_csv_serialization_includes_scenario_identity():
    from app.export.runtime_summary import build_runtime_summary_csv
    rows = _rows(scenario_id="sc-f07-0001", scenario_name="F07 Test Downside")
    csv_text = build_runtime_summary_csv("generic_wind_reference", rows=rows)
    header = csv_text.splitlines()[0]
    assert "scenario_id" in header and "scenario_name" in header
    assert "sc-f07-0001" in csv_text
    assert "F07 Test Downside" in csv_text


# ---------------------------------------------------------------------------
# Export service: the resolved authority's scenario reaches the artifact
# ---------------------------------------------------------------------------

def test_export_service_binds_authority_scenario_into_csv(monkeypatch):
    from app.project_factories import create_generic_wind_reference
    from app.services import export_service

    authority = export_service.ResolvedExportAuthority(
        project_inputs=create_generic_wind_reference(),
        current_snapshot={},
        runtime_origin="saved_state",
        active_scenario_id="sc-f07-0002",
        active_scenario_name="F07 Test Sensitivity",
        last_runtime_scenario_id=None,
        any_run_committed=False,
    )
    monkeypatch.setattr(export_service, "resolve_export_authority",
                        lambda record, uid: authority)

    export = export_service.build_runtime_summary_csv_export(
        "generic_wind_reference",
        safe_project="generic_wind_reference",
        project_record=None,
        user_id="f07-user",
    )
    assert export.status_code == 200, export.error_content
    assert export.metadata["export_active_scenario_id"] == "sc-f07-0002"
    assert "sc-f07-0002" in export.bytes_data.decode("utf-8"), (
        "the artifact itself must carry the active scenario identity"
    )


def test_export_service_factory_path_stays_marker_only(monkeypatch):
    from app.services import export_service

    authority = export_service.ResolvedExportAuthority(
        project_inputs=None, current_snapshot=None, runtime_origin=None,
    )
    monkeypatch.setattr(export_service, "resolve_export_authority",
                        lambda record, uid: authority)

    export = export_service.build_runtime_summary_csv_export(
        "generic_wind_reference",
        safe_project="generic_wind_reference",
        project_record=None,
        user_id=None,
    )
    assert export.status_code == 200, export.error_content
    # factory path: no scenario authority exists; markers unchanged
    assert export.metadata["export_active_scenario_id"] == ""
    assert "not_applicable" in export.bytes_data.decode("utf-8") or \
           "unavailable" in export.bytes_data.decode("utf-8")


def test_workbook_bundle_rows_carry_scenario_identity():
    """The institutional workbook metadata sheet reads bundle.scenario_id from
    runtime_rows[0] — one engine execution of the reference factory, asserting
    the binding flows through the bundle builder."""
    from app.export.institutional_workbook import _build_export_bundle
    from app.project_factories import create_generic_wind_reference

    bundle = _build_export_bundle(
        "generic_wind_reference",
        project_inputs=create_generic_wind_reference(),
        runtime_origin="saved_state",
        scenario_id="sc-f07-0003",
        scenario_name="F07 Test Bundle",
    )
    assert bundle.runtime_rows[0]["scenario_id"] == "sc-f07-0003"
    assert bundle.scenario_id == "sc-f07-0003"
    assert bundle.scenario_name == "F07 Test Bundle"
