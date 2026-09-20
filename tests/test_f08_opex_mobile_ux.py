"""F08 — Model OPEX mobile/editable UX tests.

Audit finding (MINOR): the Workbook V2 OPEX sheet's custom-row form, add-row
form, and deactivate button used classes that had NO CSS rules at all — they
rendered as unstyled inline flow, overflowing narrow (390px) viewports — and
the sheet's fixed 23rem grid columns overflowed small screens.

The fix adds layout rules in the existing design language (mirroring the
CAPEX sheet's equivalent styles) plus a ≤640px collapse of the sheet grid to
Code | Description | Y1. These tests pin:

1. every v2-opex-* class used by the OPEX template has a CSS rule
   (the defect class is structurally closed);
2. the mobile collapse rules exist;
3. editable inputs keep accessible labels and HTMX wiring (no regression).
"""

from __future__ import annotations

import io
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "app" / "templates" / "v2" / "partials" / "sheet_opex.html"
CSS = REPO / "static" / "css" / "workbook_v2.css"

# Classes styled via element selectors rather than their own class rule —
# each also carries a sibling class that IS styled (e.g. v2-opex-proj-sticky-*).
_ELEMENT_STYLED = {
    "v2-opex-proj-td-code",
    "v2-opex-proj-td-name",
    "v2-opex-proj-td-year",
    "v2-opex-proj-th-code",
    "v2-opex-proj-th-name",
}


def _template_classes() -> set[str]:
    tpl = io.open(TEMPLATE, encoding="utf-8").read()
    classes: set[str] = set()
    for m in re.finditer(r'class="([^"]+)"', tpl):
        for c in m.group(1).split():
            if c.startswith("v2-opex-") and "{%" not in c:
                classes.add(c)
    return classes


def _mobile_blocks(css: str) -> list[str]:
    """Extract the body of every (max-width: 640px) media block."""
    blocks = []
    for m in re.finditer(r"@media \(max-width: 640px\)", css):
        depth = 0
        start = css.index("{", m.end())
        i = start
        while i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        blocks.append(css[start:i])
    return blocks


def test_every_opex_template_class_has_a_css_rule():
    css = io.open(CSS, encoding="utf-8").read()
    missing = sorted(
        c for c in _template_classes()
        if ("." + c) not in css and c not in _ELEMENT_STYLED
    )
    assert not missing, (
        f"OPEX template classes with no CSS rule (render unstyled): {missing}"
    )


def test_mobile_collapse_rules_exist():
    css = io.open(CSS, encoding="utf-8").read()
    blocks = _mobile_blocks(css)
    assert blocks, "a (max-width: 640px) media block must exist"
    for rule in (
        ".v2-opex-col-header",
        ".v2-opex-group-header",
        ".v2-opex-grand-total-row",
        "3rem 1fr 5rem",
    ):
        assert any(rule in b for b in blocks), (
            f"the mobile collapse block must style {rule}"
        )


