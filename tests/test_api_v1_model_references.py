"""A3 Model Reference API v1 tests.

Test IDs: A3-01 through A3-70+
Scope: GET /api/v1/model/references, /api/v1/model/references/{key},
       /api/v1/model/references/{key}/capex, /api/v1/model/references/{key}/opex

No DB dependency: all endpoints are pure factory-based.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.router as _router_module

# ---------------------------------------------------------------------------
# Fixture: test app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """TestClient wired to the same router used in production (no DB needed)."""
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    return TestClient(_app)


# ── Convenience helpers ───────────────────────────────────────────────────────

def _list(client):
    return client.get("/api/v1/model/references")

def _template(client, key):
    return client.get(f"/api/v1/model/references/{key}")

def _capex(client, key):
    return client.get(f"/api/v1/model/references/{key}/capex")

def _opex(client, key):
    return client.get(f"/api/v1/model/references/{key}/opex")


# ── A3 List endpoint ──────────────────────────────────────────────────────────

def test_a3_01_list_returns_200(client):
    assert _list(client).status_code == 200

def test_a3_02_list_state_available(client):
    assert _list(client).json()["state"] == "AVAILABLE"

def test_a3_03_list_api_version(client):
    assert _list(client).json()["api_version"] == "v1"

def test_a3_04_list_count_is_2(client):
    assert _list(client).json()["data"]["count"] == 2

def test_a3_05_list_contains_solar_key(client):
    keys = [r["key"] for r in _list(client).json()["data"]["references"]]
    assert "generic_solar_reference" in keys

def test_a3_06_list_contains_wind_key(client):
    keys = [r["key"] for r in _list(client).json()["data"]["references"]]
    assert "generic_wind_reference" in keys

def test_a3_07_list_solar_display_name(client):
    refs = {r["key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs["generic_solar_reference"]["display_name"] == "Generic Solar Reference"

def test_a3_08_list_wind_display_name(client):
    refs = {r["key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs["generic_wind_reference"]["display_name"] == "Generic Wind Reference"

def test_a3_09_list_solar_technology(client):
    refs = {r["key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs["generic_solar_reference"]["technology"] == "solar"

def test_a3_10_list_wind_technology(client):
    refs = {r["key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs["generic_wind_reference"]["technology"] == "wind"

def test_a3_11_list_references_is_list(client):
    body = _list(client).json()
    assert isinstance(body["data"]["references"], list)

def test_a3_12_list_stable_second_call(client):
    assert _list(client).json() == _list(client).json()

def test_a3_13_list_no_storage_reference(client):
    keys = [r["key"] for r in _list(client).json()["data"]["references"]]
    assert "generic_storage_reference" not in keys


# ── A3 Template endpoint — Solar ──────────────────────────────────────────────

def test_a3_14_solar_template_returns_200(client):
    assert _template(client, "generic_solar_reference").status_code == 200

def test_a3_15_solar_template_state_available(client):
    assert _template(client, "generic_solar_reference").json()["state"] == "AVAILABLE"

def test_a3_16_solar_template_api_version(client):
    assert _template(client, "generic_solar_reference").json()["api_version"] == "v1"

def test_a3_17_solar_template_reference_key(client):
    body = _template(client, "generic_solar_reference").json()
    assert body["reference_key"] == "generic_solar_reference"

def test_a3_18_solar_template_capacity_mw(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["capacity_mw"] == 64.0

def test_a3_19_solar_template_horizon_years(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["horizon_years"] == 25

def test_a3_20_solar_template_construction_months(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["construction_months"] == 14

def test_a3_21_solar_template_technology(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["technology"] == "solar"

def test_a3_22_solar_template_ppa_base_tariff(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["ppa_base_tariff"] == 50.0

def test_a3_23_solar_template_gearing_ratio(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["gearing_ratio"] == 0.75

def test_a3_24_solar_template_senior_tenor(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["senior_tenor_years"] == 15

def test_a3_25_solar_template_corporate_tax(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["corporate_tax_rate"] == 0.25

def test_a3_26_solar_template_operating_hours_p50(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["operating_hours_p50"] == 1500.0

def test_a3_27_solar_template_display_name(client):
    data = _template(client, "generic_solar_reference").json()["data"]
    assert data["display_name"] == "Generic Solar Reference"


# ── A3 Template endpoint — Wind ───────────────────────────────────────────────

def test_a3_28_wind_template_returns_200(client):
    assert _template(client, "generic_wind_reference").status_code == 200

def test_a3_29_wind_template_capacity_mw(client):
    data = _template(client, "generic_wind_reference").json()["data"]
    assert data["capacity_mw"] == 48.0

def test_a3_30_wind_template_horizon_years(client):
    data = _template(client, "generic_wind_reference").json()["data"]
    assert data["horizon_years"] == 27

def test_a3_31_wind_template_construction_months(client):
    data = _template(client, "generic_wind_reference").json()["data"]
    assert data["construction_months"] == 20

def test_a3_32_wind_template_technology(client):
    data = _template(client, "generic_wind_reference").json()["data"]
    assert data["technology"] == "wind"

def test_a3_33_wind_template_ppa_tariff(client):
    data = _template(client, "generic_wind_reference").json()["data"]
    assert data["ppa_base_tariff"] == 60.0

def test_a3_34_wind_template_operating_hours_p50(client):
    data = _template(client, "generic_wind_reference").json()["data"]
    assert data["operating_hours_p50"] == 3000.0


# ── A3 CAPEX endpoint — Solar ─────────────────────────────────────────────────

def test_a3_35_solar_capex_returns_200(client):
    assert _capex(client, "generic_solar_reference").status_code == 200

def test_a3_36_solar_capex_state_available(client):
    assert _capex(client, "generic_solar_reference").json()["state"] == "AVAILABLE"

def test_a3_37_solar_capex_api_version(client):
    assert _capex(client, "generic_solar_reference").json()["api_version"] == "v1"

def test_a3_38_solar_capex_capacity_mw(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    assert data["capacity_mw"] == 64.0

def test_a3_39_solar_capex_items_is_list(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    assert isinstance(data["items"], list)

def test_a3_40_solar_capex_total(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    assert data["total_capex_keur"] == pytest.approx(33_000.0)

def test_a3_41_solar_capex_has_solar_modules(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    labels = [it["canonical_label"] for it in data["items"]]
    assert "Solar Modules" in labels

def test_a3_42_solar_modules_amount(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_label"] == "Solar Modules")
    assert item["reference_amount_keur"] == pytest.approx(20_000.0)

def test_a3_43_solar_modules_unit_rate(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_label"] == "Solar Modules")
    assert item["unit_rate_keur_per_mw"] == pytest.approx(312.5)

def test_a3_44_solar_capex_has_inverters(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    labels = [it["canonical_label"] for it in data["items"]]
    assert "Inverters" in labels

def test_a3_45_solar_capex_has_grid_connection(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    labels = [it["canonical_label"] for it in data["items"]]
    assert "Grid Connection" in labels

def test_a3_46_solar_capex_has_civil_works(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    labels = [it["canonical_label"] for it in data["items"]]
    assert "Civil Works" in labels

def test_a3_47_solar_capex_has_soft_costs(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    labels = [it["canonical_label"] for it in data["items"]]
    assert "Soft Costs" in labels

def test_a3_48_solar_soft_costs_owner_category(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_label"] == "Soft Costs")
    assert item["owner_category_code"] == "C.08"

def test_a3_49_solar_capex_all_scaling_mode_per_mw(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    assert all(it["scaling_mode"] == "PER_MW" for it in data["items"])

def test_a3_50_solar_capex_items_have_canonical_field(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    assert all("canonical_field" in it for it in data["items"])

def test_a3_51_solar_capex_reference_key_in_data(client):
    data = _capex(client, "generic_solar_reference").json()["data"]
    assert data["key"] == "generic_solar_reference"


# ── A3 CAPEX endpoint — Wind ──────────────────────────────────────────────────

def test_a3_52_wind_capex_returns_200(client):
    assert _capex(client, "generic_wind_reference").status_code == 200

def test_a3_53_wind_capex_capacity_mw(client):
    data = _capex(client, "generic_wind_reference").json()["data"]
    assert data["capacity_mw"] == 48.0

def test_a3_54_wind_capex_total(client):
    data = _capex(client, "generic_wind_reference").json()["data"]
    assert data["total_capex_keur"] == pytest.approx(43_000.0)

def test_a3_55_wind_capex_has_wind_turbines(client):
    data = _capex(client, "generic_wind_reference").json()["data"]
    labels = [it["canonical_label"] for it in data["items"]]
    assert "Wind Turbines" in labels

def test_a3_56_wind_turbines_amount(client):
    data = _capex(client, "generic_wind_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_label"] == "Wind Turbines")
    assert item["reference_amount_keur"] == pytest.approx(30_000.0)

def test_a3_57_wind_turbines_unit_rate(client):
    data = _capex(client, "generic_wind_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_label"] == "Wind Turbines")
    assert item["unit_rate_keur_per_mw"] == pytest.approx(625.0)

def test_a3_58_wind_capex_no_production_units_zero_item(client):
    data = _capex(client, "generic_wind_reference").json()["data"]
    fields = [it.get("canonical_field") for it in data["items"]]
    for item in data["items"]:
        assert item["reference_amount_keur"] > 0, "zero-amount items must be filtered"


# ── A3 OPEX endpoint — Solar ──────────────────────────────────────────────────

def test_a3_59_solar_opex_returns_200(client):
    assert _opex(client, "generic_solar_reference").status_code == 200

def test_a3_60_solar_opex_state_available(client):
    assert _opex(client, "generic_solar_reference").json()["state"] == "AVAILABLE"

def test_a3_61_solar_opex_capacity_mw(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    assert data["capacity_mw"] == 64.0

def test_a3_62_solar_opex_total_y1(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    assert data["total_opex_y1_keur"] == pytest.approx(380.0)

def test_a3_63_solar_opex_technical_management_amount(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_key"] == "Technical Management")
    assert item["reference_amount_keur"] == pytest.approx(150.0)

def test_a3_64_solar_opex_insurance_amount(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_key"] == "Insurance")
    assert item["reference_amount_keur"] == pytest.approx(100.0)

def test_a3_65_solar_opex_maintenance_amount(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_key"] == "Maintenance")
    assert item["reference_amount_keur"] == pytest.approx(80.0)

def test_a3_66_solar_opex_lease_tax_amount(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_key"] == "Lease & Tax")
    assert item["reference_amount_keur"] == pytest.approx(50.0)

def test_a3_67_solar_opex_annual_inflation(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    assert all(it["annual_inflation"] == pytest.approx(0.02) for it in data["items"])

def test_a3_68_solar_opex_scaling_mode(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    assert all(it["scaling_mode"] == "PER_MW" for it in data["items"])

def test_a3_69_solar_opex_reference_key_in_data(client):
    data = _opex(client, "generic_solar_reference").json()["data"]
    assert data["key"] == "generic_solar_reference"


# ── A3 OPEX endpoint — Wind ───────────────────────────────────────────────────

def test_a3_70_wind_opex_returns_200(client):
    assert _opex(client, "generic_wind_reference").status_code == 200

def test_a3_71_wind_opex_total_y1(client):
    data = _opex(client, "generic_wind_reference").json()["data"]
    assert data["total_opex_y1_keur"] == pytest.approx(550.0)

def test_a3_72_wind_opex_technical_management_amount(client):
    data = _opex(client, "generic_wind_reference").json()["data"]
    item = next(it for it in data["items"] if it["canonical_key"] == "Technical Management")
    assert item["reference_amount_keur"] == pytest.approx(200.0)

def test_a3_73_wind_opex_items_have_unit_rate(client):
    data = _opex(client, "generic_wind_reference").json()["data"]
    assert all("unit_rate_keur_per_mw" in it for it in data["items"])


# ── A3 Error cases ────────────────────────────────────────────────────────────

def test_a3_74_unknown_key_template_404(client):
    assert _template(client, "unknown_reference").status_code == 404

def test_a3_75_unknown_key_capex_404(client):
    assert _capex(client, "unknown_reference").status_code == 404

def test_a3_76_unknown_key_opex_404(client):
    assert _opex(client, "unknown_reference").status_code == 404

def test_a3_77_storage_key_template_404(client):
    assert _template(client, "generic_storage_reference").status_code == 404

def test_a3_78_storage_key_capex_404(client):
    assert _capex(client, "generic_storage_reference").status_code == 404

def test_a3_79_storage_key_opex_404(client):
    assert _opex(client, "generic_storage_reference").status_code == 404

def test_a3_80_404_has_error_code(client):
    body = _template(client, "unknown_reference").json()
    assert body["error"] == "REFERENCE_NOT_FOUND"

def test_a3_81_404_has_reference_key(client):
    body = _template(client, "unknown_reference").json()
    assert body["reference_key"] == "unknown_reference"

def test_a3_82_404_has_api_version(client):
    body = _template(client, "unknown_reference").json()
    assert body["api_version"] == "v1"

def test_a3_83_invalid_format_key_template_400(client):
    assert _template(client, "INVALID_KEY").status_code == 400

def test_a3_84_invalid_format_key_capex_400(client):
    assert _capex(client, "INVALID_KEY").status_code == 400

def test_a3_85_invalid_format_key_opex_400(client):
    assert _opex(client, "INVALID_KEY").status_code == 400

def test_a3_86_400_has_error_code(client):
    body = _template(client, "INVALID_KEY").json()
    assert body["error"] == "REFERENCE_KEY_INVALID"

def test_a3_87_400_has_reference_key(client):
    body = _template(client, "INVALID_KEY").json()
    assert body["reference_key"] == "INVALID_KEY"

def test_a3_88_400_has_api_version(client):
    body = _template(client, "INVALID_KEY").json()
    assert body["api_version"] == "v1"

def test_a3_89_key_starts_with_digit_is_400(client):
    assert _template(client, "1bad_key").status_code == 400

def test_a3_90_key_with_slash_is_handled(client):
    # '/' in path segment is not possible via routing; FastAPI would split the path.
    # Test a key with invalid chars that arrive as a path param.
    assert _template(client, "bad.key").status_code == 400


# ── A3 /meta capabilities ─────────────────────────────────────────────────────

def test_a3_91_meta_includes_model_references_list(client):
    resp = client.get("/api/v1/meta")
    assert resp.status_code == 200
    assert "model.references.list" in resp.json()["capabilities"]

def test_a3_92_meta_includes_model_references_template(client):
    assert "model.references.template" in client.get("/api/v1/meta").json()["capabilities"]

def test_a3_93_meta_includes_model_references_capex(client):
    assert "model.references.capex" in client.get("/api/v1/meta").json()["capabilities"]

def test_a3_94_meta_includes_model_references_opex(client):
    assert "model.references.opex" in client.get("/api/v1/meta").json()["capabilities"]


# ── A3 No-DB purity checks ────────────────────────────────────────────────────

def test_a3_95_no_db_needed_for_list(client, tmp_path, monkeypatch):
    """List endpoint works with no DB configured."""
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "nonexistent.db"))
    assert _list(client).status_code == 200

def test_a3_96_no_db_needed_for_solar_template(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "nonexistent.db"))
    assert _template(client, "generic_solar_reference").status_code == 200

def test_a3_97_no_db_needed_for_solar_capex(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "nonexistent.db"))
    assert _capex(client, "generic_solar_reference").status_code == 200

def test_a3_98_no_db_needed_for_solar_opex(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "nonexistent.db"))
    assert _opex(client, "generic_solar_reference").status_code == 200
