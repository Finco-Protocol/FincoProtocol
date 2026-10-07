"""Workflow 04 - Calculation Trace acceptance matrix.

Acceptance markers:

  CALCULATION_TRACE_NO_RECOMPUTE          (A) values are verbatim pass-through
  CALCULATION_TRACE_CANONICAL_PASS_THROUGH (B) bit-equal canonical values
  CALCULATION_TRACE_STABLE_IDS            (C) stable trace identity
  CALCULATION_TRACE_REFERENCES_TYPED      (D) assumption refs exist or fail
  CALCULATION_TRACE_COMPLETENESS_STABLE   (E) completeness deterministic
  CALCULATION_TRACE_UNAVAILABLE_HONEST    (F) unavailable stays UNAVAILABLE
  CALCULATION_TRACE_RUN_BOUND_IDENTITY    (G) run identity recorded verbatim
  CALCULATION_TRACE_NO_MASQUERADE         (H) working copy never claims run
  CALCULATION_TRACE_AUTHORITY_XIRR        (I) XIRR points at canonical authority
  CALCULATION_TRACE_AUTHORITY_DEBT        (J) debt points at canonical authority
  CALCULATION_TRACE_METRIC_DISTINCT       (K) DSCR/LLCR/PLCR stay distinct
  CALCULATION_TRACE_NO_ENGINE_MUTATION    (L) zero effect on economics
  CALCULATION_TRACE_SERIALIZATION         (M) deterministic JSON + guards
"""
from __future__ import annotations

import pytest

from app.model_v2.assumption_register import (
    AssumptionContextKind,
    AssumptionSourceKind,
    RegisterContext,
    RunIdentity,
    build_assumption_register,
)
from app.model_v2.calculation_trace import (
    CALCULATION_TRACE_SCHEMA_ID,
    CALCULATION_TRACE_SCHEMA_VERSION,
    CalculationTrace,
    TraceCompleteness,
    build_calculation_trace,
)
from app.project_factories import create_generic_solar_reference
from app.services.production_financial_authority import run_clean_production


@pytest.fixture(scope="module")
def solar_run():
    inputs = create_generic_solar_reference()
    return inputs, run_clean_production(inputs, "Base", project_type="solar")


@pytest.fixture(scope="module")
def traced(solar_run):
    inputs, run = solar_run
    context = RegisterContext.for_working_copy(
        state_provenance=AssumptionSourceKind.FACTORY_DEFAULT
    )
    register = build_assumption_register(inputs, context)
    trace = build_calculation_trace(
        run, context=context, assumption_register=register
    )
    return context, register, run, trace


def test_a_and_b_pass_through_bit_exact(traced):
    """CALCULATION_TRACE_NO_RECOMPUTE + CANONICAL_PASS_THROUGH = PASS."""
    _, _, run, trace = traced
    g2c = run.g2c_result
    assert trace.entry("project_xirr").output_value == (
        g2c.return_summary.project.project_xirr
    )
    assert trace.entry("pure_equity_xirr").output_value == g2c.pure_equity_xirr
    assert trace.entry("total_sponsor_xirr").output_value == (
        g2c.total_sponsor_xirr
    )
    assert trace.entry("senior_debt_keur").output_value == (
        g2c.financing_result.final_senior_commitment_keur
    )
    assert trace.entry("project_npv_keur").output_value == (
        g2c.valuation_summary.project_npv.npv_keur
    )
    # min DSCR mirrors the canonical presentation aggregation
    dscrs = [
        row.base_dscr
        for row in g2c.waterfall_periods
        if row.base_dscr is not None
    ]
    if dscrs:
        assert trace.entry("min_dscr").output_value == pytest.approx(
            min(dscrs), abs=1e-12
        )


def test_c_trace_ids_stable(traced):
    """CALCULATION_TRACE_STABLE_IDS = PASS."""
    context, register, run, trace = traced
    again = build_calculation_trace(
        run, context=context, assumption_register=register
    )
    assert [e.trace_id for e in trace.entries] == [
        e.trace_id for e in again.entries
    ]
    assert trace.to_json() == again.to_json()


def test_d_references_must_exist(traced):
    """CALCULATION_TRACE_REFERENCES_TYPED = PASS."""
    _, register, _, trace = traced
    known = {e.assumption_id for e in register.entries}
    for entry in trace.entries:
        for assumption_id in entry.referenced_assumption_ids:
            assert assumption_id in known, assumption_id
    assert trace.entry("senior_debt_keur").referenced_assumption_ids


def test_e_completeness_deterministic(traced):
    """CALCULATION_TRACE_COMPLETENESS_STABLE = PASS."""
    _, _, run, trace = traced
    again = build_calculation_trace(
        run,
        context=RegisterContext.for_working_copy(
            state_provenance=AssumptionSourceKind.FACTORY_DEFAULT
        ),
    )
    assert [e.completeness for e in trace.entries] == [
        e.completeness for e in again.entries
    ]
    assert all(
        e.completeness in (TraceCompleteness.AUTHORITY_ONLY,
                           TraceCompleteness.UNAVAILABLE)
        for e in trace.entries
    )


