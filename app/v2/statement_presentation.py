"""Shared table adapter over the existing persisted/annual statement projection.

No statement assembly, engine execution or second aggregation authority.
"""
from app.workbook.runtime_projection import build_runtime_projection_bundle


def statement_table(rows, labels, table_id, title, note="", classification="", periods=None, index_key="period"):
    from app.v2.output_workspace_projection import _cell, _columns, period_label
    columns = (_columns(periods, index_key) if periods else
               [{"index": n, "date": label, "label": period_label(label), "year0": False}
                for n, label in enumerate(labels)])
    return {"id": table_id, "title": title, "note": note, "classification": classification,
            "unavailable": [row["label"] for row in rows or () if all(v is None for v in row["values"])],
            "available": rows is not None and bool(columns), "columns": columns,
            "rows": [{"key": row["key"], "label": row["label"], "total": row.get("is_total", False),
                      "unit": "keur", "cells": [_cell(value) for value in row["values"]],
                      "css_class": row.get("css_class", ""), "status_title": row.get("status_title", "")}
                     for row in rows or ()]}


def financial_statement_tables(projection, *, payload=None):
    """Both views use the SAME canonical rows; annual values already aggregated exactly once."""
    payload = payload or {}
    from app.v2.output_workspace_projection import STATEMENT_NOTES
    result = []
    for table_id, title, attr, section, index_key in (
        ("pnl", "Profit & Loss", "pnl", "pnl", "period"),
        ("balance_sheet", "Balance Sheet", "bs", "balance_sheet", "period_index"),
        ("cash_flow", "Cash Flow (PF waterfall)", "pf_cf", "pf_cash_waterfall", "period_index"),
    ):
        table = statement_table(getattr(projection, attr + "_rows"),
                                getattr(projection, attr + "_period_labels"), table_id, title,
                                STATEMENT_NOTES[table_id],
                                getattr(projection, attr + "_classification"),
                                (payload.get(section) or {}).get("periods"), index_key)
        table["annual"] = statement_table(getattr(projection, attr + "_annual_rows"),
                                          getattr(projection, attr + "_annual_labels"),
                                          table_id + "-annual", title, "Canonical annual view · flows summed; stocks year-end.")
        result.append(table)
    return result


def statements_from_run(runtime_result, stale=False):
    from app.workbook.runtime_projection import thaw_runtime_payload
    projection = build_runtime_projection_bundle(runtime_result, stale).fs
    payload = thaw_runtime_payload(getattr(runtime_result, "financial_statements", None) or {}) or {}
    return financial_statement_tables(projection, payload=payload)
