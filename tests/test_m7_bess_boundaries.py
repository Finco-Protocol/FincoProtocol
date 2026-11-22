"""Candidate authority is not a release pin; exact inactive operating comparison."""
import subprocess
import sys
import types
from pathlib import Path
from dataclasses import replace
import json
import pytest

BASE = '6fc77de98bc0562fb51efdbf96e1803a29b5b148'
ROOT = Path(__file__).resolve().parents[1]


def historical_module(path, name):
    source = subprocess.run(['git', 'show', BASE + ':' + path], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True).stdout
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        exec(compile(source, path, 'exec'), module.__dict__)
    finally:
        sys.modules.pop(name)
    return module


@pytest.mark.parametrize('kind', ['solar', 'wind', 'data_center', 'ev_charging'])
def test_four_vertical_inactive_operating_result_is_bit_exact_to_rc2(kind):
    from app import project_factories as factories
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    old_adapter = historical_module('financial_engine/adapters/project_inputs.py', 'financial_engine.adapters.m7_before')
    old_engine = historical_module('financial_engine/orchestrator.py', 'financial_engine.m7_before')
    inputs = getattr(factories, 'create_generic_' + kind + '_reference')()
    before, after = old_adapter.from_project_inputs(inputs), from_project_inputs(inputs)
    assert before == after
    assert old_engine.run_operating_model(before) == run_operating_model(after)


def test_bess_cannot_silently_consume_renewable_bank_yield_or_price_overrides(monkeypatch):
    from tests.test_m7_bess_canonical_finance import candidate
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import derive_debt_sizing_operating_input
    from financial_engine.inputs import DebtSizingCaseInput, YieldScenario as CleanYield
    p, raw = candidate(monkeypatch)
    for config in (DebtSizingCaseInput(production_yield_scenario=CleanYield.P90_10Y),
                   DebtSizingCaseInput(production_yield_scenario=CleanYield.P50, market_prices_curve_eur_mwh=(100,))):
        with pytest.raises(ValueError, match='BESS_BANK_CASE_UNSUPPORTED'):
            derive_debt_sizing_operating_input(from_project_inputs(p), config)


def test_writer_does_not_accept_an_arbitrary_new_field():
    from app.workbook.revenue_contracts_service import save_contracts
    with pytest.raises(ValueError, match='TYPED_CONTRACT_FIELD_NOT_AUTHORIZED'):
        save_contracts(owner='synthetic-owner', project_id='not-created', expected_hash='x', raw='{}', field_id='unapproved.policy')


def test_candidate_manifest_is_not_a_release():
    """The M7 BESS candidate stays review-only (blob pinning against the moving head was retired with CI governance V4/V5;
    activation is guarded by tests/test_financial_activation_flags_closed.py)."""
    manifest = json.loads((ROOT / 'docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest.get('release_approved') is False
    assert manifest.get('status') == 'CANDIDATE_REVIEW_ONLY'
