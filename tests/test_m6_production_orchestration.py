"""M6 production-orchestration correction tests.

PR #172 proved the ProjectInputs -> senior-debt contract/solver bridge. These
tests sit ABOVE that level: ProjectInputs -> run_project_financing_model ->
clean production path.

Economic contract:
  * GEARING_CAP (M6): final senior debt = eligible project cost x maximum
    gearing. DSCR capacity is diagnostic only; DSCR_SCULPTED repayment shapes
    repayment and never resizes the debt.
  * FLAT_DSCR_SCULPTED + TOTAL_PROJECT_USES (COMBINED_MINIMUM): final senior debt
    = min(DSCR capacity, gearing capacity). Unchanged.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.project_factories import create_generic_solar_reference
from app.services.production_financial_authority import (
    ProductionAuthorityClassification,
    classify_production_authority,
    run_clean_production,
)
from finco_core.inputs import (
    DebtSizingMode,
    GearingBasisMode,
    GearingCapRepaymentMethod as Repayment,
)
from financial_engine.financing.project import run_project_financing_model
from financial_engine.financing.project_uses import compute_project_uses
from financial_engine.senior_debt.solver import DSCR_SCULPTING_INFEASIBLE

TOL = 1e-6


def _project(mode, repayment=Repayment.LEVEL_PRINCIPAL, *, gearing=0.95, dscr=1.6):
    base = create_generic_solar_reference()
    return replace(
        base,
        financing=replace(
            base.financing,
            debt_sizing_mode=mode,
            gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
            gearing_cap_repayment_method=repayment,
            gearing_ratio=gearing,
            target_dscr=dscr,
        ),
    )


@pytest.fixture(scope="module")
def combined():
    project = _project(DebtSizingMode.FLAT_DSCR_SCULPTED)
    return project, run_project_financing_model(project)


@pytest.fixture(scope="module")
def m6_level():
    project = _project(DebtSizingMode.GEARING_CAP, Repayment.LEVEL_PRINCIPAL)
    return project, run_project_financing_model(project)


@pytest.fixture(scope="module")
def m6_sculpted():
    project = _project(DebtSizingMode.GEARING_CAP, Repayment.DSCR_SCULPTED)
    return project, run_project_financing_model(project)


def _gearing_capacity(project):
    return compute_project_uses(project).total_project_uses_keur * project.financing.gearing_ratio


# --- A. ProjectInputs -> run_project_financing_model ------------------------

def test_combined_minimum_regression_is_dscr_bound_minimum(combined):
    project, result = combined
    gearing = _gearing_capacity(project)
    assert result.gearing_debt_capacity_keur == pytest.approx(gearing, abs=TOL)
    # Fixture premise: DSCR capacity is the binding (lower) constraint.
    assert result.dscr_debt_capacity_keur < gearing
    assert result.final_senior_commitment_keur == pytest.approx(
        min(result.dscr_debt_capacity_keur, gearing), abs=TOL
    )


def test_m6_level_principal_runs_and_is_gearing_sized(m6_level, combined):
    project, result = m6_level
    gearing = _gearing_capacity(project)
    assert result.gearing_debt_capacity_keur == pytest.approx(gearing, abs=TOL)
    assert result.final_senior_commitment_keur == pytest.approx(gearing, abs=TOL)
    # DSCR capacity is NOT a sizing constraint for M6: debt exceeds it, whereas
    # the COMBINED_MINIMUM run of the same project is capped below the gearing cap.
    assert result.final_senior_commitment_keur > result.dscr_debt_capacity_keur
    assert combined[1].final_senior_commitment_keur < result.final_senior_commitment_keur


def test_m6_dscr_sculpted_feasible_runs_and_does_not_resize_debt(m6_sculpted, m6_level):
    project, result = m6_sculpted
    gearing = _gearing_capacity(project)
    assert result.final_senior_commitment_keur == pytest.approx(gearing, abs=TOL)
    assert result.final_senior_commitment_keur > result.dscr_debt_capacity_keur
    assert result.final_senior_commitment_keur == pytest.approx(
        m6_level[1].final_senior_commitment_keur, abs=TOL
    )


def test_m6_repayment_methods_differ_in_repayment_not_in_debt(m6_level, m6_sculpted):
    level, sculpted = m6_level[1], m6_sculpted[1]
    assert level.final_senior_commitment_keur == pytest.approx(
        sculpted.final_senior_commitment_keur, abs=TOL
    )
    level_ds = [p.senior_principal_keur for p in level.senior_debt_result.periods] \
        if hasattr(level, "senior_debt_result") else None
    # Repayment profile comparison uses whichever senior schedule the result exposes.
    if level_ds is not None:
        sculpted_ds = [p.senior_principal_keur for p in sculpted.senior_debt_result.periods]
        assert level_ds != pytest.approx(sculpted_ds)


def test_m6_infeasible_dscr_sculpting_fails_closed_with_canonical_reason():
    project = _project(
        DebtSizingMode.GEARING_CAP, Repayment.DSCR_SCULPTED, gearing=0.9, dscr=2.5
    )
    with pytest.raises(Exception) as excinfo:
        run_project_financing_model(project)
    assert DSCR_SCULPTING_INFEASIBLE in str(excinfo.value)


def test_input_invariants_are_still_fail_closed():
    base = create_generic_solar_reference()
    with pytest.raises(ValueError, match="GEARING_CAP_REQUIRES_TOTAL_PROJECT_USES"):
        replace(base.financing, debt_sizing_mode=DebtSizingMode.GEARING_CAP,
                gearing_basis_mode=None)
    with pytest.raises(ValueError, match="GEARING_CAP_REPAYMENT_METHOD_REQUIRES_GEARING_CAP"):
        replace(base.financing, gearing_cap_repayment_method=Repayment.DSCR_SCULPTED)


def test_flat_dscr_without_gearing_basis_is_unchanged_and_fails_closed_in_g2a():
    base = create_generic_solar_reference()
    project = replace(base, financing=replace(base.financing, gearing_basis_mode=None))
    with pytest.raises(ValueError, match="G2A_GEARING_BASIS_EXPLICIT_INPUT_REQUIRED"):
        run_project_financing_model(project)


# --- B. ProjectInputs -> run_clean_production -------------------------------

@pytest.mark.parametrize(
    "repayment", [Repayment.LEVEL_PRINCIPAL, Repayment.DSCR_SCULPTED]
)
def test_m6_is_production_ready_and_completes_clean_run(repayment):
    project = _project(DebtSizingMode.GEARING_CAP, repayment)
    decision = classify_production_authority(project)
    assert decision.classification is ProductionAuthorityClassification.CLEAN_PRODUCTION_READY
    run = run_clean_production(project, "Base", project_type="Solar")
    financing = run.g2c_result.financing_result
    # The production policy adds construction IDC / fees / DSRA to the uses, so the
    # eligible cost is the engine's own policy-applied Total Project Uses
    # (gearing_debt_capacity_keur = eligible cost x maximum gearing, asserted by the
    # engine handshake). M6 debt equals that gearing capacity, not DSCR capacity.
    assert financing.gearing_debt_capacity_keur > 0.0
    assert financing.final_senior_commitment_keur == pytest.approx(
        financing.gearing_debt_capacity_keur, abs=TOL
    )
    assert financing.final_senior_commitment_keur > financing.dscr_debt_capacity_keur


def test_combined_minimum_clean_production_regression():
    project = _project(DebtSizingMode.FLAT_DSCR_SCULPTED)
    run = run_clean_production(project, "Base", project_type="Solar")
    financing = run.g2c_result.financing_result
    assert financing.final_senior_commitment_keur == pytest.approx(
        min(financing.dscr_debt_capacity_keur, financing.gearing_debt_capacity_keur), abs=TOL
    )


def test_m6_infeasible_clean_production_fails_closed():
    project = _project(
        DebtSizingMode.GEARING_CAP, Repayment.DSCR_SCULPTED, gearing=0.9, dscr=2.5
    )
    with pytest.raises(Exception) as excinfo:
        run_clean_production(project, "Base", project_type="Solar")
    assert DSCR_SCULPTING_INFEASIBLE in str(excinfo.value)