def test_previously_unstyled_forms_now_have_layout_rules():
    css = io.open(CSS, encoding="utf-8").read()
    for cls in (
        ".v2-opex-custom-row",
        ".v2-opex-custom-row-form",
        ".v2-opex-add-row-form",
        ".v2-opex-deactivate-btn",
        ".v2-opex-custom-save-btn",
        ".v2-opex-add-btn",
    ):
        assert cls + " {" in css or cls + " {" in css.replace("\r", ""), (
            f"{cls} must have a layout rule"
        )
    # the custom-row form must wrap instead of overflowing on narrow screens
    form_block = css.split(".v2-opex-custom-row-form {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in form_block


def test_editable_inputs_keep_accessible_labels_and_htmx():
    tpl = io.open(TEMPLATE, encoding="utf-8").read()
    # every editable OPEX input carries an aria-label
    for name in ("label", "amount_keur", "inflation_pct", "notes"):
        inputs = re.findall(r'<input[^>]*name="' + name + r'"[^>]*>', tpl)
        assert inputs, f"input {name} must exist"
        for tag in inputs:
            assert 'aria-label="' in tag, f"input {name} must keep its aria-label"
    # custom-row lifecycle still routes through HTMX endpoints
    assert 'hx-post="/v2/opex/line/update"' in tpl
    assert 'hx-post="/v2/opex/line/add"' in tpl
    assert 'hx-post="/v2/opex/line/deactivate"' in tpl


# ── Automated real-browser layout regression ─────────────────────────────────
#
# These tests use the actual workbook_v2.css (inlined) with a representative
# OPEX fixture matching the exact classes from sheet_opex.html.  Playwright
# renders them in a headed-less Chromium and asserts overflow metrics.
#
# Skip gracefully when playwright is not importable (keeps CI working in
# environments without it); the pre-installed Chromium binary is used.
# ─────────────────────────────────────────────────────────────────────────────

_CHROMIUM = "/opt/pw-browsers/chromium"
_PW_ARGS = ["--no-sandbox", "--disable-setuid-sandbox"]


def _build_opex_fixture_html() -> str:
    """Minimal HTML that exercises the OPEX grid classes using the real CSS."""
    css = CSS.read_text(encoding="utf-8")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<style>
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 0; }}
{css}
</style>
</head>
<body>
<div id="opex-sheet" style="max-width:100%;overflow-x:hidden;">

  <!-- Column header — 5-column grid on desktop, collapses to 3 on mobile -->
  <div class="v2-opex-col-header">
    <span class="v2-opex-col-code">Code</span>
    <span class="v2-opex-col-desc">Description</span>
    <span class="v2-opex-col-y1">Y1 kEUR</span>
    <span class="v2-opex-col-escl">Escl %</span>
    <span class="v2-opex-col-status">Status</span>
  </div>

  <!-- Group with open details — includes custom-row and add-row forms -->
  <details class="v2-opex-group" open>
    <summary class="v2-opex-group-header">
      <span class="v2-opex-col-code">B.01</span>
      <span class="v2-opex-col-desc">Operations &amp; Maintenance</span>
      <span class="v2-opex-subtotal v2-opex-col-y1">1,200</span>
      <span class="v2-opex-col-escl">2.0 %</span>
      <span class="v2-opex-col-status"><span class="v2-opex-badge v2-opex-badge-engine">ENGINE</span></span>
    </summary>
    <div class="v2-opex-group-body">
      <!-- Read-only row -->
      <div class="v2-opex-ro-row v2-opex-line-row" data-testid="opex-ro-row">
        <span class="v2-opex-line-code">B.01.01</span>
        <span class="v2-opex-line-name">Fixed O&amp;M</span>
        <span class="v2-opex-line-y1">600</span>
        <span class="v2-opex-line-escl">2.0 %</span>
        <span class="v2-opex-line-notes"></span>
      </div>
      <!-- Custom row with edit form -->
      <div class="v2-opex-custom-row" data-testid="opex-custom-row">
        <form class="v2-opex-custom-row-form" data-testid="opex-custom-row-form"
              hx-post="/v2/opex/line/update" hx-swap="outerHTML">
          <input type="text" name="label" aria-label="Label"
                 class="v2-opex-custom-label" value="Insurance" inputmode="text"/>
          <input type="text" name="amount_keur" aria-label="Amount kEUR"
                 class="v2-opex-custom-amount" value="50" inputmode="decimal"/>
          <input type="text" name="inflation_pct" aria-label="Inflation %"
                 class="v2-opex-custom-inflation" value="2.0" inputmode="decimal"/>
          <input type="hidden" name="notes" aria-label="Notes" value=""/>
          <button type="submit" class="v2-opex-custom-save-btn">Save</button>
          <button type="button" class="v2-opex-deactivate-btn"
                  hx-post="/v2/opex/line/deactivate">Deactivate</button>
        </form>
      </div>
      <!-- Add-row form -->
      <form class="v2-opex-add-row-form" data-testid="opex-add-row-form"
            hx-post="/v2/opex/line/add" hx-swap="beforebegin">
        <input type="text" name="label" aria-label="New row label"
               class="v2-opex-custom-label" placeholder="Label" inputmode="text"/>
        <input type="text" name="amount_keur" aria-label="Amount kEUR"
               class="v2-opex-custom-amount" placeholder="0" inputmode="decimal"/>
        <input type="text" name="inflation_pct" aria-label="Inflation %"
               class="v2-opex-custom-inflation" placeholder="2.0" inputmode="decimal"/>
        <button type="submit" class="v2-opex-add-btn">+ Add</button>
      </form>
    </div>
  </details>

  <!-- KPI summary strip -->
  <div class="v2-opex-kpi-strip" data-testid="opex-kpi-strip">
    <div class="v2-opex-kpi-item">
      <span class="v2-opex-kpi-label">Total OPEX Y1</span>
      <span class="v2-opex-kpi-value">1,200 kEUR</span>
    </div>
  </div>

  <!-- Grand-total row -->
  <div class="v2-opex-grand-total-row" data-testid="opex-grand-total-row">
    <span class="v2-opex-col-code"></span>
    <span class="v2-opex-total-label-cell v2-opex-col-desc">Grand Total</span>
    <span class="v2-opex-col-y1 v2-opex-grand-total-amount">1,200</span>
    <span class="v2-opex-col-escl"></span>
    <span class="v2-opex-col-status"></span>
  </div>

  <!-- Year projection table — intentional local horizontal scroll -->
  <div class="v2-opex-projection-panel">
    <div style="overflow-x:auto;">
      <table class="v2-opex-proj-table v2-table">
        <thead><tr>
          <th class="v2-opex-proj-th-code">Code</th>
          <th class="v2-opex-proj-th-name">Group</th>
          <th>Y1</th><th>Y2</th><th>Y3</th><th>Y4</th><th>Y5</th>
          <th>Y6</th><th>Y7</th><th>Y8</th><th>Y9</th><th>Y10</th>
        </tr></thead>
        <tbody><tr>
          <td class="v2-opex-proj-td-code">B.01</td>
          <td class="v2-opex-proj-td-name">Operations</td>
          <td>600</td><td>612</td><td>624</td><td>637</td><td>649</td>
          <td>662</td><td>675</td><td>689</td><td>703</td><td>717</td>
        </tr></tbody>
      </table>
    </div>
  </div>

