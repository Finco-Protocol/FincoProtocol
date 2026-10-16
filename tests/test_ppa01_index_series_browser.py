"""PPA-01 browser acceptance (real Chromium, real CSP): explicit CPI/PPI index series in the guided PPA workflow.

Entry -> validation -> Save -> reload -> stale-tab refusal with the draft kept -> Run -> STALE -> re-Run. Solar and Wind. The UI shows a read-only
effective-price preview only; the canonical Run owns every revenue figure. Set PPA01_SCREENSHOT_DIR to keep screenshots.
"""
from __future__ import annotations

import json
import os
import re

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: F401,E402

SAVED = re.compile(r"^Saved Working Copy")
SHOTS = os.environ.get("PPA01_SCREENSHOT_DIR")
TEMPLATES = ["generic_solar_reference", "generic_wind_reference"]


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"))


def _open(s):
    s.page.on("dialog", lambda d: d.accept())
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    s.page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    return json.loads(s.page.locator("[data-testid=ppa-quick-add]").get_attribute("data-operating-years"))


def _add_series_ppa(s, years, levels_text=None, *, price="60", share="60", ref="CPI-PPA"):
    s.fill(kind="indexed_ppa", price=price, share=share, ref=ref)
    s.page.locator('[data-quick="index_mode"]').select_option("series")
    s.use_full_window()
    if levels_text is not None:
        s.page.locator('[data-quick="index_levels"]').fill(levels_text)
    s.add()


def _levels(years, start=100.0, step=2.5):
    return [round(start + step * i, 4) for i in range(len(years))]


def _text(value):
    """How the browser renders a typed number (105.0 -> '105')."""
    return str(int(value)) if float(value) == int(value) else str(value)


def _save(s):
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()


def _persisted_series(s):
    return s.saved_book()["streams"][0].get("index_series")


@pytest.mark.parametrize("template", TEMPLATES)
def test_pasted_series_is_added_previewed_saved_and_restored_after_reload(live_server, browser, template):
    s = Session(live_server, browser, f"ppa01-b-{template[8:12]}", template=template)
    years = _open(s)
    levels = _levels(years)
    s.fill(kind="indexed_ppa")
    assert s.page.locator("[data-quick-index]").is_hidden() is False                    # the annual rate input is the default
    s.page.locator('[data-quick="index_mode"]').select_option("series")
    assert s.page.locator("[data-quick-index]").is_hidden() and s.page.locator("[data-quick-index-series]").is_visible()
    _add_series_ppa(s, years, "\n".join(str(v) for v in levels))
    assert s.page.locator("[data-quick-error]").is_hidden(), s.page.locator("[data-quick-error]").inner_text()
    rows = s.page.locator("[data-index-point]")
    assert rows.count() == len(years)
    assert rows.first.locator("th").inner_text().endswith("(base)")
    assert rows.nth(2).locator("[data-index-level]").input_value() == _text(levels[2])
    # read-only effective price preview = price x level / base level (display only)
    assert rows.nth(2).locator("[data-index-effective]").inner_text() == f"{60 * levels[2] / levels[0]:.4f}"
    assert rows.first.locator("[data-index-basis]").input_value() == "FORECAST"
    _shot(s.page, f"ppa01-editor-desktop-{template[8:12]}")
    _save(s)
    saved = _persisted_series(s)
    assert [(p["operating_year"], p["level"]) for p in saved] == [(y["year"], lv) for y, lv in zip(years, levels)]
    stream = s.saved_book()["streams"][0]
    assert stream["indexation_rate"] == 0 and stream["price_eur_mwh"] == 60.0 and s.saved_book()["version"] == 2
    s.page.reload()
    s.page.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")
    _open(s)
    s.page.locator(".rc-index-editor summary").first.click()
    assert s.page.locator("[data-index-point]").count() == len(years)
    assert s.page.locator("[data-index-point]").nth(4).locator("[data-index-level]").input_value() == _text(levels[4])
    assert s.errors == [], s.errors
    s.close()


