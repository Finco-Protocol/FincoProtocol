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
    Absent keys and explicit None values return None (F07/C: unavailable
    persisted evidence ≠ financial zero).  Genuine persisted 0.0 is returned
    as 0.0.  Callers must guard against None before numeric formatting.
    .periods is served from debt_schedule.periods (senior-debt periods;
    absent per-period fields also return None per _PeriodAdapter).
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
        # F07/C: distinguish absent key / explicit null (→ None) from
        # genuine persisted 0.0 (→ 0.0).  Use a sentinel to tell the
        # two None-like states apart without a second dict lookup.
        _MISSING = object()
        val = self._rs.get(name, _MISSING)
        if val is _MISSING or val is None:
            return None  # unavailable persisted evidence ≠ financial zero
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
    ws: "Any | None" = None,
    contingency_authority: "dict | None" = None,
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
    # The factory key selects a serializer, not the identity of an owned Working Copy.
    export_code = getattr(project_record, "project_code", None) or project_key_norm
    export_name = getattr(project_record, "project_name", None) or project_inputs.info.name
    for row in runtime_rows:
        row["project"] = export_name
        row["active_project"] = export_code
        if row["metric"] == "active_project":
            row["value"] = export_name

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

    # Correction B — Section A: wire real persisted lineage fields.
    _project_id = str(getattr(project_record, "project_id", None) or "not_applicable")
    _input_composite_hash = str(
        getattr(ws, "last_runtime_composite_hash", None) or "not_applicable"
    ) if ws is not None else "not_applicable"
    # Engine version: read from persisted run-bound identity (captured at run commit time).
    # Do NOT read current ENGINE_VERSION at export time — that misrepresents historical run lineage.
    # If the persisted identity lacks engine_version (legacy run), report NOT_AVAILABLE.
    _engine_version_str = "NOT_AVAILABLE"
    if ws is not None:
        _ri = getattr(ws, "last_runtime_identity", None)
        if isinstance(_ri, dict):
            _ev = _ri.get("engine_version")
            if _ev and str(_ev).strip():
                _engine_version_str = str(_ev)
    # Senior debt authority from persisted runtime_summary — numeric float stored by run path.
    _senior_debt_auth: float | None = None
    _sd_raw = result_adapter.senior_debt_keur
    if _sd_raw is not None:
        try:
            _v = float(str(_sd_raw).replace(",", "").strip())
            if _v > 0.0:
                _senior_debt_auth = _v
        except (TypeError, ValueError):
            _senior_debt_auth = None

    return WorkbookExportBundle(
        project_key=export_code,
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
        authority_metadata={
            "project_owner_id": getattr(project_record, "user_id", None) or "NOT_AVAILABLE",
            "run_project_name": (current_snapshot or {}).get("project_name") or "NOT_AVAILABLE",
            "serialization_template": project_key_norm,
            **({"revenue_multistream_audit": result_adapter.revenue_multistream_audit}
               if result_adapter.revenue_multistream_audit else {}),
        },
        contingency_authority=dict(contingency_authority) if contingency_authority else None,
        export_authority=export_authority,
        working_changed_since_run=runtime_rows[0]["working_changed_since_run"],
        run_id=runtime_rows[0]["run_id"],
        run_at=runtime_rows[0]["run_at"],
        inputs_summary=build_inputs_summary_table(project_inputs),
        capex_summary=build_capex_summary_table(project_inputs),
        capex_items=build_capex_items_table(project_inputs),
        revenue_table=build_revenue_table(result_adapter),
        debt_table=build_debt_table(result_adapter),
        project_id=_project_id,
        input_composite_hash=_input_composite_hash,
        engine_version=_engine_version_str,
        senior_debt_keur_authority=_senior_debt_auth,
        sources_uses_authority=(
            {
                "total_uses_keur": float(result_adapter.total_project_uses_keur),
                "derived_shl_cash_keur": float(result_adapter.derived_shl_cash_keur),
                "sponsor_equity_keur": float(result_adapter.sponsor_equity_sources_keur),
            }
            if (result_adapter.total_project_uses_keur is not None
                and result_adapter.derived_shl_cash_keur is not None
                and result_adapter.sponsor_equity_sources_keur is not None)
            else None
        ),
    )


# ─── Freshness (existing authority; fail-closed) ─────────────────────────────


def _resolve_freshness(ws: Any, user_id: str, project_id: str) -> Any:
    """CURRENT/STALE of the Last Run via the existing freshness authority.

    If the current Working Copy identity cannot be resolved, ``None`` is passed and the
    authority fails closed to STALE -- an export never claims CURRENT it cannot prove.
    """
    from app.workbook.runtime_authority import resolve_runtime_freshness

    current_hash = None
    try:
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_consistent_for_get

        current_hash = assemble_consistent_for_get(user_id, project_id, WORKBOOK.version).composite_hash
    except Exception:  # noqa: BLE001 - unresolved identity must degrade to STALE, not crash the export
        current_hash = None
    return resolve_runtime_freshness(ws, current_composite_hash=current_hash)


