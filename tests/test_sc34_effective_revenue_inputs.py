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
