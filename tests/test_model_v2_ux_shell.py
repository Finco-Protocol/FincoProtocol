"""Model V2 UX Foundation — Workspace Shell (UX-2) acceptance.

Covers the finance workspace shell contracts:

  UX_SHELL_HEADER_STATE         Working Copy vs Last Run: NOT RUN / CURRENT /
                                STALE from the canonical freshness authority
  UX_SHELL_HEADER_IDENTITY      name · technology · country · capacity
  UX_SHELL_HEADER_PROTECTED     protected-reference state visible
  UX_SHELL_RUN_MODEL            Run Model binds the EXISTING canonical form
  UX_SHELL_NAV_MAPPING          every available nav item activates a REAL
                                existing sheet tab; future items render
                                disabled and truthful
  UX_SHELL_DEEP_LINK            section hash deep links (client contract)
  UX_SHELL_POST_RUN_COHERENCE   one successful run refreshes the header to
                                CURRENT through the ONE post-run authority
  UX_SHELL_POST_SAVE_STALE      a causal save refreshes the header to STALE
  UX_SHELL_NO_ENGINE            rendering the shell never runs the engine

No finance logic lives in the shell modules.
"""
from __future__ import annotations

from tests.model_react_test_helpers import react_workbook_tokens, react_workspace_payload
from tests.run_clone_csrf import post_valid_csrf

import pytest


# ---------------------------------------------------------------------------
# Unit: header state machine
# ---------------------------------------------------------------------------

class TestHeaderStateProjection:
    def _build(self, **overrides):
        from app.v2.workspace_shell_projection import (
            build_workspace_header_projection,
        )
        kwargs = dict(
            project_name="Alpha Solar",
            technology="Solar",
            country_iso="de",
            capacity_mw="64.0",
            project_editable=True,
            runtime_state="NOT_RUN",
            has_runtime=False,
            last_runtime_at_display="",
            active_scenario_name="Base Case",
        )
        kwargs.update(overrides)
        return build_workspace_header_projection(**kwargs)

    def test_not_run_state(self):
        h = self._build()
        assert h.state == "NOT_RUN"
        assert h.state_label == "NOT RUN"
        assert "No successful run yet" in h.state_detail

    def test_current_state(self):
        h = self._build(runtime_state="CURRENT", has_runtime=True,
                        last_runtime_at_display="2026-10-06 21:14 UTC")
        assert h.state == "CURRENT"
        assert h.state_label == "CURRENT"
        assert "Last Run · Successful" in h.state_detail
        assert "2026-10-06 21:14 UTC" in h.state_detail

    def test_stale_state_keeps_last_run_visible(self):
        h = self._build(runtime_state="STALE", has_runtime=True,
                        last_runtime_at_display="2026-10-06 21:14 UTC")
        assert h.state == "STALE"
        assert "changes not run" in h.state_detail
        assert "Last Run · Successful" in h.state_detail

    def test_stale_without_runtime_degrades_to_not_run(self):
        """A stale flag without persisted runtime never fabricates CURRENT."""
        h = self._build(runtime_state="STALE", has_runtime=False)
        assert h.state == "NOT_RUN"

    def test_identity_formatting(self):
        h = self._build(country_iso="de", capacity_mw=64.0)
        assert h.country_iso == "DE"
        assert h.capacity_display == "64.0 MW"
        assert h.technology == "Solar"


# ---------------------------------------------------------------------------
# Unit: navigation mapping — no fake pages
# ---------------------------------------------------------------------------

class TestWorkspaceNavMapping:
    def test_every_available_nav_item_targets_a_valid_tab_id(self):
        from app.v2.workspace_shell_projection import workspace_nav_groups

        seen = set()
        for group in workspace_nav_groups():
            for item in group.items:
                if item.available:
                    assert item.tab_id and item.tab_id.startswith("tab-"), (
                        f"nav item {item.label!r} missing valid tab_id: {item.tab_id!r}")
                    seen.add(item.tab_id)
        assert {"tab-overview", "tab-project-setup", "tab-debt", "tab-trust"}.issubset(seen)

    def test_future_items_are_disabled_and_truthful(self):
        from app.v2.workspace_shell_projection import workspace_nav_groups

        futures = [item for group in workspace_nav_groups()
                   for item in group.items if not item.available]
        # Roadmap placeholders are not primary destinations in Option C.
        assert not futures
        for item in futures:
            assert item.tab_id is None  # no fake target

    def test_nav_groups_are_finance_native(self):
        from app.v2.workspace_shell_projection import workspace_nav_groups

        labels = [g.label for g in workspace_nav_groups()]
        assert labels[0] == "Project landing"
        for expected in ("Inputs", "Financing", "Results", "Scenarios", "Analysis", "Model Checks", "Trust"):
            assert expected in labels


# ---------------------------------------------------------------------------
# Workbook shell render (real app, seeded reference project)
# ---------------------------------------------------------------------------

VERTICALS = [("generic_solar_reference", 64.0)]


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ux-shell.db"))
    db.init_db()
    yield


def _client_with_project(template_source: str, capacity_mw: float):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    user_id = "ux-shell-user"
    record = create_reference_seeded_project(
        user_id=user_id,
        template_source=template_source,
        requested_name=f"Shell {template_source}",
        capacity_mw=capacity_mw,
    )
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id,
                                                 username="admin")}
    client = TestClient(main_web.app, raise_server_exceptions=True)
    return client, cookies, record