def test_incomplete_or_invalid_levels_block_save_and_keep_every_typed_value(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-invalid")
    years = _open(s)
    _add_series_ppa(s, years)                                              # no pasted levels: the rows start empty, nothing is invented
    assert s.page.locator("[data-index-point]").count() == len(years)
    assert all(v == "" for v in s.page.locator("[data-index-level]").evaluate_all("els => els.map(e => e.value)"))
    save = s.page.locator("[data-revenue-save]")
    assert save.is_disabled()
    assert "index level above zero for operating year" in s.page.locator("[data-revenue-feedback]").inner_text()
    first, second = s.page.locator("[data-index-level]").nth(0), s.page.locator("[data-index-level]").nth(1)
    first.fill("100")
    second.fill("1,5")                                                        # comma decimal: never silently reinterpreted
    assert second.get_attribute("aria-invalid") == "true" and save.is_disabled()
    second.fill("0")
    assert save.is_disabled() and "above zero" in s.page.locator("[data-revenue-feedback]").inner_text()
    for i, v in enumerate(_levels(years)):
        s.page.locator("[data-index-level]").nth(i).fill(str(v))
    assert save.is_enabled()
    s.page.locator("[data-index-level]").nth(3).fill("")                      # clearing one level re-blocks Save; the rest stay
    assert save.is_disabled() and s.page.locator("[data-index-level]").nth(5).input_value() == _text(_levels(years)[5])
    assert s.saved_book() is None                                             # nothing persisted behind the user's back
    s.close()


def test_a_bad_paste_is_rejected_atomically_and_year_rows_follow_continuity_rules(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-paste")
    years = _open(s)
    _add_series_ppa(s, years, "\n".join(str(v) for v in _levels(years)))
    before = s.page.locator("[data-index-level]").evaluate_all("els => els.map(e => e.value)")
    editor = s.page.locator(".rc-index-editor")
    paste = editor.locator("textarea")
    for bad, message in [("100\n102\nabc", "not an index level"), (f"{years[0]['year']}\t100\n{years[0]['year'] + 2}\t101", "consecutive"),
                         ("100\n-3", "above zero"), ("100\t101\t102\t103", "use one level per line")]:
        paste.fill(bad)
        editor.get_by_role("button", name="Replace levels with pasted values").click()
        assert message in s.page.locator("[data-revenue-error]").inner_text()
        assert s.page.locator("[data-index-level]").evaluate_all("els => els.map(e => e.value)") == before     # nothing half-applied
    last = s.page.locator("[data-index-point]").last
    assert last.get_by_role("button", name=re.compile("Remove operating year")).is_visible()                    # only the last year can go
    assert s.page.locator("[data-index-point]").first.get_by_role("button").count() == 0
    last.get_by_role("button", name=re.compile("Remove operating year")).click()
    assert s.page.locator("[data-index-point]").count() == len(years) - 1
    assert "no index level for operating year" in s.page.locator("[data-revenue-feedback]").inner_text()        # now short of the priced years
    editor.get_by_role("button", name="+ Operating year").click()
    assert s.page.locator("[data-index-point]").count() == len(years)
    s.close()


def test_observed_and_forecast_are_distinguishable_and_persisted(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-basis")
    years = _open(s)
    _add_series_ppa(s, years, "\n".join(str(v) for v in _levels(years)))
    for i in range(2):
        s.page.locator("[data-index-basis]").nth(i).select_option("OBSERVED")
    _save(s)
    bases = [p["basis"] for p in _persisted_series(s)]
    assert bases[:2] == ["OBSERVED", "OBSERVED"] and set(bases[2:]) == {"FORECAST"}
    s.close()


def test_switching_back_to_an_annual_rate_removes_the_series_after_confirmation(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-mode")
    years = _open(s)
    _add_series_ppa(s, years, "\n".join(str(v) for v in _levels(years)))
    _save(s)
    s.page.locator(".rc-index-editor summary").first.click()
    s.page.locator(".rc-index-editor").get_by_label("Fixed annual escalation (%)").click()
    assert s.page.locator("[data-index-point]").count() == 0
    s.page.locator("[data-revenue-save]").click()                                      # no basis left: an indexed PPA needs a positive rate
    assert "positive annual indexation rate" in s.page.locator("[data-revenue-error]").inner_text()
    s.page.locator('[data-field="indexation_rate"]').first.fill("2")
    _save(s)
    stream = s.saved_book()["streams"][0]
    assert stream["indexation_rate"] == 0.02 and "index_series" not in stream           # one economic basis at a time
    s.close()


def test_two_tabs_a_stale_series_save_keeps_the_typed_levels_and_never_overwrites(live_server, browser):
    from tests.test_sc34_draft_preservation_browser import _second_view
    s = Session(live_server, browser, "ppa01-b-stale")
    years = _open(s)
    ctx_b, b, errors_b = _second_view(browser, live_server, "ppa01-b-stale", s.rec, "revenue")
    b.on("dialog", lambda d: d.accept())
    b.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")
    _add_series_ppa(s, years, "\n".join(str(v) for v in _levels(years)))
    _save(s)
    committed = s.saved_book()
    b.evaluate("document.getElementById('tab-revenue').click()")
    b.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    b.locator('[data-testid=ppa-quick-add] [data-quick="kind"]').select_option("indexed_ppa")
    b.locator('[data-quick="index_mode"]').select_option("series")
    b.locator('[data-testid=ppa-quick-add] [data-quick="price"]').fill("70")
    b.locator('[data-testid=ppa-quick-add] [data-quick="share"]').fill("20")
    b.locator('[data-testid=ppa-quick-add] [data-quick="ref"]').fill("CPI-B")
    b.locator('[data-testid=ppa-quick-add] [data-dd="manual"]').check()
    b.locator('[data-testid=ppa-quick-add] [data-dd="end"]').fill(b.locator("[data-testid=ppa-quick-add]").get_attribute("data-window-end"))
    b.locator('[data-quick="index_levels"]').fill("\n".join(str(v) for v in _levels(years, 90.0, 1.0)))
    b.locator("[data-quick-add]").click()
    with b.expect_response(lambda r: r.url.endswith("/v2/workbook/revenue/contracts")) as rb:
        b.locator("[data-revenue-save]").click()
    assert rb.value.status == 409
    error = b.locator("[data-revenue-error]")
    error.locator("[data-conflict-reload]").wait_for()
    assert b.locator("[data-revenue-editor]").get_attribute("data-dirty") == "true"
    b.locator(".rc-index-editor summary").first.click()
    assert b.locator("[data-index-level]").first.input_value() == "90"                  # B's typed levels survived the refusal
    assert not SAVED.search(b.locator("[data-revenue-feedback]").inner_text())
    assert s.saved_book() == committed
    assert errors_b == [], errors_b
    s.close(); ctx_b.close()


def test_phone_viewport_keeps_the_page_still_and_the_table_scrolls_inside(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-mobile", viewport={"width": 390, "height": 844})
    years = _open(s)
    _add_series_ppa(s, years, "\n".join(str(v) for v in _levels(years)))
    s.page.locator(".rc-index-editor").scroll_into_view_if_needed()
    assert s.page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    _shot(s.page, "ppa01-editor-mobile")
    s.close()


def test_keyboard_only_entry_moves_level_then_basis_then_next_year(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-keys")
    years = _open(s)
    _add_series_ppa(s, years)
    page = s.page
    page.locator("[data-index-level]").first.focus()
    page.keyboard.type("100")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.hasAttribute('data-index-basis')")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.hasAttribute('data-index-level') && document.activeElement.closest('tr').dataset.indexPoint") == str(years[1]["year"])
    s.close()


def test_run_after_save_then_edit_makes_results_stale_and_rerun_is_current(live_server, browser):
    s = Session(live_server, browser, "ppa01-b-run")
    years = _open(s)
    _add_series_ppa(s, years, "\n".join(str(v) for v in _levels(years)))
    _save(s)
    page = s.page
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/run") and r.request.method == "POST", timeout=240000):
        page.locator('[data-testid="header-run-btn"]').click()
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    from app.persistence.run_history_repository import get_run_history
    assert len(get_run_history("ppa01-b-run", s.rec.project_id)) == 1
    page.evaluate("document.getElementById('tab-revenue').click()")
    page.locator(".rc-index-editor summary").first.click()
    page.locator("[data-index-level]").nth(3).fill("120")
    _save(s)
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="STALE").wait_for(timeout=30000)
    assert len(get_run_history("ppa01-b-run", s.rec.project_id)) == 1               # history untouched by the edit
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/run") and r.request.method == "POST", timeout=240000):
        page.locator('[data-testid="header-run-btn"]').click()
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    assert len(get_run_history("ppa01-b-run", s.rec.project_id)) == 2
    assert s.errors == [], s.errors
    s.close()
