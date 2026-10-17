"""Bounded migration reconciliation: source-workbook outputs vs a committed native FINCO Run.

This is evidence plumbing, not a calculator.  It never runs a Run, never recomputes a financial result and never
translates a workbook formula.  The comparison itself is delegated to the P0-B3 framework
(``tools.numerical_validation.reconcile.compare``) so statuses, tolerance semantics and provenance gates are the
ones already reviewed there: PASS / FAIL / UNAVAILABLE / NOT_COMPARABLE, signed residual FINCO - reference.

A comparison is attempted only when EVERY gate below holds.  Otherwise the outcome is NOT_COMPARABLE with the
explicit reason codes - never a guessed parity and never a number "close enough":

  G1 the source output is a finite numeric value (cached/literal) whose label maps to exactly one FINCO metric in
     the explicit table below, with a unit that converts by an explicit rule;
  G2 the source output's formula precedents are fully observable: every numeric literal leaf was mapped AND applied
     through the signed review (a static hard-coded output has no dependency evidence at all);
  G3 the committed Run is the project's current Run for the same scenario, produced AFTER Apply (freshness CURRENT);
  G4 the applied values are still the values in the Working Copy;
  G5 the user attests that scope, currency, period and conventions of the source output equal the FINCO metric's.

Financial reconciliation is deliberately separate from the input mapping success rate.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


# label pattern -> FINCO runtime_summary key, canonical unit, stage in the P0-B3 dependency order.
# Deliberately small and explicit: a label not listed here is "no FINCO counterpart established".
METRICS: tuple[dict, ...] = (
    {"key": "equity_irr", "label": "Equity IRR", "pattern": r"^(?:equity|levered|sponsor) irr$", "unit": "fraction", "stage": "returns"},
    {"key": "project_irr", "label": "Project IRR", "pattern": r"^(?:project|unlevered|asset) irr$", "unit": "fraction", "stage": "returns"},
    {"key": "min_dscr", "label": "Minimum DSCR", "pattern": r"^(?:min(?:imum)?|lowest) dscr$", "unit": "ratio", "stage": "debt"},
    {"key": "avg_dscr", "label": "Average DSCR", "pattern": r"^(?:avg|average|mean) dscr$", "unit": "ratio", "stage": "debt"},
    {"key": "total_capex_keur", "label": "Total CAPEX", "pattern": r"^total (?:project )?capex$", "unit": "kEUR", "stage": "capex_funding"},
    {"key": "total_revenue_keur", "label": "Total revenue", "pattern": r"^total (?:project )?revenues?$", "unit": "kEUR", "stage": "revenue"},
    {"key": "total_opex_keur", "label": "Total OPEX", "pattern": r"^total (?:project )?opex$", "unit": "kEUR", "stage": "opex_ebitda"},
    {"key": "total_ebitda_keur", "label": "Total EBITDA", "pattern": r"^total (?:project )?ebitda$", "unit": "kEUR", "stage": "opex_ebitda"},
    {"key": "senior_debt_keur", "label": "Senior debt", "pattern": r"^(?:total )?senior debt(?: amount)?$", "unit": "kEUR", "stage": "capex_funding"},
)
_CURRENCY = {"eur": Decimal("0.001"), "€": Decimal("0.001"), "keur": Decimal(1), "k eur": Decimal(1), "k€": Decimal(1),
             "meur": Decimal(1000), "m eur": Decimal(1000), "m€": Decimal(1000)}
_FRACTION = {"fraction": Decimal(1), "decimal": Decimal(1), "ratio": Decimal(1), "%": Decimal("0.01"), "pct": Decimal("0.01"),
             "percent": Decimal("0.01")}
_RATIO = {"x": Decimal(1), "ratio": Decimal(1), "": Decimal(1)}
HORIZON = {"key": "HORIZON", "start": "1900-01-01", "end": "2999-12-31"}   # whole-run aggregate, NOT a calendar period
MODEL_LABEL = "source-workbook-cached-value-v1"


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[()\[\]:]", " ", str(text or "")).strip().casefold())


def match_metric(label: str) -> dict | None:
    norm = re.sub(r"\s*(?:\(|\[).*?(?:\)|\])\s*", " ", str(label or "")).strip()
    norm = _norm(norm)
    hits = [m for m in METRICS if re.match(m["pattern"], norm)]
    return hits[0] if len(hits) == 1 else None


def convert_source_value(metric: dict, value: Any, unit: str | None) -> tuple[Decimal | None, str | None]:
    """Explicit unit rule only.  Returns (value in the metric's canonical unit, reason-if-not)."""
    if isinstance(value, bool) or value is None:
        return None, "SOURCE_VALUE_MISSING"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, "SOURCE_VALUE_NOT_NUMERIC"
    if not number.is_finite():
        return None, "SOURCE_VALUE_NOT_FINITE"
    u = (unit or "").strip().casefold()
    table = {"fraction": _FRACTION, "kEUR": _CURRENCY, "ratio": _RATIO}[metric["unit"]]
    if u not in table:
        return None, "SOURCE_UNIT_NOT_CONVERTIBLE" if u else "SOURCE_UNIT_REQUIRED"
    if metric["unit"] == "fraction" and u in ("", ):
        return None, "SOURCE_UNIT_REQUIRED"
    return number * table[u], None


def finco_metric_value(runtime_summary: Mapping[str, Any], metric: dict) -> tuple[Decimal | None, str | None]:
    raw = runtime_summary.get(metric["key"]) if isinstance(runtime_summary, Mapping) else None
    if raw is None or isinstance(raw, bool):
        return None, "FINCO_METRIC_UNAVAILABLE"
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None, "FINCO_METRIC_NOT_NUMERIC"
    return (value, None) if value.is_finite() else (None, "FINCO_METRIC_NOT_FINITE")


def _p0b3():
    """P0-B3 is loaded lazily: the application must start even where the validation tooling is not deployed."""
    from tools.numerical_validation import reconcile as framework
    return framework


def _sha(obj: Any) -> str:
    return hashlib.sha256(_p0b3().canonical_bytes(obj)).hexdigest()


def _dec_str(value: Decimal) -> str:
    return format(value.normalize(), "f") if value != 0 else "0"


def reconcile_output(*, output: Mapping[str, Any], applied_cells: set[str], applied_fields: list[dict],
                     run: Mapping[str, Any], run_current: bool, applied_values_intact: bool,
                     scenario_ok: bool, slice_key: str, attested: bool,
                     abs_tolerance: str = "0", rel_tolerance: str = "0", project_code: str = "") -> dict:
    """One source output -> one reconciliation row.  ``run`` is a plain mapping of the committed Run evidence."""
    metric = next((m for m in METRICS if m["key"] == output.get("metric_key")), None)
    row: dict[str, Any] = {
        "source": output.get("source"), "label": output.get("label"), "scenario_key": output.get("scenario_key"),
        "finco_metric": metric["key"] if metric else None, "unit": metric["unit"] if metric else None,
        "source_value": output.get("value"), "source_unit": output.get("unit"),
        "run": {k: run.get(k) for k in ("history_id", "runtime_snapshot_id", "ran_at", "engine_version", "composite_hash",
                                        "active_scenario_id")},
        "status": "NOT_COMPARABLE", "reasons": [], "comparison": None,
    }
    reasons: list[str] = []
    if metric is None:
        reasons.append("NO_FINCO_COUNTERPART_ESTABLISHED")
    source_value, why = (convert_source_value(metric, output.get("value"), output.get("unit")) if metric else (None, None))
    if why:
        reasons.append(why)
    if output.get("scenario_key") not in (slice_key, "COMMON", "SINGLE_CASE"):
        reasons.append("SOURCE_OUTPUT_BELONGS_TO_ANOTHER_SCENARIO")
    # G2 – dependency evidence
    if not output.get("formula"):
        reasons.append("SOURCE_OUTPUT_IS_STATIC_VALUE_NO_DEPENDENCY_EVIDENCE")
    else:
        if output.get("dependency_flags"):
            reasons.append("SOURCE_OUTPUT_DEPENDS_ON_DYNAMIC_OR_EXTERNAL_LOGIC")
        if output.get("leaves_truncated"):
            reasons.append("SOURCE_OUTPUT_DEPENDENCY_GRAPH_TRUNCATED")
        if not output.get("leaves"):
            reasons.append("SOURCE_OUTPUT_HAS_NO_INPUT_LEAVES")
        missing = [leaf for leaf in output.get("leaves", []) if leaf not in applied_cells]
        if missing:
            reasons.append("SOURCE_OUTPUT_DEPENDS_ON_UNMAPPED_OR_UNAPPLIED_INPUTS")
            row["unapplied_leaf_count"] = len(missing)
            row["unapplied_leaf_sample"] = missing[:5]
    if not run_current:
        reasons.append("RUN_NOT_CURRENT_FOR_APPLIED_INPUTS")
    if not scenario_ok:
        reasons.append("RUN_SCENARIO_DIFFERS_FROM_TARGET")
    if not applied_values_intact:
        reasons.append("WORKING_COPY_CHANGED_AFTER_APPLY")
    if not attested:
        reasons.append("CONVENTIONS_NOT_ATTESTED")
    finco_value, why = (finco_metric_value(run.get("runtime_summary") or {}, metric) if metric else (None, None))
    if why:
        reasons.append(why)
    row["reasons"] = sorted(set(reasons))
    if row["reasons"]:
        return row

    # Every gate holds: delegate to P0-B3 with a single whole-horizon observation.
    try:
        framework = _p0b3()
    except ImportError:
        row["reasons"] = ["P0B3_FRAMEWORK_UNAVAILABLE"]
        return row
    canonical_bytes, compare = framework.canonical_bytes, framework.compare
    config = _sha({"project": project_code, "scenario": run.get("active_scenario_id"),
                   "applied": sorted((a["field_id"], a["value"]) for a in applied_fields)})
    conventions = _sha({"attested": True, "metric": metric["key"], "unit": metric["unit"], "source_cells": output.get("source")})
    ref_rows = {"rows": [{"metric": metric["key"], "period": HORIZON["key"], "value": _dec_str(source_value),
                          "unit": metric["unit"], "currency": "EUR"}]}
    fin_rows = {"rows": [{"metric": metric["key"], "period": HORIZON["key"], "value": _dec_str(finco_value),
                          "unit": metric["unit"], "currency": "EUR"}]}
    ref_bytes, fin_bytes = canonical_bytes(ref_rows), canonical_bytes(fin_rows)

    def identity(run_key: str, engine: str, sha: str) -> dict:
        return {"project_key": project_code or "project", "scenario_key": str(run.get("active_scenario_id") or "default"),
                "configuration_sha256": config, "run_key": run_key,
                "calculated_at": str(run.get("ran_at") or "1970-01-01T00:00:00+00:00"),
                "engine_version": engine, "output_sha256": sha, "currency": "EUR", "calendar": "HORIZON_AGGREGATE",
                "conventions_sha256": conventions}
    manifest = {
        "version": 1,
        "reference": identity("source-workbook:" + str(output.get("workbook_sha256", ""))[:16], MODEL_LABEL,
                              hashlib.sha256(ref_bytes).hexdigest()),
        "finco": identity("finco-run:" + str(run.get("history_id")), str(run.get("engine_version") or "unknown"),
                          hashlib.sha256(fin_bytes).hexdigest()),
        "reference_export_version": MODEL_LABEL, "reference_parsed_version": MODEL_LABEL,
        "periods": [{"reference": dict(HORIZON), "finco": dict(HORIZON)}],
        "metrics": [{"key": metric["key"], "stage": metric["stage"], "reference_metric": metric["key"],
                     "finco_metric": metric["key"], "unit": metric["unit"],
                     "abs_tolerance": abs_tolerance, "rel_tolerance": rel_tolerance}],
    }
    result = compare(manifest, ref_bytes, fin_bytes)
    cell = result["results"][0]
    row["status"] = cell["status"]
    row["reasons"] = [cell["reason"]] if cell["reason"] else []
    row["comparison"] = {k: cell[k] for k in ("reference_value", "finco_value", "delta_finco_minus_reference", "absolute_difference",
                                               "relative_difference", "absolute_tolerance", "relative_tolerance", "tolerance_allowance")}
    row["p0b3_schema"] = result["schema"]
    row["horizon_note"] = "Whole-run aggregate; not a calendar period alignment."
    return row


def reconciliation_summary(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"outputs": len(rows), "counts": counts,
            "comparable": sum(1 for r in rows if r["status"] in ("PASS", "FAIL")),
            "status": ("NOT_STARTED" if not rows else "COMPARED" if any(r["status"] in ("PASS", "FAIL") for r in rows)
                       else "NOT_COMPARABLE")}


def evidence_digest(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
