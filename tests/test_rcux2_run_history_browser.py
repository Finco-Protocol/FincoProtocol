"""RC-UX Phase 2 / Section 6: Run History list, detail, compare and expanded compare in real Chromium under the real CSP.

Wide tables must scroll inside their own bounded, keyboard-reachable region and never widen the document; Run identities and the
CURRENT / STALE state must stay truthful; earlier Runs stay immutable.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_construction_timing_browser import Timing  # noqa: E402
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402

VIEWPORTS = [(1440, 900, "light"), (1366, 768, "light"), (390, 844, "light"), (390, 844, "dark")]


def _two_runs(live_server, browser, uid):
    t = Timing(live_server, browser, uid)
    t.run()
    t.open()
    t.dd("start").fill("2030-02-01")
    t.save()                                                                         # an input change, then a second committed Run
    t.page.wait_for_selector(".htmx-request", state="detached")
    t.run()
    return t


OFFENDERS = """() => { const W = window.innerWidth, out = [];
  document.querySelectorAll('body *').forEach(e => { const r = e.getBoundingClientRect(); if (r.width > 0 && r.right > W + 1 && e.offsetParent !== null) {
    let a = e, clipped = false; while ((a = a.parentElement)) { const o = getComputedStyle(a).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') { clipped = true; break; } }
    if (!clipped) out.push(e.tagName + '.' + String(e.className).slice(0, 40) + '#' + e.id + ' right=' + Math.round(r.right) + ' w=' + Math.round(r.width)); } });
  return out.slice(0, 6); }"""


class _Overflow:
    """Truthy when the document does not overflow; its repr names the unclipped offenders, so a failure is self-explaining."""

    def __init__(self, page):
        self.ok = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        self.offenders = [] if self.ok else page.evaluate(OFFENDERS)

    def __bool__(self):
        return bool(self.ok)

    def __repr__(self):
        return f"document overflow; unclipped offenders: {self.offenders}"


def _no_document_overflow(page):
    return _Overflow(page)


def _open_history(t):
    t.page.evaluate("document.getElementById('tab-run-history').click()")
    t.page.locator("[data-testid=run-history-table]").wait_for()


def test_history_detail_and_compare_never_widen_the_document_and_tables_scroll_in_their_own_region(live_server, browser):
    t = _two_runs(live_server, browser, "rcux2-rh-1")
    for width, height, scheme in VIEWPORTS:
        t.page.emulate_media(color_scheme=scheme)
        t.page.set_viewport_size({"width": width, "height": height})
        _open_history(t)
        assert t.page.locator("[data-testid^=run-history-row-]").count() == 2
        region = t.page.locator(".v2-rh-scroll").first
        assert region.get_attribute("tabindex") == "0" and region.get_attribute("role") == "region"      # keyboard-reachable scroll region
        ov = _no_document_overflow(t.page)
        assert ov, ("list", width, scheme, repr(ov))
        for opener, back in (("run-history-detail-1", "run-detail-back"), ("run-history-compare-expanded-1", "ds-back-to-history"), ("run-history-compare-1", "run-compare-back")):
            t.page.locator(f"[data-testid={opener}]").click()
            t.page.locator(f"[data-testid={back}]").wait_for()
            ov = _no_document_overflow(t.page)
            assert ov, (opener, width, scheme, repr(ov))
            assert t.page.locator(f"[data-testid={back}]").is_visible()                                    # navigation back is never hidden
            t.page.locator(f"[data-testid={back}]").click()
            try:
                t.page.locator("[data-testid=run-history-table]").wait_for()
            except Exception:
                pytest.fail(f"back from {opener} did not return to the Run History list at {width}px {scheme}: " + t.page.locator("#v2-sheet-run-history").inner_text()[:200])
    assert t.errors == [], t.errors
    t.close()


def test_history_identities_and_states_are_truthful_and_earlier_runs_stay_immutable(live_server, browser):
    from app.persistence.run_history_repository import get_run_history
    t = _two_runs(live_server, browser, "rcux2-rh-2")
    rows = get_run_history(t.uid, t.rec.project_id)
    assert len(rows) == 2
    _open_history(t)
    shown = t.page.locator("[data-testid^=run-history-status-]").all_inner_texts()
    assert len(shown) == 2 and sum("LAST RUN" in x.upper() for x in shown) == 1                        # exactly one row is the Last Run, the other is historical
    snapshot_texts = t.page.locator(".v2-rh-mono").all_inner_texts()
    for entry in rows:
        assert any(str(getattr(entry, "snapshot_id", ""))[:8] in text or not getattr(entry, "snapshot_id", "") for text in snapshot_texts)
    t.open()                                                                                          # change an input: results go STALE, history is untouched
    t.dd("start").fill("2030-03-01")
    t.save()
    assert t.state() == "STALE"
    after = get_run_history(t.uid, t.rec.project_id)
    assert [str(getattr(e, "snapshot_id", e)) for e in after] == [str(getattr(e, "snapshot_id", e)) for e in rows]
    _open_history(t)
    assert "STALE" in t.page.locator("[data-testid^=run-history-last-run-state-]").first.inner_text().upper()
    assert t.page.locator("[data-testid^=run-history-row-]").count() == 2
    t.close()