def test_f_unavailable_stays_unavailable(traced):
    """CALCULATION_TRACE_UNAVAILABLE_HONEST = PASS."""
    _, _, _, trace = traced
    for key in ("project_npv_keur", "min_llcr", "min_plcr"):
        entry = trace.entry(key)
        if entry.output_value is None:
            assert entry.completeness is TraceCompleteness.UNAVAILABLE
            assert entry.status is not None
            assert entry.notes and "never as zero" in entry.notes


def test_g_run_bound_records_identity():
    """CALCULATION_TRACE_RUN_BOUND_IDENTITY = PASS."""
    inputs = create_generic_solar_reference()
    identity = RunIdentity(
        snapshot_id="20261006T012345Z",
        composite_hash="cafe",
        workbook_version="2.3.0",
        engine_version="clean_senior_debt_v0",
    )
    run = run_clean_production(inputs, "Base", project_type="solar")
    trace = build_calculation_trace(
        run,
        context=RegisterContext.for_run_bound(
            run_identity=identity,
            state_provenance=AssumptionSourceKind.USER_INPUT,
        ),
    )
    payload = trace.to_dict()
    assert payload["context"]["context_kind"] == "RUN_BOUND"
    assert payload["context"]["run_identity"]["snapshot_id"] == (
        "20261006T012345Z"
    )
    assert CalculationTrace.from_json(trace.to_json()).fingerprint == (
        trace.fingerprint
    )


def test_h_working_copy_never_claims_run(traced):
    """CALCULATION_TRACE_NO_MASQUERADE = PASS."""
    context, _, _, trace = traced
    payload = trace.to_dict()
    assert payload["context"]["context_kind"] == "WORKING_COPY"
    assert payload["context"]["run_identity"] is None
    assert context.context_kind is AssumptionContextKind.WORKING_COPY


def test_i_xirr_authority(traced):
    """CALCULATION_TRACE_AUTHORITY_XIRR = PASS."""
    _, _, _, trace = traced
    entry = trace.entry("project_xirr")
    assert entry.methodology_key == "project_irr"
    assert "project_returns" in entry.authority
    assert entry.formula_ref


def test_j_debt_authority(traced):
    """CALCULATION_TRACE_AUTHORITY_DEBT = PASS."""
    _, _, _, trace = traced
    entry = trace.entry("senior_debt_keur")
    assert "financing" in entry.authority
    assert entry.output_value > 0


def test_k_coverage_metrics_distinct(traced):
    """CALCULATION_TRACE_METRIC_DISTINCT = PASS."""
    _, _, _, trace = traced
    dscr = trace.entry("min_dscr")
    llcr = trace.entry("min_llcr")
    plcr = trace.entry("min_plcr")
    ids = {dscr.trace_id, llcr.trace_id, plcr.trace_id}
    assert len(ids) == 3
    assert dscr.methodology_key == "dscr"
    assert llcr.methodology_key == "llcr"
    assert plcr.methodology_key is None  # registry seam: documented

def test_l_no_engine_mutation(solar_run, traced):
    """CALCULATION_TRACE_NO_ENGINE_MUTATION = PASS."""
    inputs, run = solar_run
    baseline = run_clean_production(inputs, "Base", project_type="solar")
    assert baseline.g2c_result.total_sponsor_xirr == (
        run.g2c_result.total_sponsor_xirr
    )
    assert (baseline.g2c_result.financing_result.final_senior_commitment_keur
            == run.g2c_result.financing_result.final_senior_commitment_keur)


def test_m_serialization_guards(traced):
    """CALCULATION_TRACE_SERIALIZATION = PASS."""
    _, _, _, trace = traced
    payload = trace.to_dict()
    assert payload["schema_id"] == CALCULATION_TRACE_SCHEMA_ID
    assert payload["schema_version"] == CALCULATION_TRACE_SCHEMA_VERSION
    assert payload["entry_count"] == len(payload["entries"])
    back = CalculationTrace.from_dict(payload)
    assert back.to_json() == trace.to_json()
    with pytest.raises(ValueError, match="SCHEMA_ID_MISMATCH"):
        CalculationTrace.from_dict({**payload, "schema_id": "x"})
    with pytest.raises(ValueError, match="SCHEMA_VERSION_UNSUPPORTED"):
        CalculationTrace.from_dict({**payload, "schema_version": 77})
    with pytest.raises(ValueError, match="field mismatch"):
        broken = dict(payload)
        broken["entries"] = [dict(payload["entries"][0], extra=1)]
        CalculationTrace.from_dict(broken)
