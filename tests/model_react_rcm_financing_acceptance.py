"""RC-M Lane C — real-Chromium acceptance of the React Financing Studio.

Real server, synthetic users.  The decisive check is serializer parity: the React typed editor and the Legacy bankability form,
driven with the same values, send byte-identical configuration documents to the canonical writer.  Screenshots go to
``$RCM_SCREENSHOT_DIR`` as ``rcm-financing-*.png``.


Not collected by pytest: ``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory Chromium role) imports the
tests and fixtures below and supplies ``live_server`` / ``browser`` / ``rcm_react_flag``.  No module-level skip lives here.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_financing_workspace_has_the_six_sections_with_authority_and_closed_structures_stated",
    "test_react_and_legacy_editors_send_byte_identical_configuration_documents",
    "test_bankability_save_reads_back_and_makes_the_last_run_stale_without_running",
    "test_obviously_invalid_input_is_stopped_before_any_request_and_the_server_still_validates",
    "test_a_changed_working_copy_is_refused_and_nothing_is_overwritten",
    "test_a_lost_save_response_is_unknown_never_retried_and_applied_once",
    "test_reference_models_show_the_bankability_view_read_only",
    "test_period_grid_supports_arrow_navigation_and_tsv_paste_as_drafts",
    "test_senior_facilities_and_sources_uses_show_the_canonical_evidence",
    "test_every_financing_tab_fits_the_viewport",
    "fin_session",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")      # CI: the role's uploaded screenshot folder
FIELD = "debt.bankability.configuration"


@pytest.fixture
def fin_session(live_server, browser, rcm_react_flag):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    contexts = []

    def open_session(uid, kind="solar", width=1440, height=1000):
        record = create_reference_seeded_project(user_id=uid, template_source=f"generic_{kind}_reference", requested_name=f"RCM fin {kind}", capacity_mw=20.0)
        context = browser.new_context(viewport={"width": width, "height": height})
        contexts.append(context)
        context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error"
                and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        return context, page, record, errors

    yield open_session
    for context in contexts:
        context.close()


def shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcm-financing-{name}.png"), full_page=True)


def open_tab(page, base, code, tab):
    page.goto(f"{base}/v2/model-react/{code}#financing")
    page.wait_for_selector("[data-financing-studio='true']", timeout=30000)
    page.locator(f"[data-financing-tab-button='{tab}']").click()
    page.wait_for_selector({"overview": "[data-financing-overview='true']", "terms": "[data-sheet-editor], .rx-card", "bankability": "[data-bankability-editor='true'], [data-bankability-state]",
                            "facilities": "[data-capital-stack='true']", "sources-uses": "[data-sources-uses='true']"}[tab], timeout=30000)


def studio(context, base, code):
    return context.request.get(f"{base}/v2/model-react/financing/studio", params={"project": code}).json()


def draft_of(record):
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(record.user_id, record.project_id)
    return dict(ws.draft_snapshot), ws.last_runtime_snapshot_id


def no_page_overflow(page):
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"


def unexpected(errors, allow=(), net=()):
    """Console errors other than deliberately provoked ones: HTTP status lines, or an aborted request we injected."""
    return [e for e in errors if not any(f"status of {code}" in e for code in allow) and not any(n in e for n in net)]


# the values both editors are driven with
def plan(n):
    return {"targets": [f"{1.20 + (i % 5) * 0.05:.2f}" for i in range(n)], "rates": [f"{5.0 + (i % 4) * 0.25:.2f}" for i in range(n)],
            "fees": {"commitment_pct": "1.10", "structuring_pct": "0.90", "arrangement_pct": "0.20"}, "requirement": "120"}


def drive_react(page, n):
    p = plan(n)
    page.select_option("[data-bank='sizing_mode']", "flat_dscr_sculpted")
    page.select_option("[data-bank='lender_case']", "P_50")
    page.select_option("[data-bank='day_count']", "act_365")
    page.select_option("[data-bank='rates_mode']", "periods")
    page.select_option("[data-bank='targets_mode']", "periods")
    for i in range(n):
        page.fill(f"[data-grid-cell='target-{i}']", p["targets"][i])
        page.fill(f"[data-grid-cell='rate-{i}']", p["rates"][i])
    page.locator("[data-bank='fees_enabled']").check()
    for key, value in p["fees"].items():
        page.fill(f"[data-bank-fee='{key}']", value)
    page.select_option("[data-bank='reserve_mode']", "cash_fixed")
    page.fill("[data-bank='requirement_keur']", p["requirement"])


LEGACY_DRIVE = """(p) => {
  const form = document.querySelector('[data-f2-form]');
  const set = (el, value) => { el.value = value; el.dispatchEvent(new Event('change', {bubbles: true})); };
  const f = (name) => form.querySelector(`[data-f2="${name}"]`);
  set(f('sizing_mode'), 'flat_dscr_sculpted'); set(f('lender_case'), 'P_50'); set(f('day_count'), 'act_365');
  set(f('rates_mode'), 'periods'); set(f('targets_mode'), 'periods');
  form.querySelectorAll('[data-f2-target]').forEach((x, i) => set(x, p.targets[i]));
  form.querySelectorAll('[data-f2-rate]').forEach((x, i) => set(x, p.rates[i]));
  f('fees_enabled').checked = true; f('fees_enabled').dispatchEvent(new Event('change', {bubbles: true}));
  for (const [key, value] of Object.entries(p.fees)) set(form.querySelector(`[data-f2-fee="${key}"]`), value);
  set(f('reserve_mode'), 'cash_fixed'); set(f('requirement_keur'), p.requirement);
  form.requestSubmit(form.querySelector('[data-f2-save]'));
}"""


def captured_value(body: str) -> str:
    return parse_qs(body, keep_blank_values=True)["value"][0]


# ── structure ──────────────────────────────────────────────────────────────

def test_financing_workspace_has_the_six_sections_with_authority_and_closed_structures_stated(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-struct")
    open_tab(page, live_server, record.project_code, "overview")
    assert [t.inner_text() for t in page.locator("[role='tab']").all()] == ["Debt terms", "Overview", "Bankability", "Senior facilities", "Sources & uses", "Investors & sponsor"]
    assert page.locator("[data-senior-pricing='FLAT']").count() == 1 and page.locator("[data-senior-dscr='FLAT_SCALAR']").count() == 1
    closed = page.locator("[data-financing-closed='true']").inner_text()
    for needle in ("Junior / subordinated", "Mezzanine / PIK", "Third or further senior", "Floating-rate"):
        assert needle in closed
    terms = page.locator("[data-senior-terms='true']").inner_text()
    api = studio(context, live_server, record.project_code)
    for label, value in api["senior_detail_rows"]:
        assert label.lower() in terms.lower() and (value is None or value in terms)       # labels are upper-cased by CSS
    shot(page, "overview-1440")
    page.locator("[data-financing-tab-button='terms']").click()
    page.wait_for_selector("text=Gearing")                                        # the existing scalar editor is intact
    page.locator("[data-financing-tab-button='bankability']").click()
    page.wait_for_selector("[data-bankability-editor='true']")
    assert "analysis" not in page.url and "financing=bankability" in page.url
    page.reload()
    page.wait_for_selector("[data-bankability-editor='true']")                   # linkable and survives a refresh
    assert unexpected(errors) == []


# ── serializer parity with the Legacy editor ───────────────────────────────

def test_react_and_legacy_editors_send_byte_identical_configuration_documents(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-parity")
    n = len(studio(context, live_server, record.project_code)["bankability"]["periods"])
    assert n >= 10
    # Legacy form
    legacy_bodies = []
    page.route("**/v2/workbook/update", lambda route: (legacy_bodies.append(route.request.post_data), route.abort()))
    page.goto(f"{live_server}/v2/workbook?project={record.project_code}")
    page.wait_for_selector("[data-f2-form]", state="attached")
    page.evaluate(LEGACY_DRIVE, plan(n))
    page.wait_for_function("() => true")
    for _ in range(50):
        if legacy_bodies:
            break
        page.wait_for_timeout(100)
    assert legacy_bodies, "the Legacy form did not submit"
    page.unroute("**/v2/workbook/update")
    # React form, same values
    react_bodies = []
    page.route("**/v2/workbook/update", lambda route: (react_bodies.append(route.request.post_data), route.abort("connectionreset")))
    open_tab(page, live_server, record.project_code, "bankability")
    drive_react(page, n)
    page.locator("[data-bank-save='true']").click()
    for _ in range(80):
        if react_bodies:
            break
        page.wait_for_timeout(100)
    assert react_bodies, "the React form did not submit"
    legacy_value, react_value = captured_value(legacy_bodies[0]), captured_value(react_bodies[0])
    assert react_value == legacy_value                                           # byte-identical document
    parsed = json.loads(react_value)
    assert parsed["rates_pct"] == [float(x) for x in plan(n)["rates"]] and parsed["reserve"]["mode"] == "cash_fixed"
    assert parse_qs(react_bodies[0])["field_id"] == [FIELD] == parse_qs(legacy_bodies[0])["field_id"]


# ── real Save, read-back, STALE ────────────────────────────────────────────

def test_bankability_save_reads_back_and_makes_the_last_run_stale_without_running(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-save")
    run_canonical(context, live_server, record.project_code)
    n = len(studio(context, live_server, record.project_code)["bankability"]["periods"])
    open_tab(page, live_server, record.project_code, "bankability")
    before_draft, before_snapshot = draft_of(record)
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/v2/workbook/update") else None)
    assert page.locator("[data-bank-save='true']").is_disabled()                 # nothing to save yet
    page.select_option("[data-bank='day_count']", "act_365")
    page.select_option("[data-bank='rates_mode']", "periods")
    for i in range(n):
        page.fill(f"[data-grid-cell='rate-{i}']", "6.25")
    assert page.locator("[data-bank-dirty]").get_attribute("data-bank-dirty") == "true"
    shot(page, "bankability-edited-1440")
    page.locator("[data-bank-save='true']").click()
    page.wait_for_selector("[data-wf-status='ok']", timeout=60000)
    assert "saved and read back" in page.locator("[data-wf-status='ok']").inner_text()
    assert len(posts) == 1
    api = studio(context, live_server, record.project_code)
    assert api["bankability"]["config"] == {"version": 1, "day_count": "act_365", "rates_pct": [6.25] * n}
    assert api["freshness"] == "STALE" and api["senior_pricing_mode"] == "WORKING_CONFIG"
    after_draft, after_snapshot = draft_of(record)
    assert after_snapshot == before_snapshot                                      # saving never ran the model
    assert json.loads(after_draft["bankability_config_json"]) == {"version": 1, "day_count": "act_365", "rates_pct": [6.25] * n}
    page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='STALE']", timeout=30000)
    assert page.locator("[data-bank-dirty]").get_attribute("data-bank-dirty") == "false"
    # reset removes the whole configuration after an explicit confirmation
    page.locator("[data-bank-reset='true']").click()
    page.locator("[data-bank-reset-yes='true']").click()
    page.wait_for_function("() => document.querySelector(\"[data-bank-reset='true']\") && document.querySelector(\"[data-bank-reset='true']\").disabled", timeout=60000)
    assert studio(context, live_server, record.project_code)["bankability"]["config"] == {}
    assert unexpected(errors) == []


def test_obviously_invalid_input_is_stopped_before_any_request_and_the_server_still_validates(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-invalid")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/v2/workbook/update") else None)
    open_tab(page, live_server, record.project_code, "bankability")
    page.select_option("[data-bank='rates_mode']", "periods")
    page.fill("[data-grid-cell='rate-0']", "25")
    page.fill("[data-grid-cell='rate-1']", "abc")
    page.locator("[data-bank-save='true']").click()
    problems = page.locator("[data-bank-problems='true']")
    problems.wait_for()
    assert "between 0 and 20" in problems.inner_text() and "plain number" in problems.inner_text()
    assert posts == [] and draft_of(record)[0].get("bankability_config_json") in (None, "")
    shot(page, "bankability-invalid-1440")
    # a value the advisory check cannot judge is still refused by the canonical server: period targets without sculpting
    page.select_option("[data-bank='rates_mode']", "inherit")
    page.select_option("[data-bank='sizing_mode']", "gearing_cap")
    page.select_option("[data-bank='targets_mode']", "periods")
    page.locator("[data-bank-save='true']").click()
    assert "DSCR sculpting" in page.locator("[data-bank-problems='true']").inner_text()
    assert posts == []


def test_a_changed_working_copy_is_refused_and_nothing_is_overwritten(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-stale")
    open_tab(page, live_server, record.project_code, "bankability")
    page.select_option("[data-bank='day_count']", "act_365")
    # another writer changes the draft after this view loaded (canonical route, valid CAS)
    tokens = context.request.get(f"{live_server}/v2/model-react/fields/debt", params={"project": record.project_code}).json()["save"]
    other = context.request.post(f"{live_server}/v2/workbook/update", max_redirects=0, form={
        "project": record.project_code, "field_id": FIELD, "value": json.dumps({"version": 1, "day_count": "act_360"}),
        "workbook_version": tokens["workbook_version"], "content_hash": tokens["content_hash"], "sheet_id": "debt", "csrf_token": tokens["csrf_token"]})
    assert other.status in (302, 303)
    page.locator("[data-bank-save='true']").click()
    page.wait_for_selector("[data-wf-status='conflict']", timeout=30000)
    assert "changed after this view loaded" in page.locator("[data-wf-status='conflict']").inner_text()
    assert json.loads(draft_of(record)[0]["bankability_config_json"]) == {"version": 1, "day_count": "act_360"}
    assert unexpected(errors) == []


def test_a_lost_save_response_is_unknown_never_retried_and_applied_once(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-lost")
    open_tab(page, live_server, record.project_code, "bankability")
    calls = []

    def lose(route):
        calls.append(1)
        route.fetch()
        route.abort("connectionreset")

    page.route("**/v2/workbook/update", lose)
    page.select_option("[data-bank='day_count']", "act_365")
    page.locator("[data-bank-save='true']").click()
    page.wait_for_selector("[data-bank-locked='true']", timeout=30000)
    assert "UNKNOWN" in page.locator("[data-wf-status='conflict']").inner_text()
    assert page.locator("[data-bank-save='true']").is_disabled()
    page.wait_for_timeout(800)
    assert len(calls) == 1
    assert json.loads(draft_of(record)[0]["bankability_config_json"]) == {"version": 1, "day_count": "act_365"}   # committed exactly once
    assert unexpected(errors, net=("ERR_CONNECTION_RESET",)) == []


def test_reference_models_show_the_bankability_view_read_only(live_server, fin_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = fin_session("rcm-fin-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    open_tab(page, live_server, ref.project_code, "bankability")
    assert page.locator("[data-bank-readonly='true']").count() == 1
    assert page.locator("[data-bank-save='true']").is_disabled() and page.locator("[data-bank='sizing_mode']").is_disabled()
    assert unexpected(errors, allow=(409,)) == []


# ── Excel-like grid ────────────────────────────────────────────────────────

def test_period_grid_supports_arrow_navigation_and_tsv_paste_as_drafts(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-grid")
    open_tab(page, live_server, record.project_code, "bankability")
    page.select_option("[data-bank='targets_mode']", "periods")
    page.select_option("[data-bank='rates_mode']", "periods")
    page.locator("[data-grid-cell='rate-0']").focus()
    page.keyboard.press("ArrowDown")
    assert page.evaluate("() => document.activeElement.dataset.gridCell") == "rate-1"
    page.keyboard.press("Enter")
    assert page.evaluate("() => document.activeElement.dataset.gridCell") == "rate-2"
    page.keyboard.press("ArrowUp")
    assert page.evaluate("() => document.activeElement.dataset.gridCell") == "rate-1"
    page.locator("[data-grid-cell='target-0']").focus()
    page.evaluate("""() => { const el = document.activeElement; const dt = new DataTransfer(); dt.setData('text', '1.31\\t6.10\\n1.32\\t6.20\\n1.33\\t6.30');
        el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); }""")
    assert [page.input_value(f"[data-grid-cell='target-{i}']") for i in range(3)] == ["1.31", "1.32", "1.33"]
    assert [page.input_value(f"[data-grid-cell='rate-{i}']") for i in range(3)] == ["6.10", "6.20", "6.30"]
    assert draft_of(record)[0].get("bankability_config_json") in (None, "")       # a paste is only a draft
    assert page.locator("[data-bank-dirty]").get_attribute("data-bank-dirty") == "true"


# ── read-only evidence tabs ────────────────────────────────────────────────

def test_senior_facilities_and_sources_uses_show_the_canonical_evidence(live_server, fin_session):
    context, page, record, errors = fin_session("rcm-fin-evidence")
    open_tab(page, live_server, record.project_code, "sources-uses")
    assert page.locator("[data-su-empty='true']").count() == 1                      # NOT_RUN: nothing is estimated
    run_canonical(context, live_server, record.project_code)
    page.reload()
    page.wait_for_selector("[data-sources-uses='true'] [data-su-table='Sources']", timeout=30000)
    api = studio(context, live_server, record.project_code)["sources_uses"]["view"]
    senior = next(r for r in api["sources"] if r["label"].startswith("Senior debt"))
    assert senior["display"] in page.locator("[data-su-table='Sources']").inner_text()
    assert page.locator("[data-su-balance='true']").inner_text().startswith("Balance:")
    shot(page, "sources-uses-1440")
    page.locator("[data-financing-tab-button='facilities']").click()
    page.wait_for_selector("[data-capital-stack='true']")
    stack = studio(context, live_server, record.project_code)["capital_stack"]
    assert page.locator("[data-facility]").count() == len(stack["rows"]) >= 1
    assert "NOT RELEASED" in page.locator("[data-stack-editor-state='not-released']").inner_text()
    assert page.locator("[data-capital-stack='true'] .rcm-closed li").count() == len(stack["unsupported"]) == 6
    shot(page, "facilities-1440")
    assert unexpected(errors) == []


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_every_financing_tab_fits_the_viewport(live_server, fin_session, width):
    context, page, record, errors = fin_session(f"rcm-fin-resp-{width}", width=width, height=900)
    run_canonical(context, live_server, record.project_code)
    for tab in ("overview", "bankability", "facilities", "sources-uses"):
        open_tab(page, live_server, record.project_code, tab)
        no_page_overflow(page)
        shot(page, f"{tab}-{width}")
        if tab == "bankability" and width <= 820:
            heights = page.evaluate("""() => Array.from(document.querySelectorAll('.rcm-fin button, .rcm-fin select, .rcm-fin input:not([type=checkbox]), .rcm-fin label.rcm-check'))
                .filter(n => n.offsetParent !== null && !n.disabled).map(n => n.getBoundingClientRect().height)""")
            assert min(heights) >= 43
    assert unexpected(errors) == []
