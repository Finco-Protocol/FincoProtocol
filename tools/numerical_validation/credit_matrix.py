"""WF-A credit validation matrix: one row per (case, credit metric), plus explicit directional checks between cases.

Pure rendering over results already produced by :func:`credit.reconcile_credit`; it never reads the application and
never runs a model.  A successful stress Run is not a validation PASS: every metric row carries the REPORTED value,
the INDEPENDENTLY recomputed value, the signed difference, the approved tolerance and the resulting status.

Directional checks compare two cases on a metric under an expectation that has been derived from the product's actual
mechanics (see the report).  A check never asserts that every ratio moves with a shock: re-sized debt absorbs a CFADS
shock by design, so each expectation is stated per sizing mode.  An unexpected direction is reported
``FAIL`` + ``FINANCIAL AUTHORITY REVIEW REQUIRED``; it is never silently "explained away" and never auto-corrected.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from .reconcile import canonical_bytes

SCHEMA = "FINCO_CREDIT_MATRIX_V1"

#: (identity, metric label, unit) — the reported-versus-independent pairs the credit layer can state.
METRICS = (
    ("CR-SIZED-DEBT", "Senior debt quantum (solver final size vs Sources & Uses)", "kEUR"),
    ("CR-GEARING-DEF", "Gearing (recorded vs Senior / total uses)", "ratio"),
    ("CR-DSCR-MIN", "Minimum DSCR (reported vs recomputed)", "ratio"),
    ("CR-DSCR-AVG", "Average DSCR (reported vs recomputed)", "ratio"),
    ("DEBT-TOTAL-SERVICE", "Total Senior debt service (reported vs scheduled sum)", "kEUR"),
    ("CR-LOCKUP-COUNT", "Periods in lock-up (reported vs closed-gate periods)", "periods"),
)

AUTHORITY_REVIEW = "FINANCIAL AUTHORITY REVIEW REQUIRED"


def metric_rows(label: str, result: Mapping[str, Any], *, delta: str, configuration: Mapping[str, Any]) -> list[dict]:
    """Matrix rows for one case from its credit reconciliation result."""
    rows: list[dict] = []
    outcomes = result["outcomes"]
    for identity, metric, unit in METRICS:
        mine = [o for o in outcomes if o["identity"] == identity]
        if not mine:
            rows.append(_row(label, result, delta, configuration, metric, unit, identity, None))
            continue
        # one summary outcome per identity for the scalar metrics; the worst residual represents multi-period identities
        worst = max(mine, key=lambda o: Decimal(o["absolute_residual"] or 0))
        statuses = {o["status"] for o in mine}
        status = "FAIL" if "FAIL" in statuses else ("PASS" if statuses == {"PASS"} else
                                                    "NOT_COMPARABLE" if "NOT_COMPARABLE" in statuses else "UNAVAILABLE")
        rows.append(_row(label, result, delta, configuration, metric, unit, identity, worst, status))
    return rows


def _row(label, result, delta, configuration, metric, unit, identity, outcome, status="UNAVAILABLE") -> dict:
    ident = result["identity"]
    base = {"case": label, "run_key": ident["run_key"], "snapshot_id": ident["snapshot_id"],
            "composite_hash": ident["composite_hash"], "assumption_delta": delta,
            "financing_configuration": dict(configuration), "credit_metric": metric, "unit": unit, "identity": identity}
    if outcome is None:
        return {**base, "reported": None, "independent": None, "signed_difference": None, "approved_allowance": None,
                "tolerance_policy": None, "result": "UNAVAILABLE", "reason": "IDENTITY_NOT_EVALUATED_FOR_THIS_RUN"}
    return {**base, "reported": outcome["observed"], "independent": outcome["expected"],
            "signed_difference": outcome["residual_observed_minus_expected"], "approved_allowance": outcome["allowance"],
            "tolerance_policy": outcome["tolerance_policy"], "result": status, "reason": outcome["reason"]}


def directional(name: str, expectation: str, a: str, a_value: Decimal | None, b: str, b_value: Decimal | None,
                relation: str, *, tolerance: Decimal = Decimal("1e-6"), basis: str = "") -> dict:
    """Compare ``b`` against ``a``.  ``relation`` is one of: increases, decreases, unchanged, not_below, not_above."""
    if relation not in ("increases", "decreases", "unchanged", "not_below", "not_above"):
        raise ValueError(f"unsupported relation {relation!r}")
    row = {"check": name, "expectation": expectation, "basis": basis, "from_case": a, "to_case": b, "relation": relation,
           "tolerance": format(tolerance, "f")}
    if a_value is None or b_value is None:
        return {**row, "from_value": None if a_value is None else format(a_value, "f"),
                "to_value": None if b_value is None else format(b_value, "f"), "signed_difference": None,
                "result": "UNAVAILABLE", "action": ""}
    diff = b_value - a_value
    ok = {"increases": diff > tolerance, "decreases": diff < -tolerance, "unchanged": abs(diff) <= tolerance,
          "not_below": diff >= -tolerance, "not_above": diff <= tolerance}[relation]
    return {**row, "from_value": format(a_value, "f"), "to_value": format(b_value, "f"),
            "signed_difference": format(diff, "f"), "result": "PASS" if ok else "FAIL",
            "action": "" if ok else AUTHORITY_REVIEW}


def build(cases: Sequence[Mapping[str, Any]], directionals: Sequence[Mapping[str, Any]],
          unavailable_cases: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    rows = [r for case in cases for r in case["rows"]]
    counts = {s: sum(r["result"] == s for r in rows) for s in ("PASS", "FAIL", "UNAVAILABLE", "NOT_COMPARABLE")}
    dcounts = {s: sum(d["result"] == s for d in directionals) for s in ("PASS", "FAIL", "UNAVAILABLE")}
    return {"schema": SCHEMA, "cases": [{"case": c["case"], "run_key": c["run_key"], "assessment": c.get("assessment", [])}
                                        for c in cases],
            "rows": rows, "metric_counts": counts, "directional_checks": list(directionals),
            "directional_counts": dcounts, "cases_without_committed_run": list(unavailable_cases),
            "disclaimer": "A successful stress Run is not a validation PASS, and a credit identity PASS does not establish "
                          "bankability. Directional expectations follow the product's actual sizing mechanics."}


def render(matrix: Mapping[str, Any]) -> dict[str, bytes]:
    js = canonical_bytes(matrix)
    lines = ["# WF-A credit validation matrix", "", matrix["disclaimer"], "",
             f"Metric rows: {matrix['metric_counts']}  ·  Directional checks: {matrix['directional_counts']}", "",
             "## Reported vs independently recomputed", "",
             "| Case | Run | Assumption delta | Metric | Reported | Independent | Signed difference | Allowance | Result |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in matrix["rows"]:
        lines.append(f"| {r['case']} | `{r['run_key'][:8]}` | {r['assumption_delta']} | {r['credit_metric']} | "
                     f"{_short(r['reported'])} | {_short(r['independent'])} | {_short(r['signed_difference'])} | "
                     f"{_short(r['approved_allowance'])} | {r['result']} |")
    lines += ["", "## Directional checks", "", "| Check | Expectation | From → To | Values | Result |", "|---|---|---|---|---|"]
    for d in matrix["directional_checks"]:
        lines.append(f"| {d['check']} | {d['expectation']} | {d['from_case']} → {d['to_case']} | "
                     f"{_short(d['from_value'])} → {_short(d['to_value'])} | {d['result']}{' — ' + d['action'] if d['action'] else ''} |")
    if matrix["cases_without_committed_run"]:
        lines += ["", "## Cases without a committed Run", ""]
        lines += [f"* `{c['case']}` — {c['assumption_delta']}: {c['reason']}" for c in matrix["cases_without_committed_run"]]
    return {"credit_matrix.json": js, "credit_matrix.md": ("\n".join(lines) + "\n").encode()}


def _short(value: Any) -> str:
    if value is None:
        return "—"
    try:
        d = Decimal(value)
    except Exception:  # noqa: BLE001
        return str(value)
    return format(d.quantize(Decimal("0.000001")) if d != d.to_integral() else d, "f")


__all__ = ["SCHEMA", "METRICS", "AUTHORITY_REVIEW", "metric_rows", "directional", "build", "render", "json"]
