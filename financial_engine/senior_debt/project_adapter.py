"""financial_engine.senior_debt.project_adapter — Generic ProjectInputs → SeniorDebt contract.

Maps a canonical ProjectInputs (from finco_core) plus the operating-model period results
to (SeniorDebtPolicy, SeniorDebtInputs) using only generic field access.

No project-name dispatch, no project-code references, no factory invocations.
The factory may encode project-specific DATA; this module encodes only the generic
field-mapping CONTRACT.

Availability source ownership decision (C3B3A):
    debt_source_ref ops_flag = 179/181 for the final debt period is NOT derivable from
    ``COD + relativedelta(years=senior_tenor_years)`` which always yields 1.0.
    The availability schedule is therefore classified EXPLICIT_INPUT and must be
    provided via SeniorSculptingConfig.debt_service_availability_schedule.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.inputs import ProjectInputs
    from financial_engine.results import OperatingPeriodResult

from finco_core.inputs._models import GearingBasisMode, PeriodFrequency
from financial_engine.senior_debt.inputs import (
    PeriodDebtServiceAvailability,
    PeriodDscrTarget,
    PeriodRate,
    SeniorDebtInputs,
)
from financial_engine.senior_debt.policy import (
    DayCountConvention,
    SeniorDebtPolicy,
    SeniorDebtSizingMode,
)


def build_senior_debt_contract_from_project_inputs(
    project_inputs: "ProjectInputs",
    operating_periods: "tuple[OperatingPeriodResult, ...]",
) -> "tuple[SeniorDebtPolicy, SeniorDebtInputs]":
    """Map a canonical ProjectInputs + operating periods to a clean senior-debt contract.

    Parameters
    ----------
    project_inputs:
        Canonical project inputs (finco_core.inputs.ProjectInputs).
    operating_periods:
        All operating-period results from run_operating_model (includes construction).
        The function selects the first ``N`` operating periods where ``N`` equals
        the number of sculpting-schedule entries (or senior_tenor_years * periods_per_year).

    Returns
    -------
    (SeniorDebtPolicy, SeniorDebtInputs) — ready for solve_senior_debt().
    """
    from finco_core.inputs._models import DebtSizingMode
    from finco_core.inputs.senior_rate_schedule import SeniorRateMode

    fin = project_inputs.financing
    sculpting = fin.senior_sculpting_config
    rate_cfg = fin.senior_debt_interest_config

    # --- Sizing mode mapping ---
    # When an explicit gearing basis is configured (TOTAL_PROJECT_USES), the solver
    # must apply COMBINED_MINIMUM so the gearing cap is enforced.  Without a gearing
    # basis the solver runs DSCR-only (useful for pure DSCR capacity diagnostics).
    raw_mode = fin.debt_sizing_mode
    gearing_basis = fin.gearing_basis_mode
    if raw_mode == DebtSizingMode.FLAT_DSCR_SCULPTED:
        if gearing_basis == GearingBasisMode.TOTAL_PROJECT_USES:
            sizing_mode = SeniorDebtSizingMode.COMBINED_MINIMUM
        elif gearing_basis is None:
            sizing_mode = SeniorDebtSizingMode.DSCR_SCULPTED
        else:
            raise ValueError(
                f"build_senior_debt_contract_from_project_inputs: unsupported "
                f"gearing_basis_mode={gearing_basis!r}. "
                f"Only TOTAL_PROJECT_USES and None are supported."
            )
    else:
        raise ValueError(
            f"build_senior_debt_contract_from_project_inputs: unsupported "
            f"debt_sizing_mode={raw_mode!r}. "
            f"Only FLAT_DSCR_SCULPTED is supported via the clean solver path."
        )

    # --- Day-count convention ---
    from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention
    finco_dc = rate_cfg.day_count
    if finco_dc == SeniorDayCountConvention.ACT_360:
        day_count = DayCountConvention.ACT_360
    elif finco_dc == SeniorDayCountConvention.ACT_365:
        day_count = DayCountConvention.ACT_365
    else:
        raise ValueError(
            f"build_senior_debt_contract_from_project_inputs: unsupported day-count "
            f"convention {finco_dc!r}. Only ACT_360 and ACT_365 are supported. "
            f"FIXED_SEMIANNUAL and EXPLICIT_FRACTIONS are not yet supported."
        )

    # --- Period selection ---
    # Select operating-only periods; map to debt tenor (first N of those).
    op_only = [p for p in operating_periods if p.is_operation]
    frequency = project_inputs.info.period_frequency
    if frequency == PeriodFrequency.SEMESTRIAL:
        periods_per_year = 2
    else:
        raise ValueError(
            f"build_senior_debt_contract_from_project_inputs: unsupported period "
            f"frequency {frequency!r}. Only SEMESTRIAL (2 periods/year) is supported "
            f"by the clean senior-debt source contract. ANNUAL and QUARTERLY require "
            f"end-to-end operating-period proof before enablement."
        )
    tenor_periods = fin.senior_tenor_years * periods_per_year

    debt_periods = op_only[:tenor_periods]
    if len(debt_periods) < tenor_periods:
        raise ValueError(
            f"Not enough operating periods for tenor: need {tenor_periods}, "
            f"got {len(debt_periods)}"
        )

    first_idx = debt_periods[0].period_index
    last_idx = debt_periods[-1].period_index

    # --- Per-period rates ---
    if rate_cfg.rate_schedule.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE:
        explicit_rates = rate_cfg.rate_schedule.explicit_all_in_rates
        if len(explicit_rates) < tenor_periods:
            raise ValueError(
                f"explicit_all_in_rates has {len(explicit_rates)} entries, "
                f"need {tenor_periods}"
            )
        period_rates = tuple(
            PeriodRate(period_index=p.period_index, annual_rate=explicit_rates[i])
            for i, p in enumerate(debt_periods)
        )
    else:
        raise ValueError(
            f"build_senior_debt_contract_from_project_inputs: unsupported "
            f"rate mode {rate_cfg.rate_schedule.mode!r}. "
            f"Only EXPLICIT_ALL_IN_SCHEDULE is supported."
        )

    # --- DSCR targets ---
    dscr_targets: tuple[PeriodDscrTarget, ...] = ()
    if sculpting.target_dscr_schedule:
        if len(sculpting.target_dscr_schedule) < tenor_periods:
            raise ValueError(
                f"target_dscr_schedule has {len(sculpting.target_dscr_schedule)} entries, "
                f"need {tenor_periods}"
            )
        dscr_targets = tuple(
            PeriodDscrTarget(
                period_index=p.period_index,
                target_dscr=sculpting.target_dscr_schedule[i],
            )
            for i, p in enumerate(debt_periods)
        )

    # --- Debt-service availability ---
    avail: tuple[PeriodDebtServiceAvailability, ...] = ()
    if sculpting.debt_service_availability_schedule:
        if len(sculpting.debt_service_availability_schedule) < tenor_periods:
            raise ValueError(
                f"debt_service_availability_schedule has "
                f"{len(sculpting.debt_service_availability_schedule)} entries, "
                f"need {tenor_periods}"
            )
        avail = tuple(
            PeriodDebtServiceAvailability(
                period_index=p.period_index,
                availability_fraction=sculpting.debt_service_availability_schedule[i],
            )
            for i, p in enumerate(debt_periods)
        )

    # --- Gearing contract ---
    # When COMBINED_MINIMUM is active, wire the gearing cap from the canonical
    # Total Project Uses authority.  Fail closed if gearing_basis_mode is set
    # but the resulting eligible cost would be zero (contract violation).
    if sizing_mode == SeniorDebtSizingMode.COMBINED_MINIMUM:
        from financial_engine.financing.project_uses import compute_project_uses
        project_uses = compute_project_uses(project_inputs)
        eligible_cost = project_uses.total_project_uses_keur
        maximum_gearing = fin.gearing_ratio
        if eligible_cost <= 0.0:
            raise ValueError(
                "GEARING_BASIS_ELIGIBLE_COST_ZERO: "
                f"gearing_basis_mode={gearing_basis!r} but computed Total Project Uses "
                f"is {eligible_cost}. Cannot apply gearing cap with zero eligible basis."
            )
    else:
        eligible_cost = 0.0
        maximum_gearing = None

    policy = SeniorDebtPolicy(
        policy_id="clean-project-senior-debt-v1",
        policy_version="1.0.0",
        sizing_mode=sizing_mode,
        target_dscr=fin.target_dscr,
        maximum_gearing=maximum_gearing,
        annual_fixed_rate=None,
        periods_per_year=periods_per_year,
        day_count_convention=day_count,
        repayment_start_period_index=first_idx,
        maturity_period_index=last_idx,
        convergence_tolerance_keur=1e-4,
        convergence_relative_tolerance=1e-9,
        maximum_iterations=200,
        permit_terminal_balloon=True,
        damping_alpha=1.0,
    )

    # Solver seed only — has no effect on the converged authoritative result.
    # For Generic Solar/Wind (zero financing costs) capex_items() == hard_capex ==
    # eligible_project_cost_keur, so the two formulations are equivalent.
    # For projects with financing costs the seed underestimates eligible_cost but
    # convergence to the correct COMBINED_MINIMUM result is unaffected.
    inputs = SeniorDebtInputs(
        eligible_project_cost_keur=eligible_cost,
        initial_debt_guess_keur=(
            fin.fixed_debt_keur
            if fin.fixed_debt_keur is not None and fin.fixed_debt_keur > 0.0
            else fin.gearing_ratio * sum(
                item.amount_keur for item in project_inputs.capex.capex_items()
            )
        ),
        period_rates=period_rates,
        explicit_principal_schedule=None,
        opening_debt_balance_keur=0.0,
        period_dscr_targets=dscr_targets,
        period_debt_service_availability=avail,
    )

    return policy, inputs
