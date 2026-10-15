"""WF-A Addendum A: Add Debt / Add Equity / Add PPA, measured on real committed Runs.

Every case drives an existing released route (F3 facility save, F4 investor agreement save, Revenue V2 contract book
save), commits a Run through the product, and reconciles what the Run recorded against an independent recomputation
(``tools.numerical_validation.impact``).  Nothing here changes the application, the engine or any policy.

Rows follow the Addendum §7 delta-matrix fields.  A row is evidence, not a PASS by construction: ``verdict`` is the
independent reconciliation result; a successful Run alone is never a validation PASS.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

USER = "decision-user"
ROWS: list[dict[str, Any]] = []


def emit(row: dict[str, Any]) -> dict[str, Any]:
    ROWS.append(row)
    target = os.environ.get("WFA_EMIT_DIR")
    if target:
        path = Path(target) / f"{row['case']}.json"
        path.write_text(json.dumps(row, sort_keys=True, default=str))
    return row


def working_inputs(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    return ProjectInputSet.from_snapshot(get_workspace_state(USER, record.project_id).draft_snapshot).to_projectinputs()


def commit(env, record):
    from tests.test_model_financing_f2 import run
    ws, _ = run(env, record)
    from app.persistence.run_history_repository import get_latest_history_entry
    return get_latest_history_entry(USER, record.project_id)


def scalars(entry) -> dict[str, Decimal | None]:
    from tools.numerical_validation.source import bundle_from_history_entry
    b = bundle_from_history_entry(entry)
    sc = lambda k: None if k not in b["scalars"] or b["scalars"][k].get("value") is None else Decimal(str(b["scalars"][k]["value"]))  # noqa: E731
    debt, uses = sc("su.senior_debt_keur"), sc("su.total_uses_keur")
    return {"senior_debt": debt, "total_uses": uses, "equity_funding": None if None in (debt, uses) else uses - debt,
            "min_dscr": sc("summary.min_dscr"), "avg_dscr": sc("summary.avg_dscr"), "total_service": sc("summary.total_senior_ds_keur"),
            "total_ebitda": sc("summary.total_ebitda_keur"), "project_irr": sc("summary.project_irr"),
            "equity_irr": sc("summary.equity_irr"), "idc": sc("su.capitalized_idc_keur")}


def authority(entry) -> Any:
    return ((getattr(entry, "runtime_summary", None) or {}).get("financing_evidence") or {}).get("facility_authority")


def delta(a: dict, b: dict) -> dict[str, str | None]:
    return {k: None if a.get(k) is None or b.get(k) is None else format(b[k] - a[k], "f") for k in a}


def reconcile(entry, **declared):
    from tools.numerical_validation import impact
    from tools.numerical_validation.source import bundle_from_history_entry
    bundle = bundle_from_history_entry(entry)
    ev = impact.impact_evidence_from_entry(entry, bundle, **declared)
    return impact.reconcile_impact(bundle, ev)


def verdict(result) -> dict[str, Any]:
    counts = result["counts"]
    ids = sorted({r["identity"] for r in result["by_identity"]})
    return {"counts": counts, "identities": ids, "fails": [o for o in result["outcomes"] if o["status"] == "FAIL"][:3],
            "by_identity": {r["identity"]: r["verdict"] for r in result["by_identity"]}}


def row(case: str, *, family: str, entry, baseline, modification: str, activated: str, result=None, independent: str = "",
        explanation: str = "", extra: dict | None = None, baseline_entry=None) -> dict[str, Any]:
    now = scalars(entry)
    base = baseline if baseline is not None else {}
    v = verdict(result) if result is not None else None
    status = ("NOT_RECONCILED" if v is None else "FAIL" if v["counts"].get("FAIL") else
              "VERIFIED" if v["counts"].get("PASS") else "NOT_COMPARABLE")
    return emit({"case": case, "family": family, "baseline_run": getattr(baseline_entry, "run_key", None) or getattr(baseline_entry, "snapshot_id", None),
                 "modified_run": getattr(entry, "run_key", None) or getattr(entry, "snapshot_id", None),
                 "input_modification": modification, "actual_activation": activated,
                 "baseline_result": {k: None if x is None else format(x, "f") for k, x in base.items()},
                 "modified_result": {k: None if x is None else format(x, "f") for k, x in now.items()},
                 "difference": delta(base, now) if base else {}, "independent_expectation": independent,
                 "reconciliation": v, "verdict": status, "explanation": explanation, **(extra or {})})
