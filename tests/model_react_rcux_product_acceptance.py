"""RC-UX Addendum B — real-Chromium end-user journeys: My Projects, New Project (two paths), templates, product language, navigation.

Real server, synthetic users, real Runs.  Not collected by pytest: the existing mandatory consolidation role imports the tests below and
supplies ``live_server`` / ``browser`` / ``rcm_react_flag``.  No module-level skip lives here.  Screenshots: ``rcux-product-*.png``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_rcux_product_empty_library_has_no_system_references_and_offers_the_two_starts",
    "test_rcux_product_template_journey_creates_saves_runs_and_appears_in_my_projects",
    "test_rcux_product_create_new_path_is_a_disclosed_guided_setup",
    "test_rcux_product_templates_stay_unmodified_and_isolated_from_other_accounts",
    "test_rcux_product_a_lost_create_response_is_reconciled_and_never_duplicates",
    "test_rcux_product_populated_library_filters_orders_and_uses_real_timestamps",
    "test_rcux_product_ordinary_screens_use_no_internal_terms_and_no_legacy_links",
    "test_rcux_product_library_and_wizard_fit_every_viewport",
    "test_rcux_product_statements_identify_each_vertical_and_labels_repeat_no_units",
    "ux_user",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")
KINDS = ("solar", "wind", "data_center", "ev_charging")
TECH_LABEL = {"solar": "Solar PV", "wind": "Onshore Wind", "data_center": "Data Center", "ev_charging": "EV Charging"}
#: Words an ordinary screen must not show.  Established finance terms (DSCR, LLCR, IRR, NPV, PPA, CAPEX, OPEX ...) are deliberately absent.
BANNED = re.compile(r"\b(canonical|scalar|composite hash|composite input|CAS|snapshot|native kernel|registry|reference seed|reference model|"
                    r"clone|legacy|classic|RuntimeResult|inputs_section|data-grid-source|fresh projection|working copy|persisted)\b", re.I)
#: A file download (Run export) is not navigation to a classic screen.  There is no other exception: the Trust evidence is a React view.
LEGACY_HREF = re.compile(r"(/v2/workbook(?!/(run-history/)?export)|/projects/|/library|staging\.|/verify/|/credit-decision|/v2/capex/spending|/v2/import)")
import pytest as _pytest  # noqa: E402


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-product-{name}.png"), full_page=True)


@_pytest.fixture
def ux_user(live_server, browser, rcm_react_flag):
    """A signed-in browser session for an account that has NO projects yet."""
    from app.auth import COOKIE_NAME, create_session_token

    contexts = []

    def open_session(uid, width=1440, height=1000):
        context = browser.new_context(viewport={"width": width, "height": height})
        contexts.append(context)
        context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        return context, page, errors

    yield open_session
    for context in contexts:
        context.close()


def _projects(context, base, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    response = context.request.get(f"{base}/v2/model-react/my-projects?{query}")
    assert response.ok, response.text()[:300]
    return response.json()


def _templates(context, base):
    return context.request.get(f"{base}/v2/model-react/templates").json()["templates"]


def _open_library(page, base):
    page.goto(f"{base}/v2/model-react/")
    page.reload()
    page.wait_for_selector("[data-library-view='true']", timeout=60000)


def _create_from_template(page, base, kind, name, *, via_hash=False):
    """Journey 3-7: New Project -> Start from a template -> pick -> details -> timeline -> review -> create."""
    if via_hash:
        page.goto(f"{base}/v2/model-react/#new-project/template")
        page.reload()
    else:
        page.locator("[data-new-project-cta='true'], [data-empty-new-project='true']").first.click()
        page.wait_for_selector("[data-path-card='template']")
        page.locator("[data-path-card='template']").click()
    page.wait_for_selector(f"[data-template-card='{kind}']", timeout=60000)
    page.locator(f"[data-template-card='{kind}']").click()
    if page.locator("[data-preview-ack='true']").count():
        page.locator("[data-preview-ack='true']").check()
    page.locator("[data-wizard-next='true']").click()
    page.fill("#rcm-name", name)
    page.locator("[data-wizard-next='true']").click()
    page.wait_for_selector("[data-wizard-panel='review']")


def test_rcux_product_empty_library_has_no_system_references_and_offers_the_two_starts(live_server, ux_user):
    from app.persistence.projects_repository import get_reference_projects
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    assert get_reference_projects()                                           # the system templates exist in the database ...
    context, page, errors = ux_user("rcux-empty-library")
    _open_library(page, live_server)
    assert page.locator("[data-library-empty='true']").count() == 1             # ... and are NOT shown as projects
    text = page.locator("main").inner_text()
    assert "No projects yet." in text and "Create your first project or start from a template." in text
    assert page.locator("[data-project-code]").count() == 0 and not re.search(r"reference|Generic .* Reference", text, re.I)
    assert page.locator("[data-empty-new-project='true']").is_visible() and page.locator("[data-empty-choose-template='true']").is_visible()
    page.locator("[data-empty-choose-template='true']").click()
    page.wait_for_selector("[data-wizard-path='template']")
    assert page.locator("[data-path-note='template']").count() == 1             # the Choose a Template CTA opens the wizard on that path
    _shot(page, "empty-library")
    assert errors == []


@pytest.mark.parametrize("kind", KINDS)
def test_rcux_product_template_journey_creates_saves_runs_and_appears_in_my_projects(live_server, ux_user, kind):
    context, page, errors = ux_user(f"rcux-journey-{kind}")
    _open_library(page, live_server)
    templates = {t["key"]: t for t in _templates(context, live_server)}
    _create_from_template(page, live_server, kind, f"My {TECH_LABEL[kind]} plan")
    review = page.locator("[data-wizard-panel='review']").inner_text()
    assert "template itself is not changed" in review.lower() and "Template starting assumptions" in review
    card = templates[kind]
    for assumption in card["starting_assumptions"][:3]:
        assert assumption["label"] in review
    page.locator("[data-wizard-create='true']").click()
    page.wait_for_selector("[data-react-workspace-version]", timeout=90000)
    code = page.url.rstrip("/").split("/")[-1].split("#")[0].split("?")[0]
    # 7. the project is saved without a Run
    mine = _projects(context, live_server)
    assert mine["total"] == 1 and mine["projects"][0]["code"] == code and mine["projects"][0]["freshness"] == "NOT_RUN"
    assert mine["projects"][0]["status"] == "Not run yet" and mine["projects"][0]["technology"]["label"] == TECH_LABEL[kind]
    # 8. back to My Projects: the saved project is there
    page.locator("[data-nav-my-projects='true']").click()
    page.wait_for_selector(f"[data-project-code='{code}']")
    cardel = page.locator(f"[data-project-code='{code}']")
    assert TECH_LABEL[kind] in cardel.inner_text() and "Not run yet" in cardel.inner_text() and f"My {TECH_LABEL[kind]} plan" in cardel.inner_text()
    assert cardel.locator("[data-field='last-run']").inner_text() == "Not run yet"
    _shot(page, f"my-projects-{kind}")
    # 9-11. open, run, results and run history
    cardel.locator(f"[data-open-project='{code}']").click()
    page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
    page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled", timeout=60000)
    page.locator("[data-wf-run='true']").click()
    page.wait_for_function("() => document.querySelector('[data-freshness]')?.getAttribute('data-freshness') === 'CURRENT'", timeout=240000)
    page.goto(f"{live_server}/v2/model-react/{code}?analysis=runs#analysis")
    page.reload()
    page.wait_for_selector("[data-run-history-row]", timeout=60000)
    assert page.locator("[data-run-history-row]").count() == 1
    _open_library(page, live_server)
    after = page.locator(f"[data-project-code='{code}']")
    assert "Results up to date" in after.inner_text() and after.locator("[data-field='last-run']").inner_text() != "Not run yet"
    assert after.locator(f"[data-project-run-history='{code}']").get_attribute("href").endswith("?analysis=runs#analysis")
    assert [e for e in errors if "status of 409" not in e] == []


def test_rcux_product_create_new_path_is_a_disclosed_guided_setup(live_server, ux_user):
    context, page, errors = ux_user("rcux-create-new")
    page.goto(f"{live_server}/v2/model-react/#new-project")
    page.reload()
    page.wait_for_selector("[data-path-card='new']")
    assert page.locator("[data-wizard-next='true']").is_disabled()                # nothing proceeds before a path is chosen
    page.locator("[data-blank-project-constraint] summary").click()
    assert "cannot currently be saved" in page.locator("[data-blank-project-constraint]").inner_text()
    page.locator("[data-path-card='new']").click()
    page.wait_for_selector("[data-tech-card='solar']")
    assert "approved starting assumptions" in page.locator("[data-path-note='new']").inner_text()
    page.locator("[data-path-change='true']").click()
    page.wait_for_selector("[data-path-card='template']")                          # the choice can be changed
    page.locator("[data-path-card='new']").click()
    page.locator("[data-tech-card='wind']").click()
    page.locator("[data-wizard-next='true']").click()
    page.fill("#rcm-name", "Guided wind project")
    page.locator("[data-wizard-next='true']").click()
    page.wait_for_selector("[data-wizard-panel='review']")
    assert page.locator("[data-review='starter']").count() == 1 and page.locator("[data-review='template-assumptions']").count() == 0
    page.locator("[data-wizard-create='true']").click()
    page.wait_for_selector("[data-react-workspace-version]", timeout=90000)
    assert _projects(context, live_server)["projects"][0]["name"] == "Guided wind project"
    assert errors == []


def test_rcux_product_templates_stay_unmodified_and_isolated_from_other_accounts(live_server, ux_user):
    from app.persistence.projects_repository import get_reference_by_template_source

    ref = get_reference_by_template_source("generic_solar_reference")
    before = (json.dumps(ref.baseline_snapshot, sort_keys=True), ref.updated_at)
    context, page, errors = ux_user("rcux-iso-a")
    _open_library(page, live_server)
    _create_from_template(page, live_server, "solar", "Isolated solar")
    page.locator("[data-wizard-create='true']").click()
    page.wait_for_selector("[data-react-workspace-version]", timeout=90000)
    code = page.url.rstrip("/").split("/")[-1].split("#")[0].split("?")[0]
    again = get_reference_by_template_source("generic_solar_reference")
    assert (json.dumps(again.baseline_snapshot, sort_keys=True), again.updated_at) == before                 # creation never touches the template
    assert code != again.project_code and not again.project_code.startswith(code)
    other_context, other_page, other_errors = ux_user("rcux-iso-b")
    assert _projects(other_context, live_server)["total"] == 0                                                # another account sees nothing of it
    other_page.goto(f"{live_server}/v2/model-react/{code}")
    other_page.wait_for_selector("[data-workspace-state], [data-app-state]", timeout=60000)
    assert other_page.locator("[data-react-workspace-version]").count() == 0
    # the template is reachable by direct link for technical use but is read-only
    other_page.goto(f"{live_server}/v2/model-react/{again.project_code}#inputs")
    other_page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
    assert "TEMPLATE · READ ONLY" in other_page.locator("h1").inner_text()
    assert other_page.locator("[data-wf-run='true']").is_disabled()
    assert _projects(other_context, live_server)["total"] == 0
    assert [e for e in errors + other_errors if not re.search(r"status of (404|409)", e)] == []


def test_rcux_product_a_lost_create_response_is_reconciled_and_never_duplicates(live_server, ux_user):
    context, page, errors = ux_user("rcux-lost-response")
    _open_library(page, live_server)
    _create_from_template(page, live_server, "solar", "Retry safe solar")
    calls = []

    def lose_the_answer(route):
        calls.append(1)
        route.fetch()                                    # the server really creates the project ...
        route.abort("failed")                            # ... but the browser never sees the answer

    page.route("**/v2/model-react/new-project/create", lose_the_answer)
    page.locator("[data-wizard-create='true']").click()
    page.wait_for_selector("[data-react-workspace-version]", timeout=90000)       # the status read reconciles and opens the project
    assert len(calls) == 1                                                       # nothing was resubmitted
    mine = _projects(context, live_server)
    assert mine["total"] == 1 and mine["projects"][0]["name"] == "Retry safe solar"
    page.reload()
    assert _projects(context, live_server)["total"] == 1
    assert [e for e in errors if not re.search(r"ERR_FAILED|Failed to load resource", e)] == []


def test_rcux_product_populated_library_filters_orders_and_uses_real_timestamps(live_server, ux_user):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = "rcux-populated"
    solar = create_reference_seeded_project(user_id=uid, requested_name="Alpha Solar", template_source="generic_solar_reference", capacity_mw=20, country_market="XA")
    wind = create_reference_seeded_project(user_id=uid, requested_name="Beta Wind", template_source="generic_wind_reference", capacity_mw=48, country_market="XB")
    create_reference_seeded_project(user_id=uid, requested_name="Gamma Data", template_source="generic_data_center_reference", capacity_mw=20, country_market="XD")
    context, page, errors = ux_user(uid)
    run_canonical(context, live_server, wind.project_code)
    _open_library(page, live_server)
    names = lambda: [page.locator("[data-project-code] h3").nth(i).inner_text() for i in range(page.locator("[data-project-code]").count())]  # noqa: E731
    assert names()[0] == "Beta Wind" and set(names()) == {"Alpha Solar", "Beta Wind", "Gamma Data"}          # recently worked on first
    ws = get_workspace_state(uid, wind.project_id)
    stamp = ws.last_runtime_at.isoformat()[:16].replace("T", " ")
    assert stamp in page.locator(f"[data-project-code='{wind.project_code}'] [data-field='last-run']").inner_text()      # a real timestamp
    assert page.locator(f"[data-project-code='{solar.project_code}'] [data-field='last-run']").inner_text() == "Not run yet"   # never fabricated
    def wait_names(expected):
        page.wait_for_function("(want) => JSON.stringify(Array.from(document.querySelectorAll('[data-project-code] h3')).map(n => n.textContent).sort()) === JSON.stringify(want)",
                               arg=sorted(expected), timeout=30000)

    page.select_option("[data-filter-technology='true']", "wind")
    wait_names(["Beta Wind"])
    page.locator("[data-filter-clear='true']").click()
    wait_names(["Alpha Solar", "Beta Wind", "Gamma Data"])
    page.select_option("[data-filter-status='true']", "not_run")
    wait_names(["Alpha Solar", "Gamma Data"])
    page.locator("[data-filter-clear='true']").click()
    wait_names(["Alpha Solar", "Beta Wind", "Gamma Data"])
    page.locator("[data-filter-has-runs='true']").check()
    wait_names(["Beta Wind"])
    page.locator("[data-filter-clear='true']").click()
    wait_names(["Alpha Solar", "Beta Wind", "Gamma Data"])
    page.select_option("[data-filter-country='true']", "XD")
    wait_names(["Gamma Data"])
    page.locator("[data-filter-clear='true']").click()
    wait_names(["Alpha Solar", "Beta Wind", "Gamma Data"])
    page.select_option("[data-library-sort='true']", "name")
    page.wait_for_function("() => document.querySelector('[data-project-code] h3')?.textContent === 'Alpha Solar'")
    page.fill("[data-filter-search='true']", "zzz-nothing")
    page.keyboard.press("Enter")
    try:
        page.wait_for_selector("[data-library-no-match='true']", timeout=15000)
    except Exception:
        raise AssertionError(page.locator("main").inner_text()[:1500])
    assert "No projects match these filters." in page.locator("[data-library-no-match='true']").inner_text()
    _shot(page, "populated-library")
    assert errors == []


def _visible_text_and_links(page):
    text = page.evaluate("() => document.body.innerText")
    links = page.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))")
    return text, links


@pytest.mark.parametrize("kind", KINDS)
def test_rcux_product_ordinary_screens_use_no_internal_terms_and_no_legacy_links(live_server, ux_user, kind):
    context, page, errors = ux_user(f"rcux-language-{kind}")
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(user_id=f"rcux-language-{kind}", requested_name=f"Language {kind}", template_source=f"generic_{kind}_reference", capacity_mw=16)
    run_canonical(context, live_server, record.project_code)
    seen: dict[str, list[str]] = {}

    def audit(label):
        text, links = _visible_text_and_links(page)
        seen[label] = [text[max(0, m.start() - 45):m.end() + 45].replace("\n", " ⏎ ") for m in BANNED.finditer(text)] + [f"href:{h}" for h in links if h and LEGACY_HREF.search(h)]

    _open_library(page, live_server)
    audit("my-projects")
    page.goto(f"{live_server}/v2/model-react/#new-project")
    page.reload()
    page.wait_for_selector("[data-path-card='template']")
    audit("wizard-start")
    page.locator("[data-path-card='template']").click()
    page.wait_for_selector(f"[data-template-card='{kind}']")
    audit("wizard-templates")
    for section in ("inputs", "statements", "financing", "results", "scenarios", "analysis", "diagnostics", "trust"):
        page.goto(f"{live_server}/v2/model-react/{record.project_code}#{section}")
        page.reload()
        page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
        page.wait_for_function("() => !document.body.innerText.includes('Loading the')", timeout=60000)
        audit(section)
    page.goto(f"{live_server}/v2/model-react/{record.project_code}?analysis=runs#analysis")
    page.reload()
    page.wait_for_selector("[data-run-history-table='true']", timeout=60000)
    audit("run-history")
    offenders = {k: sorted(set(v)) for k, v in seen.items() if v}
    assert offenders == {}, json.dumps(offenders, indent=1)
    assert errors == []


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_product_library_and_wizard_fit_every_viewport(live_server, ux_user, width):
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = f"rcux-viewport-{width}"
    for i in range(2):
        create_reference_seeded_project(user_id=uid, requested_name=f"Viewport project {i}", template_source="generic_solar_reference", capacity_mw=10 + i)
    context, page, errors = ux_user(uid, width=width, height=900)
    _open_library(page, live_server)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll (library)"
    _shot(page, f"library-{width}")
    page.goto(f"{live_server}/v2/model-react/#new-project/template")
    page.reload()
    page.wait_for_selector("[data-template-card='solar']", timeout=60000)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll (wizard)"
    _shot(page, f"templates-{width}")
    if width <= 820:
        heights = page.evaluate("() => Array.from(document.querySelectorAll('[data-path-card], [data-template-card], .rcm-actions button')).filter(n => n.offsetParent !== null).map(n => n.getBoundingClientRect().height)")
        assert heights and min(heights) >= 36
    assert errors == []


@pytest.mark.parametrize("kind", KINDS)
def test_rcux_product_statements_identify_each_vertical_and_labels_repeat_no_units(live_server, ux_user, kind):
    """Audit B F02 / F05: no vertical is presented as a placeholder Solar project, and no label prints its unit twice."""
    context, page, errors = ux_user(f"rcux-identity-{kind}")
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(user_id=f"rcux-identity-{kind}", requested_name=f"Identity {kind}", template_source=f"generic_{kind}_reference", capacity_mw=16)
    run_canonical(context, live_server, record.project_code)
    texts = {}
    for section in ("inputs", "statements", "results"):
        page.goto(f"{live_server}/v2/model-react/{record.project_code}#{section}")
        page.reload()
        page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
        page.wait_for_function("() => !document.body.innerText.includes('Loading the')", timeout=60000)
        texts[section] = page.evaluate("document.body.innerText")
    if kind != "solar":
        for section in ("statements", "results"):
            hit = re.search(r"\bsolar (pv|project|plant|park|farm|example|demo)\b|\bdemo\b", texts[section], re.I)       # a limitation note may name Solar and Wind; the project itself is never called Solar
            assert not hit, (kind, section, texts[section][max(0, hit.start() - 80):hit.end() + 80] if hit else "")
    assert f"Identity {kind}" in texts["statements"]
    for section, text in texts.items():
        twice = re.findall(r"\(([^()]{1,12})\)\s*\(\1\)|\b(MW|kEUR|EUR|MWh|%)\s+\2\b", text)
        assert twice == [], (kind, section, twice[:3])
    assert [e for e in errors if "Failed to load resource" not in e] == []
