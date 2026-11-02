"""PR-U1 real-Chromium acceptance bodies: one Inputs overview, one CAPEX workbench, one OPEX workbench (synthetic Solar / Wind only).

Not collected by pytest: ``tests/u1_browser_role.py`` supplies the fixtures (like the WF-06B role). No private workbook name, cell address or
vendor name appears here; amounts are synthetic. Screenshots: ``$U1_SCREENSHOT_DIR``.
"""
from __future__ import annotations

import os
import re

from tests.model_react_mvp_acceptance import session as vertical_session
from tests.model_react_overnight_b_acceptance import horizontal_overflow, settle_inputs
from tests.model_react_wf1_browser_acceptance import open_section, run_canonical

SHOTS = os.environ.get("U1_SCREENSHOT_DIR", "")
VIEWPORTS = ((1440, 900), (1280, 800), (768, 1024), (390, 844), (320, 640))
CODE = re.compile(r"\b[CB]\.\d{2}(?:\.\d{2}|\.U\d{3})?\b")
SIX_BASE = ("opex.lines.cleaning_materials", "opex.lines.security", "opex.lines.power_expenses",
            "opex.lines.audit_accounting_legal", "opex.lines.bank_fees", "opex.lines.environmental_social")
MONEY_FIELD = re.compile(r"^(capex\.|opex\.)")


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"u1-{name}.png"), full_page=False)


def _costlines(context, base, code, sheet):
    r = context.request.get(f"{base}/v2/model-react/costlines?sheet={sheet}&project={code}")
    assert r.ok, r.text()[:200]
    return r.json()


def _opex_projection(context, base, code):
    r = context.request.get(f"{base}/v2/model-react/opex-projection?project={code}")
    assert r.ok, r.text()[:200]
    return r.json()


def _goto(page, base, code, hash_):
    page.goto(f"{base}/v2/model-react/{code}#{hash_}")
    page.reload()
    page.wait_for_selector("[data-react-workspace-version]", timeout=60000)


def _wait_cards(page):
    page.wait_for_function("() => { const c = document.querySelector(\"[data-ci-card-total='capex']\"); const o = document.querySelector(\"[data-ci-card-total='opex']\"); "
                           "return c && c.dataset.exact && o && !/…/.test(o.innerText); }", timeout=60000)


def _bench(page, sheet, view="lines"):
    page.wait_for_selector(f"[data-cost-workbench='{sheet}'][data-cost-view='{view}']", timeout=60000)
    if view == "lines":
        page.wait_for_selector(f"[data-cost-grid='{sheet}'] [data-saved-total]", timeout=60000)


def check_A01_one_editable_money_authority_and_no_codes(browser, base, kind):
    """A01 + A31: no cost input outside its workbench; no C./B. code on any cost surface; the six OPEX base fields only in the OPEX workbench."""
    context, page, record, errors = vertical_session(browser, base, f"u1-a01-{kind}", kind)
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        _wait_cards(page)
        # the overview and the Assumptions grid carry no CAPEX / OPEX money cell at all
        cells = page.locator("[data-grid-cell]").evaluate_all("els => els.map(e => e.dataset.gridCell)")
        assert cells and not [c for c in cells if MONEY_FIELD.match(c)], [c for c in cells if MONEY_FIELD.match(c)]
        assert page.locator("[data-cost-grid]").count() == 0 and page.locator("[data-base-input]").count() == 0
        assert not CODE.search(page.locator("body").inner_text()), CODE.search(page.locator("body").inner_text())
        shot(page, f"{kind}-overview")
        # CAPEX workbench: amounts only through the cost-line grid; no code anywhere in any of its views
        _goto(page, base, record.project_code, "inputs/capex")
        _bench(page, "capex")
        assert page.locator("[data-base-input]").count() == 0 and page.locator("[data-cost-grid='capex'] input[data-c='1']").count() > 5
        assert not CODE.search(page.locator("[data-cost-workbench]").inner_text())
        _goto(page, base, record.project_code, "inputs/capex/monthly")
        _bench(page, "capex", "monthly")
        page.wait_for_selector("[data-capex-studio='ready']", timeout=60000)
        assert not CODE.search(page.locator("[data-cost-workbench]").inner_text())
        # OPEX workbench: the six base fields (and only they) are the first row of their group, with exactly their canonical field ids
        _goto(page, base, record.project_code, "inputs/opex")
        _bench(page, "opex")
        ids = page.locator("[data-base-input]").evaluate_all("els => els.map(e => e.dataset.baseInput)")
        assert sorted(ids) == sorted(SIX_BASE), ids
        assert not CODE.search(page.locator("[data-cost-workbench]").inner_text())
        first = page.locator("tr[data-group-row] + tr[data-base-row]").count()
        assert first == 6, "each base row is the FIRST row of its group"
        shot(page, f"{kind}-opex")
        _goto(page, base, record.project_code, "inputs/opex/years")
        _bench(page, "opex", "years")
        page.wait_for_selector("[data-opex-projection='ready']", timeout=60000)
        assert not CODE.search(page.locator("[data-cost-workbench]").inner_text())
        assert not errors, errors
    finally:
        context.close()


