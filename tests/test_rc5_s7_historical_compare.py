"""RC-5 / S7-03: historical Run Compare integrity - itemize only what each Run itself persisted; name lines from Run evidence; state limits.

Read-only. The comparison never consults the current Working Copy, never runs the model and never invents a value or a label.
"""
from __future__ import annotations

import copy
import json
import re
import uuid

import pytest
from bs4 import BeautifulSoup

from app.v2 import decision_support_projection as dsp
from tests.test_developer_economics_persistence_v1 import OWNER, Flow, env  # noqa: F401
from tests.test_rc2_integration_acceptance import _pi, _save_revenue
from tests.test_rc5_run_compare_sensitivity_integrity import _compare, _history_ids
from tests.test_wf07_revenue_multistream import contracts

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _scalars(**values):
    base = {"operating_hours_p50": 1500.0, "ppa_base_tariff_eur_mwh": 50.0, "gearing_ratio": 0.7, "target_dscr": 1.15, "senior_tenor_years": 14}
    return {dsp.SCALAR_INPUTS_KEY: {"schema": "x", "values": {**base, **values}}}


def _ident(h="h", capex=None, opex=None, overrides=None, labels=None):
    out = {"composite_hash": h, "capex_rows": capex or [], "opex_rows": opex or [], "scenario_overrides": overrides or {}}
    if labels is not None:
        out["row_labels"] = labels
    return out


def _by_name(rows):
    return {r.name: r for r in rows}


# ── persisted effective scalars: P50 and the other provable scalars ───────────────────────────────────────────────────────

def test_p50_change_is_itemized_when_both_runs_recorded_it_reference_first():
    rows = dsp.build_assumption_diff(_ident("a"), _ident("b"), _scalars(operating_hours_p50=1500.0), _scalars(operating_hours_p50=1620.0))
    row = _by_name(rows)["P50 operating hours (h/yr)"]
    assert (row.category, row.value_a, row.value_b) == ("technical", "1500.0", "1620.0")        # A = Reference, B = Selected
    swapped = _by_name(dsp.build_assumption_diff(_ident("b"), _ident("a"), _scalars(operating_hours_p50=1620.0), _scalars(operating_hours_p50=1500.0)))
    assert (swapped["P50 operating hours (h/yr)"].value_a, swapped["P50 operating hours (h/yr)"].value_b) == ("1620.0", "1500.0")


@pytest.mark.parametrize("key,label,a,b", [
    ("operating_hours_p50", "P50 operating hours (h/yr)", 1500.0, 1400.0),
    ("ppa_base_tariff_eur_mwh", "PPA base tariff (EUR/MWh)", 50.0, 55.0),
    ("gearing_ratio", "Senior gearing ratio", 0.7, 0.65),
    ("target_dscr", "Target DSCR", 1.15, 1.3),
    ("senior_tenor_years", "Senior tenor (years)", 14, 16),
])
def test_each_recorded_scalar_changes_exactly_one_row_and_unchanged_scalars_are_omitted(key, label, a, b):
    rows = dsp.build_assumption_diff(_ident("a"), _ident("b"), _scalars(**{key: a}), _scalars(**{key: b}))
    assert [r.name for r in rows] == [label]
    assert dsp.build_assumption_diff(_ident("a"), _ident("b"), _scalars(), _scalars()) == []


def test_scalars_are_compared_only_when_both_runs_recorded_them_and_the_gap_is_stated():
    one_sided = dsp.build_assumption_diff(_ident("a"), _ident("b"), _scalars(operating_hours_p50=1500.0), {})
    assert one_sided == []                                                           # nothing inferred from the Run that lacks the evidence
    limits = {l.code: l.message for l in dsp.build_assumption_limitations(_ident("a"), _ident("b"), _scalars(), {})}
    assert "Selected (B)" in limits["SCALAR_INPUTS_NOT_RECORDED"] and "Reference (A)" not in limits["SCALAR_INPUTS_NOT_RECORDED"]
    both = {l.code: l.message for l in dsp.build_assumption_limitations(_ident("a"), _ident("b"), {}, {})}
    assert "Reference (A) and Selected (B)" in both["SCALAR_INPUTS_NOT_RECORDED"]
    assert not [l for l in dsp.build_assumption_limitations(_ident("a"), _ident("b"), _scalars(), _scalars()) if l.code == "SCALAR_INPUTS_NOT_RECORDED"]


