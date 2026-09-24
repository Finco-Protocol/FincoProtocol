"""A5 Model Reference Run API — acceptance tests.

Endpoint: POST /api/v1/model/references/{reference_key}/run
Request:  {"capacity_mw": <finite positive number, 0 < x <= 10000>}

Test groups:
  A5-01–A5-15  Path-parameter 404 validation
  A5-16–A5-30  Request-body 400 validation
  A5-31–A5-50  Successful run: response shape + authority fields
  A5-51–A5-65  Scaling integrity (ratio, CAPEX totals)
  A5-66–A5-80  Persistence isolation (no DB mutations)
  A5-81–A5-90  Concurrency semaphore
  A5-91–A5-99  Meta capabilities list
"""
from __future__ import annotations

import math
import threading
import unittest.mock as mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import router as v1_router
from app.services.reference_seed_service import get_reference_inputs


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(v1_router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def solar_run(client):
    """Canonical Solar run at reference capacity (64 MW). Cached per session."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def wind_run(client):
    """Canonical Wind run at reference capacity (48 MW). Cached per session."""
    r = client.post(
        "/api/v1/model/references/generic_wind_reference/run",
        json={"capacity_mw": 48.0},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── A5-01–A5-15: 404 path validation ──────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "generic_storage_reference",
    "solar",
    "wind",
    "Solar",
    "Wind",
    "GENERIC_SOLAR_REFERENCE",
    "generic_solar",
    "generic_wind",
    "storage",
    "unknown_key",
    "generic_solar_reference_v2",
    "",  # handled at path level — may be 404 or 405
    "null",
    "true",
    "1234",
])
def test_unsupported_reference_key_returns_404(client, key):
    """A5-01–A5-15: Keys outside VALID_REFERENCE_KEYS must return 404."""
    if key == "":
        # empty path segment — framework-level 404/405; not our error body
        return
    r = client.post(
        f"/api/v1/model/references/{key}/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "MODEL_REFERENCE_NOT_FOUND"
    assert body["api_version"] == "v1"


# ── A5-16–A5-30: 400 request validation ───────────────────────────────────────

@pytest.mark.parametrize("payload,description", [
    ({}, "missing capacity_mw"),
    ({"capacity_mw": None}, "null"),
    ({"capacity_mw": "100"}, "string"),
    ({"capacity_mw": "64.0"}, "string float"),
    ({"capacity_mw": True}, "boolean true"),
    ({"capacity_mw": False}, "boolean false"),
    ({"capacity_mw": 0}, "zero"),
    ({"capacity_mw": -1}, "negative"),
    ({"capacity_mw": -0.001}, "small negative"),
    ({"capacity_mw": 10001}, "above max"),
    ({"capacity_mw": 10000.01}, "above max decimal"),
    ({"capacity_mw": [64]}, "array"),
    ({"capacity_mw": {"v": 64}}, "object"),
    ({"capacity_mw": 64, "extra_field": 1}, "extra field"),
    ({"capacity_mw": 64, "a": 1, "b": 2}, "two extra fields"),
])
def test_invalid_request_returns_400(client, payload, description):
    """A5-16–A5-30: Invalid request bodies must return 400 MODEL_RUN_REQUEST_INVALID."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json=payload,
    )
    assert r.status_code == 400, f"Expected 400 for {description}, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"] == "MODEL_RUN_REQUEST_INVALID"
    assert body["api_version"] == "v1"
    assert "detail" in body


def test_no_pydantic_422_for_invalid_capacity(client):
    """A5: Pydantic must never emit 422 — handler owns all 400 responses."""
    for payload in [
        {"capacity_mw": "string"},
        {"capacity_mw": True},
        {"capacity_mw": None},
        {"capacity_mw": []},
    ]:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json=payload,
        )
        assert r.status_code != 422, f"Got unexpected 422 for {payload}"


# ── A5-31–A5-50: Response shape and authority fields ──────────────────────────

def test_solar_run_envelope(solar_run):
    """A5-31: Outer envelope must have correct shape."""
    assert solar_run["api_version"] == "v1"
    assert solar_run["state"] == "AVAILABLE"
    assert solar_run["reference_key"] == "generic_solar_reference"
    assert isinstance(solar_run["data"], dict)


def test_run_data_top_level_keys(solar_run):
    """A5-32: data must contain all required top-level sections."""
    data = solar_run["data"]
    for key in ("identity", "scaling", "capex", "opex", "results",
                "preserved_assumptions", "authority"):
        assert key in data, f"Missing section: {key}"