def check_A02_totals_agree_with_the_server_and_opex_includes_the_bases(browser, base, kind):
    """A02: card total == workbench saved total == projection.saved_total_keur (exact); the OPEX figure is the server's Year-1 (bases + lines)."""
    context, page, record, errors = vertical_session(browser, base, f"u1-a02-{kind}", kind)
    try:
        proj = _costlines(context, base, record.project_code, "capex")["projection"]
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        _wait_cards(page)
        card = page.locator("[data-ci-card-total='capex']")
        assert card.get_attribute("data-exact") == str(proj["saved_total_keur"])
        assert abs(float(card.inner_text().split()[0].replace(",", "")) - proj["saved_total_keur"]) <= 0.5
        assert "calculated when you run the model" in page.locator("[data-ci-card='capex']").inner_text()
        opx = _opex_projection(context, base, record.project_code)
        y1 = opx["totals"]["excluding_contingency"][0]
        assert abs(float(page.locator("[data-ci-card-total='opex']").inner_text().split()[0].replace(",", "")) - y1) <= 0.5
        lines_only = _costlines(context, base, record.project_code, "opex")["projection"]["saved_total_keur"]
        assert y1 >= lines_only - 1e-6, "the OPEX figure is never the lines-only total"
        _goto(page, base, record.project_code, "inputs/capex")
        _bench(page, "capex")
        assert page.locator("[data-cost-grid='capex'] [data-saved-total]").get_attribute("data-exact") == str(proj["saved_total_keur"])
        assert not errors, errors
    finally:
        context.close()


def check_A14_opex_base_plus_line_is_one_group_one_save_and_reconciles(browser, base, kind):
    """A14 / D2: base 20 + added line 10 in one group, saved by ONE Save changes; the server projection and the Run agree; deactivate restores."""
    context, page, record, errors = vertical_session(browser, base, f"u1-a14-{kind}", kind)
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        _goto(page, base, record.project_code, "inputs/opex")
        _bench(page, "opex")
        group = "B.05"
        base_input = page.locator("[data-base-input='opex.lines.security']")
        before = next(r for r in _opex_projection(context, base, record.project_code)["rows"] if r["code"] == group)["values"][0]
        base_input.focus()
        base_input.fill("20")
        assert page.locator("[data-bar-save-all]").is_enabled() and page.locator("[data-unsaved-indicator]").count() == 1
        grid = page.locator("[data-cost-grid='opex']")
        grid.locator(f"[data-cost-group-add='{group}']").click()
        form = page.locator("[data-cost-line-manager='opex']")
        form.get_by_label("Line label").fill("U1 synthetic security line")
        form.get_by_label("Amount").fill("10")
        assert form.get_by_label("Inflation").input_value() == "0"                                  # D8: deterministic fallback, disclosed
        assert "no project-wide OPEX escalation" in page.locator("[data-inflation-default]").inner_text()
        form.get_by_label("Inflation").fill("2.5")
        form.locator("[data-cost-add='opex']").click()
        page.wait_for_selector("[data-cost-line-commands='opex'] [role='status']:has-text('verified in the fresh projection')", timeout=30000)
        line = next(l for l in _costlines(context, base, record.project_code, "opex")["lines"] if l["label"] == "U1 synthetic security line")
        assert str(line["amount_keur"]) in ("10", "10.0") and float(line["inflation_pct"]) == 2.5     # the user's exact value is saved
        runs_before = context.request.get(f"{base}/v2/model-react/runs?project={record.project_code}").json()["runs"]
        page.locator("[data-bar-save-all]").click()                                                  # the ONE save: base cell (+ any staged lines)
        page.wait_for_function("() => document.querySelector('[data-bar-save-all]')?.disabled", timeout=30000)
        after = next(r for r in _opex_projection(context, base, record.project_code)["rows"] if r["code"] == group)["values"][0]
        assert abs(after - 30.0) < 1e-6, (before, after)                                            # Y1 = base 20 + line 10 (inflation starts in year 2)
        row_texts = page.locator(f"tr[data-group-row='{group}'] ~ tr").all_inner_texts()[:2]
        assert "Group base amount" in row_texts[0] and "U1 synthetic security line" in " ".join(row_texts), row_texts
        assert context.request.get(f"{base}/v2/model-react/runs?project={record.project_code}").json()["runs"] == runs_before     # no Run
        # the Run folds it exactly once: the committed Run's OPEX security Y1 equals the projection
        run_canonical(context, base, record.project_code)
        ident = context.request.get(f"{base}/v2/model-react/runs?project={record.project_code}").json()["runs"]
        assert len(ident) == len(runs_before) + 1
        assert not errors, errors
    finally:
        context.close()


