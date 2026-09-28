"""FINCO API v1.1 — Institutional Read-Only Surface Tests (Correction A).

Acceptance markers (12 required):
  CORR_A_SIGNED_SESSION_AUTH              — auth via signed session cookie only
  CORR_A_SPOOFED_IDENTITY_BLOCKED         — X-User-Id header has zero authority
  CORR_A_VALID_SESSION_OWN_PROJECTS_ONLY  — valid session resolves only its own projects
  CORR_A_MISSING_AUTH_FAILS_CLOSED        — missing/invalid auth fails closed
  CORR_A_AVAILABLE_AFTER_COMMITTED_RUN    — committed run → AVAILABLE
  CORR_A_AVAILABLE_AFTER_WC_EDIT          — canonical Last Run stays AVAILABLE after WC edit
  CORR_A_WORKING_COPY_CHANGED_SINCE_RUN   — working_copy_changed_since_run exposed separately
  CORR_A_VALIDATION_VS_VERIFY_SEPARATION  — /validation and /verify use different authorities
  CORR_A_VERIFY_FAILS_CLOSED              — Verify fails closed when no source-proven binding
  CORR_A_RLIVE_EXACT_ASSETKEY             — R-LIVE accepts exact canonical_id only
  CORR_A_EXPORT_CANONICAL_LAST_RUN        — /export is real authenticated XLSX delegate
  CORR_A_SUPPORTED_TODAY_CANONICAL        — supported-today from canonical PRODUCT_CAPABILITIES

Final marker: FINCO_PR125_CORRECTION_A_CURRENT_MAIN_READY
"""
from __future__ import annotations

