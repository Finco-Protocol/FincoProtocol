"""RC-M — every new surface stays legible (WCAG AA text contrast, no page overflow) in every selectable theme.

Uses the same contrast probe as the Overnight B theme acceptance.  Disabled controls are exempt, as in WCAG.
"""
from __future__ import annotations

import os

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.model_react_overnight_b_acceptance import CONTRAST_JS, THEMES
from tests.model_react_wf1_browser_acceptance import run_canonical

TEXT = ("h1,h2,h3,h4,label,p,li,button:not(:disabled),a,th,td,dt,dd,legend,summary,"
        "select:not(:disabled),input:not(:disabled):not([type=checkbox])")
SELECTOR = ", ".join(f"{scope} :is({TEXT})" for scope in (".rcm-wizard", ".rcm-analysis", ".rcm-fin")) + \
    ", .rcm-tabs button, .rcm-new-project-cta, .fm-workspace-bar a, .rcm-tag, .rcm-badge, .rcm-chip"
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture(autouse=True, scope="module")
def _react_flag():
    old = os.environ.get("FINCO_MODEL_REACT_V1")
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    yield
    if old is None:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)
    else:
        os.environ["FINCO_MODEL_REACT_V1"] = old


def check(page, label):
    sampled = page.evaluate(CONTRAST_JS, SELECTOR)
    assert sampled, label
    weak = [s for s in sampled if s["ratio"] < 4.5]
    assert not weak, f"{label}: contrast below 4.5:1 for {weak[:4]}"
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), f"{label}: horizontal page scroll"


def test_new_surfaces_are_legible_in_every_theme(live_server, browser):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = "rcm-theme"
    record = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="RCM theme", capacity_mw=20.0)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    try:
        run_canonical(context, live_server, record.project_code)

        def select_theme(theme):
            page.locator("[data-testid='finco-theme-select']").select_option(label=theme)
            page.wait_for_timeout(120)

        for theme in THEMES:
            # Library + wizard
            page.goto(f"{live_server}/v2/model-react/")
            page.wait_for_selector("[data-new-project-cta='true']")
            select_theme(theme); check(page, f"{theme} / library")
            page.goto(f"{live_server}/v2/model-react/#new-project")
            page.wait_for_selector("[data-new-project-wizard='true']")
            select_theme(theme)
            page.locator("[data-tech-card='data_center']").click()
            check(page, f"{theme} / wizard step 1 (preview box)")
            page.locator("[data-preview-ack]").check()
            page.locator("[data-wizard-next]").click()
            page.wait_for_selector("[data-wizard-panel='details']")
            page.fill("#rcm-name", "Theme check")
            page.locator("[data-wizard-next]").click()
            page.wait_for_selector("[data-wizard-panel='timeline']")
            check(page, f"{theme} / wizard step 3")
            page.locator("[data-wizard-next]").click()
            page.wait_for_selector("[data-wizard-panel='review']")
            check(page, f"{theme} / wizard step 4")
            # Analysis
            for tool, marker in (("sensitivity", "[data-sensitivity-panel='true']"), ("goal-seek", "[data-goal-seek-panel='true']")):
                page.goto(f"{live_server}/v2/model-react/{record.project_code}#analysis")
                page.wait_for_selector("[data-analysis-tools='true']")
                select_theme(theme)
                page.locator(f"[data-analysis-tab='{tool}']").click()
                page.wait_for_selector(marker)
                if tool == "sensitivity":
                    page.locator("[data-sens-run='true']").click()
                    page.wait_for_selector("[data-strip-table='true']", timeout=240000)
                else:
                    page.locator("[data-gs-target='true']").fill("12")
                    page.locator("[data-gs-solve='true']").click()
                    page.wait_for_selector("[data-gs-result]", timeout=240000)
                check(page, f"{theme} / {tool}")
            # Financing
            for tab, marker in (("overview", "[data-financing-overview='true']"), ("bankability", "[data-bankability-editor='true']"),
                                ("facilities", "[data-capital-stack='true']"), ("sources-uses", "[data-sources-uses='true']"),
                                ("investors", "[data-investors-panel='true']")):
                page.goto(f"{live_server}/v2/model-react/{record.project_code}#financing")
                page.wait_for_selector("[data-financing-studio='true']")
                select_theme(theme)
                page.locator(f"[data-financing-tab-button='{tab}']").click()
                page.wait_for_selector(marker, timeout=30000)
                check(page, f"{theme} / financing {tab}")
        assert [e for e in errors if "status of" not in e] == [], errors
    finally:
        context.close()
