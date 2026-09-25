"""EV Charging Correction C — charging-efficiency percent authority + fail-closed
driver validation.

Canonical representation contract:
    UI input      = 94     (human percent, registry PCT min 50 / max 100)
    snapshot      = "94"   (persisted human percent)
    runtime typed = 0.94   (fraction, EVChargingDrivers.charging_efficiency)

Fail-closed contract: a driver key that is EXPLICITLY present in the snapshot
but malformed, out of range, or ramp-inconsistent raises
``EVDriverValidationError`` — it is never silently replaced by the reference
default.  Missing/blank keys still default for backward compatibility.

Efficiency end-to-end causality is exercised through the REAL workbook HTMX
form (94 → 92), the same representation a user edits, then proven in the
runtime: revenue unchanged, grid purchase and B.08 grow by exactly 94/92.
"""

from __future__ import annotations

import re

import pytest

from app import ev_charging_economics as ev
from finco_core.opex.projections import opex_item_amount_at_year


@pytest.fixture()
def ev_wc(tmp_path, monkeypatch):
    """Fresh DB + a real seeded EV working copy (reconciled S&U)."""
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "corc.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="corc-user", template_source="generic_ev_charging_reference",
        requested_name="CorC Efficiency", capacity_mw=5.0,
    )
    return record


def _client():
    from fastapi.testclient import TestClient
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=True)


def _cookies():
    from app.auth import COOKIE_NAME, create_session_token
    return {COOKIE_NAME: create_session_token(user_id="corc-user", username="admin")}


def _rendered_efficiency_form(page_html: str) -> dict[str, str]:
    """Extract the efficiency field's real form values from rendered HTML."""
    i = page_html.find('data-field-id="revenue.ev_charging.charging_efficiency"')
    assert i != -1, "efficiency field not rendered"
    block = page_html[i:i + 3000]
    form_start = block.rfind("<form", 0, block.find('name="value"'))
    form_html = block[form_start:block.find("</form>", block.find('name="value"'))]
    values = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', form_html))
    values["value"] = re.search(r'name="value"([^>]*)value="([^"]*)"', block).group(2)
    return values


# ── §A/B: percent convention ────────────────────────────────────────────────

def test_seed_persists_efficiency_as_human_percent(ev_wc):
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state("corc-user", ev_wc.project_id)
    assert float(ws.draft_snapshot["ev_charging_efficiency"]) == pytest.approx(94.0)


def test_resolver_converts_percent_to_runtime_fraction(ev_wc):
    from app.persistence.workspace_repository import get_workspace_state
    from app.input_adapter import build_projectinputs_from_snapshot
    ws = get_workspace_state("corc-user", ev_wc.project_id)
    pi = build_projectinputs_from_snapshot(dict(ws.draft_snapshot))
    drivers = ev.drivers_from_snapshot(dict(ws.draft_snapshot))
    assert drivers.charging_efficiency == pytest.approx(0.94)
    # runtime electricity uses the fraction
    elec = next(i for i in pi.opex if i.name == "Electricity Procurement")
    assert opex_item_amount_at_year(elec, 3) == pytest.approx(
        5.0 * 2000.0 / 0.94 * 120.0 * (1.02 ** 2) / 1000.0, rel=1e-9
    )


def test_snapshot_values_emit_human_percent():
    drivers = ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS
    values = ev.ev_driver_snapshot_values(drivers)
    assert float(values["ev_charging_efficiency"]) == pytest.approx(94.0)


# ── §E: fail-closed explicit invalid input ──────────────────────────────────

def test_explicit_invalid_efficiency_fails_closed():
    from app.ev_charging_economics import EVDriverValidationError
    with pytest.raises(EVDriverValidationError):
        ev.drivers_from_snapshot({"ev_charging_efficiency": "0.92"})  # fraction, not percent


def test_explicit_out_of_range_efficiency_fails_closed():
    from app.ev_charging_economics import EVDriverValidationError
    with pytest.raises(EVDriverValidationError):
        ev.drivers_from_snapshot({"ev_charging_efficiency": "150"})


def test_explicit_malformed_price_fails_closed():
    from app.ev_charging_economics import EVDriverValidationError
    with pytest.raises(EVDriverValidationError):
        ev.drivers_from_snapshot({"ev_charging_price_eur_kwh": "abc"})


def test_explicit_negative_price_fails_closed():
    from app.ev_charging_economics import EVDriverValidationError
    with pytest.raises(EVDriverValidationError):
        ev.drivers_from_snapshot({"ev_charging_price_eur_kwh": "-1"})


def test_explicit_malformed_escalation_fails_closed():
    from app.ev_charging_economics import EVDriverValidationError
    with pytest.raises(EVDriverValidationError):
        ev.drivers_from_snapshot({"ev_charging_price_escalation": "two percent"})


def test_missing_keys_still_default_safely():
    drivers = ev.drivers_from_snapshot({})
    assert drivers == ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS


