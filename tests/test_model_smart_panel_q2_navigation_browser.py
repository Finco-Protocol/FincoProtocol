"""Q2 Correction B — Explore <-> workbook navigation behaviour in a real browser engine.

Renders the REAL panel template and loads the REAL ``model_smart_panel_v2.js`` into a
synthetic workbook whose register paths deliberately differ from field ids.  The established
navigation owner (``v2FieldValidationUx.jump``) is replaced by a recorder that moves focus the
way the real one does (activates the owning tab, focuses the input), so the focus side effect
that previously could overwrite the return origin is exercised.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright")
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from app.v2.smart_panel_projection import build_smart_panel_projection

REPO = Path(__file__).resolve().parents[1]
JS = (REPO / "static/js/model_smart_panel_v2.js").read_text()

FIELDS = [  # register path != field id, on purpose
    {"path": "technical.operating_hours_p50", "label": "P50 hours", "section": "T", "value": "2100", "unit": "h/yr", "source": "USER_INPUT"},
    {"path": "debt.margin", "label": "Margin", "section": "D", "value": "2.1", "unit": "%", "source": "USER_INPUT"},
    {"path": "orphan.path", "label": "No row", "section": "X", "value": "1", "unit": "", "source": "USER_INPUT"},
    {"path": "dup.path", "label": "Dup", "section": "X", "value": "1", "unit": "", "source": "USER_INPUT"},
]


def _panel_html():
    proj = build_smart_panel_projection(
        trust_pack=None, runtime_state="NOT_RUN", has_runtime=False, project_key="",
        assumption_register_view={"available": True, "entry_count": len(FIELDS), "rows": FIELDS})
    env = Environment(loader=FileSystemLoader(str(REPO / "app/templates/v2")), autoescape=select_autoescape(["html"]))
    return env.get_template("partials/_model_smart_panel.html").render({"smart_panel": proj})


def _rows():
    return """
<section id="panel-a" class="v2-sheet-panel"><div class="v2-field-row v2-field-editable" data-field-id="project_setup.technical.p50_hours" data-register-path="technical.operating_hours_p50" data-field-label="P50"><input type="text" style="width:120px" class="v2-field-input" id="in-p50"></div>
<div class="v2-field-row v2-field-editable" data-field-id="project_setup.technical.free" data-field-label="Free"><input type="text" style="width:120px" class="v2-field-input" id="in-free"></div></section>
<section id="panel-b" class="v2-sheet-panel" hidden><div class="v2-field-row v2-field-editable" data-field-id="debt.senior.margin_pct" data-register-path="debt.margin" data-field-label="Margin"><input type="text" style="width:120px" class="v2-field-input" id="in-margin"></div>
<div class="v2-field-row" data-field-id="dup.one" data-register-path="dup.path"><input type="text" style="width:120px" class="v2-field-input" id="in-dup1"></div>
<div class="v2-field-row" data-field-id="dup.two" data-register-path="dup.path"><input type="text" style="width:120px" class="v2-field-input" id="in-dup2"></div></section>"""


def _page_html():
    return f"""<!doctype html><html><body>
<div id="v2-sheet-tabs"><button role="tab" id="tab-a" class="v2-tab" aria-controls="panel-a" aria-selected="true">A</button>
<button role="tab" id="tab-b" class="v2-tab" aria-controls="panel-b" aria-selected="false">B</button></div>
<div id="rows">{_rows()}</div>
<aside id="oob">{_panel_html()}</aside>
<script>
window.__jumps = [];
window.v2FieldValidationUx = {{ jump: function (id) {{
  window.__jumps.push(id);
  var row = Array.prototype.find.call(document.querySelectorAll('.v2-field-row[data-field-id]'), function (r) {{ return r.getAttribute('data-field-id') === id; }});
  if (!row) return false;
  var panel = row.closest('.v2-sheet-panel');
  if (panel.hidden) document.querySelector('[aria-controls="' + panel.id + '"]').click();
  row.querySelector('input').focus();
  return true; }} }};
