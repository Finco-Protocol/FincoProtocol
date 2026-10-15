"""C-0: the cost-staging module is its own file (extracted verbatim from workbook_v2.js; byte parity proven at extraction).

Structural contract only: where the module lives, that it exists exactly once, and that it is loaded in the same place as before.
It deliberately does not freeze the file's content - later streams change cost_staging.js and workbook_v2.js on purpose.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = (ROOT / "static/js/cost_staging.js").read_text(encoding="utf-8")
CORE = (ROOT / "static/js/workbook_v2.js").read_text(encoding="utf-8")
PAGE = (ROOT / "app/templates/v2/workbook.html").read_text(encoding="utf-8")
MARKER = "Cost grid (CAPEX / OPEX): direct-cell editing"
GUARD = "window.__v2CostGridInit"


def test_the_cost_grid_lives_in_exactly_one_file():
    assert MODULE.count(MARKER) == 1 and CORE.count(MARKER) == 0
    assert MODULE.count(GUARD) >= 1 and CORE.count(GUARD) == 0
    assert "window.v2CostGrid = {" in MODULE and "v2CostGrid" not in CORE         # public surface unchanged and not duplicated
    body = MODULE.split(MARKER, 1)[1]
    assert body.count("if (window.__v2CostGridInit) return;") == 1                # one self-contained, guarded module


def test_the_module_adds_no_new_transport_and_no_dynamic_code():
    for forbidden in ("eval(", "new Function(", "XMLHttpRequest", "navigator.sendBeacon"):
        assert forbidden not in MODULE, forbidden
    assert "data-cost-grid" in MODULE and "data-cost-row" in MODULE


def test_the_page_loads_the_module_once_directly_after_the_core_script():
    core, module = '/static/js/workbook_v2.js', '/static/js/cost_staging.js'
    assert PAGE.count(core) == 1 and PAGE.count(module) == 1
    assert PAGE.index(core) < PAGE.index(module) < PAGE.index('/static/js/model_smart_panel_v2.js')
    assert PAGE.index(module) < PAGE.index('/static/js/model_bess_workspace.js')       # exactly where the tail of the old file ran
