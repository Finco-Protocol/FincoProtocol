"""F03: validated read-only financing period bridge for ONE authorized committed Run.

Selection, access control and freshness are resolved by the caller. Period axes
must not be conflated; absent construction commitment/outstanding is not zero.
No financial solver, workbook update, or Run writer is called here.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from app.v2.debt_metrics_projection import build_debt_metrics
from app.v2.financing_sources_uses_projection import (
    FinancingEvidenceInvalid,
    build_sources_uses_projection,
)


class F02PeriodEvidenceUnavailable(ValueError):
    """A committed entry cannot attest the requested financing period bridge."""


def _identity(entry: Any) -> tuple[str, str, str]:
    history_id = getattr(entry, "history_id", None)
    snapshot_id = getattr(entry, "runtime_snapshot_id", None)
    composite_hash = getattr(entry, "composite_hash", None)
    if not all(isinstance(v, str) and v for v in (history_id, snapshot_id, composite_hash)):
        raise F02PeriodEvidenceUnavailable("COMMITTED_RUN_IDENTITY_UNAVAILABLE")
    return history_id, snapshot_id, composite_hash


def build_f02_period_evidence(entry: Any, *, state: str) -> dict[str, Any]:
    """Read one persisted entry, with independent S&U run-binding and sealed debt checks."""
    if state not in {"CURRENT", "STALE", "HISTORICAL"}:
        raise F02PeriodEvidenceUnavailable("RUN_STATE_UNAVAILABLE")
    history_id, snapshot_id, composite_hash = _identity(entry)
    scenario_id = getattr(entry, "last_runtime_scenario_id", None)
    if scenario_id is not None and not isinstance(scenario_id, str):
        raise F02PeriodEvidenceUnavailable("RUN_SCENARIO_INVALID")
    try:
        su = build_sources_uses_projection(
            runtime_result=entry,
            integrity_evidence=getattr(entry, "integrity_evidence", None),
            freshness="STALE" if state == "HISTORICAL" else state,
            run_kind="HISTORICAL_RUN" if state == "HISTORICAL" else "LAST_RUN",
            expected_snapshot_id=snapshot_id,
            expected_composite_hash=composite_hash,
            expected_scenario_id=scenario_id,
        )
    except FinancingEvidenceInvalid as exc:
        raise F02PeriodEvidenceUnavailable(str(exc)) from exc
    if not su["has_financing_evidence"]:
        raise F02PeriodEvidenceUnavailable("TYPED_FINANCING_EVIDENCE_UNAVAILABLE")

    summary = getattr(entry, "runtime_summary")
    raw_fc = summary["financing_evidence"]["construction_funding"].get("non_construction_fc_use")
    fc_senior_draw = raw_fc.get("senior_draw_keur") if isinstance(raw_fc, Mapping) else None
    if fc_senior_draw is not None and (
        isinstance(fc_senior_draw, bool) or not isinstance(fc_senior_draw, (int, float))
        or not math.isfinite(fc_senior_draw)
    ):
        raise F02PeriodEvidenceUnavailable("FC_SENIOR_DRAW_MALFORMED")
    dm = build_debt_metrics(entry, state=state)
    construction = tuple({
        "period_index": row["period"],
        "date": row["date"],
        "axis": "RUN_CONSTRUCTION_PERIOD",
        "fields": row["fields"],
    } for row in su["construction_rows"])
    repayment = tuple({
        "period_index": row["period_index"],
        "date": row["date"],
        "label": row["label"],
        "axis": "RUN_DEBT_SERVICE_PERIOD",
        "senior_opening_keur": row["senior_opening_keur"],
        "principal_keur": row["principal_keur"],
        "interest_keur": row["interest_keur"],
        "debt_service_keur": row["debt_service_keur"],
        "senior_closing_keur": row["senior_closing_keur"],
        "dscr": row["dscr"],
        "shortfall_keur": row["shortfall_keur"],
        "cash_after_senior_keur": row["cash_after_senior_keur"],
    } for row in dm["periods"]) if dm["available"] else ()
    return {
        "schema": "F02_PERIOD_EVIDENCE_PHASE_A_V1",
        "identity": {"history_id": history_id, "snapshot_id": snapshot_id,
                     "composite_hash": composite_hash, "scenario_id": scenario_id,
                     "state": state},
        "sources_uses": su,
        "construction": {"rows": construction, "granularity": "RUN_PERIOD",
                         "policy": su["construction_policy"],
                         "non_construction_fc_use": su["non_construction"],
                         "fc_senior_draw": {"value": fc_senior_draw, "unit": "kEUR",
                                            "source": "RuntimeResult.runtime_summary.financing_evidence."
                                                      "construction_funding.non_construction_fc_use.senior_draw_keur"}},
        "repayment": {"available": dm["available"], "reason": dm["reason"],
                      "rows": repayment, "axis": dm["axis"]},
        "unavailable": {
            "independent_lender_commitments": "UNAVAILABLE",
            "construction_opening_outstanding": "UNAVAILABLE",
            "construction_closing_outstanding": "UNAVAILABLE",
            "reserve_draw_target_topup_ledger": "UNAVAILABLE",
            "benchmark_reset_schedule": "ENGINE_ONLY",
        },
        "source_authority": "ONE_COMMITTED_RUN_HISTORY_ENTRY",
        "internal_run_binding": "PROVEN_BACKEND_ENTRY",
        "studio_credit_cross_view": "MITIGATED_NOT_PROVEN",
    }
