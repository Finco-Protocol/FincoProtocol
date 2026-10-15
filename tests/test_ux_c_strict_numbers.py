"""Stream C (RC-UX): malformed numeric input is rejected, never reinterpreted (UX-017, UX-018).

The browser module and the server writer boundary share one rule: an amount is an optional sign, ASCII digits and one unambiguous decimal
separator. ``410 420 430`` must never become 410420430, ``1,234`` is ambiguous and is rejected, a multiline paste is rejected.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static/js/cost_staging.js").read_text(encoding="utf-8")

ACCEPT = {"410": "410", " 410 ": "410", "-12.5": "-12.5", "+3": "+3", ".5": ".5", "12,5": "12.5", "1,234.56": "1234.56", "0": "0"}
REJECT = ["410 420 430", "1,234", "12 5", "4\n10", "410\n420\n430", "1.234,56", "1,2,3", "1e3x", "abc", "--5", "1.2.3", "١٢٣", "", "12,", ",5"]


def _node_normalise(values):
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    start = JS.index("var AMOUNT =")
    end = JS.index("function isNumeric")
    program = "%s\nconsole.log(JSON.stringify(%s.map(function(v){return [normNumber(v), AMOUNT.test(normNumber(v))];})));" % (
        JS[start:end], json.dumps(values))
    out = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_the_browser_gate_accepts_only_unambiguous_amounts():
    got = _node_normalise(list(ACCEPT))
    for (raw, want), (norm, ok) in zip(ACCEPT.items(), got):
        assert ok and norm == want, (raw, norm)


@pytest.mark.parametrize("raw", REJECT)
def test_the_browser_gate_rejects_malformed_and_ambiguous_input(raw):
    (norm, ok), = _node_normalise([raw])
    assert not ok, (raw, norm)
    assert re.sub(r"\s", "", norm) != "410420430" or " " in norm or "\n" in norm      # never silently concatenated


def test_plain_arrows_do_not_change_a_value():
    block = JS[JS.index("e.key === 'ArrowUp'"):]
    block = block[:block.index("});")]
    assert "e.altKey" in block and "adjust(t, dir, e.shiftKey)" in block
    assert block.index("e.altKey") < block.index("adjust(")


@pytest.mark.parametrize("raw", ["410 420 430", "1_000", "１２３", " 5 ", "1,234", "nan", "inf", "0x10", "5\n", "", "1e400"])
def test_the_server_boundary_refuses_non_ascii_or_padded_amounts(raw):
    from app.v2.capex_commands import CapexInvalidAmountError, _parse_finite_amount_keur
    from app.v2.opex_commands import OpexInvalidAmountError, _parse_finite_opex_numerics
    with pytest.raises(CapexInvalidAmountError):
        _parse_finite_amount_keur(raw)
    with pytest.raises(OpexInvalidAmountError):
        _parse_finite_opex_numerics(raw, "2")
    with pytest.raises(OpexInvalidAmountError):
        _parse_finite_opex_numerics("2", raw)


@pytest.mark.parametrize("raw,want", [("410", 410.0), ("-12.5", -12.5), ("1e-05", 1e-05), (".5", 0.5), (7, 7.0), (2.5, 2.5)])
def test_the_server_boundary_still_accepts_what_the_ui_sends(raw, want):
    from app.v2.capex_commands import _parse_finite_amount_keur
    assert _parse_finite_amount_keur(raw) == want


def test_opex_summary_total_is_shown_from_the_live_total_in_both_fields():
    """UX-003: the F06 override must set display_value too - the sheet renders display_value, not value."""
    src = (ROOT / "app/v2/router.py").read_text(encoding="utf-8")
    block = src[src.index('if _summary_field["field_id"] == "opex.summary.total_y1":'):]
    block = block[:block.index("\n\n")]
    assert '"value"] = opex_vm.y1_total_opex' in block and '"display_value"] = opex_vm.y1_total_opex' in block


def test_the_two_opex_sticky_columns_share_one_offset_variable():
    """UX-005: the name column offset equals the code column width by construction."""
    css = (ROOT / "static/css/workbook_v2.css").read_text(encoding="utf-8")
    assert "left: 4.2rem; z-index: 2" not in css
    name = css[css.index(".v2-opex-proj-sticky-name {"):]
    name = name[:name.index("}")]
    assert "left: var(--v2-proj-code-w)" in name
    code = css[css.index(".v2-opex-proj-sticky-code {"):]
    code = code[:code.index("}")]
    assert code.count("var(--v2-proj-code-w)") == 3


def test_a_failed_unsaved_cost_edit_blocks_structural_actions_scenario_changes_and_run():
    """UX-019: a failed row is still unsaved; the htmx:confirm guard must refuse to swap it away (and must not retry)."""
    guard = JS[JS.index("htmx:confirm"):]
    guard = guard[:guard.index("if (!gridBusy()) return;")]
    assert "'failed'" in guard and "e.preventDefault()" in guard and "isDirty(r)" in guard
    assert "saveRow" not in guard and "commitRow" not in guard                 # no automatic retry of a financial write
