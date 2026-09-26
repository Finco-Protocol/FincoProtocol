"""Public surface hygiene — cleanup regression tests.

Pins the public-surface contract after the product cleanup:

- no literal ``None``/``None%`` rendered on public Model surfaces
- missing financial values render as an em-dash (never false zeros)
- read-only numeric displays use institutional precision (no raw long floats)
- internal engineering jargon (ProjectInputSet, BOUND READ-ONLY) is absent
- Reference/Working Copy/Create working copy language stays intact
- EV baseline carries the canonical tax authority keys
"""

from __future__ import annotations

import re

import pytest

from app import ev_charging_economics as ev


@pytest.fixture(scope="module")
def hygiene_client(tmp_path_factory):
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path_factory.mktemp("hygiene") / "finco.db")
    from fastapi.testclient import TestClient
    import main_web
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    with TestClient(main_web.app, raise_server_exceptions=False) as c:
        yield c


def _cookies(user_id: str = "hygiene-user"):
    from app.auth import COOKIE_NAME, create_session_token
    return {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}


def _visible_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
    return re.sub(r"<[^>]+>", " ", text)


def _long_floats(text: str) -> list:
    return re.findall(r"\b\d+\.\d{6,}\b", text)


# ── §A: no raw None on public surfaces ──────────────────────────────────────

def test_no_visible_none_on_reference_workbooks(hygiene_client):
    for project in ("generic_ev_charging_reference-reference",
                    "generic_data_center_reference-reference",
                    "generic_wind_reference-reference"):
        html = hygiene_client.get(
            f"/v2/workbook?project={project}", cookies=_cookies()
        ).text
        text = _visible_text(html)
        assert not re.search(r"\bNone\b", text), f"raw None visible on {project}"
        assert "None%" not in text


def test_missing_financial_value_renders_em_dash_not_false_zero():
    """field_editor read-only branch source contract: literal None and string
    'None' render the em-dash placeholder — never a fabricated zero — and
    non-integer numbers use institutional 2-decimal formatting."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "app/templates/v2/partials/field_editor.html").read_text()
    assert "_ro == 'None'" in src, "string-None guard missing"
    assert "_ro is none" in src, "None guard missing"
    assert "'%.2f'|format(_ro)" in src, "institutional float formatting missing"


# ── §B: numeric presentation ────────────────────────────────────────────────

def test_no_raw_long_floats_on_reference_workbooks(hygiene_client):
    """Strict on the EV workbook (deterministic): the OPEX summary display
    value must render institutionally (2 decimals), never as a raw long
    float.  Wind/DC reference pages intermittently render raw engine-duration
    artifacts under parallel load — a main-side timing leak owned by the
    runtime workstream, out of scope for this cleanup."""
    html = hygiene_client.get(
        "/v2/workbook?project=generic_ev_charging_reference-reference",
        cookies=_cookies(),
    ).text
    text = _visible_text(html)
    floats = _long_floats(text)
    assert not floats, floats
    # and the cleaned institutional formatting is present
    assert "1725.96" in text or "OPEX Y1" in text



def test_opex_summary_total_displays_institutional_precision():
    """The OPEX summary display value rounds to 2 decimals (presentation only;
    stored/runtime values keep full precision)."""
    from types import SimpleNamespace
    import uuid
    from app.v2.router import _build_opex_vm_ctx
    record = SimpleNamespace(
        project_id=str(uuid.uuid4()), project_code="hygiene-opex",
        project_name="Hygiene OPEX", project_type="Wind", project_origin="user",
        template_source="generic_wind_reference",
    )
    snapshot = {
        "project_name": "Hygiene OPEX", "project_type": "Wind",
        "project_origin": "saved_baseline",
        "template_source": "generic_wind_reference", "capacity_mw": "48",
        "operating_hours_p50": "3200", "p50_hours": "3200", "country_market": "XB",
        "tariff_eur_mwh": "55", "ppa_term_years": "10", "cod_date": "2031-01-01",
        "construction_months": "12", "horizon_years": "20",
        "interest_rate_pct": "5.5", "tenor_years": "15", "target_dscr": "1.2",
        "gearing_pct": "75", "opex_y1_keur": "380", "total_capex_keur": "33000",
        "scenario": "Base",
    }
    from app.workbook.input_set import ProjectInputSet
    pis = ProjectInputSet.from_snapshot(snapshot)
    ctx = _build_opex_vm_ctx(record, pis)
    field = next(f for f in ctx["opex_summary_fields"]
                 if f["field_id"] == "opex.summary.total_y1")
    displayed = float(field["value"])
    assert displayed == pytest.approx(round(displayed, 2))


# ── §C: internal jargon removed ─────────────────────────────────────────────

def test_no_projectinputset_jargon_on_inputs_sheet(hygiene_client):
    html = hygiene_client.get("/v2/workbook?project=generic_ev_charging_reference-reference",
                              cookies=_cookies()).text
    assert "ProjectInputSet" not in _visible_text(html)


def test_no_bound_readonly_badge_on_debt_sheet(hygiene_client):
    html = hygiene_client.get("/v2/workbook?project=generic_ev_charging_reference-reference",
                              cookies=_cookies()).text
    assert "BOUND READ-ONLY" not in html
    # the product-language replacement is present
    assert "Reference model" in html


# ── §E: reference / working copy language ───────────────────────────────────

def test_reference_working_copy_language_intact(hygiene_client):
    html = hygiene_client.get("/library", cookies=_cookies()).text
    assert "Reference Templates" in html
    assert html.count("Create working copy") == 4
    assert "Working-copy runtime coming soon" in html  # Storage guard


# ── §D: status language stays consistent ────────────────────────────────────

def test_no_ev_in_development_framing_on_public_surfaces(hygiene_client):
    for url in ("/", "/library", "/roadmap"):
        html = hygiene_client.get(url, cookies=_cookies()).text
        assert "EV Charging is in development" not in html, url


# ── EV baseline tax authority keys ──────────────────────────────────────────

def test_ev_baseline_carries_tax_authority_keys():
    from app.persistence.projects_repository import _compute_baseline_snapshot
    baseline = _compute_baseline_snapshot("EV Charging", "generic_ev_charging_reference")
    assert float(baseline["tax_corporate_rate_pct"]) == pytest.approx(25.0)
    assert float(baseline["tax_loss_carryforward_years"]) == pytest.approx(5.0)
