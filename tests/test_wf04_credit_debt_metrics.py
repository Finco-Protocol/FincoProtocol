"""WF-04: Event-of-Default threshold, contractual covenant and coverage conclusions over REAL committed Runs.

The weak-coverage project is the seeded Wind working copy at 85 % gearing under the GEARING_CAP sizing mode: the Run commits (the engine
completes) with a raw minimum DSCR of 0.9925… (below 1.00x).  Threshold values in the tests are derived from that measured value, so no
canonical contractual number is invented.  Everything is read through the real credit-decision route.
"""
import dataclasses
import json
import math
import re

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import config, run, save

USER = "decision-user"
EOD = "debt.contract.min_dscr_eod"
COV = "debt.contract.contractual_dscr"


@pytest.fixture
def cenv(env):  # noqa: F811
    from app.v2.credit_decision_router import router
    env.client.app.include_router(router, prefix="/v2")
    return env


def update(env, record, field_id, value):
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    response = post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                                   data={"project": record.project_code, "field_id": field_id, "value": str(value), **tokens(page)})
    assert response.status_code == 200 and "field-error" not in response.text[:4000], response.text[:500]


def weak_wind(cenv):
    """Seeded Wind at 85 % gearing under GEARING_CAP: a committed Run with DSCR below 1.00x is possible (the engine completes)."""
    record = cenv.create("wind")
    update(cenv, record, "debt.senior.gearing_pct", 85)
    assert save(cenv, record, config(sizing_mode="gearing_cap")).status_code == 200
    return record


def history(record):
    from app.persistence.run_history_repository import get_run_history
    return list(get_run_history(USER, record.project_id))


def raw_min(entry):
    rows = entry.integrity_evidence["senior_debt"]["periods"]
    return min(p["reported_dscr"] for p in rows if p["debt_service"] > 1e-6 and p["reported_dscr"] is not None)


def credit(cenv, record, *run_ids):
    params = [("project", record.project_code)] + [("run", r) for r in run_ids]
    response = cenv.client.get("/v2/credit-decision", params=params)
    assert response.status_code == 200, response.text[:400]
    match = re.search(r'<script type="application/json" data-cd-payload>(.*?)</script>', response.text, re.S)
    assert match, response.text[:400]
    return json.loads(match.group(1))


def finding(data, run_index, fid):
    run_id = data["runs"][run_index]["identity"]["history_id"]
    rows = [f for f in data["findings"] if f["run_history_id"] == run_id and (f["check_id"] == fid or f["id"].endswith(":" + fid))]
    assert rows, (fid, [f["id"] for f in data["findings"] if f["run_history_id"] == run_id])
    return rows[0]


def view_of(data, run_index=0):
    return data["runs"][run_index]["debt_metrics"]


# ── the Owner's acceptance cases ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_owner_example_floor_above_actual_triggers_eod_on_a_completed_run_without_payment_default_claims(cenv):
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    assert len(history(record)) == 1                                   # exactly one persisted, completed Run
    data = credit(cenv, record)
    assert data["runs"][0]["identity"]["state"] == "LAST RUN · CURRENT"
    eod = finding(data, 0, "CD-EOD")
    assert eod["status"] == "TRIGGERED" and eod["severity"] == "HIGH" and eod["classification"] == "CONTRACTUAL_COVENANT"
    assert eod["threshold"]["v"] == 1.05 and eod["actual"]["v"] == pytest.approx(raw_min(history(record)[0]), abs=0)
    assert eod["period"] != "AGGREGATE" and "Event of Default: TRIGGERED — actual DSCR" in eod["detail"] and "below configured Minimum DSCR 1.05x" in eod["detail"]
    assert "not a legally declared default" in eod["detail"] and "payment default" not in eod["detail"].replace("missed payment", "")
    # coverage < 1.00x is a separate, independent conclusion; neither unprofitability nor default is asserted
    assert finding(data, 0, "CD-F2")["reason_code"] == "DSCR_BELOW_ONE"
    from app.workbook.dscr_contract_terms import MESSAGE_EOD_NOTE
    scan = {k: v for k, v in view_of(data).items() if k != "integrity"}      # the Integrity block carries existing check ids verbatim
    text = (json.dumps(scan).replace(MESSAGE_EOD_NOTE, "")                    # the required disclosures are negations; scan everything else
            .replace("a deficiency is not by itself a payment default", ""))
    assert not any(b in text.lower() for b in ("unprofitable", "feasible", "bankable", "payment default", "defaulted", "acceleration"))
    assert view_of(data)["evaluation"]["coverage"]["status"] == "DEFICIENCY"


