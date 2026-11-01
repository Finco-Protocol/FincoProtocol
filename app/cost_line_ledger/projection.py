"""Provenance-free server projection of persisted cost lines with ledger classification and group subtotals.

Group totals are the plain sum of ACTIVE persisted line amounts (what the existing grid footer shows). They are not a model result and
claim no more than the saved data; the Run fold stays the only economic authority. Spreadsheet provenance is never emitted and the
projection fails closed if a source-reference key or cell-address pattern is about to be returned.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence

from app.cost_line_ledger.ledger import (
    CAPEX_PARENT_NAMES, DERIVED_CAPEX_PARENTS, LEDGER_VERSION, TEMPLATE_VERSION, RowKind, classify_persisted_line, ledger_rows,
)
from app.reference_detail_catalog import OPEX_PARENT_NAMES

PUBLIC_LINE_KEYS = frozenset({
    "sub_line_id", "label", "amount_keur", "row_version", "notes", "inflation_pct", "active", "category",
    "finco_display_code", "template_line_id", "row_kind", "summable", "lineage", "mapping_status",
})
PUBLIC_GROUP_KEYS = frozenset({"code", "label", "row_kind", "mapping_status", "line_count", "active_line_count", "saved_total_keur", "counts_toward_sheet_total"})

_FORBIDDEN_KEY = re.compile(r"excel|workbook|worksheet|spreadsheet|cell_ref|source_ref|source_cell|formula_ref|sheet_name", re.I)
_CELL_ADDRESS = re.compile(r"(?:'[^']+'|[A-Za-z_][A-Za-z0-9_ ]*)!\$?[A-Z]{1,3}\$?\d+")
_FILE_REF = re.compile(r"\.xls[xmb]?\b", re.I)
_USER_TEXT_KEYS = frozenset({"label", "notes"})        # free text typed by the owner is data, not provenance


class SourceProvenanceExposed(ValueError):
    """The projection was about to expose spreadsheet provenance to the client."""


def assert_no_source_provenance(obj: Any, _path: str = "$") -> None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if _FORBIDDEN_KEY.search(str(key)):
                raise SourceProvenanceExposed(f"forbidden provenance key at {_path}.{key}")
            if key in _USER_TEXT_KEYS:
                continue
            assert_no_source_provenance(value, f"{_path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            assert_no_source_provenance(value, f"{_path}[{i}]")
    elif isinstance(obj, str):
        if _CELL_ADDRESS.search(obj) or _FILE_REF.search(obj):
            raise SourceProvenanceExposed(f"spreadsheet reference pattern at {_path}")


def _num(value: Any) -> float:
    v = float(value or 0.0)
    if not math.isfinite(v):
        raise ValueError("non-finite persisted cost amount")
    return v


def project_cost_lines(technology: str, sheet: str, lines: Iterable[Mapping[str, Any]], *, codes: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Annotate persisted ``lines`` (route dicts) and add per-group saved totals.

    ``codes`` maps ``sub_line_id`` to the persisted FINCO business code. Input lines are never modified and no amount is altered.
    """
    if sheet not in ("capex", "opex"):
        raise ValueError(sheet)
    codes = codes or {}
    out: list[dict[str, Any]] = []
    for line in lines:
        code = codes.get(line.get("sub_line_id"), "") or ""
        cls = classify_persisted_line(technology, sheet, code, str(line.get("category") or ""))
        row = {k: line.get(k) for k in ("sub_line_id", "label", "amount_keur", "row_version", "notes", "inflation_pct", "active", "category")}
        row.update({"finco_display_code": code, "template_line_id": cls["template_line_id"], "row_kind": cls["row_kind"],
                    "summable": cls["summable"], "lineage": cls["lineage"], "mapping_status": cls["mapping_status"]})
        out.append(row)

    names = CAPEX_PARENT_NAMES if sheet == "capex" else OPEX_PARENT_NAMES
    kinds = {r.finco_display_code: r for r in ledger_rows(technology) if r.sheet == sheet and r.row_kind in (RowKind.HEADING.value, RowKind.DERIVED_RUNTIME.value)}
    parents = sorted(set(kinds) | {str(r["category"]) for r in out if r["category"]})
    groups = []
    for code in parents:
        members = [r for r in out if r["category"] == code]
        derived = code in DERIVED_CAPEX_PARENTS and sheet == "capex"
        unresolved = any(r["mapping_status"] == "UNRESOLVED" for r in members) or (kinds.get(code) is not None and
                    any(x.row_kind == RowKind.UNRESOLVED_MAPPING.value for x in ledger_rows(technology) if x.parent_group == code and x.sheet == sheet))
        active = [r for r in members if r["active"]]
        groups.append({
            "code": code, "label": f"{code} {names.get(code, code)}",
            "row_kind": RowKind.DERIVED_RUNTIME.value if derived else RowKind.HEADING.value,
            "mapping_status": "DERIVED" if derived else ("UNRESOLVED" if unresolved else "PROVEN"),
            "line_count": len(members), "active_line_count": len(active),
            "saved_total_keur": None if derived else math.fsum(_num(r["amount_keur"]) for r in active),
            "counts_toward_sheet_total": not derived,
        })
    result = {"ledger": {"version": LEDGER_VERSION, "template": TEMPLATE_VERSION}, "lines": out, "groups": groups,
              "saved_total_keur": math.fsum(g["saved_total_keur"] for g in groups if g["counts_toward_sheet_total"])}
    assert_no_source_provenance(result)
    return result
