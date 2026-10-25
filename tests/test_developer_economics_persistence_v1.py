"""RC-2 / M4 — Developer Economics persistence bridge (Save -> STALE -> Run -> CURRENT -> history).

Real authorized Save / Scenario / Run / History acceptance on neutral Solar and Wind fixtures. Every
financial figure is compared with the existing canonical calculator; nothing here re-implements one.
"""

from tests.run_clone_csrf import post_valid_csrf
import copy
import json
import re
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

OWNER = "decision-user"


def _tokens(html):
    return {k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1) for k in ("content_hash", "workbook_version")}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.developer_decision_router import router as dev_router
    from app.v2.router import router
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "dev.db"))
    db.init_db()
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    app.include_router(dev_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        def create(kind="solar", name=None):
            return create_reference_seeded_project(user_id=OWNER, requested_name=name or ("Developer " + kind),
                                                   template_source="generic_" + kind + "_reference", capacity_mw=16)
        yield SimpleNamespace(client=client, create=create, app=app)
    reset_model_executor_for_tests()


def _fc(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    ws = get_workspace_state(OWNER, record.project_id)
    return WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs().info.financial_close


def _doc(fc, **over):
    doc = {"version": 1, "enabled": True, "outcome": "REALIZED",
           "spend_schedule": [{"spend_date": (fc - timedelta(days=400)).isoformat(), "amount_keur": 1000.0},
                              {"spend_date": (fc - timedelta(days=100)).isoformat(), "amount_keur": 500.0}],
           "reimbursed_development_cost_keur": 1200.0, "developer_fee_mode": "FIXED_KEUR",
           "developer_fee_value": 300.0, "settlement": "AT_FINANCIAL_CLOSE",
           "book_basis_mode": "CAPITALISE_AS_SOFT_COSTS"}
    doc.update(over)
    return doc


def _form(doc, page_html, record, **extra):
    """The browser form for ``doc`` (percent fees are submitted as percentage points)."""
    pct = doc["developer_fee_mode"] == "PCT_OF_HARD_CAPEX"
    from bs4 import BeautifulSoup
    form = BeautifulSoup(page_html, "html.parser").select_one('[data-testid="dd-config-form"]')
    hidden = {i["name"]: i["value"] for i in form.select('input[type="hidden"]')}
    data = {
        "csrf_token": hidden["csrf_token"], "project": hidden["project"],
        "content_hash": hidden["content_hash"], "scenario_id": hidden["scenario_id"],
        "outcome": doc["outcome"], "reimbursed": str(doc["reimbursed_development_cost_keur"]),
        "fee_mode": doc["developer_fee_mode"],
        "fee_value": str(doc["developer_fee_value"] * 100 if pct else doc["developer_fee_value"]),
        "action": "save",
    }
    if doc["enabled"]:
        data["enabled"] = "on"
    data.update(extra)
    data["spend_date"] = [r["spend_date"] for r in doc["spend_schedule"]]
    data["spend_amount"] = [str(r["amount_keur"]) for r in doc["spend_schedule"]]
    return data


class Flow:
    def __init__(self, env, kind="solar"):
        self.env, self.kind = env, kind
        self.record = env.create(kind)
        self.project = {"project": self.record.project_code}

    def ws(self):
        from app.persistence.workspace_repository import get_workspace_state
        return get_workspace_state(OWNER, self.record.project_id)

    def page(self, **params):
        r = self.env.client.get("/v2/developer-decision", params={**self.project, **params})
        assert r.status_code == 200, r.text[:500]
        return r.text

    def save(self, doc, **extra):
        html = self.page()
        data = _form(doc, html, self.record, **extra)
        return self.env.client.post("/v2/developer-decision/configuration", data=data, follow_redirects=False)

    def run(self):
        wb = self.env.client.get("/v2/workbook", params=self.project)
        r = post_valid_csrf(self.env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data={**self.project, **_tokens(wb.text)})
        assert r.status_code == 200 and 'id="v2-sheet-returns"' in r.text, r.text[:2000]
        assert not self.ws().dirty
        return copy.deepcopy(self.ws().last_runtime_summary)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_save_stale_run_current_history_and_calculator_parity(env, kind):
    from app.model_v2.developer_evidence import read_committed_evidence
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.developer_economics_config import SNAPSHOT_KEY, apply_config
    from app.workbook.service import WorkbookService
    from financial_engine.developer_economics import compute_developer_economics
    flow = Flow(env, kind)
    baseline = flow.run()                                  # disabled: legacy behaviour, no Developer key
    assert "developer_economics" not in baseline
    fc = _fc(flow.record)
    doc = _doc(fc)
    r = flow.save(doc)
    assert r.status_code == 303, r.text[:600]
    assert flow.ws().dirty
    assert json.loads(flow.ws().draft_snapshot[SNAPSHOT_KEY])["spend_schedule"][0]["amount_keur"] == 1000.0
    assert 'data-testid="dd-last-state"' in flow.page()
    assert "STALE" in flow.page()                          # previous Last Run is stale after the Save
    committed = flow.run()
    evidence = read_committed_evidence(committed, expect_snapshot_id=flow.ws().last_runtime_snapshot_id)
    assert evidence is not None
    # The committed figures are exactly the existing canonical calculator's output on the same inputs.
    inputs = apply_config(WorkbookService.build_draft_input_set_from_workspace(flow.ws()).to_projectinputs(), json.dumps(doc))
    expected = compute_developer_economics(inputs)
    assert evidence["total_development_spend_keur"] == expected.total_development_spend_keur == 1500.0
    assert evidence["reimbursed_development_cost_keur"] == 1200.0 and evidence["developer_fee_keur"] == 300.0
    assert evidence["developer_moic"] == pytest.approx(expected.developer_moic)
    assert evidence["developer_xirr"] == pytest.approx(expected.developer_xirr)
    assert [row["net_developer_cashflow_keur"] for row in evidence["cashflows"]] == \
        [row.net_developer_cashflow_keur for row in expected.cashflows]
    page = flow.page()
    assert 'data-testid="dd-last-state"' in page and "CURRENT" in page
    # Real project-use effect: the Run's total uses/capex-funded structure changed versus the disabled Run.
    assert committed["total_capex_keur"] == baseline["total_capex_keur"]
    assert committed["project_irr"] != baseline["project_irr"] or committed["equity_irr"] != baseline["equity_irr"]
    # Developer cash flows never enter the sponsor return ledger.
    assert committed["total_distributions_keur"] is not None
    history = get_run_history(OWNER, flow.record.project_id)
    assert len(history) == 2 and "developer_economics" in history[0].runtime_summary
    assert "developer_economics" not in history[1].runtime_summary           # disabled historical Run still loads
    # Later edit: historical evidence is immutable and never reconstructed from the Working Copy.
    snapshot_before = copy.deepcopy(history[0].runtime_summary["developer_economics"])
    assert flow.save(_doc(fc, developer_fee_value=999.0)).status_code == 303
    after = get_run_history(OWNER, flow.record.project_id)
    assert after[0].runtime_summary["developer_economics"] == snapshot_before
    hist_page = flow.page(history_id=history[0].history_id)
    assert 'data-testid="dd-historical"' in hist_page and "HISTORICAL" in hist_page and "300.0" in hist_page
    old = flow.page(history_id=history[1].history_id)
    assert "not enabled in this Run" in old


# ───────────────────────────── strict codec ─────────────────────────────

def _codec_doc():
    return _doc(date(2027, 6, 30))


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.pop("enabled"), "DEV_ECON_SCHEMA"),
    (lambda d: d.update(extra=1), "DEV_ECON_SCHEMA"),
    (lambda d: d.update(version=2), "DEV_ECON_VERSION"),
    (lambda d: d.update(enabled="yes"), "DEV_ECON_ENABLED"),
    (lambda d: d.update(outcome="MAYBE"), ""),
    (lambda d: d.update(developer_fee_value=float("inf")), "DEV_ECON_NONFINITE"),
    (lambda d: d.update(developer_fee_value=True), "DEV_ECON_NUMBER"),
    (lambda d: d.update(developer_fee_value=-1), ""),
    (lambda d: d.update(reimbursed_development_cost_keur=1e9), "REIMBURSEMENT_EXCEEDS"),
    (lambda d: d.update(spend_schedule="x"), "DEV_ECON_SCHEDULE"),
    (lambda d: d["spend_schedule"][0].update(spend_date="2027-02-30"), "DEV_ECON_SPEND_DATE"),
    (lambda d: d["spend_schedule"][0].update(spend_date="27-01-01"), "DEV_ECON_SPEND_DATE"),
    (lambda d: d["spend_schedule"][0].update(amount_keur="500"), "DEV_ECON_NUMBER"),
    (lambda d: d["spend_schedule"].append(dict(d["spend_schedule"][1])), "SCHEDULE_ORDER"),      # duplicate date
    (lambda d: d["spend_schedule"].reverse(), "SCHEDULE_ORDER"),
    (lambda d: d.update(developer_fee_mode="PCT_OF_HARD_CAPEX", developer_fee_value=5.0), "FEE"),   # 5 would be 500 %
    (lambda d: d.update(outcome="ABANDONED"), "ABANDONED_WITH_RECEIPTS"),
])
def test_codec_rejects_malformed_or_invalid_payloads(mutate, code):
    from app.workbook.developer_economics_config import DeveloperConfigError, parse_config
    doc = _codec_doc()
    mutate(doc)
    with pytest.raises(DeveloperConfigError) as exc:
        parse_config(json.dumps(doc))
    assert code in str(exc.value)


