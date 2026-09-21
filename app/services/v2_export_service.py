"""V2 canonical last-run export service — zero engine execution.

Builds the institutional workbook from persisted RuntimeResult data only.
Never calls execute_production_waterfall or run_clean_production.

Architecture (F06 single-read):
  1. get_workspace_state           → ONE workspace read; ws used for both:
     a. resolve_canonical_last_run_from_workspace(ws) → project_inputs + authority
     b. RuntimeResult.from_workspace_state(ws)        → KPIs, debt schedule, FS
  2. _RuntimeResultAdapter         → KPI attribute access from runtime_summary dict
  3. _StatementsAdapter            → FS period access from financial_statements dict
  4. export_institutional_workbook_from_bundle → pure serialization, ZERO engine

The single workspace read eliminates the torn-workbook race (F06): authority
and RuntimeResult both derive from the same immutable ws snapshot, so a
concurrent save cannot mix Last Run A inputs with Last Run B outputs.
"""
from __future__ import annotations

import datetime
from typing import Any


# ─── Persisted-data adapters ──────────────────────────────────────────────────


class _PeriodAdapter:
    """Attribute-access wrapper for a period dict from a persisted schedule.

    Compatible with both plain dict and MappingProxyType (RuntimeResult._freeze).
    Returns None for fields absent from or explicitly null in the persisted payload
    (F07: absent field ≠ financial zero; callers must guard against None before
    arithmetic).  Converts ISO date strings to datetime.date for .isoformat() calls.
    """

    __slots__ = ("_d",)

    def __init__(self, d: Any) -> None:
        object.__setattr__(self, "_d", d)

    def __getattr__(self, name: str) -> Any:
        try:
            val = self._d[name]
        except (KeyError, TypeError):
            return None  # F07: absent field → None, not 0.0
        if val is None:
            return None  # F07: explicit null → None, not 0.0
        if name in ("date", "end_date") and isinstance(val, str):
            try:
                return datetime.date.fromisoformat(val[:10])
            except ValueError:
                return val
        return val


class _FSSection:
    """Adapter for one financial-statement section (pnl, tax_bridge, etc.)."""

    __slots__ = ("_d",)

    def __init__(self, d: Any) -> None:
        object.__setattr__(self, "_d", d or {})

    @property
    def periods(self) -> list:
        raw = None
        try:
            raw = self._d.get("periods") if hasattr(self._d, "get") else self._d["periods"]
        except (KeyError, TypeError):
            pass
        return [_PeriodAdapter(p) for p in (raw or [])]


class _StatementsAdapter:
    """Adapter for a persisted financial_statements dict.

    Provides .pnl, .tax_bridge, .pf_cash_waterfall, .balance_sheet, each
    returning a _FSSection with a .periods list of _PeriodAdapter objects.
    None is returned for the adapter itself only when called with None, so
    the bundle's statements field should be set to None when financial_statements
    is absent — the workbook writers will then render their NOT_AVAILABLE rows.
    """

    __slots__ = ("_d",)

    def __init__(self, d: Any) -> None:
        object.__setattr__(self, "_d", d or {})

    def _section(self, key: str) -> "_FSSection":
        try:
            val = self._d.get(key) if hasattr(self._d, "get") else self._d[key]
        except (KeyError, AttributeError, TypeError):
            val = None
        return _FSSection(val)

    @property
    def pnl(self) -> "_FSSection":
        return self._section("pnl")

    @property
    def tax_bridge(self) -> "_FSSection":
        return self._section("tax_bridge")

    @property
    def pf_cash_waterfall(self) -> "_FSSection":
        return self._section("pf_cash_waterfall")

    @property
    def balance_sheet(self) -> "_FSSection":
        return self._section("balance_sheet")


class _RuntimeResultAdapter:
    """Attribute-access wrapper for persisted runtime_summary + debt_schedule.

    Provides the attribute interface expected by WorkbookExportBundle sheet
    writers and build_runtime_summary_rows. Reads ONLY from persisted dicts.
    Never calls execute_production_waterfall or run_clean_production.

    KPI fields (project_irr, equity_irr, …) are served from runtime_summary.
    .periods is served from debt_schedule.periods (senior debt periods; SHL
    and revenue per-period fields will be 0.0 — a known persisted-path
    limitation documented in the export workbook).
    .sculpting_result returns None so _resolve_export_senior_debt_keur falls
    through to context.senior_debt_keur (the explicit input field).
    """

    __slots__ = ("_rs", "_ds_periods")

    def __init__(self, runtime_summary: Any, debt_schedule: Any) -> None:
        rs: dict = {}
        if runtime_summary:
            if hasattr(runtime_summary, "items"):
                rs = {k: v for k, v in runtime_summary.items()}
            else:
                try:
                    rs = dict(runtime_summary)
                except (TypeError, ValueError):
                    pass
        object.__setattr__(self, "_rs", rs)

        ds = debt_schedule or {}
        raw_periods = None
        try:
            raw_periods = ds.get("periods") if hasattr(ds, "get") else ds["periods"]
        except (KeyError, TypeError):
            pass
        object.__setattr__(self, "_ds_periods", list(raw_periods or []))

    @property
    def periods(self) -> list:
        return [_PeriodAdapter(p) for p in self._ds_periods]

    @property
    def sculpting_result(self) -> None:
        return None

    @property
    def shl_data_available(self) -> bool:
        """F07: True only when the persisted debt_schedule includes SHL per-period fields.

        The production _serialize_debt_schedule persists senior fields only (no SHL).
        This guard prevents _write_shl_sheet from crashing on None arithmetic.
        """
        if not self._ds_periods:
            return False
        first = self._ds_periods[0]
        return "shl_balance_keur" in first

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        val = self._rs.get(name)
        if val is None:
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            return val


