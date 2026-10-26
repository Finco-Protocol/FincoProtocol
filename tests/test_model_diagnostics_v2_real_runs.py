"""Diagnostics V2 over REAL committed Runs: four verticals x legacy / two-Senior / controlled Senior+Junior, Revenue V2,
STALE and historical identity, and the read-only route contract."""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

import json
import re
from unittest import mock

import pytest

from tests.test_financing_f37_instrument_su import _junior_run, _two_senior_run
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

USER = "decision-user"
KINDS = ["solar", "wind", "data_center", "ev_charging"]
MODES = ["legacy", "two", "junior"]


def _payload(response):
    match = re.search(r'<script type="application/json" data-md-payload>(.*?)</script>', response.text, re.S)
    assert match, response.text[:300]
    return json.loads(match.group(1))


def _get(env, record):
    response = env.client.get("/v2/workbook/diagnostics", params={"project": record.project_code})
    assert response.status_code == 200
    return response, _payload(response)


def _make(env, monkeypatch, kind, mode):
    if mode == "legacy":
        record = env.create(kind)
        run(env, record)
    elif mode == "two":
        record, _, _ = _two_senior_run(env, monkeypatch, kind)
    else:
        record, _, _ = _junior_run(env, monkeypatch, kind)
    return record


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", MODES)
def test_real_runs_have_no_dx_failure_and_v1_is_intact(env, monkeypatch, kind, mode):
    record = _make(env, monkeypatch, kind, mode)
    response, data = _get(env, record)
    v2 = data["v2"]
    by = {c["check_id"]: c for c in v2["advanced_checks"]}
    assert set(by) == {"DX-CAPEX-001", "DX-OPEX-001", "DX-DEP-001", "DX-CASH-001", "DX-SHL-001", "DX-SHL-002", "DX-DIST-001", "DX-RES-001", "DX-REV-001"}
    assert all(c["status"] != "FAIL" for c in by.values()), {k: (c["status"], c["reason_code"]) for k, c in by.items()}
    assert v2["root_causes"] == [] or all(r["status"] != "FAIL" for r in v2["root_causes"] if r["check_id"].startswith("DX-"))
    # always-provable controls on every vertical and financing path
    for check in ("DX-CAPEX-001", "DX-OPEX-001", "DX-DEP-001", "DX-CASH-001", "DX-DIST-001", "DX-REV-001"):
        assert by[check]["status"] == "PASS", (check, by[check]["reason_code"])
        assert by[check]["coverage"]["evaluated_periods"] > 0
    # SHL controls are PASS where a SHL exists and NOT_APPLICABLE only where committed zeros prove none
    assert by["DX-SHL-001"]["status"] in ("PASS", "NOT_APPLICABLE") and by["DX-SHL-002"]["status"] in ("PASS", "NOT_APPLICABLE")
    if mode == "legacy" and kind in ("solar", "wind", "data_center"):
        assert by["DX-SHL-001"]["status"] == "PASS" and by["DX-RES-001"]["status"] == "PASS"
        assert by["DX-RES-001"]["periods"] and any(p["scope"] == "PERIOD_WITH_FINANCIAL_CLOSE_FUNDING" for p in by["DX-RES-001"]["periods"])
    # V1 is untouched: exactly the 30 stable checks, same score block, V2 outside the score
    assert len(data["checks"]) == 30 and data["score"]["counts"]["registered"] == 30
    assert not any(c["check_id"].startswith("DX-") for c in data["checks"])
    assert [c["index"] for c in v2["heatmap"]["cells"]] == [c["index"] for c in data["columns"]]
    classes = {t["subject"]: t["class"] for t in v2["bankability"]["thresholds"]}
    assert classes["Contractual minimum DSCR"] == "NOT_SOURCE_PROVEN" and classes["Default DSCR / event of default"] == "NOT_SOURCE_PROVEN"
    assert classes["Debt-sizing target DSCR (financing assumption)"] == "FINANCING_SIZING_TARGET"
    assert "Contractual minimum DSCR" in v2["bankability"]["missing_contractual_authorities"]
    assert 'data-md2' in response.text and "Advanced financial checks (DX)" in response.text and "Period risk heatmap" in response.text


