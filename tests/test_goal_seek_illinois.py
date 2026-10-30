"""Independent oracle for the Step 4 bracketed Illinois regula falsi (post-#400 performance PR, Financial Owner approval 2026-10-30).

Every evaluator here is SYNTHETIC and in-memory. The tests pin the safety contract (statuses, tolerance, bracket, budgets, verification,
determinism) and one representative cost reduction; they never assume the new solved tariff equals the bisection tariff.
"""
import asyncio
import math

import pytest

from app.services import goal_seek as G
from app.services.goal_seek import GoalSeekModelRunError, GoalSeekStatus, solve_tariff_for_metric


def _evaluator(fn, regime=None, fail_on_batch=None, record=None):
    batches = {"n": 0}

    async def evaluate(tariffs):
        batches["n"] += 1
        if record is not None:
            record.append(list(tariffs))
        if fail_on_batch is not None and batches["n"] == fail_on_batch:
            raise GoalSeekModelRunError("SYNTHETIC canonical timeout")
        return [fn(t) for t in tariffs]
    if regime is not None:
        evaluate.regime_at = regime
    return evaluate


def _solve(fn, *, metric="project_irr", current=57.0, target=0.09, regime=None, fail_on_batch=None, record=None, **kwargs):
    return asyncio.run(solve_tariff_for_metric(project_type="solar", current_tariff=current, target_value=target, metric_key=metric,
                                               evaluate_batch=_evaluator(fn, regime, fail_on_batch, record), **kwargs))


def _npv(t):            # kEUR, linear in the tariff (the shape of the expensive canonical NPV case)
    return 50.0 * (t - 60.0)


# ── the candidate rule itself ────────────────────────────────────────────────────────────────────────────────────────────

def test_candidate_is_the_illinois_interpolation_strictly_inside_the_bracket():
    t, method = G._illinois_candidate(50.0, 70.0, -100.0, 300.0, force_bisection=False)
    assert method == "illinois" and 50.0 < t < 70.0 and math.isclose(t, 55.0)


@pytest.mark.parametrize("w_lo,w_hi", [(0.0, 0.0), (5.0, 5.0), (1.0, -1.0), (float("nan"), 1.0), (-1.0, float("inf")), (-1e308, 1e308)])
def test_degenerate_or_nonfinite_weights_fall_back_to_the_midpoint(w_lo, w_hi):
    assert G._illinois_candidate(50.0, 70.0, w_lo, w_hi, force_bisection=False) == (60.0, "bisection")


@pytest.mark.parametrize("w_lo,w_hi", [(-1e-12, 1.0), (-1.0, 1e-12)])            # interpolation on (or next to) an endpoint never spins
def test_endpoint_skewed_interpolation_falls_back_to_the_midpoint(w_lo, w_hi):
    assert G._illinois_candidate(50.0, 70.0, w_lo, w_hi, force_bisection=False) == (60.0, "bisection")


def test_a_forced_safeguard_step_is_the_midpoint():
    assert G._illinois_candidate(50.0, 70.0, -100.0, 300.0, force_bisection=True) == (60.0, "bisection")


# ── representative cost reduction (fails on the historical bisection: 32 evaluations) ──────────────────────────────────

def test_a_linear_npv_target_is_solved_with_far_fewer_canonical_evaluations():
    r = _solve(_npv, metric="project_npv", current=60.0, target=1500.0)
    assert r.status == GoalSeekStatus.SOLVED.value and r.absolute_target_error <= G.DEFAULT_TARGET_TOLERANCE
    assert r.model_evaluations <= 12                                                    # historical bisection: 32 (incl. the 3 verification runs)
    assert r.bracket_lower <= r.solved_input_value <= r.bracket_upper


# ── safety contract: every candidate is canonical, interior and inside the certified bracket ───────────────────────────

@pytest.mark.parametrize("fn,metric,current,target", [
    (_npv, "project_npv", 60.0, 1500.0),
    (lambda t: 2.0 * (t - 30.0) ** 2 - 1800.0, "project_npv", 60.0, 4000.0),           # strongly convex
    (lambda t: 0.02 * math.log(t), "project_irr", 57.0, 0.12),                        # concave
    (lambda t: 0.02 + 0.05 * t, "project_irr", 57.0, 5.0),                            # steep
    (lambda t: 0.02 + 0.001 * t, "project_irr", 57.0, 0.0315),                        # root next to the lower bracket edge
])
def test_solved_results_meet_the_unchanged_tolerance_and_stay_inside_the_bracket(fn, metric, current, target):
    record = []
    r = _solve(fn, metric=metric, current=current, target=target, record=record)
    assert r.status == GoalSeekStatus.SOLVED.value
    assert abs(fn(r.solved_input_value) - target) <= G.DEFAULT_TARGET_TOLERANCE and r.absolute_target_error <= G.DEFAULT_TARGET_TOLERANCE
    assert r.bracket_lower <= r.solved_input_value <= r.bracket_upper
    assert all(math.isfinite(t) for batch in record for t in batch)
    assert r.model_evaluations <= G.DEFAULT_MAX_MODEL_EVALUATIONS and r.iterations <= G.DEFAULT_MAX_ITERATIONS
    assert r == _solve(fn, metric=metric, current=current, target=target)                # deterministic


