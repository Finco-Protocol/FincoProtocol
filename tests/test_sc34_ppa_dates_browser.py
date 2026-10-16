"""SAFE CORE V3.4 / Workstream B (SC-05): the guided PPA date helper only offers dates the canonical validator accepts (real Chromium, real CSP).

Solar and Wind. The helper never rounds the contract term for the user: an unacceptable date is refused with both neighbouring accepted dates, what
each one means (term and operating periods covered; the end is EXCLUSIVE), and an explicit button. Scheduled curves keep one explicit price per
covered operating period.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: F401,E402

SAVED = re.compile(r"^Saved Working Copy")
TEMPLATES = ["generic_solar_reference", "generic_wind_reference"]


def _open(s):
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    s.page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    return json.loads(s.page.locator("[data-testid=ppa-quick-add]").get_attribute("data-boundaries"))


def _save(s):
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()


def _day_before(iso):
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


@pytest.mark.parametrize("template", TEMPLATES)
def test_an_off_boundary_end_offers_both_accepted_neighbours_and_never_rounds_silently(live_server, browser, template):
    s = Session(live_server, browser, f"sc34-dates-{template[8:12]}", template=template)
    boundaries = _open(s)
    start, later, earlier = boundaries[0], boundaries[10], boundaries[9]
    bad_end = _day_before(later)
    assert bad_end not in boundaries
    s.fill(price="60", share="50", ref="REF-DATES")
    s.set_dates(end=bad_end)
    s.add()
    error = s.page.locator("[data-quick-error]")
    text = error.inner_text()
    assert "operating-period boundary" in text and "exclusive" in text and "never rounded" in text
    offered = {error.locator("[data-quick-suggest]").get_attribute("data-quick-suggest"),
               error.locator("[data-quick-suggest-alt]").get_attribute("data-quick-suggest-alt")}
    assert offered == {earlier, later}                                              # both sides are offered, with what each means
    assert "operating period" in error.locator("[data-quick-suggest]").inner_text()
    assert s.page.locator("[data-revenue-rows] tr").count() == 0                    # nothing added, nothing snapped
    assert s.dd("end").input_value() == bad_end                                     # the entered date is untouched
    error.locator(f'[data-quick-suggest-alt="{earlier}"], [data-quick-suggest="{earlier}"]').click()
    assert s.dd("end").input_value() == earlier and s.dd("manual").is_checked()      # manual override stays available and explicit
    s.add()
    assert s.page.locator("[data-quick-error]").is_hidden()
    _save(s)
    stream = s.saved_book()["streams"][0]
    assert (stream["start_date"], stream["end_date"]) == (start, earlier)
    assert s.errors == [], s.errors
    s.close()


@pytest.mark.parametrize("template", TEMPLATES)
def test_an_end_after_the_model_operating_period_is_explained_not_saved(live_server, browser, template):
    s = Session(live_server, browser, f"sc34-dates-after-{template[8:12]}", template=template)
    boundaries = _open(s)
    window_end = s.window_end()
    assert window_end == boundaries[-1]
    s.fill(price="60", share="50", ref="REF-LATE")
    s.set_dates(end=(date.fromisoformat(window_end) + timedelta(days=366)).isoformat())
    s.add()
    text = s.page.locator("[data-quick-error]").inner_text()
    assert "after the model operating period ends" in text and window_end in text
    assert s.page.locator("[data-revenue-rows] tr").count() == 0
    assert s.saved_book() is None                                                    # nothing persisted
    s.close()


@pytest.mark.parametrize("template", TEMPLATES)
def test_fixed_indexed_and_scheduled_ppas_over_a_partial_term_save_with_explicit_coverage(live_server, browser, template):
    s = Session(live_server, browser, f"sc34-dates-kinds-{template[8:12]}", template=template)
    boundaries = _open(s)
    starts = json.loads(s.page.locator("[data-testid=ppa-quick-add]").get_attribute("data-period-starts"))
    a, b = boundaries[2], boundaries[8]                                              # a partial term inside the operating period
    for kind, ref in (("fixed_ppa", "REF-F"), ("indexed_ppa", "REF-I"), ("scheduled_ppa", "REF-S")):
        s.fill(kind=kind, price="55", share="30", ref=ref, **({"index": "2"} if kind == "indexed_ppa" else {}))
        s.set_dates(start=a, end=b)
        s.add()
        assert s.page.locator("[data-quick-error]").is_hidden(), (kind, s.page.locator("[data-quick-error]").inner_text())
    _save(s)
    streams = s.saved_book()["streams"]
    assert [(r["start_date"], r["end_date"]) for r in streams] == [(a, b)] * 3
    scheduled = streams[2]
    covered = [d for d in starts if a <= d < b]
    assert [p["period_start"] for p in scheduled["price_curve"]] == covered         # one explicit price per covered period, none invented
    assert streams[0]["price_eur_mwh"] == 55 and streams[1]["indexation_rate"] == 0.02
    s.page.reload()
    s.page.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")
    _open(s)
    assert s.page.locator('[data-field="start_date"]').first.input_value() == a        # the saved dates are what reopens
    assert s.errors == [], s.errors
    s.close()
