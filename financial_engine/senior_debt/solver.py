"""financial_engine.senior_debt.solver — Fixed-point senior debt sizing solver.

Iteration sequence (DSCR_SCULPTED / COMBINED_MINIMUM):
  1.  Start from initial_debt_guess.
  2.  Forward-roll the schedule to get per-period interest (rolling balance).
  3.  Pass period interest into the Phase 2B tax/CFADS calculation.
  4.  Recalculate cash tax and canonical CFADS.
  5.  Backward-induct DSCR capacity from the updated CFADS.
  6.  Apply optional damping: D_new = alpha*D_candidate + (1-alpha)*D_old.
  7.  Compare per-field convergence using abs OR rel tolerance.
  8.  Repeat until convergence or maximum_iterations.

Convergence contract:
  Tracked fields: debt_size, opening, interest, principal, closing, CFADS, cash_tax
  A field pair (a, b) is converged when:
    |a - b| <= convergence_tolerance_keur   (absolute)
    OR |a - b| / max(|a|, |b|, 1.0) <= convergence_relative_tolerance  (relative)
  ALL tracked fields for ALL periods must satisfy convergence simultaneously.
  Both convergence_tolerance_keur and convergence_relative_tolerance have real semantics.

Finalisation contract:
  After the outer loop converges, a finalisation sub-loop enforces the exact handshake
  invariant: the exact senior_interest_keur in the returned result must be exactly the
  interest input used in the final authoritative tax/CFADS calculation.

  Algorithm (per iteration of the sub-loop):
    1. Build candidate_rows from current CFADS at final D.
    2. Extract candidate_interest EXACTLY from candidate_rows (not a copy or approximation).
    3. Call tax_cfads_fn(candidate_interest) → get new_cfads, new_cash_tax.
    4. Build verify_rows from new_cfads.
    5. Compare candidate_rows vs verify_rows using the SAME convergence contract
       (abs OR rel, all fields: interest, principal, closing, CFADS, cash_tax).
    6. If converged: return candidate_rows as the authoritative result.
       The last tax_cfads_fn call received candidate_interest, which is EXACTLY
       the interest in candidate_rows (= returned rows). Invariant holds by construction.
    7. If not converged: set CFADS = new_cfads and repeat.

  If the sub-loop reaches _MAX_FINALISATION_ITERATIONS without convergence:
    termination_reason = FINALISATION_NOT_CONVERGED
    is_authoritative = False
    The caller raises SeniorDebtNonConvergenceError.

Repayment method (Option B — fixed documented combinations):
  DSCR_SCULPTED sizing   → DSCR_SCULPTED repayment
  GEARING_CAP sizing     → LEVEL_PRINCIPAL repayment
  COMBINED_MINIMUM sizing→ DSCR_SCULPTED repayment (sizing and repayment are separate;
                           amortisation never switches to level-principal when gearing binds)
  EXPLICIT_SCHEDULE sizing→ EXPLICIT repayment

Repayment method (Issue 3 — Option B):
  Fixed documented combinations derived from sizing_mode:
    DSCR_SCULPTED sizing   → DSCR_SCULPTED repayment
    GEARING_CAP sizing     → LEVEL_PRINCIPAL repayment
    COMBINED_MINIMUM sizing→ DSCR_SCULPTED repayment (sizing and repayment are separate;
                             amortisation never switches to level-principal when gearing binds)
    EXPLICIT_SCHEDULE sizing→ EXPLICIT repayment

Non-convergence → termination_reason=MAX_ITERATIONS_REACHED; result has
is_authoritative=False.

GEARING_CAP: D = eligible_project_cost × maximum_gearing; level-principal amort;
one iteration (no sizing loop). Tax feedback computed once; finalisation applied.

COMBINED_MINIMUM: run DSCR sizing loop to convergence, then apply gearing cap and
take the minimum; forward roll with DSCR-sculpted repayment at that final D.

EXPLICIT_SCHEDULE: validate that explicit schedule sums to opening balance (within
tolerance); forward roll once with exact explicit principals; finalisation applied.

Determinism guarantee: same input → same iteration count → same schedules.
No random damping. No mutable global state.
"""
from __future__ import annotations

import math
from typing import Callable, TYPE_CHECKING

from financial_engine.senior_debt.interest import (
    build_rate_map,
    period_day_fraction,
    period_interest,
)
from financial_engine.senior_debt.models import SeniorDebtSchedules, SolverDiagnostics
from financial_engine.senior_debt.policy import SeniorDebtPolicy, SeniorDebtSizingMode
from financial_engine.senior_debt.sculpting import (
    PeriodDebtRow,
    build_explicit_schedule,
    build_level_principal_schedule,
    build_schedule,
)