def test_identity_section(solar_run):
    """A5-33: identity section must have correct values for solar reference."""
    identity = solar_run["data"]["identity"]
    assert identity["reference_key"] == "generic_solar_reference"
    assert identity["technology"] == "solar"
    assert identity["synthetic_reference"] is True
    assert identity["market_benchmark"] is False


def test_scaling_section_at_canonical_capacity(solar_run):
    """A5-34: At canonical Solar capacity (64 MW) scale_ratio must be 1.0."""
    scaling = solar_run["data"]["scaling"]
    assert scaling["reference_capacity_mw"] == 64.0
    assert scaling["requested_capacity_mw"] == 64.0
    assert abs(scaling["scale_ratio"] - 1.0) < 1e-9
    assert scaling["project_created"] is False
    assert scaling["engine_executed"] is True
    assert scaling["db_writes"] is False
    assert scaling["stateless"] is True


def test_authority_section(solar_run):
    """A5-35: authority section must confirm clean G2C execution and full M8 disclosure."""
    authority = solar_run["data"]["authority"]
    assert authority["runtime_authority"] == "clean_g2c"
    assert authority["calculation_count"] == 1
    assert authority["scenario"] == "Base"
    assert authority["engine_executed"] is True
    assert authority["project_created"] is False
    assert authority["stateless"] is True
    assert authority["synthetic_reference"] is True
    assert authority["market_benchmark"] is False
    assert authority["scenario_created"] is False
    assert authority["workspace_mutated"] is False
    assert authority["persisted"] is False


def test_results_kpi_fields_present(solar_run):
    """A5-36: results must include all expected KPI fields."""
    results = solar_run["data"]["results"]
    for field in (
        "project_irr", "equity_irr", "sponsor_irr",
        "project_npv_keur", "min_dscr", "avg_dscr", "min_llcr",
        "total_revenue_keur", "total_ebitda_keur", "total_opex_keur",
        "total_tax_keur", "total_capex_keur",
    ):
        assert field in results, f"Missing KPI field: {field}"


def test_results_irr_are_finite_or_none(solar_run):
    """A5-37: IRR fields must be finite floats or None — never NaN/Inf."""
    results = solar_run["data"]["results"]
    for field in ("project_irr", "equity_irr", "sponsor_irr"):
        v = results[field]
        if v is not None:
            assert math.isfinite(v), f"{field} is not finite: {v}"


def test_results_dscr_positive(solar_run):
    """A5-38: min_dscr and avg_dscr must be positive when present."""
    results = solar_run["data"]["results"]
    if results["min_dscr"] is not None:
        assert results["min_dscr"] > 0
    if results["avg_dscr"] is not None:
        assert results["avg_dscr"] > 0


def test_preserved_assumptions_present(solar_run):
    """A5-39: preserved_assumptions must have revenue, financing, tax."""
    pa = solar_run["data"]["preserved_assumptions"]
    assert "revenue" in pa
    assert "financing" in pa
    assert "tax" in pa


def test_preserved_assumptions_match_a3_revenue(client, solar_run):
    """A5-40: revenue preserved_assumptions must match the A3 reference endpoint."""
    a3_r = client.get("/api/v1/model/references/generic_solar_reference")
    assert a3_r.status_code == 200
    a3_revenue = a3_r.json()["data"]["revenue"]
    run_revenue = solar_run["data"]["preserved_assumptions"]["revenue"]
    assert run_revenue == a3_revenue


def test_capex_section_present(solar_run):
    """A5-41: capex section in data must have summary fields and items list."""
    capex = solar_run["data"]["capex"]
    assert "reference_total_capex_keur" in capex
    assert "scaled_total_capex_keur" in capex
    assert isinstance(capex["items"], list)
    assert len(capex["items"]) > 0


def test_opex_section_present(solar_run):
    """A5-42: opex section in data must have summary fields and items list."""
    opex = solar_run["data"]["opex"]
    assert "reference_opex_y1_keur" in opex
    assert "scaled_opex_y1_keur" in opex
    assert isinstance(opex["items"], list)
    assert len(opex["items"]) > 0


def test_wind_run_identity(wind_run):
    """A5-43: Wind run identity section must reflect wind technology."""
    identity = wind_run["data"]["identity"]
    assert identity["reference_key"] == "generic_wind_reference"
    assert identity["technology"] == "wind"


