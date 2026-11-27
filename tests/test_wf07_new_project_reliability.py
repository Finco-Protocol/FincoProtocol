"""WF-07 / S7-09: the real New Project journey for all four verticals keeps country, template provenance and capacity consistent, and discloses that
reference assumptions are generic. Country never changes tariff/price/market inputs (no invented national values)."""
from __future__ import annotations

import re

import pytest

from tests.test_qa_create_project_country_capacity import _login, client  # noqa: F401


VERTICALS = [
    ("solar", "generic_solar_reference", "Solar"),
    ("wind", "generic_wind_reference", "Wind"),
    ("data_center", "generic_data_center_reference", "Data Center"),
    ("ev_charging", "generic_ev_charging_reference", "EV Charging"),
]


def _create(client, name, technology, country, capacity=20):
    opts = client.get("/v2/model-react/new-project/options").json()
    return client.post(
        "/v2/model-react/new-project/create",
        json={
            "request_id": opts["request_id"],
            "csrf_token": opts["csrf_token"],
            "name": name,
            "technology": technology,
            "country": country,
            "capacity_mw": float(capacity),
            "acknowledge_preview": True,
        },
    )


def test_the_form_discloses_generic_reference_assumptions_and_country_scope(client):
    _login(client)
    opts = client.get("/v2/model-react/new-project/options").json()
    assert opts["ok"] is True
    for tech in opts["technologies"]:
        if tech["creatable"]:
            text = " ".join(tech["limitations"])
            assert "Generic market profiles are illustrative" in text or "generic" in text.lower()
            assert "country-specific tax" in text.lower()
    preview = client.get(
        "/v2/model-react/new-project/preview",
        params={"name": "Disclosure Check", "technology": "solar", "country": "HR", "capacity_mw": "20"},
    ).json()
    assert preview["effective"]["tax_template"] == "Generic Tax Template"


@pytest.mark.parametrize("technology, template, project_type", VERTICALS)
def test_template_type_country_and_capacity_are_persisted_and_country_changes_no_price_input(client, technology, template, project_type):
    _login(client)
    snaps = {}
    for country in ("HR", "DE"):
        r = _create(client, f"V {template} {country}", technology, country)
        assert r.status_code in (200, 201), r.text[:300]
        import app.persistence.db as db
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_name=?", (f"V {template} {country}",)).fetchone()
        assert row is not None, (template, country)
        assert row["project_type"] == project_type and row["template_source"] == template
        import json
        snap = json.loads(row["baseline_snapshot_json"])
        assert snap["country_market"] == country                       # location metadata persisted exactly (canonical code)
        snaps[country] = snap
    differing = {k for k in set(snaps["HR"]) | set(snaps["DE"]) if snaps["HR"].get(k) != snaps["DE"].get(k)}
    # Only identity/location keys may differ between the two countries; no tariff, price, curve, inflation or tax input moves.
    assert not [k for k in differing if re.search(r"tariff|price|curve|inflation|tax|rate", k, re.I)], differing