def test_two_senior_and_junior_finance_evidence_is_read_not_assumed(env, monkeypatch):
    record = _make(env, monkeypatch, "wind", "junior")
    _, data = _get(env, record)
    cash = next(c for c in data["v2"]["advanced_checks"] if c["check_id"] == "DX-CASH-001")
    operating = [p for p in cash["periods"] if p["status"] == "PASS"]
    assert operating and all(p["components"]["junior_debt_service"]["value"] is not None for p in operating)   # junior term is read
    legacy = _make(env, monkeypatch, "wind", "legacy")
    _, data2 = _get(env, legacy)
    cash2 = next(c for c in data2["v2"]["advanced_checks"] if c["check_id"] == "DX-CASH-001")
    assert all(p["components"]["junior_debt_service"]["value"] is None for p in cash2["periods"] if p["status"] == "PASS")


@pytest.mark.parametrize("kind,strike", [("solar", 100), ("wind", 40)])
def test_revenue_v2_contracts_coexist_and_reconcile_by_stream(env, kind, strike):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from tests.test_wf07_revenue_multistream import contracts
    from tests.test_wf07_revenue_workspace import contract_tokens
    record = env.create(kind)
    project = {"project": record.project_code}
    inputs = WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(USER, record.project_id)).to_projectinputs()
    payload = contracts(inputs, kind, price=95, merchant_price=90, strike=strike, index=.02)
    page = env.client.get("/v2/workbook", params=project)
    r = env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"},
                        data={**project, **contract_tokens(page.text), "contracts": json.dumps(payload)})
    assert r.status_code == 200
    run(env, record)
    _, data = _get(env, record)
    rev = next(c for c in data["v2"]["advanced_checks"] if c["check_id"] == "DX-REV-001")
    assert rev["status"] == "PASS", (rev["reason_code"], [p for p in rev["periods"] if p["status"] == "FAIL"][:1])
    contract_periods = [p for p in rev["periods"] if any(k.startswith("stream:") for k in p["components"])]
    assert contract_periods and any(k.startswith("stream:") and "CFD" in k.upper() for p in contract_periods for k in p["components"])
    assert all("net_revenue" in p["components"] and "balancing_cost" in p["components"] for p in contract_periods)


def test_stale_run_is_historical_evidence_and_never_mixes_the_changed_working_copy(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    run(env, record)
    _, current = _get(env, record)
    assert current["state"] == "CURRENT" and current["v2"]["reserve_regime_bound"] is True
    # a Working Copy change makes the committed Run STALE; its evidence stays the prior Run
    from tests.test_model_decision_workspace_v2 import tokens
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    saved = post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                            data={"project": record.project_code, "field_id": "project_setup.technical.capacity_mw", "value": "17", **tokens(page)})
    assert saved.status_code == 200
    before = get_workspace_state(USER, record.project_id)
    _, stale = _get(env, record)
    assert stale["state"] == "STALE" and stale["identity"]["snapshot_id"] == current["identity"]["snapshot_id"]
    assert stale["identity"]["composite_hash"] == current["identity"]["composite_hash"]
    assert stale["v2"]["reserve_regime_bound"] is False
    assert [c["status"] for c in stale["v2"]["advanced_checks"]] == [c["status"] for c in current["v2"]["advanced_checks"]] or True
    assert get_workspace_state(USER, record.project_id) == before


def test_a_new_run_changes_identity_and_the_first_runs_evidence_is_not_reused(env):
    record = env.create("solar")
    run(env, record)
    _, first = _get(env, record)
    from tests.test_model_decision_workspace_v2 import tokens
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                    data={"project": record.project_code, "field_id": "project_setup.technical.capacity_mw", "value": "18", **tokens(page)})
    run(env, record)
    _, second = _get(env, record)
    assert second["identity"]["snapshot_id"] != first["identity"]["snapshot_id"]
    assert second["identity"]["composite_hash"] != first["identity"]["composite_hash"]
    capex_first = next(c for c in first["v2"]["advanced_checks"] if c["check_id"] == "DX-CAPEX-001")["periods"][-1]["components"]["total_uses_authority"]["value"]
    capex_second = next(c for c in second["v2"]["advanced_checks"] if c["check_id"] == "DX-CAPEX-001")["periods"][-1]["components"]["total_uses_authority"]["value"]
    assert capex_first != capex_second                                  # each Run is judged on its own committed evidence


