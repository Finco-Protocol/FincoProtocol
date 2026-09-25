"""A4 Model Reference Preview API — acceptance tests.

Tests A4-01 through A4-85 as specified, plus adversarial coverage.

Endpoint: POST /api/v1/model/references/{reference_key}/preview
Request:  {"capacity_mw": <finite positive number, 0 < x <= 10000>}
"""
from __future__ import annotations

import math
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import router as v1_router
from app.services.reference_seed_service import (
    canonical_capex_reference_items,
    canonical_opex_reference_items,
    get_reference_inputs,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(v1_router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


def _post(client, key: str, body: dict):
    return client.post(f"/api/v1/model/references/{key}/preview", json=body)


def _solar(client, capacity_mw):
    return _post(client, "generic_solar_reference", {"capacity_mw": capacity_mw})


def _wind(client, capacity_mw):
    return _post(client, "generic_wind_reference", {"capacity_mw": capacity_mw})


# ── A4-01..06  Route / OpenAPI ────────────────────────────────────────────────

def test_a4_01_route_exists(client):
    r = _solar(client, 64.0)
    assert r.status_code == 200


def test_a4_02_post_only_no_get(client):
    r = client.get("/api/v1/model/references/generic_solar_reference/preview")
    assert r.status_code == 405


def test_a4_03_openapi_request_schema(client):
    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/api/v1/model/references/{reference_key}/preview"]["post"]
    ref_name = op["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    req_schema = schema["components"]["schemas"][ref_name]
    props = req_schema.get("properties", {})
    assert "capacity_mw" in props
    assert props["capacity_mw"].get("type") == "number"
    assert props["capacity_mw"].get("exclusiveMinimum", -1) == 0


def test_a4_04_openapi_typed_200(client):
    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/api/v1/model/references/{reference_key}/preview"]["post"]
    assert "200" in op["responses"]
    assert "$ref" in str(op["responses"]["200"])


def test_a4_05_openapi_400(client):
    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/api/v1/model/references/{reference_key}/preview"]["post"]
    assert "400" in op["responses"]


def test_a4_06_openapi_404(client):
    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/api/v1/model/references/{reference_key}/preview"]["post"]
    assert "404" in op["responses"]


# ── A4-07..11  Supported / unsupported keys ───────────────────────────────────

def test_a4_07_solar_supported(client):
    r = _solar(client, 64.0)
    assert r.status_code == 200
    assert r.json()["reference_key"] == "generic_solar_reference"


def test_a4_08_wind_supported(client):
    r = _wind(client, 48.0)
    assert r.status_code == 200
    assert r.json()["reference_key"] == "generic_wind_reference"


def test_a4_09_storage_404(client):
    r = _post(client, "generic_storage_reference", {"capacity_mw": 100.0})
    assert r.status_code == 404
    assert r.json()["error"] == "MODEL_REFERENCE_NOT_FOUND"


def test_a4_10_alias_404(client):
    r = _post(client, "solar", {"capacity_mw": 64.0})
    assert r.status_code == 404


def test_a4_11_uppercase_404(client):
    r = _post(client, "SOLAR", {"capacity_mw": 64.0})
    assert r.status_code == 404


# ── A4-12..23  Capacity validation ────────────────────────────────────────────

def test_a4_12_capacity_integer_valid(client):
    r = _solar(client, 100)
    assert r.status_code == 200


def test_a4_13_capacity_float_valid(client):
    r = _solar(client, 100.0)
    assert r.status_code == 200


def test_a4_14_fractional_valid(client):
    r = _solar(client, 73.25)
    assert r.status_code == 200
    cap = r.json()["data"]["scaling"]["requested_capacity_mw"]
    assert cap == 73.25


def test_a4_15_zero_invalid(client):
    r = _solar(client, 0)
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_16_negative_invalid(client):
    r = _solar(client, -1)
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_17_string_invalid(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": "100"})
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_18_bool_invalid(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": True})
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_19_null_invalid(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": None})
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_20_missing_invalid(client):
    r = _post(client, "generic_solar_reference", {})
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_21_list_invalid(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": [64.0]})
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_22_object_invalid(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": {"value": 64.0}})
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_a4_23_over_max_invalid(client):
    r = _solar(client, 10_001.0)
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


# ── A4-24..26  No side effects on invalid input ────────────────────────────────

def test_a4_24_invalid_request_zero_db_calls(client, monkeypatch):
    import app.persistence.db as db_mod
    called = []
    monkeypatch.setattr(db_mod, "get_cursor", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("get_cursor called")))
    r = _solar(client, 0)
    assert r.status_code == 400
    assert not called


def test_a4_25_invalid_request_zero_project_creation(client, monkeypatch):
    import app.services.project_library_service as pls
    called = []
    monkeypatch.setattr(pls, "create_working_copy", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("create_working_copy called")))
    r = _solar(client, -5)
    assert r.status_code == 400
    assert not called


def test_a4_26_invalid_request_zero_engine_run(client, monkeypatch):
    import app.api.project_runner as pr
    called = []
    orig = getattr(pr, "run_project", None)
    monkeypatch.setattr(pr, "run_project", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("run_project called")))
    r = _solar(client, "bad")
    assert r.status_code == 400
    assert not called


# ── A4-27..31  Scaling ratios ─────────────────────────────────────────────────

def test_a4_27_solar_64_ratio_1(client):
    r = _solar(client, 64.0)
    scaling = r.json()["data"]["scaling"]
    assert scaling["scale_ratio"] == pytest.approx(1.0)
    assert scaling["reference_capacity_mw"] == 64.0
    assert scaling["requested_capacity_mw"] == 64.0


def test_a4_28_wind_48_ratio_1(client):
    r = _wind(client, 48.0)
    scaling = r.json()["data"]["scaling"]
    assert scaling["scale_ratio"] == pytest.approx(1.0)
    assert scaling["reference_capacity_mw"] == 48.0
    assert scaling["requested_capacity_mw"] == 48.0


def test_a4_29_solar_128_ratio_2(client):
    r = _solar(client, 128.0)
    scaling = r.json()["data"]["scaling"]
    assert scaling["scale_ratio"] == pytest.approx(2.0)


def test_a4_30_wind_24_ratio_0_5(client):
    r = _wind(client, 24.0)
    scaling = r.json()["data"]["scaling"]
    assert scaling["scale_ratio"] == pytest.approx(0.5)


def test_a4_31_fractional_ratio_exact(client):
    r = _solar(client, 73.25)
    scaling = r.json()["data"]["scaling"]
    assert scaling["scale_ratio"] == pytest.approx(73.25 / 64.0)


# ── A4-32..35  CAPEX totals ────────────────────────────────────────────────────

def test_a4_32_solar_reference_capex_total(client):
    r = _solar(client, 64.0)
    capex = r.json()["data"]["capex"]
    assert capex["reference_total_capex_keur"] == pytest.approx(33000.0)


def test_a4_33_solar_scaled_capex_total_128(client):
    r = _solar(client, 128.0)
    capex = r.json()["data"]["capex"]
    assert capex["reference_total_capex_keur"] == pytest.approx(33000.0)
    assert capex["scaled_total_capex_keur"] == pytest.approx(66000.0)


def test_a4_34_wind_reference_capex_total(client):
    r = _wind(client, 48.0)
    capex = r.json()["data"]["capex"]
    assert capex["reference_total_capex_keur"] == pytest.approx(43000.0)


def test_a4_35_wind_scaled_capex_total_24(client):
    r = _wind(client, 24.0)
    capex = r.json()["data"]["capex"]
    assert capex["scaled_total_capex_keur"] == pytest.approx(21500.0)


# ── A4-36..41  CAPEX items parity ─────────────────────────────────────────────

def test_a4_36_capex_row_count_parity_solar(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_capex_reference_items(pi)
    r = _solar(client, 64.0)
    items = r.json()["data"]["capex"]["items"]
    assert len(items) == len(expected)


def test_a4_37_capex_canonical_fields_parity(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected_fields = set(canonical_capex_reference_items(pi).keys())
    r = _solar(client, 64.0)
    actual_fields = {it["canonical_field"] for it in r.json()["data"]["capex"]["items"]}
    assert actual_fields == expected_fields


def test_a4_38_capex_owner_category_parity(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_capex_reference_items(pi)
    r = _solar(client, 64.0)
    actual = {it["canonical_field"]: it["owner_category_code"] for it in r.json()["data"]["capex"]["items"]}
    for field, item in expected.items():
        assert actual[field] == item["owner_category_code"]


def test_a4_39_capex_unit_rate_parity(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_capex_reference_items(pi)
    r = _solar(client, 64.0)
    actual = {it["canonical_field"]: it["unit_rate_keur_per_mw"] for it in r.json()["data"]["capex"]["items"]}
    for field, item in expected.items():
        assert actual[field] == pytest.approx(float(item["unit_rate_keur_per_mw"]))


def test_a4_40_capex_scaled_amount_causal_formula(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_capex_reference_items(pi)
    cap = 100.0
    r = _solar(client, cap)
    for it in r.json()["data"]["capex"]["items"]:
        expected_item = expected[it["canonical_field"]]
        rate = float(expected_item["unit_rate_keur_per_mw"])
        assert it["scaled_amount_keur"] == pytest.approx(rate * cap)


def test_a4_41_no_alias_duplication_solar(client):
    r = _solar(client, 64.0)
    fields = [it["canonical_field"] for it in r.json()["data"]["capex"]["items"]]
    assert len(fields) == len(set(fields)), "Duplicate canonical_field entries found"


# ── A4-42..47  OPEX items parity ──────────────────────────────────────────────

def test_a4_42_opex_row_count_parity_solar(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_opex_reference_items(pi)
    r = _solar(client, 64.0)
    items = r.json()["data"]["opex"]["items"]
    assert len(items) == len(expected)


def test_a4_43_opex_canonical_key_parity(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected_keys = set(canonical_opex_reference_items(pi).keys())
    r = _solar(client, 64.0)
    actual_keys = {it["canonical_key"] for it in r.json()["data"]["opex"]["items"]}
    assert actual_keys == expected_keys


def test_a4_44_opex_group_code_parity(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_opex_reference_items(pi)
    r = _solar(client, 64.0)
    actual = {it["canonical_key"]: it["group_code"] for it in r.json()["data"]["opex"]["items"]}
    for key, item in expected.items():
        assert actual[key] == item.get("group_code")


def test_a4_45_opex_unit_rate_parity(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_opex_reference_items(pi)
    r = _solar(client, 64.0)
    actual = {it["canonical_key"]: it["unit_rate_keur_per_mw"] for it in r.json()["data"]["opex"]["items"]}
    for key, item in expected.items():
        assert actual[key] == pytest.approx(float(item["unit_rate_keur_per_mw"]))


def test_a4_46_opex_inflation_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_opex_reference_items(pi)
    r_ref = _solar(client, 64.0)
    r_scaled = _solar(client, 128.0)
    ref_items = {it["canonical_key"]: it for it in r_ref.json()["data"]["opex"]["items"]}
    scaled_items = {it["canonical_key"]: it for it in r_scaled.json()["data"]["opex"]["items"]}
    for key in ref_items:
        assert ref_items[key]["annual_inflation_rate"] == scaled_items[key]["annual_inflation_rate"]


def test_a4_47_opex_scaled_amount_causal_formula(client):
    pi = get_reference_inputs("generic_solar_reference")
    expected = canonical_opex_reference_items(pi)
    cap = 100.0
    r = _solar(client, cap)
    for it in r.json()["data"]["opex"]["items"]:
        expected_item = expected[it["canonical_key"]]
        rate = float(expected_item["unit_rate_keur_per_mw"])
        assert it["scaled_amount_keur"] == pytest.approx(rate * cap)


# ── A4-48..53  Technical section ──────────────────────────────────────────────

def test_a4_48_technical_capacity_changes(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["technical"]["capacity_mw"] == 100.0


def test_a4_49_technical_p50_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    assert r.json()["data"]["technical"]["operating_hours_p50"] == pytest.approx(
        float(pi.technical.operating_hours_p50)
    )


def test_a4_50_technical_p90_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    expected = (
        float(pi.technical.operating_hours_p90_10y)
        if pi.technical.operating_hours_p90_10y is not None else None
    )
    assert r.json()["data"]["technical"]["operating_hours_p90_10y"] == expected


def test_a4_51_technical_p99_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    p99 = getattr(pi.technical, "operating_hours_p99_1y", None)
    expected = float(p99) if p99 is not None else None
    assert r.json()["data"]["technical"]["operating_hours_p99_1y"] == expected


def test_a4_52_horizon_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 100.0)
    assert r.json()["data"]["technical"]["horizon_years"] == int(pi.info.horizon_years)


def test_a4_53_construction_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 100.0)
    assert r.json()["data"]["technical"]["construction_months"] == int(pi.info.construction_months)


# ── A4-54..59  Preserved assumptions ──────────────────────────────────────────

def test_a4_54_ppa_tariff_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    rev = r.json()["data"]["preserved_assumptions"]["revenue"]
    assert rev["ppa_base_tariff_eur_mwh"] == pytest.approx(float(pi.revenue.ppa_base_tariff))


def test_a4_55_market_curve_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    rev = r.json()["data"]["preserved_assumptions"]["revenue"]
    expected_curve = [float(v) for v in pi.revenue.market_prices_curve]
    assert rev["market_prices_curve_eur_mwh"] == expected_curve


def test_a4_56_gearing_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    fin = r.json()["data"]["preserved_assumptions"]["financing"]
    assert fin["gearing_ratio"] == pytest.approx(float(pi.financing.gearing_ratio))


def test_a4_57_base_rate_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    fin = r.json()["data"]["preserved_assumptions"]["financing"]
    assert fin["base_rate"] == pytest.approx(float(pi.financing.base_rate))


def test_a4_58_margin_bps_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    fin = r.json()["data"]["preserved_assumptions"]["financing"]
    assert fin["margin_bps"] == int(pi.financing.margin_bps)


def test_a4_59_tax_rate_unchanged(client):
    pi = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 128.0)
    tax = r.json()["data"]["preserved_assumptions"]["tax"]
    assert tax["corporate_rate"] == pytest.approx(float(pi.tax.corporate_rate))


# ── A4-60..63  Semantic flags ──────────────────────────────────────────────────

def test_a4_60_project_created_false(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["scaling"]["project_created"] is False


def test_a4_61_engine_executed_false(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["scaling"]["engine_executed"] is False


def test_a4_62_synthetic_reference_true(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["identity"]["synthetic_reference"] is True
    assert r.json()["data"]["reference_semantics"]["synthetic_reference"] is True


def test_a4_63_market_benchmark_false(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["identity"]["market_benchmark"] is False
    assert r.json()["data"]["reference_semantics"]["market_benchmark"] is False


# ── A4-64..68  Tripwires ───────────────────────────────────────────────────────

_PERSISTENCE_TARGETS = [
    ("app.persistence.db", "get_cursor"),
    ("app.services.project_library_service", "ensure_reference_models"),
    ("app.persistence.projects_repository", "get_reference_by_template_source"),
    ("app.persistence.workspace_repository", "get_workspace_state"),
    ("app.persistence.workspace_repository", "save_workspace_state"),
]


@pytest.mark.parametrize("module_path,fn_name", _PERSISTENCE_TARGETS)
def test_a4_64_persistence_tripwire(client, monkeypatch, module_path, fn_name):
    import importlib
    mod = importlib.import_module(module_path)
    called = []

    def _raise(*a, **kw):
        called.append((module_path, fn_name))
        raise AssertionError(f"{module_path}.{fn_name} must not be called by A4 preview")

    monkeypatch.setattr(mod, fn_name, _raise)
    r = _solar(client, 100.0)
    assert r.status_code == 200, f"{fn_name} was called during valid A4 preview"
    assert not called


def test_a4_65_create_working_copy_tripwire(client, monkeypatch):
    import app.services.project_library_service as pls
    called = []
    monkeypatch.setattr(pls, "create_working_copy", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("create_working_copy called")))
    r = _solar(client, 64.0)
    assert r.status_code == 200
    assert not called


def test_a4_66_capex_write_tripwire(client, monkeypatch):
    import app.persistence.capex_sub_lines as cx
    called = []
    monkeypatch.setattr(cx, "create_sub_line", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("create_capex_line called")))
    r = _solar(client, 64.0)
    assert r.status_code == 200
    assert not called


def test_a4_67_opex_write_tripwire(client, monkeypatch):
    import app.persistence.opex_sub_lines as ox
    called = []
    monkeypatch.setattr(ox, "create_sub_line", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("create_opex_line called")))
    r = _solar(client, 64.0)
    assert r.status_code == 200
    assert not called


def test_a4_68_engine_run_tripwire(client, monkeypatch):
    import app.api.project_runner as pr
    called = []
    monkeypatch.setattr(pr, "run_project", lambda *a, **kw: called.append(1) or (_ for _ in ()).throw(AssertionError("run_project called")))
    r = _solar(client, 64.0)
    assert r.status_code == 200
    assert not called


# ── A4-69..70  Determinism / no mutation ──────────────────────────────────────

def test_a4_69_deterministic_repeated_request(client):
    r1 = _solar(client, 100.0)
    r2 = _solar(client, 100.0)
    assert r1.json() == r2.json()


def test_a4_70_no_mutation_across_different_capacities(client):
    r1 = _solar(client, 64.0)
    data1_before = r1.json()["data"]
    _solar(client, 128.0)
    r1_after = _solar(client, 64.0)
    assert r1_after.json()["data"] == data1_before


# ── A4-71..73  No private / user / workspace fields ───────────────────────────

_PROHIBITED_KEYS = frozenset({
    "user_id", "project_id", "project_name", "workspace", "session",
    "run_id", "last_run", "export_id", "saved_snapshot", "draft_snapshot",
    "_reference_seed_profile", "reference_project_id",
})

_PROHIBITED_PHRASES = frozenset({
    "market average", "real project", "real jurisdiction",
    "client calibration", "investment recommendation",
})


def _collect_keys(obj, found: set) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            _collect_keys(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, found)


def test_a4_71_no_user_project_workspace_fields(client):
    r = _solar(client, 100.0)
    all_keys: set = set()
    _collect_keys(r.json(), all_keys)
    for prohibited in _PROHIBITED_KEYS:
        assert prohibited not in all_keys, f"Prohibited key '{prohibited}' found in response"


def test_a4_72_no_private_seed_profile_fields(client):
    r = _solar(client, 100.0)
    text = r.text
    assert "_reference_seed_profile" not in text
    assert "reference_project_id" not in text


def test_a4_73_no_prohibited_benchmark_language(client):
    r = _solar(client, 100.0)
    text = r.text.lower()
    for phrase in _PROHIBITED_PHRASES:
        assert phrase.lower() not in text, f"Prohibited phrase '{phrase}' found in response"


# ── A4-74..76  Numeric safety ─────────────────────────────────────────────────

def _collect_floats(obj) -> list:
    result = []
    if isinstance(obj, float):
        result.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            result.extend(_collect_floats(v))
    elif isinstance(obj, list):
        for item in obj:
            result.extend(_collect_floats(item))
    return result


def test_a4_74_all_numeric_outputs_finite(client):
    r = _solar(client, 100.0)
    for f in _collect_floats(r.json()):
        assert math.isfinite(f), f"Non-finite float {f!r} found in response"


def test_a4_75_zero_not_null(client):
    r = _solar(client, 64.0)
    data = r.json()["data"]
    assert data["scaling"]["project_created"] is False
    assert data["scaling"]["engine_executed"] is False


def test_a4_76_false_not_null(client):
    r = _solar(client, 64.0)
    assert r.json()["data"]["identity"]["market_benchmark"] is False


# ── A4-77..80  Meta capabilities ──────────────────────────────────────────────

def test_a4_77_meta_has_preview_capability(client):
    r = client.get("/api/v1/meta")
    caps = r.json()["capabilities"]
    assert "model.references.preview" in caps


def test_a4_78_a1_capabilities_retained(client):
    r = client.get("/api/v1/meta")
    caps = r.json()["capabilities"]
    for cap in ["radar.assets.list", "radar.assets.identity", "radar.assets.fundamentals",
                "radar.assets.financials", "radar.assets.corporate_actions", "radar.assets.evidence"]:
        assert cap in caps, f"A1 capability '{cap}' missing"


def test_a4_79_a2_capability_retained(client):
    r = client.get("/api/v1/meta")
    assert "radar.execution.simulation" in r.json()["capabilities"]


def test_a4_80_a3_capabilities_retained(client):
    r = client.get("/api/v1/meta")
    caps = r.json()["capabilities"]
    for cap in ["model.references.list", "model.references.template",
                "model.references.capex", "model.references.opex"]:
        assert cap in caps, f"A3 capability '{cap}' missing"


# ── A4-81..85  Regression ─────────────────────────────────────────────────────

def test_a4_81_a1_regression(client):
    r = client.get("/api/v1/radar/assets")
    assert r.status_code in (200, 503)


def test_a4_82_a2_regression(client):
    r = client.post(
        "/api/v1/radar/assets/test-uid-123/execution-simulation",
        json={"direction": "BUY", "notional_usd": "100"},
    )
    assert r.status_code in (200, 400, 404, 503)


def test_a4_83_a3_regression(client):
    r = client.get("/api/v1/model/references")
    assert r.status_code == 200
    assert r.json()["data"]["count"] == 3


def test_a4_84_reference_seed_regression(client):
    from app.services.reference_seed_service import (
        canonical_capex_reference_items,
        canonical_opex_reference_items,
        get_reference_inputs,
    )
    pi_s = get_reference_inputs("generic_solar_reference")
    pi_w = get_reference_inputs("generic_wind_reference")
    assert float(pi_s.capex.total_capex) == pytest.approx(33000.0)
    assert float(pi_w.capex.total_capex) == pytest.approx(43000.0)
    assert len(canonical_capex_reference_items(pi_s)) == 5
    assert len(canonical_opex_reference_items(pi_s)) == 4
    assert len(canonical_capex_reference_items(pi_w)) == 4
    assert len(canonical_opex_reference_items(pi_w)) == 4


def test_a4_85_identity_section_from_factory(client):
    pi_s = get_reference_inputs("generic_solar_reference")
    r = _solar(client, 100.0)
    identity = r.json()["data"]["identity"]
    assert identity["name"] == pi_s.info.name
    assert identity["reference_code"] == pi_s.info.code
    assert identity["technology"] == "solar"


# ── Adversarial / extra ────────────────────────────────────────────────────────

def test_a4_extra_01_reference_capacity_identity_solar(client):
    pi = get_reference_inputs("generic_solar_reference")
    cap = float(pi.technical.capacity_mw)
    r = _solar(client, cap)
    d = r.json()["data"]
    capex_items = canonical_capex_reference_items(pi)
    for it in d["capex"]["items"]:
        ref_amt = next(v["reference_amount_keur"] for k, v in capex_items.items() if k == it["canonical_field"])
        assert it["scaled_amount_keur"] == pytest.approx(ref_amt)
    assert d["capex"]["scaled_total_capex_keur"] == pytest.approx(d["capex"]["reference_total_capex_keur"])


def test_a4_extra_02_reference_capacity_identity_wind(client):
    pi = get_reference_inputs("generic_wind_reference")
    cap = float(pi.technical.capacity_mw)
    r = _wind(client, cap)
    d = r.json()["data"]
    assert d["capex"]["scaled_total_capex_keur"] == pytest.approx(d["capex"]["reference_total_capex_keur"])
    assert d["opex"]["scaled_opex_y1_keur"] == pytest.approx(d["opex"]["reference_opex_y1_keur"])


def test_a4_extra_03_solar_opex_doubles_at_128(client):
    r_ref = _solar(client, 64.0)
    r_dbl = _solar(client, 128.0)
    ref_y1 = r_ref.json()["data"]["opex"]["scaled_opex_y1_keur"]
    dbl_y1 = r_dbl.json()["data"]["opex"]["scaled_opex_y1_keur"]
    assert dbl_y1 == pytest.approx(ref_y1 * 2.0)


def test_a4_extra_04_wind_capex_halves_at_24(client):
    r_ref = _wind(client, 48.0)
    r_half = _wind(client, 24.0)
    ref_capex = r_ref.json()["data"]["capex"]["scaled_total_capex_keur"]
    half_capex = r_half.json()["data"]["capex"]["scaled_total_capex_keur"]
    assert half_capex == pytest.approx(ref_capex * 0.5)


def test_a4_extra_05_scaling_mode_disclosure(client):
    r = _solar(client, 100.0)
    for it in r.json()["data"]["capex"]["items"]:
        assert it["scaling_mode"] == "PER_MW"
    for it in r.json()["data"]["opex"]["items"]:
        assert it["scaling_mode"] == "PER_MW"


def test_a4_extra_06_preview_only_flag(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["reference_semantics"]["preview_only"] is True


def test_a4_extra_07_scaling_authority_label(client):
    r = _solar(client, 100.0)
    assert r.json()["data"]["reference_semantics"]["scaling_authority"] == "REFERENCE_SEED"


def test_a4_extra_08_capacity_10000_accepted(client):
    r = _solar(client, 10_000.0)
    assert r.status_code == 200


def test_a4_extra_09_wind_opex_group_codes(client):
    r = _wind(client, 48.0)
    codes = {it["group_code"] for it in r.json()["data"]["opex"]["items"]}
    assert codes == {"B.01", "B.02", "B.06", "B.07"}


def test_a4_extra_10_envelope_has_api_version(client):
    r = _solar(client, 64.0)
    assert r.json()["api_version"] == "v1"
    assert r.json()["state"] == "AVAILABLE"


# ── Correction A: C01–C18 ─────────────────────────────────────────────────────

# C01–C02: Public semantics — preview_granularity and detail_catalog_authority

def test_c01_preview_granularity_canonical_parent_solar(client):
    r = _solar(client, 64.0)
    assert r.json()["data"]["reference_semantics"]["preview_granularity"] == "CANONICAL_PARENT"


def test_c02_detail_catalog_authority_public_generic_v1_solar(client):
    r = _solar(client, 64.0)
    assert r.json()["data"]["reference_semantics"]["detail_catalog_authority"] == "PUBLIC_GENERIC_DETAIL_V1"


def test_c02b_preview_granularity_canonical_parent_wind(client):
    r = _wind(client, 48.0)
    assert r.json()["data"]["reference_semantics"]["preview_granularity"] == "CANONICAL_PARENT"


def test_c02c_detail_catalog_authority_wind(client):
    r = _wind(client, 48.0)
    assert r.json()["data"]["reference_semantics"]["detail_catalog_authority"] == "PUBLIC_GENERIC_DETAIL_V1"


# C03–C06: min_llcr preserved financing assumption

def test_c03_min_llcr_present_solar(client):
    r = _solar(client, 64.0)
    assert "min_llcr" in r.json()["data"]["preserved_assumptions"]["financing"]


def test_c04_min_llcr_present_wind(client):
    r = _wind(client, 48.0)
    assert "min_llcr" in r.json()["data"]["preserved_assumptions"]["financing"]


def test_c05_min_llcr_is_float(client):
    r = _solar(client, 64.0)
    v = r.json()["data"]["preserved_assumptions"]["financing"]["min_llcr"]
    assert isinstance(v, (int, float))
    assert v > 0


def test_c06_min_llcr_value_solar(client):
    from app.api.v1.model_reference import get_pi as _get_pi
    pi = _get_pi("generic_solar_reference")
    expected = float(pi.financing.min_llcr)
    r = _solar(client, 64.0)
    actual = r.json()["data"]["preserved_assumptions"]["financing"]["min_llcr"]
    assert actual == pytest.approx(expected)


# C07–C10: Strict extra-field rejection + OpenAPI

def test_c07_extra_field_returns_400(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": 100.0, "extra_field": "bad"})
    assert r.status_code == 400


def test_c08_extra_field_error_code(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": 100.0, "extra_field": "bad"})
    assert r.json()["error"] == "MODEL_PREVIEW_REQUEST_INVALID"


def test_c09_extra_field_stable_detail_no_echo(client):
    r = _post(client, "generic_solar_reference", {"capacity_mw": 100.0, "bogus_key": 1})
    detail = r.json()["detail"]
    assert detail == "Only capacity_mw is accepted."
    assert "bogus_key" not in detail


def test_c09b_extra_field_sentinel_absent_from_response(client):
    sentinel = "SENTINEL_MUST_NOT_APPEAR_IN_RESPONSE_XYZ"
    r = _post(client, "generic_solar_reference", {"capacity_mw": 100.0, sentinel: "v"})
    assert sentinel not in r.text


def test_c10_openapi_additional_properties_false(client):
    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/api/v1/model/references/{reference_key}/preview"]["post"]
    ref_name = op["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    req_schema = schema["components"]["schemas"][ref_name]
    assert req_schema.get("additionalProperties") is False


# C11–C14: CAPEX/OPEX parent-child reconciliation at reference capacity

def test_c11_solar_capex_parent_equals_detail_child_sum(client):
    from app.reference_detail_catalog import capex_children, allocate_parent_amount
    r = _solar(client, 64.0)
    items = r.json()["data"]["capex"]["items"]
    for item in items:
        code = item["owner_category_code"]
        parent_amt = item["reference_amount_keur"]
        children = capex_children("solar", code)
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(parent_amt, children))
        assert child_sum == pytest.approx(parent_amt), f"{code}: parent={parent_amt} child_sum={child_sum}"


def test_c12_wind_capex_parent_equals_detail_child_sum(client):
    from app.reference_detail_catalog import capex_children, allocate_parent_amount
    r = _wind(client, 48.0)
    items = r.json()["data"]["capex"]["items"]
    for item in items:
        code = item["owner_category_code"]
        parent_amt = item["reference_amount_keur"]
        children = capex_children("wind", code)
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(parent_amt, children))
        assert child_sum == pytest.approx(parent_amt), f"{code}: parent={parent_amt} child_sum={child_sum}"


def test_c13_solar_opex_parent_equals_detail_child_sum(client):
    from app.reference_detail_catalog import opex_children, allocate_parent_amount
    r = _solar(client, 64.0)
    items = r.json()["data"]["opex"]["items"]
    for item in items:
        group = item.get("group_code")
        if group is None:
            continue
        parent_amt = item["reference_amount_keur"]
        children = opex_children(group, "solar")
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(parent_amt, children))
        assert child_sum == pytest.approx(parent_amt), f"{group}: parent={parent_amt} child_sum={child_sum}"


def test_c14_wind_opex_parent_equals_detail_child_sum(client):
    from app.reference_detail_catalog import opex_children, allocate_parent_amount
    r = _wind(client, 48.0)
    items = r.json()["data"]["opex"]["items"]
    for item in items:
        group = item.get("group_code")
        if group is None:
            continue
        parent_amt = item["reference_amount_keur"]
        children = opex_children(group, "wind")
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(parent_amt, children))
        assert child_sum == pytest.approx(parent_amt), f"{group}: parent={parent_amt} child_sum={child_sum}"


# C15–C18: Scaled child sums reconcile to scaled A4 parent amounts

def test_c15_solar_scaled_capex_child_sum_reconciles(client):
    from app.reference_detail_catalog import capex_children, allocate_parent_amount
    r = _solar(client, 128.0)
    items = r.json()["data"]["capex"]["items"]
    for item in items:
        code = item["owner_category_code"]
        scaled_amt = item["scaled_amount_keur"]
        children = capex_children("solar", code)
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(scaled_amt, children))
        assert child_sum == pytest.approx(scaled_amt), f"{code}: scaled={scaled_amt} child_sum={child_sum}"


def test_c16_wind_scaled_capex_child_sum_reconciles(client):
    from app.reference_detail_catalog import capex_children, allocate_parent_amount
    r = _wind(client, 24.0)
    items = r.json()["data"]["capex"]["items"]
    for item in items:
        code = item["owner_category_code"]
        scaled_amt = item["scaled_amount_keur"]
        children = capex_children("wind", code)
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(scaled_amt, children))
        assert child_sum == pytest.approx(scaled_amt), f"{code}: scaled={scaled_amt} child_sum={child_sum}"


def test_c17_solar_scaled_opex_child_sum_reconciles(client):
    from app.reference_detail_catalog import opex_children, allocate_parent_amount
    r = _solar(client, 128.0)
    items = r.json()["data"]["opex"]["items"]
    for item in items:
        group = item.get("group_code")
        if group is None:
            continue
        scaled_amt = item["scaled_amount_keur"]
        children = opex_children(group, "solar")
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(scaled_amt, children))
        assert child_sum == pytest.approx(scaled_amt), f"{group}: scaled={scaled_amt} child_sum={child_sum}"


def test_c18_wind_scaled_opex_child_sum_reconciles(client):
    from app.reference_detail_catalog import opex_children, allocate_parent_amount
    r = _wind(client, 24.0)
    items = r.json()["data"]["opex"]["items"]
    for item in items:
        group = item.get("group_code")
        if group is None:
            continue
        scaled_amt = item["scaled_amount_keur"]
        children = opex_children(group, "wind")
        child_sum = sum(float(ca) for _, ca in allocate_parent_amount(scaled_amt, children))
        assert child_sum == pytest.approx(scaled_amt), f"{group}: scaled={scaled_amt} child_sum={child_sum}"
