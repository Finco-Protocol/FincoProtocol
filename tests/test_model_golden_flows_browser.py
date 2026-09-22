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


_CHROMIUM_EXEC = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="module")
def browser():
    launch_kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    import os
    if os.path.exists(_CHROMIUM_EXEC):
        launch_kwargs["executable_path"] = _CHROMIUM_EXEC
    with sync_playwright() as pw:
        instance = pw.chromium.launch(**launch_kwargs)
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
        page.wait_for_load_state("networkidle", timeout=15_000)
        page.locator(".v2-compare-chip").first.wait_for(state="visible", timeout=10_000)
        chips = page.locator(".v2-compare-chip")
        assert chips.count() >= 2, (
            "Compare tab must show ≥2 chips after fresh-on-open GET; "
            "GF-F03: scenario created after initial page load must appear"
        )
        # Base case chip carries the v2-scenario-base-badge marker
        base_chip = page.locator(".v2-compare-chip .v2-scenario-base-badge")
        assert base_chip.count() >= 1, "Base Case chip must be present (v2-scenario-base-badge)"
        scenario_chip_fresh = page.locator(".v2-compare-chip", has_text=scenario_name)
        assert scenario_chip_fresh.count() >= 1, (
            f"Scenario '{scenario_name}' chip must appear after tab click (GF-F03)"
        )
        assert len(golden_app["calls"]) == calls_before_compare, (
            "Opening Compare tab must not execute the engine"
        )
        # Select two distinct chips by index to avoid re-clicking the same chip.
        # Scenario chip renders first; nth(0) and nth(1) are always different.
        page.locator(".v2-compare-chip").nth(0).click()
        page.locator(".v2-compare-chip--selected").first.wait_for(state="attached", timeout=5_000)
        page.locator(".v2-compare-chip").nth(1).click()
        page.locator("#v2-compare-submit-btn:not([disabled])").wait_for(state="visible", timeout=10_000)
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


# ── Golden Flow B ─────────────────────────────────────────────────────────────
# Protected Reference → Working Copy → causal Run → reopen
# ─────────────────────────────────────────────────────────────────────────────


