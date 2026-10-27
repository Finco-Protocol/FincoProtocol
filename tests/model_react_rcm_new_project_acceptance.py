"""RC-M Lane A — real-Chromium acceptance of the React New Project wizard.

Runs against the real server (main_web) with synthetic users.  Every figure the wizard shows is compared with the
server's own canonical reads; nothing is asserted from hard-coded financial values.  Screenshots go to
``$RCM_SCREENSHOT_DIR`` (when set) as ``rcm-*.png``.


Not collected by pytest: ``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory Chromium role) imports the
tests and fixtures below and supplies ``live_server`` / ``browser`` / ``rcm_react_flag``.  No module-level skip lives here.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


__all__ = (
    "test_new_project_is_prominent_in_the_library_and_the_global_navigation",
    "test_the_global_navigation_link_opens_the_wizard_from_a_workspace",
    "test_pilot_candidate_wizard_creates_exactly_one_not_run_working_copy",
    "test_wizard_created_and_directly_created_projects_have_identical_effective_inputs",
    "test_preview_vertical_needs_an_explicit_acknowledgement",
    "test_double_clicking_create_creates_one_project",
    "test_a_lost_response_after_commit_is_reconciled_without_a_second_project",
    "test_a_lost_request_fails_closed_without_a_retry_control_and_survives_reload",
    "test_an_expired_security_token_is_refused_and_nothing_is_created",
    "test_keyboard_only_flow_reaches_review",
    "test_every_step_fits_the_viewport_with_usable_touch_targets",
    "test_wizard_renders_in_every_selectable_theme",
    "np_session",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")      # CI: the role's uploaded screenshot folder
VIEWPORTS = (320, 390, 768, 1440)
NEW = "#new-project"


@pytest.fixture
def np_session(live_server, browser, rcm_react_flag):
    from app.auth import COOKIE_NAME, create_session_token

    contexts = []

    def open_session(uid, width=1440, height=1000, scheme="light"):
        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
        contexts.append(context)
        context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error"
                and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        return context, page, errors

    yield open_session
    for context in contexts:
        context.close()


def shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcm-{name}.png"), full_page=True)


def unexpected(errors, allow=()):
    """Console errors that are not an expected, deliberately provoked refusal (HTTP status lines only)."""
    return [e for e in errors if not any(f"status of {code}" in e for code in allow)]


def projects_of(uid):
    from app.persistence.projects_repository import list_project_records

    return list_project_records(user_id=uid, include_archived=True)


def open_wizard(page, base):
    page.goto(f"{base}/v2/model-react/{NEW}")
    page.wait_for_selector("[data-new-project-wizard='true']")


def step(page):
    return int(page.locator("[data-new-project-wizard='true']").get_attribute("data-wizard-step"))


def pick(page, key):
    page.locator(f"[data-tech-card='{key}']").click()


def next_(page):
    page.locator("[data-wizard-next]").click()


def fill_details(page, name, capacity=None, country=None):
    page.fill("#rcm-name", name)
    if capacity is not None:
        page.fill("#rcm-capacity", str(capacity))
    if country is not None:
        page.select_option("#rcm-country", country)


def no_page_overflow(page):
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"


def go_to_review(page, key, name, capacity=None, country=None):
    pick(page, key)
    if page.locator("[data-preview-ack]").count():
        page.locator("[data-preview-ack]").check()
    next_(page)
    page.wait_for_selector("[data-wizard-panel='details']")
    fill_details(page, name, capacity, country)
    next_(page)
    page.wait_for_selector("[data-wizard-panel='timeline']")
    next_(page)
    page.wait_for_selector("[data-wizard-panel='review']")


def wait_workspace(page, base, project_pattern=None):
    page.wait_for_url(re.compile(rf"{re.escape(base)}/v2/model-react/(?!#)[^/#?]+"), timeout=30000)
    page.wait_for_selector("[data-react-workspace-version]", timeout=30000)


# ── entry points ───────────────────────────────────────────────────────────

def test_new_project_is_prominent_in_the_library_and_the_global_navigation(live_server, np_session):
    context, page, errors = np_session("rcm-entry")
    page.goto(f"{live_server}/v2/model-react/")
    cta = page.locator("[data-new-project-cta='true']")
    cta.wait_for()
    assert cta.inner_text().strip() == "+ New Project"
    # the existing working-copy action stays, and stays distinct
    assert page.locator("button:has-text('Create working copy')").count() >= 1
    assert page.locator("[data-nav-new-project='true']").count() == 1
    shot(page, "library-1440")
    cta.click()
    page.wait_for_selector("[data-new-project-wizard='true']")
    assert page.url.endswith(NEW) and step(page) == 1
    # Cancel returns to the Library without a reload loop
    page.locator("[data-wizard-cancel]").click()
    page.wait_for_selector("[data-library-view='true']")
    assert errors == []


def test_the_global_navigation_link_opens_the_wizard_from_a_workspace(live_server, np_session):
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = "rcm-nav"
    record = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="RCM nav", capacity_mw=20.0)
    context, page, errors = np_session(uid)
    page.goto(f"{live_server}/v2/model-react/{record.project_code}")
    page.wait_for_selector("[data-nav-new-project='true']")
    page.locator("[data-nav-new-project='true']").click()
    page.wait_for_selector("[data-new-project-wizard='true']")
    assert "/v2/model-react" in page.url and page.url.endswith(NEW)
    assert errors == []


# ── Solar / Wind end to end ────────────────────────────────────────────────

@pytest.mark.parametrize("key,label,country", [("solar", "Solar", "XA"), ("wind", "Wind", "XB")])
def test_pilot_candidate_wizard_creates_exactly_one_not_run_working_copy(live_server, np_session, key, label, country):
    uid = f"rcm-{key}"
    context, page, errors = np_session(uid)
    options = context.request.get(f"{live_server}/v2/model-react/new-project/options").json()
    canon = {t["key"]: t for t in options["technologies"]}[key]
    open_wizard(page, live_server)
    # step 1: release posture from the registry; Storage is visibly closed and not selectable
    assert page.locator(f"[data-tech-card='{key}'] [data-tier]").get_attribute("data-tier") == "PILOT_CANDIDATE"
    assert page.locator("[data-tech-card='storage']").is_disabled()
    assert page.locator("[data-wizard-next]").is_disabled()
    shot(page, f"{key}-step1-1440")
    pick(page, key)
    assert page.locator(f"[data-tech-card='{key}']").get_attribute("aria-checked") == "true"
    next_(page)
    # step 2: canonical default capacity is pre-filled; invalid input is refused by the server and shown inline
    page.wait_for_selector("[data-wizard-panel='details']")
    assert float(page.input_value("#rcm-capacity")) == canon["default_capacity_mw"]
    assert page.input_value("#rcm-country") == country
    fill_details(page, "", capacity=0.01)
    next_(page)
    page.wait_for_selector("#rcm-name-err")
    page.wait_for_selector("#rcm-capacity-err")
    assert step(page) == 2 and page.locator("#rcm-name").get_attribute("aria-invalid") == "true"
    shot(page, f"{key}-step2-errors-1440")
    fill_details(page, f"RCM {label} Wizard", capacity=37.5)
    next_(page)
    # step 3: the canonical reference timeline, read-only
    page.wait_for_selector("[data-wizard-panel='timeline']")
    tl = canon["timeline"]
    assert page.locator("[data-timeline='construction_months']").inner_text().startswith(str(tl["construction_months"]))
    assert page.locator("[data-timeline='cod_date']").inner_text() == tl["cod_date"]
    assert page.locator("[data-timeline='horizon_years']").inner_text().startswith(str(tl["horizon_years"]))
    shot(page, f"{key}-step3-1440")
    next_(page)
    # step 4: effective assumptions are the server preview, not browser arithmetic
    page.wait_for_selector("[data-wizard-panel='review']")
    preview = context.request.get(f"{live_server}/v2/model-react/new-project/preview",
                                  params={"name": f"RCM {label} Wizard", "technology": key, "country": country, "capacity_mw": "37.5"}).json()
    assert page.locator("[data-review='capex']").inner_text().startswith(preview["effective"]["total_capex_display"])
    assert page.locator("[data-review='opex']").inner_text().startswith(preview["effective"]["opex_y1_display"])
    assert "NOT RUN" in page.locator("[data-review='status']").inner_text()
    assert projects_of(uid) == []                      # nothing is written before Create
    shot(page, f"{key}-step4-1440")
    page.locator("[data-wizard-create]").click()
    wait_workspace(page, live_server)
    rows = projects_of(uid)
    assert len(rows) == 1 and rows[0].project_name == f"RCM {label} Wizard"
    assert page.url.rstrip("/").endswith(rows[0].project_code)
    page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='NOT_RUN']", timeout=30000)
    shot(page, f"{key}-created-not-run-1440")
    assert unexpected(errors, allow=(422,)) == []          # the one 422 is the deliberately invalid step 2


def test_wizard_created_and_directly_created_projects_have_identical_effective_inputs(live_server, np_session):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = "rcm-parity"
    context, page, errors = np_session(uid)
    open_wizard(page, live_server)
    go_to_review(page, "solar", "RCM Parity Wizard", capacity=33, country="DE")
    page.locator("[data-wizard-create]").click()
    wait_workspace(page, live_server)
    wizard = [r for r in projects_of(uid) if r.project_name == "RCM Parity Wizard"][0]
    direct = create_reference_seeded_project(user_id="rcm-parity-oracle", template_source="generic_solar_reference",
                                             requested_name="RCM Parity Oracle", capacity_mw=33.0, country_market="DE")
    a = get_workspace_state(uid, wizard.project_id).draft_snapshot
    b = get_workspace_state("rcm-parity-oracle", direct.project_id).draft_snapshot
    volatile = {"project_name", "active_project", "_reference_seed_profile"}
    assert {k: v for k, v in a.items() if k not in volatile} == {k: v for k, v in b.items() if k not in volatile}
    assert errors == []


# ── preview verticals ──────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["data_center", "ev_charging"])
def test_preview_vertical_needs_an_explicit_acknowledgement(live_server, np_session, key):
    uid = f"rcm-{key}"
    context, page, errors = np_session(uid)
    open_wizard(page, live_server)
    pick(page, key)
    assert page.locator(f"[data-tech-card='{key}'] [data-tier]").get_attribute("data-tier") == "PREVIEW"
    page.wait_for_selector("[data-preview-limitations='true']")
    next_(page)
    page.wait_for_selector("[data-wizard-error='true']")
    assert step(page) == 1                                   # blocked without the acknowledgement
    shot(page, f"{key}-preview-1440")
    page.locator("[data-preview-ack]").check()
    next_(page)
    page.wait_for_selector("[data-wizard-panel='details']")
    assert projects_of(uid) == []
    assert errors == []


# ── duplicate / lost-response safety ───────────────────────────────────────

def test_double_clicking_create_creates_one_project(live_server, np_session):
    uid = "rcm-double"
    context, page, errors = np_session(uid)
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/new-project/create") else None)
    open_wizard(page, live_server)
    go_to_review(page, "wind", "RCM Double")
    button = page.locator("[data-wizard-create]")
    button.dblclick()
    button.click(force=True, timeout=1000) if button.is_enabled() else None
    wait_workspace(page, live_server)
    assert len(posts) == 1 and len(projects_of(uid)) == 1
    assert errors == []


def test_a_lost_response_after_commit_is_reconciled_without_a_second_project(live_server, np_session):
    uid = "rcm-lost-after"
    context, page, errors = np_session(uid)
    calls = []

    def lose_response(route):
        calls.append(1)
        route.fetch()                  # the server really commits ...
        route.abort("connectionreset")   # ... and the browser never sees the answer

    page.route("**/new-project/create", lose_response)
    open_wizard(page, live_server)
    go_to_review(page, "solar", "RCM Lost After")
    page.locator("[data-wizard-create]").click()
    wait_workspace(page, live_server)                      # reconciled by request identity -> the one project
    assert len(calls) == 1 and len(projects_of(uid)) == 1
    assert errors == [] or all("Failed to load resource" in e for e in errors)


def test_a_lost_request_fails_closed_without_a_retry_control_and_survives_reload(live_server, np_session):
    uid = "rcm-lost-before"
    context, page, errors = np_session(uid)
    calls = []
    page.route("**/new-project/create", lambda route: (calls.append(1), route.abort("connectionreset")))
    open_wizard(page, live_server)
    go_to_review(page, "solar", "RCM Lost Before")
    page.locator("[data-wizard-create]").click()
    unknown = page.locator("[data-create-unknown='true']")
    unknown.wait_for()
    assert "Result unknown" in unknown.inner_text()
    assert page.locator("[data-wizard-create]").is_disabled()          # no blind retry
    assert page.locator("[data-refresh-library='true']").count() == 1
    assert len(calls) == 1 and projects_of(uid) == []
    shot(page, "create-unknown-1440")
    page.unroute("**/new-project/create")
    assert re.search(r"#new-project:[0-9a-f]{32}$", page.url)         # the request identity lives in the URL, never in storage
    assert page.evaluate("() => [window.sessionStorage.length, window.localStorage.length]") == [0, 0]
    page.reload()                                                      # the identity reconciles the earlier request
    notice = page.locator("[data-previous-create='unknown']")
    notice.wait_for()
    assert "earlier create request" in notice.inner_text()
    page.locator("[data-previous-create] button:has-text('Dismiss')").click()
    assert page.locator("[data-previous-create]").count() == 0 and page.url.endswith(NEW)
    assert projects_of(uid) == []


def test_an_expired_security_token_is_refused_and_nothing_is_created(live_server, np_session):
    uid = "rcm-csrf"
    context, page, errors = np_session(uid)
    open_wizard(page, live_server)
    go_to_review(page, "solar", "RCM Csrf")

    def corrupt(route):
        body = route.request.post_data_json
        body["csrf_token"] = "tampered." + "0" * 64
        route.continue_(post_data=__import__("json").dumps(body))

    page.route("**/new-project/create", corrupt)
    page.locator("[data-wizard-create]").click()
    page.wait_for_selector("[data-wizard-error='true']")
    assert "nothing was created" in page.locator("[data-wizard-error='true']").inner_text()
    assert projects_of(uid) == []
    assert page.locator("[data-wizard-create]").is_enabled()
    assert all("403" in e or "Failed to load resource" in e for e in errors)


# ── keyboard, responsive and themes ────────────────────────────────────────

def test_keyboard_only_flow_reaches_review(live_server, np_session):
    context, page, errors = np_session("rcm-keyboard")
    open_wizard(page, live_server)
    page.locator("[data-tech-card='solar']").focus()
    page.keyboard.press("Space")
    assert page.locator("[data-tech-card='solar']").get_attribute("aria-checked") == "true"
    page.locator("[data-wizard-next]").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("[data-wizard-panel='details']")
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "rcm-step-heading"
    page.fill("#rcm-name", "RCM Keyboard")
    page.locator("#rcm-name").press("Enter")                 # Enter in the form advances like Next
    page.wait_for_selector("[data-wizard-panel='timeline']")
    assert errors == []


@pytest.mark.parametrize("width", VIEWPORTS)
def test_every_step_fits_the_viewport_with_usable_touch_targets(live_server, np_session, width):
    context, page, errors = np_session(f"rcm-resp-{width}", width=width, height=900)
    page.goto(f"{live_server}/v2/model-react/")
    page.wait_for_selector("[data-library-view='true']")
    no_page_overflow(page)
    shot(page, f"library-{width}")
    open_wizard(page, live_server)
    for label, action in (("step1", lambda: pick(page, "wind")), ("step2", lambda: next_(page)),
                          ("step3", lambda: (fill_details(page, "RCM Responsive"), next_(page))), ("step4", lambda: next_(page))):
        action()
        page.wait_for_function("() => document.querySelector('#rcm-step-heading')")
        no_page_overflow(page)
        shot(page, f"wizard-{label}-{width}")
        small = page.evaluate("""() => Array.from(document.querySelectorAll('.rcm-wizard button, .rcm-wizard input, .rcm-wizard select'))
            .filter(n => n.offsetParent !== null).map(n => { const r = n.getBoundingClientRect();
              return {tag: n.tagName, w: r.width, h: r.height, right: r.right, left: r.left}; })""")
        assert all(item["right"] <= width + 1 and item["left"] >= -1 for item in small), "clipped control"
        if width <= 820:
            buttons = [i for i in small if i["tag"] == "BUTTON"]
            assert all(i["h"] >= 43 for i in buttons), f"touch target below 44px at {width}: {buttons}"
    assert errors == []


@pytest.mark.parametrize("theme", ["g-forest-green-white", "b-slate-teal", "d-high-contrast"])
def test_wizard_renders_in_every_selectable_theme(live_server, np_session, theme):
    context, page, errors = np_session(f"rcm-theme-{theme}")
    open_wizard(page, live_server)
    page.evaluate("t => document.getElementById('finco-react-root').setAttribute('data-fm-theme', t)", theme)
    pick(page, "solar")
    selected = page.locator("[data-tech-card='solar']")
    border = selected.evaluate("n => getComputedStyle(n).borderTopWidth")
    assert border == "2px"                                    # the selected state is not conveyed by colour alone
    shot(page, f"theme-{theme}")
    assert errors == []