# ─── Bundle builder (no engine, no DB write) ─────────────────────────────────


def _build_persisted_bundle(
    project_key: str,
    *,
    project_record: Any,
    project_inputs: Any,
    current_snapshot: "dict | None",
    result_adapter: "_RuntimeResultAdapter",
    statements_adapter: "Any | None",
    runtime_origin: "str | None",
    scenario_id: "str | None",
    scenario_name: "str | None",
    export_authority: str,
    working_changed_since_run: "bool | None",
    run_id: "str | None",
    run_at: "str | None",
    snapshot_id: str,
    runtime_timestamp: "str | None" = None,
) -> Any:  # WorkbookExportBundle
    from app.export.institutional_workbook import WorkbookExportBundle
    from app.export.runtime_summary import build_runtime_summary_rows
    from app.input_helpers import (
        build_capex_items_table,
        build_capex_summary_table,
        build_inputs_summary_table,
    )
    from app.output_tables import build_debt_table, build_revenue_table
    from app.ui.project_context import get_project_context

    project_key_norm = (project_key or "generic_wind_reference").strip().lower()

    # Build runtime rows from persisted adapter — no engine call via _precomputed.
    # F08: pass persisted runtime_timestamp so the workbook carries the actual run
    # time, not the export-generation time.
    runtime_rows = build_runtime_summary_rows(
        project_key_norm,
        _precomputed=(project_inputs, result_adapter),
        runtime_origin=runtime_origin,
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        export_authority=export_authority,
        working_changed_since_run=working_changed_since_run,
        run_id=run_id,
        run_at=run_at,
        runtime_timestamp=runtime_timestamp,
    )

    # Project context: prefer record-authoritative for user projects.
    context = get_project_context(project_key_norm)
    if project_record is not None and project_inputs is not None and current_snapshot is not None:
        from app.ui.project_context import build_project_context_for_record
        context = build_project_context_for_record(
            project_code=getattr(project_record, "project_code", "") or project_key_norm,
            project_name=getattr(project_record, "project_name", "") or project_key_norm,
            project_type=getattr(project_record, "project_type", None),
            project_origin=getattr(project_record, "project_origin", "") or "",
            template_source=getattr(project_record, "template_source", None),
            baseline_snapshot=getattr(project_record, "baseline_snapshot", None),
            current_snapshot=current_snapshot,
            effective_project_inputs=project_inputs,
        )

    return WorkbookExportBundle(
        project_key=project_key_norm,
        project_name=runtime_rows[0]["project"],
        generated_at=runtime_rows[0]["export_generated_at"],
        branch=runtime_rows[0]["branch_name"],
        commit_sha=runtime_rows[0]["commit_sha"],
        runtime_timestamp=runtime_rows[0]["runtime_timestamp"],
        active_project=runtime_rows[0]["active_project"],
        scenario_id=runtime_rows[0]["scenario_id"],
        scenario_name=runtime_rows[0]["scenario_name"],
        scenario_revision=runtime_rows[0]["scenario_revision"],
        runtime_snapshot_id=snapshot_id or runtime_rows[0]["runtime_snapshot_id"],
        runtime_origin=runtime_rows[0]["runtime_origin"],
        template_origin=runtime_rows[0]["template_origin"],
        template_revision=runtime_rows[0]["template_revision"],
        export_template_version=runtime_rows[0]["export_template_version"],
        runtime_flag_count=runtime_rows[0]["runtime_flag_count"],
        runtime_flags_json=runtime_rows[0]["runtime_flags_json"],
        governance_posture_summary=runtime_rows[0]["governance_posture_summary"],
        replay_limitations=runtime_rows[0]["replay_limitations"],
        context=context,
        project_inputs=project_inputs,
        runtime_result=result_adapter,
        runtime_rows=runtime_rows,
        statements=statements_adapter,
        authority_metadata={},
        export_authority=export_authority,
        working_changed_since_run=runtime_rows[0]["working_changed_since_run"],
        run_id=runtime_rows[0]["run_id"],
        run_at=runtime_rows[0]["run_at"],
        inputs_summary=build_inputs_summary_table(project_inputs),
        capex_summary=build_capex_summary_table(project_inputs),
        capex_items=build_capex_items_table(project_inputs),
        revenue_table=build_revenue_table(result_adapter),
        debt_table=build_debt_table(result_adapter),
    )


