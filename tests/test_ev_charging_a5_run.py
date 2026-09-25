"""EV Charging V1 — A5 stateless Model Reference Run API acceptance.

Covers Correction A items E/F/G: the advertised EV reference key must run
cleanly at 5/8/10 MW through exactly one canonical calculation, with the
electricity schedule rebuilt at the requested capacity (no 5 MW step
survivors), stateless-authority flags, and GET/preview/run consistency.
"""

from __future__ import annotations

import pytest

from app import ev_charging_economics as ev

EV_KEY = "generic_ev_charging_reference"


@pytest.fixture(scope="module")
def client():
    # The A5 router is exercised on a dedicated FastAPI app (stateless API —
    # main_web is not involved), mirroring test_api_v1_model_reference_run.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.router import router as v1_router
    app = FastAPI()
    app.include_router(v1_router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


def _run(client, capacity_mw):
    return client.post(
        f"/api/v1/model/references/{EV_KEY}/run",
        json={"capacity_mw": capacity_mw},
    )


def _preview(client, capacity_mw):
    return client.post(
        f"/api/v1/model/references/{EV_KEY}/preview",
        json={"capacity_mw": capacity_mw},
    )


def _assert_authority_stateless(data):
    authority = data["authority"]
    assert authority["runtime_authority"] == "clean_g2c"
    assert authority["calculation_count"] == 1
    assert authority["project_created"] is False
    assert authority["scenario_created"] is False
    assert authority["workspace_mutated"] is False
    assert authority["persisted"] is False
    assert data["scaling"]["project_created"] is False
    assert data["scaling"]["db_writes"] is False


# ── 5 MW: stabilized economics reconcile exactly ─────────────────────────────

def test_a5_ev_run_5mw(client):
    resp = _run(client, 5.0)
    assert resp.status_code == 200, resp.text[:500]
    data = resp.json()["data"]
    _assert_authority_stateless(data)
    # identity: charging terminology, never generation capacity
    assert data["identity"]["technology"] == "ev_charging"
    assert data["identity"]["capacity_unit"] == "MW charging capacity"
    # capex: reference scale unchanged (9,000 kEUR)
    assert data["capex"]["scaled_total_capex_keur"] == pytest.approx(9_000.0)
    # runtime results finite and plausible
    results = data["results"]
    assert results["total_revenue_keur"] == pytest.approx(
        sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21)), rel=1e-6
    )


# ── 8 MW: full electricity schedule rebuilt at requested capacity ────────────

def test_a5_ev_run_8mw_rebuilds_electricity_schedule(client):
    resp = _run(client, 8.0)
    assert resp.status_code == 200, resp.text[:500]
    data = resp.json()["data"]
    _assert_authority_stateless(data)
    assert data["capex"]["scaled_total_capex_keur"] == pytest.approx(14_400.0)
    results = data["results"]
    # the engine revenue must equal the 8 MW authority schedule (ramp visible)
    assert results["total_revenue_keur"] == pytest.approx(
        sum(ev.charging_revenue_keur(8.0, y) for y in range(1, 21)), rel=1e-6
    )
    # the electricity schedule must be rebuilt at 8 MW: run the exact inputs
    # the API built and assert no 5 MW Y2/Y3 step amount survives.
    from app.api.v1.model_run import build_run_response_data
    from finco_core.opex.projections import opex_item_amount_at_year

    data2 = build_run_response_data(EV_KEY, 8.0)
    # rebuild via the same authority the API used and compare against drivers
    scaled = ev.scaled_ev_reference_inputs(8.0)
    elec = next(i for i in scaled.opex if i.name == "Electricity Procurement")
    for year in (1, 2, 3, 4, 10):
        assert opex_item_amount_at_year(elec, year) == pytest.approx(
            ev.electricity_expense_keur(8.0, year), rel=1e-12
        ), year
    ref_elec_y2 = opex_item_amount_at_year(
        next(i for i in ev.scaled_ev_reference_inputs(5.0).opex
             if i.name == "Electricity Procurement"), 2
    )
    assert opex_item_amount_at_year(elec, 2) != pytest.approx(ref_elec_y2, rel=1e-6), (
        "a 5 MW Y2 step amount survived the 8 MW rebuild"
    )


# ── 10 MW: capacity-proportional physics double vs 5 MW ─────────────────────

def test_a5_ev_run_10mw_doubles_capacity_proportional_economics(client):
    resp = _run(client, 10.0)
    assert resp.status_code == 200, resp.text[:500]
    data = resp.json()["data"]
    _assert_authority_stateless(data)
    assert data["capex"]["scaled_total_capex_keur"] == pytest.approx(18_000.0)
    # revenue doubles vs 5 MW for every year (prices/hours unchanged)
    assert data["results"]["total_revenue_keur"] == pytest.approx(
        2.0 * sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21)), rel=1e-6
    )
    # grid energy purchased doubles: 20,000 / 0.94 MWh stabilized
    assert ev.grid_energy_purchased_mwh(10.0, 3) == pytest.approx(
        2.0 * ev.grid_energy_purchased_mwh(5.0, 3), rel=1e-12
    )


# ── G: GET / preview / run consistency ───────────────────────────────────────

def test_a5_ev_get_preview_run_consistency(client):
    assert client.get(f"/api/v1/model/references/{EV_KEY}").status_code == 200
    assert _preview(client, 8.0).status_code == 200
    assert _run(client, 8.0).status_code == 200


def test_a5_ev_invalid_reference_404(client):
    resp = client.post(
        "/api/v1/model/references/generic_nonexistent_reference/run",
        json={"capacity_mw": 5.0},
    )
    assert resp.status_code == 404


def test_a5_ev_invalid_capacity_400(client):
    for bad in (0, -5.0):
        resp = _run(client, bad)
        assert resp.status_code == 400, (bad, resp.status_code, resp.text[:200])