def test_invalid_driver_never_silently_defaults_in_snapshot_resolution(ev_wc):
    """End of the real resolution path: an explicit invalid driver must blow up
    the materialization, never run on silently-substituted defaults."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.ev_charging_economics import EVDriverValidationError
    ws = get_workspace_state("corc-user", ev_wc.project_id)
    snapshot = dict(ws.draft_snapshot)
    snapshot["ev_charging_price_eur_kwh"] = "not-a-number"
    with pytest.raises(EVDriverValidationError):
        build_projectinputs_from_snapshot(snapshot)


def test_ramp_invalid_edit_fails_closed():
    """An explicit Y2 > stabilized edit is a visible validation failure —
    never silently clamped into the user's value."""
    from app.ev_charging_economics import EVDriverValidationError
    with pytest.raises(EVDriverValidationError, match="non-decreasing"):
        ev.drivers_from_snapshot({
            "ev_full_load_hours_y1": "1200",
            "ev_full_load_hours_y2": "2500",
            "ev_full_load_hours_stabilized": "2000",
        })
    with pytest.raises(EVDriverValidationError, match="non-decreasing"):
        ev.drivers_from_snapshot({
            "ev_full_load_hours_y1": "1800",
            "ev_full_load_hours_y2": "1600",
            "ev_full_load_hours_stabilized": "2000",
        })


# ── §C: real workbook form edit 94 → 92 (HTMX), runtime causality, reload ───

def test_efficiency_form_edit_causality_end_to_end(ev_wc):
    from app.persistence.workspace_repository import get_workspace_state
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.services.production_waterfall_seam import execute_production_waterfall

    client = _client()
    cookies = _cookies()
    page = client.get(f"/v2/workbook?project={ev_wc.project_code}", cookies=cookies)
    assert page.status_code == 200

    # The real rendered form for the efficiency field carries the human-percent
    # representation a user sees.
    form = _rendered_efficiency_form(page.text)
    assert form["field_id"] == "revenue.ev_charging.charging_efficiency"
    assert float(form["value"]) == pytest.approx(94.0)
    assert {"project", "sheet_id", "field_id", "workbook_version", "content_hash"}.issubset(form)

    # Baseline runtime: revenue + B.08 Y1 at 94 %
    def _resolved_runtime(snapshot_extra=None):
        ws = get_workspace_state("corc-user", ev_wc.project_id)
        snapshot = dict(ws.draft_snapshot)
        if snapshot_extra:
            snapshot.update(snapshot_extra)
        pi = build_projectinputs_from_snapshot(snapshot)
        result = execute_production_waterfall(pi).result
        periods = [p for p in result.periods if getattr(p, "is_operation", True)]
        revenue = sum(float(p.revenue_keur or 0.0) for p in periods)
        elec = next(i for i in pi.opex if i.name == "Electricity Procurement")
        b08_y1 = opex_item_amount_at_year(elec, 1)
        return revenue, b08_y1

    revenue_94, b08_94 = _resolved_runtime()
    assert revenue_94 == pytest.approx(
        sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21)), rel=1e-6
    )

    # HTMX save through the real endpoint: 94 → 92
    form["value"] = "92"
    resp = client.post("/v2/workbook/update", data=form, cookies=cookies,
                       headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:400]

    # Snapshot persists the human-percent value
    ws = get_workspace_state("corc-user", ev_wc.project_id)
    assert float(ws.draft_snapshot["ev_charging_efficiency"]) == pytest.approx(92.0)

    # Runtime causality: revenue unchanged, B.08 increases by exactly 94/92
    revenue_92, b08_92 = _resolved_runtime()
    assert revenue_92 == pytest.approx(revenue_94, rel=1e-9), (
        "charging revenue must be unchanged by an efficiency edit"
    )
    assert b08_92 == pytest.approx(b08_94 * (0.94 / 0.92), rel=1e-9)
    assert b08_92 > b08_94

    # Reload: the rendered form shows the persisted 92 with a fresh hash
    page2 = client.get(f"/v2/workbook?project={ev_wc.project_code}", cookies=cookies)
    form2 = _rendered_efficiency_form(page2.text)
    assert float(form2["value"]) == pytest.approx(92.0)
    assert form2["content_hash"] != form["content_hash"]


# ── §F: display contract (registry-bound rendering) ─────────────────────────

def test_efficiency_renders_94_percent_with_institutional_bounds(ev_wc):
    client = _client()
    page = client.get(f"/v2/workbook?project={ev_wc.project_code}", cookies=_cookies())
    block = page.text[
        page.text.find('data-field-id="revenue.ev_charging.charging_efficiency"'):]
    m = re.search(r'name="value"([^>]*)value="([^"]*)"', block)
    value = float(m.group(2))
    assert value == pytest.approx(94.0), "initial UI value must be 94 (%), not 0.94"
    attrs = m.group(1)
    assert 'min="50"' in attrs and 'max="100"' in attrs
    assert value >= 50 and value <= 100
