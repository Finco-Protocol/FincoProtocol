"""Model V2 UX Foundation — Model Home (UX-1) acceptance.

Covers the Model Home product contracts:

  UX_HOME_LIBRARY_FIRST          Model entry opens Model Home, never a project
  UX_HOME_HIERARCHY              hero → New Project → Recent → Reference Models
  UX_HOME_EMPTY_STATE            empty Recent block collapses to onboarding
  UX_HOME_POPULATED_RECENT       compact decision-useful rows, persisted evidence
  UX_HOME_REFERENCE_MODELS       Open model / Create working copy semantics
  UX_HOME_PREVIEW_STATE          unsupported verticals render PREVIEW, honestly
  UX_HOME_KPI_EVIDENCE           persisted Last Run evidence only; unavailable
                                 is omitted — never zero
  UX_HOME_NO_ENGINE              no engine execution anywhere on Model Home
  UX_HOME_SEARCH_PRESERVED       functional search/filter/paging unchanged

No engine execution happens on any Model Home code path.
"""
from __future__ import annotations

import re
from unittest import mock

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ux-home.db"))
    db.init_db()
    yield


def _client_and_cookie(user_id: str = "ux-home-user"):
    from app.auth import COOKIE_NAME, create_session_token
    from fastapi.testclient import TestClient
    import main_web

    cookies = {COOKIE_NAME: create_session_token(user_id=user_id,
                                                 username="admin")}
    client = TestClient(main_web.app, raise_server_exceptions=True)
    return client, cookies


def _create_working_project(user_id: str, name: str, code: str):
    """Create a minimal user project row via the repository authority."""
    from app.persistence.projects_repository import save_project

    return save_project(
        user_id=user_id,
        project_code=code,
        project_name=name,
        source_project_template="generic_solar_reference",
        project_type="solar",
        project_origin="user",
        template_source="generic_solar_reference",
    )


class TestModelEntryLibraryFirst:
    def test_model_home_renders_library(self, seeded_db):
        client, cookies = _client_and_cookie()
        r = client.get("/library", cookies=cookies)
        assert r.status_code == 200
        # Library-first hero — Model entry is Model Home, not a project.
        assert "FINCO MODEL" in r.text
        assert "/projects/new" in r.text
        # Never auto-opens a workbook surface.
        assert "/v2/workbook?" not in r.text.split("library-list-region")[0]

    def test_new_project_is_the_primary_cta(self, seeded_db):
        client, cookies = _client_and_cookie()
        html = client.get("/library", cookies=cookies).text
        cta = re.search(r'<a href="/projects/new" class="fo-library-cta-new"', html)
        assert cta is not None


class TestEmptyState:
    def test_no_projects_collapses_recent_and_shows_onboarding(self, seeded_db):
        client, cookies = _client_and_cookie()
        html = client.get("/library", cookies=cookies).text
        assert 'data-testid="library-onboarding"' in html
        assert "No working projects yet" in html
        # The populated "Recent Projects" section heading is not rendered.
        assert ">Recent Projects<" not in html

    def test_references_visible_in_empty_state(self, seeded_db):
        client, cookies = _client_and_cookie()
        html = client.get("/library", cookies=cookies).text
        assert "Reference Models" in html
        assert html.count("Create working copy") >= 1


class TestPopulatedRecentProjects:
    def test_recent_first_and_rows_carry_persisted_evidence(self, seeded_db):
        user = "ux-home-populated"
        client, cookies = _client_and_cookie(user)
        _create_working_project(user, "Alpha Park", "alpha-park")
        html = client.get("/library", cookies=cookies).text
        recent_at = html.index("Recent Projects")
        references_at = html.index("Reference Models")
        assert recent_at < references_at  # Recent Projects first
        assert 'data-testid="library-row-alpha-park"' in html
        # No persisted run yet → typed NOT RUN, never a fabricated timestamp.
        assert 'data-testid="last-run-none-alpha-park"' in html
        assert "Not run" in html

    def test_last_run_timestamp_when_persisted(self, seeded_db):
        from datetime import datetime, timezone

        user = "ux-home-lastrun"
        client, cookies = _client_and_cookie(user)
        record = _create_working_project(user, "Beta Park", "beta-park")
        from app.persistence.workspace_repository import save_workspace_state as _sws
        _sws(
            user_id=user,
            project_id=record.project_id,
            project_code="beta-park",
            active_scenario_id=None,
            active_scenario_name=None,
            draft_snapshot={},
            saved_snapshot={},
            last_runtime_snapshot={},
            last_runtime_summary={"project_irr": 0.08},
            last_runtime_snapshot_id="snap-1",
            last_runtime_origin="v2_run",
            last_runtime_scenario_id=None,
            last_financial_statements={},
            last_debt_schedule={},
            last_tax_schedule={},
            last_distribution_schedule={},
            last_sponsor_schedule={},
            dirty=False,
            governance_state={},
            replay_metadata={},
            last_runtime_at=datetime(2026, 10, 6, 21, 14, tzinfo=timezone.utc),
        )
        html = client.get("/library", cookies=cookies).text
        assert 'data-testid="last-run-beta-park"' in html
        assert "Last run · 2026-10-06" in html


