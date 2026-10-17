"""Excel migration PLAN: classification, scenario-aware slices and the macro-aware assessment.

Pure analysis.  No writer, no engine, no persistence, no formula evaluation, no macro execution.  The mapping,
unit and applicability rules are the existing AI Import V1/V2 engine (``intake.proposals_from_tables``) - this
module only decides *which cells* are shown to that engine, under *which scenario*, and how the rest of the
workbook is classified so that nothing is silently dropped or silently promoted to an assumption.

Classes (a cell has exactly one):
  DIRECT_INPUT_MAPPING                   canonical scalar field, exact type/unit/applicability validation
  STRUCTURED_INPUT_REQUIRES_OWNER_EDITOR cost lines, revenue contracts, financing instruments, cascade fields:
                                         each has its own canonical writer; never entered through scalar Apply
  FORMULA_OR_MACRO_DEPENDENCY            Excel logic; never turned into a fixed FINCO assumption
  OUTPUT_FOR_RECONCILIATION_ONLY         calculated/historical Excel outputs; evidence for comparison only
  UNSUPPORTED_OR_AMBIGUOUS               anything that cannot be mapped safely
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.model_import.intake import MAX_CELLS, proposals_from_tables
from app.model_import.migration_reconcile import match_metric
from app.model_import.migration_scenarios import (
    PARTIALLY_OBSERVABLE, SCENARIO_LOGIC_UNRESOLVED, STATIC_OBSERVABLE, detect_scenarios, governed_literals,
)
from app.model_import.workbook_inspect import Inspection, clean_text
from app.workbook.registry import WORKBOOK

DIRECT = "DIRECT_INPUT_MAPPING"
STRUCTURED = "STRUCTURED_INPUT_REQUIRES_OWNER_EDITOR"
FORMULA = "FORMULA_OR_MACRO_DEPENDENCY"
OUTPUT = "OUTPUT_FOR_RECONCILIATION_ONLY"
UNSUPPORTED = "UNSUPPORTED_OR_AMBIGUOUS"
CLASSES = (DIRECT, STRUCTURED, FORMULA, OUTPUT, UNSUPPORTED)

COMMON = "COMMON"
SINGLE_CASE = "SINGLE_CASE"
MAX_SLICE_ROWS = 150           # the signed review ticket's own bound
MAX_SLICES = 6
MAX_BASIS_OUTPUTS = 25
C0_WRITER = "Canonical batch writer (WorkbookUpdateService.apply_batch_draft_update, signed C0 review ticket)"

_OUTPUT_SHEET = re.compile(r"\b(?:outputs?|results?|summary|returns?|dashboard|kpis?|report|checks?|audit|dscr)\b", re.IGNORECASE)
_OUTPUT_LABEL = re.compile(
    r"\b(?:irr|npv|dscr|llcr|plcr|payback|moic|equity multiple|cfads|ebitda|net income|net profit|cash balance|"
    r"gearing achieved|total|subtotal|cumulative|npv of)\b", re.IGNORECASE)
_INPUT_QUALIFIER = re.compile(r"\b(?:target|covenant|threshold|lock[- ]?up|default|minimum required|input|assumed|assumption)\b",
                              re.IGNORECASE)
_UNIT_DECISION = frozenset({
    "IMPORT_PERCENT_SCALE_AMBIGUOUS", "IMPORT_PERCENT_SCALE_CONFLICT", "IMPORT_CURRENCY_UNIT_REQUIRED",
    "IMPORT_UNIT_INCOMPATIBLE", "IMPORT_NUMBER_FORMAT_AMBIGUOUS", "IMPORT_VALUE_INVALID", "IMPORT_DATE_INVALID",
})


def _row_of(coord: str) -> int:
    m = re.search(r"(\d+)$", coord)
    return int(m.group(1)) if m else 0


def _output_like(label: str, sheet: str) -> bool:
    if _OUTPUT_SHEET.search(sheet):
        return True
    return bool(_OUTPUT_LABEL.search(label)) and not _INPUT_QUALIFIER.search(label)


# ── table views handed to the existing mapping engine ─────────────────────────────────────────────────────
def _mask(tables: list, *, drop: set, skip_sheets: set, cut_rows: dict) -> list:
    out = []
    for title, rows in tables:
        if title in skip_sheets:
            continue
        limit = cut_rows.get(title)
        new_rows = []
        for r_index, cells in enumerate(rows, 1):
            if limit is not None and r_index >= limit:
                break
            new_rows.append([(None, None, c) if (title, c) in drop else (v, f, c) for v, f, c in cells])
        out.append((title, new_rows))
    return out


def _synth_table(insp: Inspection, sheet: str, value_cells: set, *, label_col: int | None, unit_col: int | None,
                 header_row: int = 0) -> tuple[str, list]:
    """label/value/unit rows for an explicit set of value cells, keeping original coordinates for provenance."""
    rows = next((r for t, r in insp.tables if t == sheet), [])
    out: list = [[("Assumption", None, "hdr"), ("Value", None, "hdr"), ("Unit", None, "hdr")]]
    blank = (None, None, "")
    for r_index, cells in enumerate(rows, 1):
        if r_index <= header_row:
            continue
        vcells = [c for c in cells if (sheet, c[2]) in value_cells]
        if label_col is not None:
            lab = cells[label_col] if label_col < len(cells) else None
        else:
            lab = next((c for c in cells if isinstance(c[0], str) and c[0].strip() and (sheet, c[2]) not in value_cells), None)
        if lab is None or lab[0] is None or not str(lab[0]).strip():
            continue
        if not vcells:
            out.append([lab, blank, blank])
            continue
        for vcell in vcells:
            if unit_col is not None:
                unit = cells[unit_col] if unit_col < len(cells) else blank
            else:
                idx = cells.index(vcell)
                unit = cells[idx + 1] if idx + 1 < len(cells) and isinstance(cells[idx + 1][0], str) else blank
            out.append([lab, vcell, unit])
    return sheet, out


# ── building blocks ───────────────────────────────────────────────────────────────────────────────────────
def _owner_text(p: dict) -> str:
    return p.get("owner_editor") or ""


def _item(i: int, p: dict, cls: str, *, insp: Inspection, scenario_key: str, scenario_label: str, target: dict,
          reason: str | None = None, dependency: str | None = None) -> dict:
    sheet, cell = p["sheet"], p["source_cell"]
    finfo = insp.formulas.get((sheet, cell))
    field_id = p.get("field_id") if cls == DIRECT else None      # outputs/formulas/structured never carry a scalar target
    canonical_unit = WORKBOOK.field(field_id).unit if field_id else None
    status = p["status"]
    if cls == DIRECT:
        if status == "ready":
            item_status = "READY_EXACT_FIELD_ID"
        elif status == "needs_review":
            item_status = "REVIEW_REQUIRED"
        elif status == "unchanged":
            item_status = "UNCHANGED"
        else:
            item_status = "BLOCKED"
    else:
        item_status = "NOT_APPLYABLE"
    decision = {
        DIRECT: ("Review the suggested mapping and confirm the target scenario" if item_status in ("READY_EXACT_FIELD_ID", "REVIEW_REQUIRED", "UNCHANGED")
                 else "Resolve the unit / number format, or enter the FINCO value manually in review"),
        STRUCTURED: "Enter through the owning FINCO editor; scalar Apply cannot write this",
        FORMULA: "Supply a plain input value (not a formula result) or enter the assumption in FINCO; the formula is not translated",
        OUTPUT: "None for Apply; usable as source evidence in the reconciliation step",
        UNSUPPORTED: "Map manually in review or leave out",
    }[cls]
    return {
        "item_id": f"I{i:04d}",
        "source": {"sheet": clean_text(sheet, 120), "cell": cell, "label_cell": p.get("label_cell"),
                   "precedent_refs": [f'{r["sheet"]}!{r["start"]}' + (f':{r["end"]}' if r["end"] else "") for r in (finfo or {}).get("refs", [])[:6]]},
        "label": clean_text(p["label"], 160), "section": clean_text(p.get("section"), 80),
        "source_value": clean_text(p["original_value"], 80), "source_unit": clean_text(p.get("source_unit"), 24) or None,
        "unit_origin": p.get("unit_origin"),
        "class": cls, "scenario_key": scenario_key, "scenario_label": scenario_label,
        "proposed_field": field_id, "proposed_label": WORKBOOK.field(field_id).label if field_id else None,
        "mapping_method": p.get("mapping_method"), "confidence_class": p.get("confidence_class"),
        "mapping_explanation": list(p.get("explanation") or ())[:4],
        "normalized_value": p.get("normalized_value"), "canonical_unit": canonical_unit,
        "unit_conversion": (f'{clean_text(p["original_value"], 40)} {p.get("source_unit") or "(no unit)"} -> {p["normalized_value"]} {canonical_unit or ""}'.strip()
                            if p.get("normalized_value") is not None and cls == DIRECT else None),
        "target": target,
        "supported_writer": (C0_WRITER if cls == DIRECT else (_owner_text(p) or None) if cls == STRUCTURED else None),
        "item_status": item_status, "reason": reason or p.get("reason"),
        "required_decision": decision, "required_unit_decision": bool(cls == DIRECT and p.get("reason") in _UNIT_DECISION),
        "unsupported_dependency": dependency,
        "alternatives": [{"field_id": a["field_id"], "label": a.get("label")} for a in (p.get("alternatives") or [])[:3]],
        "formula": ({"text": finfo["text"], "cached": finfo["cached"], "has_cached": finfo["has_cached"],
                     "cached_is_authoritative": False, "reference_count": len(finfo["refs"]),
                     "functions": finfo["functions"][:8], "flags": finfo["flags"]} if finfo else None),
    }


def _classify(p: dict, insp: Inspection, selector_cells: set) -> tuple[str, str | None, str | None]:
    sheet, cell, label = p["sheet"], p["source_cell"], p["label"]
    if (sheet, cell) in selector_cells:
        return UNSUPPORTED, "SCENARIO_SELECTOR_CELL", (
            "Scenario switch: its value only identifies the case selected when the workbook was last saved")
    finfo = insp.formulas.get((sheet, cell))
    if finfo is not None or p.get("reason") == "IMPORT_FORMULA_NOT_AUTHORITATIVE":
        dep = "Excel formula" + (" with " + ", ".join(finfo["flags"]).lower().replace("_", " ") if finfo and finfo["flags"] else "")
        if _output_like(label, sheet):
            return OUTPUT, "CALCULATED_OUTPUT_FORMULA", dep
        return FORMULA, "IMPORT_FORMULA_NOT_AUTHORITATIVE", dep
    if p.get("field_id"):
        return DIRECT, None, None
    if _output_like(label, sheet):
        return OUTPUT, "OUTPUT_LABEL_OR_SHEET", None
    if p.get("status") == "unsupported_for_apply" or p.get("target_kind") not in (None, "SCALAR", "UNSUPPORTED") or p.get("recognized_target"):
        return STRUCTURED, p.get("reason") or "UNSUPPORTED_FOR_APPLY", "Owned by a dedicated FINCO editor/writer"
    return UNSUPPORTED, p.get("reason") or "IMPORT_UNSUPPORTED_LABEL", None


def _trace_basis_output(item: dict, insp: Inspection) -> dict | None:
    """Source-output evidence for the reconciliation step (bounded; values are cached/literal, never recomputed)."""
    if item["class"] != OUTPUT:
        return None
    sheet, cell = item["source"]["sheet"], item["source"]["cell"]
    key = (next((t for t, _ in insp.tables if clean_text(t, 120) == sheet), sheet), cell)
    finfo = insp.formulas.get(key)
    raw = finfo["cached"] if finfo else insp.literals.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    metric = match_metric(item["label"])
    unit = item["source_unit"] or ("fraction" if finfo and finfo.get("percent_format") else None)
    out: dict[str, Any] = {
        "source": f"{sheet}!{cell}", "label": item["label"], "value": repr(raw) if isinstance(raw, float) else str(raw),
        "unit": unit, "metric_key": metric["key"] if metric else None, "scenario_key": item["scenario_key"],
        "formula": bool(finfo), "leaves": [], "leaves_truncated": False, "dependency_flags": [],
    }
    if finfo:
        visited: set = set()
        lits, truncated = governed_literals(insp, [key], depth=12, cap=5000, visited_formulas=visited)
        numeric = sorted(f"{s}!{c}" for (s, c) in lits if isinstance(insp.literals.get((s, c)), (int, float))
                         and not isinstance(insp.literals.get((s, c)), bool))
        out["leaves"], out["leaves_truncated"] = numeric[:80], truncated or len(numeric) > 80
        out["dependency_flags"] = sorted({f for vk in visited if vk in insp.formulas for f in insp.formulas[vk]["flags"]})
    return out


# ── the plan ───────────────────────────────────────────────────────────────────────────────────────────────
def build_plan(insp: Inspection, *, project_type: str, template_source: str, project_code: str,
               target_scenario_id: str | None, target_scenario_name: str | None) -> dict:
    scen = detect_scenarios(insp)
    target = {"project": project_code, "scenario_id": target_scenario_id,
              "scenario_name": target_scenario_name or "(default Working Copy)"}
    sheets = [s["name"] for s in insp.report["sheets"]]
    output_sheets = {t for t in sheets if _OUTPUT_SHEET.search(t)}
    selector_cells = {(s["sheet"], s["cell"]) for s in scen["selectors"]}
    unresolved_numeric = {k for k in scen["_unresolved_cells"]
                          if isinstance(insp.literals.get(k), (int, float)) and not isinstance(insp.literals.get(k), bool)}
    scenario_sheets: set[str] = set()
    cut_rows: dict[str, int] = {}
    scen_defs: list[dict] = []           # flattened scenario descriptors with their partition tables
    for st in scen["structures"]:
        for s in st["scenarios"]:
            d = {"structure": st["id"], "evidence": st["evidence"], **s}
            if st["evidence"] == "COLUMN_BLOCK":
                cut_rows[st["sheet"]] = st["block"]["header_row"]
                d["block"] = st["block"]
            elif st["evidence"] in ("SHEET_PER_SCENARIO", "NAME_ONLY"):
                scenario_sheets.add(s["sheet"])      # a scenario-named sheet never degrades to case-independent inputs
            scen_defs.append(d)

    drop = unresolved_numeric | selector_cells
    common_tables = _mask(insp.tables, drop=drop, skip_sheets=output_sheets | scenario_sheets, cut_rows=cut_rows)

    def scenario_tables(d: dict) -> list:
        cells = scen["_scenario_cells"].get(d["key"], set()) | scen["_scenario_formula_cells"].get(d["key"], set())
        if d["evidence"] == "COLUMN_BLOCK":
            b = d["block"]
            return [_synth_table(insp, b["sheet"], cells, label_col=b["label_col"], unit_col=b["unit_col"],
                                 header_row=b["header_row"])]
        if d["evidence"] in ("SHEET_PER_SCENARIO", "NAME_ONLY"):
            return [(t, rows) for t, rows in insp.tables if t == d["sheet"]]
        return []

    items: list[dict] = []
    counter = [0]

    def add_all(proposals: list[dict], scenario_key: str, scenario_label: str, resolution_forced: str | None = None) -> None:
        for p in proposals:
            if str(p["original_value"]).strip().casefold() in ("value", "unit", "units", "values"):
                continue                      # a column-header echo, not data
            counter[0] += 1
            cls, reason, dep = _classify(p, insp, selector_cells)
            if resolution_forced and cls == DIRECT:
                cls_item = _item(counter[0], p, cls, insp=insp, scenario_key=scenario_key, scenario_label=scenario_label,
                                 target=target, reason=resolution_forced, dependency="Scenario logic not statically resolvable")
                cls_item["item_status"] = "BLOCKED_SCENARIO_LOGIC_UNRESOLVED"
                cls_item["required_decision"] = "Scenario logic is unresolved (switch/macro/recalculation); do not apply without an owner decision"
                cls_item["supported_writer"] = None
                items.append(cls_item)
                continue
            items.append(_item(counter[0], p, cls, insp=insp, scenario_key=scenario_key, scenario_label=scenario_label,
                               target=target, reason=reason, dependency=dep))

    common_result = proposals_from_tables(common_tables, project_type=project_type, template_source=template_source)
    common_key = SINGLE_CASE if not scen_defs and not unresolved_numeric else COMMON
    add_all(common_result["proposals"], common_key, "Single case" if common_key == SINGLE_CASE else "Case-independent inputs")

    scenario_results: dict[str, dict] = {}
    for d in scen_defs:
        tables = scenario_tables(d)
        result = proposals_from_tables(tables, project_type=project_type, template_source=template_source) if tables else {"proposals": [], "totals": {}}
        scenario_results[d["key"]] = result
        forced = SCENARIO_LOGIC_UNRESOLVED if d["resolution"] == SCENARIO_LOGIC_UNRESOLVED else None
        add_all(result["proposals"], d["key"], d["label"], forced)

    if unresolved_numeric or selector_cells:
        by_sheet: dict[str, set] = {}
        for s, c in unresolved_numeric | selector_cells:
            by_sheet.setdefault(s, set()).add(c)
        un_tables = [_synth_table(insp, s, {(s, c) for c in cells}, label_col=None, unit_col=None) for s, cells in by_sheet.items()]
        un_result = proposals_from_tables(un_tables, project_type=project_type, template_source=template_source)
        add_all(un_result["proposals"], SCENARIO_LOGIC_UNRESOLVED, "Scenario logic unresolved", SCENARIO_LOGIC_UNRESOLVED)

    out_tables = [(t, rows) for t, rows in insp.tables if t in output_sheets]
    if out_tables:
        out_result = proposals_from_tables(out_tables, project_type=project_type, template_source=template_source)
        first_output_item = len(items)
        add_all(out_result["proposals"], common_key if common_key == SINGLE_CASE else COMMON, "Output sheet")
        for it in items[first_output_item:]:
            if it["class"] != OUTPUT and it["class"] != FORMULA:       # output sheets never feed scalar Apply
                it["class"], it["supported_writer"], it["item_status"] = OUTPUT, None, "NOT_APPLYABLE"
                it["reason"] = it["reason"] or "OUTPUT_LABEL_OR_SHEET"
                it["required_decision"] = "None for Apply; usable as source evidence in the reconciliation step"

    # reconciliation basis (source outputs with their dependency evidence), bounded
    basis = []
    for it in items:
        b = _trace_basis_output(it, insp)
        if b is not None:
            basis.append(b)
        if len(basis) >= MAX_BASIS_OUTPUTS:
            break

    # apply slices: scenario/common union through the SAME engine, so duplicates & applicability are re-checked
    slices = []
    observable_defs = [d for d in scen_defs if d["resolution"] != SCENARIO_LOGIC_UNRESOLVED]
    candidates: list[tuple] = []
    for d in observable_defs[:MAX_SLICES]:
        candidates.append((d["key"], d["label"], d["kind"], d["resolution"], common_tables + scenario_tables(d)))
    if not observable_defs:
        unresolved_present = bool(scen_defs or unresolved_numeric or selector_cells)
        candidates.append((common_key, "Case-independent inputs only" if unresolved_present else "Single case (no scenario structure detected)",
                           "COMMON", SCENARIO_LOGIC_UNRESOLVED if unresolved_present else STATIC_OBSERVABLE, common_tables))
    for key, label, kind, resolution, tables in candidates:
        result = proposals_from_tables(tables, project_type=project_type, template_source=template_source)
        props = result["proposals"]
        eligible_rows = [p for p in props if p["status"] in ("ready", "needs_review", "unchanged")]
        reasons = []
        if len(props) > MAX_SLICE_ROWS:
            reasons.append("SLICE_PROPOSAL_LIMIT_EXCEEDED")
        if not eligible_rows:
            reasons.append("NO_APPLYABLE_SCALAR_ROWS")
        slices.append({
            "key": key, "label": label, "kind": kind, "resolution": resolution, "scope": "scenario" if kind != "COMMON" else "common_only",
            "rows": len(props), "applyable_rows": len(eligible_rows), "totals": result["totals"],
            "apply_eligible": not reasons,
            "blockers": reasons, "notes": (["SCENARIO_LOGIC_UNRESOLVED_ELSEWHERE_IN_WORKBOOK"] if kind == "COMMON" and resolution == SCENARIO_LOGIC_UNRESOLVED else []),
            "_proposals": props,
        })
    for d in scen_defs:
        if d["resolution"] == SCENARIO_LOGIC_UNRESOLVED and len(slices) < MAX_SLICES + 2:
            slices.append({"key": d["key"], "label": d["label"], "kind": d["kind"], "resolution": SCENARIO_LOGIC_UNRESOLVED,
                           "scope": "scenario", "rows": 0, "applyable_rows": 0, "totals": {}, "apply_eligible": False,
                           "blockers": ["SCENARIO_LOGIC_UNRESOLVED"], "notes": [], "_proposals": []})

    # summaries
    counts = Counter(i["class"] for i in items)
    direct = [i for i in items if i["class"] == DIRECT]
    mapped = [i for i in direct if i["item_status"] in ("READY_EXACT_FIELD_ID", "REVIEW_REQUIRED", "UNCHANGED")]
    candidates_n = sum(1 for i in items if i["class"] != OUTPUT)
    interpreted_values = {(i["source"]["sheet"], i["source"]["cell"]) for i in items}
    numeric_total = Counter(k[0] for k, v in insp.literals.items() if isinstance(v, (int, float)) and not isinstance(v, bool))
    numeric_seen = Counter(clean_text(k[0], 120) for k in insp.literals if isinstance(insp.literals[k], (int, float))
                           and not isinstance(insp.literals[k], bool) and (clean_text(k[0], 120), k[1]) in interpreted_values)
    uninterpreted = {s: n - numeric_seen.get(clean_text(s, 120), 0) for s, n in numeric_total.items() if n - numeric_seen.get(clean_text(s, 120), 0) > 0}
    plan = {
        "workbook": {"sha256": insp.digest, "format": insp.report["format"], "size_bytes": insp.report["size_bytes"],
                     "macro_bearing": insp.report["macro_bearing"]},
        "target": target,
        "scenarios": {k: scen[k] for k in ("overall", "structures", "selectors", "selector_driven_formula_cells", "governed_truncated")},
        "items": items[:MAX_CELLS],
        "class_counts": {c: counts.get(c, 0) for c in CLASSES},
        "mapping": {
            "direct_total": len(direct), "direct_mapped": len(mapped),
            "direct_blocked": len(direct) - len(mapped),
            "input_candidates": candidates_n,
            "input_mapping_completeness": (round(len(mapped) / candidates_n, 4) if candidates_n else None),
            "definition": "mapped scalar candidates / all non-output candidates; says nothing about financial parity",
        },
        "coverage": {"numeric_literal_cells": sum(numeric_total.values()),
                     "numeric_cells_in_label_value_layout": sum(numeric_seen.values()),
                     "numeric_cells_not_interpreted": dict(sorted(uninterpreted.items(), key=lambda kv: -kv[1])[:10]),
                     "note": "Only label/value/unit rows and scenario column blocks are interpreted; wide period tables are not."},
        "slices": slices,
        "reconciliation_basis": basis,
        "apply_eligible": any(s["apply_eligible"] for s in slices),
    }
    plan["macro_assessment"] = macro_assessment(insp, plan, scen)
    return plan


# ── macro-aware dependency assessment (not a VBA interpreter) ──────────────────────────────────────────────
def macro_assessment(insp: Inspection, plan: dict, scen: dict) -> dict:
    rep = insp.report
    macro = rep["macro_bearing"]
    counts = plan["class_counts"]
    fl = rep["formulas"]
    structures = [s for st in scen["structures"] for s in st["scenarios"]]
    observable = [s["label"] for s in structures if s["resolution"] in (STATIC_OBSERVABLE, PARTIALLY_OBSERVABLE)]
    unresolved = [s["label"] for s in structures if s["resolution"] == SCENARIO_LOGIC_UNRESOLVED]
    if scen["selectors"] and not unresolved:
        unresolved.append("Case selected by a switch cell")
    needs_feature: list[str] = []
    blockers: list[str] = []
    flags = fl["flags"]
    if rep["calc"]["iterative"]:
        needs_feature.append("ITERATIVE_CALCULATION: the workbook relies on iterative/circular calculation; FINCO equivalence needs a separately approved financial feature review")
    if flags.get("DYNAMIC_OR_VOLATILE_FUNCTION"):
        needs_feature.append("DYNAMIC_ADDRESSING: INDIRECT/OFFSET/volatile functions make the dependency graph non-static")
    if macro and rep["vba"]["status"] != "ABSENT":
        needs_feature.append("MACRO_BEHAVIOUR: VBA project present; its behaviour is not interpreted and cannot be proven irrelevant")
    if unresolved:
        blockers.append("SCENARIO_LOGIC_UNRESOLVED: some scenario values require recalculation or macro execution")
    if counts[FORMULA]:
        blockers.append(f"FORMULA_ONLY_INPUTS: {counts[FORMULA]} cell(s) are formula results, not plain assumptions")
    if counts[STRUCTURED]:
        blockers.append(f"STRUCTURED_INPUTS: {counts[STRUCTURED]} cell(s) belong to cost/revenue/financing editors")
    if rep["external_links"] or flags.get("EXTERNAL_WORKBOOK_REFERENCE"):
        blockers.append("EXTERNAL_LINKS: values may depend on other workbooks that were not provided")
    if macro and rep["vba"]["status"] != "ABSENT":
        blockers.append("MACRO_PRESENT: scenario results or calculations may be produced by macros that are never executed here")
    if "FORMULAS_WITHOUT_CACHED_VALUES" in rep["warnings"]:
        blockers.append("NO_CACHED_RESULTS: some formulas have no stored result, so source outputs may be unavailable")
    if plan["coverage"]["numeric_cells_not_interpreted"]:
        blockers.append("UNINTERPRETED_REGIONS: numeric cells outside label/value/unit layouts (e.g. period tables) are not read")
    if rep["external_links"] or flags.get("DDE_REFERENCE") or flags.get("ACTIVE_OR_NETWORK_FUNCTION"):
        needs_feature.append("EXTERNAL_DATA: external links/DDE/network functions are never followed")
    return {
        "macro_bearing": macro,
        "plain_data_inputs_extractable": counts[DIRECT],
        "scenarios_statically_observable": observable,
        "scenarios_requiring_macro_or_recalculation": unresolved,
        "native_excel_formula_cells": fl["total"],
        "formula_functions_top": dict(list(fl["functions"].items())[:10]),
        "maps_to_existing_finco_authorities": {
            "scalar_batch_writer": counts[DIRECT], "owner_editors": counts[STRUCTURED],
            "owner_editors_named": sorted({i["supported_writer"] for i in plan["items"] if i["class"] == STRUCTURED and i["supported_writer"]})},
        "requires_separate_approved_feature": needs_feature,
        "prevents_accurate_migration": blockers,
        "automation_level": "PARTIAL_SCALAR_INPUT_MIGRATION_ONLY",
        "interpretation": "Dependency assessment from static container/formula evidence. No VBA source was read or interpreted; no macro, formula, link or DDE was executed.",
    }
