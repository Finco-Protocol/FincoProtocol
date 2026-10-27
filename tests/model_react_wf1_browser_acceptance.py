"""WF-React-1 browser acceptance bodies (Product Truth & Financial Workspace).

Not collected by pytest: executed through the thin wrappers in
``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory
Chromium role and its Playwright fixture lifecycle), exactly like the diagnostics
acceptance bodies.  No module-level skip lives here.

Covers, against the real server and a real persisted Run: product truth in every
section; canonical EUR/kEUR/mEUR conversion, ratios, negatives, rounding and
monetary KPI precision proven with an independent Decimal oracle; same-Run
Results/Analysis/Statements/Library parity; CURRENT/STALE/NOT_RUN consistency;
Library pagination, server search and Reference/Working-Copy status; navigation
and Back/Forward; desktop/tablet/mobile layout.  Screenshots go under
``$WF1_SCREENSHOT_DIR`` (or the role's ``$WF05_SCREENSHOT_DIR``) as ``wf1-*.png``.
"""
from __future__ import annotations

import os
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

CIT_CELL = "[data-grid-cell='tax.assumptions.cit_rate_pct']"
SAVE_BUTTON = "#rx-grid-save"


def make_session(browser, live_server, uid):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference",
                                             requested_name="UX02 browser", capacity_mw=20.0)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                          "url": live_server}])
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text)
            if message.type == "error"
            and not str((message.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    return context, page, record, errors


FORBIDDEN = (
    "DEMO-FIXED", "Design prototype", "SYNTHETIC DEMO", "synthetic", "No live calculations",
    "backend connection", "fixed reference", "NOT CONNECTED", "12.46%", "1.82x", "Adriatic",
    "530 MW", "fictional", "browser session only", "Illustrative", "Prototype",
)
SECTIONS = ("overview", "inputs", "statements", "financing", "results", "scenarios", "analysis",
            "diagnostics", "trust")


def run_canonical(context, base, code):
    """Run through the legacy workbook's own Run form (what its Run button posts)."""
    from bs4 import BeautifulSoup

    page = context.request.get(f"{base}/v2/workbook?project={code}")
    form = BeautifulSoup(page.text(), "html.parser").select_one("#v2-canonical-run-form")
    assert form is not None, "canonical run form missing"
    tokens = {f["name"]: f.get("value", "") for f in form.select("input[name]")}
    response = context.request.post(f"{base}/v2/workbook/run", headers={"HX-Request": "true"},
                                    form={"project": code, **tokens})
    assert response.ok, response.text()[:300]
    assert response.headers.get("x-finco-run-outcome") != "FAILED"


def api(context, base, surface, code):
    response = context.request.get(f"{base}/v2/model-react/{surface}?project={code}")
    assert response.ok, response.text()[:300]
    return response.json()


def open_section(page, base, code, section):
    page.goto(f"{base}/v2/model-react/{code}#{section}")
    page.reload()
    page.wait_for_selector("[data-react-workspace-version]")
    page.wait_for_function(
        "() => !document.body.innerText.includes('Loading the persisted') && "
        "!document.body.innerText.includes('Loading the canonical input grid')", timeout=30000)


def shot(page, name):
    folder = os.environ.get("WF1_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(folder) / f"wf1-{name}.png"), full_page=True)


def expect_display(canonical: str, base: str, shown: str, precision: int) -> str:
    """Independent oracle: exact Decimal re-expression of the canonical text."""
    text = canonical.replace(",", "")
    if text in ("—", ""):
        return "—"
    value = Decimal(text)
    exponent = {"EUR": 0, "kEUR": 3, "mEUR": 6}
    scaled = value.scaleb(exponent[base] - exponent[shown])
    quant = Decimal(1).scaleb(-precision)
    rounded = scaled.copy_abs().quantize(quant, rounding=ROUND_HALF_UP)
    body = f"{rounded:,.{precision}f}"
    return f"({body})" if value < 0 and rounded != 0 else body


def check_product_truth_no_prototype_or_synthetic_content_in_any_section(seeded):
    context, page, record, errors, base = seeded
    run_canonical(context, base, record.project_code)
    from tests.react_run_identity import text as run_text
    snapshot_id = api(context, base, "workspace", record.project_code)["identity"]["snapshot_id"]
    status = run_text(snapshot_id)
    for section in SECTIONS:
        open_section(page, base, record.project_code, section)
        body = page.inner_text("body")
        for token in FORBIDDEN:
            assert token.lower() not in body.lower(), f"{token!r} found in section {section}"
        assert page.locator(".fm-topbar").count() == 1, f"duplicate application header in {section}"
        assert page.locator("[data-origin-chip]").get_attribute("data-origin-chip") == "canonical-run"
        shot(page, f"desktop-{section}")
    open_section(page, base, record.project_code, "results")
    assert status in page.inner_text("body"), "Results must show the persisted Run identity"
    assert page.locator(f"[data-run-identity='{snapshot_id}']").count() >= 1, "the full canonical identifier is bound to the displayed Run"
    page.goto(f"{base}/v2/model-react/")
    page.wait_for_selector("[data-library-view='true']")
    body = page.inner_text("body")
    for token in FORBIDDEN:
        assert token.lower() not in body.lower(), f"{token!r} found in the Library"
    assert errors == [], errors


def expect_display_v(value, base: str, shown: str, precision: int) -> str:
    """Independent oracle on the canonical numeric value (exact decimal of its shortest repr)."""
    if value is None:
        return "—"
    return expect_display(repr(float(value)), base, shown, precision)


COLLECT_CELLS = """() => Array.from(document.querySelectorAll('button.fm-sw-cell-button')).map(b => ({
    row: b.dataset.statementRow, col: Number(b.dataset.statementCol), text: b.innerText,
    canonical: b.dataset.canonical, v: b.dataset.canonicalV === undefined ? null : b.dataset.canonicalV,
    unit: b.closest('tr').dataset.rowUnit, source: b.closest('tr').dataset.unitSource }))"""


def check_statement_units_ratios_negatives_and_rounding_match_canonical_api(seeded):
    """Same-Run end to end: API projection (canonical unit/v/text) == rendered DOM, all six destinations."""
    context, page, record, errors, base = seeded
    run_canonical(context, base, record.project_code)
    payload = api(context, base, "statements", record.project_code)
    sheets = {s["id"]: s for s in payload["snapshot"]["sheets"]}
    assert set(sheets) == {"pl", "balance", "cashflow", "cfads", "debt", "sponsor"}
    labels = {"pl": "Profit & Loss", "balance": "Balance Sheet", "cashflow": "Cash Flow (PF waterfall)",
              "cfads": "CFADS", "debt": "Debt", "sponsor": "Distributions"}
    open_section(page, base, record.project_code, "statements")
    compared = ratio_cells = negative_cells = unavailable_cells = zero_cells = 0
    for sheet_id, sheet in sheets.items():
        page.get_by_role("tab", name=labels[sheet_id], exact=True).click()
        views = ("annual", "model") if sheet_id in ("pl", "balance", "cashflow") else ("model",)
        for view in views:
            page.select_option("#fm-sw-view", view)
            key_v, key_t = ("annual_v", "annual") if view == "annual" else ("model_v", "model")
            rows = {r["id"]: r for r in sheet["rows"]}
            for unit in ("EUR", "kEUR", "mEUR"):
                for precision in (0, 3):
                    page.select_option("#fm-sw-unit", unit)
                    page.select_option("#fm-sw-precision", str(precision))
                    cells = page.evaluate(COLLECT_CELLS)
                    assert len(cells) == sum(len(r[key_t]) for r in rows.values()), (sheet_id, view)
                    for cell in cells:
                        row = rows[cell["row"]]
                        canonical_text, canonical_v = row[key_t][cell["col"]], row[key_v][cell["col"]]
                        assert cell["canonical"] == canonical_text, (sheet_id, cell)
                        assert (cell["v"] is None) == (canonical_v is None), (sheet_id, cell, canonical_v)
                        assert cell["source"] == "canonical-row-unit", (sheet_id, cell["row"], cell["source"])
                        if row["unit"] == "x":      # ratio: never monetary-scaled, canonical text precision
                            expected = "—" if canonical_v is None else f"{canonical_text}x"
                            assert cell["unit"] == "x"
                            ratio_cells += canonical_v is not None
                        else:
                            assert row["unit"] == "keur"
                            expected = expect_display_v(canonical_v, "kEUR", unit, precision)
                            assert cell["unit"] == unit
                        assert cell["text"] == expected, (sheet_id, view, unit, precision, cell["row"], cell["col"],
                                                          canonical_text, canonical_v, cell["text"], expected)
                        compared += 1
                        if canonical_v is None:
                            assert cell["text"] == "—", "an unavailable cell must never render as a number"
                            unavailable_cells += 1
                        elif canonical_v == 0:
                            zero_cells += 1
                        elif canonical_v < 0:
                            negative_cells += 1
    assert compared > 5000 and ratio_cells > 0 and unavailable_cells > 0 and zero_cells > 0 and negative_cells > 0, \
        (compared, ratio_cells, unavailable_cells, zero_cells, negative_cells)
    # canonical default shows the canonical value; headers never label kEUR values as mEUR
    page.get_by_role("tab", name="Profit & Loss", exact=True).click()
    page.select_option("#fm-sw-view", "annual")
    page.select_option("#fm-sw-unit", "kEUR")
    page.select_option("#fm-sw-precision", "2")
    assert "Statement line · kEUR" in page.inner_text("#fm-sw-sheet")
    revenue = next(r for r in sheets["pl"]["rows"] if r["id"] == "revenues_keur")
    assert page.locator("button[data-statement-row='revenues_keur'][data-statement-col='1']").inner_text() == revenue["annual"][1]
    # provenance: every row of every destination is resolved from canonical metadata, never from a label
    for sheet_id in sheets:
        page.get_by_role("tab", name=labels[sheet_id], exact=True).click()
        assert page.locator("tr[data-unit-source]").count() > 0
        assert page.locator("tr[data-unit-source]:not([data-unit-source='canonical-row-unit'])").count() == 0, sheet_id
    assert errors == [], errors


def check_results_and_analysis_values_are_the_canonical_values_of_the_same_run(seeded):
    context, page, record, errors, base = seeded
    run_canonical(context, base, record.project_code)
    payload = api(context, base, "statements", record.project_code)
    assert payload["state"] == "CURRENT"
    run_id = payload["status"]["runId"]
    pl = {r["id"]: r for r in next(s for s in payload["snapshot"]["sheets"] if s["id"] == "pl")["rows"]}

    open_section(page, base, record.project_code, "results")
    assert page.locator("[data-run-context]").get_attribute("data-run-state") == "CURRENT"
    from tests.react_run_identity import text as run_text
    assert run_text(run_id) in page.locator("[data-run-context]").inner_text()
    assert page.locator("[data-run-context] [data-run-identity]").get_attribute("data-run-identity") == run_id
    assert f"Integrity: {payload['status']['integrity']}" in page.locator("[data-results-view]").inner_text()
    # every metric card keeps the canonical source text separately (data-metric-canonical); monetary KPIs are
    # re-expressed through the selected unit/precision, everything else (IRR, MOIC, DSCR, %) is verbatim
    metrics = payload["results"]["metrics"]
    cards = page.locator("[data-metric-label]")
    assert cards.count() == len(metrics) and len(metrics) > 0

    def expected_metric(metric, unit, precision):
        if not metric["available"]:
            return "Not available"
        money = re.fullmatch(r"(.*?)\s*(kEUR|mEUR|EUR)", metric["display"].strip())
        if not money:
            return metric["display"]
        return f"{expect_display(money.group(1), money.group(2), unit, precision)} {unit}"

    monetary = [m for m in metrics if m["available"] and re.search(r"(kEUR|mEUR|EUR)$", m["display"])]
    verbatim = [m for m in metrics if m["available"] and m not in monetary]
    assert monetary and verbatim, "the Run must expose both monetary and non-monetary KPIs"
    for unit in ("EUR", "kEUR", "mEUR"):
        for precision in (0, 1, 2, 3):
            page.select_option("select[data-control='unit']", unit)
            page.select_option("select[data-control='precision']", str(precision))
            for metric in metrics:
                card = page.locator(f"[data-metric-label='{metric['label']}']")
                assert card.get_attribute("data-metric-canonical") == metric["display"], "source text must be preserved"
                value = card.locator(".rx-live-kpi-value").inner_text()
                assert value == expected_metric(metric, unit, precision), (metric["label"], unit, precision, value)
                if not metric["available"]:
                    assert card.get_attribute("data-metric-source") == metric["source"], "the Run's own reason is kept for the audit trail"
                    assert "Not available in this Run" in card.inner_text()
    for metric in verbatim:
        assert page.locator(f"[data-metric-label='{metric['label']}'] .rx-live-kpi-value").inner_text() == metric["display"]
    page.select_option("select[data-control='unit']", "kEUR")
    page.select_option("select[data-control='precision']", "1")
    # operating performance annual table: every cell traces to the canonical annual statement column
    for row_key, canonical_row in (("pl.revenues_keur", pl["revenues_keur"]), ("pl.ebit_keur", pl["ebit_keur"])):
        cells = page.locator(f"[data-period-table='operating-performance'] td[data-row='{row_key}']")
        assert cells.count() == len(canonical_row["annual"])
        for i in range(cells.count()):
            cell = cells.nth(i)
            assert cell.get_attribute("data-canonical") == canonical_row["annual"][i]
            canonical_v = canonical_row["annual_v"][i]
            assert (cell.get_attribute("data-v") is None) == (canonical_v is None)
            assert canonical_v is None or float(cell.get_attribute("data-v")) == canonical_v, "DOM value == API v"
            assert cell.inner_text() == expect_display_v(canonical_v, "kEUR", "kEUR", 1)
    # unit switch converts the same canonical values; headers carry the unit
    page.select_option("select[data-control='unit']", "mEUR")
    page.select_option("select[data-control='precision']", "3")
    cell = page.locator("[data-period-table='operating-performance'] td[data-row='pl.revenues_keur']").nth(1)
    assert cell.inner_text() == expect_display_v(pl["revenues_keur"]["annual_v"][1], "kEUR", "mEUR", 3)
    assert "Line · mEUR" in page.locator("[data-period-table='operating-performance']").inner_text()
    # sponsor cash flow table
    sponsor = payload["results"]["sponsor_table"]
    legal = next(r for r in sponsor["rows"] if r["key"] == "legal_equity_distribution_keur")
    cells = page.locator("[data-period-table='sponsor-cash-flow'] td[data-row$='legal_equity_distribution_keur']")
    assert cells.count() == len(legal["cells"])
    assert [cells.nth(i).get_attribute("data-canonical") for i in range(cells.count())] == \
        [c["text"] for c in legal["cells"]]

    # Analysis: same Run, charts carry canonical points, DSCR in x
    open_section(page, base, record.project_code, "analysis")
    assert page.locator("[data-run-context]").get_attribute("data-run-state") == "CURRENT"
    from tests.react_run_identity import text as run_text
    assert run_text(run_id) in page.locator("[data-run-context]").inner_text()
    assert page.locator("[data-run-context] [data-run-identity]").get_attribute("data-run-identity") == run_id
    chart = page.locator("[data-chart='revenue-opex']")
    assert chart.get_attribute("data-chart-state") == "available"
    bars = chart.locator("[data-series='pl.revenues_keur'] rect")
    assert bars.count() == sum(1 for t in pl["revenues_keur"]["annual"] if t not in ("—", ""))
    assert [bars.nth(i).get_attribute("data-canonical") for i in range(bars.count())][:3] == \
        [t for t in pl["revenues_keur"]["annual"] if t not in ("—", "")][:3]
    # chart geometry is driven by the canonical numeric value, not parsed display text
    assert [float(bars.nth(i).get_attribute("data-v")) for i in range(bars.count())] == \
        [v for v in pl["revenues_keur"]["annual_v"] if v is not None]
    title = bars.nth(1).locator("title").text_content()
    assert expect_display_v(pl["revenues_keur"]["annual_v"][1], "kEUR", "kEUR", 1) in title and "kEUR" in title
    assert page.locator("[data-chart='dscr']").get_attribute("data-chart-state") == "available"
    assert " x" in page.locator("[data-chart='dscr'] .rx-note").inner_text()
    for chart_id in ("revenue-opex", "ebitda-cash", "cfads-debt-service", "dscr", "debt-balance",
                     "distributions", "sponsor-cash-flow-chart"):
        assert page.locator(f"[data-chart='{chart_id}']").count() == 1
    # Statements carry the same Run identity
    open_section(page, base, record.project_code, "statements")
    from tests.react_run_identity import text as run_text
    assert run_text(run_id) in page.locator("[data-run-freshness]").inner_text()
    assert page.locator("[data-run-freshness] [data-run-identity]").get_attribute("data-run-identity") == run_id
    assert errors == [], errors


def check_current_stale_not_run_are_consistent_across_every_surface(seeded):
    context, page, record, errors, base = seeded
    code = record.project_code

    def states(expected):
        open_section(page, base, code, "overview")
        assert page.locator("[data-workspace-status]").locator("[data-freshness]").get_attribute("data-freshness") == expected
        open_section(page, base, code, "results")
        assert page.locator("[data-results-view]").get_attribute("data-results-state") == expected
        open_section(page, base, code, "analysis")
        assert page.locator("[data-analysis-view]").get_attribute("data-analysis-state") == expected
        open_section(page, base, code, "statements")
        assert page.locator("[data-statements-view]").get_attribute("data-statements-state") == expected
        page.goto(f"{base}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        library = page.locator(f"[data-project-code='{code}'] [data-run-state]").first.get_attribute("data-run-state")
        assert library == expected, (library, expected)

    # NOT_RUN: no figures anywhere, only explicit unavailable states
    states("NOT_RUN")
    open_section(page, base, code, "results")
    assert page.locator("[data-metric-label]").count() == 0 and page.locator("td[data-canonical]").count() == 0
    assert "No saved Run exists" in page.inner_text("[data-results-view]")
    open_section(page, base, code, "analysis")
    assert page.locator("[data-chart]").count() == 0 and "No saved Run exists" in page.inner_text("[data-analysis-view]")
    # CURRENT
    run_canonical(context, base, code)
    states("CURRENT")
    open_section(page, base, code, "results")
    assert "prior saved Run" not in page.inner_text("[data-results-view]")
    assert page.locator("[data-stale-banner]").count() == 0
    # STALE after a Save
    open_section(page, base, code, "inputs")
    page.wait_for_selector(CIT_CELL, timeout=60000)
    page.locator(CIT_CELL).fill("23.5")
    page.locator(SAVE_BUTTON).click()
    page.wait_for_selector("[data-save-state='saved']")
    states("STALE")
    open_section(page, base, code, "results")
    assert "STALE · prior saved Run" in page.inner_text("[data-results-view]")
    assert page.locator("[data-stale-banner]").count() == 1
    open_section(page, base, code, "analysis")
    assert page.locator("[data-stale-banner]").count() == 1
    assert errors == [], errors


def check_library_search_pagination_and_reference_working_copy_status(browser, react_enabled):
    """My Projects: one canonical page (12), search across pages, no system templates among the projects."""
    from app.services.reference_seed_service import create_reference_seeded_project

    context, page, record, errors = make_session(browser, react_enabled, "wf1-library")
    try:
        for index in range(22):
            create_reference_seeded_project(user_id="wf1-library", template_source="generic_solar_reference",
                                            requested_name=f"Needle{index:02d}" if index < 3 else f"Bulk{index:02d}",
                                            capacity_mw=5.0)
        total = 23  # the 22 above + the fixture's own project
        page.goto(f"{react_enabled}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        page.wait_for_function("() => document.querySelectorAll(\"[data-project-kind='project']\").length === 12")
        rows = page.locator("[data-project-kind='project']")
        assert rows.count() == 12, "page 1 shows exactly one canonical page"
        assert page.locator("[data-project-kind='reference']").count() == 0, "system templates are not projects"
        assert f"of {total} projects" in page.locator("[data-library-count]").inner_text()
        assert page.get_by_role("button", name="Previous").is_disabled()
        first_page = [rows.nth(i).get_attribute("data-project-code") for i in range(rows.count())]
        page.get_by_role("button", name="Next").click()
        page.wait_for_function("() => document.querySelector('[data-library-paging]').innerText.includes('Page 2 of 2')")
        page.wait_for_function(f"() => document.querySelectorAll(\"[data-project-kind='project']\").length === {total - 12}")
        second = page.locator("[data-project-kind='project']")
        assert not set(first_page) & {second.nth(i).get_attribute("data-project-code") for i in range(second.count())}
        assert page.get_by_role("button", name="Next").is_disabled()
        shot(page, "desktop-library-page2")
        page.get_by_role("button", name="Previous").click()
        page.wait_for_function("() => document.querySelector('[data-library-paging]').innerText.includes('Page 1 of 2')")

        # server-side search: filters across pages and resets to page 1
        page.locator("[data-filter-search]").fill("Needle")
        page.get_by_role("button", name="Search", exact=True).click()
        page.wait_for_function("() => document.querySelectorAll(\"[data-project-kind='project']\").length === 3")
        page.locator("[data-filter-clear]").click()
        page.wait_for_function("() => document.querySelectorAll(\"[data-project-kind='project']\").length === 12")
        page.locator("[data-filter-search]").fill("zzz-no-match")
        page.get_by_role("button", name="Search", exact=True).click()
        page.wait_for_selector("[data-library-no-match]")
        assert "No projects match" in page.inner_text("[data-library-no-match]")
        page.locator("[data-filter-clear]").click()
        page.wait_for_function("() => document.querySelectorAll(\"[data-project-kind='project']\").length === 12")

        # status and the real Run metadata; opening a project reaches its workspace
        target = page.locator("[data-project-kind='project']").first.get_attribute("data-project-code")
        page.locator(f"[data-project-code='{target}'] [data-open-project]").click()
        page.wait_for_selector("[data-workspace-status='true']")
        assert target in page.url
        assert errors == [], errors
    finally:
        context.close()


def check_results_analysis_navigation_and_back_forward(seeded):
    context, page, record, errors, base = seeded
    run_canonical(context, base, record.project_code)
    open_section(page, base, record.project_code, "overview")
    nav = page.locator(".fm-nav a")
    labels = [nav.nth(i).inner_text().replace("\n", " ") for i in range(nav.count())]
    assert [label.split(" ", 1)[1] for label in labels] == [
        "Inputs", "Statements", "Financing", "Results", "Scenarios", "Analysis", "Model checks", "Trust"]
    # real in-page links, no design-harness routes
    assert all((nav.nth(i).get_attribute("href") or "").startswith("#") for i in range(nav.count()))
    page.locator(".fm-nav a", has_text="Results").click()
    page.wait_for_selector("[data-results-view]")
    assert page.locator(".fm-nav a.active").inner_text().split("\n")[-1] == "Results"
    page.locator(".fm-nav a", has_text="Analysis").click()
    page.wait_for_selector("[data-analysis-view]")
    assert page.locator("[data-feature-gate]").count() == 0, "Analysis is a live view, not a gated placeholder"
    assert page.locator(".fm-nav a[aria-current='page']").inner_text().split("\n")[-1] == "Analysis"
    page.go_back()
    page.wait_for_selector("[data-results-view]")
    page.go_forward()
    page.wait_for_selector("[data-analysis-view]")
    # the breadcrumb / library links are real routes
    assert page.locator(".fm-workspace-bar a").first.get_attribute("href") == "/v2/model-react/"
    assert errors == [], errors


def check_responsive_layout_has_no_page_level_horizontal_overflow(browser, react_enabled, name, viewport):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = f"wf1-resp-{name}"
    record = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference",
                                             requested_name=f"Resp {name}", capacity_mw=12.0)
    context = browser.new_context(viewport=viewport)
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                          "url": react_enabled}])
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        run_canonical(context, react_enabled, record.project_code)
        page.goto(f"{react_enabled}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "library overflows"
        shot(page, f"{name}-library")
        for section in ("overview", "statements", "results", "analysis"):
            open_section(page, react_enabled, record.project_code, section)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), \
                f"{section} overflows horizontally at {name}"
            shot(page, f"{name}-{section}")
        assert errors == [], errors
    finally:
        context.close()