if TYPE_CHECKING:
    from financial_engine.results import OperatingPeriodResult
    from financial_engine.senior_debt.inputs import SeniorDebtInputs


# Type alias for the tax+CFADS callable the solver calls on each iteration.
# Signature: (period_interest_map: dict[int, float]) -> (cfads_by_period, cash_tax_by_period)
TaxCfadsCallable = Callable[
    [dict[int, float]],        # senior_interest_by_period
    tuple[dict[int, float], dict[int, float]],  # (cfads_by_period, cash_tax_by_period)
]

# Maximum finalisation sub-loop iterations to enforce interest/CFADS self-consistency.
_MAX_FINALISATION_ITERATIONS = 20


# ---------------------------------------------------------------------------
# Convergence helpers (Issue 2)
# ---------------------------------------------------------------------------

def _field_converged(a: float, b: float, abs_tol: float, rel_tol: float) -> bool:
    """True if the field pair satisfies absolute OR relative convergence criterion."""
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    if rel_tol > 0.0:
        ref = max(abs(a), abs(b), 1.0)
        if diff / ref <= rel_tol:
            return True
    return False


def _schedules_converged(
    rows_a: tuple[PeriodDebtRow, ...],
    rows_b: tuple[PeriodDebtRow, ...],
    cfads_a: dict[int, float],
    cfads_b: dict[int, float],
    cash_tax_a: dict[int, float],
    cash_tax_b: dict[int, float],
    D_a: float,
    D_b: float,
    abs_tol: float,
    rel_tol: float,
) -> bool:
    """True if ALL tracked fields (debt, schedule, CFADS, cash_tax) are converged.

    Convergence for each field: |Δ| <= abs_tol  OR  |Δ|/max(|a|,|b|,1) <= rel_tol
    """
    if not _field_converged(D_a, D_b, abs_tol, rel_tol):
        return False
    for ra, rb in zip(rows_a, rows_b):
        idx = ra.period_index
        if not _field_converged(ra.opening_keur, rb.opening_keur, abs_tol, rel_tol):
            return False
        if not _field_converged(ra.interest_keur, rb.interest_keur, abs_tol, rel_tol):
            return False
        if not _field_converged(ra.principal_keur, rb.principal_keur, abs_tol, rel_tol):
            return False
        if not _field_converged(ra.closing_keur, rb.closing_keur, abs_tol, rel_tol):
            return False
        ca_val = cfads_a.get(idx, 0.0)
        cb_val = cfads_b.get(idx, 0.0)
        if not _field_converged(ca_val, cb_val, abs_tol, rel_tol):
            return False
        ta_val = cash_tax_a.get(idx, 0.0)
        tb_val = cash_tax_b.get(idx, 0.0)
        if not _field_converged(ta_val, tb_val, abs_tol, rel_tol):
            return False
    return True


def _compute_max_abs_diff(
    rows_a: tuple[PeriodDebtRow, ...],
    rows_b: tuple[PeriodDebtRow, ...],
    cfads_a: dict[int, float],
    cfads_b: dict[int, float],
    cash_tax_a: dict[int, float],
    cash_tax_b: dict[int, float],
    D_a: float,
    D_b: float,
) -> float:
    """Return the maximum absolute difference across all tracked fields."""
    max_diff = abs(D_a - D_b)
    for ra, rb in zip(rows_a, rows_b):
        idx = ra.period_index
        max_diff = max(max_diff, abs(ra.opening_keur - rb.opening_keur))
        max_diff = max(max_diff, abs(ra.interest_keur - rb.interest_keur))
        max_diff = max(max_diff, abs(ra.principal_keur - rb.principal_keur))
        max_diff = max(max_diff, abs(ra.closing_keur - rb.closing_keur))
        max_diff = max(max_diff, abs(cfads_a.get(idx, 0.0) - cfads_b.get(idx, 0.0)))
        max_diff = max(max_diff, abs(cash_tax_a.get(idx, 0.0) - cash_tax_b.get(idx, 0.0)))
    return max_diff


# ---------------------------------------------------------------------------
# Resolution helpers — build period maps from inputs + policy fallbacks
# ---------------------------------------------------------------------------

def build_dscr_target_map(
    policy: SeniorDebtPolicy,
    inputs: "SeniorDebtInputs",
    period_indices: tuple[int, ...],
) -> dict[int, float]:
    """Resolve the per-period DSCR ratio used in backward induction and sculpting.

    Per-period PeriodDscrTarget values override the scalar policy fallback.
    Periods not covered by the schedule use policy.target_dscr.
    """
    overrides = {dt.period_index: dt.target_dscr for dt in inputs.period_dscr_targets}
    return {idx: overrides.get(idx, policy.target_dscr) for idx in period_indices}


