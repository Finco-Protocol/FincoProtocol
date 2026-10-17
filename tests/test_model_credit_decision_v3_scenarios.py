"""RC-4 / B Credit Decision: lender cases, DSCR feasibility, reserves, proposals, revenue downside, failed attempts and scenarios on REAL
committed canonical Runs (second ring; shares the helpers of the first real-run module)."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from tests.test_model_credit_decision_v3_real_runs import (  # noqa: F401  (cenv is a fixture)
    USER, cenv, credit, finding, history, last, set_field)
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (env is the fixture cenv builds on)
from tests.test_model_financing_f2 import config, run, save


def rows_of(data):
    return {r["key"]: r for g in data["comparison"]["groups"] for r in g["rows"]}


# ── P50 versus P90-10y lender case (paired Runs), STALE binding ----------------------------------------------------------
def test_p50_vs_p90_lender_cases_are_separate_from_the_operating_case_and_bound_only_when_current(cenv):
    record = cenv.create("solar")
    assert "field-error-banner" not in save(cenv, record, config(lender_case="P_50")).text
    run(cenv, record)
    first = last(record)
    assert "field-error-banner" not in save(cenv, record, config(lender_case="P90-10y")).text
    # the Working Copy changed after the first Run: it is STALE, so Working Copy terms must not be bound to it
    _, stale = credit(cenv, record)
    assert stale["runs"][0]["identity"]["state"] == "LAST RUN · STALE"
    assert stale["runs"][0]["structure"]["lender_case"]["value"]["v"] is None
    run(cenv, record)
    second = last(record)
    assert second.history_id != first.history_id
    _, data = credit(cenv, record, second.history_id, first.history_id)
    now, before = data["runs"]
    assert now["identity"]["state"] == "LAST RUN · CURRENT" and before["identity"]["state"] == "HISTORICAL"
    assert now["structure"]["lender_case"]["value"]["v"] == "P90-10y"
    assert "bound Working Copy" in now["structure"]["lender_case"]["credit_case"]
    assert before["structure"]["lender_case"]["value"]["v"] is None            # the P50 Run did not persist its lender case
    rows = rows_of(data)
    # operating case identical, credit-sizing evidence differs
    assert rows["total_revenue"]["deltas"][1]["v"] == pytest.approx(0.0, abs=1e-9)
    assert rows["total_ebitda"]["deltas"][1]["v"] == pytest.approx(0.0, abs=1e-9)
    assert rows["dscr_capacity"]["cells"][0]["v"] != rows["dscr_capacity"]["cells"][1]["v"]
    assert rows["dscr_capacity"]["deltas"][1]["v"] is not None and rows["dscr_capacity"]["deltas"][1]["v"] != 0
    # the statement CFADS line is after tax and reserve movements, so it may differ with the financing; only operating revenue and EBITDA are pinned


# ── DSCR below 1 with CONVERGED solver; unavailable equity IRR -------------------------------------------------------------
@pytest.mark.parametrize("kind,gearing", [("solar", 90), ("wind", 95)])
def test_converged_solver_with_dscr_below_one_is_reported_as_failure_of_feasibility(cenv, kind, gearing):
    record = cenv.create(kind)
    assert "field-error-banner" not in save(cenv, record, config(sizing_mode="gearing_cap")).text
    set_field(cenv, record, "debt.senior.gearing_pct", gearing)
    run(cenv, record)
    _, data = credit(cenv, record)
    cap = data["runs"][0]["capacity"]
    assert cap["convergence"]["termination_reason"]["v"] == "CONVERGED" and cap["min_dscr"]["v"] < 1.0
    f = finding(data, 0, "CD-F2")
    assert f["status"] == "FAIL" and f["classification"] == "OBSERVED_FINANCIAL_RESULT" and "CONVERGED" in f["title"]
    assert f["headroom"]["v"] < 0 and "not a lender covenant" in f["threshold_authority"]
    assert data["runs"][0]["structure"]["sizing_mode"]["value"]["v"] == "gearing_cap"
    assert "no feasibility check" in data["runs"][0]["structure"]["sizing_mode"]["note"]
    assert finding(data, 0, "CD-SHORTFALL")["actual"]["v"] >= 1
    # severity is that of the existing QM-SD-007 rule, never invented here
    assert f["severity"] == finding(data, 0, "QM-SD-007")["severity"]
    # fixed-debt stress publishes no equity IRR (WF-A F-5): unavailable, never zero
    if last(record).runtime_summary.get("equity_irr") is None:
        f5 = finding(data, 0, "CD-F5")
        assert f5["classification"] == "UNSUPPORTED_EVIDENCE_MISSING" and f5["actual"]["d"] == "UNAVAILABLE"


# ── DSRA / DSRF differences ---------------------------------------------------------------------------------------------------
def test_dsra_and_dsrf_differences_across_three_committed_runs(cenv):
    record = cenv.create("solar")

    def reserve(mode, req=0, commit=0, fee=0):
        return config(reserve=dict(mode=mode, months=0, requirement_keur=req, commitment_keur=commit, fee_pct=fee))
    ids = []
    for payload_ in (reserve("none"), reserve("cash_fixed", 500), reserve("dsrf", 500, 500, 0.75)):
        assert "field-error-banner" not in save(cenv, record, payload_).text
        run(cenv, record)
        ids.append(last(record).history_id)
    response, data = credit(cenv, record, *ids)
    assert [r["identity"]["state"] for r in data["runs"]] == ["HISTORICAL", "HISTORICAL", "LAST RUN · CURRENT"]
    initial = [r["structure"]["reserve"]["initial_dsra_funding"]["v"] for r in data["runs"]]
    assert initial[0] == 0 and initial[1] == 500 and initial[2] == 0
    regimes = [r["structure"]["reserve"]["regime"]["v"] for r in data["runs"]]
    assert regimes[:2] == [None, None] and regimes[2] == "DSRF"                       # bound only for the CURRENT Run
    assert "not cash funded" in data["runs"][2]["structure"]["reserve"]["dsrf_note"]
    rows = rows_of(data)
    assert rows["initial_dsra"]["deltas"][1]["v"] == pytest.approx(500.0) and rows["initial_dsra"]["deltas"][2]["v"] == pytest.approx(0.0)
    assert rows["total_uses"]["deltas"][1]["v"] > 0
    dsra_row = {r["key"]: r for r in data["runs"][1]["timeline"]["rows"]}["dsra_balance"]
    assert any(c["v"] and c["v"] > 0 for c in dsra_row["cells"])
    assert "Reserve instrument" in response.text


# ── inactive financing proposal -----------------------------------------------------------------------------------------------
def test_saved_but_inactive_financing_proposal_does_not_change_the_run_and_is_labelled_working_copy(cenv, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook import multisenior_config as f3
    from app.workbook.input_set import ProjectInputSet
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state
    monkeypatch.setattr(f3, "ACTIVATION_ENABLED", True)
    record = cenv.create("solar")
    ws = get_workspace_state(USER, record.project_id)
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    assert "field-error-banner" not in save(cenv, record, state(active=False, collection=collection_for_inputs(pi)), field=f3.FIELD_ID).text
    run(cenv, record)
    response, data = credit(cenv, record)
    assert data["runs"][0]["structure"]["authority"] == "AGGREGATE_SINGLE_SENIOR" and data["runs"][0]["structure"]["facilities"] == []
    proposal = data["working_proposal"]
    assert proposal["available"] and proposal["has_saved_proposal"] and proposal["saved_only"] and not proposal["active_in_working_copy"]
    assert "not committed evidence" in response.text and "saved only" in response.text


# ── revenue downside and F-3 -------------------------------------------------------------------------------------------------------
def test_revenue_downside_compares_committed_runs_and_f3_is_listed_only_when_debt_rises(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    base = last(record)
    set_field(cenv, record, "revenue.ppa.base_tariff", 38)
    run(cenv, record)
    down = last(record)
    assert down.history_id != base.history_id
    _, data = credit(cenv, record, base.history_id, down.history_id)
    rows = rows_of(data)
    assert rows["total_revenue"]["deltas"][1]["v"] < 0 and rows["cfads_total"]["deltas"][1]["v"] < 0
    entry_cfads = sum(r["fcf_banks_keur"] for r in down.financial_statements["pf_cash_waterfall"]["periods"])
    assert rows["cfads_total"]["cells"][1]["v"] == pytest.approx(entry_cfads)
    assert rows["total_revenue"]["cells"][0]["v"] == base.runtime_summary["total_revenue_keur"]
    assert rows["total_revenue"]["cells"][1]["v"] == down.runtime_summary["total_revenue_keur"]
    commitment = rows["final_commitment"]["deltas"][1]["v"]
    both_gearing = all(r["capacity"]["binding_constraint"]["v"] == "GEARING" for r in data["runs"])
    f3 = data["comparison"]["f3"]
    if commitment is not None and commitment > 1e-6:
        assert len(f3) == 1 and f3[0]["attribution"] == ("COMMITTED_USES_LINES" if both_gearing else "UNAVAILABLE")
    else:
        assert f3 == []
    assert rows["total_uses"]["cells"][0]["v"] == base.runtime_summary["financing_evidence"]["sources_uses"]["total_uses_keur"]


# ── failed stress Run is never a scenario ----------------------------------------------------------------------------------------------
def test_failed_run_attempt_is_never_committed_and_cannot_appear_as_a_scenario(cenv):
    from app.persistence.workspace_repository import get_workspace_state
    record = cenv.create("solar")
    run(cenv, record)
    ok = last(record)
    count = len(history(record))
    set_field(cenv, record, "revenue.ppa.base_tariff", 1)
    page = cenv.client.get("/v2/workbook", params={"project": record.project_code})
    response = cenv.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={"project": record.project_code, **tokens(page.text)})
    assert response.status_code == 200
    if len(history(record)) != count:
        pytest.skip("this input did not fail closed; the failure contract is covered by the synthetic integrity test")
    ws = get_workspace_state(USER, record.project_id)
    assert ws.dirty and last(record).history_id == ok.history_id
    response, data = credit(cenv, record)
    assert [r["identity"]["history_id"] for r in data["runs"]] == [ok.history_id]
    assert data["runs"][0]["identity"]["state"] == "LAST RUN · STALE"
    assert "never committed" in response.text


# ── scenarios and Run History immutability ------------------------------------------------------------------------------------------------
def test_multiple_scenarios_keep_their_own_run_identities_and_history_is_immutable(cenv):
    from app.persistence.scenarios_repository import list_scenarios
    record = cenv.create("solar")
    run(cenv, record)
    base = last(record)
    created = cenv.client.post("/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "scenario_name": "Revenue downside"})
    assert created.status_code == 200
    scenario = next(s for s in list_scenarios(user_id=USER, project_id=record.project_id) if s.scenario_name == "Revenue downside")
    over = cenv.client.post("/v2/workbook/scenarios/update-overrides", headers={"HX-Request": "true"},
                            data={"project": record.project_code, "scenario_id": scenario.scenario_id, "tariff_eur_mwh": "40"})
    assert over.status_code == 200
    run(cenv, record)
    down = last(record)
    assert down.last_runtime_scenario_id == scenario.scenario_id and base.last_runtime_scenario_id is None
    frozen = [json.dumps(asdict(e), sort_keys=True, default=str) for e in history(record)]
    _, data = credit(cenv, record, base.history_id, down.history_id)
    names = [r["identity"]["scenario"] for r in data["runs"]]
    assert names[0].startswith("Base Case") and names[1] == "Revenue downside"
    assert data["runs"][0]["identity"]["scenario_id"] is None and data["runs"][1]["identity"]["scenario_id"] == scenario.scenario_id
    assert data["runs"][0]["identity"]["composite_hash"] != data["runs"][1]["identity"]["composite_hash"]
    assert rows_of(data)["total_revenue"]["deltas"][1]["v"] != 0
    # viewing, and a later Run, never rewrite earlier Run History entries
    assert [json.dumps(asdict(e), sort_keys=True, default=str) for e in history(record)] == frozen
    run(cenv, record)
    later = [json.dumps(asdict(e), sort_keys=True, default=str) for e in history(record)]
    assert all(item in later for item in frozen) and len(later) == len(frozen) + 1
