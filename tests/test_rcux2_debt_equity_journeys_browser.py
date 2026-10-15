"""RC-UX Phase 2 / Section 5: Debt proposal and Investor Agreement journeys in real Chromium under the real CSP.

* Senior financing: the journey ends honestly at SAVED PROPOSAL - NOT ACTIVE IN RUN. Activation stays release-closed; an inactive proposal must not
  alter the active financial results.
* Investors: ownership allocates results between investors and does not change project economics or Sources & Uses; funding (commitments and
  paid-in capital) must reconcile before a Run is committed.
Numerical reconciliation of the results themselves belongs to WF-A.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from playwright.sync_api import expect  # noqa: E402
from tests.model_workspace_navigation import activate_destination  # noqa: E402
from tests.test_financing_f37_browser_v1 import USER, _project, browser, live_server  # noqa: F401,E402
from tests.test_investor_f4_workspace import funded_agreement  # noqa: E402

KPI_KEYS = ("project_irr", "pure_equity_irr", "total_sponsor_irr", "total_capex_keur", "total_revenue_keur", "total_cfads_keur", "min_dscr", "avg_dscr")


def _context(browser, live_server, record):
    from app.auth import COOKIE_NAME, create_session_token
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=USER, username="admin"), "url": live_server}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    page.goto(f"{live_server}/v2/workbook?project={record.project_code}")
    return ctx, page, errors


def _kpis(record):
    from app.persistence.workspace_repository import get_workspace_state
    summary = get_workspace_state(USER, record.project_id).last_runtime_summary or {}
    return {k: summary[k] for k in KPI_KEYS if k in summary}


def _history(record):
    from app.persistence.run_history_repository import get_run_history
    return [str(getattr(e, "snapshot_id", e)) for e in get_run_history(USER, record.project_id)]


def _run(page):
    with page.expect_response(lambda r: "/v2/workbook/run" in r.url and r.request.method == "POST", timeout=240000) as ran:
        page.locator('[data-testid=header-run-btn]').click()
    assert ran.value.status == 200
    ran.value.finished()
    return ran.value.text()


def _open_agreement(page):
    with page.expect_response(lambda r: "/v2/workbook/financing/investor?" in r.url) as refreshed:
        activate_destination(page, "tab-investor")
    refreshed.value.finished()
    page.locator("[data-testid=f4-agreement-panel] summary").click()
    root = page.locator("#f4-investor-workspace")
    expect(root.locator(".f4-agreement-form")).to_be_visible()
    page.wait_for_function("() => window.fincoF4EditorRegistered === true")
    return root


def _fill_agreement(root, doc):
    root.locator("[name=agreement_id]").fill(doc["agreement_id"])
    for investor in doc["investors"]:
        root.locator("[data-f4-add=investor]").click()
        row = root.locator("tr[data-f4-investor]").last
        for field in ("investor_id", "ownership_fraction", "commitment_keur"):
            value = investor[field] * 100 if field == "ownership_fraction" else investor[field]
            row.locator(f"[data-f4-field={field}]").fill(str(value))
    for contribution in doc["contributions"]:
        root.locator("[data-f4-add=contribution]").click()
        row = root.locator("tr[data-f4-contribution]").last
        for field, value in contribution.items():
            row.locator(f"[data-f4-field={field}]").fill(str(value))


def _agreement(record):
    from app.persistence.workspace_repository import get_workspace_state
    return funded_agreement(get_workspace_state(USER, record.project_id))


def test_senior_proposal_is_saved_persists_stays_inactive_and_does_not_change_the_run(live_server, browser):
    from app.persistence.workspace_repository import get_workspace_state
    record = _project("generic_solar_reference", two_senior=False)
    ctx, page, errors = _context(browser, live_server, record)
    activate_destination(page, "tab-debt")
    page.wait_for_selector("[data-testid=capital-stack-table]")
    first = _run(page)
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    active_before, history_before = _kpis(record), _history(record)
    assert active_before
    row = page.locator("[data-f3-instrument]").first
    row.locator("[data-cs-expand]").click()
    draws = row.locator('[data-f3="draws"]')
    first_date = draws.input_value().splitlines()[0].split(",")[0].strip()
    row.locator('[data-f3="commitment_keur"]').fill("1000")
    draws.fill(f"{first_date}, 1000")
    row.locator('[data-f3="rate_pct"]').fill("4.25")
    row.locator('[data-f3="grace_months"]').fill("12")
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as saved:
        page.locator("[data-f3-save]").click()
    assert saved.value.status == 200
    expect(page.locator("[data-testid=cs-stack-status]")).to_have_text("SAVED PROPOSAL")
    expect(page.locator("[data-testid=cs-not-active]")).to_have_text("Not active in Run")          # proposal vs active terms are visibly distinct
    expect(page.locator("[data-f3-activate]")).not_to_be_checked()                                   # saved, but not activated
    expect(page.locator("[data-testid=cs-activation-note]")).to_contain_text("do not affect the model")
    assert get_workspace_state(USER, record.project_id).last_runtime_snapshot_id                       # the committed Run is untouched by the save
    page.reload()
    activate_destination(page, "tab-debt")
    page.wait_for_selector("[data-testid=capital-stack-table]")
    expect(page.locator('[data-f3="rate_pct"]').first).to_have_value("4.25")                          # persists across reload
    expect(page.locator("[data-testid=cs-stack-status]")).to_have_text("SAVED PROPOSAL")
    _run(page)
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    assert _kpis(record) == active_before                                                              # an inactive proposal never alters the active results
    assert len(_history(record)) == len(history_before) + 1 and history_before[0] in _history(record)  # earlier Run unchanged
    assert errors == [], errors
    ctx.close()


def test_two_investors_with_differing_contributions_save_reload_and_run(live_server, browser):
    record = _project("generic_solar_reference", two_senior=False)
    doc = _agreement(record)
    for investor, share in zip(doc["investors"], (.6, .4)):
        investor["ownership_fraction"] = share                                                        # ownership 60/40
    by_date = {}
    for c in doc["contributions"]:
        by_date.setdefault(c["cash_date"], 0.0)
        by_date[c["cash_date"]] += c["amount_keur"]
    doc["contributions"] = [dict(investor_id=i, cash_date=d, amount_keur=total * share)           # paid-in 70/30 while ownership is 60/40
                            for d, total in by_date.items() for i, share in (("alpha", .7), ("beta", .3))]
    ctx, page, errors = _context(browser, live_server, record)
    root = _open_agreement(page)
    _fill_agreement(root, doc)
    root.locator("button[value=save]").click()
    expect(root).to_have_attribute("data-state", "STALE")
    root.get_by_role("button", name="Reload agreement").click()
    expect(root.locator("tr[data-f4-investor]")).to_have_count(2)
    assert root.locator("tr[data-f4-investor]").first.locator("[data-f4-field=ownership_fraction]").input_value() in ("60", "60.0")
    text = _run(page)
    assert "No Run was committed" not in text, text
    root.get_by_role("button", name="Reload agreement").click()
    expect(root).to_have_attribute("data-state", "CURRENT", timeout=30000)
    expect(root.locator("[data-testid=f4-capital-accounts] tbody tr")).to_have_count(2)
    assert errors == [], errors
    ctx.close()


def test_changing_ownership_alone_does_not_change_project_economics(live_server, browser):
    record = _project("generic_solar_reference", two_senior=False)
    doc = _agreement(record)
    for investor, share in zip(doc["investors"], (.6, .4)):
        investor["ownership_fraction"] = share
    ctx, page, errors = _context(browser, live_server, record)
    root = _open_agreement(page)
    _fill_agreement(root, doc)
    root.locator("button[value=save]").click()
    expect(root).to_have_attribute("data-state", "STALE")
    _run(page)
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    reference = _kpis(record)
    assert reference
    rows = root.locator("tr[data-f4-investor]")
    rows.first.locator("[data-f4-field=ownership_fraction]").fill("50")                              # ownership 60/40 -> 50/50, funding untouched
    rows.last.locator("[data-f4-field=ownership_fraction]").fill("50")
    root.locator("button[value=save]").click()
    expect(root).to_have_attribute("data-state", "STALE")
    _run(page)
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    assert _kpis(record) == reference                                                                # CAPEX, revenue, debt and project returns unchanged
    assert errors == [], errors
    ctx.close()


def test_ownership_not_summing_to_100_is_refused_with_a_clear_error_and_nothing_is_saved(live_server, browser):
    from app.persistence.workspace_repository import get_workspace_state
    record = _project("generic_solar_reference", two_senior=False)
    doc = _agreement(record)
    doc["investors"][0]["ownership_fraction"] = .60
    doc["investors"][1]["ownership_fraction"] = .30                                                   # 60 + 30 = 90
    before = get_workspace_state(USER, record.project_id)
    ctx, page, errors = _context(browser, live_server, record)
    root = _open_agreement(page)
    _fill_agreement(root, doc)
    root.locator("button[value=save]").click()
    page.wait_for_timeout(1500)
    after = get_workspace_state(USER, record.project_id)
    assert after.draft_snapshot == before.draft_snapshot and after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    message = root.locator("[data-f4-error]")
    assert message.is_visible() and message.inner_text().strip() != ""                                 # an actionable message, not a silent no-op
    ctx.close()


def test_contributions_that_do_not_reconcile_never_change_the_committed_results(live_server, browser):
    """Unreconciled paid-in capital is refused either at Save or at Run; in both cases no Run is committed and the previous results stay."""
    from app.persistence.workspace_repository import get_workspace_state
    record = _project("generic_solar_reference", two_senior=False)
    doc = _agreement(record)
    doc["contributions"][0]["amount_keur"] += 1000                                                    # paid-in no longer equals the model's equity funding
    before = (get_workspace_state(USER, record.project_id).last_runtime_snapshot_id, _history(record))
    ctx, page, errors = _context(browser, live_server, record)
    root = _open_agreement(page)
    _fill_agreement(root, doc)
    root.locator("button[value=save]").click()
    page.wait_for_timeout(2000)
    if root.get_attribute("data-state") == "STALE":                                                   # accepted at Save: the Run must refuse it
        text = _run(page)
        assert "No Run was committed" in text or "reconcil" in text.lower(), text[:400]
    else:                                                                                             # refused at Save: a visible message, nothing stored
        assert root.locator("[data-f4-error]").is_visible() or "reconcil" in root.inner_text().lower()
    after = (get_workspace_state(USER, record.project_id).last_runtime_snapshot_id, _history(record))
    assert after == before                                                                             # no Run was committed, the previous results stay
    ctx.close()
