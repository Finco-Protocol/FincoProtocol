"""RC-UX A2 (Audit A GAP-R9) — real-Chromium acceptance of the React CAPEX spending-profile studio (Inputs > Studios).

Real server, synthetic users, real committed Runs.  Not collected by pytest: the existing mandatory consolidation role imports the tests
below and supplies ``live_server`` / ``browser`` / ``rcm_react_flag`` / ``an_session``.  No module-level skip lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_rcux_capex_studio_lists_the_canonical_items_and_previews_without_writing",
    "test_rcux_capex_explicit_weights_are_validated_by_the_server_never_normalised",
    "test_rcux_capex_save_is_verified_marks_the_run_stale_and_the_next_run_applies_it",
    "test_rcux_capex_a_stale_token_is_refused_and_the_draft_is_kept",
    "test_rcux_capex_undo_discard_and_remove_are_explicit",
    "test_rcux_capex_studio_fits_every_viewport",
    "test_rcux_capex_reference_models_are_read_only",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-capex-{name}.png"), full_page=True)


def _profiles(context, base, code):
    response = context.request.get(f"{base}/v2/model-react/capex/profiles?project={code}")
    assert response.ok, response.text()[:300]
    return response.json()


def _open(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#inputs")
    page.reload()                                                       # a same-URL goto is a hash navigation; reload re-reads every projection
    page.locator("[data-studio-tab='capex-profile']").click()           # studios stay closed until chosen (compact Inputs)
    page.wait_for_selector("[data-capex-studio='ready']", timeout=60000)


def test_rcux_capex_studio_lists_the_canonical_items_and_previews_without_writing(live_server, an_session):
    context, page, record, errors = an_session("rcux-capex-list")
    requests = []
    page.on("request", lambda r: requests.append((r.method, r.url)) if "/v2/" in r.url and "/static/" not in r.url else None)
    _open(page, live_server, record.project_code)
    api = _profiles(context, live_server, record.project_code)
    shown = [page.locator("[data-capex-item]").nth(i).get_attribute("data-capex-item") for i in range(page.locator("[data-capex-item]").count())]
    assert shown == [i["item_key"] for i in api["items"]] and shown
    assert page.locator("[data-capex-binding]").get_attribute("data-capex-binding") == "none"
    assert page.locator("[data-capex-preview]").is_disabled() and page.locator("[data-capex-save]").is_disabled()
    first = shown[0]
    page.select_option(f"[data-capex-shape='{first}']", "FRONT_LOADED")
    assert "1 item changed" in page.locator("[data-capex-save]").inner_text()
    page.locator("[data-capex-preview]").click()
    page.wait_for_selector("[data-capex-plan='current']", timeout=30000)
    assert page.locator("[data-capex-month]").count() == api["months"]
    assert page.locator("[data-capex-reconciles]").get_attribute("data-capex-reconciles") == "true"
    assert page.locator("[data-capex-unallocated]").inner_text() == "0.000"
    assert page.locator("[data-canonical='false']").count() == 1 and "PREVIEW ONLY" in page.locator("[data-capex-plan]").inner_text()
    server = context.request.get(f"{live_server}/v2/model-react/capex/preview", headers={"X-Finco-React-Request": "1"},
                                 params={"project": record.project_code, "spec": f'[["{first}","FRONT_LOADED","",""]]'}).json()["plan"]
    assert [page.locator(f"[data-capex-month='{m['month']}'] td").last.inner_text() for m in server["months"]] == [m["remaining"] for m in server["months"]]
    assert "not estimated" in page.locator("[data-capex-studio]").inner_text()                # IDC / S&U are not estimated pre-Run
    assert _profiles(context, live_server, record.project_code)["saved"]["rows"] == {}        # nothing saved
    page.select_option(f"[data-capex-shape='{first}']", "UNIFORM")
    assert page.locator("[data-capex-outdated]").count() == 1                                  # a changed draft marks the preview outdated
    _shot(page, "preview-1440")
    assert {m for m, _ in requests} <= {"GET"}, [r for r in requests if r[0] != "GET"]
    assert errors == []


def test_rcux_capex_explicit_weights_are_validated_by_the_server_never_normalised(live_server, an_session):
    context, page, record, errors = an_session("rcux-capex-explicit")
    _open(page, live_server, record.project_code)
    months = _profiles(context, live_server, record.project_code)["months"]
    key = page.locator("[data-capex-item]").first.get_attribute("data-capex-item")
    page.select_option(f"[data-capex-shape='{key}']", "EXPLICIT")
    box = page.locator(f"[data-capex-explicit='{key}']")
    box.fill("\n".join(["1"] * months))                                                       # an Excel column that sums to `months` %, not 100 %
    assert f"{months} of {months} entered" in page.locator(f"[data-capex-item='{key}']").inner_text()
    page.locator("[data-capex-preview]").click()
    page.wait_for_selector(f"[data-capex-row='{key}']", timeout=30000)
    assert page.locator(f"[data-capex-row='{key}']").get_attribute("data-status") == "invalid"
    assert "CAPEX_PROFILE_WEIGHT_SUM_INVALID" in page.locator(f"[data-capex-row='{key}']").inner_text()
    assert page.locator("[data-capex-reconciles]").get_attribute("data-capex-reconciles") == "false"
    assert page.locator("[data-capex-month]").count() == 0 or page.locator("[data-capex-months] th").count() >= 6
    page.locator(f"[data-capex-explicit='{key}']").fill("\t".join(["0"] * (months - 1) + ["100"]))     # a pasted Excel row
    page.locator("[data-capex-preview]").click()
    page.wait_for_function(f"() => document.querySelector(\"[data-capex-row='{key}']\")?.getAttribute('data-status') === 'valid'", timeout=30000)
    assert page.locator("[data-capex-reconciles]").get_attribute("data-capex-reconciles") == "true"
    assert errors == []


def test_rcux_capex_save_is_verified_marks_the_run_stale_and_the_next_run_applies_it(live_server, an_session):
    context, page, record, errors = an_session("rcux-capex-save")
    run_canonical(context, live_server, record.project_code)
    before = _profiles(context, live_server, record.project_code)
    base_idc = before["last_run"]["sources_uses"]["capitalized_idc_keur"]["value"]
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    _open(page, live_server, record.project_code)
    assert page.locator("[data-capex-lr-freshness]").get_attribute("data-capex-lr-freshness") == "CURRENT"
    page.select_option("[data-capex-bulk-shape='true']", "FRONT_LOADED")
    page.locator("[data-capex-bulk-apply='true']").click()
    page.locator("[data-capex-save='true']").click()
    page.wait_for_selector("[data-capex-status='ok']", timeout=60000)
    assert "STALE" in page.locator("[data-capex-status='ok']").inner_text() and "model was not run" in page.locator("[data-capex-status='ok']").inner_text()
    after = _profiles(context, live_server, record.project_code)
    assert after["saved"]["binding"]["bound"] is True and len(after["saved"]["rows"]) == len(before["items"])
    assert page.locator("[data-capex-binding]").get_attribute("data-capex-binding") == "bound"
    assert page.locator("[data-capex-lr-freshness]").get_attribute("data-capex-lr-freshness") == "STALE"
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history     # Save never runs
    run_canonical(context, live_server, record.project_code)
    final = _profiles(context, live_server, record.project_code)
    assert final["last_run"]["freshness"] == "CURRENT" and final["last_run"]["used_profile"] is True
    assert final["last_run"]["sources_uses"]["capitalized_idc_keur"]["value"] != base_idc                      # timing moved IDC (committed evidence)
    _open(page, live_server, record.project_code)
    assert page.locator("[data-capex-lr='capitalized_idc_keur']").inner_text() == final["last_run"]["sources_uses"]["capitalized_idc_keur"]["display"]
    _shot(page, "saved-1440")
    assert errors == []


def test_rcux_capex_a_stale_token_is_refused_and_the_draft_is_kept(live_server, an_session):
    context, page, record, errors = an_session("rcux-capex-stale")
    _open(page, live_server, record.project_code)
    key = page.locator("[data-capex-item]").first.get_attribute("data-capex-item")
    page.select_option(f"[data-capex-shape='{key}']", "BACK_LOADED")
    other = _profiles(context, live_server, record.project_code)                                # a second "tab" saves first
    fields = {"project": record.project_code, "csrf_token": other["save"]["csrf_token"], "content_hash": other["save"]["content_hash"], "action": "save",
              "key_0": key, "shape_0": "MILESTONE", "explicit_0": "", "milestone_0": "1"}
    assert context.request.post(f"{live_server}/v2/capex/spending-profiles/save", form=fields).ok
    page.locator("[data-capex-save='true']").click()
    page.wait_for_selector("[data-capex-status='error']", timeout=30000)
    assert "Nothing was changed" in page.locator("[data-capex-status='error']").inner_text()
    assert page.locator(f"[data-capex-shape='{key}']").input_value() == "BACK_LOADED"           # the draft survives the refusal
    saved = _profiles(context, live_server, record.project_code)["saved"]["rows"]
    assert saved[key]["shape"] == "MILESTONE"                                                  # the other tab's profile is intact
    assert errors == [e for e in errors if "status of 409" in e]


def test_rcux_capex_undo_discard_and_remove_are_explicit(live_server, an_session):
    context, page, record, errors = an_session("rcux-capex-undo")
    _open(page, live_server, record.project_code)
    key = page.locator("[data-capex-item]").first.get_attribute("data-capex-item")
    page.select_option(f"[data-capex-shape='{key}']", "UNIFORM")
    page.select_option(f"[data-capex-shape='{key}']", "BACK_LOADED")
    page.locator("[data-capex-undo='true']").click()
    assert page.locator(f"[data-capex-shape='{key}']").input_value() == "UNIFORM"
    page.locator("[data-capex-discard='true']").click()
    assert page.locator(f"[data-capex-shape='{key}']").input_value() == "" and page.locator("[data-capex-save='true']").is_disabled()
    page.select_option(f"[data-capex-shape='{key}']", "UNIFORM")
    page.locator("[data-capex-save='true']").click()
    page.wait_for_selector("[data-capex-status='ok']", timeout=60000)
    page.locator("[data-capex-remove='true']").click()
    page.wait_for_selector("[data-wf-dialog='true']")
    page.keyboard.press("Escape")
    assert _profiles(context, live_server, record.project_code)["saved"]["binding"]["saved"] is True       # cancelling removes nothing
    page.locator("[data-capex-remove='true']").click()
    page.locator("[data-wf-dialog='true'] button", has_text="Remove profile").click()
    page.wait_for_function("() => document.querySelector('[data-capex-binding]')?.getAttribute('data-capex-binding') === 'none'", timeout=60000)
    assert _profiles(context, live_server, record.project_code)["saved"]["rows"] == {}
    assert errors == []


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_capex_studio_fits_every_viewport(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcux-capex-resp-{width}", width=width, height=900)
    _open(page, live_server, record.project_code)
    key = page.locator("[data-capex-item]").first.get_attribute("data-capex-item")
    page.select_option(f"[data-capex-shape='{key}']", "FRONT_LOADED")
    page.locator("[data-capex-preview]").click()
    page.wait_for_selector("[data-capex-months]", timeout=30000)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"
    box = page.locator("[data-capex-months]").locator("xpath=ancestor::div[contains(@class,'rcm-scroll')][1]").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1
    _shot(page, f"studio-{width}")
    assert errors == []


def test_rcux_capex_reference_models_are_read_only(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcux-capex-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    page.goto(f"{live_server}/v2/model-react/{ref.project_code}#inputs")
    page.locator("[data-studio-tab='capex-profile']").click()
    page.wait_for_selector("[data-capex-unavailable='true']", timeout=60000)
    assert page.locator("[data-capex-studio]").count() == 0
    assert context.request.get(f"{live_server}/v2/model-react/capex/profiles?project={ref.project_code}").status in (200, 409)
