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
    assert actual == original.replace(historical, approved_valuation_extension + extended)

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
