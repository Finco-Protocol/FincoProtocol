"""Model Parity Pass — V2 scenario override editing tests.

Covers the new POST /v2/workbook/scenarios/update-overrides endpoint and the
overrides field added to ScenarioPresentation.

Priority gaps addressed (gap audit finding #1):
  A. Base Case rejection — endpoint returns 409 for base-case scenarios
  B. Valid override persistence — endpoint calls update_scenario_overrides and
     returns 200 + re-rendered scenario list partial
  C. Auth gate — 401 without authenticated user
  D. Project/scenario guard — 404 for unknown project or scenario
  E. Protected reference gate — 409 for protected reference projects
  F. Non-numeric field skipped — non-parseable value silently dropped (not 500)
  G. Missing required params — 422 when project or scenario_id absent
  H. Persistence failure — 500 when update_scenario_overrides returns None
  I. HTMX response — HTML partial returned for HX-Request: true
  J. Non-HTMX redirect — 303 redirect for non-HTMX requests

  Presentation layer:
  K. ScenarioPresentation carries overrides dict from ScenarioRecord
  L. Base Case scenario has empty overrides in presentation
  M. Override editor fields constant is exported from scenario_presentation
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ─── helpers ─────────────────────────────────────────────────────────────────


def _get_test_client():
    from fastapi.testclient import TestClient
    from app.v2.router import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    return TestClient(app, raise_server_exceptions=False)


def _mock_user(user_id="user-sc"):
    return SimpleNamespace(user_id=user_id)


def _make_project_record(is_protected=False):
    rec = SimpleNamespace(
        project_id="proj-id-1",
        project_code="test_proj",
        project_name="Test Project",
        project_type="wind",
        project_origin="user_created",
        template_source=None,
        baseline_snapshot=None,
        full_inputs=None,
        is_reference_project=is_protected,
    )
    return rec


def _make_scenario(is_base_case=False, overrides=None):
    return SimpleNamespace(
        scenario_id="sc-1",
        project_id="proj-id-1",
        scenario_name="Downside",
        is_base_case=is_base_case,
        archived=False,
        overrides=overrides or {},
        base_input_set={},
        snapshot=None,
        last_run_summary={},
        updated_at=None,
    )


def _make_ws():
    return SimpleNamespace(
        active_scenario_id="sc-1",
        active_scenario_name="Downside",
        last_runtime_snapshot_id=None,
        dirty=False,
    )


def _post_overrides(client, data, htmx=True, follow_redirects=True):
    headers = {"HX-Request": "true"} if htmx else {}
    return client.post(
        "/v2/workbook/scenarios/update-overrides",
        data=data,
        headers=headers,
        follow_redirects=follow_redirects,
    )


# ─── Case A: base-case rejection ─────────────────────────────────────────────


def test_update_overrides_base_case_rejected():
    """Case A: base-case scenario returns 409."""
    client = _get_test_client()
    base_sc = _make_scenario(is_base_case=True)

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=base_sc),
    ):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "sc-1"})

    assert resp.status_code == 409
    body = resp.json()
    assert "Base Case" in body.get("error", "")


# ─── Case B: valid override persistence ──────────────────────────────────────


def test_update_overrides_success_persists_and_returns_html():
    """Case B: valid overrides are persisted; response is HTML (re-rendered partial)."""
    client = _get_test_client()
    sc = _make_scenario(overrides={})
    updated_sc = _make_scenario(overrides={"tariff_eur_mwh": 55.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ) as mock_upo,
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch(
            "app.persistence.scenarios_repository.list_scenarios",
            return_value=[updated_sc],
        ),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "tariff_eur_mwh": "55"},
        )

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    # Verify persistence was called with the correct numeric override
    mock_upo.assert_called_once_with("user-sc", "sc-1", {"tariff_eur_mwh": 55.0})


# ─── Case C: auth gate ────────────────────────────────────────────────────────


def test_update_overrides_unauthenticated():
    """Case C: missing auth returns 401."""
    client = _get_test_client()
    with patch("app.v2.router._get_current_user", return_value=None):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "sc-1"})
    assert resp.status_code == 401


# ─── Case D: project / scenario guard ────────────────────────────────────────


def test_update_overrides_project_not_found():
    """Case D1: unknown project returns 404."""
    client = _get_test_client()
    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(None, "user-sc"),
        ),
    ):
        resp = _post_overrides(client, {"project": "ghost", "scenario_id": "sc-1"})
    assert resp.status_code == 404


def test_update_overrides_scenario_not_found():
    """Case D2: unknown scenario_id returns 404."""
    client = _get_test_client()
    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=None),
    ):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "ghost"})
    assert resp.status_code == 404


def test_update_overrides_scenario_wrong_project():
    """Case D3: scenario belongs to different project → 404."""
    client = _get_test_client()
    sc_wrong = _make_scenario()
    sc_wrong = SimpleNamespace(**{**sc_wrong.__dict__, "project_id": "other-proj"})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc_wrong),
    ):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "sc-1"})
    assert resp.status_code == 404


# ─── Case E: protected reference gate ────────────────────────────────────────


def test_update_overrides_protected_reference_rejected():
    """Case E: protected reference project → 409."""
    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(is_protected=True), "user-sc"),
        ),
        patch("app.v2.router.is_protected_reference", return_value=True),
    ):
        resp = _post_overrides(client, {"project": "ref_proj", "scenario_id": "sc-1"})
    assert resp.status_code == 409


# ─── Case F: non-numeric field silently skipped ───────────────────────────────


def test_update_overrides_non_numeric_value_skipped():
    """Case F: non-numeric value for a field is silently dropped; other fields proceed."""
    client = _get_test_client()
    sc = _make_scenario()
    updated_sc = _make_scenario(overrides={"gearing_pct": 70.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ) as mock_upo,
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch("app.persistence.scenarios_repository.list_scenarios", return_value=[updated_sc]),
    ):
        resp = _post_overrides(
            client,
            {
                "project": "test_proj",
                "scenario_id": "sc-1",
                "tariff_eur_mwh": "not_a_number",  # dropped
                "gearing_pct": "70",                # kept
            },
        )

    assert resp.status_code == 200
    # Only the numeric field reaches the persistence layer
    mock_upo.assert_called_once_with("user-sc", "sc-1", {"gearing_pct": 70.0})


# ─── Case G: missing required params ─────────────────────────────────────────


def test_update_overrides_missing_project():
    """Case G1: missing project field → 422."""
    client = _get_test_client()
    with patch("app.v2.router._get_current_user", return_value=_mock_user()):
        resp = _post_overrides(client, {"scenario_id": "sc-1"})
    assert resp.status_code == 422


def test_update_overrides_missing_scenario_id():
    """Case G2: missing scenario_id field → 422."""
    client = _get_test_client()
    with patch("app.v2.router._get_current_user", return_value=_mock_user()):
        resp = _post_overrides(client, {"project": "test_proj"})
    assert resp.status_code == 422


# ─── Case H: persistence failure ─────────────────────────────────────────────


def test_update_overrides_persistence_failure():
    """Case H: update_scenario_overrides returns None → 500."""
    client = _get_test_client()
    sc = _make_scenario()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=None,
        ),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "tariff_eur_mwh": "50"},
        )
    assert resp.status_code == 500


# ─── Case I: HTMX response ───────────────────────────────────────────────────


def test_update_overrides_htmx_response_contains_scenario_list():
    """Case I: HTMX request → HTML partial with v2-sheet-scenarios element."""
    client = _get_test_client()
    sc = _make_scenario(overrides={"tariff_eur_mwh": 50.0})
    updated_sc = _make_scenario(overrides={"tariff_eur_mwh": 55.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch("app.persistence.scenarios_repository.list_scenarios", return_value=[updated_sc]),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "tariff_eur_mwh": "55"},
            htmx=True,
        )

    assert resp.status_code == 200
    assert "v2-sheet-scenarios" in resp.text


# ─── Case J: non-HTMX redirect ───────────────────────────────────────────────


def test_update_overrides_non_htmx_redirects():
    """Case J: non-HTMX request → 303 redirect to workbook page."""
    client = _get_test_client()
    sc = _make_scenario()
    updated_sc = _make_scenario(overrides={"gearing_pct": 65.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch("app.persistence.scenarios_repository.list_scenarios", return_value=[updated_sc]),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "gearing_pct": "65"},
            htmx=False,
            follow_redirects=False,
        )

    assert resp.status_code == 303
    assert "test_proj" in resp.headers.get("location", "")


# ─── Case K: ScenarioPresentation carries overrides ──────────────────────────


def test_scenario_presentation_carries_overrides():
    """Case K: build_scenario_presentation exposes overrides from ScenarioRecord."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={"tariff_eur_mwh": 55.0, "gearing_pct": 70.0})
    pres = build_scenario_presentation(sc, active_scenario_id=None)

    assert pres.overrides == {"tariff_eur_mwh": 55.0, "gearing_pct": 70.0}