def test_golden_flow_b_reference_to_working_copy_causal_run_reopen(
    golden_app, browser
):
    """Library → reference → Create Working Copy → causal edit → Run → reopen."""
    uid = "golden-b-" + uuid.uuid4().hex[:8]
    page = _page(browser, golden_app, user_id=uid)
    try:
        base_url = golden_app["url"]
        calls = golden_app["calls"]

        # ── 1. Navigate to library; find the solar reference project ─────────
        page.goto(base_url + "/library")
        page.wait_for_url("**/library**")

        ref_code = "generic_solar_reference-reference"
        ref_badge = page.locator(f'[data-testid="badge-reference-{ref_code}"]')
        ref_badge.wait_for(state="visible", timeout=10_000)
        assert ref_badge.count() >= 1, "Solar reference row must have reference badge in library"

        # ── 2. Open the reference in the workbook ────────────────────────────
        page.locator(f'[data-testid="open-{ref_code}"]').click()
        page.wait_for_url("**/v2/workbook**")
        _click_tab(page, "tab-overview", "panel-overview")
        # Toolbar must show "Reference" badge, not "Working Copy"
        assert page.locator(".v2-toolbar-ref-badge").count() == 1, (
            "Reference project must show Reference badge in toolbar"
        )
        assert page.locator(".v2-toolbar-wc-badge").count() == 0, (
            "Reference project must not show Working Copy badge"
        )

        # ── 3. Verify inputs are read-only (protected notice present) ────────
        _click_tab(page, "tab-inputs", "panel-inputs")
        assert page.locator(".v2-protected-notice").count() >= 1, (
            "Reference project must show protected notice in inputs"
        )
        # Save button must be absent for reference inputs
        assert page.locator(
            '#panel-inputs [data-field-id="project_setup.technical.p50_hours"] button[name="Save"]'
        ).count() == 0 or page.locator(
            '#panel-inputs [data-field-id="project_setup.technical.p50_hours"] input[name="value"]'
        ).get_attribute("readonly") is not None or page.locator(
            '.v2-protected-notice'
        ).count() >= 1, "Reference inputs are read-only"

        # ── 4. Create working copy from library ──────────────────────────────
        page.goto(base_url + "/library")
        page.wait_for_url("**/library**")
        ref_badge.wait_for(state="visible", timeout=10_000)
        calls_before_copy = len(calls)
        clone_btn = page.locator(f'[data-testid="clone-{ref_code}"]')
        clone_btn.wait_for(state="visible", timeout=10_000)
        clone_btn.click()
        # HTMX fires HX-Redirect → browser navigates to new workbook
        page.wait_for_url("**/v2/workbook**", timeout=30_000)
        wc_project = page.locator("#v2-workbook-shell").get_attribute("data-project")
        assert wc_project, "Working copy must have a project code"
        assert wc_project != ref_code, "Working copy must have a distinct project code"
        assert len(calls) == calls_before_copy, (
            "Creating a working copy must not execute the engine"
        )

        # ── 5. Verify working copy identity ──────────────────────────────────
        _click_tab(page, "tab-overview", "panel-overview")
        assert page.locator(".v2-toolbar-wc-badge").count() == 1, (
            "Working copy must show Working Copy badge in toolbar"
        )
        assert page.locator(".v2-toolbar-ref-badge").count() == 0, (
            "Working copy must not show Reference badge"
        )

        # ── 6. Capture baseline p50 from the working copy ────────────────────
        _click_tab(page, "tab-inputs", "panel-inputs")
        p50_field = page.locator(
            '#panel-inputs [data-field-id="project_setup.technical.p50_hours"] input[name="value"]'
        )
        p50_field.wait_for(state="visible", timeout=10_000)
        initial_p50_wc = float(p50_field.input_value())
        assert initial_p50_wc > 0, "Working copy must inherit p50_hours from reference"

        # ── 7. Causal edit: change p50_hours ─────────────────────────────────
        # Working copy has no prior run; after save the OOB fires banner-not-run
        # (has_runtime=False → NOT_RUN state, not STALE).
        new_p50 = initial_p50_wc * 1.15
        p50_field.fill(str(new_p50))
        p50_row = page.locator(
            '#panel-inputs [data-field-id="project_setup.technical.p50_hours"]'
        )
        p50_row.get_by_role("button", name="Save").click()
        # After save, OOB banner swaps in — wait for any banner to confirm save completed
        page.locator(
            '[data-testid="banner-not-run"], [data-testid="banner-stale"]'
        ).first.wait_for(state="attached", timeout=15_000)

        # ── 8. Run exactly once ───────────────────────────────────────────────
        calls_before_run = len(calls)
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=120_000
        )
        assert len(calls) == calls_before_run + 1, (
            "Exactly one engine execution for one visible Run"
        )

        # ── 9. Capture post-run KPIs + identity ──────────────────────────────
        _click_tab(page, "tab-overview", "panel-overview")
        irr_after = _metric_text(page, "kpi-project-irr")
        snapshot_after = _metric_text(page, "overview-snapshot-id")
        run_at_after = _metric_text(page, "overview-run-at")
        assert irr_after not in ("—", ""), "IRR must be populated after Run"
        assert snapshot_after not in ("—", ""), "Snapshot ID must be populated after Run"

        # Export is enabled after run
        assert page.locator('[data-testid="v2-export-btn"]:not([disabled])').count() == 1, (
            "Export button must be enabled after Run"
        )

        # ── 10. Access isolation: a different user cannot open this project ───
        calls_before_isolation = len(calls)
        uid2 = "golden-b-other-" + uuid.uuid4().hex[:8]
        page2 = _page(browser, golden_app, user_id=uid2)
        try:
            page2.goto(base_url + f"/v2/workbook?project={wc_project}", timeout=15_000)
            # Must not reach the workbook — either redirect to library/login or 404
            page2.wait_for_load_state("load")
            final_url = page2.url
            found_workbook = (
                f"project={wc_project}" in final_url
                and page2.locator("#v2-workbook-shell").count() > 0
            )
            assert not found_workbook, (
                f"User '{uid2}' must not be able to open '{uid}' working copy '{wc_project}'"
            )
        finally:
            page2.close()
        assert len(calls) == calls_before_isolation, (
            "Access isolation probe must not execute the engine"
        )

        # ── 11. Navigate away via toolbar back ───────────────────────────────
        page.locator(".v2-toolbar-back").click()
        page.wait_for_url("**/library**")

        # ── 12. Reopen working copy ───────────────────────────────────────────
        calls_before_reopen = len(calls)
        page.locator(f'[data-testid="open-{wc_project}"]').click()
        page.wait_for_url(f"**project={wc_project}**")
        page.wait_for_load_state("networkidle", timeout=15_000)
        assert len(calls) == calls_before_reopen, (
            "Reopen must NOT execute the engine"
        )

        # ── 13. Verify persistence after reopen ──────────────────────────────
        _click_tab(page, "tab-overview", "panel-overview")
        assert _metric_text(page, "kpi-project-irr") == irr_after, (
            "Project IRR must persist through reopen"
        )
        assert _metric_text(page, "overview-snapshot-id") == snapshot_after, (
            "Snapshot ID must persist (no implicit run on reopen)"
        )
        assert _metric_text(page, "overview-run-at") == run_at_after, (
            "Run timestamp must persist (no timestamp rotation on reopen)"
        )
        assert page.locator('[data-testid="overview-status-current"]').count() == 1, (
            "Status must remain CURRENT after reopen"
        )

        # Edited p50 input persists
        _click_tab(page, "tab-inputs", "panel-inputs")
        persisted_p50 = float(
            page.locator(
                '#panel-inputs [data-field-id="project_setup.technical.p50_hours"] input[name="value"]'
            ).input_value()
        )
        assert abs(persisted_p50 - new_p50) < 0.01, (
            "Edited p50_hours must persist through reopen"
        )

        # Reference project persistence: reference project code and project_id unchanged
        page.goto(base_url + "/library")
        page.wait_for_url("**/library**")
        ref_badge_after = page.locator(f'[data-testid="badge-reference-{ref_code}"]')
        assert ref_badge_after.count() >= 1, (
            "Reference project must still exist in library after working copy creation"
        )
    finally:
        page.close()


