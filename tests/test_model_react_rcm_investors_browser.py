"""RC-M Lane C — real-Chromium acceptance of the React Investors & sponsor panel.

Serializer parity with the Legacy F4 editor is asserted byte for byte; the Save/Reload/Run chain, refusals, a lost response and the
read-only reference state are exercised against the real server.  Screenshots: ``$RCM_SCREENSHOT_DIR`` / ``rcm-investors-*.png``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.model_react_wf1_browser_acceptance import run_canonical

SHOTS = os.environ.get("RCM_SCREENSHOT_DIR", "")


@pytest.fixture(autouse=True, scope="module")
def _react_flag():
    old = os.environ.get("FINCO_MODEL_REACT_V1")
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    yield
    if old is None:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)
    else:
        os.environ["FINCO_MODEL_REACT_V1"] = old


@pytest.fixture
def session(live_server, browser):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    contexts = []

    def open_session(uid, width=1440, height=1000):
        record = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="RCM inv", capacity_mw=20.0)
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
        page.screenshot(path=str(Path(SHOTS) / f"rcm-investors-{name}.png"), full_page=True)


def unexpected(errors, allow=(), net=()):
    return [e for e in errors if not any(f"status of {c}" in e for c in allow) and not any(n in e for n in net)]


def open_panel(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#financing")
    page.wait_for_selector("[data-financing-studio='true']", timeout=30000)
    page.locator("[data-financing-tab-button='investors']").click()
    page.wait_for_selector("[data-investors-panel='true'], [data-investors-state]", timeout=30000)


def api(context, base, code):
    return context.request.get(f"{base}/v2/model-react/investors/agreement", params={"project": code}).json()


def draft_of(record):
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(record.user_id, record.project_id)
    return dict(ws.draft_snapshot), ws.last_runtime_snapshot_id


def add_holder(page, i, name, pct, commitment):
    page.locator("[data-inv-add='holder']").click()
    row = page.locator(f"[data-inv-holder='{i}'] input")
    row.nth(0).fill(name); row.nth(1).fill(pct); row.nth(2).fill(commitment)


def add_contribution(page, i, name, date, amount):
    page.locator("[data-inv-add='contribution']").click()
    row = page.locator(f"[data-inv-contribution='{i}'] input")
    row.nth(0).fill(name); row.nth(1).fill(date); row.nth(2).fill(amount)


PARITY = {"id": "AGR-PARITY", "holders": [("INV-A", "60", "1000"), ("INV-B", "40", "1000")],
          "contributions": [("INV-A", "2031-03-01", "60.5"), ("INV-B", "2031-03-01", "40")]}


def test_react_and_legacy_editors_send_byte_identical_agreement_documents(live_server, session):
    context, page, record, errors = session("rcm-inv-parity")
    bodies = []
    page.route("**/v2/workbook/investor/agreement", lambda route: (bodies.append(route.request.post_data), route.abort())
               if route.request.method == "POST" else route.continue_())
    # Legacy form
    page.goto(f"{live_server}/v2/workbook?project={record.project_code}")
    page.wait_for_selector("[data-testid='f4-agreement-panel']", state="attached")
    page.evaluate("() => { const p = document.querySelector('[data-testid=\"f4-agreement-panel\"]'); p.open = true; p.dispatchEvent(new Event('toggle', {bubbles: false})); }")
    page.wait_for_selector(".f4-agreement-form", state="attached", timeout=30000)
    page.evaluate("""(p) => {
      const form = document.querySelector('.f4-agreement-form');
      form.elements.agreement_id.value = p.id;
      const add = (kind) => form.querySelector(`[data-f4-add="${kind}"]`).click();
      const fill = (row, values) => row.querySelectorAll('[data-f4-field]').forEach((el, i) => { el.value = values[i]; });
      p.holders.forEach((h) => { add('investor'); fill(form.querySelectorAll('[data-f4-investor]')[form.querySelectorAll('[data-f4-investor]').length - 1], h); });
      p.contributions.forEach((c) => { add('contribution'); fill(form.querySelectorAll('[data-f4-contribution]')[form.querySelectorAll('[data-f4-contribution]').length - 1], c); });
      form.requestSubmit(form.querySelector('button[name="action"][value="save"]'));
    }""", PARITY)
    for _ in range(60):
        if bodies:
            break
        page.wait_for_timeout(100)
    assert bodies, "the Legacy form did not submit"
    legacy = parse_qs(bodies[0], keep_blank_values=True)
    # React form, same values
    del bodies[:]
    open_panel(page, live_server, record.project_code)
    page.fill("[data-inv='agreement_id']", PARITY["id"])
    for i, h in enumerate(PARITY["holders"]):
        add_holder(page, i, *h)
    for i, c in enumerate(PARITY["contributions"]):
        add_contribution(page, i, *c)
    assert page.locator("[data-inv-ownership-total]").get_attribute("data-inv-ownership-total") == "100.0000"
    page.locator("[data-inv-save='true']").click()
    for _ in range(80):
        if bodies:
            break
        page.wait_for_timeout(100)
    assert bodies, "the React form did not submit"
    react = parse_qs(bodies[0], keep_blank_values=True)
    assert react["agreement"] == legacy["agreement"]                              # byte-identical agreement document
    assert react["action"] == ["save"] and react["project"] == legacy["project"]     # (the Legacy action travels with the clicked button, not requestSubmit)
    assert json.loads(react["agreement"][0])["investors"][0]["ownership_fraction"] == 0.6


def test_save_reload_run_gives_run_bound_evidence_and_the_same_numbers_as_the_adapter(live_server, session):
    context, page, record, errors = session("rcm-inv-flow")
    run_canonical(context, live_server, record.project_code)
    funding = api(context, live_server, record.project_code)["funding"]
    assert funding
    open_panel(page, live_server, record.project_code)
    assert "No working agreement is saved" in page.locator("[data-investor-workflow-text='true']").inner_text()
    assert page.locator("[data-inv-save='true']").is_disabled()
    page.fill("[data-inv='agreement_id']", "AGR-FLOW")
    add_holder(page, 0, "INV-A", "60", "1000")
    add_holder(page, 1, "INV-B", "40", "1000")
    n = 0
    for row in funding:
        for name, share in (("INV-A", 0.6), ("INV-B", 0.4)):
            add_contribution(page, n, name, row["date"], repr(round(row["paid_in_keur"] * share, 10)))
            n += 1
    shot(page, "edited-1440")
    before_draft, before_snapshot = draft_of(record)
    page.locator("[data-inv-save='true']").click()
    page.wait_for_selector("[data-wf-status='ok']", timeout=60000)
    assert "saved and read back" in page.locator("[data-wf-status='ok']").inner_text()
    body = api(context, live_server, record.project_code)
    assert body["terms"]["agreement_id"] == "AGR-FLOW" and body["terms"]["version"] == 1 and len(body["terms"]["investors"]) == 2
    assert draft_of(record)[1] == before_snapshot                                  # Save never ran the model
    assert json.loads(draft_of(record)[0]["investor_agreement_json"])["agreement_id"] == "AGR-FLOW"
    page.wait_for_selector("[data-investor-workflow='SAVED_NOT_RUN']")
    assert page.locator("[data-investor-evidence]").count() == 0 or "Last Run" in page.inner_text("[data-investors-panel]")
    # deliberate Run -> evidence
    run_canonical(context, live_server, record.project_code)
    page.reload()
    page.wait_for_selector("[data-investor-workflow='INCORPORATED']", timeout=30000)
    api_rows = api(context, live_server, record.project_code)["evidence"]["investors"]
    for mine in api_rows:
        cells = page.locator(f"[data-evidence-row='{mine['investor_id']}'] td").all_inner_texts()
        assert cells[0] == f"{mine['ownership_fraction'] * 100:.2f}%"
        assert cells[4] == f"{mine['residual_distributions_keur']:,.2f}"
        assert cells[6] == (f"{mine['dpi']:.3f}x" if mine["dpi"] is not None else "UNAVAILABLE")
    shot(page, "evidence-1440")
    text = page.inner_text("[data-investors-panel]")
    for needle in ("Project IRR is not Pure Equity IRR", "No shareholder-loan control is editable", "Preferences and carry", "NAV / terminal valuation"):
        assert needle in text
    assert page.locator("[data-sponsor-returns='true'] [data-sponsor-metric]").count() == 4
    assert unexpected(errors) == []


def test_an_ownership_total_other_than_100_is_refused_by_the_server_and_nothing_changes(live_server, session):
    context, page, record, errors = session("rcm-inv-refuse")
    open_panel(page, live_server, record.project_code)
    before = draft_of(record)
    page.fill("[data-inv='agreement_id']", "AGR-BAD")
    add_holder(page, 0, "INV-A", "50", "1000")
    add_holder(page, 1, "INV-B", "40", "1000")
    assert page.locator("[data-inv-ownership-total]").get_attribute("data-inv-ownership-total") == "90.0000"
    page.locator("[data-inv-save='true']").click()
    page.wait_for_selector("[data-wf-status='error']", timeout=30000)
    assert "Nothing was changed" in page.locator("[data-wf-status='error']").inner_text()
    assert draft_of(record) == before and api(context, live_server, record.project_code)["terms"] is None
    assert page.locator("[data-inv-save='true']").is_enabled()                      # a definitive refusal may be corrected and resubmitted
    assert unexpected(errors, allow=(422,)) == []


def test_a_lost_save_response_is_unknown_never_retried_and_committed_once(live_server, session):
    context, page, record, errors = session("rcm-inv-lost")
    calls = []

    def lose(route):
        if route.request.method != "POST":
            return route.continue_()
        calls.append(1)
        route.fetch()
        route.abort("connectionreset")

    page.route("**/v2/workbook/investor/agreement", lose)
    open_panel(page, live_server, record.project_code)
    page.fill("[data-inv='agreement_id']", "AGR-LOST")
    add_holder(page, 0, "INV-A", "100", "500")
    page.locator("[data-inv-save='true']").click()
    page.wait_for_selector("[data-investors-locked='true']", timeout=30000)
    assert "UNKNOWN" in page.locator("[data-wf-status='conflict']").inner_text()
    assert page.locator("[data-inv-save='true']").is_disabled()
    page.wait_for_timeout(800)
    assert len(calls) == 1 and api(context, live_server, record.project_code)["terms"]["agreement_id"] == "AGR-LOST"
    assert unexpected(errors, net=("ERR_CONNECTION_RESET",)) == []


def test_reference_models_are_read_only(live_server, session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = session("rcm-inv-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    open_panel(page, live_server, ref.project_code)
    assert page.locator("[data-investors-readonly='true']").count() == 1
    assert page.locator("[data-inv-save='true']").is_disabled() and page.locator("[data-inv='agreement_id']").is_disabled()
    assert unexpected(errors, allow=(409,)) == []


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_the_panel_fits_every_viewport(live_server, session, width):
    context, page, record, errors = session(f"rcm-inv-resp-{width}", width=width, height=900)
    run_canonical(context, live_server, record.project_code)
    open_panel(page, live_server, record.project_code)
    add_holder(page, 0, "INV-A", "100", "500")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    shot(page, f"panel-{width}")
    if width <= 820:
        heights = page.evaluate("""() => Array.from(document.querySelectorAll('.rcm-fin button, .rcm-fin select, .rcm-fin input:not([type=checkbox])'))
            .filter(n => n.offsetParent !== null && !n.disabled).map(n => n.getBoundingClientRect().height)""")
        assert min(heights) >= 43
    assert unexpected(errors) == []