def build_debt_service_availability_map(
    inputs: "SeniorDebtInputs",
    period_indices: tuple[int, ...],
) -> dict[int, float]:
    """Resolve per-period debt-service availability fraction.

    Explicit PeriodDebtServiceAvailability entries override the default.
    Periods with no explicit entry fall back to 1.0 (full availability).
    """
    explicit = {
        av.period_index: av.availability_fraction
        for av in inputs.period_debt_service_availability
    }
    return {idx: explicit.get(idx, 1.0) for idx in period_indices}


# ---------------------------------------------------------------------------
# BLOCKER 1: Backward DSCR capacity via backward induction
# ---------------------------------------------------------------------------

def _backward_dscr_capacity(
    cfads_by: dict[int, float],
    rate_map: dict[int, float],
    period_start_end: dict[int, tuple],
    period_indices: tuple[int, ...],
    policy: SeniorDebtPolicy,
    dscr_map: dict[int, float] | None = None,
    availability_map: dict[int, float] | None = None,
) -> float:
    """Compute maximum debt capacity via backward induction.

    Starting from closing_maturity = 0, work backwards:
      allowed_ds_t = max(0, cfads_t / resolved_dscr_t) * resolved_availability_t
      opening_t    = (closing_t + allowed_ds_t) / (1 + f_t)
    where f_t = rate_t * day_frac_t.
    """
    repayment_ids = [
        idx for idx in period_indices
        if policy.repayment_start_period_index <= idx <= policy.maturity_period_index
    ]
    if not repayment_ids:
        return 0.0

    closing = 0.0
    for idx in reversed(repayment_ids):
        target_dscr = dscr_map[idx] if dscr_map is not None else policy.target_dscr
        availability = availability_map[idx] if availability_map is not None else 1.0
        cfads = cfads_by.get(idx, 0.0)
        ds = max(0.0, cfads / target_dscr) * availability if target_dscr > 0 else 0.0
        rate = rate_map.get(idx, 0.0)
        start, end = period_start_end[idx]
        f = rate * period_day_fraction(start, end, policy.day_count_convention)
        denom = 1.0 + f
        opening = (closing + ds) / denom if denom > 1e-15 else closing + ds
        closing = max(0.0, opening)

    return closing


# ---------------------------------------------------------------------------
# BLOCKER 2: Authoritative forward roll (single pass, rolling balance)
# ---------------------------------------------------------------------------

def _forward_roll(
    opening_keur: float,
    period_indices: tuple[int, ...],
    rate_map: dict[int, float],
    period_start_end: dict[int, tuple],
    cfads_by: dict[int, float],
    policy: SeniorDebtPolicy,
    repayment_method_str: str,
    explicit_by: dict[int, float] | None = None,
    dscr_map: dict[int, float] | None = None,
    availability_map: dict[int, float] | None = None,
) -> tuple[PeriodDebtRow, ...]:
    """Single-pass authoritative forward roll.

    Interest is computed from the rolling balance — the identity of this function.
    For dscr_sculpted repayment:
      allowed_ds[p] = max(0, CFADS[p] / resolved_dscr[p]) * resolved_availability[p]
      principal[p]  = max(0, min(allowed_ds[p] - interest[p], balance[p]))
    """
    rows: list[PeriodDebtRow] = []
    balance = opening_keur

    repayment_ids = [
        idx for idx in period_indices
        if policy.repayment_start_period_index <= idx <= policy.maturity_period_index
    ]
    n_repayment = len(repayment_ids)
    level_installment = opening_keur / n_repayment if n_repayment > 0 else 0.0

    for idx in period_indices:
        rate = rate_map.get(idx, 0.0)
        start, end = period_start_end[idx]
        day_frac = period_day_fraction(start, end, policy.day_count_convention)
        interest = balance * rate * day_frac  # ROLLING BALANCE — identity test

        in_repayment = (
            policy.repayment_start_period_index <= idx <= policy.maturity_period_index
        )

        if not in_repayment:
            principal = 0.0
        elif repayment_method_str == "dscr_sculpted":
            cfads = cfads_by.get(idx, 0.0)
            target_dscr = dscr_map[idx] if dscr_map is not None else policy.target_dscr
            availability = availability_map[idx] if availability_map is not None else 1.0
            ds = max(0.0, cfads / target_dscr) * availability if target_dscr > 0 else 0.0
            principal = max(0.0, ds - interest)
            principal = min(principal, balance)  # safety floor
        elif repayment_method_str == "level_principal":
            principal = min(level_installment, balance)
        elif repayment_method_str == "explicit":
            # NO CAPPING per Blocker 5 — exact explicit schedule
            principal = (explicit_by or {}).get(idx, 0.0)
        else:
            raise ValueError(f"Unknown repayment_method_str: {repayment_method_str!r}")

        debt_service = interest + principal
        closing = max(0.0, balance - principal)

        cfads_val = cfads_by.get(idx, 0.0)
        dscr_val = (
            cfads_val / debt_service
            if debt_service > 0.0 and math.isfinite(cfads_val)
            else None
        )

        rows.append(PeriodDebtRow(
            period_index=idx,
            opening_keur=balance,
            interest_keur=interest,
            principal_keur=principal,
            debt_service_keur=debt_service,
            closing_keur=closing,
            dscr=dscr_val,
        ))
        balance = closing

    return tuple(rows)