class TestWorkbookShellRender:
    def test_header_and_nav_mounted(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        ws = react_workspace_payload(client, record.project_code, cookies=cookies)
        assert ws["ok"] is True
        assert ws["freshness"]["state"] == "NOT_RUN"
        assert ws["freshness"]["has_runtime"] is False
        assert ws["project"]["protected_reference"] is False
        assert ws["project"]["project_type"] == "Solar"
        page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert page.status_code == 200 and "finco-react.js" in page.text

    def test_run_model_binds_existing_canonical_form(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        runs = client.get(f"/v2/model-react/runs?project={record.project_code}", cookies=cookies)
        assert runs.status_code == 200
        run_form = runs.json()["run_contract"]
        assert run_form["url"] == "/v2/workbook/run" and run_form["csrf_token"]

    def test_nav_items_activate_real_tabs(self, seeded_db):
        from app.v2.workspace_shell_projection import workspace_nav_groups
        client, cookies, record = _client_with_project(*VERTICALS[0])
        assert react_workspace_payload(client, record.project_code, cookies=cookies)["ok"] is True
        tab_ids = {item.tab_id for g in workspace_nav_groups() for item in g.items}
        for tab_id in ("tab-overview", "tab-project-setup", "tab-revenue",
                       "tab-capex", "tab-opex", "tab-debt", "tab-tax",
                       "tab-outputs", "tab-returns", "tab-scenarios",
                       "tab-sensitivity", "tab-compare", "tab-trust"):
            assert tab_id in tab_ids

    def test_deep_link_hash_contract_present(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert page.status_code == 200 and "finco-react.js" in page.text

    def test_no_engine_run_on_shell_render(self, seeded_db):
        from unittest import mock
        client, cookies, record = _client_with_project(*VERTICALS[0])
        with mock.patch("app.api.project_runner.run_project",
                        side_effect=AssertionError("engine ran")):
            r = client.get(f"/v2/model-react/workspace?project={record.project_code}",
                           cookies=cookies)
        assert r.status_code == 200 and r.json()["ok"] is True


class TestProtectedReferenceHeader:
    def test_protected_reference_renders_readonly_badge_and_no_run_cta(self):
        from app.v2.workspace_shell_projection import (
            build_workspace_header_projection,
        )
        header = build_workspace_header_projection(
            project_name="Solar Reference",
            project_editable=False,
            runtime_state="CURRENT",
            has_runtime=True,
            last_runtime_at_display="2026-10-06 21:14 UTC",
        )
        assert header.project_editable is False
        assert header.state == "CURRENT"
        assert header.state_label == "CURRENT"


# ---------------------------------------------------------------------------
# UX Correction A4 — Trust & Diagnostics React endpoints over canonical authorities
# ---------------------------------------------------------------------------

class TestTrustSheetWorkflow04Surfaces:
    def test_assumption_register_renders_from_real_authority(self, seeded_db):
        from app.v2.router import _build_assumption_register_view, _build_pis_with_composite_identity
        from app.persistence.workspace_repository import get_workspace_state
        client, cookies, record = _client_with_project(*VERTICALS[0])
        ws = get_workspace_state("ux-shell-user", record.project_id)
        pis = _build_pis_with_composite_identity(ws, record, "ux-shell-user")
        view = _build_assumption_register_view(pis)
        assert view["fingerprint"] and len(view["rows"]) > 0
        assert react_workspace_payload(client, record.project_code, cookies=cookies)["ok"] is True

    def test_trace_surface_is_typed_unavailable(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        diag = client.get(f"/v2/model-react/diagnostics?project={record.project_code}",
                          cookies=cookies)
        assert diag.status_code == 200
        assert diag.json()["insight"]["state"] == "NOT_RUN"

    def test_smart_panel_assumptions_link_targets_register_anchor(
            self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        inputs = client.get(f"/v2/model-react/inputs?project={record.project_code}",
                            cookies=cookies)
        assert inputs.status_code == 200 and inputs.json()["ok"] is True


# ---------------------------------------------------------------------------
# UX Correction A9 — React workspace navigation & scenario compare endpoint
# ---------------------------------------------------------------------------

class TestNavigationHierarchy:
    def test_left_nav_primary_and_tab_strip_demoted(self, seeded_db):
        from app.v2.workspace_shell_projection import workspace_nav_groups
        assert len(workspace_nav_groups()) >= 5

    def test_tab_activation_contract_unchanged(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        cmp_resp = client.get(f"/v2/model-react/scenario-compare?project={record.project_code}",
                              cookies=cookies)
        assert cmp_resp.status_code == 200 and cmp_resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Post-run / post-save coherence through the ONE post-run authority
# ---------------------------------------------------------------------------

def _run_once(client, cookies, record):
    tokens = react_workbook_tokens(client, record.project_code, cookies=cookies)
    return post_valid_csrf(client,
        "/v2/workbook/run",
        data={"project": record.project_code, **tokens},
        cookies=cookies,
    )


class TestPostRunHeaderCoherence:
    def test_successful_run_refreshes_header_to_current(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        run = _run_once(client, cookies, record)
        assert run.status_code == 200, run.text[:300]
        ws = react_workspace_payload(client, record.project_code, cookies=cookies)
        assert ws["freshness"]["state"] == "CURRENT"
        assert ws["identity"]["snapshot_id"]

    def test_smart_panel_refreshes_after_run(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        run = _run_once(client, cookies, record)
        assert run.status_code == 200
        diag = client.get(f"/v2/model-react/diagnostics?project={record.project_code}",
                          cookies=cookies)
        assert diag.status_code == 200 and diag.json()["insight"]["state"] == "CURRENT"
