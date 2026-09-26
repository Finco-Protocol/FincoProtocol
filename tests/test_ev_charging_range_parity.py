"""EV Charging Correction D — canonical driver range parity + fail-closed
range/ramp validation.

Single range authority: ``EV_DRIVER_BOUNDS`` (runtime units) in
``app/ev_charging_economics.py``.  The Workbook registry derives its EV
min/max from the same authority (converted to display units), so the UI
validation contract and the runtime validation contract cannot drift.

Boundary matrix (§C): every explicit out-of-range persisted value raises
``EVDriverValidationError`` — no silent clamp, no silent default substitution.
Missing/blank keys still default to the canonical reference drivers.
"""

from __future__ import annotations

import re

import pytest

from app import ev_charging_economics as ev
from app.ev_charging_economics import (
    EV_DRIVER_BOUNDS,
    EVDriverValidationError,
    drivers_from_snapshot,
)


# Registry unit for percent-convention keys is human percent.
_DISPLAY_SCALE = {"ev_charging_price_escalation", "ev_electricity_price_escalation", "ev_charging_efficiency"}


_SUFFIX = {
    "ev_full_load_hours_y1": "hours_y1",
    "ev_full_load_hours_y2": "hours_y2",
    "ev_full_load_hours_stabilized": "hours_stabilized",
    "ev_charging_price_eur_kwh": "charging_price",
    "ev_charging_price_escalation": "charging_price_escalation",
    "ev_charging_efficiency": "charging_efficiency",
    "ev_electricity_price_eur_kwh": "electricity_price",
    "ev_electricity_price_escalation": "electricity_price_escalation",
}


def _inline_ramp(probe: dict) -> dict:
    """Converter: repr-float map → the raw string map the resolver expects."""
    return {k: repr(float(v)) for k, v in probe.items()}


def _runtime_value(key: str, raw: str) -> float:
    """Resolve a single explicit driver raw value to its runtime-unit value."""
    value = float(raw)
    if key in _DISPLAY_SCALE:
        value = value / 100.0
    return value


# ── §B: single range authority ──────────────────────────────────────────────

def test_registry_bounds_derived_from_canonical_authority():
    """Registry min/max must equal the canonical authority for every driver."""
    from app.workbook.registry import WORKBOOK
    for key, (low, high) in EV_DRIVER_BOUNDS.items():
        field = WORKBOOK.field(f"revenue.ev_charging.{_SUFFIX[key]}")
        reg_low, reg_high = float(field.min_value), float(field.max_value)
        if key in _DISPLAY_SCALE:
            low, high = low * 100.0, high * 100.0
        assert reg_low == pytest.approx(low), key
        assert reg_high == pytest.approx(high), key


# ── §C: full boundary matrix (explicit values) ──────────────────────────────

def _resolve_one(key: str, raw: str):
    drivers = drivers_from_snapshot({key: raw})
    attr = {
        "ev_full_load_hours_y1": "full_load_hours_y1",
        "ev_full_load_hours_y2": "full_load_hours_y2",
        "ev_full_load_hours_stabilized": "full_load_hours_stabilized",
        "ev_charging_price_eur_kwh": "charging_price_eur_kwh",
        "ev_charging_price_escalation": "charging_price_escalation",
        "ev_charging_efficiency": "charging_efficiency",
        "ev_electricity_price_eur_kwh": "electricity_price_eur_kwh",
        "ev_electricity_price_escalation": "electricity_price_escalation",
    }[key]
    return getattr(drivers, attr)


def _ok(key: str, raw: str, expected_runtime: float):
    assert _resolve_one(key, raw) == pytest.approx(expected_runtime), (key, raw)


def _reject(key: str, raw: str):
    with pytest.raises(EVDriverValidationError):
        _resolve_one(key, raw)


def _resolve_set(probe: dict) -> float:
    """Resolve a full ramp set; return the stabilized value for sanity."""
    return drivers_from_snapshot(probe).full_load_hours_stabilized


def test_efficiency_boundaries():
    _reject("ev_charging_efficiency", "49")
    _ok("ev_charging_efficiency", "50", 0.50)
    _ok("ev_charging_efficiency", "94", 0.94)
    _ok("ev_charging_efficiency", "100", 1.00)
    _reject("ev_charging_efficiency", "101")