def test_wind_run_authority(wind_run):
    """A5-44: Wind run authority must confirm clean_g2c and calculation_count=1."""
    authority = wind_run["data"]["authority"]
    assert authority["runtime_authority"] == "clean_g2c"
    assert authority["calculation_count"] == 1


# ── A5-51–A5-65: Scaling integrity ────────────────────────────────────────────

def test_solar_2x_scale_ratio(client):
    """A5-51: Solar at 128 MW must produce scale_ratio = 2.0."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 128.0},
    )
    assert r.status_code == 200
    scaling = r.json()["data"]["scaling"]
    assert scaling["reference_capacity_mw"] == 64.0
    assert scaling["requested_capacity_mw"] == 128.0
    assert abs(scaling["scale_ratio"] - 2.0) < 1e-9


def test_solar_2x_capex_doubles(client, solar_run):
    """A5-52: At 2× capacity, scaled_total_capex must be 2× reference total."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 128.0},
    )
    assert r.status_code == 200
    ref_capex = solar_run["data"]["capex"]["reference_total_capex_keur"]
    scaled_capex = r.json()["data"]["capex"]["scaled_total_capex_keur"]
    assert abs(scaled_capex - ref_capex * 2.0) < 0.01


def test_solar_half_scale(client, solar_run):
    """A5-53: Solar at 32 MW must produce scale_ratio = 0.5."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 32.0},
    )
    assert r.status_code == 200
    scaling = r.json()["data"]["scaling"]
    assert abs(scaling["scale_ratio"] - 0.5) < 1e-9


def test_wind_2x_scale_ratio(client):
    """A5-54: Wind at 96 MW must produce scale_ratio = 2.0."""
    r = client.post(
        "/api/v1/model/references/generic_wind_reference/run",
        json={"capacity_mw": 96.0},
    )
    assert r.status_code == 200
    scaling = r.json()["data"]["scaling"]
    assert scaling["reference_capacity_mw"] == 48.0
    assert abs(scaling["scale_ratio"] - 2.0) < 1e-9


def test_canonical_capacity_scale_ratio_is_1(solar_run, wind_run):
    """A5-55: At canonical capacity, scale_ratio must be exactly 1.0."""
    assert abs(solar_run["data"]["scaling"]["scale_ratio"] - 1.0) < 1e-9
    assert abs(wind_run["data"]["scaling"]["scale_ratio"] - 1.0) < 1e-9


def test_canonical_capacity_capex_matches_reference(solar_run):
    """A5-56: At canonical capacity, scaled and reference CAPEX totals must match."""
    capex = solar_run["data"]["capex"]
    assert abs(capex["scaled_total_capex_keur"] - capex["reference_total_capex_keur"]) < 0.01


def test_results_total_capex_matches_scaling(client):
    """A5-57: results.total_capex_keur must equal capex.scaled_total_capex_keur."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 100.0},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert abs(
        data["results"]["total_capex_keur"] - data["capex"]["scaled_total_capex_keur"]
    ) < 0.01


def test_technical_capacity_matches_request(client):
    """A5-58: The returned scaling.requested_capacity_mw must equal the input."""
    for cap in [50.0, 100.0, 200.0]:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": cap},
        )
        assert r.status_code == 200
        assert r.json()["data"]["scaling"]["requested_capacity_mw"] == cap


# ── A5-66–A5-80: Persistence isolation ────────────────────────────────────────

def test_run_does_not_create_project(client):
    """A5-66: Run must never create a project record (project_created=False)."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 200
    assert r.json()["data"]["scaling"]["project_created"] is False


def test_run_has_no_db_writes(client):
    """A5-67: Run must declare no DB writes and not be persisted."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["scaling"]["db_writes"] is False
    assert data["authority"]["persisted"] is False
    assert data["authority"]["workspace_mutated"] is False


def test_run_does_not_call_execute_run_route(client):
    """A5-68: execute_run_route (browser persistence service) must never be called."""
    with mock.patch("app.services.run_service.execute_run_route") as patched:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 200
        patched.assert_not_called()


def test_run_does_not_call_create_reference_seeded_project(client):
    """A5-69: create_reference_seeded_project (DB seed) must never be called."""
    with mock.patch(
        "app.services.reference_seed_service.create_reference_seeded_project"
    ) as patched:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 200
        patched.assert_not_called()


