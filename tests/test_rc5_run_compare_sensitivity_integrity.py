"""RC-5A / Workstream B: Run Comparison, assumption lineage and sensitivity integrity (read-only analytical authority).

Real Solar and Wind committed Runs through the real routes. Nothing here changes a financial formula, a tolerance or a persisted Run; GET views never
execute the model.
"""
from __future__ import annotations

import copy
import re
from dataclasses import replace

import pytest

from app.v2 import decision_support_projection as dsp
from tests.test_developer_economics_persistence_v1 import OWNER, Flow, env  # noqa: F401
from tests.test_rc2_integration_acceptance import _pi, _save_revenue
from tests.test_wf07_revenue_multistream import contracts

COMPARE = "/v2/workbook/run-compare"
SENS = "/v2/workbook/scenarios/sensitivity/run"


def _text(html):
    import html as _html
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))


def _history_ids(flow):
    from app.persistence.run_history_repository import get_run_history
    return [h.history_id for h in get_run_history(OWNER, flow.record.project_id)]      # newest first


def _compare(flow, run_a, run_b):
    return flow.env.client.get(COMPARE, params={**flow.project, "run_a": run_a, "run_b": run_b})


def _attribution(html):
    m = re.search(r'data-testid="ds-attribution" data-status="([A-Z_]+)">([^<]*)<', html)
    assert m, html[:500]
    return m.group(1), m.group(2).strip()


def _row(html, label):
    key = label.lower().replace(" ", "-")
    m = re.search(rf'data-testid="ds-var-{key}"[^>]*>(.*?)</tr>', html, re.S)
    assert m, label
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
    return cells        # [label, reference, selected, delta, pp, pct]


# ─────────────── signed deltas: one convention, delta = Selected - Reference ───────────────
def test_signed_delta_convention_positive_negative_zero_and_reversal():
    a = {"project_irr": 0.0800, "total_capex_keur": 50_000.0, "min_dscr": 1.30, "total_revenue_keur": 90_000.0}
    b = {"project_irr": 0.0765, "total_capex_keur": 52_500.0, "min_dscr": 1.30, "total_revenue_keur": 88_000.0}
    rows = {r.label: r for sec in dsp.build_run_variance(a, b) for r in sec.rows}
    assert rows["Project IRR"].abs_delta == rows["Project IRR"].pp_delta == "-0.35 pp"     # percentage points, signed
    assert rows["Total CAPEX"].abs_delta == "+2,500" and rows["Total CAPEX"].direction == "up"
    assert rows["Operating Revenue"].abs_delta == "-2,000" and rows["Operating Revenue"].pct_delta == "-2.2%"
    assert rows["Minimum DSCR"].abs_delta == "0.00x" and rows["Minimum DSCR"].direction == "flat"   # zero carries no sign
    reversed_rows = {r.label: r for sec in dsp.build_run_variance(b, a) for r in sec.rows}
    assert reversed_rows["Project IRR"].pp_delta == "+0.35 pp"                              # swapping reference/selected flips the sign
    assert reversed_rows["Total CAPEX"].abs_delta == "-2,500" and reversed_rows["Operating Revenue"].abs_delta == "+2,000"
    assert all("−" not in r.abs_delta and r.abs_delta != "2,500" for r in rows.values())    # never an unsigned magnitude


def test_dscr_and_unavailable_values_stay_truthful():
    rows = {r.label: r for sec in dsp.build_run_variance({"min_dscr": 1.35, "avg_dscr": None}, {"min_dscr": 1.20, "avg_dscr": 1.4}) for r in sec.rows}
    assert rows["Minimum DSCR"].abs_delta == "-0.15x"
    assert rows["Average DSCR"].abs_delta == "—" and rows["Average DSCR"].direction == ""   # unavailable is never zero


# ─────────────── assumption lineage ───────────────
def _ident(h, capex=None, opex=None, overrides=None):
    return {"composite_hash": h, "capex_rows": capex or [], "opex_rows": opex or [], "scenario_overrides": overrides or {}}


def test_identical_identity_is_the_only_no_difference_state():
    ia = ib = _ident("h1")
    rows = dsp.build_assumption_diff(ia, ib)
    att = dsp.build_assumption_attribution(ia, ib, rows)
    assert att.status == "IDENTICAL" and att.message == "Identical committed effective-input identity."
    assert dsp.build_drivers_of_change(rows, [], attribution=att)["no_assumption_changes"] is True