</div>
</body>
</html>"""


def _get_playwright():
    """Return sync_playwright entry-point or None if playwright is unavailable."""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def test_opex_390px_no_document_overflow():
    """At 390px the OPEX sheet must not cause horizontal document overflow."""
    sync_playwright = _get_playwright()
    if sync_playwright is None:
        import pytest
        pytest.skip("playwright not installed")
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

    html = _build_opex_fixture_html()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=_CHROMIUM,
            args=_PW_ARGS,
        )
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(html, wait_until="load")

        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        client_w = page.evaluate("document.documentElement.clientWidth")

        # Verify mobile collapse: escl/status columns hidden
        escl_visible = page.evaluate(
            "window.getComputedStyle(document.querySelector('.v2-opex-col-escl')).display !== 'none'"
        )
        status_visible = page.evaluate(
            "window.getComputedStyle(document.querySelector('.v2-opex-col-status')).display !== 'none'"
        )

        # Code, desc, Y1 must be in viewport
        code_el = page.locator(".v2-opex-col-code").first
        code_box = code_el.bounding_box()

        browser.close()

    assert scroll_w <= client_w, (
        f"390px: document overflows — scrollWidth={scroll_w} > clientWidth={client_w}"
    )
    assert not escl_visible, "390px: .v2-opex-col-escl must collapse (display:none)"
    assert not status_visible, "390px: .v2-opex-col-status must collapse (display:none)"
    assert code_box is not None and code_box["x"] >= 0, "Code column must be in viewport"


def test_opex_1280px_desktop_no_overflow_columns_visible():
    """At 1280px the OPEX sheet must not overflow and all 5 columns must be visible."""
    sync_playwright = _get_playwright()
    if sync_playwright is None:
        import pytest
        pytest.skip("playwright not installed")
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

    html = _build_opex_fixture_html()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=_CHROMIUM,
            args=_PW_ARGS,
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content(html, wait_until="load")

        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        client_w = page.evaluate("document.documentElement.clientWidth")

        # On desktop all 5 columns must be visible
        escl_visible = page.evaluate(
            "window.getComputedStyle(document.querySelector('.v2-opex-col-escl')).display !== 'none'"
        )
        status_visible = page.evaluate(
            "window.getComputedStyle(document.querySelector('.v2-opex-col-status')).display !== 'none'"
        )
        y1_visible = page.evaluate(
            "window.getComputedStyle(document.querySelector('.v2-opex-col-y1')).display !== 'none'"
        )

        browser.close()

    assert scroll_w <= client_w, (
        f"1280px: document overflows — scrollWidth={scroll_w} > clientWidth={client_w}"
    )
    assert escl_visible, "1280px: .v2-opex-col-escl must be visible on desktop"
    assert status_visible, "1280px: .v2-opex-col-status must be visible on desktop"
    assert y1_visible, "1280px: .v2-opex-col-y1 must be visible on desktop"


def test_opex_390px_editable_row_reachable():
    """At 390px add-row and custom-row form controls must be reachable (within viewport)."""
    sync_playwright = _get_playwright()
    if sync_playwright is None:
        import pytest
        pytest.skip("playwright not installed")
    import os
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

    html = _build_opex_fixture_html()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=_CHROMIUM,
            args=_PW_ARGS,
        )
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(html, wait_until="load")

        # Measure overall overflow first
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        client_w = page.evaluate("document.documentElement.clientWidth")

        # All form inputs must be within the 390px width (no right-overflow)
        add_form_box = page.locator("[data-testid='opex-add-row-form']").bounding_box()
        custom_form_box = page.locator("[data-testid='opex-custom-row-form']").bounding_box()
        add_btn_box = page.locator(".v2-opex-add-btn").bounding_box()

        browser.close()

    assert scroll_w <= client_w, (
        f"390px (editable row): document overflows scrollWidth={scroll_w} > clientWidth={client_w}"
    )
    if add_form_box:
        assert add_form_box["x"] + add_form_box["width"] <= client_w + 1, (
            f"Add-row form overflows viewport at 390px: right edge={add_form_box['x'] + add_form_box['width']}"
        )
    if custom_form_box:
        assert custom_form_box["x"] + custom_form_box["width"] <= client_w + 1, (
            f"Custom-row form overflows viewport at 390px: right edge={custom_form_box['x'] + custom_form_box['width']}"
        )
    assert add_btn_box is not None, "Add button must be rendered"
    assert add_btn_box["x"] >= 0, "Add button must be within viewport (not left-clipped)"
