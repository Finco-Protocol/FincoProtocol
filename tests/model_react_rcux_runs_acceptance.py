"""RC-UX B2/B3 (Audit A GAP-R13) — real-Chromium acceptance of React Analysis > Run history & compare.

Real server, synthetic users, real committed Runs.  Every figure the UI shows is compared with the adapter's own canonical read; the whole
flow is asserted to issue GET requests only (nothing saved, nothing run).  Screenshots go to ``$RCM_SCREENSHOT_DIR`` as ``rcux-runs-*.png``.

Not collected by pytest: ``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory Chromium role) imports the
tests below and supplies ``live_server`` / ``browser`` / ``rcm_react_flag`` / ``an_session``.  No module-level skip lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_rcux_run_history_lists_filters_sorts_and_limits_the_selection",
    "test_rcux_compare_shows_the_canonical_deltas_and_issues_only_get_requests",
    "test_rcux_compare_cashflow_and_assumption_blocks",
    "test_rcux_runs_workspace_fits_every_viewport",
    "test_rcux_reference_models_have_no_run_history_workspace",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-runs-{name}.png"), full_page=True)


def _three_runs(context, live_server, record):
    for _ in range(3):
        run_canonical(context, live_server, record.project_code)


def _open_runs(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#analysis")
    page.wait_for_selector("[data-analysis-tools='true']", timeout=30000)
    page.locator("[data-analysis-tab='runs']").click()
    page.wait_for_selector("[data-run-history-table='true']", timeout=30000)


def _compare(context, base, code, ids):
    query = "&".join([f"project={code}"] + [f"run={i}" for i in ids])
    response = context.request.get(f"{base}/v2/model-react/compare?{query}")
    assert response.ok, response.text()[:300]
    return response.json()


def _history(context, base, code):
    body = context.request.get(f"{base}/v2/model-react/insights/history?project={code}").json()
    return [r["identity"] for r in body["history"]]


def test_rcux_run_history_lists_filters_sorts_and_limits_the_selection(live_server, an_session):
    context, page, record, errors = an_session("rcux-runs-list")
    _three_runs(context, live_server, record)
    identities = _history(context, live_server, record.project_code)
    assert len(identities) == 3
    _open_runs(page, live_server, record.project_code)
    rows = page.locator("[data-run-history-row]")
    assert rows.count() == 3
    shown = [rows.nth(i).get_attribute("data-run-history-row") for i in range(3)]
    assert shown == [i["history_id"] for i in sorted(identities, key=lambda i: i["ran_at"], reverse=True)]       # newest first
    states = {i["history_id"]: i["state"] for i in identities}
    assert sum("CURRENT" in s for s in states.values()) == 1 and sum(s == "HISTORICAL" for s in states.values()) == 2
    for history_id, state in states.items():
        assert page.locator(f"[data-run-history-row='{history_id}']").get_attribute("data-run-state") == state
    # the Last Run's composite hash equals the Working Copy: the label is shown but the Run keeps its own state
    assert page.locator("[data-matches-working-copy='true']").count() >= 1
    page.select_option("[data-run-sort='true']", "oldest")
    assert page.locator("[data-run-history-row]").first.get_attribute("data-run-history-row") == shown[-1]
    page.select_option("[data-run-filter-state='true']", "HISTORICAL")
    assert page.locator("[data-run-history-row]").count() == 2
    page.fill("[data-run-filter-text='true']", identities[0]["history_id"][:12])
    assert page.locator("[data-run-history-row]").count() <= 1
    page.fill("[data-run-filter-text='true']", "no-such-run-xyz")
    assert page.locator("[data-run-empty='true']").count() == 1
    page.locator("[data-run-filter-clear='true']").click()
    assert page.locator("[data-run-history-row]").count() == 3
    # at most three Runs can be selected for comparison
    for history_id in shown:
        page.locator(f"[data-run-select='{history_id}']").check()
    assert page.locator("[data-run-select]:checked").count() == 3
    assert page.locator("[data-run-select]:not(:checked)").count() == 0
    page.locator(f"[data-run-select='{shown[0]}']").uncheck()
    page.locator("[data-open-working-copy='true']").click()
    page.wait_for_function("() => location.hash === '#inputs'")
    _shot(page, "history-1440")
    assert errors == []


def test_rcux_compare_shows_the_canonical_deltas_and_issues_only_get_requests(live_server, an_session):
    context, page, record, errors = an_session("rcux-runs-compare")
    _three_runs(context, live_server, record)
    identities = _history(context, live_server, record.project_code)
    ids = [i["history_id"] for i in identities][:2]
    requests = []
    page.on("request", lambda r: requests.append((r.method, r.url)) if "/v2/" in r.url and "/static/" not in r.url else None)
    _open_runs(page, live_server, record.project_code)
    assert page.locator("[data-compare-state='IDLE']").count() == 1
    for history_id in ids:
        page.locator(f"[data-run-select='{history_id}']").check()
    page.wait_for_selector("[data-compare-table='true']", timeout=30000)
    api = _compare(context, live_server, record.project_code, ids)
    assert [c["history_id"] for c in api["columns"]] == ids
    for row in api["rows"]:
        shown = page.locator(f"[data-compare-row='{row['key']}']")
        assert shown.count() == 1, row["key"]
        text = shown.inner_text()
        for value in row["values"]:
            assert value in text, (row["key"], value)
        if row["availability"][1] == "available" and row["pct_deltas"][1] != "—":
            assert row["pct_deltas"][1] in shown.locator("[data-pct-delta='true']").inner_text()
    plcr = page.locator("[data-compare-row='plcr']").inner_text()
    assert "not available" in plcr and " 0" not in plcr                                 # unavailable is never zero
    page.locator("[data-delta-mode='abs']").click()
    assert page.locator("[data-pct-delta='true']").count() == 0 and page.locator("[data-abs-delta='true']").count() > 0
    page.locator("[data-delta-mode='pct']").click()
    assert page.locator("[data-abs-delta='true']").count() == 0 and page.locator("[data-pct-delta='true']").count() > 0
    page.locator("[data-delta-mode='both']").click()
    assert page.locator("[data-compare-column]").count() == 2
    # a third Run extends the comparison; the selection order keeps the reference first
    page.locator(f"[data-run-select='{identities[2]['history_id']}']").check()
    page.wait_for_function("() => document.querySelectorAll('[data-compare-column]').length === 3", timeout=30000)
    _shot(page, "compare-1440")
    assert {m for m, _ in requests} <= {"GET"}, [r for r in requests if r[0] != "GET"]   # nothing saved, nothing run
    assert errors == []


def test_rcux_compare_cashflow_and_assumption_blocks(live_server, an_session):
    context, page, record, errors = an_session("rcux-runs-cash")
    _three_runs(context, live_server, record)
    ids = [i["history_id"] for i in _history(context, live_server, record.project_code)][:2]
    _open_runs(page, live_server, record.project_code)
    for history_id in ids:
        page.locator(f"[data-run-select='{history_id}']").check()
    page.wait_for_selector("[data-cashflow-table='true']", timeout=30000)
    api = _compare(context, live_server, record.project_code, ids)
    first = api["cashflow"]["series"][0]
    assert page.locator("[data-cashflow-total='true']").inner_text().count("—") == 0 or not first["runs"][0]["available"]
    assert page.locator("[data-cashflow-table='true'] tbody tr").count() == len(first["periods"]) + 1
    page.select_option("[data-cashflow-series='true']", "dscr")
    assert "n/a (ratio)" in page.locator("[data-cashflow-total='true']").inner_text()      # a ratio is never summed
    assert "never zero" in page.locator("[data-cashflow-note='true']").inner_text()
    assert page.locator("[data-composite-equal]").get_attribute("data-composite-equal") == str(api["assumptions"]["composite_hash_equal"]).lower()
    assert "cannot be itemised" in page.locator("[data-assumptions-limitation='true']").inner_text()
    page.locator("details:has-text('Run provenance') summary").click()
    for history_id in ids:
        assert page.locator(f"[data-provenance='{history_id}']").inner_text().count(history_id) == 1
    assert errors == []


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_runs_workspace_fits_every_viewport(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcux-runs-resp-{width}", width=width, height=900)
    _three_runs(context, live_server, record)
    ids = [i["history_id"] for i in _history(context, live_server, record.project_code)][:2]
    _open_runs(page, live_server, record.project_code)
    for history_id in ids:
        page.locator(f"[data-run-select='{history_id}']").check()
    page.wait_for_selector("[data-compare-table='true']", timeout=30000)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"
    box = page.locator("[data-compare-table='true']").locator("xpath=ancestor::div[contains(@class,'rcm-scroll')][1]").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1                       # the table scrolls inside its own region
    if width <= 820:
        heights = page.evaluate("""() => Array.from(document.querySelectorAll('[data-runs-workspace] select, [data-runs-workspace] input[type=text], [data-runs-workspace] .rcm-mode'))
            .filter(n => n.offsetParent !== null).map(n => n.getBoundingClientRect().height)""")
        assert heights and min(heights) >= 36
    _shot(page, f"compare-{width}")
    assert errors == []


def test_rcux_reference_models_have_no_run_history_workspace(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcux-runs-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    page.goto(f"{live_server}/v2/model-react/{ref.project_code}#analysis")
    page.wait_for_selector("[data-analysis-tools='true']")
    page.locator("[data-analysis-tab='runs']").click()
    page.wait_for_selector("[data-runs-unavailable='true']")
    assert page.locator("[data-run-history-table='true'], [data-compare-table='true']").count() == 0
    assert [e for e in errors if "status of 409" not in e] == []          # the EXISTING Overview-tab insights read answers 409 for a reference
