"""Goal Seek / Tender V1 — canonical decision support (pure orchestration).

Goal Seek solves ONE canonical scalar revenue-price input (the PPA base
tariff) so that the canonical FINCO model produces a user-chosen target
return metric (Project IRR / Pure Equity IRR / Total Sponsor IRR).

HARD RULES (mirroring the composition-layer contract):

- The canonical engine remains the single financial authority. Goal Seek
  NEVER duplicates revenue, debt, tax, DSRA, SHL or return math: every
  candidate tariff is evaluated by running the SAME canonical ``run_project``
  authority the Workbook runs, through the existing persistence-free
  batched candidate authority (``run_sensitivity_points`` — "temporary, not
  written to scenario persistence").
- Decision support only: candidate evaluation has NO side effects — it
  never appends Run History, never promotes Last Run, never mutates the
  Working Copy. Only the explicit user "Apply" action (routed through the
  canonical ``WorkbookUpdateService.apply_draft_update`` field-save
  authority) writes the solved tariff, triggering the normal STALE
  semantics.
- Deterministic, bounded, bracketed solving: geometric bracket ladder +
  monotonicity verification + plain bisection. No unconstrained optimizer,
  no NaN acceptance, no silent extrapolation beyond the explored bounds.

"Tender" is a UX label for the same single calculation contract (e.g.
"find the tariff required to achieve a target return").
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Sequence

# ── Typed registries ─────────────────────────────────────────────────────────


class GoalSeekStatus(str, Enum):
    SOLVED = "SOLVED"
    TARGET_ALREADY_MET = "TARGET_ALREADY_MET"
    NO_SOLUTION_IN_BOUNDS = "NO_SOLUTION_IN_BOUNDS"
    NON_MONOTONIC_TARGET = "NON_MONOTONIC_TARGET"
    TARGET_METRIC_UNAVAILABLE = "TARGET_METRIC_UNAVAILABLE"
    MODEL_RUN_FAILED = "MODEL_RUN_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"


@dataclass(frozen=True)
class GoalSeekMetric:
    """One canonical target metric. ``kpi_key`` is the exact key in the
    canonical run payload's ``kpis`` dict; values are FRACTIONS
    (0.08 == 8.00%)."""

    key: str
    kpi_key: str
    label: str


# All three metrics are computed by the single canonical G2C path for every
# supported project type (no per-type branching), so all three are valid V1
# targets. A metric can still be unavailable AT a specific candidate when its
# canonical status is not OK (e.g. unpaid SHL bullet) — handled as a typed
# unavailable state, never as zero.
GOAL_SEEK_METRICS: dict[str, GoalSeekMetric] = {
    "project_irr": GoalSeekMetric("project_irr", "project_irr", "Project IRR"),
    "pure_equity_irr": GoalSeekMetric("pure_equity_irr", "equity_irr", "Pure Equity IRR"),
    "total_sponsor_irr": GoalSeekMetric(
        "total_sponsor_irr", "total_sponsor_xirr", "Total Sponsor IRR"),
}


@dataclass(frozen=True)
class GoalSeekSolveVariable:
    """One canonical scalar revenue-price solve variable.

    V1 supports exactly the technologies whose canonical revenue-price input
    is a scalar on the canonical ProjectInputs revenue authority (the PPA
    base tariff). Projects without such a scalar (Data Center's service
    price is adapter-derived; EV Charging has no V1 price scalar) fail
    closed instead of inventing a variable."""

    key: str
    field_id: str
    fallback_field_id: Optional[str]
    unit: str
    label: str
    project_types: frozenset


GOAL_SEEK_SOLVE_VARIABLES: dict[str, GoalSeekSolveVariable] = {
    "ppa_base_tariff": GoalSeekSolveVariable(
        key="ppa_base_tariff",
        field_id="revenue.ppa.base_tariff",
        fallback_field_id="revenue.ppa.tariff_legacy",
        unit="EUR/MWh",
        label="Tariff / Revenue Price",
        project_types=frozenset({"solar", "wind"}),
    ),
}


def resolve_metric(metric_key: str) -> Optional[GoalSeekMetric]:
    return GOAL_SEEK_METRICS.get(str(metric_key or "").strip())


def resolve_solve_variable(project_type: str) -> Optional[GoalSeekSolveVariable]:
    """Typed resolver: the canonical scalar revenue-price variable for a
    project type, or None when the project has no supported scalar
    revenue-price solve variable (fail closed)."""
    pt = str(project_type or "").strip().lower()
    for variable in GOAL_SEEK_SOLVE_VARIABLES.values():
        if pt in variable.project_types:
            return variable
    return None


# ── Solver constants (explicit, bounded, deterministic) ─────────────────────

#: Absolute tolerance on the TARGET METRIC (fraction): 1e-4 == 0.01
#: percentage point. This is the Goal Seek tolerance — internal
#: financial-engine convergence is never touched.
DEFAULT_TARGET_TOLERANCE = 1e-4
DEFAULT_MAX_ITERATIONS = 60
#: Deterministic evaluation budget (candidate runs) per solve.
DEFAULT_MAX_MODEL_EVALUATIONS = 40
#: Bisection stops when the tariff interval is below this fraction of the
#: starting tariff scale.
TARIFF_EPSILON_FRACTION = 1e-4
#: Probe responses must be non-decreasing within this slack.
MONOTONIC_EPSILON = 1e-9
#: Adaptive initial bracket around the CURRENT canonical tariff (visible in
#: result metadata; never hardcoded to one technology's scale).
BRACKET_LOWER_FRACTION = 0.2      # lower = 20% of current tariff
BRACKET_UPPER_MULTIPLE = 3.0      # initial upper = 3x current tariff
#: Upper expansion is capped: at most this many x-factor expansions.
BRACKET_MAX_EXPANSIONS = 2
BRACKET_EXPANSION_FACTOR = 4.0
LADDER_POINTS = 5                 # interior resolution of the bracket ladder


class GoalSeekModelRunError(Exception):
    """Raised by the evaluator when the canonical model run itself fails
    (execution failure/timeout) — distinct from a candidate whose metric is
    simply unavailable."""


# ── Result contract ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoalSeekResult:
    """Typed Goal Seek result. Failures are typed statuses — never a null
    masquerading as a solved value."""

    status: str                       # GoalSeekStatus value
    solve_variable: str               # solve-variable key
    solve_variable_label: str
    solve_variable_unit: str
    solve_field_id: str               # canonical workbook field to apply
    target_metric: str                # metric request key
    target_metric_label: str
    target_value: float               # FRACTION (0.08 == 8%)
    solved_input_value: Optional[float]
    achieved_metric_value: Optional[float]
    absolute_target_error: Optional[float]
    iterations: int
    model_evaluations: int
    lower_bound: float                # lowest explored tariff
    upper_bound: float                # highest explored tariff
    bracket_lower: Optional[float]    # final proven bracket (when found)
    bracket_upper: Optional[float]
    started_from_value: float
    expansions: int = 0
    message: str = ""

    @property
    def solved(self) -> bool:
        return self.status in (
            GoalSeekStatus.SOLVED.value,
            GoalSeekStatus.TARGET_ALREADY_MET.value,
        )


# ── Solver ───────────────────────────────────────────────────────────────────

Evaluator = Callable[[Sequence[float]], Awaitable[list[Optional[float]]]]


def _metric_at(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _ladder(lower: float, start: float, upper: float, points: int = LADDER_POINTS) -> list[float]:
    """Deterministic geometric-flavoured ladder with the exact start inside."""
    raw = {lower, start, upper}
    for i in range(1, points - 2):
        raw.add(lower + (upper - lower) * i / (points - 1))
    return sorted(v for v in raw if v >= 0.0)


class _EvaluationBudgetExhausted(Exception):
    """Internal control flow: the requested evaluation would exceed the budget.

    Never escapes the Goal Seek solver contract; converted to a typed
    non-success result by :func:`solve_tariff_for_metric`."""


async def solve_tariff_for_metric(
    *,
    project_type: str,
    current_tariff: float,
    target_value: float,
    metric_key: str = "project_irr",
    evaluate_batch: Evaluator,
    tolerance: float = DEFAULT_TARGET_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_evaluations: int = DEFAULT_MAX_MODEL_EVALUATIONS,
) -> GoalSeekResult:
    """Deterministic bracketed solve (see :func:`_solve_impl`).

    Genuine evaluation-budget exhaustion is returned as the typed bounded
    non-success status ``NO_SOLUTION_IN_BOUNDS`` — never a raw exception and
    never a fabricated ``SOLVED``."""
    budget = {"evaluations": 0}
    try:
        return await _solve_impl(
            project_type=project_type, current_tariff=current_tariff,
            target_value=target_value, metric_key=metric_key,
            evaluate_batch=evaluate_batch, tolerance=tolerance,
            max_iterations=max_iterations, max_evaluations=max_evaluations,
            budget=budget)
    except _EvaluationBudgetExhausted:
        metric = resolve_metric(metric_key)
        variable = resolve_solve_variable(project_type)
        return GoalSeekResult(
            status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
            solve_variable=variable.key if variable else "ppa_base_tariff",
            solve_variable_label=variable.label if variable else "Tariff / Revenue Price",
            solve_variable_unit=variable.unit if variable else "EUR/MWh",
            solve_field_id=variable.field_id if variable else "revenue.ppa.base_tariff",
            target_metric=metric.key if metric else str(metric_key),
            target_metric_label=metric.label if metric else str(metric_key),
            target_value=target_value,
            solved_input_value=None,
            achieved_metric_value=None,
            absolute_target_error=None,
            iterations=0,
            model_evaluations=budget["evaluations"],
            lower_bound=0.0,
            upper_bound=0.0,
            bracket_lower=None,
            bracket_upper=None,
            started_from_value=current_tariff,
            message="Evaluation budget exhausted before the target could be solved.")


async def _solve_impl(
    *,
    project_type: str,
    current_tariff: float,
    target_value: float,
    metric_key: str,
    evaluate_batch: Evaluator,
    tolerance: float,
    max_iterations: int,
    max_evaluations: int,
    budget: dict,
) -> GoalSeekResult:
    """Deterministic bracketed solve of the tariff for a target metric.

    ``evaluate_batch(tariffs)`` must return one metric value (fraction) or
    ``None`` (metric unavailable at that candidate) per tariff, in order,
    and raise :class:`GoalSeekModelRunError` when the canonical model run
    itself fails. It must be side-effect free.
    """
    metric = resolve_metric(metric_key)
    variable = resolve_solve_variable(project_type)

    def _result(**kwargs: Any) -> GoalSeekResult:
        base = dict(
            solve_variable=variable.key if variable else "ppa_base_tariff",
            solve_variable_label=variable.label if variable else "Tariff / Revenue Price",
            solve_variable_unit=variable.unit if variable else "EUR/MWh",
            solve_field_id=variable.field_id if variable else "revenue.ppa.base_tariff",
            target_metric=metric.key if metric else str(metric_key),
            target_metric_label=metric.label if metric else str(metric_key),
            target_value=target_value,
            solved_input_value=None,
            achieved_metric_value=None,
            absolute_target_error=None,
            iterations=0,
            model_evaluations=budget["evaluations"],
            lower_bound=0.0,
            upper_bound=0.0,
            bracket_lower=None,
            bracket_upper=None,
            started_from_value=current_tariff,
        )
        base.update(kwargs)
        return GoalSeekResult(**base)

    # ── Request validation (fail closed) ──────────────────────────────────── #
    if metric is None:
        return _result(
            status=GoalSeekStatus.INVALID_REQUEST.value,
            message=f"Unknown target metric {metric_key!r}; supported: "
                    f"{sorted(GOAL_SEEK_METRICS)}")
    if variable is None:
        return _result(
            status=GoalSeekStatus.INVALID_REQUEST.value,
            message=f"Project type {project_type!r} has no supported scalar "
                    "revenue-price solve variable in V1.")
    if not math.isfinite(target_value):
        return _result(status=GoalSeekStatus.INVALID_REQUEST.value,
                       message="Target value must be a finite number.")
    if not math.isfinite(current_tariff) or current_tariff <= 0:
        return _result(
            status=GoalSeekStatus.INVALID_REQUEST.value,
            message="Current tariff must be a positive number to derive an "
                    "adaptive bracket.")
    if tolerance <= 0 or max_iterations < 1 or max_evaluations < 1:
        return _result(status=GoalSeekStatus.INVALID_REQUEST.value,
                       message="Solver limits must be positive.")

    async def _eval(tariffs: Sequence[float]) -> list[Optional[float]]:
        if budget["evaluations"] + len(tariffs) > max_evaluations:
            raise _EvaluationBudgetExhausted()
        budget["evaluations"] += len(tariffs)
        raw_list = await evaluate_batch(tariffs)
        if len(raw_list) != len(tariffs):
            raise GoalSeekModelRunError(
                "evaluator returned a mismatched candidate count")
        return [_metric_at(raw) for raw in raw_list]

    def _usable(points: list[tuple[float, Optional[float]]]) -> list[tuple[float, float]]:
        return [(t, f) for t, f in points if f is not None]

    def _monotone_rising(seq: list[tuple[float, float]]) -> Optional[str]:
        """None when non-decreasing; a reason string otherwise."""
        for (t0, f0), (t1, f1) in zip(seq, seq[1:]):
            if f1 < f0 - MONOTONIC_EPSILON:
                return (f"metric decreases from {f0:.6f} to {f1:.6f} between "
                        f"tariff {t0:.4f} and {t1:.4f}")
        if seq and max(f for _, f in seq) - min(f for _, f in seq) <= MONOTONIC_EPSILON:
            return "metric is flat across the whole explored bracket"
        return None

    # ── Step 1: current point ─────────────────────────────────────────────── #
    try:
        current_batch = await _eval([current_tariff])
    except GoalSeekModelRunError as exc:
        return _result(status=GoalSeekStatus.MODEL_RUN_FAILED.value,
                       message=f"Canonical model run failed: {exc}")
    f_current = current_batch[0]
    if f_current is None:
        return _result(
            status=GoalSeekStatus.TARGET_METRIC_UNAVAILABLE.value,
            message=f"{metric.label} is not available at the current tariff "
                    f"(canonical status is not OK); nothing to solve.")
    if abs(f_current - target_value) <= tolerance:
        return _result(
            status=GoalSeekStatus.TARGET_ALREADY_MET.value,
            solved_input_value=current_tariff,
            achieved_metric_value=f_current,
            absolute_target_error=abs(f_current - target_value),
            lower_bound=current_tariff,
            upper_bound=current_tariff,
            message=f"Target already met at the current tariff "
                    f"({current_tariff:.2f} {variable.unit}).")

    # ── Step 2: bracket ladder + monotonicity verification ───────────────── #
    lower = max(0.0, current_tariff * BRACKET_LOWER_FRACTION)
    upper = current_tariff * BRACKET_UPPER_MULTIPLE
    expansions = 0
    probes: list[tuple[float, Optional[float]]] = []

    while True:
        ladder = _ladder(lower, current_tariff, upper)
        # honour the evaluation budget deterministically
        remaining = max_evaluations - budget["evaluations"]
        if len(ladder) > remaining:
            ladder = ladder[:max(3, remaining)]
        try:
            batch = await _eval(ladder)
        except GoalSeekModelRunError as exc:
            return _result(status=GoalSeekStatus.MODEL_RUN_FAILED.value,
                           message=f"Canonical model run failed: {exc}",
                           lower_bound=min(ladder), upper_bound=max(ladder),
                           expansions=expansions)
        probes = list(zip(ladder, batch))
        usable = _usable(probes)
        if len(usable) >= 3:
            break
        if expansions >= BRACKET_MAX_EXPANSIONS:
            return _result(
                status=GoalSeekStatus.TARGET_METRIC_UNAVAILABLE.value,
                message=f"{metric.label} is unavailable at (almost) every "
                        "probed tariff; cannot bracket the target.",
                lower_bound=min(ladder), upper_bound=max(ladder),
                expansions=expansions)
        expansions += 1
        upper *= BRACKET_EXPANSION_FACTOR

    # probe points beyond budget guard: shrink silently never happens for
    # well-formed budgets (40 >= 5 ladder + 60 bisection is capped by
    # max_evaluations in the loop below).

    ladder = [t for t, _ in probes]
    usable = _usable(probes)
    reason = _monotone_rising(usable)
    if reason is not None:
        return _result(
            status=GoalSeekStatus.NON_MONOTONIC_TARGET.value,
            message=f"{metric.label} response is not monotonic in the "
                    f"investigated tariff interval ({reason}); refusing to "
                    "pick an arbitrary root.",
            lower_bound=min(ladder), upper_bound=max(ladder),
            expansions=expansions)

    def _extend_upper() -> None:
        nonlocal upper
        upper = upper * BRACKET_EXPANSION_FACTOR

    # ── Step 3: bracketing (capped expansion, both directions) ───────────── #
    while True:
        # find an adjacent usable bracketing pair
        bracket = None
        for (t0, f0), (t1, f1) in zip(usable, usable[1:]):
            if f0 - tolerance <= target_value <= f1 + tolerance:
                bracket = (t0, f0, t1, f1)
                break
            if target_value < f0 and t0 == usable[0][0] and t0 <= 0.0 + 1e-12:
                # below the economically lowest tariff (zero) — cannot expand
                return _result(
                    status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
                    message=f"Target {target_value * 100:.4f}% is below the "
                            "best achievable value within the allowed tariff "
                            f"bounds (at tariff 0 the metric is "
                            f"{f0 * 100:.4f}%).",
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    achieved_metric_value=f0,
                    absolute_target_error=abs(f0 - target_value),
                    expansions=expansions)
        if bracket is not None:
            break
        f_min = min(f for _, f in usable)
        f_max = max(f for _, f in usable)
        if target_value < f_min:
            # Downward expansion: the ladder lower bound may sit above the
            # true economic floor (a zero tariff).  Expand down while the
            # budget remains; once the floor is reached, the target is
            # provably out of bounds.
            if expansions >= BRACKET_MAX_EXPANSIONS or lower <= 0.0 + 1e-12:
                return _result(
                    status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
                    message=(f"Target {target_value * 100:.4f}% is below the "
                             f"best (lowest) achievable value "
                             f"{f_min * 100:.4f}% within the allowed tariff "
                             "bounds (the lower bound is already the economic "
                             "floor of 0)."),
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    achieved_metric_value=f_min,
                    absolute_target_error=abs(f_min - target_value),
                    expansions=expansions)
            expansions += 1
            new_lower = max(0.0, lower / 8.0)
            new_points = sorted({
                new_lower,
                (new_lower + min(t for t, _ in usable)) / 2.0,
            })
            remaining = max_evaluations - budget["evaluations"]
            new_points = new_points[:max(1, remaining)]
            if not new_points:
                return _result(
                    status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
                    message="Evaluation budget exhausted before the target "
                            "could be bracketed.",
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    expansions=expansions)
            try:
                batch = await _eval(new_points)
            except GoalSeekModelRunError as exc:
                return _result(
                    status=GoalSeekStatus.MODEL_RUN_FAILED.value,
                    message=f"Canonical model run failed: {exc}",
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    expansions=expansions)
            probes = list(zip(new_points, batch)) + probes
            probes.sort(key=lambda pair: pair[0])
            lower = new_lower
            usable = _usable(probes)
            ladder = [t for t, _ in probes]
            reason = _monotone_rising(usable)
            if reason is not None:
                return _result(
                    status=GoalSeekStatus.NON_MONOTONIC_TARGET.value,
                    message=(f"{metric.label} response is not monotonic in "
                             f"the expanded interval ({reason})."),
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    expansions=expansions)
            continue
        if target_value > f_max:
            if expansions >= BRACKET_MAX_EXPANSIONS:
                return _result(
                    status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
                    message=(f"Target {target_value * 100:.4f}% exceeds the "
                             f"best achievable value {f_max * 100:.4f}% at "
                             f"the capped upper bound {upper:.2f} "
                             f"{variable.unit}; upper expansion is capped."),
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    achieved_metric_value=f_max,
                    absolute_target_error=abs(f_max - target_value),
                    expansions=expansions)
            expansions += 1
            _extend_upper()
            new_points = [upper / BRACKET_EXPANSION_FACTOR * 2.0, upper]
            new_points = [p for p in new_points
                          if p > max(t for t, _ in usable)]
            remaining = max_evaluations - budget["evaluations"]
            new_points = new_points[:max(1, remaining)]
            if not new_points:
                return _result(
                    status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
                    message="Evaluation budget exhausted before the target "
                            "could be bracketed.",
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    expansions=expansions)
            try:
                batch = await _eval(new_points)
            except GoalSeekModelRunError as exc:
                return _result(
                    status=GoalSeekStatus.MODEL_RUN_FAILED.value,
                    message=f"Canonical model run failed: {exc}",
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    expansions=expansions)
            probes.extend(zip(new_points, batch))
            probes.sort(key=lambda pair: pair[0])
            usable = _usable(probes)
            ladder = [t for t, _ in probes]
            reason = _monotone_rising(usable)
            if reason is not None:
                return _result(
                    status=GoalSeekStatus.NON_MONOTONIC_TARGET.value,
                    message=(f"{metric.label} response is not monotonic in "
                             f"the expanded interval ({reason})."),
                    lower_bound=min(ladder), upper_bound=max(ladder),
                    expansions=expansions)
            continue
        # target between usable points but no adjacent pair matched (a None
        # gap split the range) — treat as continuity break
        return _result(
            status=GoalSeekStatus.NON_MONOTONIC_TARGET.value,
            message="Metric evidence is discontinuous across the explored "
                    "interval (unavailable candidates split the bracket).",
            lower_bound=min(ladder), upper_bound=max(ladder),
            expansions=expansions)

    t_lo, f_lo, t_hi, f_hi = bracket
    tariff_eps = current_tariff * TARIFF_EPSILON_FRACTION

    # exact hits on bracket edges
    for t_edge, f_edge in ((t_lo, f_lo), (t_hi, f_hi)):
        if abs(f_edge - target_value) <= tolerance:
            return _result(
                status=GoalSeekStatus.SOLVED.value,
                solved_input_value=t_edge,
                achieved_metric_value=f_edge,
                absolute_target_error=abs(f_edge - target_value),
                iterations=0,
                model_evaluations=budget["evaluations"],
                lower_bound=min(ladder), upper_bound=max(ladder),
                bracket_lower=t_lo, bracket_upper=t_hi,
                expansions=expansions,
                message=f"Solved at a probed bracket edge.")

    # ── Step 4: bisection (deterministic) ─────────────────────────────────── #
    lo, hi, f_lo_v, f_hi_v = t_lo, t_hi, f_lo, f_hi
    iterations = 0
    best: tuple[float, float] = (
        (t_lo, f_lo) if abs(f_lo - target_value) <= abs(f_hi - target_value)
        else (t_hi, f_hi))
    while iterations < max_iterations:
        if abs(f_lo_v - target_value) <= tolerance:
            break
        if (hi - lo) <= tariff_eps:
            break
        mid = (lo + hi) / 2.0
        try:
            batch = await _eval([mid])
        except GoalSeekModelRunError as exc:
            return _result(status=GoalSeekStatus.MODEL_RUN_FAILED.value,
                           message=f"Canonical model run failed: {exc}",
                           lower_bound=min(ladder), upper_bound=max(ladder),
                           bracket_lower=lo, bracket_upper=hi,
                           iterations=iterations, expansions=expansions)
        f_mid = batch[0]
        iterations += 1
        if f_mid is None:
            return _result(
                status=GoalSeekStatus.NON_MONOTONIC_TARGET.value,
                message="Metric became unavailable inside the bracket "
                        "(discontinuous response); refusing to extrapolate.",
                lower_bound=min(ladder), upper_bound=max(ladder),
                bracket_lower=lo, bracket_upper=hi,
                iterations=iterations, model_evaluations=budget["evaluations"],
                expansions=expansions)
        if abs(f_mid - target_value) < abs(best[1] - target_value):
            best = (mid, f_mid)
        if abs(f_mid - target_value) <= tolerance:
            lo, hi = mid, mid
            f_lo_v, f_hi_v = f_mid, f_mid
            break
        if f_mid < target_value:
            lo, f_lo_v = mid, f_mid
        else:
            hi, f_hi_v = mid, f_mid

    solved_tariff, achieved = best
    error = abs(achieved - target_value)
    if error <= tolerance:
        status = GoalSeekStatus.SOLVED.value
        message = (f"Solved: tariff {solved_tariff:.2f} {variable.unit} "
                   f"achieves {metric.label} {achieved * 100:.4f}%.")
    elif (hi - lo) <= tariff_eps:
        return _result(
            status=GoalSeekStatus.NON_MONOTONIC_TARGET.value,
            message="Response is discontinuous at model resolution inside "
                    "the bracket; the target cannot be met exactly at the "
                    "model's tariff resolution.",
            solved_input_value=solved_tariff,
            achieved_metric_value=achieved,
            absolute_target_error=error,
            iterations=iterations, model_evaluations=budget["evaluations"],
            lower_bound=min(ladder), upper_bound=max(ladder),
            bracket_lower=lo, bracket_upper=hi, expansions=expansions)
    else:
        return _result(
            status=GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value,
            message="Iteration budget exhausted before reaching the target "
                    "tolerance; no fabricated result is returned.",
            solved_input_value=solved_tariff,
            achieved_metric_value=achieved,
            absolute_target_error=error,
            iterations=iterations, model_evaluations=budget["evaluations"],
            lower_bound=min(ladder), upper_bound=max(ladder),
            bracket_lower=lo, bracket_upper=hi, expansions=expansions)

    return _result(
        status=status,
        solved_input_value=solved_tariff,
        achieved_metric_value=achieved,
        absolute_target_error=abs(achieved - target_value),
        iterations=iterations,
        model_evaluations=budget["evaluations"],
        lower_bound=min(ladder), upper_bound=max(ladder),
        bracket_lower=lo, bracket_upper=hi,
        expansions=expansions,
        message=message)


# ── Canonical candidate evaluator (persistence-free) ─────────────────────────


def make_canonical_evaluator(
    runtime_project_key: str,
    base_override: Any,
    metric: GoalSeekMetric,
) -> Callable[[Sequence[float]], Awaitable[list[Optional[float]]]]:
    """Build the canonical candidate evaluator for one solve.

    Each candidate tariff is applied to the ALREADY-CANONICAL base
    ``ProjectInputs`` override (the exact input state a normal Run would
    use — tariff swap is a pure dataclass replace, never a recomputation of
    any financial formula), then evaluated by the EXISTING persistence-free
    batched candidate authority ``run_sensitivity_points`` (the same
    production-proven worker the V2 sensitivity grid uses: "temporary — not
    written to scenario persistence"). No Run History entry, no Last Run
    promotion, no Working Copy mutation, no per-iteration artifacts.

    Per-candidate engine errors map to ``None`` (metric unavailable at that
    candidate); executor-level busy re-raises; timeout/failed raise
    :class:`GoalSeekModelRunError` (→ typed MODEL_RUN_FAILED).
    """
    from dataclasses import replace as _dc_replace

    def _with_tariff(pi: Any, tariff: float) -> Any:
        if getattr(pi.revenue, "multistream_config_json", ""):
            raise GoalSeekModelRunError("REVENUE_V2_GOAL_SEEK_UNSUPPORTED: no scalar tariff authority in an explicit contract book")
        # Pure input swap on the frozen canonical revenue authority.
        return _dc_replace(pi, revenue=_dc_replace(pi.revenue, ppa_base_tariff=tariff))

    async def _evaluate(tariffs: Sequence[float]) -> list[Optional[float]]:
        from app.runtime.model_execution import (
            ModelExecutionBusy,
            ModelExecutionFailed,
            ModelExecutionTimeout,
            run_model_process,
        )
        from app.services.sensitivity_execution import run_sensitivity_points

        candidates = [_with_tariff(base_override, float(t)) for t in tariffs]
        try:
            outputs = await run_model_process(
                run_sensitivity_points, runtime_project_key, candidates)
        except ModelExecutionBusy:
            raise
        except (ModelExecutionFailed, ModelExecutionTimeout) as exc:
            raise GoalSeekModelRunError(str(exc)) from exc
        values: list[Optional[float]] = []
        for out in outputs:
            if not isinstance(out, dict) or "error" in out:
                values.append(None)
                continue
            kpis = out.get("kpis") or {}
            raw = kpis.get(metric.kpi_key)
            if raw is None and metric.kpi_key == "total_sponsor_xirr":
                # canonical compat alias written by the same run payload
                raw = kpis.get("sponsor_irr")
            values.append(raw)
        return values

    return _evaluate
