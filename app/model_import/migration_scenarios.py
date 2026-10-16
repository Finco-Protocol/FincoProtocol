"""Static scenario-structure detection for the Excel migration plan.

A scenario NAME is a label, never proof of semantics.  This module records the observable evidence (a column
header, a sheet name, a selector cell, formulas that read the selector, a macro-bearing container) and decides
only one thing: whether per-scenario values are *statically observable as literal cells*.  It never evaluates
a formula, never runs a selector macro and never infers which scenario a cached result belongs to.

Resolution vocabulary
  STATIC_OBSERVABLE           every value cell of the scenario block is a literal
  PARTIALLY_OBSERVABLE        some value cells are literals, some are formulas (formula cells are dependencies)
  SCENARIO_LOGIC_UNRESOLVED   the scenario is selected by a switch/macro/formula, or only named; values cannot be
                              resolved without recalculation or execution
"""
from __future__ import annotations

import re
from typing import Any

from app.model_import.workbook_inspect import Inspection, clean_text, expand_ref

STATIC_OBSERVABLE = "STATIC_OBSERVABLE"
PARTIALLY_OBSERVABLE = "PARTIALLY_OBSERVABLE"
SCENARIO_LOGIC_UNRESOLVED = "SCENARIO_LOGIC_UNRESOLVED"
SEMANTICS_LABEL_ONLY = "LABEL_ONLY_UNVERIFIED"

MAX_SCENARIOS = 8
_SELECTOR_LABEL = re.compile(
    r"^(?:scenario|case)$|\b(?:scenario|case)\b.*\b(?:select\w*|switch|active|current|live|number|no|index|id)\b"
    r"|\b(?:select\w*|active|current|live|switch)\b.*\b(?:scenario|case)\b", re.IGNORECASE)
_SELECTOR_NAME = re.compile(r"scenario|case_?(?:sel|switch|no|num|idx)|switch|selector", re.IGNORECASE)
_SELECTOR_FUNCTIONS = frozenset({"CHOOSE", "INDEX", "MATCH", "VLOOKUP", "HLOOKUP", "XLOOKUP", "LOOKUP", "IF", "IFS",
                                 "SWITCH", "OFFSET", "INDIRECT"})

_KINDS = (
    ("BASE", re.compile(r"^(?:base(?: ?case)?|bc|reference(?: case)?|central|management case)$")),
    ("UPSIDE", re.compile(r"^(?:upside|optimistic|high(?: case)?|best(?: case)?)$")),
    ("DOWNSIDE", re.compile(r"^(?:downside|pessimistic|low(?: case)?|stress(?:ed)?(?: case)?|worst(?: case)?)$")),
    ("PROBABILITY", re.compile(r"^p ?(?:50|75|90|95|99)(?: case)?$")),
    ("FINANCING_CASE", re.compile(r"^(?:alt(?:ernative)? financing(?: case)?(?: [a-z0-9]+)?|financing(?: case)? [a-z0-9]+|"
                                  r"refinanc\w*(?: case)?|senior only|senior \+ mezz\w*)$")),
    ("NUMBERED", re.compile(r"^(?:case|scenario) ?[0-9a-z]$")),
)


def scenario_kind(text: Any) -> tuple[str, str, str] | None:
    """(kind, key, display label) when ``text`` is a recognised scenario name; the name alone proves nothing."""
    if not isinstance(text, str):
        return None
    norm = re.sub(r"\s+", " ", text.strip().casefold())
    norm = re.sub(r"^(?:scenario|case)\s*[:\-]\s*", "", norm) if re.match(r"^(?:scenario|case)\s*[:\-]", norm) else norm
    if not norm or len(norm) > 40:
        return None
    for kind, pattern in _KINDS:
        if pattern.match(norm):
            key = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")
            return kind, key, clean_text(text, 40)
    return None


def _sheet_scenario(title: str) -> tuple[str, str, str] | None:
    parts = [p for p in re.split(r"[\s_\-]+", title) if p]
    for i in range(len(parts)):
        for width in (2, 1):
            hit = scenario_kind(" ".join(parts[i:i + width]))
            if hit:
                return hit
    return None