def test_malformed_scalar_evidence_is_treated_as_not_recorded():
    for bad in ({dsp.SCALAR_INPUTS_KEY: "x"}, {dsp.SCALAR_INPUTS_KEY: {"values": []}}, {dsp.SCALAR_INPUTS_KEY: None}):
        assert dsp.build_assumption_diff(_ident("a"), _ident("b"), bad, _scalars()) == []


# ── CAPEX / OPEX names from authoritative historical evidence ─────────────────────────────────────────────────────────────

_CAPEX_ID_1, _CAPEX_ID_2 = str(uuid.uuid4()), str(uuid.uuid4())
_OPEX_ID = str(uuid.uuid4())


def _capex(sid, amount, category="C.01"):
    return {"sub_line_id": sid, "parent_category_code": category, "amount_keur": amount}


def _opex(sid, amount, group="B.02", code="B.02.01"):
    return {"sub_line_id": sid, "parent_group_code": group, "business_code": code, "amount_keur": amount, "inflation_pct": 2.0}


def test_recorded_row_labels_are_used_and_no_uuid_is_ever_a_label():
    labels = {"capex": {_CAPEX_ID_1: "PV Modules"}, "opex": {_OPEX_ID: "Preventive maintenance"}}
    a = _ident("a", capex=[_capex(_CAPEX_ID_1, 100.0)], opex=[_opex(_OPEX_ID, 10.0)], labels=labels)
    b = _ident("b", capex=[_capex(_CAPEX_ID_1, 120.0)], opex=[_opex(_OPEX_ID, 12.0)], labels=labels)
    rows = _by_name(dsp.build_assumption_diff(a, b))
    assert set(rows) == {"PV Modules", "Preventive maintenance"}
    assert (rows["PV Modules"].category, rows["PV Modules"].value_a, rows["PV Modules"].value_b) == ("capex", "100", "120")
    assert [l.code for l in dsp.build_assumption_limitations(a, b, _scalars(), _scalars())] == []        # everything recorded: no limitation


def test_name_recorded_in_only_one_run_is_still_authoritative_for_the_line():
    a = _ident("a", capex=[_capex(_CAPEX_ID_1, 100.0)])
    b = _ident("b", capex=[_capex(_CAPEX_ID_1, 120.0)], labels={"capex": {_CAPEX_ID_1: "PV Modules"}})
    assert [r.name for r in dsp.build_assumption_diff(a, b)] == ["PV Modules"]
    assert [l.code for l in dsp.build_assumption_limitations(a, b)] == ["ROW_NAMES_NOT_RECORDED", "SCALAR_INPUTS_NOT_RECORDED"]


def test_legacy_rows_use_registry_category_and_code_with_an_explicit_marker_never_the_id():
    a = _ident("a", capex=[_capex(_CAPEX_ID_1, 100.0), _capex(_CAPEX_ID_2, 50.0)], opex=[_opex(_OPEX_ID, 10.0)])
    b = _ident("b", capex=[_capex(_CAPEX_ID_1, 120.0), _capex(_CAPEX_ID_2, 60.0)], opex=[_opex(_OPEX_ID, 12.0)])
    rows = dsp.build_assumption_diff(a, b)
    names = [r.name for r in rows]
    assert len(set(names)) == len(names) == 3                                         # distinct, even for two nameless lines in one category
    assert all("name not recorded with this Run" in n for n in names)
    assert any(n.startswith("Production Units · sub-line") for n in names)
    assert any(n.startswith("O&M Preventive & Corrective · B.02.01") for n in names)
    assert not any(UUID_RE.search(n) for n in names) and _CAPEX_ID_1 not in " ".join(names)
    codes = [l.code for l in dsp.build_assumption_limitations(a, b)]
    assert "ROW_NAMES_NOT_RECORDED" in codes