# ---------------------------------------------------------------------------
# Issue 1: Finalisation sub-loop — enforce interest/CFADS self-consistency
# ---------------------------------------------------------------------------

def _finalise_authoritative(
    D: float,
    period_indices: tuple[int, ...],
    rate_map: dict[int, float],
    period_start_end: dict[int, tuple],
    cfads_by: dict[int, float],
    policy: SeniorDebtPolicy,
    repayment_str: str,
    tax_cfads_fn: TaxCfadsCallable,
    explicit_by: dict[int, float] | None = None,
    dscr_map: dict[int, float] | None = None,
    availability_map: dict[int, float] | None = None,
) -> tuple[tuple[PeriodDebtRow, ...], dict[int, float], dict[int, float], bool]:
    """After outer loop convergence, ensure schedule is self-consistent with tax/CFADS.

    Invariant by construction:
      The last tax_cfads_fn call receives candidate_interest (from candidate_rows).
      We return candidate_rows — so returned interest EXACTLY equals last tax input.

    Returns (rows, cfads, cash_tax, converged: bool).
    converged=False signals FINALISATION_NOT_CONVERGED; caller sets is_authoritative=False.
    """
    abs_tol = policy.convergence_tolerance_keur
    rel_tol = policy.convergence_relative_tolerance
    prev_cash_tax: dict[int, float] = {idx: 0.0 for idx in period_indices}

    for _ in range(_MAX_FINALISATION_ITERATIONS):
        # candidate_rows: schedule with current CFADS at debt D
        candidate_rows = _forward_roll(
            D, period_indices, rate_map, period_start_end,
            cfads_by, policy, repayment_str, explicit_by=explicit_by,
            dscr_map=dscr_map, availability_map=availability_map,
        )
        # Last tax call with candidate interest — new_cfads is RESPONSE to candidate_rows
        candidate_interest = {r.period_index: r.interest_keur for r in candidate_rows}
        new_cfads, new_cash_tax = tax_cfads_fn(candidate_interest)
        # verify_rows: what the schedule looks like if we use the response CFADS
        verify_rows = _forward_roll(
            D, period_indices, rate_map, period_start_end,
            new_cfads, policy, repayment_str, explicit_by=explicit_by,
            dscr_map=dscr_map, availability_map=availability_map,
        )
        # Converged when candidate_rows ≈ verify_rows across ALL fields (same contract as outer loop)
        if _schedules_converged(
            candidate_rows, verify_rows,
            cfads_by, new_cfads,
            prev_cash_tax, new_cash_tax,
            D, D,
            abs_tol, rel_tol,
        ):
            # Return candidate_rows: last tax call received candidate_interest,
            # which is EXACTLY the interest in candidate_rows. Invariant holds.
            return candidate_rows, new_cfads, new_cash_tax, True
        prev_cash_tax = new_cash_tax
        cfads_by = new_cfads

    # Exhausted finalisation iterations — not self-consistent
    candidate_rows = _forward_roll(
        D, period_indices, rate_map, period_start_end,
        cfads_by, policy, repayment_str, explicit_by=explicit_by,
        dscr_map=dscr_map, availability_map=availability_map,
    )
    return candidate_rows, cfads_by, prev_cash_tax, False


# ---------------------------------------------------------------------------
# Diagnostic factory
# ---------------------------------------------------------------------------

def _make_diag(
    *,
    converged: bool,
    iteration: int,
    initial_guess: float,
    final_d: float,
    max_abs_diff: float,
    binding: str | None,
    termination_reason: str,
    dscr_capacity: float | None = None,
    gearing_capacity: float | None = None,
) -> SolverDiagnostics:
    return SolverDiagnostics(
        converged=converged,
        iteration_count=iteration,
        initial_debt_guess_keur=initial_guess,
        final_debt_size_keur=final_d,
        maximum_absolute_difference_keur=max_abs_diff,
        maximum_relative_difference=max_abs_diff / max(abs(final_d), 1.0),
        binding_constraint=binding,
        termination_reason=termination_reason,
        is_authoritative=(termination_reason == "CONVERGED"),
        dscr_debt_capacity_keur=(
            final_d if dscr_capacity is None and binding == "DSCR" else dscr_capacity
        ),
        gearing_debt_capacity_keur=(
            final_d if gearing_capacity is None and binding == "GEARING" else gearing_capacity
        ),
    )