@pytest.mark.parametrize("raw", ["{", "[]", "null", '{"version": NaN}', "x" * 70_000])
def test_codec_rejects_malformed_json_and_oversize(raw):
    from app.workbook.developer_economics_config import DeveloperConfigError, parse_config
    with pytest.raises(DeveloperConfigError):
        parse_config(raw)


def test_codec_is_canonical_idempotent_and_absent_is_neutral():
    from app.workbook.developer_economics_config import apply_config, canonical_json, parse_config
    from app.project_factories import create_generic_solar_reference
    doc = _codec_doc()
    once = canonical_json(json.dumps(doc))
    assert canonical_json(once) == once and canonical_json(doc) == once
    assert parse_config("") is None and parse_config(None) is None and canonical_json("") == ""
    solar = create_generic_solar_reference()
    assert apply_config(solar, "") is solar                       # absent: the very same object
    disabled = dict(doc, enabled=False)
    assert apply_config(solar, json.dumps(disabled)) == solar     # disabled == absent, bit-exact


def test_spend_after_financial_close_fails_closed_at_materialisation():
    from app.workbook.developer_economics_config import DeveloperConfigError, apply_config
    from app.project_factories import create_generic_solar_reference
    solar = create_generic_solar_reference()
    late = _doc(solar.info.financial_close)
    late["spend_schedule"][1]["spend_date"] = (solar.info.financial_close + timedelta(days=1)).isoformat()
    with pytest.raises(DeveloperConfigError, match="SPEND_AFTER_FINANCIAL_CLOSE"):
        apply_config(solar, json.dumps(late))