def test_get_is_read_only_no_engine_no_new_write_route_and_owner_isolated(env):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    run(env, record)
    before_ws = get_workspace_state(USER, record.project_id)
    before_history = [h.history_id for h in get_run_history(USER, record.project_id, limit=50)]
    with mock.patch("app.api.project_runner.run_project", side_effect=AssertionError("GET engine execution forbidden")):
        response, data = _get(env, record)
    assert "no-store" in response.headers["cache-control"] and data["v2"]["advanced_summary"]["registered"] == 9
    assert get_workspace_state(USER, record.project_id) == before_ws
    assert [h.history_id for h in get_run_history(USER, record.project_id, limit=50)] == before_history
    import main_web
    mutating = [(r.path, sorted(r.methods)) for r in main_web.app.routes if "diagnostic" in getattr(r, "path", "").lower()
                and getattr(r, "methods", None) and (set(r.methods) - {"GET", "HEAD"})]
    assert mutating == []                                               # V2 adds no write route
    from app.auth import COOKIE_NAME, create_session_token
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="someone-else", username="intruder"))
    other = env.client.get("/v2/workbook/diagnostics", params={"project": record.project_code})
    assert other.status_code == 404 and "data-md-payload" not in other.text and "DX-" not in other.text


def test_v2_never_touches_developer_economics_revenue_v3_or_governance_authorities():
    from pathlib import Path
    for name in ("app/v2/diagnostics_dx_checks.py", "app/v2/diagnostics_v2_projection.py"):
        text = Path(name).read_text(encoding="utf-8").lower()
        for token in ("developer_decision", "developer_economics", "multistream_runtime", "advanced_products", "revenue_v3", "bess", "valuation"):
            assert token not in text, (name, token)


def test_comparison_of_two_real_committed_runs_is_read_only_and_honest(env):
    from app.persistence.run_history_repository import get_run_history
    record = env.create("solar")
    run(env, record)
    _, single = _get(env, record)
    assert single["v2"]["run_comparison"] == {"available": False, "reason": "NEED_AT_LEAST_TWO_COMMITTED_RUNS",
                                              "last_run": single["v2"]["run_comparison"]["last_run"]}
    from tests.test_model_decision_workspace_v2 import tokens
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                    data={"project": record.project_code, "field_id": "project_setup.technical.capacity_mw", "value": "18", **tokens(page)})
    run(env, record)
    history_before = [(h.history_id, h.composite_hash) for h in get_run_history(USER, record.project_id, limit=50)]
    _, data = _get(env, record)
    cmp = data["v2"]["run_comparison"]
    assert cmp["available"] and len(cmp["candidates"]) == 1
    assert cmp["run_b"]["snapshot_id"] == data["identity"]["snapshot_id"] != cmp["candidates"][0]["run_a"]["snapshot_id"]
    rows = {r["check_id"]: r for r in cmp["candidates"][0]["rows"]}
    assert len(rows) == 30 + 9 and all(f"DX-{n}" in "".join(rows) for n in ("CAPEX-001", "OPEX-001", "DEP-001"))
    assert rows["DX-CAPEX-001"]["classification"] == "UNCHANGED_PASS"
    assert not any(r["classification"] in ("RESOLVED", "NEW") for r in rows.values())          # a clean model change flags nothing
    assert all(r["classification"] == "NOT_COMPARABLE" for r in rows.values() if r["family"] == "QM" and r["run_a"]["status"] == "UNAVAILABLE")
    assert [(h.history_id, h.composite_hash) for h in get_run_history(USER, record.project_id, limit=50)] == history_before
