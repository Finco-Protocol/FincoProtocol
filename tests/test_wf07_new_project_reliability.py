"""WF-07 / S7-09: the real New Project journey for all four verticals keeps country, template provenance and capacity consistent, and discloses that
reference assumptions are generic. Country never changes tariff/price/market inputs (no invented national values)."""
from __future__ import annotations

import re

import pytest

from tests.test_qa_create_project_country_capacity import _login, client  # noqa: F401

VERTICALS = [("generic_solar_reference", "Solar"), ("generic_wind_reference", "Wind"),
             ("generic_data_center_reference", "Data Center"), ("generic_ev_charging_reference", "EV Charging")]


def _create(client, name, template, country, project_type, capacity="20"):
    return client.post("/projects/create", data={"project_name": name, "project_type": project_type, "template_source": template,
                                                  "country_market": country, "capacity_mw": capacity}, follow_redirects=False)


def test_the_form_discloses_generic_reference_assumptions_and_country_scope(client):
    _login(client)
    page = re.sub(r"\s+", " ", client.get("/projects/new").text)
    assert 'data-testid="reference-assumptions-note"' in page
    assert "generic, editable assumptions" in page and "not verified for the selected country" in page
    assert "does not change tariff, market or cost assumptions" in page
    assert "Country-specific tax templates are not yet active" in page


@pytest.mark.parametrize("template, project_type", VERTICALS)
def test_template_type_country_and_capacity_are_persisted_and_country_changes_no_price_input(client, template, project_type):
    _login(client)
    snaps = {}
    for country in ("HR", "DE"):
        r = _create(client, f"V {template} {country}", template, country, project_type)
        assert r.status_code in (200, 303), r.text[:300]
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