def test_equality_is_not_a_trigger_and_one_ulp_below_is(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    m = raw_min(history(record)[0])
    assert m < 1.0
    update(cenv, record, EOD, repr(m))                                  # the exact raw double, as text
    run(cenv, record)
    equal = credit(cenv, record)
    assert view_of(equal)["evaluation"]["eod"]["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
    assert finding(equal, 0, "CD-EOD")["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
    update(cenv, record, EOD, repr(math.nextafter(m, 2.0)))              # the floor is one ulp above the actual minimum
    run(cenv, record)
    tight = credit(cenv, record)
    assert view_of(tight)["evaluation"]["eod"]["status"] == "TRIGGERED"
    shown = finding(tight, 0, "CD-EOD")
    assert shown["actual"]["d"] != shown["threshold"]["d"]               # the display cannot hide a one-ulp breach
    assert shown["actual"]["v"] == m


def test_covenant_breach_without_eod_and_the_two_terms_stay_independent(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    m = raw_min(history(record)[0])
    update(cenv, record, EOD, repr(m - 0.05))                           # floor below the actual minimum
    update(cenv, record, COV, repr(m + 0.10))                           # covenant above it
    run(cenv, record)
    data = credit(cenv, record)
    cov, eod = finding(data, 0, "CD-COV-DSCR"), finding(data, 0, "CD-EOD")
    assert cov["status"] == "BREACHED" and "covenant is not met" in cov["detail"] and cov["classification"] == "CONTRACTUAL_COVENANT"
    assert eod["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
    rows = {r["id"]: r for r in view_of(data)["covenant_table"]}
    assert rows["CONTRACTUAL_DSCR"]["status"] == "BREACHED" and rows["EOD_FLOOR"]["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
    assert rows["SIZING_TARGET"]["description"].startswith("Sizing assumption — NOT a contractual covenant")
    assert rows["CONTRACTUAL_DSCR"]["headroom"]["absolute"]["v"] == pytest.approx(-0.10)
    assert "QM-COV-001" not in {f["check_id"] for f in data["findings"]}  # superseded by the Run-bound finding, never a contradicting row


def test_no_terms_configured_is_not_configured_never_a_pass_and_qm_cov_001_stays_unavailable(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    data = credit(cenv, record)
    for fid, code in (("CD-EOD", "EOD_THRESHOLD_NOT_CONFIGURED"), ("CD-COV-DSCR", "CONTRACTUAL_DSCR_NOT_CONFIGURED")):
        f = finding(data, 0, fid)
        assert f["status"] == "NOT_CONFIGURED" and f["reason_code"] == code and f["classification"] == "UNSUPPORTED_EVIDENCE_MISSING"
    assert finding(data, 0, "QM-COV-001")["status"] == "UNAVAILABLE"
    assert view_of(data)["evaluation"]["eod"]["status"] == "NOT_CONFIGURED"


# ── immutability: a Run is judged by ITS terms, never by a later edit ─────────────────────────────────────────────────────────────────
def test_historical_runs_keep_their_own_terms_across_edits_stale_state_and_compare(cenv):
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    first = history(record)[0].history_id
    update(cenv, record, EOD, "0.5")                                    # a Working Copy edit after the Run …
    stale = credit(cenv, record, first)
    assert stale["runs"][0]["identity"]["state"] == "LAST RUN · STALE"
    assert finding(stale, 0, "CD-EOD")["status"] == "TRIGGERED"          # … does not touch the saved Run's verdict
    assert len(history(record)) == 1                                    # and Save committed nothing
    run(cenv, record)
    entries = history(record)
    second = next(e.history_id for e in entries if e.history_id != first)
    data = credit(cenv, record, first, second)
    by_id = {r["identity"]["history_id"]: i for i, r in enumerate(data["runs"])}
    assert finding(data, by_id[first], "CD-EOD")["status"] == "TRIGGERED"
    assert finding(data, by_id[second], "CD-EOD")["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
    assert data["runs"][by_id[first]]["identity"]["state"] == "HISTORICAL"


def test_a_run_committed_before_the_contract_is_not_recorded_never_judged_by_todays_working_copy(cenv):
    from app.v2.credit_decision_projection import HISTORICAL, RunInput, build_credit_decision
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    entry = history(record)[0]
    identity = {k: v for k, v in entry.last_runtime_identity.items() if k != "dscr_contract_terms"}      # a pre-WF-04 Run
    old = dataclasses.replace(entry, last_runtime_identity=identity)
    data = build_credit_decision([RunInput(entry=old, state=HISTORICAL)], project_code=record.project_code)
    f = finding(data, 0, "CD-EOD")
    assert f["status"] == "UNAVAILABLE" and f["reason_code"] == "NOT_RECORDED" and f["classification"] == "UNSUPPORTED_EVIDENCE_MISSING"
    assert data["runs"][0]["debt_metrics"]["contract_terms"]["recorded"] is False
    assert finding(data, 0, "CD-F2")["reason_code"] == "DSCR_BELOW_ONE"      # coverage needs no terms


def test_tampered_or_missing_evidence_withholds_every_verdict(cenv):
    from app.v2.debt_metrics_projection import build_debt_metrics
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    entry = history(record)[0]
    forged = json.loads(json.dumps(entry.integrity_evidence))
    forged["senior_debt"]["periods"][5]["reported_dscr"] = 5.0           # a forged ratio would otherwise hide the breach
    out = build_debt_metrics(dataclasses.replace(entry, integrity_evidence=forged))
    assert out["evaluation"]["eod"]["status"] == "UNAVAILABLE" and out["evaluation"]["eod"]["reason"].startswith("EVIDENCE_NOT_VERIFIED")
    assert out["evaluation"]["coverage"]["status"] == "UNAVAILABLE" and out["available"] is False
    gone = build_debt_metrics(dataclasses.replace(entry, integrity_evidence={}))
    assert gone["evaluation"]["eod"]["status"] == "UNAVAILABLE" and gone["covenant_table"] == [] and gone["periods"] == []


# ── what is plotted / listed is exactly what the Run persisted ────────────────────────────────────────────────────────────────────────
def test_series_and_schedule_carry_only_persisted_values_and_never_fabricate_a_series(cenv):
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    update(cenv, record, COV, "1.2")
    run(cenv, record)
    entry = history(record)[0]
    view = view_of(credit(cenv, record))
    evidence = {p["period_index"]: p for p in entry.integrity_evidence["senior_debt"]["periods"]}
    serviced = [p for p in view["periods"] if p["has_debt_service"]]
    assert serviced and {p["period_index"] for p in serviced} <= set(evidence)
    for p in serviced:
        assert p["dscr"] == evidence[p["period_index"]]["reported_dscr"]                        # raw, not the 2-decimal schedule value
        assert p["date"] and p["debt_service_keur"] == evidence[p["period_index"]]["debt_service"]
        assert p["below_one"] == (p["dscr"] < 1.0) and p["eod_breach"] == (p["dscr"] < 1.05) and p["covenant_breach"] == (p["dscr"] < 1.2)
    for p in view["periods"]:
        if not p["has_debt_service"]:
            assert p["dscr"] is None and p["bank_dscr"] is None and p["below_one"] is None      # no 0x after final service, no terminal zero
    assert view["series"]["llcr"]["available"] is False and "per-period LLCR series" in view["series"]["llcr"]["reason"]
    assert view["axis"]["frequency"] == "SEMIANNUAL" and view["axis"]["period_count"] == len(view["periods"])
    assert view["kpis"]["achieved_min_dscr"]["value"] == raw_min(entry)
    assert entry.runtime_summary["min_dscr"] == raw_min(entry)                    # the persisted summary minimum is the same raw value
    assert view["kpis"]["llcr"]["available"] is False and view["kpis"]["plcr"]["available"] is False
    rows = {r["key"]: r for g in view["schedule"] for r in g["rows"]}
    assert rows["eod_breach"]["available"] and rows["covenant_breach"]["available"] and rows["dsra_balance_keur"]["unit"] == "kEUR"
    assert [r["id"] for r in view["covenant_table"]] == ["EOD_FLOOR", "CONTRACTUAL_DSCR", "COVERAGE_1X", "LOCKUP", "SIZING_TARGET", "LLCR"]
    reserves = view["reserves"]
    assert reserves["dsrf"]["available"] is False and "not a DSRF commitment" in reserves["dsrf"]["reason"]


def test_reference_inputs_never_leak_into_the_payload(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    text = json.dumps(credit(cenv, record)["runs"][0]["debt_metrics"])
    for forbidden in ("PRIVATE_REFERENCE", "Default DSCR", "xlsm", "workbook"):
        assert forbidden not in text


def test_terms_do_not_change_any_financial_result_between_runs_of_the_same_inputs(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    update(cenv, record, EOD, "1.05")
    update(cenv, record, COV, "1.2")
    run(cenv, record)
    new, old = history(record)[0], history(record)[-1]
    assert new.history_id != old.history_id
    assert new.integrity_evidence["digest"] == old.integrity_evidence["digest"]
    for name in ("debt_schedule", "tax_schedule", "distribution_schedule", "financial_statements"):
        assert getattr(new, name) == getattr(old, name), name
    assert new.runtime_summary["min_dscr"] == old.runtime_summary["min_dscr"]


def test_reserve_draw_and_unpaid_service_stay_unavailable_and_name_the_exact_missing_evidence(cenv):
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    gaps = {g["id"]: g for g in view_of(credit(cenv, record))["reserves"]["unavailable_conclusions"]}
    assert set(gaps) == {"RESERVE_DRAW", "UNPAID_DEBT_SERVICE"}
    assert all(g["status"] == "UNAVAILABLE" and g["missing"] for g in gaps.values())
    assert any("DSRA draw" in m for m in gaps["RESERVE_DRAW"]["missing"])
    assert any("actually paid" in m for m in gaps["UNPAID_DEBT_SERVICE"]["missing"])
    # the DSCR shortfall never fills those gaps: no value, no pass
    text = json.dumps(gaps).lower()
    assert "pass" not in text and "paid in full" not in text and "covered" not in text.replace("covering a shortfall", "")


def test_the_projection_is_a_pure_function_of_the_sealed_run_and_presentation_precision_cannot_change_a_verdict_or_a_hash(cenv):
    """Display precision 0 -> 2 -> 0 lives only in the browser; the server payload carries raw values and is byte-identical on every read."""
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    entry = history(record)[0]
    digest, snapshot = entry.integrity_evidence["digest"], json.dumps(entry.last_runtime_identity, sort_keys=True)
    first = json.dumps(credit(cenv, record)["runs"][0]["debt_metrics"], sort_keys=True)
    for _ in range(2):
        assert json.dumps(credit(cenv, record)["runs"][0]["debt_metrics"], sort_keys=True) == first
    reread = history(record)[0]
    assert reread.integrity_evidence["digest"] == digest and json.dumps(reread.last_runtime_identity, sort_keys=True) == snapshot
    ev = json.loads(first)["evaluation"]
    assert ev["eod"]["status"] == "TRIGGERED" and ev["achieved_min_dscr"]["min"] == raw_min(reread)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_the_contract_is_recorded_and_projected_for_every_technology(cenv, kind):
    record = cenv.create(kind)
    update(cenv, record, EOD, "1.05")
    update(cenv, record, COV, "1.2")
    run(cenv, record)
    entries = history(record)
    assert len(entries) == 1
    from app.workbook.dscr_contract_terms import read_run_terms
    terms = read_run_terms(entries[0].last_runtime_identity)
    assert terms.recorded and (terms.eod.value, terms.contractual.value) == (1.05, 1.2)
    view = view_of(credit(cenv, record))
    assert view["available"] and view["contract_terms"]["recorded"]
    statuses = {view["evaluation"]["eod"]["status"], view["evaluation"]["covenant"]["status"]}
    assert statuses <= {"TRIGGERED", "NOT_TRIGGERED_UNDER_THIS_FLOOR", "BREACHED", "COMPLIANT", "UNAVAILABLE", "NOT_APPLICABLE"}
    assert view["evaluation"]["eod"]["status"] != "NOT_CONFIGURED" and view["evaluation"]["covenant"]["status"] != "NOT_CONFIGURED"
    assert view["integrity"]["status"] in {"PASS", "FAIL", "INCOMPLETE", "UNAVAILABLE"}


def test_a_stranger_and_another_projects_run_never_see_or_are_judged_by_foreign_terms(cenv):
    from app.auth import COOKIE_NAME, create_session_token
    a = weak_wind(cenv)
    update(cenv, a, EOD, "1.05")
    update(cenv, a, COV, "1.2")
    run(cenv, a)
    b = cenv.create("solar")
    run(cenv, b)
    a_run = history(a)[0].history_id
    # another project of the same owner: its Run is judged by ITS OWN (absent) terms, and A's Run id is not addressable through B
    own = view_of(credit(cenv, b))
    assert own["contract_terms"]["eod_minimum_dscr"]["status"] == "NOT_CONFIGURED" and own["evaluation"]["eod"]["status"] == "NOT_CONFIGURED"
    foreign = cenv.client.get("/v2/credit-decision", params=[("project", b.project_code), ("run", a_run)])
    assert foreign.status_code in (404, 422) or a_run not in foreign.text
    # a stranger gets nothing of A: no payload, no term text
    cenv.client.cookies.set(COOKIE_NAME, create_session_token(user_id="stranger-user", username="admin"))
    denied = cenv.client.get("/v2/credit-decision", params={"project": a.project_code})
    assert denied.status_code in (403, 404) and "data-cd-payload" not in denied.text and "1.05" not in denied.text
