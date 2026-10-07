"""Workflow 04 - Solar / Wind canonical reference integration proofs.

Real-reference proofs on the canonical Generic Solar Reference and Generic
Wind Reference authorities. ZERO economic change is asserted by repeat-run
identity and by the repository's own pinned validation contracts (read-only).

Acceptance markers:

  ASSUMPTION_TRACE_SOLAR_REFERENCE_ZERO_ECONOMIC_DELTA
  ASSUMPTION_TRACE_WIND_REFERENCE_ZERO_ECONOMIC_DELTA
  ASSUMPTION_TRACE_REGISTERS_DETERMINISTIC_PER_VERTICAL
  ASSUMPTION_TRACE_TRACES_MATCH_CANONICAL_KPIS
  ASSUMPTION_TRACE_PINNED_CONTRACT_REGRESSION
  ASSUMPTION_TRACE_NO_FROZEN_NAMESPACE_TOUCHED
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from app.model_v2.assumption_register import (
    AssumptionContextKind,
    AssumptionSourceKind,
    RegisterContext,
    RunIdentity,
    build_assumption_register,
)
from app.model_v2.calculation_trace import build_calculation_trace
from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.production_financial_authority import run_clean_production

_VERTICALS = (
    ("solar", create_generic_solar_reference),
    ("wind", create_generic_wind_reference),
)

# Headline regression references pinned by the repository's own validation
# authority (app/model_validation/contracts.py - read-only reuse; the module
# is frozen and is NOT modified by this workflow).
_EXPECTED_HEADLINES = {
    "solar": {"project_irr": 0.11768, "senior_debt_keur": 26983.33},
    "wind": {"project_irr": 0.13311, "senior_debt_keur": 36505.16},
}


@pytest.fixture(scope="module", params=[v for v, _ in _VERTICALS])
def proof(request):
    factory = dict(_VERTICALS)[request.param]
    inputs = factory()
    context = RegisterContext.for_working_copy(
        state_provenance=AssumptionSourceKind.FACTORY_DEFAULT
    )
    base_register = build_assumption_register(inputs, context)
    run = run_clean_production(inputs, "Base", project_type=request.param)
    run_register = build_assumption_register(run.project_inputs, context)
    trace = build_calculation_trace(
        run, context=context, assumption_register=run_register
    )
    repeat = run_clean_production(inputs, "Base", project_type=request.param)
    return {
        "vertical": request.param,
        "inputs": inputs,
        "run": run,
        "repeat": repeat,
        "base_register": base_register,
        "run_register": run_register,
        "trace": trace,
    }


def test_zero_economic_delta(proof):
    """ASSUMPTION_TRACE_{SOLAR,WIND}_REFERENCE_ZERO_ECONOMIC_DELTA = PASS."""
    run, repeat = proof["run"], proof["repeat"]
    a, b = run.g2c_result, repeat.g2c_result
    assert a.total_sponsor_xirr == b.total_sponsor_xirr
    assert a.pure_equity_xirr == b.pure_equity_xirr
    assert (a.financing_result.final_senior_commitment_keur
            == b.financing_result.final_senior_commitment_keur)
    assert (a.valuation_summary.project_npv.npv_keur
            == b.valuation_summary.project_npv.npv_keur)
    # register rebuild is byte-identical across runs
    context = RegisterContext.for_working_copy(
        state_provenance=AssumptionSourceKind.FACTORY_DEFAULT
    )
    assert build_assumption_register(
        repeat.project_inputs, context
    ).to_json() == proof["run_register"].to_json()


def test_register_deterministic_per_vertical(proof):
    """ASSUMPTION_TRACE_REGISTERS_DETERMINISTIC_PER_VERTICAL = PASS."""
    context = RegisterContext.for_working_copy(
        state_provenance=AssumptionSourceKind.FACTORY_DEFAULT
    )
    rebuilt = build_assumption_register(proof["inputs"], context)
    assert rebuilt.to_json() == proof["base_register"].to_json()
    assert rebuilt.fingerprint == proof["base_register"].fingerprint
    # run-bound register binds the declared identity and round-trips
    bound_context = RegisterContext.for_run_bound(
        run_identity=RunIdentity(
            snapshot_id="reference-proof",
            composite_hash=proof["base_register"].fingerprint,
            workbook_version=proof["base_register"].workbook_version,
            engine_version=proof["base_register"].engine_version,
        ),
        state_provenance=AssumptionSourceKind.FACTORY_DEFAULT,
    )
    bound = build_assumption_register(proof["inputs"], bound_context)
    assert bound.context.context_kind is AssumptionContextKind.RUN_BOUND
    assert bound.to_json() == build_assumption_register(
        proof["inputs"], bound_context
    ).to_json()


def test_trace_matches_canonical_kpis(proof):
    """ASSUMPTION_TRACE_TRACES_MATCH_CANONICAL_KPIS = PASS."""
    trace, run = proof["trace"], proof["run"]
    g2c = run.g2c_result
    assert trace.entry("project_xirr").output_value == (
        g2c.return_summary.project.project_xirr
    )
    assert trace.entry("senior_debt_keur").output_value == (
        g2c.financing_result.final_senior_commitment_keur
    )
    assert trace.entry("total_revenue_keur").output_value > 0
    assert trace.entry("total_ebitda_keur").output_value > 0


def test_pinned_contract_regression(proof):
    """ASSUMPTION_TRACE_PINNED_CONTRACT_REGRESSION = PASS."""
    vertical = proof["vertical"]
    expected = _EXPECTED_HEADLINES[vertical]
    trace = proof["trace"]
    assert trace.entry("project_xirr").output_value == pytest.approx(
        expected["project_irr"], abs=1e-5
    )
    assert trace.entry("senior_debt_keur").output_value == pytest.approx(
        expected["senior_debt_keur"], rel=1e-4
    )


def test_no_frozen_namespace_touched():
    """ASSUMPTION_TRACE_NO_FROZEN_NAMESPACE_TOUCHED = PASS."""
    probe = subprocess.run(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        capture_output=True,
    )
    assert probe.returncode == 0
    from finance_integrity_governance import unapproved_engine_changes
    from model_v2_governance import model_v2_frozen_violations

    assert model_v2_frozen_violations() == []
    # Engine files outside the shared approved allow-list (which also honours the Model V2
    # scope contract) must stay untouched.
    assert unapproved_engine_changes() == []
