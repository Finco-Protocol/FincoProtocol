"""A3 Model Reference API v1 — Correction A acceptance tests.

Test IDs: A3-01 through A3-150+

Scope:
  GET /api/v1/model/references
  GET /api/v1/model/references/{key}
  GET /api/v1/model/references/{key}/capex
  GET /api/v1/model/references/{key}/opex

Invariants proved here:
  - Synthetic disclosure on every surface
  - Factory authority for name/code/capacity (no duplicate production constants)
  - Full grouped detail structure
  - CAPEX: canonical total = float(pi.capex.total_capex)
  - OPEX: canonical total = sum(y1_amount_keur), group_code from seed authority
  - CAPEX/OPEX full parity against helpers
  - No DB calls (persistence tripwires)
  - No engine calls (run_project tripwire)
  - Deterministic repeated GET
  - Public state safety (no sensitive fields in JSON)
  - OpenAPI route existence and GET-only contract
  - Meta capability retention (A1/A2 + A3)
  - All unsupported keys → 404 MODEL_REFERENCE_NOT_FOUND (no 400)
"""
from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.router as _router_module

# ---------------------------------------------------------------------------
# Fixture: test app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    _app = FastAPI()
    _app.include_router(_router_module.router, prefix="/api/v1")
    return TestClient(_app)


# Convenience helpers

def _list(client):
    return client.get("/api/v1/model/references")

def _detail(client, key):
    return client.get(f"/api/v1/model/references/{key}")

def _capex(client, key):
    return client.get(f"/api/v1/model/references/{key}/capex")

def _opex(client, key):
    return client.get(f"/api/v1/model/references/{key}/opex")

_SOLAR = "generic_solar_reference"
_WIND = "generic_wind_reference"
_STORAGE = "generic_storage_reference"


# ── A3-01..A3-13: List endpoint ───────────────────────────────────────────────

def test_a3_01_list_returns_200(client):
    assert _list(client).status_code == 200

def test_a3_02_list_state_available(client):
    assert _list(client).json()["state"] == "AVAILABLE"

def test_a3_03_list_api_version(client):
    assert _list(client).json()["api_version"] == "v1"

def test_a3_04_list_count_2(client):
    assert _list(client).json()["data"]["count"] == 2

def test_a3_05_list_has_solar_key(client):
    keys = [r["reference_key"] for r in _list(client).json()["data"]["references"]]
    assert _SOLAR in keys

def test_a3_06_list_has_wind_key(client):
    keys = [r["reference_key"] for r in _list(client).json()["data"]["references"]]
    assert _WIND in keys

def test_a3_07_list_no_storage(client):
    keys = [r["reference_key"] for r in _list(client).json()["data"]["references"]]
    assert _STORAGE not in keys

def test_a3_08_list_solar_name_from_factory(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_SOLAR]["name"] == "Generic Solar Reference"

def test_a3_09_list_wind_name_from_factory(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_WIND]["name"] == "Generic Wind Reference"

def test_a3_10_list_solar_code_from_factory(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_SOLAR]["reference_code"] == "REF-SOLAR-A"

def test_a3_11_list_wind_code_from_factory(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_WIND]["reference_code"] == "REF-WIND-B"

def test_a3_12_list_solar_capacity_from_factory(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_SOLAR]["reference_capacity_mw"] == 64.0

def test_a3_13_list_wind_capacity_from_factory(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_WIND]["reference_capacity_mw"] == 48.0


# ── A3-14..A3-19: List synthetic disclosure ───────────────────────────────────

def test_a3_14_list_top_level_synthetic_reference_true(client):
    assert _list(client).json()["data"]["synthetic_reference"] is True

def test_a3_15_list_top_level_market_benchmark_false(client):
    assert _list(client).json()["data"]["market_benchmark"] is False

def test_a3_16_list_solar_entry_synthetic_reference_true(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_SOLAR]["synthetic_reference"] is True

def test_a3_17_list_solar_entry_market_benchmark_false(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_SOLAR]["market_benchmark"] is False

def test_a3_18_list_wind_entry_synthetic_reference_true(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_WIND]["synthetic_reference"] is True

def test_a3_19_list_wind_entry_market_benchmark_false(client):
    refs = {r["reference_key"]: r for r in _list(client).json()["data"]["references"]}
    assert refs[_WIND]["market_benchmark"] is False


# ── A3-20..A3-30: Detail endpoint structure ───────────────────────────────────

def test_a3_20_solar_detail_200(client):
    assert _detail(client, _SOLAR).status_code == 200

def test_a3_21_solar_detail_state_available(client):
    assert _detail(client, _SOLAR).json()["state"] == "AVAILABLE"

def test_a3_22_solar_detail_reference_key(client):
    assert _detail(client, _SOLAR).json()["reference_key"] == _SOLAR

def test_a3_23_wind_detail_200(client):
    assert _detail(client, _WIND).status_code == 200

