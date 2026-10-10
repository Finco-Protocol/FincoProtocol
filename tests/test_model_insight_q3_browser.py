"""Q3 UX behaviour in a real browser engine: the REAL panel template + REAL panel script over crafted,
Q1-derived evidence.  Complements the authenticated real-server acceptance (separate evidence)."""
from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("playwright")
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import test_model_quality_q1 as q1
from app.v2.insight_quality_projection import build_quality_insight
from app.v2.insight_scenario_projection import build_scenario_insight
from app.v2.smart_panel_projection import build_smart_panel_projection

REPO = Path(__file__).resolve().parents[1]
JS = (REPO / "static/js/model_smart_panel_v2.js").read_text()
CSS = (REPO / "static/css/model_smart_panel_v2.css").read_text()
runs = q1.runs


def _ws(payload):
    return SimpleNamespace(
        last_runtime_summary=q1.persisted_summary(payload), last_integrity_evidence=copy.deepcopy(payload["integrity_evidence"]),
        last_sponsor_schedule=copy.deepcopy(payload["sponsor_schedule"]), last_debt_schedule={},
        last_runtime_snapshot_id=q1.SNAP, last_runtime_composite_hash=q1.HASH,
        last_runtime_identity={"engine_version": "clean_senior_debt_v0"}, last_runtime_at=None,
        last_runtime_scenario_id=None, active_scenario_id=None, active_scenario_name="Base Case")


def _entry(payload, sid, snap, when):
    return SimpleNamespace(
        history_id=f"h-{snap}", runtime_snapshot_id=snap, ran_at=when, engine_version="clean_senior_debt_v0",
        last_runtime_scenario_id=sid, composite_hash="cd" * 32, last_runtime_identity={},
        runtime_summary=q1.persisted_summary(payload, snap=snap, scenario=sid), debt_schedule={},
        sponsor_schedule=copy.deepcopy(payload["sponsor_schedule"]), integrity_evidence=copy.deepcopy(payload["integrity_evidence"]))


def _panel_html(payload, pi, *, corrupt=False):
    ws = _ws(payload)
    if corrupt:
        from app.run_integrity.checks import _BS_KEYS
        row = next(r for r in ws.last_integrity_evidence["balance_sheet"]
                   if all(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) for k in _BS_KEYS))
        row["retained_earnings"] += 1000.0
        q1.redigest(ws.last_integrity_evidence)
    register = {"available": True, "entry_count": 1, "rows": [
        {"path": "financing.target_dscr", "label": "Target DSCR", "section": "FINANCING", "value": "1.2", "unit": "x", "source": "USER_INPUT"}]}
    proj = build_smart_panel_projection(trust_pack=None, runtime_state="CURRENT", has_runtime=True, project_key="",
                                        assumption_register_view=register)
    quality = build_quality_insight(ws, run_state="CURRENT", project_inputs=pi, active_scenario_id=None,
                                    scenario_name="Base Case", register_paths=["financing.target_dscr"])
    scenarios = [SimpleNamespace(scenario_id="b", scenario_name="Base Case", is_base_case=True),
                 SimpleNamespace(scenario_id="u", scenario_name="Upside", is_base_case=False),
                 SimpleNamespace(scenario_id="d", scenario_name="Downside", is_base_case=False)]
    history = [_entry(payload, None, q1.SNAP, "2026-10-08T12:00:00"), _entry(payload, "u", "S-U", "2026-10-10T12:00:00"),
               _entry(payload, "d", "S-D", "2026-10-09T12:00:00")]
    scn = build_scenario_insight(scenarios=scenarios, run_history=history, active_scenario_id="b", active_run_state="CURRENT",
                                 last_run_snapshot_id=q1.SNAP)
    proj = dataclasses.replace(proj, insight={"quality": quality, "scenarios": scn})
    env = Environment(loader=FileSystemLoader(str(REPO / "app/templates/v2")), autoescape=select_autoescape(["html"]))
    return env.get_template("partials/_model_smart_panel.html").render({"smart_panel": proj})