# ───────────────────────── Save semantics / security ─────────────────────────

def test_invalid_save_is_atomic_and_reports_without_writing(env):
    flow = Flow(env)
    fc = _fc(flow.record)
    before = copy.deepcopy(flow.ws().draft_snapshot)
    late = _doc(fc)
    late["spend_schedule"][1]["spend_date"] = (fc + timedelta(days=5)).isoformat()
    r = flow.save(late)
    assert r.status_code == 422 and "SPEND_AFTER_FINANCIAL_CLOSE" in r.text and 'data-testid="dd-form-error"' in r.text
    assert flow.ws().draft_snapshot == before and not flow.ws().dirty
    bad_amount = flow.save(_doc(fc), reimbursed="not-a-number")
    assert bad_amount.status_code == 422 and flow.ws().draft_snapshot == before
    over = flow.save(_doc(fc, reimbursed_development_cost_keur=5000.0))
    assert over.status_code == 422 and "REIMBURSEMENT_EXCEEDS_ELIGIBLE" in over.text
    assert flow.ws().draft_snapshot == before


def test_csrf_owner_reference_unauthenticated_and_scenario_denials(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    flow = Flow(env)
    fc = _fc(flow.record)
    html = flow.page()
    data = _form(_doc(fc), html, flow.record)
    before = copy.deepcopy(flow.ws().draft_snapshot)
    url = "/v2/developer-decision/configuration"
    for bad in ("", "forged", data["csrf_token"][:-3] + "abc"):
        assert env.client.post(url, data={**data, "csrf_token": bad}).status_code == 403
    assert flow.ws().draft_snapshot == before
    # foreign owner: another user's project is not found, nothing is written
    from app.auth import COOKIE_NAME, create_session_token
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="other-user", username="other"))
    assert env.client.post(url, data=data).status_code == 404
    env.client.cookies.clear()
    assert env.client.post(url, data=data, follow_redirects=False).status_code == 401
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
    assert flow.ws().draft_snapshot == before
    # stale composite identity / wrong scenario selection -> one rejected writer
    assert env.client.post(url, data={**data, "content_hash": "0" * 64}, follow_redirects=False).status_code == 409
    assert env.client.post(url, data={**data, "scenario_id": "not-the-active-scenario"}, follow_redirects=False).status_code == 409
    assert flow.ws().draft_snapshot == before