def test_a3_24_wind_detail_reference_key(client):
    assert _detail(client, _WIND).json()["reference_key"] == _WIND

def test_a3_25_detail_has_identity_section(client):
    assert "identity" in _detail(client, _SOLAR).json()["data"]

def test_a3_26_detail_has_technical_section(client):
    assert "technical" in _detail(client, _SOLAR).json()["data"]

def test_a3_27_detail_has_revenue_section(client):
    assert "revenue" in _detail(client, _SOLAR).json()["data"]

def test_a3_28_detail_has_financing_section(client):
    assert "financing" in _detail(client, _SOLAR).json()["data"]

def test_a3_29_detail_has_tax_section(client):
    assert "tax" in _detail(client, _SOLAR).json()["data"]

def test_a3_30_detail_has_capex_summary(client):
    assert "capex_summary" in _detail(client, _SOLAR).json()["data"]

def test_a3_31_detail_has_opex_summary(client):
    assert "opex_summary" in _detail(client, _SOLAR).json()["data"]

def test_a3_32_detail_has_reference_semantics(client):
    assert "reference_semantics" in _detail(client, _SOLAR).json()["data"]


# ── A3-33..A3-42: Identity section ───────────────────────────────────────────

def test_a3_33_identity_solar_name_from_factory(client):
    id_ = _detail(client, _SOLAR).json()["data"]["identity"]
    assert id_["name"] == "Generic Solar Reference"

def test_a3_34_identity_solar_code_from_factory(client):
    id_ = _detail(client, _SOLAR).json()["data"]["identity"]
    assert id_["reference_code"] == "REF-SOLAR-A"

def test_a3_35_identity_solar_country_iso(client):
    id_ = _detail(client, _SOLAR).json()["data"]["identity"]
    assert id_["country_iso"] == "XA"

def test_a3_36_identity_wind_country_iso(client):
    id_ = _detail(client, _WIND).json()["data"]["identity"]
    assert id_["country_iso"] == "XB"

def test_a3_37_identity_synthetic_reference_true(client):
    id_ = _detail(client, _SOLAR).json()["data"]["identity"]
    assert id_["synthetic_reference"] is True

def test_a3_38_identity_market_benchmark_false(client):
    id_ = _detail(client, _SOLAR).json()["data"]["identity"]
    assert id_["market_benchmark"] is False

def test_a3_39_identity_wind_synthetic_reference_true(client):
    id_ = _detail(client, _WIND).json()["data"]["identity"]
    assert id_["synthetic_reference"] is True

def test_a3_40_identity_wind_market_benchmark_false(client):
    id_ = _detail(client, _WIND).json()["data"]["identity"]
    assert id_["market_benchmark"] is False

def test_a3_41_reference_semantics_synthetic_reference_true(client):
    rs = _detail(client, _SOLAR).json()["data"]["reference_semantics"]
    assert rs["synthetic_reference"] is True

def test_a3_42_reference_semantics_market_benchmark_false(client):
    rs = _detail(client, _SOLAR).json()["data"]["reference_semantics"]
    assert rs["market_benchmark"] is False


# ── A3-43..A3-55: Technical section ──────────────────────────────────────────