def _page(panel):
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}
body{{margin:0;font:14px sans-serif}}</style></head><body>
<div id="v2-sheet-tabs"><button role="tab" id="tab-overview" aria-selected="true">Overview</button></div>
<div id="oob">{panel}</div>
<script>window.__navs=[];document.addEventListener('click',function(e){{var b=e.target.closest('[data-nav-tab]');if(b)window.__navs.push(b.getAttribute('data-nav-tab'));}});</script>
<script id="sp">{JS}</script></body></html>"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(args=["--no-sandbox"])
        except Exception:
            import glob
            found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
            if not found:  # pragma: no cover
                pytest.skip("chromium unavailable")
            b = pw.chromium.launch(executable_path=found[-1], args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture(scope="module")
def html(runs):
    pi, payload = runs["solar"]
    return _panel_html(payload, pi)


@pytest.fixture(scope="module")
def html_failing(runs):
    pi, payload = runs["solar"]
    return _panel_html(payload, pi, corrupt=True)


def _open(browser, content, width=1280):
    pg = browser.new_page(viewport={"width": width, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.set_default_timeout(5000)
    pg.set_content(_page(content))
    return pg


def _expand(pg, check_id):
    """Open the check and every collapsed group around it (what a user does with the mouse or Enter)."""
    pg.evaluate("""id => { var d=document.querySelector('details[data-check-id="'+id+'"]');
                 for (var n=d; n && n.id!=='model-smart-panel'; n=n.parentElement) if (n.tagName==='DETAILS') n.open=true; }""", check_id)


def test_four_modes_keyboard_cycle_and_roving_tabindex(browser, html):
    pg = _open(browser, html)
    try:
        pg.focus('[data-sp-mode="solutions"]')
        seen = []
        for _ in range(4):
            pg.keyboard.press("ArrowRight")
            seen.append(pg.evaluate("document.querySelector('[data-sp-mode][aria-selected=true]').dataset.spMode"))
        assert seen == ["inspector", "changes", "scenarios", "solutions"]
        assert pg.eval_on_selector_all("[data-sp-mode]", "b=>b.map(x=>x.tabIndex)") == [0, -1, -1, -1]
        assert not pg.errors
    finally:
        pg.close()


def test_blocking_first_expanded_and_keyboard_expandable(browser, html_failing):
    pg = _open(browser, html_failing)
    try:
        order = pg.eval_on_selector_all("[data-q3-group]", "g=>g.map(x=>x.dataset.q3Group)")
        assert order[:3] == ["blocking", "issues", "gaps"]
        first = pg.locator('[data-q3-group="blocking"] details[data-q3-check]').first
        assert first.get_attribute("open") is not None and first.get_attribute("data-check-status") == "FAIL"
        gap = pg.locator('[data-q3-group="gaps"] details[data-q3-check]').first
        assert gap.get_attribute("open") is None
        gap.locator("summary").focus(); pg.keyboard.press("Enter")
        assert gap.get_attribute("open") is not None
        assert "UNAVAILABLE" in gap.inner_text() and "Reason" in gap.inner_text()
    finally:
        pg.close()


def test_check_links_to_explore_related_checks_and_back_to_findings(browser, html):
    pg = _open(browser, html)
    try:
        btn = pg.locator('details[data-check-id="QM-SD-004"] [data-sp-explore]')
        _expand(pg, "QM-SD-004")
        assert btn.get_attribute("data-sp-explore") == "f:financing.target_dscr"
        btn.click()
        assert pg.evaluate("document.querySelector('[data-sp-mode][aria-selected=true]').dataset.spMode") == "inspector"
        assert pg.input_value("#v2-sp-inspect-select") == "f:financing.target_dscr"
        related = pg.locator("[data-sp-focus-check]")
        texts = related.all_inner_texts()
        assert len(texts) >= 2 and any("QM-SD-004" in t for t in texts), texts
        pg.locator('[data-sp-focus-check="QM-SD-004"]').click()
        assert pg.evaluate("document.querySelector('[data-sp-mode][aria-selected=true]').dataset.spMode") == "solutions"
        assert pg.locator('details[data-check-id="QM-SD-004"]').get_attribute("open") is not None
        assert pg.evaluate("document.activeElement.parentElement.dataset.checkId") == "QM-SD-004"
        assert not pg.errors
    finally:
        pg.close()


def test_compare_picker_switches_table_and_survives_oob_swap(browser, html):
    pg = _open(browser, html)
    try:
        pg.click('[data-sp-mode="scenarios"]')
        visible = lambda: pg.eval_on_selector_all("[data-sp-compare-table]:not([hidden])", "t=>t.map(x=>x.dataset.spCompareTable)")
        first = pg.eval_on_selector_all("[data-sp-compare]", "b=>b.map(x=>x.dataset.spCompare)")
        assert len(first) == 2 and visible() == [first[0]]
        pg.click(f'[data-sp-compare="{first[1]}"]')
        assert visible() == [first[1]]
        assert pg.get_attribute(f'[data-sp-compare="{first[1]}"]', "aria-pressed") == "true"
        pg.evaluate("""() => { var o=document.getElementById('oob'); o.innerHTML=o.innerHTML;
                      document.dispatchEvent(new Event('htmx:afterSwap')); document.dispatchEvent(new Event('htmx:afterSettle')); }""")
        assert pg.evaluate("document.querySelector('[data-sp-mode][aria-selected=true]').dataset.spMode") == "scenarios"
        assert visible() == [first[1]], "chosen comparison survives the OOB replacement"
        assert pg.locator("[data-testid=q3-scenario-list] li").count() == 3
        assert "ACTIVE" in pg.locator("li.is-active").inner_text()
        assert not pg.errors
    finally:
        pg.close()


def test_scenarios_nav_is_navigation_only_and_no_duplicate_handlers(browser, html):
    pg = _open(browser, html)
    try:
        pg.evaluate("""() => { var s=document.createElement('script'); s.textContent=document.getElementById('sp').textContent; document.body.appendChild(s); }""")
        pg.click('[data-sp-mode="scenarios"]')
        pg.click('#v2-sp-view-scenarios [data-nav-tab="tab-scenarios"]')
        assert pg.evaluate("window.__navs") == ["tab-scenarios"]
        panel = pg.inner_html("#model-smart-panel")
        for forbidden in ("<form", "<input", "<textarea", "hx-post", "onclick", "contenteditable"):
            assert forbidden not in panel
        assert pg.locator("#model-smart-panel select").count() == 1
        pg.click('[data-sp-compare]')   # one click, one toggle, no exception
        assert not pg.errors
    finally:
        pg.close()


@pytest.mark.parametrize("mode", ["solutions", "scenarios"])
def test_mobile_390_has_no_horizontal_overflow(browser, html_failing, mode):
    pg = _open(browser, html_failing, width=390)
    try:
        pg.click(f'[data-sp-mode="{mode}"]')
        for d in pg.locator("details[data-q3-check]").all()[:6]:
            d.evaluate("e => e.open = true")
        assert pg.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
        assert all(pg.locator(f'[data-sp-mode="{m}"]').is_visible() for m in ("solutions", "inspector", "changes", "scenarios"))
    finally:
        pg.close()


def test_go_to_field_and_return_still_work_from_a_quality_check(browser, html):
    rows = """<section id="panel-a"><div class="v2-field-row" data-field-id="debt.senior.target_dscr" data-register-path="financing.target_dscr">
    <input type="text" style="width:100px" class="v2-field-input" id="in-t"></div></section>"""
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.set_default_timeout(5000)
        content = _page(html).replace('<div id="oob">', rows + '<div id="oob">')
        content = content.replace("<script id=\"sp\">", """<script>window.v2FieldValidationUx={jump:function(id){window.__jump=id;document.getElementById('in-t').focus();return true;}};
        document.addEventListener('click',function(e){var b=e.target.closest('[data-jump-field]');if(b&&!b.disabled)window.v2FieldValidationUx.jump(b.getAttribute('data-jump-field'));});</script><script id="sp">""")
        pg.set_content(content)
        _expand(pg, "QM-SD-004")
        pg.click('details[data-check-id="QM-SD-004"] [data-sp-explore]')
        go = pg.locator("[data-sp-inspector-result] [data-jump-field]")
        assert go.get_attribute("data-jump-field") == "debt.senior.target_dscr"
        go.click()
        assert pg.evaluate("window.__jump") == "debt.senior.target_dscr"
        assert pg.locator("[data-sp-return]").get_attribute("data-sp-return") == "tab-overview"
        assert not pg.errors
    finally:
        pg.close()
