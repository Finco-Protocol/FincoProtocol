"""SC-06: the Revenue sheet shows the effective tariff / balancing deduction a Run would use, with value, unit, source and what it means."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "e.db"))
    db.init_db()
    import main_web
    yield TestClient(main_web.app)


def _sheet(client, uid, template):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    rec = create_reference_seeded_project(user_id=uid, template_source=template, requested_name="E", capacity_mw=40.0)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username="admin"))
    return rec, client.get(f"/v2/workbook/grid/sheet?project={rec.project_code}&sheet=revenue").text


def _row(html, key):
    m = re.search(rf'data-testid="effective-{key}"[^>]*data-source="([^"]*)".*?data-testid="effective-{key}-value">(.*?)</strong>', html, re.S)
    assert m, key
    return m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()


def test_wind_shows_the_real_effective_tariff_and_template_balancing_deduction(client):
    _, html = _sheet(client, "sc34-eff-w", "generic_wind_reference")
    source, value = _row(html, "tariff")
    assert value.startswith("60 ") and "EUR/MWh" in value and source == "Saved legacy tariff key"
    source, value = _row(html, "balancing")
    assert value.startswith("8 ") and "EUR/MWh" in value and source.startswith("Project template default")
    assert "net revenue = gross revenue - balancing deduction" in html
    assert "takes effect only after Save and a new Run" in html


def test_an_explicit_balancing_value_is_reported_as_a_saved_input_and_template_value_is_replaced(client):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    rec, _ = _sheet(client, "sc34-eff-w2", "generic_wind_reference")
    pis = ProjectInputSet.from_snapshot(get_workspace_state("sc34-eff-w2", rec.project_id).draft_snapshot)
    pis = pis.with_value("revenue.balancing.cost_eur_per_mwh", "5.5")
    from app.v2.effective_revenue_inputs import build_effective_revenue_inputs
    rows = {r["key"]: r for r in build_effective_revenue_inputs(pis)}
    assert rows["balancing"]["value"] == 5.5 and rows["balancing"]["source"] == "Saved input"
    assert rows["tariff"]["value"] == 60.0                                          # the tariff is untouched (no fabricated override)


def test_active_contracts_mark_the_scalar_tariff_as_not_used(client):
    from app.v2.effective_revenue_inputs import build_effective_revenue_inputs
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    rec, _ = _sheet(client, "sc34-eff-w3", "generic_wind_reference")
    pis = ProjectInputSet.from_snapshot(get_workspace_state("sc34-eff-w3", rec.project_id).draft_snapshot)
    rows = {r["key"]: r for r in build_effective_revenue_inputs(pis, contracts_active=True)}
    assert rows["tariff"]["value"] is None and rows["tariff"]["source"] == "Not used"
    assert rows["balancing"]["value"] == 8.0                                        # the per-MWh deduction still applies with contracts


def test_solar_reference_shows_no_phantom_balancing_deduction(client):
    _, html = _sheet(client, "sc34-eff-s", "generic_solar_reference")
    source, value = _row(html, "balancing")
    assert value.startswith("0 ") and source == "No deduction"


@pytest.fixture()
def revenue_case(tmp_path, monkeypatch):
    from app.persistence import db
    from app.persistence.projects_repository import _compute_baseline_snapshot, create_project_record
    from app.persistence.workspace_repository import save_workspace_state

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "revenue-authority.db"))
    db.init_db()
    snapshot = _compute_baseline_snapshot("Wind", "generic_wind_reference")
    snapshot.update(project_name="Synthetic Wind", project_origin="saved_baseline")
    record = create_project_record(
        user_id="a4-revenue", project_code="a4-revenue", project_name="Synthetic Wind",
        project_type="Wind", project_origin="saved_baseline", template_source="generic_wind_reference",
        baseline_snapshot=snapshot,
    )
    ws = save_workspace_state(
        user_id=record.user_id, project_id=record.project_id, project_code=record.project_code,
        draft_snapshot=snapshot, saved_snapshot=snapshot,
    )
    return record, ws, snapshot


@pytest.mark.parametrize("raw, source, tariff", [
    (None, "Saved legacy tariff key", 60.0),
    ("", "Saved legacy tariff key", 60.0),
    ("  ", "Saved legacy tariff key", 60.0),
    ("0", "Saved input", 0.0),
    ("12.5", "Saved input", 12.5),
])
def test_tariff_provenance_distinguishes_blank_from_explicit_zero(revenue_case, raw, source, tariff):
    from app.v2.effective_revenue_inputs import build_effective_revenue_inputs
    from app.workbook.input_set import ProjectInputSet

    _, _, snapshot = revenue_case
    if raw is not None:
        snapshot["rev_ppa_base_tariff"] = raw
    pis = ProjectInputSet.from_snapshot(snapshot)
    before = pis.to_snapshot()
    row = build_effective_revenue_inputs(pis)[0]
    assert row["value"] == pis.to_projectinputs().revenue.ppa_base_tariff == tariff
    assert row["source"] == source
    assert pis.to_snapshot() == before


def test_pricing_basis_preserves_explicit_zero_tariff_and_escalation(revenue_case):
    from app.v2.router import _build_revenue_ctx
    from app.workbook.input_set import ProjectInputSet

    _, ws, snapshot = revenue_case
    snapshot.update(rev_ppa_base_tariff="0", rev_ppa_index="0")
    pis = ProjectInputSet.from_snapshot(snapshot)
    ctx = _build_revenue_ctx(pis, ws)
    basis = {label: value for label, value, _ in ctx["revenue_pricing_basis"]}
    assert basis["Contracted tariff"] == pis.to_projectinputs().revenue.ppa_base_tariff == 0.0
    assert basis["PPA escalation"] == pis.to_projectinputs().revenue.ppa_index == 0.0


@pytest.mark.parametrize("raw, entered, effective", [(None, None, 8.0), ("", None, 8.0), ("0", 0.0, 8.0), ("5.5", 5.5, 5.5)])
def test_pricing_basis_shows_effective_balancing_without_changing_entered_value(revenue_case, raw, entered, effective):
    from app.v2.router import _build_revenue_ctx
    from app.workbook.input_set import ProjectInputSet

    _, ws, snapshot = revenue_case
    if raw is not None:
        snapshot["rev_balancing_cost_eur_per_mwh"] = raw
    pis = ProjectInputSet.from_snapshot(snapshot)
    before = pis.to_snapshot()
    ctx = _build_revenue_ctx(pis, ws)
    basis = {label: value for label, value, _ in ctx["revenue_pricing_basis"]}
    balancing = next(row for row in ctx["revenue_effective_inputs"] if row["key"] == "balancing")
    assert basis["Balancing cost"] == balancing["value"] == effective
    assert pis.get("revenue.balancing.cost_eur_per_mwh") == entered
    field = next(field for field in ctx["revenue_fields"] if field["field_id"] == "revenue.balancing.cost_eur_per_mwh")
    assert field["value"] == entered
    if raw == "0":
        assert "explicitly 0 EUR/MWh" in balancing["detail"]
        assert "template deduction applies at 8 EUR/MWh" in balancing["detail"]
        assert "no explicit value" not in balancing["detail"]
    elif raw in (None, ""):
        assert "No Balancing Cost" in balancing["detail"]
    assert pis.to_snapshot() == before


def test_pricing_basis_missing_effective_balancing_stays_unavailable(revenue_case, monkeypatch):
    from app.v2 import effective_revenue_inputs
    from app.v2.router import _build_revenue_ctx
    from app.workbook.input_set import ProjectInputSet

    _, ws, snapshot = revenue_case
    snapshot["rev_balancing_cost_eur_per_mwh"] = "5.5"
    pis = ProjectInputSet.from_snapshot(snapshot)
    monkeypatch.setattr(effective_revenue_inputs, "build_effective_revenue_inputs", lambda *args, **kwargs: ())
    ctx = _build_revenue_ctx(pis, ws)
    basis = {label: value for label, value, _ in ctx["revenue_pricing_basis"]}
    assert basis["Balancing cost"] is None
    assert pis.get("revenue.balancing.cost_eur_per_mwh") == 5.5


@pytest.mark.parametrize("tariff", [0, 35])
def test_next_run_tariff_uses_selected_scenario_authority(revenue_case, tariff):
    from app.persistence.db import get_cursor
    from app.persistence.scenarios_repository import add_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_revenue_ctx
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.scenario_revenue_authority import bind_scenario_tariff

    record, _, snapshot = revenue_case
    scenario = add_scenario(
        user_id=record.user_id, project_id=record.project_id, project_code=record.project_code,
        scenario_name="Tariff scenario", parent_scenario_id="synthetic-base", base_input_set=snapshot,
        overrides={"tariff_eur_mwh": tariff},
    )
    with get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET active_scenario_id=? WHERE project_id=?", (scenario.scenario_id, record.project_id))
    ws = get_workspace_state(record.user_id, record.project_id)
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot)
    ctx = _build_revenue_ctx(pis, ws)
    actual = ProjectInputSet.from_snapshot(bind_scenario_tariff(dict(pis.snapshot_origin), scenario.overrides)).to_projectinputs()
    assert ctx["revenue_effective_inputs"][0]["value"] == actual.revenue.ppa_base_tariff == tariff
    assert ctx["revenue_effective_inputs"][0]["source"] == "Scenario override"
    assert ctx["revenue_pricing_basis"][0][1] == tariff
    assert get_workspace_state(record.user_id, record.project_id).draft_snapshot == snapshot


@pytest.fixture()
def selected_tariff_case(revenue_case):
    from app.persistence.db import get_cursor
    from app.persistence.scenarios_repository import add_scenario
    from app.persistence.workspace_repository import get_workspace_state

    record, _, snapshot = revenue_case
    scenario = add_scenario(
        user_id=record.user_id, project_id=record.project_id, project_code=record.project_code,
        scenario_name="Synthetic tariff", parent_scenario_id="synthetic-base", base_input_set=snapshot,
        overrides={"tariff_eur_mwh": 35},
    )
    with get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET active_scenario_id=? WHERE project_id=?", (scenario.scenario_id, record.project_id))
    return record, get_workspace_state(record.user_id, record.project_id), snapshot, scenario


def test_scenario_without_tariff_override_preserves_default_year_inputs(selected_tariff_case, monkeypatch):
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_revenue_ctx
    from app.workbook import scenario_revenue_authority
    from app.workbook.input_set import ProjectInputSet

    record, ws, snapshot, scenario = selected_tariff_case
    with get_cursor() as cur:
        cur.execute("UPDATE scenarios SET overrides_json='{}' WHERE scenario_id=?", (scenario.scenario_id,))

    def unexpected_binding(*args, **kwargs):
        raise AssertionError("No scenario tariff was supplied")

    monkeypatch.setattr(scenario_revenue_authority, "bind_scenario_tariff", unexpected_binding)
    pis = ProjectInputSet.from_snapshot(snapshot)
    ctx = _build_revenue_ctx(pis, ws)
    revenue = pis.to_projectinputs().revenue
    basis = {label: value for label, value, _ in ctx["revenue_pricing_basis"]}
    assert basis["Contracted tariff"] == revenue.ppa_base_tariff == 60.0
    assert basis["PPA term"] == revenue.ppa_term_years == 12
    assert basis["PPA escalation"] == revenue.ppa_index * 100 == 2.0
    assert ctx["revenue_effective_inputs"][0]["source"] == "Saved legacy tariff key"
    assert ctx["revenue_multistream"]["operating_years"]
    assert get_workspace_state(record.user_id, record.project_id).draft_snapshot == snapshot


@pytest.mark.parametrize("tariff", [None, "invalid", -1, True, "nan", "inf"])
def test_bad_scenario_tariff_is_unavailable_not_a_base_fallback(selected_tariff_case, tariff):
    import json
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_revenue_ctx
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.scenario_revenue_authority import bind_scenario_tariff

    record, ws, snapshot, scenario = selected_tariff_case
    overrides = {"tariff_eur_mwh": tariff}
    with get_cursor() as cur:
        cur.execute("UPDATE scenarios SET overrides_json=? WHERE scenario_id=?", (json.dumps(overrides), scenario.scenario_id))
    with pytest.raises(ValueError):
        bind_scenario_tariff(snapshot, overrides)
    ctx = _build_revenue_ctx(ProjectInputSet.from_snapshot(snapshot), ws)
    assert ctx["revenue_pricing_basis"][0][1] is None
    assert ctx["revenue_effective_inputs"] == ()
    assert get_workspace_state(record.user_id, record.project_id).draft_snapshot == snapshot


@pytest.mark.parametrize("scope", ["project_mismatch", "owner_mismatch", "archived", "base_case", "missing"])
def test_out_of_scope_scenario_cannot_supply_display_tariff(selected_tariff_case, monkeypatch, scope):
    from app.persistence.db import get_cursor
    from app.persistence.projects_repository import create_project_record
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_revenue_ctx
    from app.workbook import scenario_revenue_authority
    from app.workbook.input_set import ProjectInputSet

    record, ws, snapshot, scenario = selected_tariff_case
    if scope == "project_mismatch":
        other = create_project_record(
            user_id=record.user_id, project_code="other-project", project_name="Other project", project_type="Wind",
            project_origin="saved_baseline", template_source="generic_wind_reference", baseline_snapshot=snapshot,
        )
    with get_cursor() as cur:
        assert cur.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        if scope == "project_mismatch":
            cur.execute("UPDATE scenarios SET project_id=? WHERE scenario_id=?", (other.project_id, scenario.scenario_id))
        elif scope == "owner_mismatch":
            cur.execute("UPDATE scenarios SET user_id='other-owner' WHERE scenario_id=?", (scenario.scenario_id,))
        elif scope == "missing":
            cur.execute("DELETE FROM scenarios WHERE scenario_id=?", (scenario.scenario_id,))
        else:
            column = "archived" if scope == "archived" else "is_base_case"
            cur.execute(f"UPDATE scenarios SET {column}=1 WHERE scenario_id=?", (scenario.scenario_id,))

    def unexpected_binding(*args, **kwargs):
        raise AssertionError("Out-of-scope scenario must not bind pricing")

    monkeypatch.setattr(scenario_revenue_authority, "bind_scenario_tariff", unexpected_binding)
    ctx = _build_revenue_ctx(ProjectInputSet.from_snapshot(snapshot), ws)
    assert ctx["revenue_pricing_basis"][0][1] == 60.0
    assert ctx["revenue_effective_inputs"][0]["value"] == 60.0
    assert ctx["revenue_effective_inputs"][0]["source"] != "Scenario override"
    assert get_workspace_state(record.user_id, record.project_id).draft_snapshot == snapshot


def test_contract_pricing_is_not_presented_as_legacy_pricing(revenue_case):
    import json
    from app.v2.router import _build_revenue_ctx, _templates
    from app.workbook.input_set import ProjectInputSet
    from tests.test_wf07_revenue_multistream import contracts

    _, ws, snapshot = revenue_case
    pis = ProjectInputSet.from_snapshot(snapshot)
    pis = pis.with_value("revenue.multistream.contracts", json.dumps(contracts(pis.to_projectinputs(), "wind", price=91)))
    ctx = _build_revenue_ctx(pis, ws)
    assert ctx["revenue_multistream"]["active"]
    assert ctx["revenue_multistream"]["rows"][0]["price_eur_mwh"] == 91
    assert ctx["revenue_effective_inputs"][0]["value"] is None
    assert ctx["revenue_effective_inputs"][0]["source"] == "Not used"
    html = _templates.get_template("partials/sheet_revenue.html").render(ctx)
    assert 'class="v2-revenue-pricing-grid"' not in html
    assert "Saved legacy tariff key" not in html
