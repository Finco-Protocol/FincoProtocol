"""RC-UX Addendum A — React-only navigation: every rendered target, every redirect, in real Chromium.

Acceptance rule: ZERO links, forms, frames or navigations from the React Model to a Legacy/classic screen.  Two independent nets:

* every user-visible navigation target in the DOM (``a``, ``area``, ``form``, ``iframe``/``frame``, ``button[formaction]``, ``[data-href]``,
  ``meta refresh``) is classified by :func:`violation`: ``staging.finco.one`` and EVERY same-host route outside ``/v2/model-react`` fails,
  not only a text search for the staging host;
* every top-level navigation the browser actually performs (clicks, redirects after Create / Save / Run, Back / Forward, reload) is logged and
  must stay under ``/v2/model-react``.

A Run export is a file download (an attachment, the page does not leave), not a screen: only the two export endpoints are allowed for that.

Not collected by pytest: the existing mandatory consolidation role imports the tests below and supplies ``live_server`` / ``browser`` /
``rcm_react_flag`` / ``an_session``.  No module-level skip lives here; the classifier is also exercised without a browser by
``tests/test_rcux_navigation_source.py``.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.model_react_mvp_acceptance import explicit_run
from tests.rcux_navigation_contract import DOWNLOAD_PATHS, REACT_PREFIX, TARGETS_JS, violation  # noqa: F401  (the pure contract, shared with the source test)
from tests.model_react_wf1_browser_acceptance import open_section, run_canonical
from tests.model_react_wf2_lifecycle_acceptance import CIT_CELL, DISCARD, SAVE, STAY, dialog, stage_cit, wait_dirty

__all__ = (
    "test_rcux_nav_every_section_and_subtab_has_only_react_targets",
    "test_rcux_nav_all_four_verticals_have_only_react_targets",
    "test_rcux_nav_library_to_project_to_workspace_and_back",
    "test_rcux_nav_new_project_creates_a_working_copy_inside_react",
    "test_rcux_nav_save_run_results_never_leave_react",
    "test_rcux_nav_scenario_compare_history_and_evidence_never_leave_react",
    "test_rcux_nav_financing_sponsor_reporting_and_trust_evidence_stay_in_react",
    "test_rcux_nav_deep_links_refresh_back_and_forward",
    "test_rcux_nav_unsaved_changes_block_leaving_and_cause_no_navigation",
    "test_rcux_nav_every_target_at_every_viewport_and_theme",
    "test_rcux_nav_gated_and_unavailable_screens_are_react_native",
    "test_rcux_nav_the_audit_catches_an_injected_classic_link_and_a_classic_redirect",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")
SECTIONS = ("overview", "inputs", "statements", "financing", "results", "scenarios", "analysis", "diagnostics", "trust")
KINDS = ("solar", "wind", "data_center", "ev_charging")
THEMES = ("FINCO default", "Slate & Teal", "High-Contrast")
def audit(page, label: str, seen: dict[str, int] | None = None) -> list[dict]:
    items = page.evaluate(TARGETS_JS)
    bad = [f"[{i['kind']}] {i['text']!r} -> {why}" for i in items if (why := violation(i["target"], page_url=page.url, download=i["download"]))]
    assert not bad, f"{label}: {bad}"
    if seen is not None:
        seen[label] = len(items)
    return items


def watch(page) -> list[str]:
    """Every top-level document navigation the browser performs from now on."""
    log: list[str] = []
    page.on("request", lambda r: log.append(r.url) if r.is_navigation_request() and r.frame == page.main_frame else None)
    return log


def assert_stayed_in_react(log: list[str], label: str):
    bad = [u for u in log if urlparse(u).path != REACT_PREFIX and not urlparse(u).path.startswith(REACT_PREFIX + "/")]
    assert not bad, f"{label}: navigated outside React: {bad}"


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-nav-{name}.png"), full_page=True)


def _settle(page):
    page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
    page.wait_for_function("() => !/Loading the persisted|Loading the canonical|Loading…|Loading\\.\\.\\./.test(document.body.innerText)", timeout=60000)


def _section(page, base, code, section):
    open_section(page, base, code, section)
    _settle(page)


def _tabs(page) -> int:
    return page.locator("main [role=tab], [role=tablist] [role=tab]").count()


def _click_every_tab(page, label, seen):
    """Visit every tab of every tablist currently rendered (one nesting level at a time) and audit after each."""
    total = 0
    for list_index in range(page.locator("[role=tablist]").count()):
        tablist = page.locator("[role=tablist]").nth(list_index)
        for tab_index in range(tablist.locator("[role=tab]").count()):
            tab = tablist.locator("[role=tab]").nth(tab_index)
            name = (tab.inner_text() or tab.get_attribute("aria-label") or str(tab_index)).strip().splitlines()[0]
            tab.click()
            page.wait_for_timeout(250)
            audit(page, f"{label} > {name}", seen)
            total += 1
    return total




def test_rcux_nav_every_section_and_subtab_has_only_react_targets(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-tabs")
    run_canonical(context, live_server, record.project_code)
    log, seen = watch(page), {}
    visited = {}
    for section in SECTIONS:
        _section(page, live_server, record.project_code, section)
        audit(page, section, seen)
        visited[section] = _click_every_tab(page, section, seen)
    assert visited["financing"] >= 6 and visited["analysis"] >= 5 and visited["inputs"] >= 3, visited      # financing, analysis tools, input studios
    for tool in ("overview", "sensitivity", "goal-seek", "whatif", "runs"):
        page.goto(f"{live_server}/v2/model-react/{record.project_code}?analysis={tool}#analysis")
        page.reload()
        _settle(page)
        audit(page, f"analysis ?analysis={tool}", seen)
    for tab in ("terms", "overview", "bankability", "facilities", "sources-uses", "investors"):
        page.goto(f"{live_server}/v2/model-react/{record.project_code}?financing={tab}#financing")
        page.reload()
        _settle(page)
        audit(page, f"financing ?financing={tab}", seen)
    assert sum(seen.values()) > 0
    assert_stayed_in_react(log, "sections and subtabs")
    assert [e for e in errors if "Failed to load resource" not in e] == []


@pytest.mark.parametrize("kind", KINDS)
def test_rcux_nav_all_four_verticals_have_only_react_targets(live_server, an_session, kind):
    context, page, record, errors = an_session(f"rcux-nav-{kind}", kind=kind)
    run_canonical(context, live_server, record.project_code)
    log = watch(page)
    for section in SECTIONS:
        _section(page, live_server, record.project_code, section)
        audit(page, f"{kind} / {section}")
    assert_stayed_in_react(log, kind)


def test_rcux_nav_library_to_project_to_workspace_and_back(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-library")
    run_canonical(context, live_server, record.project_code)
    log = watch(page)
    page.goto(f"{live_server}/v2/model-react/")
    page.wait_for_selector(f"[data-open-project='{record.project_code}']", timeout=60000)
    audit(page, "my projects")
    for link in ("data-project-scenarios", "data-project-run-history"):
        target = page.locator(f"[{link}='{record.project_code}']").get_attribute("href")
        assert target.startswith(f"/v2/model-react/{record.project_code}"), target
    page.locator(f"[data-open-project='{record.project_code}']").click()
    page.wait_for_url(f"**/v2/model-react/{record.project_code}**", timeout=60000)
    _settle(page)
    audit(page, "workspace opened from the library")
    page.locator("[data-nav-my-projects='true']").click()
    page.wait_for_selector(f"[data-open-project='{record.project_code}']", timeout=60000)
    assert urlparse(page.url).path.rstrip("/") == REACT_PREFIX
    page.go_back()
    page.wait_for_url(f"**/v2/model-react/{record.project_code}**", timeout=60000)
    _settle(page)
    audit(page, "Back to the workspace")
    assert_stayed_in_react(log, "library -> project -> library")
    _shot(page, "library-project")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_nav_new_project_creates_a_working_copy_inside_react(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-create")
    log = watch(page)
    created = []
    for path, card, name in (("template", "[data-template-card='solar']", "Nav from template"), ("new", "[data-tech-card='wind']", "Nav guided wind")):
        page.goto(f"{live_server}/v2/model-react/#new-project")
        page.reload()
        page.wait_for_selector("[data-new-project-wizard='true']", timeout=60000)
        audit(page, f"new project ({path}): choose a path")
        page.locator(f"[data-path-card='{path}']").click()
        page.wait_for_selector(card, timeout=60000)
        audit(page, f"new project ({path}): technology / template")
        page.locator(card).click()
        if page.locator("[data-preview-ack='true']").count():
            page.locator("[data-preview-ack='true']").check()
        page.locator("[data-wizard-next='true']").click()
        page.fill("#rcm-name", name)
        page.locator("[data-wizard-next='true']").click()
        page.wait_for_selector("[data-wizard-panel='timeline']", timeout=30000)
        audit(page, f"new project ({path}): timeline")
        page.locator("[data-wizard-next='true']").click()
        page.wait_for_selector("[data-wizard-panel='review']", timeout=30000)
        audit(page, f"new project ({path}): review")
        page.locator("[data-wizard-create='true']").click()
        page.wait_for_selector("[data-react-workspace-version]", timeout=120000)       # the new Working Copy opens in the React workspace
        route = urlparse(page.url).path
        assert route.startswith(REACT_PREFIX + "/") and route.rstrip("/") != REACT_PREFIX, route
        created.append(route)
        _settle(page)
        audit(page, f"the new working copy ({path})")
    assert len(set(created)) == 2
    assert_stayed_in_react(log, "new project -> working copy")
    _shot(page, "new-project")


def test_rcux_nav_save_run_results_never_leave_react(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-saverun")
    log = watch(page)
    _section(page, live_server, record.project_code, "inputs")
    stage_cit(page, "27")
    wait_dirty(page)
    page.locator(SAVE).click()
    page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '0'", timeout=60000)
    assert urlparse(page.url).path == f"{REACT_PREFIX}/{record.project_code}"               # Save does not redirect anywhere
    audit(page, "after Save")
    explicit_run(page)
    assert urlparse(page.url).path == f"{REACT_PREFIX}/{record.project_code}"               # Run reloads the same React workspace
    _settle(page)
    audit(page, "after Run")
    for section in ("results", "statements"):
        _section(page, live_server, record.project_code, section)
        audit(page, f"after Run / {section}")
    assert_stayed_in_react(log, "save -> run -> results")
    _shot(page, "save-run-results")


def test_rcux_nav_scenario_compare_history_and_evidence_never_leave_react(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-compare")
    run_canonical(context, live_server, record.project_code)
    log = watch(page)
    _section(page, live_server, record.project_code, "scenarios")
    audit(page, "scenarios")
    page.goto(f"{live_server}/v2/model-react/{record.project_code}?analysis=runs#analysis")
    page.reload()
    _settle(page)
    page.evaluate("() => document.querySelectorAll('details').forEach(d => { d.open = true; })")          # expose every disclosure
    audit(page, "run history (disclosures open)")
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    assert history, "the committed Run is listed"
    insights = context.request.get(f"{live_server}/v2/model-react/insights/history?project={record.project_code}")
    assert insights.ok
    _shot(page, "history")
    assert_stayed_in_react(log, "scenario -> compare -> history")


def test_rcux_nav_financing_sponsor_reporting_and_trust_evidence_stay_in_react(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-finance")
    run_canonical(context, live_server, record.project_code)
    log = watch(page)
    page.goto(f"{live_server}/v2/model-react/{record.project_code}?financing=investors#financing")
    page.reload()
    _settle(page)
    audit(page, "financing > investors & sponsor")
    _section(page, live_server, record.project_code, "results")
    audit(page, "results (reporting)")
    _section(page, live_server, record.project_code, "trust")
    audit(page, "trust")
    assert page.locator("[data-trust-load='validation']").is_enabled() and page.locator("[data-trust-load='certificate']").is_enabled()
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/trust/" in r.url else None)
    assert requests == [], "nothing is requested while the page renders"
    page.locator("[data-trust-load='validation']").click()
    page.wait_for_selector("[data-trust-result='validation']", timeout=180000)
    assert "reference" in page.locator("[data-trust-panel='validation']").inner_text().lower()
    page.locator("[data-trust-load='certificate']").click()
    page.wait_for_selector("[data-trust-result='certificate']", timeout=60000)
    audit(page, "trust (evidence shown)")
    assert any(u.split("?")[0].endswith("/trust/validation") for u in requests) and any(u.split("?")[0].endswith("/trust/certificate") for u in requests)
    assert not [u for u in requests if "/v2/workbook/" in u]
    assert urlparse(page.url).path == f"{REACT_PREFIX}/{record.project_code}"
    assert_stayed_in_react(log, "financing -> sponsor -> reporting -> trust")
    _shot(page, "trust-evidence")


def test_rcux_nav_deep_links_refresh_back_and_forward(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-history")
    run_canonical(context, live_server, record.project_code)
    log = watch(page)
    code = record.project_code
    for section in ("financing", "analysis", "trust"):
        page.goto(f"{live_server}/v2/model-react/{code}#{section}")
        page.reload()
        _settle(page)
        assert page.url.endswith(f"/{code}#{section}")
        assert page.locator(".fm-nav a.active").first.get_attribute("href") == f"#{section}"      # a deep link lands on the section, a refresh keeps it
        audit(page, f"deep link {section}")
    sequence = ("inputs", "statements", "results", "scenarios")
    for section in sequence:
        page.locator(f".fm-nav a[href='#{section}']").first.click()
        page.wait_for_function(f"() => location.hash === '#{section}'")
    for section in reversed(sequence[:-1]):
        page.go_back()
        page.wait_for_function(f"() => location.hash === '#{section}'")
        assert page.locator(".fm-nav a.active").first.get_attribute("href") == f"#{section}"
    page.go_forward()
    page.wait_for_function(f"() => location.hash === '#{sequence[1]}'")
    assert page.locator(".fm-nav a.active").first.get_attribute("href") == f"#{sequence[1]}"
    audit(page, "after Back/Forward")
    assert_stayed_in_react(log, "deep links, Back, Forward")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_nav_unsaved_changes_block_leaving_and_cause_no_navigation(live_server, an_session):
    context, page, record, errors = an_session("rcux-nav-guard")
    log = watch(page)
    _section(page, live_server, record.project_code, "inputs")
    stage_cit(page, "29")
    wait_dirty(page)
    before = len(log)
    page.locator("[data-nav-my-projects='true']").click()
    d = dialog(page)
    d.get_by_role("button", name=STAY).click()
    page.wait_for_timeout(300)
    assert urlparse(page.url).path == f"{REACT_PREFIX}/{record.project_code}" and len(log) == before          # nothing navigated
    assert page.locator(CIT_CELL).input_value() == "29"                                                        # the draft survives
    page.locator("[data-nav-my-projects='true']").click()
    dialog(page).get_by_role("button", name=DISCARD).click()
    page.wait_for_selector(f"[data-open-project='{record.project_code}']", timeout=60000)
    assert urlparse(page.url).path.rstrip("/") == REACT_PREFIX
    audit(page, "library after a confirmed discard")
    assert_stayed_in_react(log, "unsaved-changes guard")


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_nav_every_target_at_every_viewport_and_theme(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcux-nav-view-{width}", width=width, height=900)
    run_canonical(context, live_server, record.project_code)
    log = watch(page)
    for theme in THEMES:
        for section in ("inputs", "financing", "analysis", "trust"):
            _section(page, live_server, record.project_code, section)
            page.locator("[data-testid='finco-theme-select']").select_option(label=theme)
            page.wait_for_timeout(120)
            audit(page, f"{width}px / {theme} / {section}")
            assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), f"{width}px {theme} {section}: page scroll"
            nav = page.locator(".fm-nav a")
            assert nav.count() >= 8                                          # every destination stays a real link in the DOM at every width
    assert_stayed_in_react(log, f"{width}px")


def test_rcux_nav_gated_and_unavailable_screens_are_react_native(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcux-nav-gated")
    ensure_reference_models()
    template = get_reference_by_template_source("generic_solar_reference")
    log = watch(page)
    # a project that was never run: Trust offers no evidence request and says why, inside React
    _section(page, live_server, record.project_code, "trust")
    audit(page, "trust without a Run")
    assert page.locator("[data-trust-load]").count() == 0
    assert page.locator("[data-trust-unavailable='validation']").count() == 1 and page.locator("[data-trust-unavailable='certificate']").count() == 1
    # a protected template: studios and analysis are read-only React states, never a link elsewhere
    for section in SECTIONS:
        _section(page, live_server, template.project_code, section)
        audit(page, f"template / {section}")
        _click_every_tab(page, f"template / {section}", {})
    page.goto(f"{live_server}/v2/model-react/{template.project_code}#inputs")
    page.reload()
    _settle(page)
    page.locator("[data-studio-tab='import']").click()
    page.wait_for_selector("[data-import-state='read-only']", timeout=60000)
    audit(page, "template / import")
    assert_stayed_in_react(log, "gated screens")


def test_rcux_nav_the_audit_catches_an_injected_classic_link_and_a_classic_redirect(live_server, an_session):
    """Negative control: the walk must FAIL on a staging link, a same-host classic link and a real navigation to a classic route."""
    context, page, record, errors = an_session("rcux-nav-control")
    _section(page, live_server, record.project_code, "inputs")
    audit(page, "clean baseline")
    for bad in ("https://staging.finco.one/v2/workbook?project=P", "/v2/workbook/trust/certificate?project=P", "/library", "/projects/new"):
        page.evaluate("(href) => { const a = document.createElement('a'); a.id = 'rcux-injected'; a.href = href; a.textContent = 'classic'; document.body.appendChild(a); }", bad)
        with pytest.raises(AssertionError):
            audit(page, f"injected {bad}")
        page.evaluate("() => document.getElementById('rcux-injected').remove()")
    log = watch(page)
    page.evaluate("() => { window.location.assign('/library'); }")
    page.wait_for_timeout(1500)
    with pytest.raises(AssertionError):
        assert_stayed_in_react(log, "classic redirect")
