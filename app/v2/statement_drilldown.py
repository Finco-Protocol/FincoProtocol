"""Statements V2 — hierarchical drill-down over the persisted Run's statement rows (SC-09).

Presentation structure only.  Every value shown is a cell the existing statement projection already produced from the
immutable Run evidence; this module nests those rows, attaches a navigation destination to each, and (model-period view
only) lists the Run's persisted revenue-stream detail.  It never sums children into a parent, never recomputes or
re-aggregates a statement line, never reads the editable Working Copy and never runs the engine.  A value the Run did not
persist stays ``None`` ("not available"), never zero.

Destinations come from the existing navigation manifest (``workspace_destinations``).  Most statement lines have no
one-to-one editable input; those say so and offer read-only Run provenance instead.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from app.v2.workspace_destinations import DESTINATIONS

PROVENANCE_TAB = "tab-trust"
_TAB_LABELS = {d.tab_id: d.label for d in DESTINATIONS}

# Presentation grouping of rows the Run persisted.  ("key", [children]) — a parent that is itself a persisted line keeps its
# own persisted values; ("group:<name>", ...) is a header with no value.  Parent/child is an accounting definition
# (EBIT = revenues - opex - depreciation, ...) used only to organise the display: no figure is derived from it.
_P = lambda key, *children: (key, tuple(children))  # noqa: E731
TREES: dict[str, tuple] = {
    "pnl": (
        _P("net_income_keur",
           _P("earnings_before_tax_keur",
              _P("ebit_keur", _P("revenues_keur"), _P("operating_expenses_keur"), _P("depreciation_keur")),
              _P("senior_interest_expense_keur"), _P("shl_interest_expense_keur")),
           _P("cit_accrual_keur")),
        _P("group:Equity roll-forward", _P("retained_earnings_keur"), _P("net_dividends_keur")),
    ),
    "cash_flow": (
        _P("fcf_banks_keur", _P("ebitda_cash_keur", _P("revenue_cash_keur"), _P("opex_cash_keur")), _P("cash_tax_keur")),
        _P("group:Senior debt service and reserves", _P("senior_total_ds_keur"), _P("dsra_funding_keur"), _P("dsra_release_keur")),
        _P("group:Cash after Senior and distributions", _P("fcf_junior_keur"), _P("fcf_for_distribution_keur"), _P("net_dividends_keur")),
    ),
    "balance_sheet": (
        _P("total_assets_keur", _P("net_fixed_assets_keur"), _P("dsra_balance_keur"), _P("cash_keur")),
        _P("total_liabilities_equity_keur", _P("share_capital_keur"), _P("retained_earnings_keur"), _P("shl_balance_keur"),
           _P("senior_balance_keur")),
        _P("balance_check_keur"),
    ),
}

# row key -> destination tab.  Absent => no one-to-one input: read-only Run provenance is offered instead.
_INPUT_DESTINATION = {
    "revenues_keur": "tab-revenue", "revenue_cash_keur": "tab-revenue",
    "operating_expenses_keur": "tab-opex", "opex_cash_keur": "tab-opex",
    "depreciation_keur": "tab-capex", "net_fixed_assets_keur": "tab-capex",
    "senior_interest_expense_keur": "tab-debt", "senior_total_ds_keur": "tab-debt", "senior_balance_keur": "tab-debt",
    "dsra_funding_keur": "tab-debt", "dsra_release_keur": "tab-debt", "dsra_balance_keur": "tab-debt",
    "cit_accrual_keur": "tab-tax", "cash_tax_keur": "tab-tax",
}
_EXPLANATION_DESTINATION = {"net_dividends_keur": "tab-returns", "fcf_for_distribution_keur": "tab-returns"}


def _destination(row_key: str, context: Mapping[str, Any]) -> dict[str, Any]:
    tab = _INPUT_DESTINATION.get(row_key)
    kind = "input"
    if tab is None:
        tab = _EXPLANATION_DESTINATION.get(row_key)
        kind = "explanation"
    if tab is None:
        tab, kind = PROVENANCE_TAB, "provenance"
    label = _TAB_LABELS.get(tab, tab)
    if kind == "input":
        note = context.get("input_note") or ""
        text = f"Open {label} (current Working Copy){' — ' + note if note else ''}"
    elif kind == "explanation":
        text = f"Open {label} (authoritative explanation)"
    else:
        text = "No one-to-one editable input for this line. Open read-only Run provenance"
    return {"tab_id": tab, "tab_label": label, "href": "#" + tab.replace("tab-", "", 1), "kind": kind, "title": text,
            "changes_context": kind == "input" and bool(context.get("input_note"))}


def _stream_rows(audit: Any, columns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Persisted per-stream revenue, aligned to the statement columns by period index (None when a period has none)."""
    from app.v2.output_workspace_projection import _cell
    if not isinstance(audit, (list, tuple)) or not audit:
        return []
    by_period: dict[int, Mapping[str, Any]] = {}
    for entry in audit:
        if isinstance(entry, Mapping) and isinstance(entry.get("period_index"), (int, float)):
            by_period[int(entry["period_index"])] = entry
    order: list[str] = []
    labels: dict[str, str] = {}
    for entry in by_period.values():
        for stream in entry.get("streams") or ():
            if isinstance(stream, Mapping) and isinstance(stream.get("id"), str) and stream["id"] not in labels:
                order.append(stream["id"])
                labels[stream["id"]] = f"{stream.get('type', 'stream')} · {stream['id']}"
    rows = []
    for sid in order:
        cells = []
        for col in columns:
            entry = by_period.get(int(col["index"]))
            value = None
            for stream in (entry or {}).get("streams") or ():
                if isinstance(stream, Mapping) and stream.get("id") == sid:
                    value = stream.get("revenue_keur")
            cells.append(_cell(value))
        rows.append({"key": f"stream:{sid}", "label": labels[sid], "cells": cells})
    return rows