def test_hours_boundaries_all_three_keys():
    # Each hours key is probed with a full monotonic ramp so the ramp check
    # never masks the range check being exercised.
    ramps = {
        "ev_full_load_hours_y1": lambda v: {
            "ev_full_load_hours_y1": v,
            "ev_full_load_hours_y2": "8760",
            "ev_full_load_hours_stabilized": "8760"},
        "ev_full_load_hours_y2": lambda v: {
            "ev_full_load_hours_y1": "0",
            "ev_full_load_hours_y2": v,
            "ev_full_load_hours_stabilized": "8760"},
        "ev_full_load_hours_stabilized": lambda v: {
            "ev_full_load_hours_y1": "0",
            "ev_full_load_hours_y2": "0",
            "ev_full_load_hours_stabilized": v},
    }
    for key, ramp in ramps.items():
        _reject(key, "-1")
        _reject(key, "8761")
        for value in ("0", "8760"):
            drivers = drivers_from_snapshot(ramp(value))
            assert getattr(drivers, {
                "ev_full_load_hours_y1": "full_load_hours_y1",
                "ev_full_load_hours_y2": "full_load_hours_y2",
                "ev_full_load_hours_stabilized": "full_load_hours_stabilized",
            }[key]) == float(value)


def test_full_ramp_at_hours_ceiling_passes():
    """8760 across the whole ramp is internally consistent → PASS."""
    drivers = drivers_from_snapshot({
        "ev_full_load_hours_y1": "8760",
        "ev_full_load_hours_y2": "8760",
        "ev_full_load_hours_stabilized": "8760",
    })
    assert drivers.full_load_hours_stabilized == 8760.0


def test_charging_price_boundaries():
    _reject("ev_charging_price_eur_kwh", "-0.01")
    _ok("ev_charging_price_eur_kwh", "0", 0.0)
    _ok("ev_charging_price_eur_kwh", "10", 10.0)
    _reject("ev_charging_price_eur_kwh", "10.01")


def test_charging_escalation_boundaries():
    _reject("ev_charging_price_escalation", "-0.01")
    _ok("ev_charging_price_escalation", "0", 0.0)
    _ok("ev_charging_price_escalation", "50", 0.50)
    _reject("ev_charging_price_escalation", "50.01")


def test_electricity_price_boundaries():
    _reject("ev_electricity_price_eur_kwh", "-0.01")
    _ok("ev_electricity_price_eur_kwh", "0", 0.0)
    _ok("ev_electricity_price_eur_kwh", "10", 10.0)
    _reject("ev_electricity_price_eur_kwh", "10.01")


def test_electricity_escalation_boundaries():
    _reject("ev_electricity_price_escalation", "-0.01")
    _ok("ev_electricity_price_escalation", "0", 0.0)
    _ok("ev_electricity_price_escalation", "50", 0.50)
    _reject("ev_electricity_price_escalation", "50.01")


# ── §D: ramp authority unchanged ────────────────────────────────────────────

def test_ramp_violations_fail_closed_not_clamped():
    for ramp in (
        {"ev_full_load_hours_y1": "1200", "ev_full_load_hours_y2": "2500",
         "ev_full_load_hours_stabilized": "2000"},
        {"ev_full_load_hours_y1": "1800", "ev_full_load_hours_y2": "1600",
         "ev_full_load_hours_stabilized": "2000"},
    ):
        with pytest.raises(EVDriverValidationError, match="non-decreasing"):
            drivers_from_snapshot(ramp)


def test_missing_keys_still_default():
    assert drivers_from_snapshot({}) == ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS


# ── §E: registry ↔ runtime drift prevention ────────────────────────────────