# ── A5-81–A5-90: Concurrency semaphore ────────────────────────────────────────

def test_semaphore_exhaustion_returns_503(client):
    """A5-81: When semaphore is exhausted, endpoint must return 503."""
    import app.api.v1.run_limiter as limiter_mod

    original = limiter_mod._semaphore
    try:
        # Replace with a BoundedSemaphore already fully acquired
        import threading
        sem = threading.BoundedSemaphore(1)
        sem.acquire()  # exhaust it
        limiter_mod._semaphore = sem

        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 503
        assert r.json()["error"] == "MODEL_RUN_CAPACITY_EXHAUSTED"
    finally:
        limiter_mod._semaphore = original


def test_semaphore_released_after_successful_run():
    """A5-82: Semaphore must be released after a successful run."""
    from app.api.v1.run_limiter import acquire_run_slot, release_run_slot
    import app.api.v1.run_limiter as limiter_mod

    original = limiter_mod._semaphore
    try:
        import threading
        sem = threading.BoundedSemaphore(1)
        limiter_mod._semaphore = sem

        acquired = acquire_run_slot()
        assert acquired
        release_run_slot()
        # Must be re-acquirable after release
        acquired_again = acquire_run_slot()
        assert acquired_again
        release_run_slot()
    finally:
        limiter_mod._semaphore = original


def test_semaphore_released_on_engine_exception(client):
    """A5-83: Semaphore must be released even when unexpected exception propagates as 500."""
    import app.api.v1.run_limiter as limiter_mod
    import app.api.v1.model_run as model_run_mod

    original_sem = limiter_mod._semaphore
    try:
        import threading
        sem = threading.BoundedSemaphore(2)
        limiter_mod._semaphore = sem

        with mock.patch.object(
            model_run_mod,
            "build_run_response_data",
            side_effect=RuntimeError("PROGRAMMING_SENTINEL"),
        ):
            r = client.post(
                "/api/v1/model/references/generic_solar_reference/run",
                json={"capacity_mw": 64.0},
            )
            # Unexpected RuntimeError propagates as 500 (not caught by typed handlers)
            assert r.status_code == 500, f"Expected 500, got {r.status_code}"

        # After the failed call, semaphore must be re-acquirable (was released in finally)
        acquired = sem.acquire(blocking=False)
        assert acquired, "Semaphore was not released after engine exception"
        sem.release()
    finally:
        limiter_mod._semaphore = original_sem


# ── A5-91–A5-99: Meta capabilities ────────────────────────────────────────────

def test_meta_includes_model_references_run(client):
    """A5-91: /meta capabilities list must include model.references.run."""
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    caps = r.json()["capabilities"]
    assert "model.references.run" in caps


def test_meta_retains_preview_capability(client):
    """A5-92: Adding run must not remove model.references.preview from /meta."""
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    caps = r.json()["capabilities"]
    assert "model.references.preview" in caps


def test_run_engine_executed_true(solar_run):
    """A5-93: engine_executed must be True in scaling section (distinguishes from A4)."""
    assert solar_run["data"]["scaling"]["engine_executed"] is True


def test_preview_engine_executed_false(client):
    """A5-94: A4 preview must still have engine_executed=False (no regression)."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/preview",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 200
    scaling = r.json()["data"]["scaling"]
    assert scaling["engine_executed"] is False


def test_run_and_preview_coexist(client):
    """A5-95: Both /preview and /run must work for the same key without conflict."""
    preview_r = client.post(
        "/api/v1/model/references/generic_wind_reference/preview",
        json={"capacity_mw": 48.0},
    )
    run_r = client.post(
        "/api/v1/model/references/generic_wind_reference/run",
        json={"capacity_mw": 48.0},
    )
    assert preview_r.status_code == 200
    assert run_r.status_code == 200
    # Preview CAPEX total must match Run reference CAPEX total at canonical capacity
    preview_capex = preview_r.json()["data"]["capex"]["reference_total_capex_keur"]
    run_capex = run_r.json()["data"]["capex"]["reference_total_capex_keur"]
    assert abs(preview_capex - run_capex) < 0.01


def test_run_storage_key_returns_404(client):
    """A5-96: Storage references must not be supported in A5."""
    r = client.post(
        "/api/v1/model/references/generic_storage_reference/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "MODEL_REFERENCE_NOT_FOUND"


def test_run_max_capacity_boundary(client):
    """A5-97: capacity_mw=10000 is the maximum allowed value."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 10000.0},
    )
    assert r.status_code == 200