def _flatten(spec: Sequence[tuple], rows_by_key: Mapping[str, Mapping[str, Any]], *, statement: str, basis: str,
             streams: Sequence[Mapping[str, Any]], context: Mapping[str, Any], id_prefix: str = "st") -> list[dict[str, Any]]:
    """Pre-order list of nodes.  A parent whose own row is absent from this Run lifts its children (nothing is dropped)."""
    seen: set[str] = set()

    def node_id(key: str) -> str:
        return f"{id_prefix}-{statement}-{basis}-" + key.replace(":", "-").replace(" ", "-")

    def build(node: tuple, depth: int, parent: Optional[str]) -> list[dict[str, Any]]:
        key, children = node
        group = key.startswith("group:")
        row = None if group else rows_by_key.get(key)
        if not group and row is None:
            return [n for child in children for n in build(child, depth, parent)]
        seen.add(key)
        kids: list[dict[str, Any]] = []
        for child in children:
            kids.extend(build(child, depth + 1, key))
        if key == "revenues_keur":
            kids.extend({"key": s["key"], "label": s["label"], "depth": depth + 1, "parent": key, "kind": "stream",
                         "children": [], "cells": s["cells"], "total": False, "unit": "keur", "css_class": "", "status_title": "",
                         "destination": _destination("revenues_keur", context), "value_source": "PERSISTED_STREAM_DETAIL",
                         "node_id": node_id(s["key"])} for s in streams)
        direct = [k["key"] for k in kids if k["parent"] == key]
        me = {"key": key, "label": key.split(":", 1)[1] if group else row["label"], "depth": depth, "parent": parent,
              "kind": "group" if group else "line", "children": direct, "total": bool(row and row.get("total")),
              "unit": (row or {}).get("unit", "keur"), "cells": None if group else row["cells"],
              "destination": None if group else _destination(key, context),
              "value_source": "GROUP_HEADER_NO_VALUE" if group else "PERSISTED_LINE",
              "css_class": (row or {}).get("css_class", ""), "status_title": (row or {}).get("status_title", ""),
              "node_id": node_id(key)}
        return [me, *kids]

    out: list[dict[str, Any]] = []
    for root in spec:
        out.extend(build(root, 0, None))
    for key, row in rows_by_key.items():                     # persisted lines the tree does not name stay visible
        if key not in seen:
            out.append({"key": key, "label": row["label"], "depth": 0, "parent": None, "kind": "line", "children": [],
                        "total": bool(row.get("total")), "unit": row.get("unit", "keur"), "cells": row["cells"],
                        "destination": _destination(key, context), "value_source": "PERSISTED_LINE",
                        "css_class": row.get("css_class", ""), "status_title": row.get("status_title", ""),
                        "node_id": node_id(key)})
    return out


def input_context(*, run_context: str, freshness_state: Optional[str]) -> dict[str, Any]:
    """What the navigation links lead to relative to the displayed Run (never silently the Run's own inputs)."""
    if run_context == "HISTORICAL_RUN":
        return {"kind": "HISTORICAL_RUN", "input_note": "this historical Run's own inputs are not shown here",
                "banner": "Historical Run. Links open the CURRENT Working Copy, which is not the inputs this Run used."}
    if freshness_state == "CURRENT":
        return {"kind": "RUN_MATCHES_WORKING_COPY", "input_note": "", "banner": ""}
    return {"kind": "WORKING_COPY_DIFFERS", "input_note": "may differ from this Run",
            "banner": "The Working Copy has changed since this Run. Links open the CURRENT Working Copy, not the inputs this Run used."}


def build_statement_drilldown(statements: Sequence[Mapping[str, Any]], *, multistream_audit: Any = None,
                              context: Mapping[str, Any], id_prefix: str = "st") -> list[dict[str, Any]]:
    """One drill-down per statement table, for the model-period and the annual view.

    ``id_prefix`` namespaces every DOM id: the Outputs sheet and a historical-Run fragment can be in the document together,
    so they must never share an id."""
    result = []
    for table in statements or ():
        sid = str(table.get("id") or "")
        spec = TREES.get(sid)
        if spec is None or not table.get("available"):
            continue
        entry: dict[str, Any] = {"id": sid, "title": table["title"], "views": {}}
        for basis, source in (("model", table), ("annual", table.get("annual") or {})):
            if not source or not source.get("available"):
                continue
            rows_by_key = {r["key"]: r for r in source["rows"]}
            streams = _stream_rows(multistream_audit, source["columns"]) if basis == "model" else []
            entry["views"][basis] = {
                "id": source["id"], "columns": source["columns"],
                "nodes": _flatten(spec, rows_by_key, statement=sid, basis=basis, streams=streams, context=context, id_prefix=id_prefix)}
        if entry["views"]:
            result.append(entry)
    return result


__all__ = ["TREES", "PROVENANCE_TAB", "build_statement_drilldown", "input_context"]