# ── refusals keep their historical typed status ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,kwargs,status", [
    ("metric unavailable inside the bracket", dict(fn=lambda t: None if 80.0 < t < 100.0 else 0.02 + 0.001 * t), "NON_MONOTONIC_TARGET"),
    ("contradictory monotonic sample", dict(fn=lambda t: 0.02 + 0.001 * t + (0.05 if 95 < t < 105 else 0.0), target=0.12), "NON_MONOTONIC_TARGET"),
    ("jump across the target", dict(fn=lambda t: 0.05 if t < 77.7 else 0.13), "NON_MONOTONIC_TARGET"),
    ("financing regime switch at the root", dict(fn=lambda t: 0.02 * t + 0.1, metric="min_dscr", target=1.30,
                                                 regime=lambda t: "A" if t < 60.0 else "B"), "NON_MONOTONIC_TARGET"),
    ("flat response", dict(fn=lambda t: 0.05, target=0.09), "NON_MONOTONIC_TARGET"),
    ("target already met", dict(fn=lambda t: 0.02 + 0.001 * t, target=0.077), "TARGET_ALREADY_MET"),
    ("budget too small to bracket", dict(fn=_npv, metric="project_npv", current=60.0, target=1500.0, max_evaluations=8), "NO_SOLUTION_IN_BOUNDS"),
    ("canonical run fails inside Step 4", dict(fn=lambda t: 0.02 + 0.001 * t, fail_on_batch=3), "MODEL_RUN_FAILED"),
])
def test_refusals_keep_their_historical_typed_status(label, kwargs, status):
    r = _solve(**kwargs)
    assert r.status == status, label
    assert r.solved_input_value is None or r.status in ("TARGET_ALREADY_MET",) or r.absolute_target_error > G.DEFAULT_TARGET_TOLERANCE, label


def test_the_unavailable_metric_bracket_runs_the_historical_midpoint_bisection():
    record = []
    r = _solve(lambda t: None if 80.0 < t < 100.0 else 0.02 + 0.001 * t, record=record)
    assert r.status == GoalSeekStatus.NON_MONOTONIC_TARGET.value
    step4 = [batch[0] for batch in record[2:]]
    assert step4[0] == (57.0 + 171.0) / 2.0                                              # exactly the bisection midpoint, never an interpolation


def test_the_final_canonical_verification_still_runs_and_still_refuses_a_regime_switch():
    record = []
    r = _solve(_npv, metric="project_npv", current=60.0, target=1500.0, record=record)
    assert len(record[-1]) == 3 and record[-1][1] == r.solved_input_value                # the reserved three-point canonical rerun
    switching = _solve(_npv, metric="project_npv", current=60.0, target=1500.0,
                       regime=lambda t: "A" if t <= 90.0 else "B")
    assert switching.status == GoalSeekStatus.NON_MONOTONIC_TARGET.value and switching.solved_input_value is None


def test_a_smaller_budget_fails_closed_and_never_fabricates_a_result():
    r = _solve(_npv, metric="project_npv", current=60.0, target=1500.0, max_evaluations=9)
    assert r.status == GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value and r.solved_input_value is None and r.model_evaluations <= 9


def test_documented_difference_a_budget_bisection_exhausted_can_now_be_solved_within_the_same_budget():
    """Historical bisection returned NO_SOLUTION_IN_BOUNDS here (budget 12); Illinois reaches a canonically verified root within the
    SAME budget. Recorded in BASELINE_VS_ILLINOIS.csv as an intended, reviewed status difference."""
    r = _solve(_npv, metric="project_npv", current=60.0, target=1500.0, max_evaluations=12)
    assert r.status == GoalSeekStatus.SOLVED.value and r.model_evaluations <= 12 and r.absolute_target_error <= G.DEFAULT_TARGET_TOLERANCE