def _history_id_for_snapshot(user_id: str, project_id: str, snapshot_id: "str | None") -> "str | None":
    """History row id of the Run that equals the Last Run (its immutable UUID), if one exists.

    Best effort: legacy workspaces have no history row; a read problem never blocks the export.
    """
    if not snapshot_id:
        return None
    try:
        from app.persistence.run_history_repository import get_run_history

        for entry in get_run_history(user_id, project_id, limit=25):
            if entry.runtime_snapshot_id == snapshot_id:
                return entry.history_id
    except Exception:  # noqa: BLE001 - identity enrichment only
        return None
    return None


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
            ws=ws,  # Correction B: pass workspace for composite hash
            contingency_authority=authority.contingency_authority,
        )

        # RC-7: freeze the SAME ws read as an immutable evidence package; the V2 reporting
        # sheets read only it, so a Working Copy edit can never reach them.
        from dataclasses import replace

        from app.export.institutional_workbook import export_institutional_workbook_from_bundle
        from app.export.run_evidence import evidence_from_workspace

        freshness = _resolve_freshness(ws, user_id, project_record.project_id)
        evidence = evidence_from_workspace(
            ws, project_record, user_id, is_stale=freshness.is_stale, freshness_source=freshness.source,
            history_id=_history_id_for_snapshot(user_id, project_record.project_id, ws.last_runtime_snapshot_id))
        bundle = replace(bundle, run_state=evidence.state)
        workbook_bytes = export_institutional_workbook_from_bundle(bundle, run_evidence=evidence)
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
        "export_project_id": bundle.project_id,
        "export_project_code": bundle.active_project,
        "export_project_name": bundle.project_name,
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
        "export_run_state": evidence.state,
        "export_evidence_digest": evidence.evidence_digest,
    }

    from app.export.filename import model_results_filename
    filename = model_results_filename(bundle.project_name, authority.active_scenario_name, rr.snapshot_id)
    return ExportResponse(
        bytes_data=workbook_bytes,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status_code=200,
        metadata=metadata,
    )



def build_historical_run_workbook_export(
    *,
    project_record: Any,
    user_id: "str | None",
    history_id: "str | None",
) -> Any:  # ExportResponse
    """Zero-engine export of ONE immutable Run History row (E3).

    The workbook is built only from that row's persisted evidence and is byte-reproducible.
    Run History does not persist the input snapshot, so no input-assumption sheet is produced
    and the current Working Copy is never substituted.  Fails closed (400/404 semantics via
    ``ExportResponse``) for a missing/foreign project, unknown or foreign history id, or a
    malformed stored row.  ``user_id`` must be the workspace owner resolved by the caller.
    """
    from app.services.export_service import ExportResponse

    def _fail(status: int, message: str) -> Any:
        return ExportResponse(
            status_code=status,
            error_content=(
                f"<html><body><h2>Run export failed</h2><p>{message}</p>"
                "<a href='/library'>Back to Library</a></body></html>"
            ),
        )

    if project_record is None or user_id is None or not history_id:
        return _fail(400, "Project and Run history ID required.")
    if (getattr(project_record, "project_origin", "") or "") != "user_created":
        return _fail(400, "Run history export requires a user project with committed Runs.")
    try:
        from app.persistence.run_history_repository import RunHistoryError, get_run_history_entry
        from app.persistence.workspace_repository import get_workspace_state

        try:
            entry = get_run_history_entry(user_id, project_record.project_id, history_id)
        except RunHistoryError:
            return _fail(422, "The stored Run record is malformed and cannot be exported.")
        if entry is None or entry.project_id != project_record.project_id or entry.user_id != user_id:
            return _fail(404, "Run history entry not found.")

        ws = get_workspace_state(user_id, project_record.project_id)
        freshness = _resolve_freshness(ws, user_id, project_record.project_id) if ws is not None else None
        from app.export.institutional_reporting_v2 import build_run_evidence_workbook
        from app.export.run_evidence import evidence_from_history_entry

        evidence = evidence_from_history_entry(
            entry, project_record,
            last_run_snapshot_id=getattr(ws, "last_runtime_snapshot_id", None) if ws is not None else None,
            last_run_is_stale=bool(freshness.is_stale) if freshness is not None else True,
            freshness_source=freshness.source if freshness is not None else "workspace_unavailable",
        )
        workbook_bytes = build_run_evidence_workbook(evidence)
    except ValueError:
        return _fail(400, "Run history export failed.")

    from app.export.filename import model_results_filename

    return ExportResponse(
        bytes_data=workbook_bytes,
        filename=model_results_filename(evidence.project_name, evidence.scenario_name, evidence.snapshot_id),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status_code=200,
        metadata={
            "export_project_id": evidence.project_id,
            "export_project_code": evidence.project_code,
            "export_project_name": evidence.project_name,
            "export_authority": "RUN_HISTORY_ENTRY",
            "export_run_id": evidence.snapshot_id,
            "export_run_at": evidence.ran_at,
            "export_history_id": evidence.history_id or "",
            "export_snapshot_id": evidence.snapshot_id,
            "export_run_state": evidence.state,
            "export_evidence_digest": evidence.evidence_digest,
            "export_active_scenario_id": evidence.scenario_id or "",
            "export_active_scenario_name": evidence.scenario_name or "",
        },
    )
