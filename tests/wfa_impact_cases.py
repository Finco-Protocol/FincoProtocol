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


FT_ALL = ("FT-DRAWS", "FT-IDC", "FT-COMMITMENT-FEE", "FT-UPFRONT", "FT-INTEREST", "FT-REPAYMENT", "FT-MATURITY")
IV_ALL = ("IV-OWNERSHIP", "IV-AGGREGATE", "IV-PAIDIN", "IV-MULTIPLE", "IV-XIRR")
RC_ALL = ("RC-PRICE", "RC-ALLOCATION", "RC-RESIDUAL", "RC-WINDOW")


def identity(entry) -> dict[str, Any] | None:
    """The immutable Run identity exactly as the independent source binds it (never inferred from the entry object)."""
    if entry is None:
        return None
    from tools.numerical_validation.source import bundle_from_history_entry
    ident = bundle_from_history_entry(entry)["identity"]
    return {k: ident[k] for k in ("run_key", "snapshot_id", "composite_hash") if k in ident} | {"history_id": getattr(entry, "history_id", None)}


def classify(result, required: tuple[str, ...] = (), *, baseline: bool = False) -> str:
    """Case verdict from per-identity outcomes.

    A feature case is VERIFIED only when EVERY identity in ``required`` (the feature-specific FT-/IV-/RC- family that applies
    to the case) has at least one PASS, no FAIL, no UNAVAILABLE and no NOT_COMPARABLE outcome.  PASS results of unrelated
    identities (for example the F3.9 statement identities) never contribute.  A baseline is only BASELINE_VERIFIED: it makes
    no claim that an inapplicable feature was independently validated.
    """
    if result is None:
        return "NOT_RECONCILED"
    counts = result["counts"]
    if counts.get("FAIL"):
        return "FAIL"
    if baseline:
        return "BASELINE_VERIFIED" if counts.get("PASS") else "NOT_RECONCILED"
    if not required:
        raise ValueError("a feature case must declare the identities it requires")
    per = {r["identity"]: r["counts"] for r in result["by_identity"]}
    if any(i not in per for i in required):
        return "INCOMPLETE_FEATURE_IDENTITIES_NOT_EVALUATED"
    counts_of = [per[i] for i in required]
    if any(c.get("UNAVAILABLE") or not (c.get("PASS") or c.get("NOT_COMPARABLE")) for c in counts_of):
        return "INCOMPLETE_FEATURE_IDENTITIES_NOT_EVALUATED"
    if any(c.get("NOT_COMPARABLE") for c in counts_of):
        return "NOT_COMPARABLE"
    return "VERIFIED"


def row(case: str, *, family: str, entry, baseline, modification: str, activated: str, result=None, independent: str = "",
        explanation: str = "", extra: dict | None = None, baseline_entry=None, required: tuple[str, ...] = (),
        is_baseline: bool = False) -> dict[str, Any]:
    now = scalars(entry)
    base = baseline if baseline is not None else {}
    v = verdict(result) if result is not None else None
    return emit({"case": case, "family": family, "baseline_run": identity(baseline_entry), "modified_run": identity(entry),
                 "input_modification": modification, "actual_activation": activated,
                 "baseline_result": {k: None if x is None else format(x, "f") for k, x in base.items()},
                 "modified_result": {k: None if x is None else format(x, "f") for k, x in now.items()},
                 "difference": delta(base, now) if base else {}, "independent_expectation": independent,
                 "required_identities": list(required), "reconciliation": v,
                 "verdict": classify(result, required, baseline=is_baseline) if result is not None else "NOT_RECONCILED",
                 "explanation": explanation, **(extra or {})})