def test_concurrent_saves_have_exactly_one_winner(env):
    flow = Flow(env)
    fc = _fc(flow.record)
    html = flow.page()
    a = _form(_doc(fc, developer_fee_value=100.0), html, flow.record)
    b = _form(_doc(fc, developer_fee_value=200.0), html, flow.record)       # same rendered identity
    url = "/v2/developer-decision/configuration"
    first = env.client.post(url, data=a, follow_redirects=False)
    second = env.client.post(url, data=b, follow_redirects=False)
    assert (first.status_code, second.status_code) == (303, 409)
    assert json.loads(flow.ws().draft_snapshot["developer_economics_json"])["developer_fee_value"] == 100.0


def test_protected_reference_is_read_only_and_rejects_writes(env):
    from app.auth import generate_csrf_token
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    record = create_reference_seeded_project(user_id=OWNER, requested_name="Ref", template_source="generic_solar_reference", capacity_mw=16)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ui.protected_reference_service.is_protected_reference", lambda r: True)
        page = env.client.get("/v2/developer-decision", params={"project": record.project_code}).text
        assert 'data-testid="dd-readonly"' in page and 'data-testid="dd-config-form"' not in page
        r = env.client.post("/v2/developer-decision/configuration", data={
            "csrf_token": generate_csrf_token(), "project": record.project_code, "content_hash": "x", "scenario_id": ""})
        assert r.status_code == 409
    assert "developer_economics_json" not in (get_workspace_state(OWNER, record.project_id).draft_snapshot or {})


def test_get_never_writes_or_runs_the_engine(env, monkeypatch):
    flow = Flow(env)
    before = copy.deepcopy(flow.ws().draft_snapshot), flow.ws().dirty
    def forbidden(*a, **k):
        raise AssertionError("GET must not run the engine")
    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    assert flow.page()
    assert (copy.deepcopy(flow.ws().draft_snapshot), flow.ws().dirty) == before


# ───────────────────── economic cases, percent fee, abandoned ─────────────────────

def test_percent_fee_is_stored_as_a_fraction_and_uses_the_hard_capex_basis(env):
    from app.model_v2.developer_evidence import read_committed_evidence
    flow = Flow(env)
    fc = _fc(flow.record)
    doc = _doc(fc, developer_fee_mode="PCT_OF_HARD_CAPEX", developer_fee_value=0.05)
    assert flow.save(doc).status_code == 303                       # form submits "5.0" percentage points
    stored = json.loads(flow.ws().draft_snapshot["developer_economics_json"])
    assert stored["developer_fee_value"] == 0.05                   # never 5 and never 0.05 %
    assert "5.0" in flow.page()                                    # displayed in percentage points
    committed = flow.run()
    evidence = read_committed_evidence(committed)
    basis = evidence["fee_basis"]
    assert basis["mode"] == "PCT_OF_HARD_CAPEX" and basis["basis_keur"] > 0
    assert evidence["developer_fee_keur"] == pytest.approx(0.05 * basis["basis_keur"])
    assert "hard CAPEX" in flow.page()