def check_decimals_default_to_zero_everywhere_and_exact_text_stays(browser, base, kind):
    """Owner correction: amounts show 0 decimals by default on every cost surface; focus shows the exact text; precision 2 shows two."""
    context, page, record, errors = vertical_session(browser, base, f"u1-dec-{kind}", kind)
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        _wait_cards(page)
        for sel in ("[data-ci-card-total='capex']", "[data-ci-card-total='opex']"):
            assert not re.search(r"\d\.\d", page.locator(sel).inner_text()), page.locator(sel).inner_text()
        for hash_, sheet, view in (("inputs/capex", "capex", "lines"), ("inputs/opex", "opex", "lines")):
            _goto(page, base, record.project_code, hash_)
            _bench(page, sheet)
            amounts = page.locator(f"[data-cost-grid='{sheet}'] input[data-c='1']").evaluate_all("els => els.map(e => [e.value, e.dataset.exact])")
            assert amounts and all(re.fullmatch(r"[\d,]+", v) for v, _ in amounts), [v for v, _ in amounts if not re.fullmatch(r"[\d,]+", v)][:5]
            inexact = next((e for v, e in amounts if "." in e.strip()), None)
            if inexact is not None:
                idx = next(i for i, (v, e) in enumerate(amounts) if e == inexact)
                cell = page.locator(f"[data-cost-grid='{sheet}'] input[data-c='1']").nth(idx)
                cell.focus()
                assert cell.input_value() == inexact                                                 # exact text on focus
            page.locator("select[aria-label='Report precision']").select_option("2")
            two = page.locator(f"[data-cost-grid='{sheet}'] input[data-c='1']").first.input_value()
            assert re.fullmatch(r"[\d,]+\.\d{2}", two), two
            page.locator("select[aria-label='Report precision']").select_option("0")
        _goto(page, base, record.project_code, "inputs/capex/monthly")
        page.wait_for_selector("[data-capex-studio='ready']", timeout=60000)
        amount_cells = page.locator("[data-capex-items] tbody tr td:nth-child(2)").all_inner_texts()
        assert amount_cells and all(re.fullmatch(r"[\d,]+|—", t.strip()) for t in amount_cells), amount_cells[:5]
        _goto(page, base, record.project_code, "inputs/opex/years")
        page.wait_for_selector("[data-opex-projection='ready']", timeout=60000)
        year_cells = page.locator("[data-opex-projection-table] tbody td.fm-num").all_inner_texts()
        assert year_cells and all(re.fullmatch(r"[\d,]+|—", t.strip()) for t in year_cells), year_cells[:5]
        assert not errors, errors
    finally:
        context.close()