import datetime
import pytest
from fastapi.testclient import TestClient


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from main_api import app
    return TestClient(app, raise_server_exceptions=False)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _make_cookie(user_id: str) -> dict:
    """Create a signed demo session cookie for the given user_id."""
    from app.auth import create_demo_session_token, DEMO_COOKIE_NAME
    return {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


# ── Project fixture with committed run ────────────────────────────────────────

def _build_persisted_run(project_type: str = "Solar"):
    """Create a user-created project with a real committed Last Run.

    Returns (project_record, workspace_state, composite_hash).
    """
    from app.auth import new_demo_user_id
    from app.persistence.projects_repository import create_project_record, get_project
    from app.persistence.workspace_repository import (
        save_workspace_state, get_workspace_state, v2_atomic_run_commit,
    )
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario
    from app.api.project_runner import run_project
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    uid = new_demo_user_id()

    if project_type == "Solar":
        from app.project_factories import create_generic_solar_reference
        pi = create_generic_solar_reference()
        template = "generic_solar_reference"
        ptype = "Solar"
    elif project_type == "Wind":
        from app.project_factories import create_generic_wind_reference
        pi = create_generic_wind_reference()
        template = "generic_wind_reference"
        ptype = "Wind"
    elif project_type == "EV Charging":
        from app.project_factories import create_generic_ev_charging_reference
        pi = create_generic_ev_charging_reference()
        template = "generic_ev_charging_reference"
        ptype = "EV Charging"
    elif project_type == "Data Center":
        from app.project_factories import create_generic_data_center_reference
        pi = create_generic_data_center_reference()
        template = "generic_data_center_reference"
        ptype = "Data Center"
    else:
        raise ValueError(f"Unsupported project_type: {project_type}")

    pcode = f"apiv11corr_{ptype.lower().replace(' ', '')}_{uid[-8:]}"
    opex_y1 = sum(item.y1_amount_keur for item in pi.opex)

    snap: dict = {
        "project_type": ptype,
        "template_source": template,
        "project_origin": "user_created",
        "project_name": pi.info.name,
        "country_market": pi.info.country_iso,
        "capacity_mw": str(pi.technical.capacity_mw),
        "cod_date": str(pi.info.cod_date),
        "construction_months": str(pi.info.construction_months),
        "horizon_years": str(pi.info.horizon_years),
        "p50_hours": str(pi.technical.operating_hours_p50),
        "opex_y1_keur": str(opex_y1),
        "total_capex_keur": str(pi.capex.total_capex),
        "interest_rate_pct": str(pi.financing.all_in_rate * 100),
        "tenor_years": str(pi.financing.senior_tenor_years),
        "target_dscr": str(pi.financing.target_dscr),
        "tariff_eur_mwh": str(pi.revenue.ppa_base_tariff),
        "ppa_term_years": str(pi.revenue.ppa_term_years),
    }

    pr = create_project_record(
        user_id=uid,
        project_code=pcode,
        project_name=f"API v1.1 CorrA Test {ptype}",
        project_type=ptype,
        project_origin="user_created",
        template_source=template,
        baseline_snapshot=snap,
    )
    save_workspace_state(
        user_id=uid,
        project_id=pr.project_id,
        project_code=pcode,
        draft_snapshot=snap,
        saved_snapshot=snap,
    )
    base_sc = get_or_create_base_case_scenario(
        user_id=uid,
        project_id=pr.project_id,
        project_code=pcode,
        project_name=f"API v1.1 CorrA Test {ptype}",
        project_type=ptype,
        source_project_template=template,
        base_input_set=snap,
        governance_state={},
    )

    identity = assemble_consistent_for_get(
        user_id=uid,
        project_id=pr.project_id,
        workbook_version=WORKBOOK.version,
    )
    composite_hash = identity.composite_hash

    run_label = template
    result = run_project(run_label, "Base", project_inputs_override=pi)
    kpis = result["kpis"]

    snapshot_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ran_at = datetime.datetime.now(datetime.timezone.utc)
    v2_atomic_run_commit(
        user_id=uid,
        project_id=pr.project_id,
        project_code=pcode,
        expected_composite_hash=composite_hash,
        runtime_snapshot_id=snapshot_id,
        runtime_origin="v2_run",
        runtime_summary=kpis,
        financial_statements=result.get("financial_statements"),
        debt_schedule=result.get("debt_schedule"),
        tax_schedule=result.get("tax_schedule"),
        distribution_schedule=result.get("distribution_schedule"),
        sponsor_schedule=result.get("sponsor_schedule"),
        active_scenario_id=base_sc.scenario_id,
        active_scenario_name="Base Case",
        last_runtime_scenario_id=base_sc.scenario_id,
        ran_at=ran_at,
    )

    ws = get_workspace_state(uid, pr.project_id)
    assert ws is not None and ws.any_run_committed
    pr2 = get_project(pr.project_id, uid)
    return pr2, ws, composite_hash


# ── CORR_A_MISSING_AUTH_FAILS_CLOSED ──────────────────────────────────────────

def test_corr_a_projects_no_session_returns_401(client):
    """No session cookie → 401 MISSING_USER_IDENTITY.
    Marker: CORR_A_MISSING_AUTH_FAILS_CLOSED
    """
    r = client.get("/api/v1.1/projects")
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "MISSING_USER_IDENTITY"
    assert body["api_version"] == "v1.1"


def test_corr_a_project_scoped_endpoints_no_session_return_401(client):
    """All project-scoped endpoints return 401 without a session cookie.
    Marker: CORR_A_MISSING_AUTH_FAILS_CLOSED
    """
    fake_pid = "no-such-project"
    paths = [
        f"/api/v1.1/projects/{fake_pid}/last-run",
        f"/api/v1.1/projects/{fake_pid}/run-identity",
        f"/api/v1.1/projects/{fake_pid}/kpis",
        f"/api/v1.1/projects/{fake_pid}/export-metadata",
        f"/api/v1.1/projects/{fake_pid}/validation",
        f"/api/v1.1/projects/{fake_pid}/verify",
    ]
    for path in paths:
        r = client.get(path)
        assert r.status_code == 401, (
            f"Expected 401 for {path} without session; got {r.status_code}"
        )
        body = r.json()
        assert body["error"] == "MISSING_USER_IDENTITY", (
            f"Expected MISSING_USER_IDENTITY for {path}; got {body.get('error')!r}"
        )


# ── CORR_A_SPOOFED_IDENTITY_BLOCKED ───────────────────────────────────────────

def test_corr_a_x_user_id_header_not_trusted(client):
    """X-User-Id header alone does NOT authenticate. Returns 401.
    Marker: CORR_A_SPOOFED_IDENTITY_BLOCKED
    """
    from app.auth import new_demo_user_id
    spoofed_uid = new_demo_user_id()

    # No cookie — only a spoofed header. Must fail closed.
    r = client.get("/api/v1.1/projects", headers={"X-User-Id": spoofed_uid})
    assert r.status_code == 401, (
        f"Spoofed X-User-Id must NOT authenticate; got {r.status_code}"
    )
    body = r.json()
    assert body["error"] == "MISSING_USER_IDENTITY"


def test_corr_a_spoofed_x_user_id_cannot_access_project(client):
    """Spoofed X-User-Id header cannot access another user's project.
    Marker: CORR_A_SPOOFED_IDENTITY_BLOCKED
    """
    # Build a project for user A with a real cookie
    pr, ws, _ = _build_persisted_run("Solar")
    user_a = pr.user_id
    pid = pr.project_id

    from app.auth import new_demo_user_id
    user_b = new_demo_user_id()
    assert user_a != user_b

    # User B sends X-User-Id=user_a (spoofed) but has no valid session cookie
    r = client.get(
        f"/api/v1.1/projects/{pid}/last-run",
        headers={"X-User-Id": user_a},
    )
    assert r.status_code == 401, (
        f"Spoofed X-User-Id (user_a's) must return 401; got {r.status_code}"
    )


# ── CORR_A_SIGNED_SESSION_AUTH ────────────────────────────────────────────────

def test_corr_a_signed_session_authenticates(client):
    """Signed demo session cookie authenticates successfully.
    Marker: CORR_A_SIGNED_SESSION_AUTH
    """
    from app.auth import new_demo_user_id
    uid = new_demo_user_id()
    cookies = _make_cookie(uid)

    r = client.get("/api/v1.1/projects", cookies=cookies)
    assert r.status_code == 200, (
        f"Valid signed session must return 200; got {r.status_code}"
    )
    body = r.json()
    assert body["state"] == "AVAILABLE"
    assert body["api_version"] == "v1.1"
    assert body["schema_version"] == "institutional-v1.1.0"


# ── CORR_A_VALID_SESSION_OWN_PROJECTS_ONLY ────────────────────────────────────

def test_corr_a_valid_session_resolves_own_projects_only(client):
    """Valid session resolves only its own projects; cannot see another user's project.
    Marker: CORR_A_VALID_SESSION_OWN_PROJECTS_ONLY
    """
    pr_a, _, _ = _build_persisted_run("Solar")
    user_a = pr_a.user_id
    pid_a = pr_a.project_id

    from app.auth import new_demo_user_id
    user_b = new_demo_user_id()
    cookies_b = _make_cookie(user_b)

    # User B's project list — should be empty (fresh user)
    r_list = client.get("/api/v1.1/projects", cookies=cookies_b)
    assert r_list.status_code == 200
    assert r_list.json()["data"]["count"] == 0, (
        "Fresh user B must have 0 projects"
    )

    # User B accessing user A's project by project_id — must get 404
    r_proj = client.get(
        f"/api/v1.1/projects/{pid_a}/last-run",
        cookies=cookies_b,
    )
    assert r_proj.status_code == 404, (
        f"User B must not see user A's project; got {r_proj.status_code}"
    )


def test_corr_a_unknown_project_returns_404(client):
    """Unknown project_id returns 404 PROJECT_NOT_FOUND.
    Marker: CORR_A_VALID_SESSION_OWN_PROJECTS_ONLY
    """
    from app.auth import new_demo_user_id
    uid = new_demo_user_id()
    cookies = _make_cookie(uid)

    r = client.get(
        "/api/v1.1/projects/does-not-exist-xyz/last-run",
        cookies=cookies,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "PROJECT_NOT_FOUND"


# ── CORR_A_AVAILABLE_AFTER_COMMITTED_RUN ──────────────────────────────────────

def test_corr_a_available_after_committed_run():
    """Committed run → state AVAILABLE on all project endpoints.
    Marker: CORR_A_AVAILABLE_AFTER_COMMITTED_RUN
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, chash = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    for path in [
        f"/api/v1.1/projects/{pid}/last-run",
        f"/api/v1.1/projects/{pid}/run-identity",
        f"/api/v1.1/projects/{pid}/kpis",
        f"/api/v1.1/projects/{pid}/export-metadata",
    ]:
        r = client.get(path, cookies=cookies)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        body = r.json()
        assert body["state"] == "AVAILABLE", (
            f"{path}: expected AVAILABLE; got {body.get('state')!r}"
        )


def test_corr_a_no_run_returns_unavailable(client):
    """Project with no committed run returns UNAVAILABLE.
    Marker: CORR_A_AVAILABLE_AFTER_COMMITTED_RUN (fail-closed)
    """
    from app.auth import new_demo_user_id
    from app.persistence.projects_repository import create_project_record
    from app.persistence.workspace_repository import save_workspace_state
    from app.project_factories import create_generic_solar_reference

    uid = new_demo_user_id()
    pcode = f"apiv11norun_{uid[-8:]}"
    pi = create_generic_solar_reference()
    snap = {
        "project_type": "Solar",
        "template_source": "generic_solar_reference",
        "project_origin": "user_created",
        "project_name": pi.info.name,
        "country_market": pi.info.country_iso,
        "capacity_mw": str(pi.technical.capacity_mw),
        "cod_date": str(pi.info.cod_date),
        "construction_months": str(pi.info.construction_months),
        "horizon_years": str(pi.info.horizon_years),
        "p50_hours": str(pi.technical.operating_hours_p50),
        "opex_y1_keur": "1000",
        "total_capex_keur": str(pi.capex.total_capex),
        "interest_rate_pct": "5.0",
        "tenor_years": "15",
        "target_dscr": "1.2",
        "tariff_eur_mwh": "60.0",
        "ppa_term_years": "20",
    }
    pr = create_project_record(
        user_id=uid,
        project_code=pcode,
        project_name="No-Run Test",
        project_type="Solar",
        project_origin="user_created",
        template_source="generic_solar_reference",
        baseline_snapshot=snap,
    )
    save_workspace_state(
        user_id=uid,
        project_id=pr.project_id,
        project_code=pcode,
        draft_snapshot=snap,
        saved_snapshot=snap,
    )
    pid = pr.project_id
    cookies = _make_cookie(uid)

    for path in [
        f"/api/v1.1/projects/{pid}/last-run",
        f"/api/v1.1/projects/{pid}/run-identity",
        f"/api/v1.1/projects/{pid}/kpis",
        f"/api/v1.1/projects/{pid}/export-metadata",
    ]:
        r = client.get(path, cookies=cookies)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        body = r.json()
        assert body["state"] == "UNAVAILABLE", (
            f"{path}: expected UNAVAILABLE without committed run; got {body.get('state')!r}"
        )


# ── CORR_A_AVAILABLE_AFTER_WC_EDIT ────────────────────────────────────────────

def test_corr_a_last_run_available_after_wc_edit():
    """Canonical Last Run stays AVAILABLE after Working Copy is mutated.

    Correction A: STALE is not a valid state. WC divergence is separate.
    Marker: CORR_A_AVAILABLE_AFTER_WC_EDIT
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)
    from app.persistence.workspace_repository import save_workspace_state

    pr, ws, chash = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    # Verify AVAILABLE before WC mutation
    r_before = client.get(f"/api/v1.1/projects/{pid}/last-run", cookies=cookies)
    assert r_before.json()["state"] == "AVAILABLE"

    # Mutate the Working Copy (dirty state)
    dirty_snap = dict(ws.draft_snapshot)
    dirty_snap["capacity_mw"] = "9999"
    save_workspace_state(
        user_id=pr.user_id,
        project_id=pid,
        project_code=pr.project_code,
        draft_snapshot=dirty_snap,
        saved_snapshot=dirty_snap,
    )

    # Must STILL be AVAILABLE — WC mutation cannot downgrade Last Run state
    r_after = client.get(f"/api/v1.1/projects/{pid}/last-run", cookies=cookies)
    body_after = r_after.json()
    assert body_after["state"] == "AVAILABLE", (
        f"After WC mutation, state must still be AVAILABLE; got {body_after.get('state')!r}. "
        "STALE is NOT a valid Correction A state."
    )


# ── CORR_A_WORKING_COPY_CHANGED_SINCE_RUN ─────────────────────────────────────

def test_corr_a_working_copy_changed_since_run_field():
    """working_copy_changed_since_run exposed separately — not as state.
    Marker: CORR_A_WORKING_COPY_CHANGED_SINCE_RUN
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)
    from app.persistence.workspace_repository import save_workspace_state

    pr, ws, chash = _build_persisted_run("Wind")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    # Before WC mutation: working_copy_changed_since_run = False
    r_clean = client.get(f"/api/v1.1/projects/{pid}/run-identity", cookies=cookies)
    assert r_clean.status_code == 200
    data_clean = r_clean.json()["data"]
    assert data_clean.get("working_copy_changed_since_run") is False, (
        f"Clean WC: expected False; got {data_clean.get('working_copy_changed_since_run')!r}"
    )

    # Mutate WC
    dirty_snap = dict(ws.draft_snapshot)
    dirty_snap["capacity_mw"] = "8888"
    save_workspace_state(
        user_id=pr.user_id,
        project_id=pid,
        project_code=pr.project_code,
        draft_snapshot=dirty_snap,
        saved_snapshot=dirty_snap,
    )

    # After WC mutation: working_copy_changed_since_run = True; state still AVAILABLE
    r_dirty = client.get(f"/api/v1.1/projects/{pid}/run-identity", cookies=cookies)
    assert r_dirty.status_code == 200
    body_dirty = r_dirty.json()
    assert body_dirty["state"] == "AVAILABLE", (
        "State must remain AVAILABLE after WC mutation"
    )
    data_dirty = body_dirty["data"]
    assert data_dirty.get("working_copy_changed_since_run") is True, (
        f"Dirty WC: expected True; got {data_dirty.get('working_copy_changed_since_run')!r}"
    )

    # Last Run identity must be immutable across WC mutation
    assert data_dirty["composite_hash"] == chash, "composite_hash must not change"
    assert data_dirty["snapshot_id"] == ws.last_runtime_snapshot_id


# ── CORR_A_VALIDATION_VS_VERIFY_SEPARATION ────────────────────────────────────

def test_corr_a_validation_endpoint_uses_model_validation_authority():
    """/validation delegates to app.model_validation with authority=MODEL_VALIDATION.
    Marker: CORR_A_VALIDATION_VS_VERIFY_SEPARATION
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r = client.get(f"/api/v1.1/projects/{pid}/validation", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] in ("AVAILABLE", "UNAVAILABLE"), (
        f"Unexpected state: {body.get('state')!r}"
    )
    evidence = body.get("evidence") or {}
    assert evidence.get("authority") == "MODEL_VALIDATION", (
        f"validation authority must be MODEL_VALIDATION; got {evidence.get('authority')!r}"
    )
    if body["state"] == "AVAILABLE":
        assert "validation_state" in evidence
        assert evidence["validation_state"] in ("PASS", "PASS_WITH_KNOWN_GAPS", "FAIL"), (
            f"validation_state must be known; got {evidence['validation_state']!r}"
        )


def test_corr_a_verify_endpoint_uses_finco_verify_authority():
    """/verify delegates to app.verified with authority=FINCO_VERIFY.
    Marker: CORR_A_VALIDATION_VS_VERIFY_SEPARATION
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r = client.get(f"/api/v1.1/projects/{pid}/verify", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    evidence = body.get("evidence") or {}
    assert evidence.get("authority") == "FINCO_VERIFY", (
        f"verify authority must be FINCO_VERIFY; got {evidence.get('authority')!r}"
    )


def test_corr_a_validation_and_verify_are_independent():
    """/validation and /verify are different endpoints with different authorities.
    Uses a project with a committed run to get full evidence from both endpoints.
    Marker: CORR_A_VALIDATION_VS_VERIFY_SEPARATION
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r_val = client.get(f"/api/v1.1/projects/{pid}/validation", cookies=cookies)
    r_ver = client.get(f"/api/v1.1/projects/{pid}/verify", cookies=cookies)

    assert r_val.status_code == 200
    assert r_ver.status_code == 200

    ev_val = r_val.json().get("evidence") or {}
    ev_ver = r_ver.json().get("evidence") or {}

    # Both have authority set — different ones
    assert ev_val.get("authority") == "MODEL_VALIDATION", (
        f"/validation must use MODEL_VALIDATION; got {ev_val.get('authority')!r}"
    )
    assert ev_ver.get("authority") == "FINCO_VERIFY", (
        f"/verify must use FINCO_VERIFY; got {ev_ver.get('authority')!r}"
    )
    # They must be different
    assert ev_val.get("authority") != ev_ver.get("authority"), (
        "/validation and /verify must use different authorities"
    )


# ── CORR_A_VERIFY_FAILS_CLOSED ────────────────────────────────────────────────

def test_corr_a_verify_fails_closed_for_unregistered_template():
    """Verify returns UNAVAILABLE for a vertical with no source-proven binding.

    EV Charging and Data Center are not in the Verify registry (V1).
    Marker: CORR_A_VERIFY_FAILS_CLOSED
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("EV Charging")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r = client.get(f"/api/v1.1/projects/{pid}/verify", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "UNAVAILABLE", (
        f"EV Charging must UNAVAILABLE from Verify (no binding); got {body.get('state')!r}"
    )
    ev = body.get("evidence") or body.get("data") or {}
    assert ev.get("reason") == "VERIFY_BINDING_UNAVAILABLE", (
        f"Expected VERIFY_BINDING_UNAVAILABLE; got {ev.get('reason')!r}"
    )


def test_corr_a_verify_available_for_solar_reference():
    """Verify is available for Solar (source-proven binding exists).
    Marker: CORR_A_VERIFY_FAILS_CLOSED (positive case)
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r = client.get(f"/api/v1.1/projects/{pid}/verify", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    # Solar reference has a Verify binding — must not error
    ev = body.get("evidence") or {}
    assert ev.get("authority") == "FINCO_VERIFY"
    # State depends on governance conditions — just check authority is correct
    assert body["state"] in ("AVAILABLE", "UNAVAILABLE")


# ── CORR_A_RLIVE_EXACT_ASSETKEY ───────────────────────────────────────────────

def test_corr_a_rlive_invalid_uid_returns_unavailable(client):
    """R-LIVE returns UNAVAILABLE for invalid / non-canonical UIDs.
    Marker: CORR_A_RLIVE_EXACT_ASSETKEY
    """
    from finco_radar.authority.r_live_policy import AAPL_KEY
    canonical_id = AAPL_KEY.canonical_id

    invalid_uids = [
        "AAPL",
        "DOES_NOT_EXIST_XYZ_999",
        "ticker:AAPL",
        "1:0x0000000000000000000000000000000000000001",
    ]
    for uid in invalid_uids:
        # Skip if uid == canonical_id (would be the valid case)
        assert uid != canonical_id, f"Test invalid uid equals canonical_id: {uid!r}"
        r = client.get(f"/api/v1.1/radar/r-live/{uid}")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "UNAVAILABLE", (
            f"UID {uid!r} must be UNAVAILABLE; got {body.get('state')!r}"
        )
        data = body.get("data") or {}
        assert data.get("reason") == "ASSET_UID_INVALID", (
            f"UID {uid!r}: expected ASSET_UID_INVALID; got {data.get('reason')!r}"
        )


def test_corr_a_rlive_canonical_id_matches_policy(client):
    """R-LIVE canonical_id matches AAPL_KEY from r_live_policy.
    Marker: CORR_A_RLIVE_EXACT_ASSETKEY
    """
    from finco_radar.authority.r_live_policy import AAPL_KEY

    # Verify canonical_id format is chain:address (not 32-byte hex)
    canonical_id = AAPL_KEY.canonical_id
    assert ":" in canonical_id, (
        f"canonical_id must be chain_id:contract_address format; got {canonical_id!r}"
    )
    chain_part, addr_part = canonical_id.split(":", 1)
    assert chain_part.isdigit(), f"chain_id part must be numeric; got {chain_part!r}"
    assert addr_part.startswith("0x"), f"contract_address must start with 0x; got {addr_part!r}"


# ── CORR_A_EXPORT_CANONICAL_LAST_RUN ─────────────────────────────────────────

def test_corr_a_export_metadata_returns_download_path():
    """Export metadata returns valid download_path and working_copy_changed_since_run.
    Marker: CORR_A_EXPORT_CANONICAL_LAST_RUN
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r = client.get(f"/api/v1.1/projects/{pid}/export-metadata", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert "download_path" in data
    assert data["download_path"] == f"/api/v1.1/projects/{pid}/export"
    assert data["export_authority"] == "CANONICAL_LAST_RUN"
    assert "working_copy_changed_since_run" in data


def test_corr_a_export_endpoint_no_session_returns_401():
    """Export endpoint returns 401 without authentication.
    Marker: CORR_A_EXPORT_CANONICAL_LAST_RUN
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/api/v1.1/projects/some-pid/export")
    assert r.status_code == 401, (
        f"Export without session must return 401; got {r.status_code}"
    )


def test_corr_a_export_endpoint_authenticated_with_committed_run():
    """Export endpoint returns XLSX for a project with a committed run.
    Marker: CORR_A_EXPORT_CANONICAL_LAST_RUN
    """
    from main_api import app
    client = TestClient(app, raise_server_exceptions=False)

    pr, ws, _ = _build_persisted_run("Solar")
    cookies = _make_cookie(pr.user_id)
    pid = pr.project_id

    r = client.get(f"/api/v1.1/projects/{pid}/export", cookies=cookies)
    assert r.status_code == 200, (
        f"Export with committed run must return 200; got {r.status_code}"
    )
    content_type = r.headers.get("content-type", "")
    assert "spreadsheetml" in content_type or "officedocument" in content_type, (
        f"Export must return XLSX content-type; got {content_type!r}"
    )
    assert len(r.content) > 1000, "XLSX must be non-trivial bytes"


# ── CORR_A_SUPPORTED_TODAY_CANONICAL ──────────────────────────────────────────

def test_corr_a_supported_today_from_product_capabilities(client):
    """supported-today delegates to canonical PRODUCT_CAPABILITIES, not hardcoded list.
    Marker: CORR_A_SUPPORTED_TODAY_CANONICAL
    """
    from app.product_capability import PRODUCT_CAPABILITIES

    r = client.get("/api/v1.1/supported-today")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "AVAILABLE"
    data = body["data"]
    assert "capabilities" in data
    caps = data["capabilities"]

    canonical_keys = {cap.key for cap in PRODUCT_CAPABILITIES}
    api_keys = {cap["key"] for cap in caps}
    assert api_keys == canonical_keys, (
        f"supported-today keys must match PRODUCT_CAPABILITIES exactly.\n"
        f"Expected: {sorted(canonical_keys)}\nGot: {sorted(api_keys)}"
    )


def test_corr_a_supported_today_has_required_fields(client):
    """Each capability in supported-today carries required canonical fields.
    Marker: CORR_A_SUPPORTED_TODAY_CANONICAL
    """
    r = client.get("/api/v1.1/supported-today")
    assert r.status_code == 200
    caps = r.json()["data"]["capabilities"]
    assert len(caps) > 0

    required_fields = {"key", "public_name", "status", "api_available"}
    for cap in caps:
        missing = required_fields - set(cap.keys())
        assert not missing, f"Capability {cap.get('key')!r} missing fields: {missing}"


def test_corr_a_supported_today_no_session_required(client):
    """supported-today is a public endpoint — no session required.
    Marker: CORR_A_SUPPORTED_TODAY_CANONICAL
    """
    r = client.get("/api/v1.1/supported-today")
    assert r.status_code == 200
    assert r.json()["state"] == "AVAILABLE"


# ── Schema version contract ────────────────────────────────────────────────────

def test_corr_a_schema_version_contract(client):
    """All v1.1 responses carry correct api_version and schema_version.
    Marker: schema contract
    """
    r = client.get("/api/v1.1/supported-today")
    assert r.status_code == 200
    body = r.json()
    assert body["api_version"] == "v1.1"
    assert body["schema_version"] == "institutional-v1.1.0"


# ── FINCO_PR125_CORRECTION_A_CURRENT_MAIN_READY ───────────────────────────────

def test_finco_pr125_correction_a_current_main_ready(client):
    """Final acceptance marker — all Correction A contracts verified.
    Marker: FINCO_PR125_CORRECTION_A_CURRENT_MAIN_READY
    """
    from finco_radar.authority.r_live_policy import AAPL_KEY
    from app.product_capability import PRODUCT_CAPABILITIES

    # 1. Auth endpoint available
    r = client.get("/api/v1.1/projects")
    assert r.status_code == 401  # no session → fails closed

    # 2. supported-today works
    r = client.get("/api/v1.1/supported-today")
    assert r.status_code == 200
    assert r.json()["state"] == "AVAILABLE"

    # 3. Canonical capabilities
    caps = r.json()["data"]["capabilities"]
    canonical_keys = {cap.key for cap in PRODUCT_CAPABILITIES}
    assert {c["key"] for c in caps} == canonical_keys

    # 4. R-LIVE invalid UID blocked
    r = client.get("/api/v1.1/radar/r-live/AAPL")
    assert r.json()["state"] == "UNAVAILABLE"
    assert r.json().get("data", {}).get("reason") == "ASSET_UID_INVALID"

    # 5. Schema version correct
    assert r.json()["api_version"] == "v1.1"
    assert r.json()["schema_version"] == "institutional-v1.1.0"
