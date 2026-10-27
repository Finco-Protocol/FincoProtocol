"""RC-UX B2 — read-only JSON adapter for the React Scenario / Run Compare workspace.

A presentation/adapter layer over the EXISTING canonical authorities.  It adds NO economic or persistence authority:

* scope, ownership, protected-reference refusal, coherent-workspace read and Run validation are the ones of
  ``app.v2.react_insights_router`` (the WF-REACT-3 insights authority) — imported, not copied;
* every KPI is the persisted value rendered by ``build_compare_rows`` / ``build_output_metric_projection``;
* the only arithmetic is presentational and server-side: a relative change against the reference Run (``(v - ref) / |ref|``) and
  period-aligned pass-through of persisted series.  A missing, null or zero-reference value stays "—" — never zero.

``GET /model-react/compare?project=CODE&run=H1&run=H2[&run=H3]`` — two or three explicitly selected committed Runs.  The first Run is
the reference.  Nothing is written, no Run is started, no Working Copy or scenario is touched.

What a historical Run does NOT persist is stated, not filled in: the full input set of a Run is not stored (only its composite hash,
scenario overrides and CAPEX / OPEX line amounts), so input differences beyond those are reported as not itemisable.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request

from app.v2.react_insights_router import _context, _error, _state, _validated_json

router = APIRouter()

MIN_RUNS = 2
MAX_RUNS = 3
NA = "—"

#: (key, label, unit, fmt, source path inside the committed Run).  Every value is read from the persisted evidence; none is derived.
SUPPLEMENTARY_ROWS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("legal_equity_contributed_keur", "Legal equity contributed", "kEUR", "keur",
     ("sponsor_schedule", "summary", "total_legal_equity_contributed_keur")),
    ("shl_cash_contributed_keur", "Shareholder loan cash contributed", "kEUR", "keur",
     ("sponsor_schedule", "summary", "total_shl_cash_contributed_keur")),
    ("legal_equity_distributions_keur", "Legal equity distributions", "kEUR", "keur",
     ("sponsor_schedule", "summary", "total_legal_equity_distributions_keur")),
    ("total_distribution_keur", "Cash distributions (distribution schedule)", "kEUR", "keur",
     ("distribution_schedule", "summary", "total_distribution_keur")),
    ("senior_contractual_maturity", "Senior contractual maturity", "date", "date",
     ("runtime_summary", "financing_evidence", "senior_debt_evidence", "repayment", "contractual_maturity_date")),
    ("senior_actual_payoff", "Senior actual payoff", "date", "date",
     ("runtime_summary", "financing_evidence", "senior_debt_evidence", "repayment", "actual_payoff_date")),
)

#: (key, label, schedule, field, period key) — period-aligned, pass-through series from the persisted schedules.
CASHFLOW_SERIES: tuple[tuple[str, str, tuple[str, ...], str, str], ...] = (
    ("revenue_cash_keur", "Revenue (cash)", ("financial_statements", "pf_cash_waterfall"), "revenue_cash_keur", "period_index"),
    ("opex_cash_keur", "Operating cost (cash)", ("financial_statements", "pf_cash_waterfall"), "opex_cash_keur", "period_index"),
    ("ebitda_cash_keur", "EBITDA (cash)", ("financial_statements", "pf_cash_waterfall"), "ebitda_cash_keur", "period_index"),
    ("cash_tax_keur", "Cash tax", ("financial_statements", "pf_cash_waterfall"), "cash_tax_keur", "period_index"),
    ("senior_total_ds_keur", "Senior debt service", ("financial_statements", "pf_cash_waterfall"), "senior_total_ds_keur", "period_index"),
    ("fcf_for_distribution_keur", "Cash flow available for distribution", ("financial_statements", "pf_cash_waterfall"),
     "fcf_for_distribution_keur", "period_index"),
    ("net_dividends_keur", "Net dividends", ("financial_statements", "pf_cash_waterfall"), "net_dividends_keur", "period_index"),
    ("senior_balance_keur", "Senior balance", ("debt_schedule",), "senior_balance_keur", "period"),
    ("dscr", "DSCR", ("debt_schedule",), "dscr", "period"),
    ("shl_cash_interest_receipt_keur", "SHL cash interest received", ("sponsor_schedule",), "shl_cash_interest_receipt_keur", "period"),
    ("shl_principal_receipt_keur", "SHL principal received", ("sponsor_schedule",), "shl_principal_receipt_keur", "period"),
    ("legal_equity_distribution_keur", "Legal equity distribution", ("sponsor_schedule",), "legal_equity_distribution_keur", "period"),
)
_RATIO_SERIES = frozenset({"dscr"})


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and abs(f) != float("inf") else None


def _path(entry: Any, path: tuple[str, ...]) -> Any:
    node: Any = entry
    for index, step in enumerate(path):
        node = getattr(node, step, None) if index == 0 else (node.get(step) if isinstance(node, dict) else None)
        if node is None:
            return None
    return node


def relative_change(value: Optional[float], reference: Optional[float]) -> tuple[Optional[float], str]:
    """(raw percent, display).  Undefined — never zero — when either side is missing or the reference is 0."""
    if value is None or reference is None or reference == 0:
        return None, NA
    pct = (value - reference) / abs(reference) * 100.0
    return pct, f"{pct:+.1f}%"


def _display(fmt: str, value: Any) -> str:
    number = _number(value)
    if fmt == "date":
        return value if isinstance(value, str) and value else NA
    if number is None:
        return NA
    if fmt == "keur":
        return f"{number:,.0f} kEUR"
    if fmt == "ratio":
        return f"{number:.2f}x"
    if fmt == "pct":
        return f"{number * 100:.2f}%"
    return f"{number:,.2f}"


def build_kpi_rows(entries, identities) -> list[dict[str, Any]]:
    from dataclasses import asdict

    from app.v2.output_metric_projection import KPI_CATALOG, SPONSOR_SUMMARY_SOURCE_KEYS
    from app.v2.run_history_projection import _enriched_kpis
    from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection

    projections = []
    for entry, identity in zip(entries, identities):
        kpis = _enriched_kpis(entry)
        sponsor_summary = (entry.sponsor_schedule or {}).get("summary") or {}
        for key, field in SPONSOR_SUMMARY_SOURCE_KEYS.items():
            kpis[key] = sponsor_summary.get(field)
        projections.append(build_scenario_projection(identity["scenario"], kpis, entry.ran_at, False))
    catalog = {row[0]: row for row in KPI_CATALOG}
    rows: list[dict[str, Any]] = []
    for row in build_compare_rows(projections):
        data = asdict(row)
        reference = data["raw_values"][0]
        pct = [relative_change(value, reference) if index else (None, NA) for index, value in enumerate(data["raw_values"])]
        data.update(unit=catalog[row.key][2], source=catalog[row.key][4], kind="kpi",
                    availability=["available" if v is not None else "not_available" for v in data["raw_values"]],
                    abs_deltas=data.pop("deltas"), pct_deltas=[p[1] for p in pct], pct_raw=[p[0] for p in pct])
        data.pop("variances", None)
        rows.append(data)
    rows.append({"key": "plcr", "label": "PLCR", "fmt": "ratio", "unit": "x", "kind": "kpi",
                 "values": [NA] * len(entries), "raw_values": [None] * len(entries), "abs_deltas": [NA] * len(entries),
                 "pct_deltas": [NA] * len(entries), "pct_raw": [None] * len(entries),
                 "availability": ["not_available"] * len(entries),
                 "source": "PLCR is not available",
                 "reason": "PLCR is not available in the saved Run results."})
    return rows


def build_supplementary_rows(entries) -> list[dict[str, Any]]:
    rows = []
    for key, label, unit, fmt, path in SUPPLEMENTARY_ROWS:
        values = [_path(e, path) for e in entries]
        raw = [_number(v) if fmt != "date" else None for v in values]
        reference = raw[0]
        pct = [relative_change(v, reference) if i else (None, NA) for i, v in enumerate(raw)]
        deltas = [NA] * len(entries)
        for i, v in enumerate(raw):
            if i and v is not None and reference is not None:
                deltas[i] = f"{v - reference:+,.0f} kEUR"
        if fmt == "date":
            deltas = [NA if i == 0 or values[i] is None or values[0] is None
                      else ("unchanged" if values[i] == values[0] else "changed") for i in range(len(entries))]
        available = [(v is not None and (fmt == "date" or _number(v) is not None)) for v in values]
        rows.append({"key": key, "label": label, "fmt": fmt, "unit": unit, "kind": "evidence",
                     "values": [_display(fmt, v) for v in values], "raw_values": raw,
                     "abs_deltas": deltas, "pct_deltas": [p[1] for p in pct], "pct_raw": [p[0] for p in pct],
                     "availability": ["available" if a else "not_available" for a in available],
                     "source": ".".join(path)})
    return rows


def build_cashflow(entries) -> dict[str, Any]:
    """Period-aligned persisted series for each Run (model-period index axis).  Totals are plain sums of persisted periods."""
    series = []
    for key, label, path, field, period_key in CASHFLOW_SERIES:
        runs = []
        axis: set[int] = set()
        for entry in entries:
            node: Any = getattr(entry, path[0], None)
            for step in path[1:]:
                node = node.get(step) if isinstance(node, dict) else None
            periods = (node or {}).get("periods") if isinstance(node, dict) else None
            by_period: dict[int, tuple[Optional[float], str]] = {}
            for row in periods or []:
                index = row.get(period_key) if isinstance(row, dict) else None
                if isinstance(index, int) and not isinstance(index, bool):
                    by_period[index] = (_number(row.get(field)), str(row.get("date") or ""))
            axis |= set(by_period)
            runs.append(by_period)
        ordered = sorted(axis)
        out_runs = []
        for entry, by_period in zip(entries, runs):
            values = [by_period[i][0] if i in by_period else None for i in ordered]
            present = [v for v in values if v is not None]
            out_runs.append({"history_id": entry.history_id, "values": values,
                             "total": (None if key in _RATIO_SERIES or not present else sum(present)),
                             "available": bool(present)})
        dates = [next((r[i][1] for r in runs if i in r and r[i][1]), "") for i in ordered]
        mismatch = any(len({r[i][1] for r in runs if i in r and r[i][1]}) > 1 for i in ordered)
        series.append({"key": key, "label": label, "unit": "x" if key in _RATIO_SERIES else "kEUR",
                       "source": ".".join(path) + ".periods." + field, "periods": ordered, "dates": dates,
                       "calendar_mismatch": mismatch, "runs": out_runs})
    return {"axis": "model period index", "series": series,
            "note": "Period values of each saved Run, aligned by model period. Totals are plain sums of the periods shown; "
                    "a period a Run does not have stays empty, never zero."}


def build_assumption_differences(entries) -> dict[str, Any]:
    """Differences that the immutable Run identity actually persists: overrides, CAPEX and OPEX line amounts, composite hash."""
    identities = [e.last_runtime_identity if isinstance(e.last_runtime_identity, dict) else {} for e in entries]
    hashes = [e.composite_hash for e in entries]

    def table(kind: str, id_key: str, label_key: str, value_key: str) -> list[dict[str, Any]]:
        names: dict[str, str] = {}
        values: list[dict[str, Any]] = []
        for identity in identities:
            mapping = {}
            for row in identity.get(kind) or []:
                if isinstance(row, dict) and row.get(id_key):
                    mapping[str(row[id_key])] = _number(row.get(value_key))
                    names.setdefault(str(row[id_key]), str(row.get(label_key) or ""))
            values.append(mapping)
        out = []
        for line_id in sorted({k for m in values for k in m}):
            amounts = [m.get(line_id) for m in values]
            if len({a for a in amounts}) > 1:
                out.append({"line_id": line_id, "group": names.get(line_id, ""), "values": amounts})
        return out

    override_keys = sorted({k for i in identities for k in (i.get("scenario_overrides") or {})})
    overrides = []
    for key in override_keys:
        values = [(i.get("scenario_overrides") or {}).get(key) for i in identities]
        if len({repr(v) for v in values}) > 1:
            overrides.append({"key": key, "values": values})
    persisted = [bool(i) for i in identities]
    return {"composite_hash_equal": len({h for h in hashes if h}) == 1 and all(hashes),
            "composite_hashes": hashes,
            "identity_persisted": persisted,
            "scenario_overrides": overrides,
            "capex_lines": table("capex_rows", "sub_line_id", "parent_category_code", "amount_keur"),
            "opex_lines": table("opex_rows", "sub_line_id", "parent_group_code", "amount_keur"),
            "limitation": "A saved Run records its inputs version, scenario overrides and CAPEX / OPEX line amounts only. "
                          "Any other input difference cannot be itemised from a Run; a different inputs version still proves the "
                          "inputs were not identical."}


@router.get("/model-react/compare")
async def react_compare(request: Request, project: str = ""):
    context, failure = _context(request, project)
    if failure is not None:
        return failure
    record, owner, ws, read_context = context
    if set(request.query_params) - {"project", "run"} or len(request.query_params.getlist("project")) != 1:
        return _error("INVALID_QUERY", 400)
    requested = request.query_params.getlist("run")
    if (not MIN_RUNS <= len(requested) <= MAX_RUNS or len(set(requested)) != len(requested)
            or any(not r.strip() or len(r) > 128 or r != r.strip() for r in requested)):
        return _error("EXPLICIT_RUN_SELECTION_REQUIRED", 422, "Select two or three distinct committed Runs to compare.")
    from app.persistence.run_history_repository import RunHistoryError, get_run_history_entry
    from app.services.react_insights_service import InsightsIdentityError, run_identity, run_links, validate_entry

    entries = []
    try:
        for history_id in requested:
            entry = get_run_history_entry(owner, record.project_id, history_id)
            if entry is None:
                return _error("RUN_NOT_FOUND", 404)
            validate_entry(entry, project_id=record.project_id, project_code=record.project_code, owner=owner)
            entries.append(entry)
    except (RunHistoryError, InsightsIdentityError):
        return _error("RUN_HISTORY_UNAVAILABLE", 422, "Stored Run evidence could not be verified.")
    freshness = read_context.freshness.state.value
    identities = [run_identity(e, _state(e, ws, freshness)) for e in entries]
    try:
        payload = {
            "ok": True, "schema": "rc-ux-compare-v1",
            "project": {"code": record.project_code, "project_id": record.project_id, "name": record.project_name},
            "working_copy": {"freshness": freshness, "composite_hash": getattr(read_context.inputs, "content_hash", None)},
            "reference_history_id": entries[0].history_id,
            "columns": [{**i, "links": run_links(record.project_code, i["history_id"])} for i in identities],
            "rows": build_kpi_rows(entries, identities) + build_supplementary_rows(entries),
            "cashflow": build_cashflow(entries),
            "assumptions": build_assumption_differences(entries),
            "semantics": {"read_only": True, "is_a_run": False,
                          "basis": "Saved Run results only. The first selected Run is the reference; "
                                   "a metric a Run does not have is shown as unavailable, never as zero."},
        }
    except (ValueError, TypeError, AttributeError, KeyError):
        return _error("RUN_EVIDENCE_UNAVAILABLE", 422, "Selected committed evidence could not be projected.")
    return _validated_json(read_context, payload)
