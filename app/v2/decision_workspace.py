"""Read-only commercial/decision presentation over existing canonical evidence.

No candidate execution or persistence. Arithmetic is limited to display deltas
and chart coordinates of finite, already-calculated results.
"""
from __future__ import annotations

from math import isfinite
from collections.abc import Mapping

from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) else None


def tender_presentation(result) -> dict:
    def get(key):
        return result.get(key) if isinstance(result, dict) else getattr(result, key, None)

    status = get("status")
    solved = numeric(get("solved_input_value")) if status in ("SOLVED", "TARGET_ALREADY_MET") else None
    start = numeric(get("started_from_value"))
    delta = solved - start if solved is not None and start is not None else None
    return {
        "accepted": solved is not None,
        "delta": f"{delta:+.2f} EUR/MWh" if delta is not None else "Not available",
        "variance": f"{delta / start * 100:+.1f}%" if delta is not None and start and start > 0 else "Not available",
    }


def sensitivity_presentation(results, driver, label) -> dict:
    """Five-point display deltas plus a single-driver range, not a multi-driver ranking."""
    projections = [build_scenario_projection(r["label"], r.get("kpis_raw") if r["status"] == "OK" else None, None, False)
                   for r in results]
    base_index = next((i for i, r in enumerate(results) if r["label"] == "Base" and r["status"] == "OK"), None)
    delta_rows = []
    tornado = []
    chart = []
    if base_index is not None:
        ordered = [projections[base_index]] + projections
        delta_rows = build_compare_rows(ordered)
        # Reuse the existing finite canonical tornado range builder without
        # performing any additional engine evaluation.
        from app.services.sensitivity_service import build_tornado_data
        base = numeric(results[base_index].get("kpis_raw", {}).get("project_irr"))
        finite = [(i, numeric(r.get("kpis_raw", {}).get("project_irr")))
                  for i, r in enumerate(results) if r["status"] == "OK"]
        finite = [(i, v) for i, v in finite if v is not None]
        if base is not None and len(finite) >= 2:
            tornado = build_tornado_data({"base_kpis": {"project_irr": base}, "rows": [
                {"shock_type": driver, "shock_label": label, "level_pct": results[i]["label"],
                 "deltas": {"project_irr": v - base}} for i, v in finite
            ]}, kpi_key="project_irr")
            scale = max(abs(v - base) for _, v in finite) or 1.0
            chart = [{"label": results[i]["label"], "value": f"{v * 100:.2f}%",
                      "delta": f"{(v - base) * 100:+.2f} pp", "width": abs(v - base) / scale * 45,
                      "negative": v < base} for i, v in finite]
    return {"delta_rows": delta_rows, "chart": chart, "tornado": tornado,
            "has_baseline": base_index is not None}


def scenario_assumptions(scenarios) -> tuple[dict, ...]:
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
    labels = {key: (label, unit) for key, label, unit in OVERRIDE_EDITOR_FIELDS}
    rows = []
    for sc in scenarios:
        rs = sc.last_run_summary or {}
        bound = rs.get("scenario_overrides_at_run")
        bound_values = bound if isinstance(bound, Mapping) else {}
        working = sc.overrides or {}
        rows.append({
            "name": sc.scenario_name,
            "working": tuple((labels.get(k, (k, ""))[0], str(v), labels.get(k, (k, ""))[1])
                             for k, v in sorted(working.items()) if not k.startswith("_")),
            "bound": tuple((labels.get(k, (k, ""))[0], str(v), labels.get(k, (k, ""))[1])
                           for k, v in sorted(bound_values.items()) if not k.startswith("_")),
            "bound_available": isinstance(bound, Mapping),
        })
    return tuple(rows)