def test_a3_43_technical_solar_capacity_mw(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["capacity_mw"] == 64.0

def test_a3_44_technical_solar_horizon_years(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["horizon_years"] == 25

def test_a3_45_technical_solar_construction_months(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["construction_months"] == 14

def test_a3_46_technical_wind_capacity_mw(client):
    t = _detail(client, _WIND).json()["data"]["technical"]
    assert t["capacity_mw"] == 48.0

def test_a3_47_technical_wind_horizon_years(client):
    t = _detail(client, _WIND).json()["data"]["technical"]
    assert t["horizon_years"] == 27

def test_a3_48_technical_wind_construction_months(client):
    t = _detail(client, _WIND).json()["data"]["technical"]
    assert t["construction_months"] == 20

def test_a3_49_technical_solar_p50(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["operating_hours_p50"] == 1500.0

def test_a3_50_technical_wind_p50(client):
    t = _detail(client, _WIND).json()["data"]["technical"]
    assert t["operating_hours_p50"] == 3000.0

def test_a3_51_technical_solar_p90(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["operating_hours_p90_10y"] == 1400.0

def test_a3_52_technical_wind_p90(client):
    t = _detail(client, _WIND).json()["data"]["technical"]
    assert t["operating_hours_p90_10y"] == 2700.0

def test_a3_53_technical_p99_is_null_not_absent(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert "operating_hours_p99_1y" in t
    assert t["operating_hours_p99_1y"] is None

def test_a3_54_technical_bess_enabled_false(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["bess_enabled"] is False

def test_a3_55_technical_bess_enabled_not_null(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["bess_enabled"] is not None


# ── A3-56..A3-68: Revenue section ────────────────────────────────────────────

def test_a3_56_revenue_solar_ppa_tariff_eur_mwh(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["ppa_base_tariff_eur_mwh"] == pytest.approx(50.0)

def test_a3_57_revenue_wind_ppa_tariff_eur_mwh(client):
    r = _detail(client, _WIND).json()["data"]["revenue"]
    assert r["ppa_base_tariff_eur_mwh"] == pytest.approx(60.0)

def test_a3_58_revenue_solar_ppa_index_rate_0_02(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["ppa_index_rate"] == pytest.approx(0.02)

def test_a3_59_revenue_market_inflation_stays_decimal(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["market_inflation_rate"] == pytest.approx(0.02)

def test_a3_60_revenue_solar_co2_enabled_false(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["co2_enabled"] is False

def test_a3_61_revenue_wind_co2_enabled_false(client):
    r = _detail(client, _WIND).json()["data"]["revenue"]
    assert r["co2_enabled"] is False

def test_a3_62_revenue_co2_enabled_is_bool_not_null(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["co2_enabled"] is not None

def test_a3_63_revenue_wind_balancing_8_0(client):
    r = _detail(client, _WIND).json()["data"]["revenue"]
    assert r["balancing_cost_wind_eur_mwh"] == pytest.approx(8.0)

def test_a3_64_revenue_has_market_prices_curve(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert isinstance(r["market_prices_curve_eur_mwh"], list)
    assert len(r["market_prices_curve_eur_mwh"]) > 0

def test_a3_65_revenue_solar_ppa_term_years(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["ppa_term_years"] == 10

def test_a3_66_revenue_wind_ppa_term_years(client):
    r = _detail(client, _WIND).json()["data"]["revenue"]
    assert r["ppa_term_years"] == 12

def test_a3_67_revenue_market_scenario(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["market_scenario"] == "Central"

def test_a3_68_revenue_co2_price_field_present(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert "co2_certificate_price_eur_mwh" in r


# ── A3-69..A3-79: Financing section ──────────────────────────────────────────

def test_a3_69_financing_gearing_ratio(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["gearing_ratio"] == pytest.approx(0.75)

def test_a3_70_financing_senior_tenor_years(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["senior_tenor_years"] == 15

def test_a3_71_financing_base_rate_decimal(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["base_rate"] == pytest.approx(0.03)

def test_a3_72_financing_margin_bps(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["margin_bps"] == 250

def test_a3_73_financing_target_dscr(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["target_dscr"] == pytest.approx(1.20)

def test_a3_74_financing_lockup_dscr(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["lockup_dscr"] == pytest.approx(1.10)

def test_a3_75_financing_dsra_months(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["dsra_months"] == 6

def test_a3_76_financing_debt_sizing_method_present(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert "debt_sizing_method" in f

def test_a3_77_financing_debt_sizing_mode_present(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert "debt_sizing_mode" in f

def test_a3_78_financing_shl_repayment_method_present(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert "clean_shl_repayment_method" in f

def test_a3_79_financing_no_shl_legacy_amount(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert "shl_amount_keur" not in f
    assert "share_capital_keur" not in f


# ── A3-80..A3-88: Tax section ─────────────────────────────────────────────────

def test_a3_80_tax_corporate_rate_0_25(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["corporate_rate"] == pytest.approx(0.25)

def test_a3_81_tax_corporate_rate_stays_decimal(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["corporate_rate"] < 1.0

def test_a3_82_tax_loss_carryforward_years(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["loss_carryforward_years"] == 5

def test_a3_83_tax_atad_ebitda_limit(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["atad_ebitda_limit"] == pytest.approx(0.30)

def test_a3_84_tax_atad_min_interest_keur(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["atad_min_interest_keur"] == pytest.approx(3000.0)

def test_a3_85_tax_clean_cash_tax_timing(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["clean_cash_tax_timing_enabled"] is True

def test_a3_86_tax_loss_carryforward_cap(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert "loss_carryforward_cap" in t

def test_a3_87_tax_wind_same_assumptions(client):
    ts = _detail(client, _SOLAR).json()["data"]["tax"]
    tw = _detail(client, _WIND).json()["data"]["tax"]
    assert ts["corporate_rate"] == tw["corporate_rate"]
    assert ts["atad_ebitda_limit"] == tw["atad_ebitda_limit"]

def test_a3_88_tax_corporate_rate_not_percentage(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["corporate_rate"] == pytest.approx(0.25)
    assert t["corporate_rate"] != 25


# ── A3-89..A3-100: CAPEX summary authority ────────────────────────────────────

def test_a3_89_solar_capex_summary_total(client):
    cs = _detail(client, _SOLAR).json()["data"]["capex_summary"]
    assert cs["total_capex_keur"] == pytest.approx(33_000.0)

def test_a3_90_wind_capex_summary_total(client):
    cs = _detail(client, _WIND).json()["data"]["capex_summary"]
    assert cs["total_capex_keur"] == pytest.approx(43_000.0)

def test_a3_91_solar_capex_seedable_total(client):
    cs = _detail(client, _SOLAR).json()["data"]["capex_summary"]
    assert cs["seedable_capex_total_keur"] == pytest.approx(33_000.0)

def test_a3_92_wind_capex_seedable_total(client):
    cs = _detail(client, _WIND).json()["data"]["capex_summary"]
    assert cs["seedable_capex_total_keur"] == pytest.approx(43_000.0)

def test_a3_93_solar_opex_summary_canonical_total(client):
    os_ = _detail(client, _SOLAR).json()["data"]["opex_summary"]
    assert os_["opex_y1_keur"] == pytest.approx(380.0)

def test_a3_94_wind_opex_summary_canonical_total(client):
    os_ = _detail(client, _WIND).json()["data"]["opex_summary"]
    assert os_["opex_y1_keur"] == pytest.approx(550.0)

def test_a3_95_solar_opex_seedable_total(client):
    os_ = _detail(client, _SOLAR).json()["data"]["opex_summary"]
    assert os_["seedable_opex_y1_keur"] == pytest.approx(380.0)

def test_a3_96_wind_opex_seedable_total(client):
    os_ = _detail(client, _WIND).json()["data"]["opex_summary"]
    assert os_["seedable_opex_y1_keur"] == pytest.approx(550.0)


# ── A3-97..A3-110: CAPEX endpoint ────────────────────────────────────────────

def test_a3_97_capex_solar_200(client):
    assert _capex(client, _SOLAR).status_code == 200

def test_a3_98_capex_wind_200(client):
    assert _capex(client, _WIND).status_code == 200

def test_a3_99_capex_solar_total_canonical(client):
    d = _capex(client, _SOLAR).json()["data"]
    assert d["total_capex_keur"] == pytest.approx(33_000.0)

def test_a3_100_capex_wind_total_canonical(client):
    d = _capex(client, _WIND).json()["data"]
    assert d["total_capex_keur"] == pytest.approx(43_000.0)

def test_a3_101_capex_solar_seedable_total(client):
    d = _capex(client, _SOLAR).json()["data"]
    assert d["seedable_capex_total_keur"] == pytest.approx(33_000.0)

def test_a3_102_capex_solar_synthetic_disclosure(client):
    d = _capex(client, _SOLAR).json()["data"]
    assert d["synthetic_reference"] is True
    assert d["market_benchmark"] is False

def test_a3_103_capex_wind_synthetic_disclosure(client):
    d = _capex(client, _WIND).json()["data"]
    assert d["synthetic_reference"] is True
    assert d["market_benchmark"] is False

def test_a3_104_capex_items_have_required_fields(client):
    d = _capex(client, _SOLAR).json()["data"]
    required = {"canonical_field", "owner_category_code", "canonical_label", "reference_amount_keur",
                "unit_rate_keur_per_mw", "scaling_mode"}
    for item in d["items"]:
        assert required.issubset(set(item.keys())), f"Item missing fields: {item}"

def test_a3_105_capex_no_zero_amount_items(client):
    for key in (_SOLAR, _WIND):
        items = _capex(client, key).json()["data"]["items"]
        assert all(it["reference_amount_keur"] > 0 for it in items)

def test_a3_106_capex_all_scaling_mode_per_mw(client):
    for key in (_SOLAR, _WIND):
        items = _capex(client, key).json()["data"]["items"]
        assert all(it["scaling_mode"] == "PER_MW" for it in items)

def test_a3_107_capex_solar_soft_costs_owner_c08(client):
    items = _capex(client, _SOLAR).json()["data"]["items"]
    soft = next(it for it in items if it["canonical_label"] == "Soft Costs")
    assert soft["owner_category_code"] == "C.08"

def test_a3_107b_capex_wind_soft_costs_owner_c08_is_canonical(client):
    """Wind uses the same established audit_legal owner; no invented C.15 split."""
    items = _capex(client, _WIND).json()["data"]["items"]
    soft = next(it for it in items if it["canonical_label"] == "Soft Costs")
    assert soft["owner_category_code"] == "C.08"

def test_a3_108_capex_solar_modules_unit_rate(client):
    items = _capex(client, _SOLAR).json()["data"]["items"]
    mod = next(it for it in items if it["canonical_label"] == "Solar Modules")
    assert mod["unit_rate_keur_per_mw"] == pytest.approx(312.5)

def test_a3_109_capex_wind_turbines_unit_rate(client):
    items = _capex(client, _WIND).json()["data"]["items"]
    turb = next(it for it in items if it["canonical_label"] == "Wind Turbines")
    assert turb["unit_rate_keur_per_mw"] == pytest.approx(625.0)


# ── A3-110..A3-125: Full CAPEX parity test ───────────────────────────────────

def test_a3_110_capex_solar_full_parity():
    """API CAPEX items must match canonical_capex_reference_items() exactly."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.v1.router as _rm
    _app = FastAPI()
    _app.include_router(_rm.router, prefix="/api/v1")
    c = TestClient(_app)

    from app.api.v1.model_reference import get_pi, VALID_REFERENCE_KEYS
    from app.services.reference_seed_service import canonical_capex_reference_items

    pi = get_pi(_SOLAR)
    expected = canonical_capex_reference_items(pi)
    api_items = _capex(c, _SOLAR).json()["data"]["items"]
    api_by_field = {it["canonical_field"]: it for it in api_items}

    assert set(api_by_field.keys()) == set(expected.keys()), "Item fields differ"
    for field, exp in expected.items():
        api = api_by_field[field]
        assert api["owner_category_code"] == exp["owner_category_code"]
        assert api["canonical_label"] == exp["canonical_label"]
        assert api["reference_amount_keur"] == pytest.approx(exp["reference_amount_keur"])
        assert api["unit_rate_keur_per_mw"] == pytest.approx(exp["unit_rate_keur_per_mw"])
        assert api["scaling_mode"] == exp["scaling_mode"]


def test_a3_111_capex_wind_full_parity():
    """Same parity test for Wind."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.v1.router as _rm
    _app = FastAPI()
    _app.include_router(_rm.router, prefix="/api/v1")
    c = TestClient(_app)

    from app.api.v1.model_reference import get_pi
    from app.services.reference_seed_service import canonical_capex_reference_items

    pi = get_pi(_WIND)
    expected = canonical_capex_reference_items(pi)
    api_items = _capex(c, _WIND).json()["data"]["items"]
    api_by_field = {it["canonical_field"]: it for it in api_items}

    assert set(api_by_field.keys()) == set(expected.keys())
    for field, exp in expected.items():
        api = api_by_field[field]
        assert api["reference_amount_keur"] == pytest.approx(exp["reference_amount_keur"])
        assert api["unit_rate_keur_per_mw"] == pytest.approx(exp["unit_rate_keur_per_mw"])


# ── A3-112..A3-125: OPEX endpoint ────────────────────────────────────────────

def test_a3_112_opex_solar_200(client):
    assert _opex(client, _SOLAR).status_code == 200

def test_a3_113_opex_wind_200(client):
    assert _opex(client, _WIND).status_code == 200

def test_a3_114_opex_solar_canonical_total(client):
    d = _opex(client, _SOLAR).json()["data"]
    assert d["opex_y1_keur"] == pytest.approx(380.0)

def test_a3_115_opex_wind_canonical_total(client):
    d = _opex(client, _WIND).json()["data"]
    assert d["opex_y1_keur"] == pytest.approx(550.0)

def test_a3_116_opex_solar_seedable_total(client):
    d = _opex(client, _SOLAR).json()["data"]
    assert d["seedable_opex_y1_keur"] == pytest.approx(380.0)

def test_a3_117_opex_synthetic_disclosure(client):
    d = _opex(client, _SOLAR).json()["data"]
    assert d["synthetic_reference"] is True
    assert d["market_benchmark"] is False

def test_a3_118_opex_items_have_group_code(client):
    for key in (_SOLAR, _WIND):
        items = _opex(client, key).json()["data"]["items"]
        for it in items:
            assert "group_code" in it, f"Missing group_code in {it}"
            assert it["group_code"] is not None

def test_a3_119_opex_group_codes_from_seed_authority(client):
    items = _opex(client, _SOLAR).json()["data"]["items"]
    group_map = {it["canonical_key"]: it["group_code"] for it in items}
    assert group_map["Technical Management"] == "B.01"
    assert group_map["Maintenance"] == "B.02"
    assert group_map["Insurance"] == "B.06"
    assert group_map["Lease & Tax"] == "B.07"

def test_a3_120_opex_wind_group_codes(client):
    items = _opex(client, _WIND).json()["data"]["items"]
    group_map = {it["canonical_key"]: it["group_code"] for it in items}
    assert group_map["Technical Management"] == "B.01"
    assert group_map["Maintenance"] == "B.02"
    assert group_map["Insurance"] == "B.06"
    assert group_map["Lease & Tax"] == "B.07"

def test_a3_121_opex_annual_inflation_rate_decimal(client):
    items = _opex(client, _SOLAR).json()["data"]["items"]
    assert all(it["annual_inflation_rate"] == pytest.approx(0.02) for it in items)

def test_a3_122_opex_scaling_mode_per_mw(client):
    items = _opex(client, _SOLAR).json()["data"]["items"]
    assert all(it["scaling_mode"] == "PER_MW" for it in items)

def test_a3_123_opex_items_have_label_field(client):
    items = _opex(client, _SOLAR).json()["data"]["items"]
    assert all("label" in it for it in items)

def test_a3_124_opex_solar_technical_management_150(client):
    items = _opex(client, _SOLAR).json()["data"]["items"]
    tm = next(it for it in items if it["canonical_key"] == "Technical Management")
    assert tm["reference_amount_keur"] == pytest.approx(150.0)

def test_a3_125_opex_wind_technical_management_200(client):
    items = _opex(client, _WIND).json()["data"]["items"]
    tm = next(it for it in items if it["canonical_key"] == "Technical Management")
    assert tm["reference_amount_keur"] == pytest.approx(200.0)


# ── A3-126..A3-130: Full OPEX parity test ────────────────────────────────────

def test_a3_126_opex_solar_full_parity():
    """API OPEX items must match canonical_opex_reference_items() exactly."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.v1.router as _rm
    _app = FastAPI()
    _app.include_router(_rm.router, prefix="/api/v1")
    c = TestClient(_app)

    from app.api.v1.model_reference import get_pi
    from app.services.reference_seed_service import canonical_opex_reference_items

    pi = get_pi(_SOLAR)
    expected = canonical_opex_reference_items(pi)
    api_items = _opex(c, _SOLAR).json()["data"]["items"]
    api_by_key = {it["canonical_key"]: it for it in api_items}

    assert set(api_by_key.keys()) == set(expected.keys()), "OPEX item keys differ"
    for key, exp in expected.items():
        api = api_by_key[key]
        assert api["group_code"] == exp["group_code"]
        assert api["label"] == exp["label"]
        assert api["reference_amount_keur"] == pytest.approx(exp["reference_amount_keur"])
        assert api["unit_rate_keur_per_mw"] == pytest.approx(exp["unit_rate_keur_per_mw"])
        assert api["annual_inflation_rate"] == pytest.approx(exp["annual_inflation_rate"])
        assert api["scaling_mode"] == exp["scaling_mode"]


def test_a3_127_opex_wind_full_parity():
    """Same parity test for Wind."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.v1.router as _rm
    _app = FastAPI()
    _app.include_router(_rm.router, prefix="/api/v1")
    c = TestClient(_app)

    from app.api.v1.model_reference import get_pi
    from app.services.reference_seed_service import canonical_opex_reference_items

    pi = get_pi(_WIND)
    expected = canonical_opex_reference_items(pi)
    api_items = _opex(c, _WIND).json()["data"]["items"]
    api_by_key = {it["canonical_key"]: it for it in api_items}

    assert set(api_by_key.keys()) == set(expected.keys())
    for key, exp in expected.items():
        api = api_by_key[key]
        assert api["group_code"] == exp["group_code"]
        assert api["reference_amount_keur"] == pytest.approx(exp["reference_amount_keur"])


# ── A3-128..A3-137: Error semantics — no 400, everything unsupported → 404 ───

def test_a3_128_unknown_key_detail_404(client):
    assert _detail(client, "unknown_reference").status_code == 404

def test_a3_129_unknown_key_capex_404(client):
    assert _capex(client, "unknown_reference").status_code == 404

def test_a3_130_unknown_key_opex_404(client):
    assert _opex(client, "unknown_reference").status_code == 404

def test_a3_131_storage_key_detail_404(client):
    assert _detail(client, _STORAGE).status_code == 404

def test_a3_132_storage_key_capex_404(client):
    assert _capex(client, _STORAGE).status_code == 404

def test_a3_133_storage_key_opex_404(client):
    assert _opex(client, _STORAGE).status_code == 404

def test_a3_134_uppercase_key_404(client):
    assert _detail(client, "GENERIC_SOLAR_REFERENCE").status_code == 404

def test_a3_135_short_alias_404(client):
    assert _detail(client, "solar").status_code == 404

def test_a3_136_bad_dot_key_404(client):
    assert _detail(client, "bad.key").status_code == 404

def test_a3_137_error_body_has_model_reference_not_found(client):
    body = _detail(client, "solar").json()
    assert body["error"] == "MODEL_REFERENCE_NOT_FOUND"

def test_a3_138_error_has_api_version(client):
    body = _detail(client, "solar").json()
    assert body["api_version"] == "v1"

def test_a3_139_error_no_reference_key_field(client):
    body = _detail(client, "solar").json()
    assert "reference_key" not in body

def test_a3_140_no_400_returned(client):
    for key in (_STORAGE, "SOLAR", "Generic_Solar_Reference", "bad.key", "unknown"):
        assert _detail(client, key).status_code == 404, f"Expected 404 for {key!r}"


# ── A3-141..A3-149: Persistence tripwires ────────────────────────────────────

_PERSISTENCE_TARGETS = [
    ("app.services.project_library_service", "ensure_reference_models"),
    ("app.services.project_library_service", "create_working_copy"),
    ("app.persistence.projects_repository", "get_reference_by_template_source"),
    ("app.persistence.workspace_repository", "get_workspace_state"),
    ("app.persistence.workspace_repository", "save_workspace_state"),
    ("app.persistence.db", "get_cursor"),
]


def _tripwire_client(monkeypatch, module_path, attr_name):
    import importlib
    mod = importlib.import_module(module_path)

    def _raise(*a, **kw):
        raise AssertionError(f"A3 endpoint must NOT call {module_path}.{attr_name}")

    monkeypatch.setattr(mod, attr_name, _raise)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.v1.router as _rm
    _app = FastAPI()
    _app.include_router(_rm.router, prefix="/api/v1")
    return TestClient(_app)


@pytest.mark.parametrize("module_path,attr_name", _PERSISTENCE_TARGETS)
def test_a3_141_to_149_no_persistence_calls(monkeypatch, module_path, attr_name):
    c = _tripwire_client(monkeypatch, module_path, attr_name)
    assert _list(c).status_code == 200
    assert _detail(c, _SOLAR).status_code == 200
    assert _detail(c, _WIND).status_code == 200
    assert _capex(c, _SOLAR).status_code == 200
    assert _opex(c, _SOLAR).status_code == 200


# ── A3-150: Engine tripwire ───────────────────────────────────────────────────

def test_a3_150_no_engine_run_project_call(monkeypatch):
    """A3 GETs must never invoke app.api.project_runner.run_project."""
    import app.api.project_runner as _runner

    def _raise(*a, **kw):
        raise AssertionError("A3 endpoint must NOT call app.api.project_runner.run_project")

    monkeypatch.setattr(_runner, "run_project", _raise)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.api.v1.router as _rm
    _app = FastAPI()
    _app.include_router(_rm.router, prefix="/api/v1")
    c = TestClient(_app)

    assert _list(c).status_code == 200
    assert _detail(c, _SOLAR).status_code == 200
    assert _detail(c, _WIND).status_code == 200
    assert _capex(c, _SOLAR).status_code == 200
    assert _opex(c, _SOLAR).status_code == 200


# ── A3-151..A3-155: Determinism ──────────────────────────────────────────────

def test_a3_151_solar_detail_deterministic(client):
    r1 = _detail(client, _SOLAR).json()
    r2 = _detail(client, _SOLAR).json()
    assert r1 == r2

def test_a3_152_wind_detail_deterministic(client):
    r1 = _detail(client, _WIND).json()
    r2 = _detail(client, _WIND).json()
    assert r1 == r2

def test_a3_153_solar_capex_deterministic(client):
    r1 = _capex(client, _SOLAR).json()
    r2 = _capex(client, _SOLAR).json()
    assert r1 == r2

def test_a3_154_wind_capex_deterministic(client):
    assert _capex(client, _WIND).json() == _capex(client, _WIND).json()

def test_a3_155_opex_deterministic(client):
    assert _opex(client, _SOLAR).json() == _opex(client, _SOLAR).json()
    assert _opex(client, _WIND).json() == _opex(client, _WIND).json()


# ── A3-156..A3-162: Public state safety — no sensitive fields ─────────────────

_SENSITIVE_KEYS = {
    "user_id", "project_id", "workspace", "draft_snapshot", "saved_snapshot",
    "last_run", "run_id", "session", "cookie", "email", "raw_payload",
}

def _recursive_keys(obj) -> set:
    if isinstance(obj, dict):
        keys = set(obj.keys())
        for v in obj.values():
            keys |= _recursive_keys(v)
        return keys
    if isinstance(obj, list):
        keys = set()
        for item in obj:
            keys |= _recursive_keys(item)
        return keys
    return set()


def test_a3_156_list_no_sensitive_fields(client):
    keys = _recursive_keys(_list(client).json())
    assert _SENSITIVE_KEYS.isdisjoint(keys), f"Sensitive keys found: {_SENSITIVE_KEYS & keys}"

def test_a3_157_solar_detail_no_sensitive_fields(client):
    keys = _recursive_keys(_detail(client, _SOLAR).json())
    assert _SENSITIVE_KEYS.isdisjoint(keys), f"Sensitive keys found: {_SENSITIVE_KEYS & keys}"

def test_a3_158_wind_detail_no_sensitive_fields(client):
    keys = _recursive_keys(_detail(client, _WIND).json())
    assert _SENSITIVE_KEYS.isdisjoint(keys)

def test_a3_159_capex_no_sensitive_fields(client):
    keys = _recursive_keys(_capex(client, _SOLAR).json())
    assert _SENSITIVE_KEYS.isdisjoint(keys)

def test_a3_160_opex_no_sensitive_fields(client):
    keys = _recursive_keys(_opex(client, _SOLAR).json())
    assert _SENSITIVE_KEYS.isdisjoint(keys)

_PROHIBITED_PHRASES = [
    "market average", "real project", "real jurisdiction",
    "client calibration", "investment recommendation", "industry benchmark",
]

def test_a3_161_no_prohibited_phrases_in_json(client):
    for resp_fn in [lambda: _list(client), lambda: _detail(client, _SOLAR), lambda: _detail(client, _WIND)]:
        text = json.dumps(resp_fn().json()).lower()
        for phrase in _PROHIBITED_PHRASES:
            assert phrase not in text, f"Prohibited phrase {phrase!r} found in JSON"

def test_a3_162_false_not_null_bess_enabled(client):
    t = _detail(client, _SOLAR).json()["data"]["technical"]
    assert t["bess_enabled"] is False
    assert t["bess_enabled"] is not None


# ── A3-163..A3-170: OpenAPI acceptance ───────────────────────────────────────

def test_a3_163_openapi_has_model_references_list(client):
    paths = client.get("/openapi.json").json().get("paths", {})
    assert "/api/v1/model/references" in paths

def test_a3_164_openapi_has_model_references_detail(client):
    paths = client.get("/openapi.json").json().get("paths", {})
    assert "/api/v1/model/references/{reference_key}" in paths

def test_a3_165_openapi_has_model_references_capex(client):
    paths = client.get("/openapi.json").json().get("paths", {})
    assert "/api/v1/model/references/{reference_key}/capex" in paths

def test_a3_166_openapi_has_model_references_opex(client):
    paths = client.get("/openapi.json").json().get("paths", {})
    assert "/api/v1/model/references/{reference_key}/opex" in paths

def test_a3_167_openapi_list_is_get_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    methods = set(paths.get("/api/v1/model/references", {}).keys())
    assert methods == {"get"}

def test_a3_168_openapi_detail_is_get_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    methods = set(paths.get("/api/v1/model/references/{reference_key}", {}).keys())
    assert methods == {"get"}

def test_a3_169_openapi_capex_is_get_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    methods = set(paths.get("/api/v1/model/references/{reference_key}/capex", {}).keys())
    assert methods == {"get"}

def test_a3_170_openapi_detail_has_404_response(client):
    paths = client.get("/openapi.json").json()["paths"]
    responses = paths["/api/v1/model/references/{reference_key}"]["get"].get("responses", {})
    assert "404" in responses


# ── A3-171..A3-177: Meta capabilities ────────────────────────────────────────

def test_a3_171_meta_a3_list_capability(client):
    caps = client.get("/api/v1/meta").json()["capabilities"]
    assert "model.references.list" in caps

def test_a3_172_meta_a3_template_capability(client):
    caps = client.get("/api/v1/meta").json()["capabilities"]
    assert "model.references.template" in caps

def test_a3_173_meta_a3_capex_capability(client):
    caps = client.get("/api/v1/meta").json()["capabilities"]
    assert "model.references.capex" in caps

def test_a3_174_meta_a3_opex_capability(client):
    caps = client.get("/api/v1/meta").json()["capabilities"]
    assert "model.references.opex" in caps

def test_a3_175_meta_retains_a1_a2_capabilities(client):
    caps = set(client.get("/api/v1/meta").json()["capabilities"])
    a1_a2 = {
        "radar.assets.list", "radar.assets.identity", "radar.assets.fundamentals",
        "radar.assets.financials", "radar.assets.corporate_actions",
        "radar.assets.evidence", "radar.execution.simulation",
    }
    assert a1_a2.issubset(caps), f"Missing A1/A2 capabilities: {a1_a2 - caps}"

def test_a3_176_meta_execution_simulation_present(client):
    caps = client.get("/api/v1/meta").json()["capabilities"]
    assert "radar.execution.simulation" in caps

def test_a3_177_meta_200(client):
    assert client.get("/api/v1/meta").status_code == 200


# ── A3-178..A3-185: Unit/rate contract ───────────────────────────────────────

def test_a3_178_solar_capacity_is_64(client):
    d = _detail(client, _SOLAR).json()["data"]["technical"]
    assert d["capacity_mw"] == 64.0

def test_a3_179_wind_capacity_is_48(client):
    d = _detail(client, _WIND).json()["data"]["technical"]
    assert d["capacity_mw"] == 48.0

def test_a3_180_ppa_index_rate_decimal_not_percent(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["ppa_index_rate"] == pytest.approx(0.02)
    assert r["ppa_index_rate"] != 2

def test_a3_181_corporate_rate_decimal_not_percent(client):
    t = _detail(client, _SOLAR).json()["data"]["tax"]
    assert t["corporate_rate"] == pytest.approx(0.25)
    assert t["corporate_rate"] != 25

def test_a3_182_margin_bps_stays_basis_points(client):
    f = _detail(client, _SOLAR).json()["data"]["financing"]
    assert f["margin_bps"] == 250

def test_a3_183_amounts_stay_keur(client):
    items = _capex(client, _SOLAR).json()["data"]["items"]
    solar_mod = next(it for it in items if it["canonical_label"] == "Solar Modules")
    assert solar_mod["reference_amount_keur"] == pytest.approx(20_000.0)

def test_a3_184_ppa_tariff_stays_eur_mwh(client):
    r = _detail(client, _SOLAR).json()["data"]["revenue"]
    assert r["ppa_base_tariff_eur_mwh"] == pytest.approx(50.0)

def test_a3_185_inflation_stays_decimal_in_opex(client):
    items = _opex(client, _SOLAR).json()["data"]["items"]
    assert all(it["annual_inflation_rate"] == pytest.approx(0.02) for it in items)
    assert all(it["annual_inflation_rate"] != 2 for it in items)
