"""True-browser acceptance for the FINCO Model Golden Flows.

The tests deliberately drive only visible product controls.  The canonical
engine is wrapped (never replaced) solely to prove which user actions execute
it.  Each flow uses an isolated persistence database.
"""
from __future__ import annotations

import socket
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def golden_app(tmp_path_factory):
    """Live application with isolated persistence and real engine execution."""
    from app.persistence import db

    db.DB_PATH = str(tmp_path_factory.mktemp("golden-flows") / "finco.db")

    import main_web
    import uvicorn
    from app.api import project_runner

    calls: list[tuple[tuple, dict]] = []
    real_run_project = project_runner.run_project

    def counted_run_project(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run_project(*args, **kwargs)

    patcher = mock.patch(
        "app.api.project_runner.run_project", side_effect=counted_run_project
    )
    patcher.start()

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "Golden Flow uvicorn server did not start"
    try:
        yield {"url": f"http://127.0.0.1:{port}", "calls": calls}
    finally:
        server.should_exit = True
        thread.join(10)
        patcher.stop()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        instance = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        yield instance
        instance.close()


def _page(browser, golden_app, *, user_id: str):
    from app.auth import COOKIE_NAME, create_session_token

    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.context.add_cookies(
        [{
            "name": COOKIE_NAME,
            "value": create_session_token(user_id=user_id, username=user_id),
            "domain": "127.0.0.1",
            "path": "/",
        }]
    )
    return page


def _click_tab(page, tab_id: str, panel_id: str) -> None:
    page.locator(f"#{tab_id}").click()
    page.locator(f"#{panel_id}").wait_for(state="visible")


def _metric_text(page, testid: str) -> str:
    return page.locator(f'[data-testid="{testid}"]').inner_text().strip()


def _create_project_from_visible_flow(page, base_url: str, name: str) -> str:
    page.goto(base_url + "/")
    page.get_by_role("link", name="Model", exact=True).click()
    page.wait_for_url("**/library")
    page.get_by_role("link", name="New Project").click()
    page.locator("#npm-project_name").fill(name)
    page.locator("#npm-project_type").select_option(label="Solar")
    page.locator("#npm-country_market").fill("Synthetic Market")
    page.locator("#npm-capacity_mw").fill("42")
    page.get_by_role("button", name="Create project").click()
    page.wait_for_url("**/v2/workbook?project=**")
    return page.locator("#v2-workbook-shell").get_attribute("data-project")


def _save_p50_hours(page, value: float) -> None:
    _click_tab(page, "tab-inputs", "panel-inputs")
    row = page.locator(
        '#panel-inputs [data-field-id="project_setup.technical.p50_hours"]'
    )
    row.locator('input[name="value"]').fill(str(value))
    row.get_by_role("button", name="Save").click()
    page.locator('[data-testid="overview-status-stale"], .v2-runtime-dirty').first.wait_for(
        state="attached"
    )


def _run(page, calls: list) -> tuple[str, str, str, int]:
    before = len(calls)
    page.locator('[data-testid="v2-run-btn"]').click()
    page.locator('[data-testid="overview-status-current"]').wait_for(
        state="attached", timeout=120_000
    )
    assert len(calls) == before + 1, "One visible Run must invoke canonical run_project once"
    return (
        _metric_text(page, "kpi-project-irr"),
        _metric_text(page, "kpi-equity-irr"),
        _metric_text(page, "overview-snapshot-id"),
        len(calls),
    )


def test_golden_flow_a_new_project_scenario_compare_and_export(golden_app, browser, tmp_path):
    """Home -> Model -> project -> Run -> scenario -> Compare -> Export."""
    page = _page(browser, golden_app, user_id="golden-a-" + uuid.uuid4().hex[:8])
    name = "Golden A " + uuid.uuid4().hex[:8]
    try:
        project = _create_project_from_visible_flow(page, golden_app["url"], name)
        assert page.locator(".v2-toolbar-name").inner_text() == name
        assert page.locator(".v2-toolbar-wc-badge").inner_text().lower() == "working copy"

        initial = _run(page, golden_app["calls"])
        _click_tab(page, "tab-inputs", "panel-inputs")
        initial_p50 = float(
            page.locator('#panel-inputs [data-field-id="project_setup.technical.p50_hours"] input[name="value"]').input_value()
        )
        _save_p50_hours(page, initial_p50 * 1.20)
        changed = _run(page, golden_app["calls"])
        assert changed[:2] != initial[:2], (
            "A visible causal tariff change must change Project IRR or Equity IRR"
        )

        for tab, panel, marker in (
            ("tab-overview", "panel-overview", '[data-testid="kpi-project-irr"]'),
            ("tab-debt", "panel-debt", "#v2-sheet-senior-debt"),
            ("tab-fs", "panel-fs", "#v2-sheet-financial-statements"),
            ("tab-returns", "panel-returns", '[data-testid="returns-authority-bar"]'),
        ):
            _click_tab(page, tab, panel)
            assert page.locator(marker).count() == 1

        _click_tab(page, "tab-scenarios", "panel-scenarios")
        scenario_name = "Golden Upside " + uuid.uuid4().hex[:5]
        page.locator('.v2-scenario-create-form input[name="scenario_name"]').fill(scenario_name)
        page.locator(".v2-scenario-create-form").get_by_role("button", name="Create").click()
        row = page.locator(".v2-scenario-row", has_text=scenario_name)
        row.wait_for(state="visible")
        if row.get_by_role("button", name="Select scenario").count():
            row.get_by_role("button", name="Select scenario").click()
            page.locator(".v2-toolbar-scenario-link", has_text=scenario_name).wait_for()
        row = page.locator(".v2-scenario-row", has_text=scenario_name)
        row.get_by_role("button", name="Edit").click()
        page.locator("#ov-p50_hours").fill(str(initial_p50 * 1.35))
        page.locator("#v2-scenario-override-form").get_by_role(
            "button", name="Save overrides"
        ).click()
        row = page.locator(".v2-scenario-row", has_text=scenario_name)
        row.get_by_text("1 override").wait_for()
        scenario_run = _run(page, golden_app["calls"])
        _click_tab(page, "tab-returns", "panel-returns")
        assert page.locator('[data-testid="returns-last-run-scenario"]').inner_text() == scenario_name

        calls_before_compare = len(golden_app["calls"])
        _click_tab(page, "tab-compare", "panel-compare")
        # GF-F03: fresh-on-open — Compare must reflect current scenario state
        # WITHOUT a page reload.  The tab HTMX GET fires on click; wait for it.
        page.locator(".v2-compare-chip").first.wait_for(state="visible", timeout=10_000)
        chips = page.locator(".v2-compare-chip")
        assert chips.count() >= 2, (
            "Compare tab must show ≥2 chips after fresh-on-open GET; "
            "GF-F03: scenario created after initial page load must appear"
        )
        base_chip = page.locator(".v2-compare-chip", has_text="Base Case")
        assert base_chip.count() >= 1, "Base Case chip must be present"
        scenario_chip_fresh = page.locator(".v2-compare-chip", has_text=scenario_name)
        assert scenario_chip_fresh.count() >= 1, (
            f"Scenario '{scenario_name}' chip must appear after tab click (GF-F03)"
        )
        assert len(golden_app["calls"]) == calls_before_compare, (
            "Opening Compare tab must not execute the engine"
        )
        chips.nth(0).click()
        scenario_chip = page.locator(".v2-compare-chip", has_text=scenario_name)
        scenario_chip.click()
        page.locator("#v2-compare-submit-btn").click()
        page.locator(".v2-compare-table").wait_for()
        assert page.locator('[data-testid="cmp-project_irr-delta"]').inner_text().strip() != "—"

        calls_before_export = len(golden_app["calls"])
        with page.expect_download(timeout=120_000) as download_info:
            page.locator('[data-testid="v2-export-btn"]').click()
        download = download_info.value
        target = tmp_path / download.suggested_filename
        download.save_as(target)
        assert target.stat().st_size > 0
        assert len(golden_app["calls"]) == calls_before_export
        assert scenario_run[2] != changed[2]

        page.locator(".v2-toolbar-back").click()
        page.wait_for_url("**/library**")
        library_row = page.locator("tr", has_text=name)
        assert library_row.get_by_text("My project").count() == 1
        library_row.get_by_role("link", name="Open").click()
        page.wait_for_url(f"**project={project}**")
        _click_tab(page, "tab-overview", "panel-overview")
        assert _metric_text(page, "overview-snapshot-id") == scenario_run[2]
    finally:
        page.close()
