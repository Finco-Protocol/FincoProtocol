"""WF-06B: cost-line ledger identity, classification, projection and provenance isolation (pure, no DB)."""
import dataclasses
import math
import pytest

from app.cost_line_ledger import (
    LEDGER_SHA256, RowKind, ledger_rows, ledger_sha256, verify_ledger, classify_persisted_line, template_line_id,
    project_cost_lines, assert_no_source_provenance, SourceProvenanceExposed, PUBLIC_LINE_KEYS, PUBLIC_GROUP_KEYS,
)
from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD, CapexSubLine, fold_sub_lines_into_capex

TECHS = ("solar", "wind")


def test_ledger_is_pinned_and_immutable():
    assert verify_ledger() and ledger_sha256() == LEDGER_SHA256
    with pytest.raises(dataclasses.FrozenInstanceError):
        ledger_rows("solar")[0].label = "x"


@pytest.mark.parametrize("tech", TECHS)
def test_identity_is_unique_stable_and_not_a_spreadsheet_address(tech):
    rows = ledger_rows(tech)
    ids = [r.template_line_id for r in rows]
    assert len(ids) == len(set(ids))
    codes = [(r.sheet, r.finco_display_code) for r in rows]
    assert len(codes) == len(set(codes))
    assert [r.display_order for r in rows] == list(range(1, len(rows) + 1))
    assert all(i.startswith(f"{tech}:PUBLIC_GENERIC_DETAIL_V1:") for i in ids)
    assert template_line_id(tech, "C.02.01") == f"{tech}:PUBLIC_GENERIC_DETAIL_V1:C.02.01"
    assert_no_source_provenance([dataclasses.asdict(r) for r in rows])


@pytest.mark.parametrize("tech", TECHS)
def test_row_kind_rules(tech):
    rows = ledger_rows(tech)
    by = {(r.sheet, r.finco_display_code): r for r in rows}
    for code in ("C.17", "C.18"):                                   # derived financing/reserves are never spend
        r = by[("capex", code)]
        assert r.row_kind == RowKind.DERIVED_RUNTIME.value and not r.taxonomy_signed_off and r.canonical_field is None
    for r in rows:
        if r.row_kind == RowKind.HEADING.value:
            assert not r.taxonomy_signed_off
        if r.row_kind == RowKind.UNRESOLVED_MAPPING.value:
            assert not r.taxonomy_signed_off
        if r.row_kind == RowKind.EDITABLE_RUN_BOUND.value:
            assert r.taxonomy_signed_off and r.unit == "kEUR"
            if r.sheet == "capex":
                assert r.canonical_field == CAPEX_CATEGORY_TO_FIELD[r.parent_group]
    unresolved = {r.parent_group for r in rows if r.row_kind == RowKind.UNRESOLVED_MAPPING.value}
    assert unresolved == {"C.04", "C.05", "C.08", "C.11", "C.13", "B.13"}


def test_classify_persisted_line():
    t = classify_persisted_line("solar", "capex", "C.02.01", "C.02")
    assert t["lineage"] == "template" and t["row_kind"] == "editable_run_bound" and t["template_line_id"].endswith("C.02.01")
    u = classify_persisted_line("wind", "capex", "C.02.U001", "C.02")
    assert u["lineage"] == "user" and u["template_line_id"] is None and u["taxonomy_signed_off"]
    uu = classify_persisted_line("wind", "capex", "C.13.U001", "C.13")
    assert uu["mapping_status"] == "UNRESOLVED" and not uu["taxonomy_signed_off"]
    assert classify_persisted_line("solar", "opex", "weird", "B.01")["row_kind"] == "unsupported"


def _line(i, cat, amount, active=True, code=None):
    return {"sub_line_id": i, "label": f"Line {i}", "amount_keur": amount, "row_version": "v", "notes": None,
            "inflation_pct": None, "active": active, "category": cat}


def test_projection_totals_exclude_inactive_derived_and_never_mutate_amounts():
    lines = [_line("a", "C.02", 100.0), _line("b", "C.02", 50.5), _line("c", "C.02", 999.0, active=False), _line("d", "C.01", 10.0)]
    codes = {"a": "C.02.01", "b": "C.02.U001", "c": "C.02.02", "d": "C.01.01"}
    snapshot = [dict(l) for l in lines]
    res = project_cost_lines("solar", "capex", lines, codes=codes)
    assert lines == snapshot                                           # input untouched
    g = {x["code"]: x for x in res["groups"]}
    assert g["C.02"]["saved_total_keur"] == 150.5 and g["C.02"]["line_count"] == 3 and g["C.02"]["active_line_count"] == 2
    assert g["C.17"]["saved_total_keur"] is None and not g["C.17"]["counts_toward_sheet_total"]
    assert res["saved_total_keur"] == 160.5
    assert [l["amount_keur"] for l in res["lines"]] == [100.0, 50.5, 999.0, 10.0]
    assert all(set(l) == PUBLIC_LINE_KEYS for l in res["lines"]) and all(set(x) == PUBLIC_GROUP_KEYS for x in res["groups"])


def test_group_totals_reconcile_with_the_capex_fold():
    """Sum of projected group totals per canonical field == amounts the real fold adds (no drift, C.08/C.11 additive)."""
    from finco_core.inputs._models import CapexItem, CapexStructure
    specs = [("C.01", 120.25, True), ("C.08", 7.5, True), ("C.11", 2.5, True), ("C.13", 11.0, True), ("C.08", 99.0, False), ("C.02", 0.0, True)]
    subs = [CapexSubLine(sub_line_id=f"s{i}", project_id="p", parent_category_code=c, business_code=f"{c}.U{i:03d}", display_order=i,
                         label="x", amount_keur=a, is_active=act) for i, (c, a, act) in enumerate(specs, 1)]
    lines = [_line(s.sub_line_id, s.parent_category_code, s.amount_keur, s.is_active) for s in subs]
    res = project_cost_lines("wind", "capex", lines, codes={s.sub_line_id: s.business_code for s in subs})
    per_field = {}
    for g in res["groups"]:
        if g["saved_total_keur"] is not None and g["code"] in CAPEX_CATEGORY_TO_FIELD:
            f = CAPEX_CATEGORY_TO_FIELD[g["code"]]
            per_field[f] = per_field.get(f, 0.0) + g["saved_total_keur"]
    base = CapexStructure(**{f: CapexItem(name=f, amount_keur=1000.0) for f in set(CAPEX_CATEGORY_TO_FIELD.values())})
    folded = fold_sub_lines_into_capex(base, subs)
    for f, total in per_field.items():
        delta = getattr(folded, f).amount_keur - getattr(base, f).amount_keur
        assert math.isclose(delta, total, abs_tol=1e-9), f


@pytest.mark.parametrize("bad", [
    {"excel_source_ref": "x"}, {"lines": [{"workbook": "a"}]}, {"cell_ref": "A1"}, {"note": "Capex!C12"}, {"p": ["'Cost Sheet'!$B$4"]},
    {"file": "model.xlsx"},
])
def test_provenance_guard_rejects(bad):
    with pytest.raises(SourceProvenanceExposed):
        assert_no_source_provenance(bad)


def test_provenance_guard_allows_owner_text_and_normal_keys():
    assert_no_source_provenance({"sheet": "capex", "lines": [{"label": "see budget.xlsx Sheet1!A1", "notes": "Capex!B2"}], "code": "C.01.02"})
    res = project_cost_lines("solar", "opex", [dict(_line("z", "B.01", 1.0), label="from plan.xlsx")], codes={"z": "B.01.U001"})
    assert res["lines"][0]["label"] == "from plan.xlsx"