class TestReferenceModels:
    def test_open_model_and_create_working_copy(self, seeded_db):
        client, cookies = _client_and_cookie()
        html = client.get("/library", cookies=cookies).text
        assert "Open model" in html
        assert "View Reference" not in html
        assert html.count("Create working copy") >= 1

    def test_storage_renders_explicit_preview_state(self, seeded_db):
        client, cookies = _client_and_cookie()
        html = client.get("/library", cookies=cookies).text
        assert 'data-testid="preview-state-generic_storage_reference-reference"' in html
        assert "PREVIEW" in html
        assert "Editable runtime not yet supported" in html


class TestReferenceKpiEvidence:
    def test_unavailable_evidence_is_omitted_never_zero(self):
        """No persisted Last Run → no KPI row at all (never '0.00%')."""
        from types import SimpleNamespace
        from app.library.model_home import build_reference_cards

        record = SimpleNamespace(
            project_id="p1", project_code="ref", project_name="Solar Reference",
            project_type="solar", is_protected=True)
        cards = build_reference_cards([record], {"p1": None})
        assert cards[0].kpis == ()

    def test_partial_evidence_shows_only_available_keys(self):
        """A KPI missing from the persisted summary is omitted; a present
        one renders with the canonical formatter (unavailable != zero)."""
        from types import SimpleNamespace
        from app.library.model_home import build_reference_cards

        record = SimpleNamespace(
            project_id="p1", project_code="ref", project_name="Solar Reference",
            project_type="solar", is_protected=True)
        ws = SimpleNamespace(last_runtime_summary={
            "project_irr": 0.087,       # available → "8.70%"
            "senior_debt_keur": None,   # documented gap → omitted
            "min_dscr": 1.42,           # available → "1.42x"
        })
        cards = build_reference_cards([record], {"p1": ws})
        keys = [k for k, _label, _display in cards[0].kpis]
        assert keys == ["project_irr", "min_dscr"]
        displays = dict((k, d) for k, _l, d in cards[0].kpis)
        assert displays["project_irr"] == "8.70%"
        assert displays["min_dscr"] == "1.42x"

    def test_legitimate_zero_stays_zero(self):
        """A persisted 0.0 is a real AVAILABLE zero — it must render."""
        from types import SimpleNamespace
        from app.library.model_home import build_reference_cards

        record = SimpleNamespace(
            project_id="p1", project_code="ref", project_name="R",
            project_type="solar", is_protected=True)
        ws = SimpleNamespace(last_runtime_summary={"min_dscr": 0.0})
        cards = build_reference_cards([record], {"p1": ws})
        assert cards[0].kpis[0][2] == "0.00x"


class TestNoEngineOnModelHome:
    def test_engine_never_runs_when_rendering_library(self, seeded_db):
        user = "ux-home-noengine"
        client, cookies = _client_and_cookie(user)
        _create_working_project(user, "Gamma Park", "gamma-park")
        with mock.patch("app.api.project_runner.run_project",
                        side_effect=AssertionError("engine ran")):
            r = client.get("/library", cookies=cookies)
            r2 = client.get("/library/list", cookies=cookies)
        assert r.status_code == 200
        assert r2.status_code == 200


class TestSearchPreserved:
    def test_filter_form_and_pagination_contract_intact(self, seeded_db):
        client, cookies = _client_and_cookie()
        html = client.get("/library", cookies=cookies).text
        assert 'id="library-filter-form"' in html
        assert 'hx-get="/library/list"' in html
        assert 'name="role"' in html
        # HTMX list partial still serves the region.
        partial = client.get("/library/list", cookies=cookies)
        assert partial.status_code == 200
        assert 'id="library-clone-error"' in partial.text