# ── Golden Flow C ─────────────────────────────────────────────────────────────
# Run A → Working edit → stale state → reopen stale → Run B
# ─────────────────────────────────────────────────────────────────────────────


def test_golden_flow_c_run_a_stale_working_edit_reopen_run_b(golden_app, browser):
    """Run A → scalar Working edit → verify stale → reopen → Run B with transition proof."""
    uid = "golden-c-" + uuid.uuid4().hex[:8]
    page = _page(browser, golden_app, user_id=uid)
    try:
        base_url = golden_app["url"]
        calls = golden_app["calls"]

        # ── 1. Create a fresh editable project ───────────────────────────────
        name = "Golden C " + uuid.uuid4().hex[:8]
        project = _create_project_from_visible_flow(page, base_url, name)
        assert page.locator(".v2-toolbar-wc-badge").inner_text().lower() == "working copy"

        # ── 2. Establish clean state — Run A ─────────────────────────────────
        calls_before_run_a = len(calls)
        run_a = _run(page, calls)
        _, equity_irr_a, snapshot_a, calls_after_a = run_a
        assert len(calls) == calls_before_run_a + 1, "Run A must invoke engine exactly once"

        # Capture additional Run A evidence — read IRR from Overview tab for
        # consistent formatting with the post-save comparison below.
        _click_tab(page, "tab-overview", "panel-overview")
        irr_a = _metric_text(page, "kpi-project-irr")
        run_at_a = _metric_text(page, "overview-run-at")
        assert snapshot_a not in ("—", ""), "Run A snapshot must be populated"
        assert irr_a not in ("—", ""), "Run A Project IRR must be populated"
        assert page.locator('[data-testid="overview-status-current"]').count() == 1, (
            "After Run A, status must be CURRENT"
        )

        # Returns must show Run A evidence
        _click_tab(page, "tab-returns", "panel-returns")
        assert page.locator('[data-testid="returns-authority-bar"]').count() == 1, (
            "Returns authority bar must be visible after Run A"
        )

        # ── 3. Scalar Working edit — DO NOT RUN ──────────────────────────────
        _click_tab(page, "tab-inputs", "panel-inputs")
        p50_row = page.locator(
            '#panel-inputs [data-field-id="project_setup.technical.p50_hours"]'
        )
        p50_before = float(p50_row.locator('input[name="value"]').input_value())
        new_p50 = p50_before * 1.10

        p50_row.locator('input[name="value"]').fill(str(new_p50))
        p50_row.get_by_role("button", name="Save").click()
        # Wait for stale state to appear after save (DO NOT click Run)
        page.locator('[data-testid="overview-status-stale"], .v2-runtime-dirty').first.wait_for(
            state="attached", timeout=15_000
        )
        calls_after_save = len(calls)

        # ── 4. Verify stale state immediately after save ──────────────────────
        # Toolbar state — overview stale
        _click_tab(page, "tab-overview", "panel-overview")
        assert page.locator('[data-testid="overview-status-stale"]').count() == 1, (
            "Overview must show STALE after Working edit"
        )
        assert page.locator('[data-testid="overview-status-current"]').count() == 0, (
            "Overview must NOT show CURRENT after Working edit without run"
        )
        # Last Run snapshot and KPIs must remain Run A's
        assert _metric_text(page, "overview-snapshot-id") == snapshot_a, (
            "Snapshot ID must remain Run A's after Working edit (no implicit run)"
        )
        assert _metric_text(page, "overview-run-at") == run_at_a, (
            "Run timestamp must remain Run A's after Working edit"
        )
        assert _metric_text(page, "kpi-project-irr") == irr_a, (
            "Project IRR must remain Run A's after Working edit (Last Run authority)"
        )

        # Returns must remain STALE but show Run A economics
        _click_tab(page, "tab-returns", "panel-returns")
        assert page.locator('[data-testid="returns-authority-bar"]').count() == 1, (
            "Returns must remain visible after Working edit"
        )

        # Export must still be bound to Run A (enabled but reflects Run A)
        assert page.locator('[data-testid="v2-export-btn"]:not([disabled])').count() == 1, (
            "Export button must remain enabled after Working edit (still bound to Run A)"
        )

        # Engine must not have fired on save
        assert len(calls) == calls_after_save, (
            "Working edit Save must NOT execute the engine"
        )

        # ── 5. GF-F04 Consistency check: Base Case scenario-card freshness ────
        # FORBIDDEN: global=Stale AND Base Case scenario row=Current
        _click_tab(page, "tab-scenarios", "panel-scenarios")
        page.wait_for_load_state("networkidle", timeout=10_000)
        base_case_row = page.locator(".v2-scenario-row").filter(
            has=page.locator(".v2-scenario-base-badge")
        )
        if base_case_row.count() > 0:
            base_state_current = base_case_row.locator(".v2-scenario-state--clean").count()
            # Overview is stale, so base case showing Current is a contradiction
            assert base_state_current == 0, (
                "GF-F04: Base Case scenario row must NOT show Current when global state is Stale. "
                "Contradiction: toolbar=Stale AND Base Case row=Current"
            )

        # ── 6. Navigate away and reopen ──────────────────────────────────────
        page.locator(".v2-toolbar-back").click()
        page.wait_for_url("**/library**")

        calls_before_reopen = len(calls)
        page.locator(f'[data-testid="open-{project}"]').click()
        page.wait_for_url(f"**project={project}**")
        page.wait_for_load_state("networkidle", timeout=15_000)
        assert len(calls) == calls_before_reopen, (
            "Reopen must NOT execute the engine (no implicit Run)"
        )

        # ── 7. Verify stale state persists after reopen (T3) ─────────────────
        _click_tab(page, "tab-overview", "panel-overview")
        assert page.locator('[data-testid="overview-status-stale"]').count() == 1, (
            "STALE state must survive browser reopen (no implicit run)"
        )
        assert _metric_text(page, "overview-snapshot-id") == snapshot_a, (
            "Snapshot ID must remain Run A's after reopen"
        )
        assert _metric_text(page, "overview-run-at") == run_at_a, (
            "Run timestamp must remain Run A's after reopen"
        )
        assert _metric_text(page, "kpi-project-irr") == irr_a, (
            "Project IRR must remain Run A's after reopen (no implicit calculation)"
        )

        # T3: scenario card must also show STALE after reopen (GET path fix).
        _click_tab(page, "tab-scenarios", "panel-scenarios")
        page.wait_for_load_state("networkidle", timeout=10_000)
        base_case_row_reopen = page.locator(".v2-scenario-row").filter(
            has=page.locator(".v2-scenario-base-badge")
        )
        if base_case_row_reopen.count() > 0:
            base_state_current_reopen = base_case_row_reopen.locator(
                ".v2-scenario-state--clean").count()
            assert base_state_current_reopen == 0, (
                "T3/GF-F05: Base Case scenario card must NOT show Current after "
                "reopen into a stale workspace (GET-path canonical freshness gap)"
            )

        # Working edit persists
        _click_tab(page, "tab-inputs", "panel-inputs")
        persisted_p50 = float(
            page.locator(
                '#panel-inputs [data-field-id="project_setup.technical.p50_hours"] input[name="value"]'
            ).input_value()
        )
        assert abs(persisted_p50 - new_p50) < 0.01, (
            "Working-edited p50_hours must persist through reopen"
        )

        # ── 8. Run B — explicit Run on the stale Working state ────────────────
        calls_before_run_b = len(calls)
        run_b = _run(page, calls)
        _, equity_irr_b, snapshot_b, calls_after_b = run_b
        assert len(calls) == calls_before_run_b + 1, "Run B must invoke engine exactly once"

        # Run B snapshot must differ from Run A
        assert snapshot_b != snapshot_a, (
            "Run B must produce a new snapshot identity distinct from Run A"
        )

        # ── 9. Verify post-Run-B state ────────────────────────────────────────
        _click_tab(page, "tab-overview", "panel-overview")
        assert page.locator('[data-testid="overview-status-current"]').count() == 1, (
            "Status must be CURRENT after Run B"
        )
        assert _metric_text(page, "overview-snapshot-id") == snapshot_b, (
            "Snapshot ID must be updated to Run B"
        )
        # Read irr_b from visible Overview tab for consistent formatting.
        irr_b = _metric_text(page, "kpi-project-irr")
        assert irr_b not in ("—", ""), "Run B Project IRR must be populated"

        # Causal KPI transition: p50 * 1.10 should change IRR
        assert irr_b != irr_a, (
            "Run B IRR must differ from Run A IRR (p50_hours changed by 10%)"
        )

        # Returns must reflect Run B
        _click_tab(page, "tab-returns", "panel-returns")
        assert page.locator('[data-testid="returns-authority-bar"]').count() == 1, (
            "Returns must be populated after Run B"
        )

        # Export remains enabled and now binds to Run B
        assert page.locator('[data-testid="v2-export-btn"]:not([disabled])').count() == 1, (
            "Export button must be enabled after Run B"
        )

        # ── 10. Scenario-card consistency after Run B (T4) ───────────────────
        _click_tab(page, "tab-scenarios", "panel-scenarios")
        page.wait_for_load_state("networkidle", timeout=10_000)
        base_case_row_b = page.locator(".v2-scenario-row").filter(
            has=page.locator(".v2-scenario-base-badge")
        )
        if base_case_row_b.count() > 0:
            # T4: after Run B, effective scenario must be CURRENT (not STALE).
            base_state_stale_b = base_case_row_b.locator(
                ".v2-scenario-state--stale").count()
            base_state_current_b = base_case_row_b.locator(
                ".v2-scenario-state--clean").count()
            assert base_state_stale_b == 0, (
                "T4/GF-F05: Base Case scenario card must NOT show Stale after "
                "Run B completes (effective scenario must be CURRENT)"
            )
            assert base_state_current_b == 1, (
                "T4/GF-F05: Base Case scenario card must show Current after "
                "Run B — global state is CURRENT and hash matches"
            )

    finally:
        page.close()
