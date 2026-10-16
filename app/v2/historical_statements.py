"""Read-only Statements V2 for ONE immutable Run History entry.

Every statement value, schedule and engine identity comes from the history entry the Run committed.  The editable Working
Copy is consulted for exactly one thing: its current composite input identity, so the entry's input freshness can be
labelled.  Nothing here runs the engine, recomputes a statement line, or substitutes current inputs for historical ones.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from app.v2.output_workspace_projection import _integrity
from app.v2.statement_drilldown import build_statement_drilldown, input_context
from app.workbook.runtime_authority import RunContext, resolve_run_status_dimensions
from app.workbook.runtime_projection import thaw_runtime_payload


def _run_result_view(entry: Any) -> SimpleNamespace:
    """Duck-typed RuntimeResult over the history entry (the statement adapters read only these attributes)."""
    return SimpleNamespace(
        debt_schedule=entry.debt_schedule, tax_schedule=entry.tax_schedule, financial_statements=entry.financial_statements,
        runtime_summary=entry.runtime_summary, sponsor_schedule=entry.sponsor_schedule,
        distribution_schedule=entry.distribution_schedule, snapshot_id=entry.runtime_snapshot_id, ran_at=entry.ran_at,
        origin=entry.runtime_origin)


def _entry_integrity(entry: Any) -> dict:
    evidence = getattr(entry, "integrity_evidence", None)
    if not evidence:
        return _integrity(None)
    try:
        from app.run_integrity import run_integrity_checks
        return _integrity(run_integrity_checks(evidence).to_dict())
    except Exception:  # noqa: BLE001 - presentation fails closed
        return _integrity(None)


def build_historical_statements(entry: Any, *, current_composite_hash: Optional[str] = None,
                                scenario_label: Optional[str] = None) -> dict[str, Any]:
    from app.v2.statement_presentation import statements_from_run
    view = _run_result_view(entry)
    statements = statements_from_run(view, False)
    summary = thaw_runtime_payload(entry.runtime_summary or {}) or {}
    integrity = _entry_integrity(entry)
    if current_composite_hash and entry.composite_hash:
        freshness = "CURRENT" if current_composite_hash == entry.composite_hash else "STALE"
        basis = "current Working Copy composite input identity (hash equality only)"
    else:
        freshness, basis = None, "not evaluated: current Working Copy identity unavailable"
    dimensions = resolve_run_status_dimensions(
        run_context=RunContext.HISTORICAL_RUN, input_freshness=freshness, integrity=integrity["status"],
        identity=entry.last_runtime_identity, replay_metadata=entry.replay_metadata,
        history_engine_version=entry.engine_version, input_freshness_basis=basis)
    context = input_context(run_context="HISTORICAL_RUN", freshness_state=freshness)
    audit = summary.get("revenue_multistream_audit") if isinstance(summary, dict) else None
    return {
        "history_id": entry.history_id,
        "identity": {"snapshot_id": entry.runtime_snapshot_id or "", "ran_at": (entry.ran_at or "")[:19].replace("T", " "),
                     "composite_hash": entry.composite_hash or "", "scenario": scenario_label or "UNAVAILABLE",
                     "scenario_proven": scenario_label is not None, "engine_version": str(entry.engine_version or "")},
        "status_dimensions": dimensions.to_dict(), "integrity": integrity,
        "drilldown": {"context": context, "statements": build_statement_drilldown(
            statements, multistream_audit=audit, context=context)},
    }


__all__ = ["build_historical_statements"]
