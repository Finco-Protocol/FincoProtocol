"""WF-09 candidate planner in a REAL authenticated Chromium (production main_web registration, real CSP)."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from tests.test_model_ai_import_browser_c import (  # noqa: E402,F401
    OWNER, _new_seeded_browser_project, _page, app_server, browser,
)

SHOTS = Path(os.environ.get("WF09_SCREENSHOT_DIR", "artifacts/wf09-capex-profiles"))
SHOTS.mkdir(parents=True, exist_ok=True)


def _state(project):
    from app.persistence.db import get_cursor
    from app.persistence.capex_sub_lines import list_sub_lines_for_project
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(OWNER, project.project_id)
    with get_cursor() as cur:
        rows = [(s.sub_line_id, s.amount_keur, s.is_active, s.schedule_json, s.updated_at)
                for s in list_sub_lines_for_project(cur, project.project_id, include_inactive=True)]
    return ws.draft_snapshot, ws.saved_snapshot, ws.dirty, ws.last_runtime_snapshot_id, rows, tuple(h.history_id for h in get_run_history(OWNER, project.project_id))


def _fill(page, key, shape, **extra):
    row = page.locator(f'tr[data-item="{key}"]')
    row.locator("select").select_option(shape)
    if "explicit" in extra:
        row.locator('input[name^="explicit_"]').fill(extra["explicit"])
    if "milestone" in extra:
        row.locator('input[name^="milestone_"]').fill(extra["milestone"])


def test_planner_preview_in_chromium_changes_nothing(browser, app_server):
    project = _new_seeded_browser_project("solar", f3_active=False)
    ctx, page = _page(browser, app_server["url"], width=1440)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    try:
        page.goto(app_server["url"] + "/v2/workbook?project=" + project.project_code)
        link = page.get_by_test_id("capex-profile-link")
        assert "preview only" in link.inner_text()
        before = _state(project)
        page.goto(app_server["url"] + link.get_attribute("href"))
        assert page.get_by_test_id("preview-banner").is_visible() and "no Run is started" in page.get_by_test_id("preview-banner").inner_text()
        assert page.locator('[data-testid="item-table"] tbody tr').count() == 12
        _fill(page, "C.02.01", "FRONT_LOADED")
        _fill(page, "C.01.01", "MILESTONE", milestone="3")
        _fill(page, "C.02.02", "EXPLICIT", explicit="50,40,0,0,0,0,0,0,0,0,0,0,0,0")        # 90 %: must be rejected, not normalised
        _fill(page, "C.03.01", "BACK_LOADED")
        page.get_by_test_id("preview-submit").click()
        page.get_by_test_id("plan-result").wait_for()
        assert page.get_by_test_id("plan-result").get_attribute("data-canonical") == "false"
        assert page.get_by_test_id("row-error").inner_text() == "CAPEX_PROFILE_WEIGHT_SUM_INVALID"
        planned = Decimal(page.get_by_test_id("planned-total").inner_text())
        profiled = Decimal(page.get_by_test_id("profiled-total").inner_text())
        unalloc = Decimal(page.get_by_test_id("unallocated-total").inner_text())
        assert planned == Decimal("8250") and profiled == Decimal("3500") + Decimal("390") + Decimal("325") and unalloc == Decimal("1500")
        rows = page.locator('[data-testid="month-table"] tbody tr')
        assert rows.count() == 14
        first_month = rows.nth(0).locator("td").all_inner_texts()
        last_month = rows.nth(13).locator("td").all_inner_texts()
        assert first_month[2] == "P0" and last_month[2] == "P2" and Decimal(last_month[-1]) == 0          # nothing remains after month 14
        assert Decimal(last_month[-2]) == profiled                                                          # cumulative reaches the profiled total
        totals = [Decimal(r.locator("td").all_inner_texts()[-3]) for r in [rows.nth(i) for i in range(14)]]
        assert sum(totals) == profiled
        assert "intra-period monthly timing is not represented" in page.get_by_test_id("period-equivalent").inner_text()
        page.screenshot(path=str(SHOTS / "wf09-01-preview-1440.png"), full_page=True)
        assert _state(project) == before                                                                    # nothing saved, no Run
        assert not errors, errors
    finally:
        ctx.close()


def test_planner_mobile_layout_has_no_page_overflow(browser, app_server):
    project = _new_seeded_browser_project("solar", f3_active=False)
    ctx, page = _page(browser, app_server["url"], width=390)
    try:
        page.goto(app_server["url"] + "/v2/capex/spending-profiles?project=" + project.project_code)
        _fill(page, "C.02.01", "UNIFORM")
        page.get_by_test_id("preview-submit").click()
        page.get_by_test_id("plan-result").wait_for()
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, overflow
        page.screenshot(path=str(SHOTS / "wf09-02-preview-390.png"), full_page=True)
        assert not page.browser_errors
    finally:
        ctx.close()
