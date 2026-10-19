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


def test_candidate_does_not_self_authorize_or_activate():
    from tests.model_v2_governance import released_engine_authority_matches
    from app.workbook import bess_config
    from domain.revenue.advanced_products import ACTIVATION_ENABLED as revenue
    from app.workbook.junior_debt_config import ACTIVATION_ENABLED as junior
    assert not bess_config.ACTIVATION_ENABLED and not revenue and not junior
    for path in ('financial_engine/bess.py', 'finco_core/inputs/bess_native.py'):
        assert not released_engine_authority_matches(path)
        assert not released_engine_authority_matches(path, ref='missing-reviewed-ref')
    assert not released_engine_authority_matches('financial_engine/unapproved_battery_policy.py')


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


def test_exact_candidate_manifest_is_not_a_release_and_mutations_fail():
    from copy import deepcopy
    manifest = json.loads((ROOT / 'docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json').read_text(encoding='utf-8'))
    expected = {'domain/bess/' + path for path in ('__init__.py', 'contracts.py', 'dispatch.py', 'settlement.py', 'synthetic.py')} | {
        'finco_core/inputs/bess_native.py', 'financial_engine/bess.py',
        'financial_engine/adapters/project_inputs.py', 'financial_engine/orchestrator.py',
        'app/run_integrity/evidence.py', 'app/run_integrity/checks.py'}
    def exact(candidate):
        if (candidate.get('release_approved') is not False or candidate.get('status') != 'CANDIDATE_REVIEW_ONLY'
                or candidate.get('base') != BASE or set(candidate.get('protected_blobs', {})) != expected):
            return False
        # RC-7B Gate R: the two shared paths (orchestrator, project_inputs) are judged against the superseding candidate blob ONLY while a complete,
        # authentic Gate R is active; every other path, and every tree without Gate R, keeps the manifest's own M7 blob.
        from quarterly_candidate_recognition import current_expected_blob
        return all(subprocess.run(['git', '-c', 'core.autocrlf=false', 'hash-object', path], cwd=ROOT,
                   capture_output=True, text=True, check=True).stdout.strip() == current_expected_blob(path, blob, repo=ROOT)
                   for path, blob in candidate['protected_blobs'].items())
    assert exact(manifest)
    for fault in ('altered', 'missing', 'extra', 'release', 'provenance'):
        bad = deepcopy(manifest)
        path = 'financial_engine/bess.py'
        if fault == 'altered': bad['protected_blobs'][path] = '0' * 40
        elif fault == 'missing': bad['protected_blobs'].pop(path)
        elif fault == 'extra': bad['protected_blobs']['financial_engine/unreviewed.py'] = '0' * 40
        elif fault == 'release': bad['release_approved'] = True
        else: bad['base'] = 'missing-reviewed-ref'
        assert not exact(bad)