def test_run_above_max_capacity_rejected(client):
    """A5-98: capacity_mw > 10000 must be rejected with 400."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 10000.01},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "MODEL_RUN_REQUEST_INVALID"


def test_run_small_positive_capacity(client):
    """A5-99: Small-but-feasible capacity (5.0 MW) must be accepted by the engine."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 5.0},
    )
    assert r.status_code == 200
    assert r.json()["data"]["scaling"]["requested_capacity_mw"] == 5.0


# ── Correction A: M3 — Canonical-capacity economic equivalence ────────────────

def test_canonical_capacity_solar_capex_equivalence():
    """M3: At 64 MW, scaled Solar CAPEX items must equal canonical factory values."""
    import dataclasses
    from app.project_factories import create_generic_solar_reference
    from app.api.v1.model_run import _build_scaled_project_inputs
    pi = create_generic_solar_reference()
    scaled = _build_scaled_project_inputs(pi, 1.0, 64.0)
    assert abs(scaled.capex.total_capex - pi.capex.total_capex) < 0.001
    assert scaled.technical.capacity_mw == 64.0
    # All individual PER_MW capex items unchanged at ratio=1
    for field in ("epc_contract", "production_units", "epc_other", "grid_connection", "audit_legal"):
        orig = getattr(pi.capex, field).amount_keur
        scaled_val = getattr(scaled.capex, field).amount_keur
        assert abs(scaled_val - orig) < 0.001, f"{field}: expected {orig}, got {scaled_val}"
    # All OPEX items unchanged at ratio=1
    for orig_item, scaled_item in zip(pi.opex, scaled.opex):
        assert abs(scaled_item.y1_amount_keur - orig_item.y1_amount_keur) < 0.001


def test_canonical_capacity_wind_capex_equivalence():
    """M3: At 48 MW, scaled Wind CAPEX items must equal canonical factory values."""
    from app.project_factories import create_generic_wind_reference
    from app.api.v1.model_run import _build_scaled_project_inputs
    pi = create_generic_wind_reference()
    scaled = _build_scaled_project_inputs(pi, 1.0, 48.0)
    assert abs(scaled.capex.total_capex - pi.capex.total_capex) < 0.001
    assert scaled.technical.capacity_mw == 48.0
    for field in ("epc_contract", "grid_connection", "epc_other", "audit_legal"):
        orig = getattr(pi.capex, field).amount_keur
        scaled_val = getattr(scaled.capex, field).amount_keur
        assert abs(scaled_val - orig) < 0.001, f"{field}: expected {orig}, got {scaled_val}"


def test_zero_capex_items_not_scaled():
    """M3: Zero CAPEX items must remain zero after scaling (no phantom amounts)."""
    from app.project_factories import create_generic_solar_reference
    from app.api.v1.model_run import _build_scaled_project_inputs
    pi = create_generic_solar_reference()
    scaled = _build_scaled_project_inputs(pi, 2.0, 128.0)
    for field in ("ops_prep", "insurances", "lease_tax", "construction_mgmt_a",
                  "commissioning", "construction_mgmt_b", "contingencies",
                  "taxes", "project_acquisition", "project_rights"):
        assert getattr(scaled.capex, field).amount_keur == 0.0, f"{field} should remain 0"


def test_canonical_capacity_revenue_assumptions_preserved():
    """M3: Revenue, financing, and tax assumptions must be identical at canonical capacity."""
    from app.project_factories import create_generic_solar_reference
    from app.api.v1.model_run import _build_scaled_project_inputs
    pi = create_generic_solar_reference()
    scaled = _build_scaled_project_inputs(pi, 1.0, 64.0)
    # Revenue, financing, tax are not touched by scaling
    assert scaled.revenue == pi.revenue
    assert scaled.financing == pi.financing
    assert scaled.tax == pi.tax


# ── Correction A: M4 — KPI parity with run_project ────────────────────────────