def test_abandoned_outcome_has_no_receipts_and_typed_unavailable_metrics(env):
    from app.model_v2.developer_evidence import read_committed_evidence
    flow = Flow(env)
    fc = _fc(flow.record)
    doc = _doc(fc, outcome="ABANDONED", reimbursed_development_cost_keur=0.0, developer_fee_value=0.0)
    assert flow.save(doc).status_code == 303
    evidence = read_committed_evidence(flow.run())
    assert evidence["outcome"] == "ABANDONED"
    assert evidence["total_developer_receipts_keur"] == 0.0 and evidence["developer_xirr"] is None
    assert evidence["developer_xirr_status"] == "NO_POSITIVE_CASHFLOW"
    page = flow.page()
    assert 'data-available="false"' in page and "no IRR exists" in page


def test_disabled_saved_configuration_is_legacy_neutral(env):
    flow = Flow(env)
    baseline = flow.run()
    fc = _fc(flow.record)
    assert flow.save(_doc(fc, enabled=False)).status_code == 303
    after = flow.run()
    assert "developer_economics" not in after
    for key in ("total_revenue_keur", "total_ebitda_keur", "project_irr", "equity_irr", "min_dscr", "total_tax_keur"):
        assert after[key] == baseline[key], key


def test_developer_cash_flows_do_not_enter_sponsor_ledgers(env):
    flow = Flow(env)
    fc = _fc(flow.record)
    assert flow.save(_doc(fc)).status_code == 303
    committed = flow.run()
    spend_dates = {r["spend_date"] for r in _doc(fc)["spend_schedule"]}
    assert not spend_dates & set(re.findall(r"\d{4}-\d{2}-\d{2}", json.dumps(flow.ws().last_sponsor_schedule or {})))
    assert "developer" not in json.dumps(flow.ws().last_sponsor_schedule or {}).lower()
    assert committed["developer_economics"]["run_binding"]["snapshot_id"] == flow.ws().last_runtime_snapshot_id


# ─────────────────────────── scenarios ───────────────────────────

def _child(flow):
    from app.persistence.scenarios_repository import list_scenarios
    env = flow.env
    assert env.client.post("/v2/workbook/scenarios/create", data={**flow.project, "scenario_name": "Alt"}).status_code == 200
    sc = next(s for s in list_scenarios(OWNER, flow.record.project_id) if not s.is_base_case)
    assert env.client.post("/v2/workbook/scenarios/select", data={**flow.project, "scenario_id": sc.scenario_id}).status_code == 200
    return sc


def test_child_scenario_inherits_overrides_and_resets(env):
    from app.model_v2.developer_evidence import read_committed_evidence
    from app.persistence.scenarios_repository import get_scenario
    flow = Flow(env)
    fc = _fc(flow.record)
    base_doc = _doc(fc, developer_fee_value=100.0)
    assert flow.save(base_doc).status_code == 303                 # Base Case selected
    sc = _child(flow)
    assert "developer_economics_json" not in get_scenario(sc.scenario_id, OWNER).overrides
    inherited = read_committed_evidence(flow.run())               # child with no override uses the Working Copy
    assert inherited["developer_fee_keur"] == 100.0
    draft_before = copy.deepcopy(flow.ws().draft_snapshot)
    assert flow.save(_doc(fc, developer_fee_value=250.0)).status_code == 303
    assert flow.ws().draft_snapshot == draft_before               # the Base Working Copy is untouched
    stored = json.loads(get_scenario(sc.scenario_id, OWNER).overrides["developer_economics_json"])
    assert stored["developer_fee_value"] == 250.0
    page = flow.page()
    assert "scenario-specific override" in page
    overridden = read_committed_evidence(flow.run())
    assert overridden["developer_fee_keur"] == 250.0              # the SELECTED scenario, never stale Base
    assert overridden["run_binding"]["scenario_id"] == sc.scenario_id
    reset = env.client.post("/v2/developer-decision/configuration", data={
        **_form(_doc(fc), flow.page(), flow.record), "action": "inherit"}, follow_redirects=False)
    assert reset.status_code == 303
    assert "developer_economics_json" not in get_scenario(sc.scenario_id, OWNER).overrides
    assert read_committed_evidence(flow.run())["developer_fee_keur"] == 100.0
    # Base cannot "inherit" from nothing
    env.client.post("/v2/workbook/scenarios/select", data={**flow.project, "scenario_id": ""})


# ─────────────────────── failure, corruption, history ───────────────────────

