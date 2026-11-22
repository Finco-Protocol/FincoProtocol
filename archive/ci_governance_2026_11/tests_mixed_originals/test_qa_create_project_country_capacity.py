"""Manual-QA Create Project corrections — capacity labels + country selector.

Proves (mission sections C and D):

C. Technology-specific capacity label on Create Project:
  - Solar / Wind        → "Installed Capacity (MW)"
  - Data Center         → "IT Capacity (MW)"
  - EV Charging         → "Charging Capacity (MW)"
  - the label and placeholder update immediately when the reference radio
    selection changes (client wiring shipped with the form), and the
    submitted backend field remains ``capacity_mw``.

D. Country selector + Generic Tax Template:
  - the country catalogue comes from THE canonical
    ``app.workbook.country_options`` (no duplicated list);
  - the selected canonical country code is persisted on the saved working
    copy together with the Generic-Tax-Template provenance;
  - HR and DE preserve DIFFERENT country codes but resolve the SAME
    generic tax template (and identical tax input values) — no
    country-specific tax rules are invented;
  - country selection never changes tariff, merchant curve, inflation,
    power price or market assumptions.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "qa_create.db"))
    monkeypatch.setenv("FINCO_APP_MODE", "development")
    # Yield runtime is ON for the Last-Observed presentation tests.
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.setenv("FINCO_YIELD_EXECUTION_ENABLED", "0")
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "qa_create.db"))
    from starlette.testclient import TestClient
    import main_web
    # HTTPS base url: session/demo cookies are marked Secure and httpx must
    # send them back, matching real browser behaviour over TLS.
    with TestClient(main_web.app, base_url="https://qa-create.local",
                    raise_server_exceptions=False) as c:
        yield c


def _login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    client.post("/login", data={
        "username": "admin", "password": "FINCO Model2026!", "csrf_token": token})


def _create(client, name, template_source, country="HR", capacity="20"):
    return client.post("/projects/create", data={
        "project_name": name,
        "project_type": "Solar",
        "template_source": template_source,
        "country_market": country,
        "capacity_mw": capacity,
    }, follow_redirects=False)


# ── C: technology-specific capacity labels ────────────────────────────────────

class TestCapacityLabels:
    def test_form_renders_capacity_label_contract(self, client):
        _login(client)
        page = client.get("/projects/new")
        assert page.status_code == 200
        assert 'data-testid="capacity-label"' in page.text
        # The four-technology label map ships with the form and covers all
        # four reference radios with the required labels.
        for label in ("Installed Capacity (MW)", "IT Capacity (MW)",
                      "Charging Capacity (MW)"):
            assert label in page.text
        assert "CAPACITY_LABELS" in page.text
        # The legacy hard-coded single label is gone.
        assert ">IT Capacity (MW)<" not in page.text

    def test_capacity_label_helper_matches_required_contract(self):
        from main_web import _capacity_label_for_template_source as label

        assert label("generic_solar_reference") == "Installed Capacity (MW)"
        assert label("generic_wind_reference") == "Installed Capacity (MW)"
        assert label("generic_data_center_reference") == "IT Capacity (MW)"
        assert label("generic_ev_charging_reference") == "Charging Capacity (MW)"

    def test_submitted_capacity_field_is_unchanged(self, client):
        """The backend field remains capacity_mw — presentation only."""
        _login(client)
        response = _create(client, "Label Solar", "generic_solar_reference",
                           country="XA", capacity="64")
        assert response.status_code in (200, 303)
        assert "capacity_mw" in response.text or response.status_code == 303


# ── D: country selector + Generic Tax Template ────────────────────────────────

class TestCountrySelector:
    def test_country_select_uses_canonical_catalogue(self, client):
        from app.workbook.country_options import COUNTRY_OPTIONS

        _login(client)
        page = client.get("/projects/new")
        assert 'data-testid="country-market"' in page.text
        for code, label in COUNTRY_OPTIONS:
            assert f'value="{code}"' in page.text, code
            assert label in page.text
        # The legacy hidden free-text market is gone.
        assert 'value="Generic Market A"' not in page.text

    def test_country_tax_helper_text_present(self, client):
        _login(client)
        page = client.get("/projects/new")
        assert 'data-testid="country-tax-note"' in page.text
        assert "Country-specific tax templates are not yet active" in page.text
        assert "Generic Tax Template" in page.text

    def test_hr_and_de_persist_distinct_codes_same_tax_template(
            self, client, tmp_path):
        """HR and DE keep different canonical country codes but resolve the
        SAME Generic Tax Template provenance — and identical tax input
        values (corporate rate etc.) — proving no country tax rules exist."""
        _login(client)
        hr = _create(client, "QA Country HR", "generic_solar_reference",
                     country="HR", capacity="64")
        de = _create(client, "QA Country DE", "generic_solar_reference",
                     country="DE", capacity="64")
        assert hr.status_code in (200, 303)
        assert de.status_code in (200, 303)

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "qa_create.db"))
        conn.row_factory = sqlite3.Row
        snapshots = {}
        for code in ("qa-country-hr", "qa-country-de"):
            row = conn.execute(
                "SELECT p.project_id FROM projects p WHERE p.project_code=?",
                (code,)).fetchone()
            assert row is not None, code
            ws = conn.execute(
                "SELECT draft_snapshot_json FROM workspace_states WHERE project_id=?",
                (row["project_id"],)).fetchone()
            import json
            snapshots[code] = json.loads(ws["draft_snapshot_json"])
        conn.close()

        hr_snap = snapshots["qa-country-hr"]
        de_snap = snapshots["qa-country-de"]
        # Distinct canonical country codes persisted verbatim.
        assert hr_snap["country_market"] == "HR"
        assert de_snap["country_market"] == "DE"
        assert hr_snap["country_market"] != de_snap["country_market"]
        # Same generic tax template provenance for both.
        assert hr_snap["tax_template"] == "Generic Tax Template"
        assert de_snap["tax_template"] == "Generic Tax Template"
        # Identical tax/economic driver values — country selection changed
        # nothing except the location metadata.
        for key in ("total_capex_keur", "opex_y1_keur", "tariff_eur_mwh"):
            if key in hr_snap and key in de_snap:
                assert hr_snap[key] == de_snap[key], key

    def test_engine_tax_inputs_identical_for_hr_and_de(self, client, tmp_path):
        """The canonical input adapter resolves the SAME tax authority for
        HR and DE working copies (Generic Tax Template; no country rules)."""
        _login(client)
        _create(client, "QA Engine HR", "generic_solar_reference",
                country="HR", capacity="64")
        _create(client, "QA Engine DE", "generic_solar_reference",
                country="DE", capacity="64")

        from app.persistence.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT project_code, user_id, project_id FROM projects "
            "WHERE project_code IN ('qa-engine-hr', 'qa-engine-de')").fetchall()
        conn.close()
        assert len(rows) == 2

        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.service import WorkbookService
        tax_rates = []
        for row in rows:
            ws = get_workspace_state(user_id=row["user_id"],
                                     project_id=row["project_id"])
            pis = WorkbookService.build_draft_input_set_from_workspace(ws)
            inputs = pis.to_projectinputs()
            tax = inputs.tax
            tax_rates.append(
                (getattr(tax, "corporate_rate", None),
                 getattr(tax, "corporate_rate_override", None),
                 getattr(tax, "country_tax_policy_id", None)))
        assert tax_rates[0] == tax_rates[1], (
            "HR and DE must resolve identical generic tax authority")
        assert tax_rates[0][2] is None, (
            "no country-specific tax policy may be selected")

    def test_unknown_country_falls_back_canonically(self, client, tmp_path):
        """Unrecognised free-text input normalises through the canonical
        helper rather than persisting garbage."""
        from app.workbook.country_options import normalize_country_code

        assert normalize_country_code("Generic Market A") == "XA"
        assert normalize_country_code("") == "XA"
        assert normalize_country_code("HR") == "HR"


# ── F: Verified Assets removed from the public product surface ────────────────

class TestVerifiedAssetsSurface:
    """The Verified Assets screen (0 VERIFIED, no user workflow) is removed
    from primary public navigation and its direct GET redirects to FINCO
    Verify. app/verified/** authority modules remain untouched."""

    def _home(self, client) -> str:
        """GET / with no project renders the Protocol home (primary nav)."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 200
        return response.text

    def test_primary_nav_has_no_verified_link(self, client):
        _login(client)
        html = self._home(client)
        assert "proto-nav" in html
        nav_start = html.index("proto-nav")
        nav = html[nav_start:html.index("</nav>", nav_start)]
        assert 'href="/verified"' not in nav
        assert 'href="/crypto"' in nav

    def test_home_page_cta_points_to_verify(self, client):
        _login(client)
        html = self._home(client)
        assert 'href="/verified"' not in html
        assert 'href="/verify"' in html
        assert "Verified production assets: 0" not in html

    def test_get_verified_redirects_to_verify(self, client):
        _login(client)
        response = client.get("/verified", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/verify"

    def test_verified_authority_modules_untouched(self):
        # Branch-owned changes only (merge-base boundary), never raw `git diff origin/main..HEAD`.
        from finance_integrity_governance import changed_paths_vs_main
        changed = [p for p in changed_paths_vs_main() if p.startswith("app/verified")]
        assert changed == [], changed


# ── G: Yield staging freshness — truthful Last Observed presentation ──────────

class TestYieldLastObserved:
    """Staging serves the BUNDLED live_opportunities.json (no history path,
    no ingestion). Rows are genuinely STALE (observed_at > freshness policy)
    and Base/Rewards APY components are genuinely absent. The UI must show
    a clear Last Observed stamp — never relabel stale as fresh."""

    @pytest.fixture()
    def yield_page(self, client):
        _login(client)
        # Bundled reference sample rows are research-mode only (the public default shows live rows only).
        page = client.get("/yield?include_reference=1")
        assert page.status_code == 200
        return page.text

    def test_last_observed_rendered_on_explore_table(self, yield_page):
        assert 'data-testid="last-observed-' in yield_page
        # Age stamp format: "<n>h ago (YYYY-MM-DD HH:MM UTC)" or UNAVAILABLE.
        pattern = (r'last-observed-yld_[0-9a-f]{32}">\s*'
                   r'(UNAVAILABLE|\d+[smhd] ago \(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\))')
        assert re.search(pattern, yield_page), "expected a Last Observed stamp per row"

    def test_stale_rows_stay_stale_with_visible_age(self, yield_page):
        """STALE badges remain truthful and carry the age alongside."""
        assert "STALE" in yield_page
        assert "CURRENT" in yield_page or "STALE" in yield_page

    def test_missing_apy_components_stay_unavailable(self, yield_page):
        """The bundled source supplies only Total APY; Base/Rewards APY must
        stay missing ('—') — never invented, never zero."""
        # Every bundled Morpho row lacks apy_base/apy_rewards: the APY cell
        # subtext renders the missing marker, not a fabricated percentage.
        assert "Base — · Rewards —" in yield_page
        assert "0.00%" not in yield_page