def _colname(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _rows(insp: Inspection, sheet: str) -> list:
    return next((rows for title, rows in insp.tables if title == sheet), [])


def _detect_column_blocks(insp: Inspection) -> list[dict]:
    blocks = []
    for title, rows in insp.tables:
        for r_index, cells in enumerate(rows, 1):
            found: dict[str, dict] = {}
            for c_index, (val, _fmt, coord) in enumerate(cells, 1):
                hit = scenario_kind(val)
                if hit and hit[1] not in found:
                    found[hit[1]] = {"kind": hit[0], "key": hit[1], "label": hit[2], "column": _colname(c_index),
                                     "column_index": c_index - 1, "header_cell": coord}
            if len(found) < 2:
                continue
            headers = [str(v).strip().casefold() if isinstance(v, str) else "" for v, _, _ in cells]
            scen_cols = {s["column_index"] for s in found.values()}
            label_col = next((i for i, h in enumerate(headers) if h in ("assumption", "parameter", "item", "label", "field",
                                                                          "input", "description") and i not in scen_cols), 0)
            unit_col = next((i for i, h in enumerate(headers) if h in ("unit", "units", "uom") and i not in scen_cols), None)
            blocks.append({"sheet": title, "header_row": r_index, "label_col": label_col, "unit_col": unit_col,
                           "scenarios": list(found.values())[:MAX_SCENARIOS]})
            break                                   # one block per sheet is interpreted (documented limit)
    return blocks


def _selectors(insp: Inspection) -> list[dict]:
    out = []
    seen = set()
    for item in insp.report["defined_names"]:
        if item.get("kind") in ("cell",) and item.get("target") and _SELECTOR_NAME.search(item["name"]):
            t = item["target"]
            key = (t["sheet"], t["start"])
            if key not in seen:
                seen.add(key)
                out.append({"origin": "DEFINED_NAME", "name": item["name"], "sheet": t["sheet"], "cell": t["start"]})
    for title, rows in insp.tables:
        for r_index, cells in enumerate(rows, 1):
            for c_index, (val, _f, coord) in enumerate(cells[:3]):
                if isinstance(val, str) and _SELECTOR_LABEL.search(val.strip()) and c_index + 1 < len(cells):
                    nxt_val, _, nxt_coord = cells[c_index + 1]
                    literal = insp.literals.get((title, nxt_coord))
                    if literal is not None and not isinstance(literal, bool) and (
                            isinstance(literal, (int, float)) or scenario_kind(literal)):
                        key = (title, nxt_coord)
                        if key not in seen:
                            seen.add(key)
                            out.append({"origin": "LABELLED_CELL", "name": clean_text(val, 60), "sheet": title, "cell": nxt_coord})
    return out[:6]


def _selector_dependents(insp: Inspection, selector: dict) -> list[tuple[str, str]]:
    """Formula cells that read the selector cell (directly or through its defined name) with a selecting function."""
    hits = []
    sel_name = (selector.get("name") or "").lower() if selector["origin"] == "DEFINED_NAME" else None
    for key, info in insp.formulas.items():
        direct = False
        for ref in info["refs"]:
            if ref["sheet"] != selector["sheet"]:
                continue
            cells = expand_ref(ref)
            if cells is not None and (selector["sheet"], selector["cell"]) in cells:
                direct = True
                break
        by_name = bool(sel_name) and any(n.lower() == sel_name for n in info["names"])
        if (direct or by_name) and set(info["functions"]) & _SELECTOR_FUNCTIONS:
            hits.append(key)
    return hits


def governed_literals(insp: Inspection, roots: list[tuple[str, str]], *, depth: int = 6, cap: int = 5000,
                      visited_formulas: set | None = None) -> tuple[set, bool]:
    """Literal cells that feed ``roots`` through formula precedents (bounded).  Second value: truncated."""
    literals: set = set()
    frontier, seen, truncated = list(roots), set(roots), False
    if visited_formulas is not None:
        visited_formulas.update(roots)
    for _ in range(depth):
        nxt = []
        for key in frontier:
            info = insp.formulas.get(key)
            if info is None:
                continue
            for ref in info["refs"]:
                cells = expand_ref(ref)
                if cells is None:
                    truncated = True
                    continue
                for cell in cells:
                    if cell in seen:
                        continue
                    seen.add(cell)
                    if len(seen) > cap:
                        return literals, True
                    if cell in insp.formulas:
                        nxt.append(cell)
                        if visited_formulas is not None:
                            visited_formulas.add(cell)
                    elif cell in insp.literals:
                        literals.add(cell)
        frontier = nxt
        if not frontier:
            break
    else:
        truncated = truncated or bool(frontier)
    return literals, truncated


def detect_scenarios(insp: Inspection) -> dict:
    """Return structures, per-scenario observability, selector evidence and the cell partition for slicing."""
    macro = bool(insp.report["macro_bearing"])
    structures: list[dict] = []
    scenario_cells: dict[str, set] = {}          # scenario key -> literal value cells that belong to it
    scenario_formula_cells: dict[str, set] = {}
    column_blocks = _detect_column_blocks(insp)
    for n, block in enumerate(column_blocks, 1):
        rows = _rows(insp, block["sheet"])
        scen = []
        for s in block["scenarios"]:
            lit, frm = set(), set()
            for r_index, cells in enumerate(rows, 1):
                if r_index <= block["header_row"] or s["column_index"] >= len(cells):
                    continue
                coord = cells[s["column_index"]][2]
                key = (block["sheet"], coord)
                if key in insp.formulas:
                    frm.add(key)
                elif key in insp.literals and cells[block["label_col"]][0] not in (None, ""):
                    lit.add(key)
            skey = s["key"] if s["key"] not in scenario_cells else f'{s["key"]}__{block["sheet"]}'
            scenario_cells[skey], scenario_formula_cells[skey] = lit, frm
            state = (STATIC_OBSERVABLE if lit and not frm else PARTIALLY_OBSERVABLE if lit else SCENARIO_LOGIC_UNRESOLVED)
            scen.append({"key": skey, "label": s["label"], "kind": s["kind"], "column": s["column"],
                         "header_cell": s["header_cell"], "literal_cells": len(lit), "formula_cells": len(frm),
                         "resolution": state, "semantics": SEMANTICS_LABEL_ONLY})
        structures.append({"id": f"S{n}", "evidence": "COLUMN_BLOCK", "sheet": block["sheet"],
                           "header_row": block["header_row"], "scenarios": scen,
                           "block": {"label_col": block["label_col"], "unit_col": block["unit_col"],
                                     "header_row": block["header_row"], "sheet": block["sheet"]}})

    sheet_hits = {}
    for title in (r["name"] for r in insp.report["sheets"]):
        hit = _sheet_scenario(title)
        if hit:
            sheet_hits[title] = hit
    used_block_sheets = {b["sheet"] for b in column_blocks}
    cand = {t: h for t, h in sheet_hits.items() if t not in used_block_sheets}
    if len({h[1] for h in cand.values()}) >= 2:
        scen = []
        for title, (kind, key, label) in cand.items():
            lit = {k for k in insp.literals if k[0] == title}
            frm = {k for k in insp.formulas if k[0] == title}
            skey = key if key not in scenario_cells else f"{key}__{title}"
            scenario_cells[skey], scenario_formula_cells[skey] = lit, frm
            state = STATIC_OBSERVABLE if lit and not frm else PARTIALLY_OBSERVABLE if lit else SCENARIO_LOGIC_UNRESOLVED
            scen.append({"key": skey, "label": label, "kind": kind, "sheet": title, "literal_cells": len(lit),
                         "formula_cells": len(frm), "resolution": state, "semantics": SEMANTICS_LABEL_ONLY})
        structures.append({"id": f"S{len(structures) + 1}", "evidence": "SHEET_PER_SCENARIO", "scenarios": scen[:MAX_SCENARIOS]})
    elif cand and not column_blocks:
        title, (kind, key, label) = next(iter(cand.items()))
        structures.append({"id": f"S{len(structures) + 1}", "evidence": "NAME_ONLY", "scenarios": [{
            "key": key, "label": label, "kind": kind, "sheet": title, "literal_cells": 0, "formula_cells": 0,
            "resolution": SCENARIO_LOGIC_UNRESOLVED, "semantics": SEMANTICS_LABEL_ONLY,
            "reason": "SCENARIO_NAME_ALONE_DOES_NOT_PROVE_SEMANTICS"}]})

    selectors = []
    driven: list[tuple[str, str]] = []
    for sel in _selectors(insp):
        deps = _selector_dependents(insp, sel)
        driven.extend(deps)
        value = insp.literals.get((sel["sheet"], sel["cell"]))
        reasons = []
        if deps:
            reasons.append("SELECTOR_DRIVES_FORMULAS")
        else:
            reasons.append("SELECTOR_NOT_READ_BY_ANY_FORMULA")
            if macro:
                reasons.append("SELECTOR_MAY_BE_CONSUMED_BY_MACRO")
        if macro:
            reasons.append("MACRO_BEARING_WORKBOOK_SWITCH_MAY_BE_MACRO_DRIVEN")
        selectors.append({**sel, "cell_value": clean_text(value, 40) if value is not None else None,
                          "dependent_formula_count": len(deps),
                          "dependents_sample": [f"{s}!{c}" for s, c in deps[:5]],
                          "currently_selected_only": True, "reasons": reasons,
                          "resolution": SCENARIO_LOGIC_UNRESOLVED})
    governed, truncated = governed_literals(insp, driven) if driven else (set(), False)
    block_cells = set().union(*scenario_cells.values()) if scenario_cells else set()
    unresolved_cells = governed - block_cells
    if selectors and not structures:
        structures.append({"id": f"S{len(structures) + 1}", "evidence": "SELECTOR_ONLY", "scenarios": [{
            "key": "unresolved_selected_case", "label": "Currently selected case", "kind": "SELECTOR",
            "literal_cells": len(unresolved_cells), "formula_cells": len(driven),
            "resolution": SCENARIO_LOGIC_UNRESOLVED, "semantics": SEMANTICS_LABEL_ONLY,
            "reason": "SCENARIO_SELECTED_BY_SWITCH_ONLY_CURRENT_CASE_OBSERVABLE"}]})
    statuses = {s["resolution"] for st in structures for s in st["scenarios"]}
    overall = ("NONE_DETECTED" if not structures and not selectors else
               SCENARIO_LOGIC_UNRESOLVED if (selectors or SCENARIO_LOGIC_UNRESOLVED in statuses) else
               PARTIALLY_OBSERVABLE if PARTIALLY_OBSERVABLE in statuses else STATIC_OBSERVABLE)
    return {
        "overall": overall, "structures": structures, "selectors": selectors,
        "selector_driven_formula_cells": len(driven), "governed_truncated": truncated,
        "_scenario_cells": scenario_cells, "_scenario_formula_cells": scenario_formula_cells,
        "_unresolved_cells": unresolved_cells,
    }