def test_registry_runtime_range_parity_below_and_above():
    """For every EV BOUND driver: below-lower fails, lower passes, upper
    passes, above-upper fails — using bounds read from BOTH the registry
    field and the canonical authority (they must agree).  Hours keys are
    probed with a full consistent ramp so the ramp check never masks the
    range check under test."""
    from app.workbook.registry import WORKBOOK
    for key, (low, high) in EV_DRIVER_BOUNDS.items():
        field = WORKBOOK.field(f"revenue.ev_charging.{_SUFFIX[key]}")
        reg_low = float(field.min_value)
        reg_high = float(field.max_value)
        if key in _DISPLAY_SCALE:
            reg_low, reg_high = reg_low / 100.0, reg_high / 100.0
        # no drift between registry and canonical authority
        assert reg_low == pytest.approx(low), key
        assert reg_high == pytest.approx(high), key

        # percent-convention keys are edited in registry (human-%) units but
        # resolve to runtime fractions — probe/expect in the matching units.
        disp_low, disp_high = (low * 100.0, high * 100.0) if key in _DISPLAY_SCALE else (low, high)
        step = abs(disp_low) * 0.01 + 0.01
        below = disp_low - step
        above = disp_high + step

        if key.startswith("ev_full_load_hours"):
            base_ramp = {
                "ev_full_load_hours_y1": {"ev_full_load_hours_y1": None,
                                          "ev_full_load_hours_y2": high,
                                          "ev_full_load_hours_stabilized": high},
                "ev_full_load_hours_y2": {"ev_full_load_hours_y1": 0.0,
                                          "ev_full_load_hours_y2": None,
                                          "ev_full_load_hours_stabilized": high},
                "ev_full_load_hours_stabilized": {"ev_full_load_hours_y1": 0.0,
                                                  "ev_full_load_hours_y2": 0.0,
                                                  "ev_full_load_hours_stabilized": None},
            }[key]
            def _set(value):
                probe = dict(base_ramp)
                probe[key] = value
                drivers = drivers_from_snapshot(probe)
                return getattr(drivers, {
                    "ev_full_load_hours_y1": "full_load_hours_y1",
                    "ev_full_load_hours_y2": "full_load_hours_y2",
                    "ev_full_load_hours_stabilized": "full_load_hours_stabilized",
                }[key])
            def _set_reject(value):
                probe = dict(base_ramp)
                probe[key] = value
                with pytest.raises(EVDriverValidationError):
                    drivers_from_snapshot(probe)
            _set_reject(below)
            assert _set(low) == low
            assert _set(high) == high
            _set_reject(above)
        else:
            def _single(raw_value):
                return _resolve_one(key, repr(raw_value))
            with pytest.raises(EVDriverValidationError):
                _single(below)
            assert _single(disp_low) == low
            assert _single(disp_high) == high
            with pytest.raises(EVDriverValidationError):
                _single(above)


# ── §G: real workbook save path rejects invalid, preserves snapshot ────────

@pytest.fixture()
def ev_wc(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "cord.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    ensure_reference_models()
    return create_reference_seeded_project(
        user_id="cord-user", template_source="generic_ev_charging_reference",
        requested_name="CorD Range", capacity_mw=5.0,
    )


def _client():
    from fastapi.testclient import TestClient
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=False)


def _cookies():
    from app.auth import COOKIE_NAME, create_session_token
    return {COOKIE_NAME: create_session_token(user_id="cord-user", username="admin")}


def _efficiency_form(page_html: str) -> dict[str, str]:
    i = page_html.find('data-field-id="revenue.ev_charging.charging_efficiency"')
    assert i != -1
    block = page_html[i:i + 3000]
    form_html = block[block.rfind("<form", 0, block.find('name="value"')):block.find("</form>", block.find('name="value"'))]
    values = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', form_html))
    values["value"] = re.search(r'name="value"([^>]*)value="([^"]*)"', block).group(2)
    return values


def test_invalid_efficiency_form_edit_rejected_and_snapshot_preserved(ev_wc):
    """Real HTMX POST with an out-of-registry-range value → rejection; the
    persisted snapshot keeps the existing valid value (defense in depth:
    UI layer)."""
    client = _client()
    cookies = _cookies()
    page = client.get(f"/v2/workbook?project={ev_wc.project_code}", cookies=cookies)
    form = _efficiency_form(page.text)
    assert float(form["value"]) == pytest.approx(94.0)

    form["value"] = "150"  # outside registry max 100
    resp = client.post("/v2/workbook/update", data=form, cookies=cookies,
                       headers={"HX-Request": "true"}, follow_redirects=False)
    # HTMX contract: 200 with an error partial (the UI shows the banner);
    # the update service validation result must flag the max violation.
    assert resp.status_code == 200
    assert "must be" in resp.text and "100" in resp.text

    # nothing persisted: a fresh read still shows the valid value
    page2 = client.get(f"/v2/workbook?project={ev_wc.project_code}", cookies=cookies)
    form2 = _efficiency_form(page2.text)
    assert float(form2["value"]) == pytest.approx(94.0)


def test_invalid_snapshot_still_fails_closed_at_runtime(ev_wc):
    """Defense in depth (runtime layer): even if invalid data reaches the
    snapshot through a non-UI path, drivers_from_snapshot fails closed."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.input_adapter import build_projectinputs_from_snapshot
    ws = get_workspace_state("cord-user", ev_wc.project_id)
    snapshot = dict(ws.draft_snapshot)
    snapshot["ev_charging_efficiency"] = "150"  # bypasses the UI form
    with pytest.raises(EVDriverValidationError):
        build_projectinputs_from_snapshot(snapshot)