def test_kpi_parity_solar_canonical(client):
    """M4: A5 solar results must exactly match run_project()['kpis'] at canonical capacity."""
    from app.api.project_runner import run_project
    from app.project_factories import create_generic_solar_reference
    pi = create_generic_solar_reference()
    direct = run_project("Generic Solar Reference", "Base", project_inputs_override=pi, use_dualrun_validation=False)
    direct_kpis = direct["kpis"]

    r = client.post("/api/v1/model/references/generic_solar_reference/run", json={"capacity_mw": 64.0})
    assert r.status_code == 200
    a5_results = r.json()["data"]["results"]

    float_fields = [
        "project_irr", "equity_irr", "sponsor_irr", "project_npv_keur", "equity_npv_keur",
        "min_dscr", "avg_dscr", "total_revenue_keur", "total_ebitda_keur",
        "total_opex_keur", "total_tax_keur", "total_capex_keur", "total_senior_ds_keur",
    ]
    for field in float_fields:
        direct_val = direct_kpis.get(field)
        a5_val = a5_results.get(field)
        if direct_val is None:
            assert a5_val is None, f"{field}: expected None, got {a5_val}"
        else:
            assert a5_val is not None, f"{field}: expected {direct_val}, got None"
            assert abs(float(a5_val) - float(direct_val)) < 1e-6, f"{field}: {a5_val} != {direct_val}"


def test_kpi_parity_wind_canonical(client):
    """M4: A5 wind results must exactly match run_project()['kpis'] at canonical capacity."""
    from app.api.project_runner import run_project
    from app.project_factories import create_generic_wind_reference
    pi = create_generic_wind_reference()
    direct = run_project("Generic Wind Reference", "Base", project_inputs_override=pi, use_dualrun_validation=False)
    direct_kpis = direct["kpis"]

    r = client.post("/api/v1/model/references/generic_wind_reference/run", json={"capacity_mw": 48.0})
    assert r.status_code == 200
    a5_results = r.json()["data"]["results"]

    for field in ["project_irr", "equity_irr", "total_revenue_keur", "total_capex_keur", "min_dscr"]:
        direct_val = direct_kpis.get(field)
        a5_val = a5_results.get(field)
        if direct_val is None:
            assert a5_val is None
        else:
            assert abs(float(a5_val) - float(direct_val)) < 1e-6, f"{field}: {a5_val} != {direct_val}"


# ── Correction A: M5 — Programming sentinel propagates as 500 ─────────────────

def test_programming_sentinel_propagates_as_500(client):
    """M5: Unexpected RuntimeError must propagate as 500, not be swallowed as 503."""
    import app.api.v1.model_run as model_run_mod

    with mock.patch.object(
        model_run_mod,
        "build_run_response_data",
        side_effect=RuntimeError("PROGRAMMING_SENTINEL"),
    ):
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
    assert r.status_code == 500, f"Expected 500 (programming error), got {r.status_code}"
    # 500 body may be empty or minimal — do not attempt JSON decode; just verify status
    assert r.status_code not in (200, 400, 503)


def test_programming_sentinel_semaphore_released(client):
    """M5: Semaphore must still be released even when a programming error propagates."""
    import app.api.v1.run_limiter as limiter_mod
    import app.api.v1.model_run as model_run_mod

    original = limiter_mod._semaphore
    try:
        sem = threading.BoundedSemaphore(1)
        limiter_mod._semaphore = sem

        with mock.patch.object(
            model_run_mod,
            "build_run_response_data",
            side_effect=RuntimeError("PROGRAMMING_SENTINEL"),
        ):
            client.post(
                "/api/v1/model/references/generic_solar_reference/run",
                json={"capacity_mw": 64.0},
            )

        acquired = sem.acquire(blocking=False)
        assert acquired, "Semaphore not released after programming error"
        sem.release()
    finally:
        limiter_mod._semaphore = original


# ── Correction A: M6 — Authority metadata fail-closed ─────────────────────────

def test_authority_metadata_fail_closed_wrong_runtime_authority(client):
    """M6: If runtime_authority != 'clean_g2c', must propagate as server error (not 200)."""
    import app.api.v1.model_run as model_run_mod

    bad_payload = {
        "runtime_authority": {"runtime_authority": "legacy", "calculation_count": 1, "scenario": "Base"},
        "kpis": {},
    }
    original_fn = model_run_mod.build_run_response_data

    def patched_build(key, capacity_mw):
        from app.api.project_runner import run_project as _rp
        from app.api.v1.model_reference import get_pi
        from app.services.reference_seed_service import build_reference_scaling_preview
        pi = get_pi(key)
        preview = build_reference_scaling_preview(key, capacity_mw)
        scaled_pi = model_run_mod._build_scaled_project_inputs(pi, preview["ratio"], capacity_mw)
        payload = dict(bad_payload)
        return model_run_mod._validate_authority_metadata(payload["runtime_authority"]) and {}

    with mock.patch("app.api.project_runner.run_project", return_value=bad_payload):
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
    assert r.status_code != 200, f"Expected non-200 on bad runtime_authority, got {r.status_code}"