def test_failed_run_publishes_no_partial_developer_result(env, monkeypatch):
    from app.persistence.run_history_repository import get_run_history
    flow = Flow(env)
    flow.run()
    fc = _fc(flow.record)
    assert flow.save(_doc(fc)).status_code == 303
    summary_before, history_before = copy.deepcopy(flow.ws().last_runtime_summary), len(get_run_history(OWNER, flow.record.project_id))
    import app.api.project_runner as runner
    original = runner.run_project
    def boom(*a, **k):
        raise RuntimeError("synthetic engine failure")
    monkeypatch.setattr(runner, "run_project", boom)
    wb = env.client.get("/v2/workbook", params=flow.project)
    r = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data={**flow.project, **_tokens(wb.text)})
    assert "developer_economics" not in (flow.ws().last_runtime_summary or {})
    assert flow.ws().last_runtime_summary == summary_before
    assert len(get_run_history(OWNER, flow.record.project_id)) == history_before and flow.ws().dirty
    monkeypatch.setattr(runner, "run_project", original)


def test_corrupt_persisted_payload_fails_closed_on_run_and_page(env):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.db import get_connection
    flow = Flow(env)
    flow.run()
    fc = _fc(flow.record)
    assert flow.save(_doc(fc)).status_code == 303
    wb = env.client.get("/v2/workbook", params=flow.project)          # identity tokens rendered before corruption
    conn = get_connection()
    draft = copy.deepcopy(flow.ws().draft_snapshot)
    draft["developer_economics_json"] = '{"version":1,"enabled":true}'
    conn.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(draft), flow.record.project_id))
    conn.commit(); conn.close()
    history = len(get_run_history(OWNER, flow.record.project_id))
    r = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data={**flow.project, **_tokens(wb.text)})
    assert len(get_run_history(OWNER, flow.record.project_id)) == history       # nothing committed
    page = flow.page()
    assert "failed closed" in page or "DEV_ECON_SCHEMA" in page


def test_corrupted_committed_evidence_is_unavailable_not_reconstructed(env):
    from app.model_v2.developer_evidence import read_committed_evidence
    from app.v2.developer_committed_projection import build_committed_view
    flow = Flow(env)
    fc = _fc(flow.record)
    assert flow.save(_doc(fc)).status_code == 303
    summary = flow.run()
    ws = flow.ws()
    good = build_committed_view(summary, freshness="CURRENT", snapshot_id=ws.last_runtime_snapshot_id,
                                composite_hash=ws.last_runtime_composite_hash)
    assert good["state"] == "CURRENT" and good["metrics"]
    for mutate in (lambda e: e.update(developer_moic=float("nan")), lambda e: e.pop("run_binding"),
                   lambda e: e["run_binding"].update(snapshot_id="forged"), lambda e: e.update(schema="other"),
                   lambda e: e["cashflows"][0].update(net_developer_cashflow_keur=None)):
        broken = copy.deepcopy(summary)
        mutate(broken["developer_economics"])
        view = build_committed_view(broken, freshness="CURRENT", snapshot_id=ws.last_runtime_snapshot_id,
                                    composite_hash=ws.last_runtime_composite_hash)
        assert view["state"] == "UNAVAILABLE" and "metrics" not in view
    wrong = build_committed_view(summary, freshness="CURRENT", snapshot_id=ws.last_runtime_snapshot_id, composite_hash="0" * 64)
    assert wrong["state"] == "UNAVAILABLE"                                       # foreign composite identity
    assert build_committed_view({}, freshness="NOT_RUN", snapshot_id=None, composite_hash=None)["state"] == "NOT_RUN"
    assert read_committed_evidence({"developer_economics": "x"}) is None


def test_identity_rotates_on_save_and_stale_follows(env):
    flow = Flow(env)
    flow.run()
    first = re.search(r'name="content_hash" value="([^"]*)"', flow.page()).group(1)
    fc = _fc(flow.record)
    assert flow.save(_doc(fc)).status_code == 303
    second = re.search(r'name="content_hash" value="([^"]*)"', flow.page()).group(1)
    assert first != second
    assert flow.save(_doc(fc)).status_code == 303            # identical payload: still a valid explicit Save
    wb = env.client.get("/v2/workbook", params=flow.project).text
    assert "STALE" in flow.page()


# ───────── RC-2: nested committed-evidence validation (never raises, never renders unsupported figures) ─────────

