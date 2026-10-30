"""Prove fixture provenance adaptations do not weaken any historical assertion."""
from pathlib import Path
import subprocess
import re
import pytest

ROOT=Path(__file__).resolve().parents[1]
BASE='cf7056de4078ca66afcf52265a9bacafe35586f7'
MARKER_ONLY=(
 'tests/test_api_v1_1_institutional.py','tests/test_p1_2_xlsx_export_reconciliation.py',
 'tests/test_p1_3_institutional_validation.py','tests/test_p1_4_ev_reconciliation.py',
 'tests/test_u2_2_returns_surface.py','tests/test_public_surface_hygiene.py',
 'tests/test_ev_charging_catalogue_seed.py','tests/test_ev_charging_driver_authority.py',
 'tests/rc7_helpers.py')

def baseline(path):
    return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,text=True)

def strip_fixture_declarations(text):
    kept=[]
    for line in text.splitlines(keepends=True):
        if '"_finval_interest_rate_unit": "human_percent_v1"' in line:
            # Only the literal metadata entry plus an inert comment is admitted.
            assert re.fullmatch(r'\s*"_finval_interest_rate_unit": "human_percent_v1",\s*(?:#[^\n]*)?\n?',line)
        else:
            kept.append(line)
    return ''.join(kept)

@pytest.mark.parametrize('path',MARKER_ONLY)
def test_only_unit_declarations_changed_no_old_assertion_or_value(path):
    actual=(ROOT/path).read_text()
    assert strip_fixture_declarations(actual)==baseline(path)
    assert strip_fixture_declarations(actual+'\nassert False\n')!=baseline(path)
    with pytest.raises(AssertionError):
        strip_fixture_declarations(actual.replace('"human_percent_v1",','"human_percent_v1", "unexpected": False,',1))


def test_old_dom_golden_is_unchanged_and_harness_only_declares_fresh_units():
    path='tests/model_workspace_harness.py'
    expected=baseline(path).replace('pis = ProjectInputSet.from_snapshot({}, workbook=WORKBOOK)',
        'pis = ProjectInputSet.from_snapshot({"_finval_interest_rate_unit": "human_percent_v1"}, workbook=WORKBOOK)\n    # Fresh synthetic presentation fixture declares its unit; no historical row is labeled.')
    assert (ROOT/path).read_text()==expected
    golden='tests/fixtures/model_workspace_field_editor_golden.json'
    assert (ROOT/golden).read_text()==baseline(golden)


