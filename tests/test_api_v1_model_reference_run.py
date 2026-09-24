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


def test_authority_section(solar_run):
    """A5-35: authority section must confirm clean G2C execution."""
    authority = solar_run["data"]["authority"]
    assert authority["runtime_authority"] == "clean_g2c"
    assert authority["calculation_count"] == 1
    assert authority["scenario"] == "Base"
    assert authority["engine_executed"] is True
    assert authority["project_created"] is False
    assert authority["db_writes"] is False
    assert authority["synthetic_reference"] is True
    assert authority["market_benchmark"] is False


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
    """A5-67: Run must never perform DB writes (db_writes=False)."""
    r = client.post(
        "/api/v1/model/references/generic_solar_reference/run",
        json={"capacity_mw": 64.0},
    )
    assert r.status_code == 200
    assert r.json()["data"]["scaling"]["db_writes"] is False
    assert r.json()["data"]["authority"]["db_writes"] is False


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
    """A5-83: Semaphore must be released even when the engine raises an exception."""
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
            side_effect=RuntimeError("simulated engine failure"),
        ):
            r = client.post(
                "/api/v1/model/references/generic_solar_reference/run",
                json={"capacity_mw": 64.0},
            )
            assert r.status_code == 503

        # After the failed call, semaphore must be re-acquirable (was released)
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
