"""Excel migration V3 in a REAL authenticated Chromium: upload -> assess -> scenario slice -> review -> Apply -> Run -> reconcile.

Synthetic generic workbooks only.  The workbook is never stored; every write goes through the existing signed review
ticket and canonical batch writer; the Run is a separate, explicit, user-started native Run.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from tests import migration_fixtures as F  # noqa: E402
from tests.migration_routes_support import journey_workbook  # noqa: E402
from tests.test_model_ai_import_browser_c import (  # noqa: E402,F401
    OWNER, _new_seeded_browser_project, _page, _run_in_real_browser_context, app_server, browser,
)

SHOTS = Path(os.environ.get("IMPORT_V2_SCREENSHOT_DIR", "artifacts/model-import-v2"))
SHOTS.mkdir(parents=True, exist_ok=True)


def value(project, field):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    ws = get_workspace_state(OWNER, project.project_id)
    return ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK).get(field)


def assess_file(page, root, project, path):
    page.goto(root + "/v2/workbook/import?project=" + project.project_code)
    page.locator("#upload").set_input_files(str(path))
    page.get_by_test_id("assess-workbook").click()
    page.get_by_text("Excel model migration assessment").wait_for()


def open_all(page):
    page.locator("details").evaluate_all("els => els.forEach(e => { e.open = true; })")


def test_assess_review_apply_run_reconcile_in_chromium(browser, app_server, tmp_path):
    from decimal import Decimal
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state

    project = _new_seeded_browser_project("solar", f3_active=False)
    ctx, page = _page(browser, app_server["url"], width=1440)
    root = app_server["url"]
    try:
        initial = _run_in_real_browser_context(ctx, page, root, project)
        history_before = tuple(h.history_id for h in get_run_history(OWNER, project.project_id))
        # the existing scenario workflow creates the Upside Working Copy scenario and makes it the active target
        created = ctx.request.post(root + "/v2/workbook/scenarios/create", form={"project": project.project_code, "scenario_name": "Upside"},
                                   headers={"HX-Request": "true"})
        assert created.status == 200, created.text()[:400]
        target = get_workspace_state(OWNER, project.project_id)
        assert target.active_scenario_name == "Upside"
        path = tmp_path / "synthetic-model.xlsx"
        path.write_bytes(journey_workbook(summary_ref="Inputs!C3"))

        assess_file(page, root, project, path)
        open_all(page)
        assert page.get_by_test_id("scenario-overall").inner_text() == "STATIC_OBSERVABLE"
        assert page.get_by_test_id("macro-flag").inner_text().endswith("no")
        text = page.get_by_test_id("plan-block").inner_text().lower()
        for needle in ("direct input mapping", "structured input requires owner editor", "formula or macro dependency",
                       "output for reconciliation only", "unsupported or ambiguous"):
            assert needle in text, needle
        assert page.locator('tr[data-class="OUTPUT_FOR_RECONCILIATION_ONLY"]').count() >= 2
        assert "(not authoritative)" in text                                           # a cached result is shown as evidence only
        assert "Upside" in page.get_by_test_id("slices-block").inner_text()
        page.screenshot(path=str(SHOTS / "migration-01-assess-desktop.png"), full_page=True)
        assert get_workspace_state(OWNER, project.project_id).draft_snapshot == target.draft_snapshot       # assessment is read-only
        assert tuple(h.history_id for h in get_run_history(OWNER, project.project_id)) == history_before

        page.get_by_test_id("source-target-ack-upside").check()
        page.get_by_test_id("review-slice-upside").click()
        page.get_by_text("Review detected assumptions").wait_for()
        assert page.get_by_test_id("migration-banner").count() == 1 and page.locator(".approve-box:checked").count() == 0
        page.get_by_test_id("select-validated").click()
        approved_count = page.locator(".approve-box:checked").count()
        assert approved_count >= 3
        page.get_by_role("button", name="Review approved change set").click()           # blocked: scenario not confirmed
        assert page.get_by_text("Final confirmation", exact=False).count() == 0
        page.get_by_test_id("scenario-confirm").check()
        page.screenshot(path=str(SHOTS / "migration-02-review-scenario.png"), full_page=True)
        page.get_by_role("button", name="Review approved change set").click()
        page.get_by_text("Final confirmation", exact=False).wait_for()
        assert page.get_by_test_id("migration-banner-confirm").count() == 1
        assert get_workspace_state(OWNER, project.project_id).draft_snapshot == target.draft_snapshot       # review is not a write
        page.get_by_role("button", name=f"Apply {approved_count} approved fields atomically").click()
        page.get_by_text("Import Apply result").wait_for()
        assert page.get_by_test_id("changed-not-run").inner_text() == "CHANGED — NOT RUN"
        page.screenshot(path=str(SHOTS / "migration-03-applied-not-run.png"), full_page=True)
        assert float(value(project, "opex.lines.insurance")) == pytest.approx(38.0)             # the Upside column
        assert float(value(project, "capex.C.grid_connection")) == pytest.approx(1100.0)
        assert float(value(project, "capex.D.audit_legal")) == pytest.approx(45.5)
        stale = get_workspace_state(OWNER, project.project_id)
        assert stale.dirty and stale.last_runtime_snapshot_id == target.last_runtime_snapshot_id
        assert tuple(h.history_id for h in get_run_history(OWNER, project.project_id)) == history_before     # no automatic Run

        # explicit native Run in a second tab, then compare from the result tab
        run_tab = ctx.new_page()
        current = _run_in_real_browser_context(ctx, run_tab, root, project)
        assert not current.dirty and len(get_run_history(OWNER, project.project_id)) == len(history_before) + 1
        page.get_by_test_id("reconcile-form").get_by_role("button").click()
        page.get_by_test_id("reconcile-block").wait_for()
        assert page.get_by_test_id("run-state").inner_text() == "CURRENT"
        page.get_by_test_id("attest").check()
        page.get_by_role("button", name="Compare", exact=True).click()
        page.get_by_test_id("recon-summary").wait_for()
        entry = get_run_history(OWNER, project.project_id)[0]
        row = page.locator('tr[data-status]', has_text="Summary!B2")
        assert row.get_attribute("data-status") in ("PASS", "FAIL"), row.inner_text()
        cells = [c.strip() for c in row.locator("td").all_inner_texts()]
        finco = Decimal(str(entry.runtime_summary["total_capex_keur"]))
        assert cells[1].startswith("1245.5") and Decimal(cells[3]) == finco                       # source cached value vs committed Run
        assert Decimal(cells[4].split()[0]) == finco - Decimal("1245.5")                          # signed residual FINCO - source
        irr = page.locator('tr[data-status]', has_text="Summary!B3")
        assert irr.get_attribute("data-status") == "NOT_COMPARABLE"
        assert "parity" in page.get_by_test_id("recon-summary").inner_text().lower()
        page.screenshot(path=str(SHOTS / "migration-06-reconciliation.png"), full_page=True)
        assert not page.browser_errors
        # the earlier Run history entries are immutable
        assert set(history_before) <= {h.history_id for h in get_run_history(OWNER, project.project_id)}
    finally:
        ctx.close()


def test_macro_workbook_and_unresolved_switch_are_inspection_only_in_chromium(browser, app_server, tmp_path):
    project = _new_seeded_browser_project("solar", f3_active=False)
    ctx, page = _page(browser, app_server["url"], width=1440)
    root = app_server["url"]
    try:
        data = F.to_xlsm(F.add_external_link(F.save(F.selector_only_workbook())), F.build_vba_container(["ThisWorkbook", "ScenarioSwitch"]))
        path = tmp_path / "synthetic-macro-model.xlsm"
        path.write_bytes(data)
        assess_file(page, root, project, path)
        assert page.get_by_test_id("macro-flag").inner_text().endswith("yes")
        vba = page.get_by_test_id("vba-block").inner_text()
        assert "ScenarioSwitch" in vba and "nothing was executed" in vba.lower()
        assert page.get_by_test_id("scenario-overall").inner_text() == "SCENARIO_LOGIC_UNRESOLVED"
        assert page.get_by_test_id("selector").count() == 1
        blockers = page.get_by_test_id("blockers").inner_text()
        assert "MACRO_PRESENT" in blockers and "EXTERNAL_LINKS" in blockers and "SCENARIO_LOGIC_UNRESOLVED" in blockers
        assert page.get_by_test_id("slice-blocked").count() >= 1
        assert page.get_by_test_id("review-slice-COMMON").count() == 1          # only the case-independent input is offered
        page.screenshot(path=str(SHOTS / "migration-04-macro-unresolved.png"), full_page=True)
        # the flat Extract-and-review path still refuses macro containers
        page.goto(root + "/v2/workbook/import?project=" + project.project_code)
        page.locator("#upload").set_input_files(str(path))
        page.get_by_role("button", name="Extract and review").click()
        assert page.get_by_text("IMPORT_FORMAT_UNSUPPORTED").count() >= 1
    finally:
        ctx.close()


def test_portfolio_manifest_and_mobile_layout_in_chromium(browser, app_server, tmp_path):
    project = _new_seeded_browser_project("solar", f3_active=False)
    ctx, page = _page(browser, app_server["url"], width=390)
    root = app_server["url"]
    try:
        a, b = tmp_path / "one.xlsx", tmp_path / "two.xlsx"
        a.write_bytes(journey_workbook())
        b.write_bytes(F.save(F.selector_only_workbook()))
        assess_file(page, root, project, a)
        page.locator("#next-upload").set_input_files(str(b))
        page.get_by_role("button", name="Add to manifest").click()
        page.get_by_test_id("manifest-table").wait_for()
        assert page.locator('[data-testid="manifest-table"] tbody tr').count() == 2
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, page.evaluate("""() => {
            const clipped = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
                if (['auto', 'hidden', 'scroll'].includes(getComputedStyle(p).overflowX)) return true; } return false; };
            return Array.from(document.querySelectorAll('body *')).filter(
                e => (e.getBoundingClientRect().right > innerWidth + 2 || e.scrollWidth > innerWidth + 2) && !clipped(e)).slice(0, 10).map(
                e => e.tagName + '.' + e.className + ' r=' + Math.round(e.getBoundingClientRect().right) + ' sw=' + e.scrollWidth + ' ' + e.textContent.slice(0, 30)); }""")
        table = page.get_by_test_id("manifest-table").inner_text().lower()
        assert "scenario logic unresolved" in table and "static observable" in table and "not started" in table
        page.screenshot(path=str(SHOTS / "migration-05-manifest-mobile.png"), full_page=True)
        with page.expect_download() as info:
            page.get_by_test_id("download-manifest").click()
        content = Path(info.value.path()).read_text()
        assert '"workbook_sha256"' in content and "1200000" not in content and "CHOOSE" not in content
        assert not page.browser_errors
    finally:
        ctx.close()