def test_authority_mock_has_only_its_missing_unit_added():
    # Historical F01 only changes the missing-unit mock. FIN-V2-3 legitimately adds
    # TWO reviewed valuation DOM hashes; no other old assertion, input or fixture
    # is allowed to drift. The entire FIN-V2-3 source cohort must match its exact
    # repository-bound manifest before this finite reconciliation is admitted.
    path='tests/test_model_workspace_productivity_v1.py'
    old='ws=SimpleNamespace(user_id="u", project_id="p", draft_snapshot={}),\n                field_id="debt.senior.interest_rate_pct"'
    new='ws=SimpleNamespace(user_id="u", project_id="p", draft_snapshot={"_finval_interest_rate_unit": "human_percent_v1"}),\n                field_id="debt.senior.interest_rate_pct"'
    assert baseline(path).count(old)==1
    original = baseline(path).replace(old,new)
    from tests.fin_v2_cohorts import matches
    actual = (ROOT/path).read_text()
    assert matches(path, actual)
    historical = '        assert set(actual) == set(golden["hashes"]) | financing_additions\n'
    assert original.count(historical)==1
    approved_valuation_extension = "        # FIN-V2-3 adds one explicitly configured policy field. Its two\n        # presentations are separately hash-locked; all historical DOM hashes\n        # and the exact CSRF/read-only checks above remain unchanged.\n        from tests.fin_v2_cohorts import matches\n        assert matches(\"app/workbook/registry.py\")\n        valuation_additions = {\n            \"project_setup|editable|debt.valuation.configuration\": \"74353aad956d330f773a01b553ca95e637aab18c1d949b9fe3f6b206bd84660b\",\n            \"project_setup|protected|debt.valuation.configuration\": \"4ed792d9787c2a2dbf1edf084be7524e8e5608626014f5ee5f4ecbed00b73186\",\n        }\n        assert {key: actual[key] for key in valuation_additions} == valuation_additions\n"
    extended = '        assert set(actual) == set(golden["hashes"]) | financing_additions | set(valuation_additions)\n'
    fin_v2_3_state = original.replace(historical, approved_valuation_extension + extended)
    if actual == fin_v2_3_state:
        return
    # WF-04 successor lineage (tests/wf04_scope.py, Owner Correction B): the file is the FIN-V2-3 state with ONLY the reviewed macro-identity guard
    # change - (1) the closed literal sets of reviewed additions (financing / valuation / the four WF-04 contract presentations, each with its own
    # sha256) and the pure judge, (2) the body of the one macro node (same node id) now delegating to them, (3) the new fail-closed negatives class.
    # Every other line - the F01 mock, _ADDED_ATTRS, _historical_macro_dom, every other test - must be untouched, and the exact blob is pinned.
    from tests import wf04_scope as WF04
    assert WF04.matches(path, actual)
    import difflib
    before, after = fin_v2_3_state.splitlines(), actual.splitlines()
    start = before.index('    def test_macro_output_matches_the_base_commit_except_three_additive_attributes(self):')
    end = next(i for i in range(start + 1, len(before)) if before[i].startswith('    @pytest.mark.parametrize("old,new", ['))
    ops = [op for op in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if op[0] != 'equal']
    assert ops and all(op[0] in ('insert', 'replace', 'delete') for op in ops)
    assert all(start <= op[1] and op[2] <= end for op in ops if op[0] != 'insert'), 'a line outside the macro node was changed or removed'
    cls = before.index('class TestDenseLayoutPreservesContract:')          # the reviewed helper block precedes this class
    nxt = next(i for i in range(end, len(before)) if before[i].startswith('# 3. CSS / JS static contracts')) - 1    # the negatives class precedes section 3
    assert all(cls - 2 <= op[1] <= end or nxt - 3 <= op[1] <= nxt + 1 for op in ops if op[0] == 'insert'), 'an insertion outside the reviewed regions'
    for kept in ('golden["base_commit"] == "1951e26df9305edaa4cec3d0066af9fd2ec48fb9"', 'drifted = sorted(k for k, v in golden["hashes"].items() if actual[k] != v)',
                 'assert matches("app/workbook/registry.py")', "_ADDED_ATTRS = re.compile(r'\\s+data-(?:field-label|sheet-id|required|register-path)=\"[^\"]*\"')"):
        assert kept in actual, kept
    assert actual.count('"project_setup|editable|debt.valuation.configuration": "74353aad956d330f773a01b553ca95e637aab18c1d949b9fe3f6b206bd84660b"') == 1


def test_sensitivity_oracle_removes_only_the_documented_old_ratio_conversion():
    path='tests/test_m3_two_driver_sensitivity.py'
    old='rate0 = float(pis.values["debt.senior.interest_rate_pct"]) * 100.0        # seeded snapshot value is a RATIO'
    new='rate0 = float(pis.values["debt.senior.interest_rate_pct"])  # verified seed is human percent'
    assert baseline(path).count(old)==1
    assert (ROOT/path).read_text()==baseline(path).replace(old,new)


def test_opex_factory_fixture_keeps_the_same_financial_rate():
    path='tests/test_f06_opex_display_authority.py'
    actual=strip_fixture_declarations((ROOT/path).read_text())
    expected=baseline(path).replace(
        '"interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000)',
        '"interest_rate_pct": str((pi.financing.base_rate + pi.financing.margin_bps / 10_000) * 100.0)')
    assert actual==expected