# ---------------------------------------------------------------------------
# Schedule → SeniorDebtSchedules
# ---------------------------------------------------------------------------

def _to_schedules(
    rows: tuple[PeriodDebtRow, ...],
    debt_size_keur: float,
    binding: str | None,
    diag: SolverDiagnostics,
) -> SeniorDebtSchedules:
    return SeniorDebtSchedules(
        period_indices=tuple(r.period_index for r in rows),
        senior_debt_opening_keur=tuple(r.opening_keur for r in rows),
        senior_interest_keur=tuple(r.interest_keur for r in rows),
        senior_principal_keur=tuple(r.principal_keur for r in rows),
        senior_debt_service_keur=tuple(r.debt_service_keur for r in rows),
        senior_debt_closing_keur=tuple(r.closing_keur for r in rows),
        senior_dscr=tuple(r.dscr for r in rows),
        debt_size_keur=debt_size_keur,
        binding_constraint=binding,
        diagnostics=diag,
    )


def _zero_rows(period_indices: tuple[int, ...]) -> tuple[PeriodDebtRow, ...]:
    return tuple(
        PeriodDebtRow(
            period_index=idx,
            opening_keur=0.0, interest_keur=0.0, principal_keur=0.0,
            debt_service_keur=0.0, closing_keur=0.0, dscr=None,
        )
        for idx in period_indices
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def solve_senior_debt(
    *,
    policy: SeniorDebtPolicy,
    inputs: "SeniorDebtInputs",
    periods: tuple["OperatingPeriodResult", ...],
    tax_cfads_fn: TaxCfadsCallable,
) -> SeniorDebtSchedules:
    """Main entry point: size and sculpt senior debt using fixed-point iteration.

    tax_cfads_fn(senior_interest_by_period) → (cfads_by_period, cash_tax_by_period)
      Called on each iteration with the current period interest map.
      Must invoke the Phase 2B tax engine and canonical CFADS function.
      Must be deterministic.

    Returns SeniorDebtSchedules.
    Non-convergence does NOT raise — it returns diagnostics with
    termination_reason=MAX_ITERATIONS_REACHED and is_authoritative=False.
    Callers must check diagnostics.is_authoritative.
    """
    from financial_engine.senior_debt.validation import validate_senior_debt_inputs

    # Operating periods only (exclude construction)
    op_periods = tuple(p for p in periods if p.is_operation)
    period_indices = tuple(p.period_index for p in op_periods)
    known_period_indices = frozenset(period_indices)
    period_start_end = {p.period_index: (p.period_start, p.period_end) for p in op_periods}

    errors = validate_senior_debt_inputs(inputs, policy, known_period_indices)
    if errors:
        diag = _make_diag(
            converged=False, iteration=0,
            initial_guess=inputs.initial_debt_guess_keur,
            final_d=0.0, max_abs_diff=float("inf"),
            binding=None, termination_reason="INVALID_INPUT",
        )
        return _to_schedules(_zero_rows(period_indices), 0.0, None, diag)

    rate_map = build_rate_map(inputs.period_rates, period_indices, policy.annual_fixed_rate)
    dscr_map = build_dscr_target_map(policy, inputs, period_indices)
    availability_map = build_debt_service_availability_map(inputs, period_indices)
    mode = policy.sizing_mode

    if mode == SeniorDebtSizingMode.EXPLICIT_SCHEDULE:
        return _solve_explicit(
            policy=policy, inputs=inputs, period_indices=period_indices,
            period_start_end=period_start_end, rate_map=rate_map, tax_cfads_fn=tax_cfads_fn,
        )

    if mode == SeniorDebtSizingMode.GEARING_CAP:
        return _solve_gearing(
            policy=policy, inputs=inputs, period_indices=period_indices,
            period_start_end=period_start_end, rate_map=rate_map, tax_cfads_fn=tax_cfads_fn,
        )

    if mode == SeniorDebtSizingMode.DSCR_SCULPTED:
        return _solve_dscr(
            policy=policy, inputs=inputs, period_indices=period_indices,
            period_start_end=period_start_end, rate_map=rate_map, tax_cfads_fn=tax_cfads_fn,
            binding_constraint="DSCR", dscr_map=dscr_map, availability_map=availability_map,
        )

    if mode == SeniorDebtSizingMode.COMBINED_MINIMUM:
        return _solve_combined(
            policy=policy, inputs=inputs, period_indices=period_indices,
            period_start_end=period_start_end, rate_map=rate_map, tax_cfads_fn=tax_cfads_fn,
            dscr_map=dscr_map, availability_map=availability_map,
        )

    raise ValueError(f"Unsupported sizing_mode: {mode!r}")


def _solve_dscr(
    *,
    policy: SeniorDebtPolicy,
    inputs: "SeniorDebtInputs",
    period_indices: tuple[int, ...],
    period_start_end: dict[int, tuple],
    rate_map: dict[int, float],
    tax_cfads_fn: TaxCfadsCallable,
    binding_constraint: str,
    dscr_map: dict[int, float] | None = None,
    availability_map: dict[int, float] | None = None,
) -> SeniorDebtSchedules:
    """Fixed-point iteration for DSCR_SCULPTED sizing using backward induction.

    Convergence tracks: debt_size, opening, interest, principal, closing, CFADS, cash_tax.
    After outer-loop convergence, runs finalisation to ensure schedule self-consistency.
    """
    D = inputs.initial_debt_guess_keur
    alpha = policy.damping_alpha
    max_iter = policy.maximum_iterations
    abs_tol = policy.convergence_tolerance_keur
    rel_tol = policy.convergence_relative_tolerance

    cfads_by: dict[int, float] = {idx: 0.0 for idx in period_indices}
    cash_tax_by: dict[int, float] = {idx: 0.0 for idx in period_indices}

    prev_rows: tuple[PeriodDebtRow, ...] | None = None
    prev_cfads: dict[int, float] | None = None
    prev_cash_tax: dict[int, float] | None = None
    prev_D: float | None = None
    max_abs_diff = float("inf")

    for iteration in range(1, max_iter + 1):
        # Step 1: forward roll (interest from rolling balance at D, using cfads_by for sculpting)
        rows = _forward_roll(
            D, period_indices, rate_map, period_start_end,
            cfads_by, policy, "dscr_sculpted",
            dscr_map=dscr_map, availability_map=availability_map,
        )
        interest_by = {r.period_index: r.interest_keur for r in rows}

        # Step 2: tax feedback
        new_cfads, new_cash_tax = tax_cfads_fn(interest_by)

        # Step 3: backward capacity from updated CFADS
        dscr_capacity = _backward_dscr_capacity(
            new_cfads, rate_map, period_start_end, period_indices, policy,
            dscr_map=dscr_map, availability_map=availability_map,
        )

        # Zero capacity short-circuit (first iteration only)
        if dscr_capacity == 0.0 and D > 0.0 and iteration == 1:
            diag = _make_diag(
                converged=False, iteration=iteration,
                initial_guess=inputs.initial_debt_guess_keur,
                final_d=0.0, max_abs_diff=D,
                binding=binding_constraint, termination_reason="NO_DEBT_CAPACITY",
            )
            return _to_schedules(_zero_rows(period_indices), 0.0, binding_constraint, diag)

        # Step 4: damping
        new_D = alpha * dscr_capacity + (1.0 - alpha) * D
        new_D = max(0.0, new_D)

        # Step 5: convergence check (Issue 2 — all fields, abs OR rel per field)
        if prev_rows is not None:
            # Build rows at new_D with new_cfads for comparison
            new_rows_check = _forward_roll(
                new_D, period_indices, rate_map, period_start_end,
                new_cfads, policy, "dscr_sculpted",
                dscr_map=dscr_map, availability_map=availability_map,
            )
            converged = _schedules_converged(
                rows, new_rows_check,
                cfads_by, new_cfads,
                cash_tax_by, new_cash_tax,
                D, new_D,
                abs_tol, rel_tol,
            )
            max_abs_diff = _compute_max_abs_diff(
                rows, new_rows_check,
                cfads_by, new_cfads,
                cash_tax_by, new_cash_tax,
                D, new_D,
            )

            if converged:
                # Finalisation — enforce exact interest/CFADS handshake
                final_rows, final_cfads, final_cash_tax, fin_ok = _finalise_authoritative(
                    new_D, period_indices, rate_map, period_start_end,
                    new_cfads, policy, "dscr_sculpted", tax_cfads_fn,
                    dscr_map=dscr_map, availability_map=availability_map,
                )
                if not fin_ok:
                    diag = _make_diag(
                        converged=False, iteration=iteration,
                        initial_guess=inputs.initial_debt_guess_keur,
                        final_d=new_D, max_abs_diff=max_abs_diff,
                        binding=binding_constraint,
                        termination_reason="FINALISATION_NOT_CONVERGED",
                    )
                    return _to_schedules(final_rows, new_D, binding_constraint, diag)
                diag = _make_diag(
                    converged=True, iteration=iteration,
                    initial_guess=inputs.initial_debt_guess_keur,
                    final_d=new_D, max_abs_diff=max_abs_diff,
                    binding=binding_constraint, termination_reason="CONVERGED",
                )
                return _to_schedules(final_rows, new_D, binding_constraint, diag)

        prev_rows = rows
        prev_cfads = cfads_by
        prev_cash_tax = cash_tax_by
        prev_D = D
        D = new_D
        cfads_by = new_cfads
        cash_tax_by = new_cash_tax

    # Max iterations reached
    final_rows = _forward_roll(
        D, period_indices, rate_map, period_start_end,
        cfads_by, policy, "dscr_sculpted",
        dscr_map=dscr_map, availability_map=availability_map,
    )
    diag = _make_diag(
        converged=False, iteration=max_iter,
        initial_guess=inputs.initial_debt_guess_keur,
        final_d=D, max_abs_diff=max_abs_diff,
        binding=binding_constraint, termination_reason="MAX_ITERATIONS_REACHED",
    )
    return _to_schedules(final_rows, D, binding_constraint, diag)


# ---------------------------------------------------------------------------
# GEARING_CAP: single-pass level-principal with finalisation
# ---------------------------------------------------------------------------

def _solve_gearing(
    *,
    policy: SeniorDebtPolicy,
    inputs: "SeniorDebtInputs",
    period_indices: tuple[int, ...],
    period_start_end: dict[int, tuple],
    rate_map: dict[int, float],
    tax_cfads_fn: TaxCfadsCallable,
) -> SeniorDebtSchedules:
    """Single-pass gearing-cap sizing (level-principal amortization) with finalisation."""
    assert policy.maximum_gearing is not None
    D = inputs.eligible_project_cost_keur * policy.maximum_gearing

    # Initial roll with zero CFADS → get interest for tax feedback
    init_cfads: dict[int, float] = {idx: 0.0 for idx in period_indices}
    rows = _forward_roll(
        D, period_indices, rate_map, period_start_end,
        init_cfads, policy, "level_principal",
    )
    interest_by = {r.period_index: r.interest_keur for r in rows}
    cfads_by, _ = tax_cfads_fn(interest_by)

    # Finalisation — enforce exact interest/CFADS handshake
    final_rows, final_cfads, final_cash_tax, fin_ok = _finalise_authoritative(
        D, period_indices, rate_map, period_start_end,
        cfads_by, policy, "level_principal", tax_cfads_fn,
    )
    if not fin_ok:
        diag = _make_diag(
            converged=False, iteration=1,
            initial_guess=D, final_d=D, max_abs_diff=0.0,
            binding="GEARING", termination_reason="FINALISATION_NOT_CONVERGED",
        )
        return _to_schedules(final_rows, D, "GEARING", diag)

    diag = _make_diag(
        converged=True, iteration=1,
        initial_guess=D, final_d=D, max_abs_diff=0.0,
        binding="GEARING", termination_reason="CONVERGED",
    )
    return _to_schedules(final_rows, D, "GEARING", diag)


# ---------------------------------------------------------------------------
# COMBINED_MINIMUM: DSCR loop → gearing cap → min → DSCR-sculpted roll
# ---------------------------------------------------------------------------

def _solve_combined(
    *,
    policy: SeniorDebtPolicy,
    inputs: "SeniorDebtInputs",
    period_indices: tuple[int, ...],
    period_start_end: dict[int, tuple],
    rate_map: dict[int, float],
    tax_cfads_fn: TaxCfadsCallable,
    dscr_map: dict[int, float] | None = None,
    availability_map: dict[int, float] | None = None,
) -> SeniorDebtSchedules:
    """COMBINED_MINIMUM: run DSCR loop to get dscr_capacity, apply gearing cap, take min.

    Forward roll at final D always uses DSCR-sculpted repayment.
    Sizing and repayment are separate — amortisation never switches to level-principal.
    """
    assert policy.maximum_gearing is not None
    gearing_cap = inputs.eligible_project_cost_keur * policy.maximum_gearing

    # Run DSCR loop to convergence
    dscr_result = _solve_dscr(
        policy=policy, inputs=inputs, period_indices=period_indices,
        period_start_end=period_start_end, rate_map=rate_map, tax_cfads_fn=tax_cfads_fn,
        binding_constraint="DSCR", dscr_map=dscr_map, availability_map=availability_map,
    )
    if not dscr_result.diagnostics.is_authoritative:
        return dscr_result

    dscr_capacity = dscr_result.debt_size_keur
    abs_tol = policy.convergence_tolerance_keur

    # Determine binding constraint
    if abs(dscr_capacity - gearing_cap) <= abs_tol:
        binding = "BOTH"
    elif dscr_capacity < gearing_cap:
        binding = "DSCR"
    else:
        binding = "GEARING"

    final_d = min(dscr_capacity, gearing_cap)

    # Finalisation at final_d with DSCR-sculpted repayment
    init_cfads: dict[int, float] = {idx: 0.0 for idx in period_indices}
    final_rows, final_cfads, final_cash_tax, fin_ok = _finalise_authoritative(
        final_d, period_indices, rate_map, period_start_end,
        init_cfads, policy, "dscr_sculpted", tax_cfads_fn,
        dscr_map=dscr_map, availability_map=availability_map,
    )
    if not fin_ok:
        diag = _make_diag(
            converged=False,
            iteration=dscr_result.diagnostics.iteration_count,
            initial_guess=inputs.initial_debt_guess_keur,
            final_d=final_d,
            max_abs_diff=dscr_result.diagnostics.maximum_absolute_difference_keur,
            binding=binding,
            termination_reason="FINALISATION_NOT_CONVERGED",
            dscr_capacity=dscr_capacity,
            gearing_capacity=gearing_cap,
        )
        return _to_schedules(final_rows, final_d, binding, diag)

    diag = _make_diag(
        converged=True,
        iteration=dscr_result.diagnostics.iteration_count,
        initial_guess=inputs.initial_debt_guess_keur,
        final_d=final_d,
        max_abs_diff=dscr_result.diagnostics.maximum_absolute_difference_keur,
        binding=binding,
        termination_reason="CONVERGED",
        dscr_capacity=dscr_capacity,
        gearing_capacity=gearing_cap,
    )
    return _to_schedules(final_rows, final_d, binding, diag)


# ---------------------------------------------------------------------------
# EXPLICIT_SCHEDULE (BLOCKER 5): upfront validation then exact forward roll
# ---------------------------------------------------------------------------

def _solve_explicit(
    *,
    policy: SeniorDebtPolicy,
    inputs: "SeniorDebtInputs",
    period_indices: tuple[int, ...],
    period_start_end: dict[int, tuple],
    rate_map: dict[int, float],
    tax_cfads_fn: TaxCfadsCallable,
) -> SeniorDebtSchedules:
    """EXPLICIT_SCHEDULE: validate principal schedule then forward roll with finalisation."""
    opening = inputs.opening_debt_balance_keur
    explicit_map = {
        pp.period_index: pp.principal_keur
        for pp in (inputs.explicit_principal_schedule or ())
    }
    explicit_total = sum(pp.principal_keur for pp in (inputs.explicit_principal_schedule or ()))
    abs_tol = policy.convergence_tolerance_keur

    # BLOCKER 5: over-repayment → INVALID_INPUT
    if explicit_total > opening + abs_tol:
        diag = _make_diag(
            converged=False, iteration=0,
            initial_guess=opening, final_d=opening,
            max_abs_diff=explicit_total - opening,
            binding=None, termination_reason="INVALID_INPUT",
        )
        return _to_schedules(_zero_rows(period_indices), opening, None, diag)

    # Under-repayment without balloon → TERMINAL_BALANCE_NOT_ALLOWED
    if not policy.permit_terminal_balloon and explicit_total < opening - abs_tol:
        diag = _make_diag(
            converged=False, iteration=0,
            initial_guess=opening, final_d=opening,
            max_abs_diff=opening - explicit_total,
            binding=None, termination_reason="TERMINAL_BALANCE_NOT_ALLOWED",
        )
        return _to_schedules(_zero_rows(period_indices), opening, None, diag)

    # Finalisation — enforce exact interest/CFADS handshake
    init_cfads: dict[int, float] = {idx: 0.0 for idx in period_indices}
    final_rows, final_cfads, final_cash_tax, fin_ok = _finalise_authoritative(
        opening, period_indices, rate_map, period_start_end,
        init_cfads, policy, "explicit", tax_cfads_fn, explicit_by=explicit_map,
    )
    if not fin_ok:
        diag = _make_diag(
            converged=False, iteration=1,
            initial_guess=opening, final_d=opening, max_abs_diff=0.0,
            binding=None, termination_reason="FINALISATION_NOT_CONVERGED",
        )
        return _to_schedules(final_rows, opening, None, diag)

    diag = _make_diag(
        converged=True, iteration=1,
        initial_guess=opening, final_d=opening, max_abs_diff=0.0,
        binding=None, termination_reason="CONVERGED",
    )
    return _to_schedules(final_rows, opening, None, diag)