document.addEventListener('click', function (e) {{
  var t = e.target.closest('#v2-sheet-tabs [role=tab]'); if (!t) return;
  document.querySelectorAll('#v2-sheet-tabs [role=tab]').forEach(function (x) {{ x.setAttribute('aria-selected', x === t ? 'true' : 'false'); }});
  document.querySelectorAll('.v2-sheet-panel').forEach(function (p) {{ p.hidden = p.id !== t.getAttribute('aria-controls'); }});
}});
document.addEventListener('click', function (e) {{
  var b = e.target.closest('[data-jump-field]'); if (!b || b.disabled) return;
  window.v2FieldValidationUx.jump(b.getAttribute('data-jump-field'));
}});
</script>
<script id="sp">{JS}</script>
</body></html>"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(args=["--no-sandbox"])
        except Exception:
            import glob
            found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
            if not found:  # pragma: no cover - environment without a browser
                pytest.skip("chromium unavailable")
            b = pw.chromium.launch(executable_path=found[-1], args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture
def fresh(browser):
    # A new page per test: set_content() reuses the window, which would keep the one-shot guard.
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.set_default_timeout(5000)
    pg.set_content(_page_html())
    yield pg
    pg.close()


def _select(page, value):
    page.click('[data-sp-mode="inspector"]')
    page.select_option("#v2-sp-inspect-select", value)


def test_explore_go_to_field_uses_workbook_field_id_and_focuses_correct_input(fresh):
    _select(fresh, "f:debt.margin")
    btn = fresh.locator("[data-sp-inspector-result] [data-jump-field]")
    assert btn.get_attribute("data-jump-field") == "debt.senior.margin_pct"
    btn.click()
    assert fresh.evaluate("window.__jumps") == ["debt.senior.margin_pct"]
    assert fresh.evaluate("document.activeElement.id") == "in-margin"
    assert fresh.evaluate("document.getElementById('panel-b').hidden") is False
    assert not fresh.errors


def test_return_navigation_restores_origin_tab_and_field(fresh):
    fresh.focus("#in-p50")  # origin: tab A, field p50 (mapped, so Explore also selects it)
    _select(fresh, "f:debt.margin")
    fresh.locator("[data-sp-inspector-result] [data-jump-field]").click()
    assert fresh.evaluate("document.activeElement.id") == "in-margin"
    back = fresh.locator("[data-sp-inspector-result] [data-sp-return]")
    assert back.get_attribute("data-sp-return") == "tab-a", "jump focus must not overwrite the return origin"
    back.click()
    assert fresh.evaluate("document.getElementById('tab-a').getAttribute('aria-selected')") == "true"
    assert fresh.evaluate("window.__jumps.slice(-1)[0]") == "project_setup.technical.p50_hours"
    assert fresh.evaluate("document.activeElement.id") == "in-p50"


def test_sheet_field_focus_selects_matching_explore_assumption(fresh):
    fresh.click('[data-sp-mode="inspector"]')
    fresh.focus("#in-p50")
    assert fresh.input_value("#v2-sp-inspect-select") == "f:technical.operating_hours_p50"
    text = fresh.inner_text("[data-sp-inspector-result]")
    assert "technical.operating_hours_p50" in text and "2100" in text


def test_unmapped_row_focus_does_not_change_selection(fresh):
    fresh.click('[data-sp-mode="inspector"]')
    fresh.focus("#in-p50")
    fresh.focus("#in-free")
    assert fresh.input_value("#v2-sp-inspect-select") == "f:technical.operating_hours_p50"


def test_missing_row_fails_closed_with_disabled_jump(fresh):
    _select(fresh, "f:orphan.path")
    assert fresh.locator("[data-sp-inspector-result] [data-jump-field]").count() == 0
    dis = fresh.locator("[data-sp-inspector-result] button:disabled")
    assert dis.count() == 1 and "UNAVAILABLE" in dis.inner_text()
    assert "no proven workbook row mapping" in fresh.inner_text("[data-sp-inspector-result]")
    assert fresh.evaluate("window.__jumps") == []


def test_ambiguous_mapping_fails_closed(fresh):
    _select(fresh, "f:dup.path")
    assert fresh.locator("[data-sp-inspector-result] [data-jump-field]").count() == 0
    assert "ambiguous" in fresh.inner_text("[data-sp-inspector-result]")
    fresh.focus("#in-dup1")  # ambiguous row focus must not retarget Explore
    assert fresh.input_value("#v2-sp-inspect-select") == "f:dup.path"
    assert fresh.evaluate("window.__jumps") == []


def test_htmx_swaps_keep_mapping_and_do_not_duplicate_handlers(fresh):
    _select(fresh, "f:debt.margin")
    # replace the rows (HTMX sheet swap) and the panel (OOB swap), then re-run the script include
    fresh.evaluate("""() => {
      document.getElementById('rows').innerHTML = document.getElementById('rows').innerHTML;
      var oob = document.getElementById('oob'); oob.innerHTML = oob.innerHTML;
      document.dispatchEvent(new Event('htmx:afterSwap')); document.dispatchEvent(new Event('htmx:afterSettle'));
      var s = document.createElement('script'); s.textContent = document.getElementById('sp').textContent; document.body.appendChild(s);
    }""")
    assert fresh.evaluate("document.querySelector('[data-sp-mode=inspector]').getAttribute('aria-selected')") == "true", "mode retained across OOB"
    _select(fresh, "f:debt.margin")
    fresh.locator("[data-sp-inspector-result] [data-jump-field]").click()
    assert fresh.evaluate("window.__jumps") == ["debt.senior.margin_pct"], "exactly one jump per click (no duplicate listeners)"
    fresh.locator("[data-sp-inspector-result] [data-sp-return]").click()
    assert fresh.evaluate("window.__jumps.length") == 1, "no origin field recorded, so return performs no extra jump"
    assert not fresh.errors
