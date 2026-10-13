"""RC-2 / M4 — Developer Economics persistence bridge (Save -> STALE -> Run -> CURRENT -> history).

Real authorized Save / Scenario / Run / History acceptance on neutral Solar and Wind fixtures. Every
financial figure is compared with the existing canonical calculator; nothing here re-implements one.
"""
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
        r = self.env.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={**self.project, **_tokens(wb.text)})
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
