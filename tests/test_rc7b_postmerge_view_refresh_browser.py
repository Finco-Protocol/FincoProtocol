"""Post-#320 recovery: a saved Construction timing edit must not leave Project Setup locked as an 'unsaved draft'.

``model_view_refresh.js`` locks the Project Setup controls while a coherent refresh is pending and refuses to refresh over unsaved edits. A trusted
edit inside the Construction timing component used to stay 'unsaved' after that component had saved it, so the sheet stayed locked until reload.
An edit outside that component (``otherDirty``) still keeps its draft; the Project Name field already disables the timing Save while it is pending.
Presentation only; no financial path is involved.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_model_project_timeline_browser import TL
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402

SHEET = "#v2-sheet-project-setup"


def test_a_saved_construction_timing_edit_lets_the_sheet_refresh_and_unlocks_its_controls(live_server, browser):
    t = TL(live_server, browser, "rc7b-postmerge-ct")
    t.dd("duration").fill("16"); t.save()
    t.page.wait_for_function(f"() => document.querySelector('{SHEET}').dataset.modelViewState === 'loaded'", timeout=20000)
    assert t.dd("duration").is_enabled()
    t.dd("duration").fill("17")                                        # the control is editable again without a reload
    t.close()