def test_unknown_category_code_is_shown_as_the_code_not_a_guess():
    a = _ident("a", capex=[_capex(_CAPEX_ID_1, 1.0, category="C.99")])
    b = _ident("b", capex=[_capex(_CAPEX_ID_1, 2.0, category="C.99")])
    assert dsp.build_assumption_diff(a, b)[0].name.startswith("C.99 · sub-line")


# ── historical Revenue contract values ────────────────────────────────────────────────────────────────────────────────────

def _book(price=85.0, ident="ppa-1", extra=None):
    streams = [{"id": ident, "type": "ppa", "price_eur_mwh": price, "volume_share": 0.6, "start_date": "2030-01-01", "end_date": "2045-01-01"}]
    return {"scenario_revenue_input": {"authority": "materialized_project_inputs", "scenario_id": "s",
                                       "multistream_config_json": json.dumps({"version": 1, "streams": streams + (extra or [])})}}


def test_contract_books_are_compared_only_when_both_runs_recorded_them():
    rows = dsp.build_assumption_diff(_ident("a"), _ident("b"), _book(85.0), _book(95.0))
    assert [(r.category, r.name, r.value_a, r.value_b) for r in rows] == [("revenue", "Contract ppa-1 · price_eur_mwh", "85.0", "95.0")]
    assert dsp.build_assumption_diff(_ident("a"), _ident("b"), _book(85.0), {}) == []             # no inference from the Working Copy
    limit = [l for l in dsp.build_assumption_limitations(_ident("a"), _ident("b"), _book(85.0), {}) if l.code == "CONTRACT_BOOK_NOT_RECORDED"]
    assert len(limit) == 1 and "Selected (B)" in limit[0].message
    assert not [l for l in dsp.build_assumption_limitations(_ident("a"), _ident("b"), {}, {}) if l.code == "CONTRACT_BOOK_NOT_RECORDED"]


def test_contract_added_in_one_book_and_uuid_ids_are_labelled_without_the_uuid():
    cid = str(uuid.uuid4())
    extra = [{"id": cid, "type": "merchant", "price_eur_mwh": 60.0}]
    rows = dsp.build_assumption_diff(_ident("a"), _ident("b"), _book(85.0), _book(85.0, extra=extra))
    assert [(r.name, r.value_a, r.value_b) for r in rows] == [("MERCHANT contract 1", "—", "present")]
    assert not UUID_RE.search(rows[0].name)
    named = [{"id": cid, "type": "merchant", "name": "Spot sales", "price_eur_mwh": 60.0}]
    rows = dsp.build_assumption_diff(_ident("a"), _ident("b"), _book(85.0), _book(85.0, extra=named))
    assert rows[0].name == "Contract Spot sales"


def test_effective_books_supersede_override_derived_itemization_without_duplicates():
    book_a, book_b = _book(85.0), _book(95.0)
    ov_a = {"rev_multistream_config_json": book_a["scenario_revenue_input"]["multistream_config_json"]}
    ov_b = {"rev_multistream_config_json": book_b["scenario_revenue_input"]["multistream_config_json"]}
    rows = dsp.build_assumption_diff(_ident("a", overrides=ov_a), _ident("b", overrides=ov_b), book_a, book_b)
    assert [r.name for r in rows] == ["Contract ppa-1 · price_eur_mwh"]
    # Without the effective books the (persisted) scenario overrides still itemize, as before.
    legacy = dsp.build_assumption_diff(_ident("a", overrides=ov_a), _ident("b", overrides=ov_b))
    assert [r.name for r in legacy] == ["Contract ppa-1 · price_eur_mwh"]


