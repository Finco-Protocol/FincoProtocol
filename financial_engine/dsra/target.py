"""Dynamic DSRA required-balance schedule builder.

Two target policies are supported: a fixed required balance and a forward
coverage target based on future senior debt service. Construction reserve
funding is separate from the operating target schedule. The builder consumes
canonical period dates, construction flags, senior debt service and explicit
coverage parameters; it does not depend on project identity or external
workbook locations."""
from __future__ import annotations

import math
from datetime import date
from enum import Enum


class DsraTargetPolicy(Enum):
    """DSRA required-balance target policy.

    FIXED_AMOUNT:
        Static scalar requirement_keur used every operating period.
        Preserves PR-3 behavior. Backward-compatible default.

    FORWARD_DEBT_SERVICE_MONTHS:
        Per-period target = next-period Senior DS multiplied by
        coverage_months * periods_per_year / 12.
        Policy-defined from the Generic Wind Reference, Generic Solar Reference, and Generic Storage Reference Operation CF formulas.
    """
    FIXED_AMOUNT = "fixed_amount"
    FORWARD_DEBT_SERVICE_MONTHS = "forward_debt_service_months"


def build_dsra_required_balance_schedule(
    *,
    period_indices: tuple[int, ...],
    period_start_dates: tuple[date, ...],
    period_end_dates: tuple[date, ...],
    is_construction: tuple[bool, ...],
    senior_debt_service_keur: tuple[float, ...],
    coverage_months: int,
    periods_per_year: int,
    policy: DsraTargetPolicy = DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS,
    fixed_amount_keur: float = 0.0,
) -> tuple[float, ...]:
    """Build DSRA required-balance schedule for all model periods.

    Parameters
    ----------
    period_indices:
        Period identifiers in chronological order (no gaps, no duplicates).
    period_start_dates:
        Start date of each period. Must be strictly ascending.
    period_end_dates:
        End date of each period. Must be strictly ascending. end > start for each period.
    is_construction:
        True for construction periods. Target is 0 for construction.
    senior_debt_service_keur:
        Senior debt service per period. Must be same length as period_indices.
        Expected positive-magnitude convention (unsigned cash outflow).
        Negative values are excluded from the coverage window (see sign-convention note).
    coverage_months:
        Number of Operation months of following-period Senior DS to cover.
        Must be > 0 for FORWARD_DEBT_SERVICE_MONTHS policy.
    periods_per_year:
        Canonical model frequency. The workbook Operation formula multiplies
        next-period Senior DS by coverage_months * periods_per_year / 12.
    policy:
        DsraTargetPolicy.FIXED_AMOUNT → fixed_amount_keur every operating period.
        DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS → next-period Senior DS
        multiplied by coverage_months * periods_per_year / 12.
    fixed_amount_keur:
        Required when policy=FIXED_AMOUNT. Must be finite and >= 0.

    Returns
    -------
    Tuple of required balances, one per period (same length as period_indices).
    Construction periods always have required_balance = 0.

    Raises
    ------
    ValueError on:
        - Length mismatch
        - coverage_months <= 0 or invalid periods_per_year for FORWARD policy
        - Non-finite or negative fixed_amount
        - Non-ascending dates
        - end_date <= start_date for any period
        - Duplicate period indices

    SIGN CONVENTION NOTE:
        senior_debt_service_keur must be in UNSIGNED POSITIVE magnitude
        (positive = cash outflow to service debt; 0 = no payment due).
        Negative values are rejected with DSRA_TARGET_NEGATIVE_SENIOR_DS.
        Refinancing is out of scope. Normalise sign at the adapter boundary.

    OPERATION PERIOD RULE:
        For operating period i, the target references Senior DS at i+1.
        The current period's DS is not the Operation target authority.
    """
    n = len(period_indices)
    if n == 0:
        return ()
    if len(period_start_dates) != n:
        raise ValueError(
            f"DSRA_TARGET_LENGTH_MISMATCH: period_start_dates length {len(period_start_dates)} "
            f"!= period_indices length {n}."
        )
    if len(period_end_dates) != n:
        raise ValueError(
            f"DSRA_TARGET_LENGTH_MISMATCH: period_end_dates length {len(period_end_dates)} "
            f"!= period_indices length {n}."
        )
    if len(is_construction) != n:
        raise ValueError(
            f"DSRA_TARGET_LENGTH_MISMATCH: is_construction length {len(is_construction)} "
            f"!= period_indices length {n}."
        )
    if len(senior_debt_service_keur) != n:
        raise ValueError(
            f"DSRA_TARGET_LENGTH_MISMATCH: senior_debt_service_keur length "
            f"{len(senior_debt_service_keur)} != period_indices length {n}."
        )

    # Validate no duplicate indices
    if len(set(period_indices)) != n:
        raise ValueError("DSRA_TARGET_DUPLICATE_PERIOD_INDICES: period_indices contains duplicates.")

    # Validate Senior DS sign: all values must be >= 0 (unsigned positive magnitude).
    for i, ds in enumerate(senior_debt_service_keur):
        if not isinstance(ds, (int, float)) or isinstance(ds, bool):
            raise ValueError(
                f"DSRA_TARGET_INVALID_SENIOR_DS: senior_debt_service_keur[{i}]={ds!r} must be numeric."
            )
        if not math.isfinite(ds):
            raise ValueError(
                f"DSRA_TARGET_INVALID_SENIOR_DS: senior_debt_service_keur[{i}]={ds!r} must be finite."
            )
        if ds < 0.0:
            raise ValueError(
                f"DSRA_TARGET_NEGATIVE_SENIOR_DS: senior_debt_service_keur[{i}]={ds!r} is negative. "
                "DS must be unsigned positive magnitude (cash outflow). "
                "Refinancing is out of scope. Normalise sign at the adapter boundary."
            )

    # Validate dates: each period end > start; start dates strictly ascending.
    for i, (s, e) in enumerate(zip(period_start_dates, period_end_dates)):
        if e <= s:
            raise ValueError(
                f"DSRA_TARGET_INVALID_DATES: period_end_dates[{i}] ({e}) "
                f"<= period_start_dates[{i}] ({s}). End must be strictly after start."
            )
    for i in range(1, n):
        if period_start_dates[i] <= period_start_dates[i - 1]:
            raise ValueError(
                f"DSRA_TARGET_NON_CHRONOLOGICAL_PERIODS: period_start_dates[{i}] "
                f"({period_start_dates[i]}) <= period_start_dates[{i-1}] "
                f"({period_start_dates[i-1]}). Periods must be in strictly ascending order."
            )

    if policy == DsraTargetPolicy.FIXED_AMOUNT:
        if not isinstance(fixed_amount_keur, (int, float)) or isinstance(fixed_amount_keur, bool):
            raise ValueError(
                f"DSRA_TARGET_INVALID_FIXED_AMOUNT: {fixed_amount_keur!r} must be numeric."
            )
        if not math.isfinite(fixed_amount_keur):
            raise ValueError(
                f"DSRA_TARGET_INVALID_FIXED_AMOUNT: {fixed_amount_keur!r} must be finite."
            )
        if fixed_amount_keur < 0.0:
            raise ValueError(
                f"DSRA_TARGET_INVALID_FIXED_AMOUNT: {fixed_amount_keur!r} must be >= 0."
            )
        return tuple(
            0.0 if is_constr else fixed_amount_keur
            for is_constr in is_construction
        )

    # FORWARD_DEBT_SERVICE_MONTHS policy
    if not isinstance(coverage_months, int) or isinstance(coverage_months, bool):
        raise ValueError(
            f"DSRA_TARGET_INVALID_COVERAGE_MONTHS: {coverage_months!r} must be an integer."
        )
    if coverage_months <= 0:
        raise ValueError(
            f"DSRA_TARGET_INVALID_COVERAGE_MONTHS: {coverage_months!r} must be > 0 "
            "for FORWARD_DEBT_SERVICE_MONTHS policy."
        )
    if not isinstance(periods_per_year, int) or isinstance(periods_per_year, bool):
        raise ValueError(
            f"DSRA_TARGET_INVALID_PERIODS_PER_YEAR: {periods_per_year!r} must be an integer."
        )
    if periods_per_year <= 0:
        raise ValueError(
            f"DSRA_TARGET_INVALID_PERIODS_PER_YEAR: {periods_per_year!r} must be > 0."
        )

    targets: list[float] = []

    for i in range(n):
        if is_construction[i]:
            targets.append(0.0)
            continue

        next_pos = i + 1
        if next_pos >= n or is_construction[next_pos]:
            targets.append(0.0)
            continue
        multiplier = coverage_months * periods_per_year / 12.0
        targets.append(senior_debt_service_keur[next_pos] * multiplier)

    return tuple(targets)
