"""Workflow B acceptance over typed inputs and immutable Last Run evidence."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import copy
import re

import pytest

from app.v2.financing_projection import (
    build_financing_evidence, build_reserve_view, build_sponsor_view,
    integrity_view, metric, senior_editor_fields,
)
from app.workbook.runtime_result import RuntimeResult


def runtime(**overrides):
    fields = dict(snapshot_id="finance-run", ran_at="2030-01-01T12:00:00Z", origin="saved_state",
        runtime_summary={"senior_debt_keur": 700.0, "actual_gearing_pct": .625,
                         "gearing_cap_pct": .7, "equity_irr": .14},
        debt_schedule={"periods": [], "summary": {"actual_min_dscr": 1.23,
            "actual_avg_dscr": 1.41, "target_dscr": 1.3, "min_llcr": None}},
        financial_statements={"pf_cash_waterfall": {"periods": [
            {"period_index": 8, "date": "2030-06-30", "fcf_banks_keur": 123.4567,
             "senior_total_ds_keur": 80.5, "dsra_funding_keur": -4.0, "dsra_release_keur": 0.0},
            {"period_index": 9, "date": "2030-12-31", "fcf_banks_keur": 0.0,
             "senior_total_ds_keur": 0.0},
        ]}}, tax_schedule=None, distribution_schedule=None,
        sponsor_schedule={"summary": {"total_sponsor_xirr": .12, "pure_equity_moic": 5.6,
            "total_sponsor_moic": 2.1, "total_shl_cash_contributed_keur": 200.0}})
    fields.update(overrides)
    return RuntimeResult(**fields)


@pytest.mark.parametrize("value", [None, True, "42,000 kEUR", "5.50%", float("inf"), float("nan")])
def test_metrics_never_parse_display_values_or_manufacture_zero(value):
    m = metric("Debt", value, "kEUR", "persisted source")
    assert m.value is None
    assert m.display == "Not available"


def test_cash_evidence_preserves_every_period_value_date_and_sign_without_totals():
    rr = runtime()
    before = copy.deepcopy(dict(rr.runtime_summary))
    view = build_financing_evidence(rr)
    source = rr.financial_statements["pf_cash_waterfall"]["periods"]
    for p, row in zip(source, view["cash_rows"], strict=True):
        assert row["cfads"].value == p["fcf_banks_keur"]
        assert row["service"].value == p["senior_total_ds_keur"]
        assert row["period"] == p["period_index"] and row["date"] == p["date"]
        assert "fcf_banks_keur" in row["cfads"].source
    assert view["cash_rows"][0]["funding"].value == -4.0
    assert view["cash_rows"][1]["funding"].value is None
    assert view["cash_rows"][1]["cfads"].value == 0.0
    assert "total_cfads" not in view
    assert dict(rr.runtime_summary) == before


def test_gearing_uses_persisted_raw_ratio_and_never_current_capex():
    view = build_financing_evidence(runtime())
    assert view["metrics"][0].value == 700.0
    assert view["metrics"][1].value == .625
    assert view["metrics"][1].display == "62.50%"
    missing = build_financing_evidence(runtime(runtime_summary={"senior_debt_keur": "700 kEUR"}))
    assert missing["metrics"][0].value is None
    assert missing["metrics"][1].value is None
    assert "Working CAPEX is not substituted" in missing["metrics"][1].reason


def test_missing_llcr_retains_reason_without_zero_or_inferred_constraint():
    rr = runtime(debt_schedule={"summary": {"llcr_unavailable_reason": "COVERAGE_DENOMINATOR_MISSING"}})
    view = build_financing_evidence(rr)
    assert view["metrics"][-1].value is None
    assert view["metrics"][-1].reason == "COVERAGE_DENOMINATOR_MISSING"
    assert view["sizing_status"] == "Not available"
    assert build_financing_evidence(None)["cash_rows"] == ()


@pytest.mark.parametrize("factory", ["create_generic_solar_reference", "create_generic_wind_reference",
                                     "create_generic_data_center_reference", "create_generic_ev_charging_reference"])
def test_editor_projects_typed_fraction_to_registry_percent_exactly(factory):
    from app import project_factories
    pi = getattr(project_factories, factory)()
    rate_config = pi.financing.senior_debt_interest_config
    schedule = replace(rate_config.rate_schedule,
        explicit_all_in_rates=tuple(.055 for _ in rate_config.rate_schedule.explicit_all_in_rates))
    pi = replace(pi, financing=replace(pi.financing,
        senior_debt_interest_config=replace(rate_config, rate_schedule=schedule)))
    fields = [{"field_id": "debt.senior.interest_rate_pct", "value": .055},
              {"field_id": "debt.senior.target_dscr", "value": 1.2}]
    rows = senior_editor_fields(fields, pi)
    assert rows[0]["value"] == "5.50"
    assert rows[0]["display_value"] == "5.50%"
    assert fields[0]["value"] == .055  # no snapshot mutation


def test_calibrated_and_unresolved_rate_authority_stays_locked():
    from app.project_factories import create_generic_solar_reference
    from app.v2.router import _lock_senior_fields_if_calibrated
    pi = create_generic_solar_reference()
    config = pi.financing.senior_debt_interest_config
    rates = (.05, .06) + tuple(config.rate_schedule.explicit_all_in_rates[2:])
    pi = replace(pi, financing=replace(pi.financing,
        senior_debt_interest_config=replace(config, rate_schedule=replace(config.rate_schedule,
            explicit_all_in_rates=rates))))
    fields = [{"field_id": "debt.senior.interest_rate_pct", "value": .055, "binding_label": "bound", "label": "All-in interest rate"}]
    rows = _lock_senior_fields_if_calibrated(senior_editor_fields(fields, pi), "CALIBRATED", "FLAT_SCALAR")
    assert rows[0]["binding_label"] == "template-locked"
    assert rows[0]["display_value"] == "Period-specific calibrated rates"
    assert _lock_senior_fields_if_calibrated(fields, "UNRESOLVED", "UNRESOLVED")[0]["binding_label"] == "template-locked"


@pytest.mark.parametrize("inputs,overall,want", [
    ("CURRENT", "FAIL", "FAIL"), ("CURRENT", "PASS", "PASS"),
    ("STALE", "FAIL", "FAIL"), ("CURRENT", "INCOMPLETE", "WARN"),
    ("NOT_RUN", None, "UNAVAILABLE"),
])
def test_integrity_is_independent_from_freshness_and_keeps_codes(inputs, overall, want):
    from app.v2.router import _templates
    report = {"overall": overall, "counts": {"FAIL": int(overall == "FAIL"), "PASS": int(overall == "PASS")},
              "checks": [{"check_id": "DSCR_SCULPTING", "title": "Debt schedule feasibility",
                  "status": overall, "reason_code": "DSCR_SCULPTING_INFEASIBLE_SCHEDULE"}]} if overall else {}
    before = copy.deepcopy(report)
    view = integrity_view(report, inputs)
    assert view["status"] == want
    assert view["prior"] == (inputs == "STALE")
    html = _templates.get_template("partials/_financing_integrity.html").render(financing_integrity=view, project_code="finance")
    assert f"Inputs: {inputs.replace('_', ' ')}" in html
    assert f"Financial integrity: {want}" in html
    if overall:
        assert "DSCR_SCULPTING_INFEASIBLE_SCHEDULE" in html
    assert report == before


def test_no_checks_cannot_be_presented_as_pass():
    assert integrity_view({"overall": "PASS"}, "CURRENT")["status"] == "UNAVAILABLE"


def test_protected_investor_keeps_reference_model_notice_without_editors():
    from app.v2.router import _templates
    html = _templates.get_template("partials/sheet_investor.html").render(
        project_editable=False, project_code="finance-reference",
        sponsor_funding_freshness={"state": "NOT_RUN", "label": "Not run"},
        sponsor_view=build_sponsor_view(None, None), sponsor_last_run_rows=())
    assert "Reference model" in html and "Create working copy" in html
    assert 'name="value"' not in html and "BOUND READ-ONLY" not in html


def test_sponsor_native_labels_and_units_do_not_reclassify_cash():
    from app.project_factories import create_generic_solar_reference
    view = build_sponsor_view(create_generic_solar_reference().financing, runtime())
    assert view["mode"] == "Share capital, then shareholder loan"
    assert view["day_count"] == "Actual period days / calendar-year days"
    assert view["repayment"] in ("Cash sweep", "Bullet at maturity")
    assert [m.value for m in view["returns"]] == [.14, .12, 5.6, 2.1]
    assert view["equity"][0].source.endswith("share_capital_keur")
    assert build_reserve_view(None)["requirement"].value is None


@pytest.fixture(scope="module")
def projects(tmp_path_factory):
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project
    patch = pytest.MonkeyPatch()
    patch.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("bankability") / "finance.db"))
    db.init_db()
    records = {}
    try:
        for kind, capacity in (("solar", 64), ("wind", 48), ("data_center", 16), ("ev_charging", 1)):
            records[kind] = create_reference_seeded_project(user_id="finance-owner", requested_name="Finance " + kind,
                template_source="generic_" + kind + "_reference", capacity_mw=capacity)
        yield records
    finally:
        patch.undo()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from main_web import app
    c = TestClient(app)
    c.cookies.set(COOKIE_NAME, create_session_token(user_id="finance-owner", username="admin"))
    try:
        yield c
    finally:
        c.close()


def tokens(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ws = get_workspace_state("finance-owner", record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    identity = assemble_consistent_for_get(user_id="finance-owner", project_id=record.project_id, workbook_version=pis.workbook_version)
    return pis.workbook_version, identity.composite_hash


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_authenticated_workspaces_render_authority_safe_financing_context(client, projects, kind):
    from app.persistence.workspace_repository import get_workspace_state
    record = projects[kind]
    page = client.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200
    assert 'data-testid="financing-cfads"' in page.text
    assert "Equity-only vs sponsor-inclusive returns" in page.text
    assert "Reserve policy &amp; assumptions" in page.text
    assert "no supported Investor write contract" in page.text
    assert "sheet=debt" in page.text and "overview-integrity-loader" in page.text
    # Initial workbook GET performs existing canonical draft initialization.
    # The new integrity read and repeated rendering must not mutate that state.
    before = get_workspace_state("finance-owner", record.project_id)
    state = client.get("/v2/workbook/financing/integrity", params={"project": record.project_code})
    assert state.status_code == 200 and "Financial integrity: UNAVAILABLE" in state.text
    assert client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    assert get_workspace_state("finance-owner", record.project_id) == before


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_percent_save_persists_existing_contract_and_rejects_invalid(client, projects, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.input_adapter import senior_rate_authority
    record = projects[kind]
    for raw, accepted in (("5.50", True), ("21", False), ("-1", False), ("nan", False), ("abc", False)):
        v, h = tokens(record)
        response = client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data={
            "project": record.project_code, "sheet_id": "debt", "field_id": "debt.senior.interest_rate_pct",
            "value": raw, "workbook_version": v, "content_hash": h})
        assert response.status_code == 200, response.text[:400]
        assert ('"workbook-field-saved"' in response.headers.get("HX-Trigger", "")) == accepted
        if not accepted:
            assert '"workbook-field-error"' in response.headers["HX-Trigger"]
            assert 'v2-field-error-banner' in response.text
        ws = get_workspace_state("finance-owner", record.project_id)
        assert float(ws.draft_snapshot["interest_rate_pct"]) == 5.5
        pi = WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs()
        assert senior_rate_authority(pi)[1] == pytest.approx(.055)


@pytest.mark.parametrize("surface", ["integrity", "investor"])
def test_financing_endpoint_enforces_authenticated_project_owner(client, projects, surface):
    from app.auth import COOKIE_NAME, create_session_token
    client.cookies.clear()
    path = "/v2/workbook/financing/" + surface
    assert client.get(path, params={"project": projects["solar"].project_code}).status_code in (401, 404)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id="other-finance-owner", username="admin"))
    assert client.get(path, params={"project": projects["solar"].project_code}).status_code == 404


def test_frozen_financial_and_parallel_files_are_not_required_by_projection():
    import inspect
    import app.v2.financing_projection as module
    source = inspect.getsource(module)
    assert "financial_engine" not in source and "finco_core" not in source
    assert "run_clean_production" not in source and "get_connection" not in source


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_run_cash_gearing_returns_and_integrity_use_exact_persisted_authorities(client, projects, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.api.v1_1.institutional import get_run_integrity_checks
    record = projects[kind]
    v, h = tokens(record)
    response = client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "workbook_version": v, "content_hash": h})
    assert response.status_code == 200, response.text[:1000]
    before = get_workspace_state("finance-owner", record.project_id)
    rr = WorkbookService.get_runtime_result(before)
    assert rr is not None
    view = build_financing_evidence(rr)
    for row, original in zip(view["cash_rows"], rr.financial_statements["pf_cash_waterfall"]["periods"], strict=True):
        assert row["cfads"].value == original["fcf_banks_keur"]
        assert row["service"].value == original["senior_total_ds_keur"]
    assert view["metrics"][0].value == rr.runtime_summary["senior_debt_keur"]
    assert view["metrics"][1].value == rr.runtime_summary["actual_gearing_pct"]
    sponsor = build_sponsor_view(None, rr)
    sr = rr.sponsor_schedule["summary"]
    assert sponsor["returns"][2].value == sr["pure_equity_moic"]
    # Numerical plausibility audit only: no production economics are changed.
    assert sr["pure_equity_moic"] == pytest.approx(
        sr["total_legal_equity_distributions_keur"] / sr["total_legal_equity_contributed_keur"])
    print(f"{kind}: legal equity={sr['total_legal_equity_contributed_keur']}, "
          f"equity receipts={sr['total_legal_equity_distributions_keur']}, "
          f"pure equity MOIC={sr['pure_equity_moic']}, sponsor MOIC={sr['total_sponsor_moic']}")
    _, authority = get_run_integrity_checks("finance-owner", record.project_id)
    page = client.get("/v2/workbook/financing/integrity", params={"project": record.project_code})
    assert page.status_code == 200
    expected = integrity_view(authority, "CURRENT")
    assert f"Financial integrity: {expected['status']}" in page.text
    assert "Inputs: CURRENT" in page.text
    assert get_workspace_state("finance-owner", record.project_id) == before


def test_concurrent_working_edit_during_integrity_read_fails_closed(client, projects, monkeypatch):
    from app.api.v1_1 import institutional
    from app.workbook.update_service import WorkbookUpdateService
    record = projects["solar"]
    original = institutional.get_run_integrity_checks
    def read_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        v, h = tokens(record)
        from app.persistence.workspace_repository import get_workspace_state
        WorkbookUpdateService.apply_draft_update(ws=get_workspace_state("finance-owner", record.project_id),
            project_record=record, field_id="debt.senior.gearing_pct", raw_value="60", workbook_version=v, content_hash=h)
        return result
    monkeypatch.setattr(institutional, "get_run_integrity_checks", read_then_edit)
    response = client.get("/v2/workbook/financing/integrity", params={"project": record.project_code})
    assert response.status_code == 200
    assert "Financial integrity: UNAVAILABLE" in response.text
    assert "Inputs: UNAVAILABLE" in response.text


def test_investor_fragment_preserves_prior_run_and_has_no_writes(client, projects):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.update_service import WorkbookUpdateService
    record = projects["solar"]
    v, h = tokens(record)
    response = client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "workbook_version": v, "content_hash": h})
    assert response.status_code == 200
    v, h = tokens(record)
    ws = get_workspace_state("finance-owner", record.project_id)
    new_gearing = "65" if float(ws.draft_snapshot.get("gearing_pct", 70)) != 65 else "60"
    WorkbookUpdateService.apply_draft_update(ws=ws, project_record=record,
        field_id="debt.senior.gearing_pct", raw_value=new_gearing, workbook_version=v, content_hash=h)
    before = get_workspace_state("finance-owner", record.project_id)
    response = client.get("/v2/workbook/financing/investor", params={"project": record.project_code})
    assert response.status_code == 200
    assert "prior" in response.text.lower() or "stale" in response.text.lower()
    assert 'data-testid="investor-return-evidence"' in response.text
    assert "htmx:afterRequest" in response.text
    assert set(v.strip() for v in response.headers["Cache-Control"].split(",")) == {"no-store"}
    assert get_workspace_state("finance-owner", record.project_id) == before


def test_concurrent_edit_during_investor_render_discards_financial_evidence(client, projects, monkeypatch):
    from app.v2 import router
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.update_service import WorkbookUpdateService
    record = projects["wind"]
    original = router._build_debt_ctx
    def build_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        v, h = tokens(record)
        WorkbookUpdateService.apply_draft_update(ws=get_workspace_state("finance-owner", record.project_id),
            project_record=record, field_id="debt.senior.gearing_pct", raw_value="60", workbook_version=v, content_hash=h)
        return result
    monkeypatch.setattr(router, "_build_debt_ctx", build_then_edit)
    response = client.get("/v2/workbook/financing/investor", params={"project": record.project_code})
    assert response.status_code == 200
    assert "workspace changed during response assembly" in response.text
    assert 'data-testid="investor-return-evidence"' not in response.text