# ── scenario overrides: readable, and never presented as applied when the Run says they were not ──────────────────────────

def test_override_rows_use_the_editor_label_and_flag_values_the_run_did_not_apply():
    a = _ident("a", overrides={"tariff_eur_mwh": 50.0, "gearing_pct": 60.0})
    b = _ident("b", overrides={"tariff_eur_mwh": 55.0, "gearing_pct": 70.0})
    evidence_b = {"effective_input_evidence": {"unbound_fields": ["gearing_pct"], "bound_fields": ["tariff_eur_mwh"]}}
    rows = _by_name(dsp.build_assumption_diff(a, b, {}, evidence_b))
    assert rows["Scenario override · Tariff (€/MWh)"].value_b == "55.0"
    gearing = rows["Scenario override · Gearing (%)"]
    assert gearing.value_a == "60.0" and gearing.value_b == "70.0 (saved, not applied by this Run)"
    assert dsp.build_assumption_diff(a, b)[0].name != "tariff_eur_mwh"                     # raw key never the label


def test_diff_is_a_pure_function_of_the_two_persisted_sides(monkeypatch):
    import app.persistence.workspace_repository as workspace_repository
    monkeypatch.setattr(workspace_repository, "get_workspace_state",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("the current Working Copy must not be read")))
    assert dsp.build_assumption_diff(_ident("a"), _ident("b"), _scalars(), _scalars(target_dscr=1.4))


# ── template + real route ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_template_renders_limitations_and_no_uuid():
    from app.v2.router import _templates
    template = _templates.get_template("partials/run_compare_expanded.html")
    limitations = dsp.build_assumption_limitations(_ident("a"), _ident("b"), {}, {})
    attribution = dsp.AssumptionAttribution("DIFFERENT_UNEXPLAINED", dsp.ATTRIBUTION_MESSAGES["DIFFERENT_UNEXPLAINED"])
    side = {"label": "x", "ran_at": "t", "scenario": "Base", "snapshot": "s", "state": "HISTORICAL", "is_last": False}
    html = template.render({"project_code": "p", "project_name": "P", "side_a": side, "side_b": {**side, "matches_working_copy": False},
                            "sections": [], "assumptions": [], "attribution": attribution, "limitations": limitations,
                            "drivers": dsp.build_drivers_of_change([], [], attribution=attribution),
                            "back_url": "/b", "workspace_url": "/w"})
    soup = BeautifulSoup(html, "html.parser")
    assert [li["data-limitation"] for li in soup.select('[data-testid="ds-limitations"] li')] == ["SCALAR_INPUTS_NOT_RECORDED"]
    assert not UUID_RE.search(html)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_runs_without_scalar_evidence_state_the_limitation_and_still_itemize_recorded_contracts(env, kind):
    flow = Flow(env, kind)
    book = contracts(_pi(flow), kind, price=95, merchant_price=90, strike=100)
    assert _save_revenue(flow, book).status_code == 200
    flow.run()
    changed = copy.deepcopy(book)
    changed["streams"][0]["price_eur_mwh"] = 110
    assert _save_revenue(flow, changed).status_code == 200
    flow.run()
    ids = _history_ids(flow)
    html = _compare(flow, ids[1], ids[0]).text
    soup = BeautifulSoup(html, "html.parser")
    rows = [[td.get_text(strip=True) for td in tr.find_all("td")] for tr in soup.select('tr[data-assumption-category="revenue"]')]
    assert any(r[1].endswith("price_eur_mwh") and r[2:] == ["95", "110"] for r in rows), rows
    shown = {li["data-limitation"] for li in soup.select('[data-testid="ds-limitations"] li')}
    assert "CONTRACT_BOOK_NOT_RECORDED" not in shown                                 # both Runs recorded their effective book
    assert not UUID_RE.search(soup.select_one('[data-testid="ds-assumptions"]').get_text())