def check_routes_aliases_back_forward_and_protected_read_only(browser, base):
    context, page, record, errors = vertical_session(browser, base, "u1-routes", "wind")
    try:
        for short, canonical in (("capex", "inputs/capex"), ("opex", "inputs/opex"), ("capex/monthly", "inputs/capex/monthly"), ("opex/years", "inputs/opex/years")):
            _goto(page, base, record.project_code, short)
            page.wait_for_selector("[data-cost-workbench]", timeout=60000)
            assert page.url.endswith(f"#{canonical}"), (short, page.url)
        _goto(page, base, record.project_code, "inputs")
        settle_inputs(page)
        page.locator("[data-open-workbench='capex']").click()
        _bench(page, "capex")
        page.locator("[data-cost-view-link='monthly']").click()
        page.wait_for_selector("[data-capex-studio='ready']", timeout=60000)
        page.go_back()
        _bench(page, "capex")
        page.go_back()
        page.wait_for_selector("[data-ci-cost-cards]", timeout=30000)
        # a staged edit survives Overview -> workbench -> Back
        cell = page.locator("[data-input-grid='canonical'] input.rx-grid-input:not([readonly])").first
        field = cell.get_attribute("data-grid-cell")
        original = cell.input_value()
        cell.fill(original + "1" if original else "1")
        page.locator("[data-open-workbench='opex']").click()
        _bench(page, "opex")
        assert page.locator("[data-unsaved-indicator]").count() == 1
        page.locator("[data-cw-back]").click()
        page.wait_for_selector(f"[data-grid-cell='{field}']", timeout=30000)
        assert page.locator(f"[data-grid-cell='{field}']").input_value() == (original + "1" if original else "1")
        assert not errors, errors
        # protected template: read-only in both workbenches
        from app.persistence.projects_repository import get_reference_by_template_source
        from app.services.project_library_service import ensure_reference_models
        ensure_reference_models()
        ref = get_reference_by_template_source("generic_solar_reference")
        for hash_, sheet in (("inputs/capex", "capex"), ("inputs/opex", "opex")):
            _goto(page, base, ref.project_code, hash_)
            page.wait_for_selector(f"[data-cost-grid='{sheet}']", timeout=60000)
            grid = page.locator(f"[data-cost-grid='{sheet}']")
            assert grid.locator("text=READ-ONLY TEMPLATE").count() >= 1
            assert grid.locator("[data-cost-addline]").is_disabled() and grid.locator("[data-base-input]:not([disabled])").count() == 0
            assert grid.locator("input[data-c='1']:not([disabled])").count() == 0
    finally:
        context.close()


def check_moved_studio_tools_are_reachable_in_their_new_homes(browser, base):
    context, page, record, errors = vertical_session(browser, base, "u1-moved", "solar")
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        assert page.locator("[data-input-studios], [data-studio-tab]").count() == 0, "the Studios container is gone"
        page.wait_for_selector("[data-revenue-assumptions='true'] [data-sheet-editor='revenue']", timeout=60000)      # Revenue assumptions in Revenue / PPA
        page.locator("[data-timing-section] > summary").click()                                                       # Construction timing in Project & Timeline
        page.wait_for_selector("[data-timing='ready']", timeout=60000)
        page.locator("[data-inputs-import] > summary").click()                                                        # Import: global Inputs section
        page.wait_for_selector("[data-import-workspace='true']", timeout=60000)
        _goto(page, base, record.project_code, "inputs/capex/monthly")                                                # CAPEX profile in CAPEX > Monthly schedule
        page.wait_for_selector("[data-capex-studio='ready']", timeout=60000)
        assert page.locator("[data-capex-studio]").count() == 1                                                       # one live instance
        assert "Model default" in page.locator("[data-capex-shape]").first.inner_text()                               # D6: the default is named honestly
        assert "Even" not in page.locator("[data-capex-shape]").first.inner_text().split("Model default")[0]
        page.locator("[data-cw-import]").click()                                                                      # Import also in the workbench toolbar
        page.wait_for_selector("[data-cw-import-panel] [data-import-workspace='true']", timeout=60000)
        _goto(page, base, record.project_code, "inputs/opex/years")
        page.wait_for_selector("[data-opex-projection='ready']", timeout=60000)                                      # OPEX Years
        page.locator("[data-save-scope-guide] > summary").count()
        assert not errors, errors
    finally:
        context.close()


def check_viewports_and_axe_on_the_new_pages(browser, base, axe_path):
    context, page, record, errors = vertical_session(browser, base, "u1-axe", "wind")
    bad = []
    try:
        page.add_init_script(path=axe_path)
        for hash_ in ("inputs", "inputs/capex", "inputs/capex/monthly", "inputs/opex", "inputs/opex/years"):
            for (w, h) in VIEWPORTS:
                page.set_viewport_size({"width": w, "height": h})
                _goto(page, base, record.project_code, hash_)
                if hash_ == "inputs":
                    settle_inputs(page); _wait_cards(page)
                elif hash_.endswith("capex") or hash_.endswith("opex"):
                    _bench(page, hash_.split("/")[1])
                page.wait_for_timeout(300)
                if horizontal_overflow(page):
                    bad.append((hash_, w, "page overflow"))
                out = page.evaluate("async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']})).violations.filter(v => v.impact === 'serious' || v.impact === 'critical').map(v => v.id)")
                if out:
                    bad.append((hash_, w, out))
                if w in (1440, 390):
                    shot(page, f"{hash_.replace('/', '_')}-{w}x{h}")
        assert not bad, bad
    finally:
        context.close()