def test_different_identity_without_persisted_detail_is_never_shown_as_no_differences():
    ia, ib = _ident("h1"), _ident("h2")
    rows = dsp.build_assumption_diff(ia, ib)
    assert rows == []
    att = dsp.build_assumption_attribution(ia, ib, rows)
    assert att.status == "DIFFERENT_UNEXPLAINED"
    assert att.message == "Committed input identities differ. Detailed historical attribution is unavailable."
    assert dsp.build_drivers_of_change(rows, [], attribution=att)["no_assumption_changes"] is False


def test_genuinely_stored_capex_opex_and_contract_detail_is_itemized_with_an_honest_caveat():
    ca = [{"sub_line_id": "epc", "name": "EPC", "amount_keur": 1000.0}]
    cb = [{"sub_line_id": "epc", "name": "EPC", "amount_keur": 1200.0}]
    oa = [{"sub_line_id": "om", "name": "O&M", "amount_keur": 50.0}]
    ob = [{"sub_line_id": "om", "name": "O&M", "amount_keur": 40.0}]
    import json
    book = lambda price: json.dumps({"streams": [{"id": "ppa-1", "price_eur_mwh": price, "volume_share": 0.6}]})   # noqa: E731
    ia = _ident("h1", ca, oa, {"rev_multistream_config_json": book(60.0), "tax_rate": 0.2})
    ib = _ident("h2", cb, ob, {"rev_multistream_config_json": book(66.0), "tax_rate": 0.25})
    rows = dsp.build_assumption_diff(ia, ib)
    by = {(r.category, r.name): (r.value_a, r.value_b) for r in rows}
    assert by[("capex", "EPC")] == ("1,000", "1,200") and by[("opex", "O&M")] == ("50", "40")
    assert by[("revenue", "Contract ppa-1 · price_eur_mwh")] == ("60.0", "66.0")
    assert ("tax", "tax_rate") in by
    att = dsp.build_assumption_attribution(ia, ib, rows)
    assert att.status == "DIFFERENT_EXPLAINED" and "may not be complete" in att.caveat


def test_missing_identity_evidence_is_unknown_not_identical():
    att = dsp.build_assumption_attribution({}, _ident("h2"), [])
    assert att.status == "UNKNOWN" and "No assumption comparison is possible" in att.message
    assert dsp.build_assumption_attribution(None, None, []).status == "UNKNOWN"


# ─────────────── real committed Runs through the real route ───────────────
@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_runs_same_identity_then_different_contracts(env, kind, monkeypatch):
    flow = Flow(env, kind)
    book = contracts(_pi(flow), kind, price=95, merchant_price=90, strike=100)
    assert _save_revenue(flow, book).status_code == 200
    flow.run()
    flow.run()                                              # same committed effective inputs again
    same_b, same_a = _history_ids(flow)[0], _history_ids(flow)[1]
    html = _compare(flow, same_a, same_b).text
    assert _attribution(html)[0] == "IDENTICAL"
    assert "iterative solve" not in html and "No assumption differences" not in html
    changed = copy.deepcopy(book)
    changed["streams"][0]["price_eur_mwh"] = 110
    assert _save_revenue(flow, changed).status_code == 200
    summary_new = flow.run()
    ids = _history_ids(flow)
    newest, older = ids[0], ids[2]                          # reference = first run, selected = newest (different contracts)
    html = _compare(flow, older, newest).text
    status, message = _attribution(html)
    assert status == "DIFFERENT_UNEXPLAINED"                # base contracts are not persisted per Run: nothing is invented
    assert message == "Committed input identities differ. Detailed historical attribution is unavailable."
    assert "No assumption differences" not in html and "iterative solve" not in html
    # signed Δ = Selected − Reference against the persisted Run values (independent arithmetic)
    from app.persistence.run_history_repository import get_run_history_entry
    ref = get_run_history_entry(OWNER, flow.record.project_id, older).runtime_summary["total_revenue_keur"]
    sel = get_run_history_entry(OWNER, flow.record.project_id, newest).runtime_summary["total_revenue_keur"]
    assert sel > ref and abs(sel - summary_new["total_revenue_keur"]) < 1e-9
    cells = _row(html, "Operating Revenue")
    assert cells[3] == f"{sel - ref:+,.0f}"
    cells_rev = _row(_compare(flow, newest, older).text, "Operating Revenue")                     # reversed direction
    assert cells_rev[3] == f"{ref - sel:+,.0f}" and cells_rev[3].startswith("-")
    assert 'data-testid="ds-delta-convention"' in html and "Reference (Run A)" in html and "Selected (Run B)" in html