def test_authority_metadata_fail_closed_wrong_calculation_count(client):
    """M6: If calculation_count != 1, must propagate as server error (not 200)."""
    bad_payload = {
        "runtime_authority": {"runtime_authority": "clean_g2c", "calculation_count": 2, "scenario": "Base"},
        "kpis": {},
    }
    with mock.patch("app.api.project_runner.run_project", return_value=bad_payload):
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
    assert r.status_code != 200, f"Expected non-200 on calculation_count=2, got {r.status_code}"


# ── Correction A: M7 — Finite JSON safety ─────────────────────────────────────

def test_finite_float_nan_returns_none():
    """M7: _finite_float(NaN) must return None."""
    from app.api.v1.model_run import _finite_float
    assert _finite_float(float("nan")) is None


def test_finite_float_pos_inf_returns_none():
    """M7: _finite_float(+Inf) must return None."""
    from app.api.v1.model_run import _finite_float
    assert _finite_float(float("inf")) is None


def test_finite_float_neg_inf_returns_none():
    """M7: _finite_float(-Inf) must return None."""
    from app.api.v1.model_run import _finite_float
    assert _finite_float(float("-inf")) is None


def test_finite_float_zero_preserved():
    """M7: _finite_float(0.0) must return 0.0 (not None)."""
    from app.api.v1.model_run import _finite_float
    result = _finite_float(0.0)
    assert result == 0.0
    assert result is not None


def test_response_has_no_non_finite_values(client):
    """M7: No A5 successful response may contain NaN or Inf in results."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 200
    results = r.json()["data"]["results"]
    for field, val in results.items():
        if val is not None and isinstance(val, float):
            assert math.isfinite(val), f"Non-finite value in results.{field}: {val}"


def test_extract_kpis_filters_non_finite():
    """M7: _extract_kpis must map NaN/Inf KPI values to None."""
    from app.api.v1.model_run import _extract_kpis
    kpis = {
        "project_irr": float("nan"),
        "equity_irr": float("inf"),
        "sponsor_irr": float("-inf"),
        "total_revenue_keur": 1234.5,
        "total_capex_keur": 0.0,
        "total_ebitda_keur": None,
        "min_dscr": 1.3,
        "avg_dscr": 1.5,
        "target_dscr": 1.2,
        "min_llcr": 1.1,
        "total_opex_keur": 50.0,
        "total_tax_keur": 30.0,
        "total_distributions_keur": 100.0,
        "total_senior_ds_keur": 200.0,
        "total_shl_service_keur": 10.0,
        "project_npv_keur": 5000.0,
        "equity_npv_keur": 3000.0,
        "periods_in_lockup": 4,
    }
    result = _extract_kpis(kpis)
    assert result["project_irr"] is None, "NaN should become None"
    assert result["equity_irr"] is None, "+Inf should become None"
    assert result["sponsor_irr"] is None, "-Inf should become None"
    assert result["total_revenue_keur"] == 1234.5
    assert result["total_capex_keur"] == 0.0
    assert result["total_ebitda_keur"] is None


# ── Correction A: M8 — Complete semantic disclosure ───────────────────────────

def test_m8_authority_semantic_disclosure(solar_run):
    """M8: Authority section must include all semantic disclosure fields."""
    authority = solar_run["data"]["authority"]
    required = {
        "stateless": True,
        "synthetic_reference": True,
        "market_benchmark": False,
        "engine_executed": True,
        "project_created": False,
        "scenario_created": False,
        "workspace_mutated": False,
        "persisted": False,
    }
    for field, expected in required.items():
        assert field in authority, f"Missing field: {field}"
        assert authority[field] == expected, f"{field}: expected {expected}, got {authority[field]}"


def test_m8_scaling_stateless_flag(solar_run):
    """M8: scaling section must include stateless=True."""
    assert solar_run["data"]["scaling"]["stateless"] is True


# ── Correction A: M10 — Scaling ratio tests (all required) ───────────────────

@pytest.mark.parametrize("capacity_mw,expected_ratio", [
    (64.0, 1.0),
    (128.0, 2.0),
    (32.0, 0.5),
])
def test_solar_scaling_ratios(client, capacity_mw, expected_ratio):
    """M10: Solar scaling ratios 1×, 2×, 0.5× must be exact."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": capacity_mw},
    )
    assert r.status_code == 200, f"Expected 200 at {capacity_mw} MW, got {r.status_code}"
    ratio = r.json()["data"]["scaling"]["scale_ratio"]
    assert abs(ratio - expected_ratio) < 1e-9, f"Expected ratio {expected_ratio}, got {ratio}"