def test_scenario_presentation_no_overrides_returns_empty_dict():
    """Case K2: scenario with no overrides → empty dict, not None."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={})
    pres = build_scenario_presentation(sc, active_scenario_id=None)

    assert pres.overrides == {}
    assert isinstance(pres.overrides, dict)


# ─── Case L: base case has empty overrides ────────────────────────────────────


def test_scenario_presentation_base_case_empty_overrides():
    """Case L: base-case scenario always has empty overrides in presentation."""
    from app.v2.scenario_presentation import build_scenario_presentation

    base_sc = _make_scenario(is_base_case=True, overrides={})
    pres = build_scenario_presentation(base_sc, active_scenario_id=None)

    assert pres.is_base_case is True
    assert pres.overrides == {}


# ─── Case M: OVERRIDE_EDITOR_FIELDS constant ─────────────────────────────────


def test_override_editor_fields_exported():
    """Case M: OVERRIDE_EDITOR_FIELDS constant is importable and well-formed."""
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS

    assert len(OVERRIDE_EDITOR_FIELDS) >= 4  # at least revenue + debt fields
    for entry in OVERRIDE_EDITOR_FIELDS:
        key, label, unit = entry
        assert key and label and unit
        assert isinstance(key, str)


def test_override_editor_fields_cover_key_modellable_inputs():
    """Case M2: key financial modelling fields are in the editor field list."""
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS

    keys = {entry[0] for entry in OVERRIDE_EDITOR_FIELDS}
    # Revenue
    assert "tariff_eur_mwh" in keys
    assert "p50_hours" in keys
    # Costs
    assert "opex_y1_keur" in keys
    # Debt
    assert "gearing_pct" in keys
    assert "interest_rate_pct" in keys