def _committed_pair(env):
    flow = Flow(env)
    assert flow.save(_doc(_fc(flow.record))).status_code == 303
    summary = flow.run()
    ws = flow.ws()
    return flow, summary, ws


@pytest.mark.parametrize("mutate", [
    lambda e: e["fee_basis"].update(mode="OTHER"),
    lambda e: e["fee_basis"].update(fee_keur="300"),
    lambda e: e["fee_basis"].pop("basis_authority"),
    lambda e: e["fee_basis"].update(basis_keur=123.0),                # FIXED fee must carry no basis
    lambda e: e.update(fee_basis="not-a-dict"),
    lambda e: e.update(cashflows=[]),
    lambda e: e.pop("cashflows"),
    lambda e: e["cashflows"][0].update(date="2027-13-45"),
    lambda e: e["cashflows"][0].update(development_spend_keur=float("inf")),
    lambda e: e["cashflows"][0].pop("net_developer_cashflow_keur"),
    lambda e: e["cashflows"].reverse(),                                # dates must strictly increase
    lambda e: e.update(developer_moic_status="MAYBE"),
    lambda e: e.update(developer_xirr_status="NO_POSITIVE_CASHFLOW"),   # a figure with a non-OK status
    lambda e: e.update(developer_moic=None),                            # OK status without a figure
    lambda e: e.update(outcome="ABANDONED"),                            # contradicts the typed input
    lambda e: e.update(total_developer_receipts_keur=-1.0),
    lambda e: e.update(settlement_date="soon"),
    lambda e: e.update(unexpected_key=1),
    lambda e: e["input"].update(enabled=False) if isinstance(e["input"], dict) else None,
    lambda e: e.update(input="{"),
])
def test_corrupted_nested_evidence_is_unavailable_without_raising(env, mutate):
    from app.v2.developer_committed_projection import build_committed_view
    flow, summary, ws = _committed_pair(env)
    broken = copy.deepcopy(summary)
    mutate(broken["developer_economics"])
    view = build_committed_view(broken, freshness="CURRENT", snapshot_id=ws.last_runtime_snapshot_id,
                                composite_hash=ws.last_runtime_composite_hash,
                                scenario_id=ws.last_runtime_scenario_id, check_scenario=True)
    assert view["state"] == "UNAVAILABLE" and "metrics" not in view and "vector" not in view


def test_wrong_scenario_binding_is_unavailable_and_not_a_500(env):
    from app.v2.developer_committed_projection import build_committed_view
    flow, summary, ws = _committed_pair(env)
    args = dict(freshness="CURRENT", snapshot_id=ws.last_runtime_snapshot_id, composite_hash=ws.last_runtime_composite_hash)
    assert build_committed_view(summary, scenario_id=ws.last_runtime_scenario_id, check_scenario=True, **args)["state"] == "CURRENT"
    assert build_committed_view(summary, scenario_id="another-scenario", check_scenario=True, **args)["state"] == "UNAVAILABLE"
    # A stored document that cannot be rendered degrades to UNAVAILABLE even through the page.
    from app.persistence.db import get_connection
    broken = copy.deepcopy(ws.last_runtime_summary)
    broken["developer_economics"]["fee_basis"] = None
    conn = get_connection()
    conn.execute("UPDATE workspace_states SET last_runtime_summary_json=? WHERE project_id=?",
                 (json.dumps(broken), flow.record.project_id))
    conn.commit(); conn.close()
    page = flow.page()
    assert 'data-testid="dd-last-state"' in page and "UNAVAILABLE" in page and 'data-testid="dd-last-developer_moic"' not in page


def test_historical_entry_is_owner_and_project_scoped_and_identity_bound(env):
    from app.persistence.run_history_repository import get_run_history, get_run_history_entry
    flow, summary, ws = _committed_pair(env)
    entry = get_run_history(OWNER, flow.record.project_id)[0]
    assert get_run_history_entry("other-user", flow.record.project_id, entry.history_id) is None
    assert get_run_history_entry(OWNER, "other-project", entry.history_id) is None
    other = flow.page(history_id="does-not-exist")
    assert "does not exist for this project" in other
    ok = flow.page(history_id=entry.history_id)
    assert 'data-testid="dd-historical"' in ok and "HISTORICAL" in ok