def test_compare_is_read_only_isolated_and_never_runs_the_engine(env, monkeypatch):
    flow = Flow(env, "solar")
    flow.run()
    flow.run()
    ids = _history_ids(flow)
    import app.api.project_runner as runner
    monkeypatch.setattr(runner, "run_project", lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET must not run the model")))
    ws0, before = flow.ws(), _history_ids(flow)
    assert _compare(flow, ids[1], ids[0]).status_code == 200
    assert _history_ids(flow) == before and flow.ws().last_runtime_snapshot_id == ws0.last_runtime_snapshot_id
    from app.auth import COOKIE_NAME, create_session_token
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="someone-else", username="admin"))
    assert _compare(flow, ids[1], ids[0]).status_code == 404                                   # owner isolation
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))


def test_a_legacy_run_without_identity_evidence_is_unknown(env, monkeypatch):
    flow = Flow(env, "solar")
    flow.run()
    flow.run()
    ids = _history_ids(flow)
    import app.persistence.run_history_repository as repo
    real = repo.get_run_history_entry

    def stripped(owner, project_id, history_id):
        entry = real(owner, project_id, history_id)
        return replace(entry, composite_hash=None, last_runtime_identity=None) if history_id == ids[1] else entry
    monkeypatch.setattr(repo, "get_run_history_entry", stripped)
    status, _ = _attribution(_compare(flow, ids[1], ids[0]).text)
    assert status == "UNKNOWN"


# ─────────────── contract-aware sensitivity ───────────────
@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_tariff_sensitivity_under_explicit_contracts_is_refused_not_flat(env, kind, monkeypatch):
    flow = Flow(env, kind)
    assert _save_revenue(flow, contracts(_pi(flow), kind, price=95, merchant_price=90, strike=100)).status_code == 200
    import app.services.sensitivity_execution as execution
    monkeypatch.setattr(execution, "run_sensitivity_points", lambda *a, **k: (_ for _ in ()).throw(AssertionError("refusal must not run points")))
    r = env.client.post(SENS, data={**flow.project, "driver": "tariff"})
    assert r.status_code == 200 and r.headers["X-Finco-Sensitivity-Outcome"] == "REFUSED"
    assert 'data-testid="sensitivity-refused"' in r.text and 'data-status="REFUSED"' in r.text
    from app.services.sensitivity_service import CONTRACTED_PRICE_SHOCK_REFUSAL
    assert CONTRACTED_PRICE_SHOCK_REFUSAL in _text(r.text)
    assert "-20%" not in r.text and "+20%" not in r.text                                       # no five-point table, nothing plausible and flat
    other = env.client.post(SENS, data={**flow.project, "driver": "generation"})              # contract-independent drivers are not refused
    assert "X-Finco-Sensitivity-Outcome" not in other.headers


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_valid_legacy_tariff_sensitivity_still_moves_the_inputs_and_outputs(env, kind, monkeypatch):
    flow = Flow(env, kind)
    import app.services.sensitivity_execution as execution
    captured = {}
    real = execution.run_sensitivity_points

    def spy(key, pis):
        captured["tariffs"] = [pi.revenue.ppa_base_tariff for pi in pis]
        return real(key, pis)
    monkeypatch.setattr(execution, "run_sensitivity_points", spy)
    r = env.client.post(SENS, data={**flow.project, "driver": "tariff"})
    assert r.status_code == 200 and "X-Finco-Sensitivity-Outcome" not in r.headers
    base = captured["tariffs"][2]
    assert [round(t / base, 6) for t in captured["tariffs"]] == [0.8, 0.9, 1.0, 1.1, 1.2]       # the legacy price really is shocked
    assert "FAILED" not in r.text


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_two_driver_matrix_and_goal_seek_refuse_with_the_same_contract_stance(env, kind):
    from app.services.sensitivity_service import CONTRACTED_PRICE_SHOCK_REFUSAL
    flow = Flow(env, kind)
    assert _save_revenue(flow, contracts(_pi(flow), kind, price=95, merchant_price=90, strike=100)).status_code == 200
    m = env.client.post("/v2/workbook/sensitivity/matrix/run", data={**flow.project, "driver_a": "tariff", "driver_b": "opex",
                                                                     "metric": "project_irr", "levels_a": "-5,0,5", "levels_b": "-5,0,5"})
    # every cell whose tariff shock is non-zero fails closed with the typed code (never a plausible flat value); only the unshocked tariff column runs
    assert "6 failed" in _text(m.text) and "REVENUE_V2_CONTRACTS_UNSUPPORTED" in m.text, _text(m.text)[:400]
    g = env.client.post("/v2/workbook/goal-seek/run", data={**flow.project, "target_metric": "project_irr", "target_value": "8.0",
                                                            "variable": "tariff"})
    assert CONTRACTED_PRICE_SHOCK_REFUSAL in _text(g.text), _text(g.text)[:400]
