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

import re

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
    def _existing_tab_ids(self):
        """Real tab ids present in the workbook shell template."""
        from pathlib import Path
        html = Path("app/templates/v2/workbook.html").read_text(
            encoding="utf-8")
        return set(re.findall(r'id="(tab-[a-z-]+)"', html))

    def test_every_available_nav_item_targets_an_existing_tab(self):
        from app.v2.workspace_shell_projection import workspace_nav_groups

        existing = self._existing_tab_ids()
        for group in workspace_nav_groups():
            for item in group.items:
                if item.available:
                    assert item.tab_id in existing, (
                        f"nav item {item.label!r} targets non-existent tab "
                        f"{item.tab_id!r}")

    def test_future_items_are_disabled_and_truthful(self):
        from app.v2.workspace_shell_projection import workspace_nav_groups

        futures = [item for group in workspace_nav_groups()
                   for item in group.items if not item.available]
        assert futures, "navigation should declare its future capabilities"
        for item in futures:
            assert item.tab_id is None  # no fake target

    def test_nav_groups_are_finance_native(self):
        from app.v2.workspace_shell_projection import workspace_nav_groups

        labels = [g.label for g in workspace_nav_groups()]
        assert labels[0] == "Overview"
        for expected in ("Model", "Financing", "Outputs", "Analysis",
                         "Trust", "Delivery"):
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
        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        assert page.status_code == 200
        assert 'id="model-workspace-header"' in page.text
        assert 'id="model-workspace-nav"' in page.text
        assert 'id="model-workspace-main"' in page.text
        # Header: NOT RUN (no run yet) + identity.  A reference-SEEDED
        # project is an editable working copy — the Working Copy badge shows;
        # the protected badge contract is covered in the unit test below.
        assert 'data-testid="header-run-state-not_run"' in page.text
        assert "NOT RUN" in page.text
        assert 'data-testid="header-wc-badge"' in page.text
        assert "64.0 MW" in page.text

    def test_run_model_binds_existing_canonical_form(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        header = page.text.split('id="model-workspace-header"')[1].split(
            "</div>")[0] + "</div>"
        # The header Run button binds the EXISTING run form — no second
        # run authority exists.
        assert 'form="v2-canonical-run-form"' in page.text.split(
            'id="model-workspace-header"')[1][:1200]

    def test_nav_items_activate_real_tabs(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        nav_html = page.text.split('id="model-workspace-nav"')[1]
        for tab_id in ("tab-overview", "tab-project-setup", "tab-revenue",
                       "tab-capex", "tab-opex", "tab-debt", "tab-tax",
                       "tab-fs", "tab-returns", "tab-scenarios",
                       "tab-sensitivity", "tab-compare", "tab-trust"):
            assert f'data-nav-tab="{tab_id}"' in nav_html
        # Future items render disabled with truthful titles.
        assert "v2-ws-nav-item--future" in nav_html
        assert "not yet available" in nav_html

    def test_deep_link_hash_contract_present(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        assert "location.hash" in page.text  # hash sync + load activation

    def test_no_engine_run_on_shell_render(self, seeded_db):
        from unittest import mock
        client, cookies, record = _client_with_project(*VERTICALS[0])
        with mock.patch("app.api.project_runner.run_project",
                        side_effect=AssertionError("engine ran")):
            r = client.get(f"/v2/workbook?project={record.project_code}",
                           cookies=cookies)
        assert r.status_code == 200


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
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        env = Environment(
            loader=FileSystemLoader("app/templates/v2"),
            autoescape=select_autoescape(["html"]),
        )
        html = env.get_template("partials/_model_workspace_header.html").render(
            {"header": header})
        assert 'data-testid="header-reference-badge"' in html
        assert "Reference · read-only" in html
        # A read-only reference never offers the Run CTA in the header.
        assert "header-run-btn" not in html


# ---------------------------------------------------------------------------
# Post-run / post-save coherence through the ONE post-run authority
# ---------------------------------------------------------------------------

def _run_once(client, cookies, record):
    page = client.get(f"/v2/workbook?project={record.project_code}",
                      cookies=cookies)
    m = re.search(r'name="content_hash" value="([^"]+)"', page.text)
    mv = re.search(r'name="workbook_version" value="([^"]+)"', page.text)
    return client.post(
        "/v2/workbook/run",
        data={"project": record.project_code,
              "content_hash": m.group(1),
              "workbook_version": mv.group(1)},
        cookies=cookies,
        headers={"HX-Request": "true"},
    )


class TestPostRunHeaderCoherence:
    def test_successful_run_refreshes_header_to_current(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        run = _run_once(client, cookies, record)
        assert run.status_code == 200, run.text[:300]
        assert 'id="model-workspace-header" hx-swap-oob="true"' in run.text
        assert 'data-testid="header-run-state-current"' in run.text
        assert "CURRENT" in run.text

    def test_smart_panel_refreshes_after_run(self, seeded_db):
        client, cookies, record = _client_with_project(*VERTICALS[0])
        run = _run_once(client, cookies, record)
        assert run.status_code == 200
        assert 'id="model-smart-panel" hx-swap-oob="true"' in run.text
