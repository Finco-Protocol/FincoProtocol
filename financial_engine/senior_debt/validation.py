"""financial_engine.senior_debt.validation — Input validation for Phase 2C."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from financial_engine.senior_debt.inputs import SeniorDebtInputs
    from financial_engine.senior_debt.policy import SeniorDebtPolicy


def validate_senior_debt_inputs(
    inputs: "SeniorDebtInputs",
    policy: "SeniorDebtPolicy",
    known_period_indices: frozenset[int],
) -> list[str]:
    """Return a list of error messages (empty = valid).

    Warnings are prefixed with 'WARNING:' and do not indicate an invalid
    configuration — they surface conditions the caller should surface to
    the user but that do not prevent the solver from running.
    """
    from financial_engine.senior_debt.policy import SeniorDebtSizingMode

    errors: list[str] = []

    # --- Policy fields ---

    # target_dscr: must be finite AND > 1.0 (checked separately)
    if not math.isfinite(policy.target_dscr):
        errors.append(f"target_dscr must be finite, got {policy.target_dscr}")
    elif policy.target_dscr <= 1.0:
        errors.append(f"target_dscr must be > 1.0, got {policy.target_dscr}")

    # maximum_gearing: must be finite when provided, and in (0, 1]
    if policy.maximum_gearing is not None:
        if not math.isfinite(policy.maximum_gearing):
            errors.append(
                f"maximum_gearing must be finite, got {policy.maximum_gearing}"
            )
        elif not (0.0 < policy.maximum_gearing <= 1.0):
            errors.append(
                f"maximum_gearing must be in (0, 1], got {policy.maximum_gearing}"
            )

    # maturity >= repayment_start
    if policy.maturity_period_index < policy.repayment_start_period_index:
        errors.append(
            f"maturity_period_index ({policy.maturity_period_index}) "
            f"must be >= repayment_start_period_index ({policy.repayment_start_period_index})"
        )

    # repayment_start_period_index must be a known period (if known_period_indices is non-empty)
    if known_period_indices and policy.repayment_start_period_index not in known_period_indices:
        errors.append(
            f"repayment_start_period_index ({policy.repayment_start_period_index}) "
            f"is not in known_period_indices"
        )

    # maturity_period_index must be a known period (if known_period_indices is non-empty)
    if known_period_indices and policy.maturity_period_index not in known_period_indices:
        errors.append(
            f"maturity_period_index ({policy.maturity_period_index}) "
            f"is not in known_period_indices"
        )

    # convergence_tolerance_keur: must be finite and >= 0
    if not math.isfinite(policy.convergence_tolerance_keur):
        errors.append("convergence_tolerance_keur must be finite")
    elif policy.convergence_tolerance_keur < 0:
        errors.append("convergence_tolerance_keur must be >= 0")

    # convergence_relative_tolerance: must be finite and >= 0
    if not math.isfinite(policy.convergence_relative_tolerance):
        errors.append("convergence_relative_tolerance must be finite")
    elif policy.convergence_relative_tolerance < 0:
        errors.append("convergence_relative_tolerance must be >= 0")

    # maximum_iterations: must be >= 1
    if policy.maximum_iterations < 1:
        errors.append("maximum_iterations must be >= 1")

    # damping_alpha: must be in (0, 1]
    if not (0.0 < policy.damping_alpha <= 1.0):
        errors.append(f"damping_alpha must be in (0, 1], got {policy.damping_alpha}")

    # annual_fixed_rate: must be >= 0 if provided
    if policy.annual_fixed_rate is not None:
        if not math.isfinite(policy.annual_fixed_rate):
            errors.append(f"Non-finite policy.annual_fixed_rate: {policy.annual_fixed_rate}")
        elif policy.annual_fixed_rate < 0:
            errors.append(
                f"annual_fixed_rate must be >= 0, got {policy.annual_fixed_rate}; "
                "negative rates are not permitted"
            )

    # --- Input fields ---
    if not math.isfinite(inputs.eligible_project_cost_keur):
        errors.append("eligible_project_cost_keur must be finite")
    elif inputs.eligible_project_cost_keur < 0:
        errors.append("eligible_project_cost_keur must be >= 0")

    if not math.isfinite(inputs.initial_debt_guess_keur):
        errors.append("initial_debt_guess_keur must be finite")
    elif inputs.initial_debt_guess_keur < 0:
        errors.append("initial_debt_guess_keur must be >= 0")

    if not math.isfinite(inputs.opening_debt_balance_keur):
        errors.append("opening_debt_balance_keur must be finite")
    elif inputs.opening_debt_balance_keur < 0:
        errors.append("opening_debt_balance_keur must be >= 0")

    # --- Period rates ---
    seen_rate_periods: set[int] = set()
    prev_period_index: int | None = None
    for pr in inputs.period_rates:
        if pr.period_index in seen_rate_periods:
            errors.append(f"Duplicate period_rate for period_index={pr.period_index}")
        seen_rate_periods.add(pr.period_index)
        if known_period_indices and pr.period_index not in known_period_indices:
            errors.append(f"period_rate references unknown period_index={pr.period_index}")
        if not math.isfinite(pr.annual_rate):
            errors.append(f"Non-finite annual_rate for period_index={pr.period_index}")
        elif pr.annual_rate < 0:
            errors.append(
                f"Negative annual_rate {pr.annual_rate} for period_index={pr.period_index}; "
                "negative interest rates are not permitted"
            )
        # Order check: period_index must be strictly increasing
        if prev_period_index is not None and pr.period_index <= prev_period_index:
            errors.append(
                f"period_rates are out of order: period_index={pr.period_index} "
                f"follows period_index={prev_period_index}; indices must be strictly increasing"
            )
        prev_period_index = pr.period_index

    # Rate coverage: when annual_fixed_rate is None, every required debt period must
    # have an explicit period_rate (no fallback exists for uncovered periods).
    if policy.annual_fixed_rate is None and known_period_indices:
        repayment_periods = frozenset(
            idx for idx in known_period_indices
            if policy.repayment_start_period_index <= idx <= policy.maturity_period_index
        )
        uncovered = repayment_periods - seen_rate_periods
        if uncovered:
            errors.append(
                f"annual_fixed_rate is None and {len(uncovered)} required debt period(s) have "
                f"no explicit period_rate: {sorted(uncovered)[:5]}{'...' if len(uncovered) > 5 else ''}"
            )
    elif not inputs.period_rates and policy.annual_fixed_rate is None:
        errors.append(
            "No period_rates provided and policy.annual_fixed_rate is None; "
            "at least one source of interest rates is required"
        )

    # --- GEARING_CAP / COMBINED_MINIMUM require maximum_gearing ---
    if policy.sizing_mode in (
        SeniorDebtSizingMode.GEARING_CAP, SeniorDebtSizingMode.COMBINED_MINIMUM
    ):
        if policy.maximum_gearing is None:
            errors.append(
                f"sizing_mode={policy.sizing_mode.value} requires maximum_gearing to be set"
            )

    # --- PeriodDscrTarget ---
    seen_dscr_periods: set[int] = set()
    for dt in inputs.period_dscr_targets:
        if isinstance(dt.period_index, bool):
            errors.append(
                f"PeriodDscrTarget period_index must not be a boolean, got {dt.period_index!r}"
            )
            continue
        if isinstance(dt.target_dscr, bool):
            errors.append(
                f"PeriodDscrTarget period_index={dt.period_index}: "
                "target_dscr must not be a boolean"
            )
        elif dt.period_index in seen_dscr_periods:
            errors.append(
                f"Duplicate PeriodDscrTarget for period_index={dt.period_index}"
            )
        else:
            if known_period_indices and dt.period_index not in known_period_indices:
                errors.append(
                    f"PeriodDscrTarget references unknown period_index={dt.period_index}"
                )
            if not math.isfinite(dt.target_dscr):
                errors.append(
                    f"PeriodDscrTarget period_index={dt.period_index}: "
                    f"target_dscr must be finite, got {dt.target_dscr}"
                )
            elif dt.target_dscr <= 1.0:
                errors.append(
                    f"PeriodDscrTarget period_index={dt.period_index}: "
                    f"target_dscr must be > 1.0, got {dt.target_dscr}"
                )
        seen_dscr_periods.add(dt.period_index)

    # --- PeriodDebtServiceAvailability ---
    seen_avail_periods: set[int] = set()
    for av in inputs.period_debt_service_availability:
        if isinstance(av.period_index, bool):
            errors.append(
                f"PeriodDebtServiceAvailability period_index must not be a boolean, got {av.period_index!r}"
            )
            continue
        if isinstance(av.availability_fraction, bool):
            errors.append(
                f"PeriodDebtServiceAvailability period_index={av.period_index}: "
                "availability_fraction must not be a boolean"
            )
        elif av.period_index in seen_avail_periods:
            errors.append(
                f"Duplicate PeriodDebtServiceAvailability for period_index={av.period_index}"
            )
        else:
            if known_period_indices and av.period_index not in known_period_indices:
                errors.append(
                    f"PeriodDebtServiceAvailability references unknown "
                    f"period_index={av.period_index}"
                )
            if not math.isfinite(av.availability_fraction):
                errors.append(
                    f"PeriodDebtServiceAvailability period_index={av.period_index}: "
                    f"availability_fraction must be finite, got {av.availability_fraction}"
                )
            elif not (0.0 <= av.availability_fraction <= 1.0):
                errors.append(
                    f"PeriodDebtServiceAvailability period_index={av.period_index}: "
                    f"availability_fraction must be in [0.0, 1.0], "
                    f"got {av.availability_fraction}"
                )
        seen_avail_periods.add(av.period_index)

    # --- EXPLICIT_SCHEDULE requires principal schedule ---
    if policy.sizing_mode == SeniorDebtSizingMode.EXPLICIT_SCHEDULE:
        if inputs.explicit_principal_schedule is None:
            errors.append("EXPLICIT_SCHEDULE mode requires explicit_principal_schedule")
        else:
            seen_principal_periods: set[int] = set()
            cumulative_principal: float = 0.0
            prev_principal_index: int | None = None
            for pp in inputs.explicit_principal_schedule:
                if pp.period_index in seen_principal_periods:
                    errors.append(
                        f"Duplicate explicit_principal for period_index={pp.period_index}"
                    )
                seen_principal_periods.add(pp.period_index)
                if known_period_indices and pp.period_index not in known_period_indices:
                    errors.append(
                        f"explicit_principal references unknown period_index={pp.period_index}"
                    )
                # Out-of-order check: period_index must be strictly increasing
                if prev_principal_index is not None and pp.period_index <= prev_principal_index:
                    errors.append(
                        f"explicit_principal_schedule is out of order: period_index={pp.period_index} "
                        f"follows period_index={prev_principal_index}; indices must be strictly increasing"
                    )
                prev_principal_index = pp.period_index
                # Must be within the permitted repayment window
                if (pp.period_index < policy.repayment_start_period_index
                        or pp.period_index > policy.maturity_period_index):
                    errors.append(
                        f"explicit_principal period_index={pp.period_index} is outside the permitted "
                        f"repayment window [{policy.repayment_start_period_index}, "
                        f"{policy.maturity_period_index}]"
                    )
                if not math.isfinite(pp.principal_keur):
                    errors.append(
                        f"Non-finite principal_keur for period_index={pp.period_index}"
                    )
                elif pp.principal_keur < 0:
                    errors.append(
                        f"Negative principal_keur for period_index={pp.period_index}"
                    )
                else:
                    cumulative_principal += pp.principal_keur

            # Validate cumulative principal against opening debt balance
            opening = inputs.opening_debt_balance_keur
            tol = policy.convergence_tolerance_keur
            if math.isfinite(cumulative_principal) and math.isfinite(opening) and math.isfinite(tol):
                if cumulative_principal > opening + tol:
                    errors.append(
                        f"cumulative explicit principal {cumulative_principal:.3f} kEUR exceeds "
                        f"opening debt {opening:.3f} kEUR; "
                        "use INVALID_INPUT to reject over-repayment"
                    )

    return errors