# ─── Public service function ──────────────────────────────────────────────────


def build_canonical_last_run_institutional_workbook_export(
    runtime_project_code: str,
    *,
    safe_project: "str | None" = None,
    project_record: Any = None,
    user_id: "str | None" = None,
) -> Any:  # ExportResponse
    """Zero-engine canonical last-run institutional workbook export.

    Reads persisted RuntimeResult from the workspace; never calls
    execute_production_waterfall or run_clean_production.

    Fails closed (400) when:
      - project_record is None or user_id is None
      - project_origin is not "user_created"
      - no committed run exists (CANONICAL_LAST_RUN_UNAVAILABLE)
      - workspace state is absent

    No factory fallback. No engine execution.
    """
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ExportResponse,
        resolve_canonical_last_run_from_workspace,
    )

    # Fail closed: V2 export requires a committed user run — no factory fallback.
    if project_record is None or user_id is None:
        return ExportResponse(
            status_code=400,
            error_content=(
                "<html><body><h2>Export failed</h2>"
                "<p>Last Run required. Run the model before exporting.</p>"
                "<a href='/library'>Back to Library</a></body></html>"
            ),
        )
    origin = getattr(project_record, "project_origin", "") or ""
    if origin != "user_created":
        return ExportResponse(
            status_code=400,
            error_content=(
                "<html><body><h2>Export failed</h2>"
                "<p>Last Run required. Run the model before exporting.</p>"
                "<a href='/library'>Back to Library</a></body></html>"
            ),
        )

    try:
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.runtime_result import RuntimeResult

        # F06: ONE workspace read.  Both authority and RuntimeResult derive from
        # the same ws object — no concurrent save can combine Last Run A inputs
        # with Last Run B outputs into a falsely canonical workbook.
        ws = get_workspace_state(user_id, project_record.project_id)

        # Raises ValueError("CANONICAL_LAST_RUN_UNAVAILABLE: …") when no run exists.
        authority = resolve_canonical_last_run_from_workspace(project_record, user_id, ws)

        rr = RuntimeResult.from_workspace_state(ws) if ws is not None else None
        if rr is None:
            raise ValueError(
                "CANONICAL_LAST_RUN_UNAVAILABLE: no committed run exists for persisted export."
            )

        # Build adapters from persisted data — ZERO engine execution.
        result_adapter = _RuntimeResultAdapter(rr.runtime_summary, rr.debt_schedule)
        statements_adapter = (
            _StatementsAdapter(rr.financial_statements) if rr.financial_statements else None
        )

        bundle = _build_persisted_bundle(
            runtime_project_code,
            project_record=project_record,
            project_inputs=authority.project_inputs,
            current_snapshot=authority.current_snapshot,
            result_adapter=result_adapter,
            statements_adapter=statements_adapter,
            runtime_origin=authority.runtime_origin,
            scenario_id=authority.active_scenario_id,
            scenario_name=authority.active_scenario_name,
            export_authority=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
            working_changed_since_run=authority.working_changed_since_run,
            run_id=authority.run_id,
            run_at=authority.run_at,
            snapshot_id=rr.snapshot_id,
            runtime_timestamp=getattr(rr, "ran_at", None),  # F08: persisted run time
        )

        from app.export.institutional_workbook import export_institutional_workbook_from_bundle
        workbook_bytes = export_institutional_workbook_from_bundle(bundle)
        first_row = bundle.runtime_rows[0]

    except ValueError:
        # F04: never reflect exception text into HTML — static safe message only.
        return ExportResponse(
            status_code=400,
            error_content=(
                "<html><body><h2>Institutional workbook export failed</h2>"
                "<p>Last Run required. Run the model and try again.</p>"
                "<a href='/library'>Back to Library</a></body></html>"
            ),
        )

    metadata = {
        "export_generated_at": first_row["export_generated_at"],
        "runtime_generated_at": first_row["runtime_generated_at"],
        "runtime_origin": first_row["runtime_origin"],
        "generated_at": first_row["generated_at"],
        "source_branch": first_row["source_branch"],
        "export_authority": EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        "export_active_scenario_id": authority.active_scenario_id or "",
        "export_active_scenario_name": authority.active_scenario_name or "",
        "export_last_runtime_scenario_id": authority.last_runtime_scenario_id or "",
        "export_run_id": authority.run_id or "",
        "export_run_at": authority.run_at or "",
        "export_snapshot_id": getattr(rr, "snapshot_id", None) or "",  # F05: for audit
        "export_working_changed_since_run": str(authority.working_changed_since_run).lower(),
    }

    filename = (
        f"phase10_{safe_project or runtime_project_code}"
        "_institutional_workbook_skeleton.xlsx"
    )
    return ExportResponse(
        bytes_data=workbook_bytes,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status_code=200,
        metadata=metadata,
    )