@pytest.mark.parametrize("capacity_mw,expected_ratio", [
    (48.0, 1.0),
    (96.0, 2.0),
    (24.0, 0.5),
])
def test_wind_scaling_ratios(client, capacity_mw, expected_ratio):
    """M10: Wind scaling ratios 1×, 2×, 0.5× must be exact."""
    r = client.post(
        "/api/v1/model/references/generic_wind_reference/run",
        json={"capacity_mw": capacity_mw},
    )
    assert r.status_code == 200, f"Expected 200 at {capacity_mw} MW, got {r.status_code}"
    ratio = r.json()["data"]["scaling"]["scale_ratio"]
    assert abs(ratio - expected_ratio) < 1e-9, f"Expected ratio {expected_ratio}, got {ratio}"


# ── Correction A: M10 — Additional persistence seam guards ────────────────────

def test_run_does_not_call_create_working_copy(client):
    """M10: create_working_copy (project creation) must never be called."""
    with mock.patch("app.services.project_library_service.create_working_copy") as patched:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 200
        patched.assert_not_called()


def test_run_does_not_call_save_workspace_state(client):
    """M10: save_workspace_state (workspace persistence) must never be called."""
    with mock.patch("app.persistence.workspace_repository.save_workspace_state") as patched:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 200
        patched.assert_not_called()


def test_run_does_not_call_execute_projects_create_route(client):
    """M10: execute_projects_create_route (project persistence) must never be called."""
    with mock.patch(
        "app.services.projects_create_service.execute_projects_create_route"
    ) as patched:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 200
        patched.assert_not_called()


# ── Correction A: M10 — Calculation count evidence ────────────────────────────

def test_calculation_count_on_success(solar_run):
    """M10: Successful run must declare calculation_count=1."""
    assert solar_run["data"]["authority"]["calculation_count"] == 1


def test_calculation_count_zero_on_404(client):
    """M10: Unsupported key (404) must not execute any calculation."""
    with mock.patch("app.api.project_runner.run_project") as patched:
        r = client.post(
            "/api/v1/model/references/generic_storage_reference/run",
            json={"capacity_mw": 64.0},
        )
        assert r.status_code == 404
        patched.assert_not_called()


def test_calculation_count_zero_on_400(client):
    """M10: Invalid request (400) must not execute any calculation."""
    with mock.patch("app.api.project_runner.run_project") as patched:
        r = client.post(
            "/api/v1/model/references/generic_solar_reference/run",
            json={"capacity_mw": -1},
        )
        assert r.status_code == 400
        patched.assert_not_called()


def test_calculation_count_zero_on_capacity_exhausted(client):
    """M10: When semaphore exhausted (503), no calculation must execute."""
    import app.api.v1.run_limiter as limiter_mod
    original = limiter_mod._semaphore
    try:
        sem = threading.BoundedSemaphore(1)
        sem.acquire()
        limiter_mod._semaphore = sem
        with mock.patch("app.api.project_runner.run_project") as patched:
            r = client.post(
                "/api/v1/model/references/generic_solar_reference/run",
                json={"capacity_mw": 64.0},
            )
            assert r.status_code == 503
            patched.assert_not_called()
    finally:
        limiter_mod._semaphore = original


# ── Correction A: M10 — Validation boundary (NaN/Inf strings) ─────────────────

@pytest.mark.parametrize("raw_body,description", [
    (b'{"capacity_mw": "NaN"}', "NaN string"),
    (b'{"capacity_mw": "Infinity"}', "+Infinity string"),
    (b'{"capacity_mw": "-Infinity"}', "-Infinity string"),
])
def test_non_finite_capacity_string_rejected(client, raw_body, description):
    """M10: String NaN/Inf representations must be rejected with 400 (string type check)."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400, f"Expected 400 for {description}, got {r.status_code}: {r.text}"
    assert r.json()["error"] == "MODEL_RUN_REQUEST_INVALID"
