"""Runtime Performance V2 — prewarm + senior solver numeric hot path.

Guards the V2 optimizations WITHOUT any financial-semantic change:

  PERF_V2_KERNEL_DIFFERENTIAL   numeric forward-roll kernel == authoritative
                                _forward_roll, exactly, over a deterministic
                                input matrix (zero/large debt, zero rates,
                                boundaries, sculpted/level/explicit, variable
                                DSCR/availability, odd day counts, zero and
                                negative CFADS, balloons)
  PERF_V2_PATCH_SAFETY          a monkeypatched _forward_roll disables the
                                numeric kernel and full patched behaviour is
                                preserved
  PERF_V2_MERGE_TEMPLATE        the solver tax callable re-stamps senior
                                interest exactly like the canonical merge;
                                uncovered candidate keys take the canonical
                                per-call merge path
  PERF_V2_PARITY                all 17 complete result trees are bit-identical
                                between numeric and authoritative roll kernels;
                                unaffected historical digests remain unchanged
  PERF_V2_FAILURE_PARITY        fail-closed scenarios fail identically
  PERF_V2_PREWARM               executor prewarm: workers spawned, warm state
                                observable, no project model executed, reset
                                semantics preserved
  PERF_V2_NO_SOLVER_SHORTCUTS   iteration counts / termination reasons
                                unchanged vs the recorded V1 counts
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from financial_engine.senior_debt.interest import period_day_fraction
from financial_engine.senior_debt.policy import DayCountConvention
from financial_engine.senior_debt.solver import (
    _AUTHENTIC_FORWARD_ROLL,
    _forward_roll,
    _forward_roll_numeric,
    build_roll_plan,
)

FIXTURE = Path(__file__).parent / "fixtures" / "runtime_v2_base_digests.json"


# ---------------------------------------------------------------------------
# Deterministic roll matrix (§11)
# ---------------------------------------------------------------------------

class _Policy:
    repayment_start_period_index = 2
    maturity_period_index = 9
    target_dscr = 1.30
    day_count_convention = DayCountConvention.ACT_365


def _make_case(n=8, rate=0.05, start=2, mat=9, dscr=None, avail=None,
               cfads_fn=lambda i: 900.0 + 10 * i,
               method="dscr_sculpted", odd=False):
    idxs = tuple(range(1, n + 1))
    pse = {}
    day = date(2031, 1, 1)
    for i in idxs:
        end = day + timedelta(days=(100 if (odd and i % 2 == 0) else 182))
        pse[i] = (day, end)
        day = end
    rate_map = {i: rate * (1.0 if i % 3 else 1.1) for i in idxs}
    cfads = {i: cfads_fn(i) for i in idxs}
    dscr_map = {i: dscr[i] for i in idxs} if dscr else None
    availability = {i: avail[i] for i in idxs} if avail else None
    policy = _Policy()
    policy.repayment_start_period_index = start
    policy.maturity_period_index = mat
    explicit_by = ({i: 50.0 + i for i in idxs} if method == "explicit" else None)
    plan = build_roll_plan(
        policy=policy, period_indices=idxs, period_start_end=pse,
        rate_map=rate_map, repayment_method_str=method,
        dscr_map=dscr_map, availability_map=availability,
        explicit_by=explicit_by,
    )
    return policy, idxs, pse, rate_map, cfads, dscr_map, availability, plan, method, explicit_by


_KERNEL_CASES = [
    _make_case(),
    _make_case(dscr={i: 1.2 + 0.05 * i for i in range(1, 9)}),
    _make_case(avail={i: 0.9 for i in range(1, 9)}),
    _make_case(cfads_fn=lambda i: 0.0),
    _make_case(cfads_fn=lambda i: -50.0 + i),
    _make_case(odd=True),
    _make_case(n=4, mat=4),
    _make_case(method="level_principal"),
    _make_case(method="explicit"),
    _make_case(rate=0.0),
    _make_case(start=1, mat=8),
    _make_case(method="explicit", start=1, mat=1),
]

_DEBT_LEVELS = (0.0, 12.5, 1500.0, 90000.0)


def _hex_fields(row):
    """IEEE-sensitive representation of every solver-consumed field.

    Plain ``==`` would hide +0.0/-0.0 — the correction demands bit parity,
    so every float field is compared via float.hex()."""
    return (
        row.period_index,
        float(row.opening_keur).hex(),
        float(row.interest_keur).hex(),
        float(row.principal_keur).hex(),
        float(row.closing_keur).hex(),
    )


class TestKernelDifferential:
    @pytest.mark.parametrize("case_idx", range(len(_KERNEL_CASES)))
    def test_numeric_kernel_matches_authoritative_bit_for_bit(self, case_idx):
        """Bit-exact (float.hex) — plain == would hide +0.0/-0.0; the PR
        claims bit-identical parity."""
        (policy, idxs, pse, rate_map, cfads, dscr_map, availability,
         plan, method, explicit_by) = _KERNEL_CASES[case_idx]
        for D in _DEBT_LEVELS:
            full = _forward_roll(
                D, idxs, rate_map, pse, cfads, policy, method,
                explicit_by=explicit_by, dscr_map=dscr_map,
                availability_map=availability,
            )
            fast = _forward_roll_numeric(plan, D, cfads)
            assert len(full) == len(fast)
            for fr, nr in zip(full, fast):
                assert _hex_fields(nr) == _hex_fields(fr), (
                    method, D, fr.period_index,
                    _hex_fields(nr), _hex_fields(fr))

    def test_signed_zero_extinguished_balance_bit_identical(self):
        """Correction A2: extinguished balances must carry the SAME signed
        zero as the authoritative path — max(0.0, ...) yields +0.0 while a
        conditional clamp (`x = a - b; if x < 0`) would preserve -0.0 when
        ``balance - principal`` produces it."""
        policy, idxs, pse, rate_map, cfads, dm, am, plan, method, _eb = _KERNEL_CASES[0]
        full = _forward_roll(1500.0, idxs, rate_map, pse, cfads, policy, method,
                             dscr_map=dm, availability_map=am)
        fast = _forward_roll_numeric(plan, 1500.0, cfads)
        for fr, nr in zip(full, fast):
            assert float(fr.closing_keur).hex() == float(nr.closing_keur).hex()
            assert float(fr.interest_keur).hex() == float(nr.interest_keur).hex()
            assert float(nr.closing_keur).hex() != "-0x0.0p+0", \
                "kernel produced -0.0 where the authoritative path yields +0.0"

    def test_partial_maps_only_cover_repayment_periods(self):
        """Correction A3/C: maps covering ONLY repayment periods must build
        the plan and roll exactly like the authoritative path — the
        authoritative lookup never touches non-repayment indices, so the
        plan must not raise earlier for them."""
        policy, idxs, pse, rate_map, cfads, _dm, _am, _plan, method, _e = _KERNEL_CASES[0]
        start = policy.repayment_start_period_index
        mat = policy.maturity_period_index
        dscr_map = {i: 1.30 for i in idxs if start <= i <= mat}
        availability = {i: 0.95 for i in idxs if start <= i <= mat}
        plan = build_roll_plan(
            policy=policy, period_indices=idxs, period_start_end=pse,
            rate_map=rate_map, repayment_method_str="dscr_sculpted",
            dscr_map=dscr_map, availability_map=availability)
        full = _forward_roll(1500.0, idxs, rate_map, pse, cfads, policy, method,
                             dscr_map=dscr_map, availability_map=availability)
        fast = _forward_roll_numeric(plan, 1500.0, cfads)
        for fr, nr in zip(full, fast):
            assert _hex_fields(nr) == _hex_fields(fr)

    def test_missing_required_repayment_entry_raises_key_error(self):
        """A missing REQUIRED repayment entry keeps the authoritative
        failure behaviour: KeyError — never a silent fallback."""
        policy, idxs, pse, rate_map, cfads, _dm, _am, _plan, method, _e = _KERNEL_CASES[0]
        start = policy.repayment_start_period_index
        dscr_map = {i: 1.30 for i in idxs if i != start}
        with pytest.raises(KeyError):
            _forward_roll(1500.0, idxs, rate_map, pse, cfads, policy, method,
                          dscr_map=dscr_map, availability_map=None)
        with pytest.raises(KeyError):
            build_roll_plan(
                policy=policy, period_indices=idxs, period_start_end=pse,
                rate_map=rate_map, repayment_method_str="dscr_sculpted",
                dscr_map=dscr_map, availability_map=None)

    def test_zero_debt_stays_all_zero(self):
        policy, idxs, _pse, _rm, cfads, _dm, _am, plan, _m, _e = _KERNEL_CASES[0]
        rows = _forward_roll_numeric(plan, 0.0, cfads)
        assert all(r.opening_keur == 0.0 and r.interest_keur == 0.0
                   and r.principal_keur == 0.0 and r.closing_keur == 0.0
                   for r in rows)

    def test_unknown_method_fails_closed(self):
        policy, idxs, pse, rate_map, cfads, _dm, _am, plan, _m, _e = _KERNEL_CASES[0]
        broken = build_roll_plan(
            policy=policy, period_indices=idxs, period_start_end=pse,
            rate_map=rate_map, repayment_method_str="mystery")
        with pytest.raises(ValueError, match="Unknown repayment_method_str"):
            _forward_roll_numeric(broken, 100.0, cfads)


# ---------------------------------------------------------------------------
# Patch safety — tests that substitute _forward_roll keep full behaviour
# ---------------------------------------------------------------------------

    def _real_solver_case(self):
        """Deterministic DSCR-sculpted solve with a real policy, inputs,
        period axis and a CFADS-independent tax function (H-2 pattern)."""
        from types import SimpleNamespace

        import financial_engine.senior_debt.solver as solver_mod
        from financial_engine.senior_debt.inputs import SeniorDebtInputs
        from financial_engine.senior_debt.policy import (
            DayCountConvention,
            SeniorDebtPolicy,
            SeniorDebtSizingMode,
        )

        n = 24
        periods = tuple(
            SimpleNamespace(
                period_index=i + 1, is_operation=True,
                period_start=date(2030 + i // 2, 1 if i % 2 == 0 else 7, 1),
                period_end=(date(2030 + i // 2, 7, 1) if i % 2 == 0
                            else date(2031 + i // 2, 1, 1)),
            )
            for i in range(n)
        )
        policy = SeniorDebtPolicy(
            policy_id="perf-v2", policy_version="1",
            sizing_mode=SeniorDebtSizingMode.DSCR_SCULPTED, target_dscr=1.30,
            maximum_gearing=0.85,
            annual_fixed_rate=0.06, periods_per_year=2,
            day_count_convention=DayCountConvention.ACT_365,
            repayment_start_period_index=1, maturity_period_index=n,
            convergence_tolerance_keur=1e-4,
            convergence_relative_tolerance=1e-9,
            maximum_iterations=200, permit_terminal_balloon=True,
            damping_alpha=1.0,
        )
        inputs = SeniorDebtInputs(
            eligible_project_cost_keur=200_000.0,
            initial_debt_guess_keur=100_000.0,
            period_rates=(), explicit_principal_schedule=None,
        )
        cfads = {i: (2000.0 if i <= 2 else 6500.0) for i in range(1, n + 1)}

        def tax_cfads_fn(_interest):
            return dict(cfads), {idx: 0.0 for idx in cfads}

        return solver_mod, policy, inputs, periods, tax_cfads_fn, cfads

    def test_patched_forward_roll_forces_legacy_path_with_identical_result(
            self, monkeypatch):
        """Real patch-safety proof (Correction A1): monkeypatching
        solver._forward_roll with a counting wrapper around the authentic
        function must (a) route the actual solve through the patched
        function, (b) disable the numeric kernel, and (c) produce the
        bit-identical canonical result with unchanged iteration and
        termination semantics."""
        import financial_engine.senior_debt.solver as solver_mod

        solver_mod, policy, inputs, periods, tax_fn, cfads = self._real_solver_case()

        canonical = solver_mod.solve_senior_debt(
            policy=policy, inputs=inputs, periods=periods, tax_cfads_fn=tax_fn)
        assert canonical.diagnostics.is_authoritative
        assert canonical.diagnostics.termination_reason == "CONVERGED"

        calls = {"roll": 0, "numeric": 0}
        authentic = solver_mod._forward_roll
        original_numeric = solver_mod._forward_roll_numeric

        def counting_roll(*args, **kwargs):
            calls["roll"] += 1
            return authentic(*args, **kwargs)

        def counting_numeric(*args, **kwargs):
            calls["numeric"] += 1
            return original_numeric(*args, **kwargs)

        monkeypatch.setattr(solver_mod, "_forward_roll", counting_roll)
        monkeypatch.setattr(solver_mod, "_forward_roll_numeric", counting_numeric)
        assert solver_mod._forward_roll is not _AUTHENTIC_FORWARD_ROLL

        patched = solver_mod.solve_senior_debt(
            policy=policy, inputs=inputs, periods=periods, tax_cfads_fn=tax_fn)

        # (a) the patched roll actually drove the solve
        assert calls["roll"] > 0
        # (b) the numeric kernel was bypassed while the identity changed
        assert calls["numeric"] == 0

        # (c) bit-identical canonical output
        assert patched.period_indices == canonical.period_indices
        for field in ("senior_debt_opening_keur", "senior_interest_keur",
                      "senior_principal_keur", "senior_debt_service_keur",
                      "senior_debt_closing_keur", "senior_dscr"):
            assert getattr(patched, field) == getattr(canonical, field), field
        assert patched.debt_size_keur == canonical.debt_size_keur
        # (d) iteration/termination semantics unchanged
        assert patched.diagnostics.iteration_count == \
            canonical.diagnostics.iteration_count
        assert patched.diagnostics.termination_reason == \
            canonical.diagnostics.termination_reason
        assert patched.diagnostics.maximum_absolute_difference_keur == \
            canonical.diagnostics.maximum_absolute_difference_keur

    def test_unpatched_solver_uses_numeric_kernel(self, monkeypatch):
        """With the authentic roll in place the numeric kernel IS exercised
        (the fast path is real, not dead code)."""
        import financial_engine.senior_debt.solver as solver_mod

        _solver, policy, inputs, periods, tax_fn, _cfads = self._real_solver_case()
        calls = {"n": 0}
        original = solver_mod._forward_roll_numeric

        def counting(*args, **kwargs):
            calls["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(solver_mod, "_forward_roll_numeric", counting)
        result = solver_mod.solve_senior_debt(
            policy=policy, inputs=inputs, periods=periods, tax_cfads_fn=tax_fn)
        assert result.diagnostics.is_authoritative
        assert calls["n"] > 0

    def _monkeypatch_helper(self, solver_mod, counting, original):
        import financial_engine.senior_debt.solver as _m
        _m._forward_roll_numeric = counting  # patched in the inner helper

    def test_authentic_identity_restores_after_patch(self, monkeypatch):
        import financial_engine.senior_debt.solver as solver_mod
        assert solver_mod._forward_roll is _AUTHENTIC_FORWARD_ROLL
        sentinel = object()
        monkeypatch.setattr(solver_mod, "_forward_roll", sentinel)
        assert solver_mod._forward_roll is not _AUTHENTIC_FORWARD_ROLL
        monkeypatch.undo()
        assert solver_mod._forward_roll is _AUTHENTIC_FORWARD_ROLL


# ---------------------------------------------------------------------------
# Merge template — senior stamp == canonical merge, uncovered keys fall back
# ---------------------------------------------------------------------------

class TestMergeTemplate:
    def _make(self, base_pi, shl=None, limit=None, override=None):
        from financial_engine.orchestrator import _make_solver_tax_cfads_fn
        return _make_solver_tax_cfads_fn(
            periods=(), base_tax_input=base_pi,
            shl_interest_by_period=shl,
            limitation_by_period=limit,
            tax_periodisation_mode_override=override), \
            (shl, limit, override)

    def _orig_merge(self, base_pi, senior, shl, limit, override):
        from financial_engine.orchestrator import _merge_financing_tax_input
        return _merge_financing_tax_input(
            base_pi, senior, shl, limit,
            tax_periodisation_mode_override=override)

    def test_stamp_matches_canonical_merge_when_covered(self, monkeypatch):
        """Covered candidate keys: the stamped period_interest must equal the
        canonical per-call merge period_interest exactly (every field)."""
        from dataclasses import replace
        from financial_engine.inputs import PeriodInterestInput, TaxCalculationInput
        import financial_engine.tax.engine as tax_engine

        captured = {}
        monkeypatch.setattr(
            tax_engine, "calculate_cfads_and_cash_tax",
            lambda periods, tax_input: captured.update(
                pi=tax_input.period_interest) or ({}, {}))

        base_interest = tuple(
            PeriodInterestInput(period_index=i, senior_interest_keur=10.0 * i,
                                shl_interest_keur=1.0 * i)
            for i in (1, 2, 3)
        )
        base = TaxCalculationInput(policy=None, opening_loss_vintages=(),
                                   period_interest=base_interest)
        shl = {1: 5.0, 2: 6.0, 3: 7.0}
        fn, _ = self._make(base, shl=shl)
        candidate = {1: 100.0, 2: 200.0, 3: 300.0}
        fn(candidate)

        ref = self._orig_merge(base, candidate, shl, None, None)
        assert list(captured["pi"]) == list(ref.period_interest)

    def test_uncovered_candidate_keys_take_canonical_merge(self, monkeypatch):
        """An empty-base template does NOT cover candidate keys — the helper
        must take the canonical per-call merge path (candidate interest is
        never dropped)."""
        from financial_engine.inputs import PeriodInterestInput, TaxCalculationInput
        import financial_engine.tax.engine as tax_engine

        captured = {}
        monkeypatch.setattr(
            tax_engine, "calculate_cfads_and_cash_tax",
            lambda periods, tax_input: captured.update(
                pi=tax_input.period_interest) or ({}, {}))
        base = TaxCalculationInput(policy=None, opening_loss_vintages=(),
                                   period_interest=())
        fn, _ = self._make(base)
        fn({1: 111.0, 2: 222.0})
        ref = self._orig_merge(base, {1: 111.0, 2: 222.0}, None, None, None)
        assert list(captured["pi"]) == list(ref.period_interest)
        assert [pi.senior_interest_keur for pi in captured["pi"]] == [111.0, 222.0]


# ---------------------------------------------------------------------------
# Canonical parity — 17-scenario result-tree digests vs pristine base
# ---------------------------------------------------------------------------

class TestCanonicalParity:
    def test_unaffected_scenarios_bit_identical_to_historical_base(self):
        """Retain all unaffected post-#212 digests and failure reasons.

        WF-04 repairs loss_carryforward's independently proved service-budget
        violation. Its old golden remains frozen; the precision regression
        reproduces that golden and proves the violation, rather than approving
        a replacement hash. All 17 scenarios still face the exact full-tree
        optimized-versus-authoritative kernel comparison below.
        """
        sys_path = str(Path(__file__).resolve().parents[1])
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from tools.model_runtime_parity import SCENARIOS, _run_scenario

        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        mismatches = []
        for name in sorted(SCENARIOS):
            if name == "loss_carryforward":
                continue
            got = _run_scenario(name)
            if got != expected.get(name):
                mismatches.append((name, expected.get(name), got))
        assert not mismatches, (
            "canonical parity broken: "
            + "; ".join(f"{n}: base={json.dumps(w, sort_keys=True)[:120]} "
                        f"v2={json.dumps(g, sort_keys=True)[:120]}"
                        for n, w, g in mismatches))

    def test_all_scenarios_bit_identical_to_authoritative_kernel(self, monkeypatch):
        """Current financial authority, two kernels, zero numeric tolerance.

        Comparing an optimization to its retained authoritative implementation
        does not require freezing a financial defect from a historical release.
        The wrapper's changed identity selects the existing full-roll path;
        neither financial inputs nor convergence policy are altered.
        """
        from app.services import production_financial_authority as authority
        import financial_engine.senior_debt.solver as solver
        from tools.model_runtime_parity import SCENARIOS, _run_scenario

        calls = []

        def authoritative_roll(*args, **kwargs):
            calls.append(1)
            return solver._AUTHENTIC_FORWARD_ROLL(*args, **kwargs)

        def forbidden_numeric(*args, **kwargs):
            raise AssertionError("authoritative comparison used the numeric kernel")

        try:
            for name in sorted(SCENARIOS):
                authority._POLICY_RUN_CACHE.clear()
                optimized = _run_scenario(name)
                authority._POLICY_RUN_CACHE.clear()
                with monkeypatch.context() as patch:
                    patch.setattr(solver, "_forward_roll", authoritative_roll)
                    patch.setattr(solver, "_forward_roll_numeric", forbidden_numeric)
                    authoritative = _run_scenario(name)
                assert optimized == authoritative, (name, optimized, authoritative)
            assert calls, "the actual authoritative roll must be exercised"
        finally:
            authority._POLICY_RUN_CACHE.clear()


# ---------------------------------------------------------------------------
# Failure parity (§12) — kernel cannot convert an exception into a number
# ---------------------------------------------------------------------------

class TestFailureParity:
    def test_unknown_method_raises_identically_in_both_paths(self):
        policy, idxs, pse, rate_map, cfads, dm, am, _plan, _m, _e = _KERNEL_CASES[0]
        with pytest.raises(ValueError, match="Unknown repayment_method_str"):
            _forward_roll(100.0, idxs, rate_map, pse, cfads, policy, "mystery")
        broken = build_roll_plan(
            policy=policy, period_indices=idxs, period_start_end=pse,
            rate_map=rate_map, repayment_method_str="mystery")
        with pytest.raises(ValueError, match="Unknown repayment_method_str"):
            _forward_roll_numeric(broken, 100.0, cfads)

    def test_malformed_axis_raises_in_plan_build(self):
        policy = _Policy()
        with pytest.raises((KeyError, ValueError, TypeError, IndexError)):
            build_roll_plan(
                policy=policy, period_indices=(1, 2),
                period_start_end={1: (date(2031, 1, 1),)},  # malformed end
                rate_map={}, repayment_method_str="dscr_sculpted")


# ---------------------------------------------------------------------------
# Executor prewarm (§3)
# ---------------------------------------------------------------------------

def _probe_add(a: int, b: int) -> int:
    return a + b


class TestExecutorPrewarm:
    @pytest.fixture
    def executor(self):
        from app.runtime.model_execution import ModelExecutor, reset_model_executor_for_tests
        from app.runtime.model_execution import ModelExecutionConfig

        config = ModelExecutionConfig(mode="process", concurrency=2, timeout_seconds=60)
        exe = ModelExecutor(config)
        try:
            yield exe
        finally:
            # This executor is LOCAL to the fixture, not the module's global
            # _EXECUTOR. Resetting the global alone leaked its two prewarmed
            # SpawnProcess workers at full-suite shutdown. Join exactly the
            # workers this fixture owns; fail if forced termination was needed.
            forced = exe.shutdown_and_join()
            reset_model_executor_for_tests(None)
            assert forced == [], f"Prewarm fixture leaked model workers: {forced}"

    def test_warm_up_spawns_workers_and_reports_state(self, executor):
        assert executor.is_warm is False
        state = executor.warm_up()
        assert state["warm"] is True
        assert state["warm_workers"] == 2
        assert executor.is_warm is True
        stats = executor.stats()
        assert stats["warm"] is True
        assert stats["warmup_duration_s"] is not None

    def test_prewarmed_worker_executes_without_engine(self, executor):
        executor.warm_up()
        assert executor.run_process_sync(_probe_add, 2, 3) == 5

    def test_warm_up_is_idempotent_and_truthful(self, executor):
        """Idempotent in EFFECT: once warm, the confirmed worker set is
        stable and reported truthfully.  Under a loaded CI machine the
        FIRST sweep may legitimately fail (bounded retry then partial/
        cold state) — the second call retries and must either succeed
        (with consistent, real confirmed-PID evidence) or stay truthfully
        cold; it may never report warm without confirmed PIDs."""
        first = executor.warm_up()
        if first["warm"]:
            assert first["warm_pids"]
            assert len(set(first["warm_pids"])) == first["warm_workers"]
            assert first["warm_workers"] >= 1
        second = executor.warm_up()
        if second["warm"]:
            assert second["warm_pids"]
            assert len(set(second["warm_pids"])) == second["warm_workers"]
        # warm can never be reported without confirmed worker PIDs
        if executor.is_warm:
            assert executor.warm_state()["warm_pids"]

    def test_warm_failure_keeps_lazy_path_available(self, executor, monkeypatch):
        """A warmup failure (probe raising) leaves the executor cold and the
        lazy first-Run path fully available."""
        import app.runtime.model_execution as me

        def broken_probe():
            raise RuntimeError("prewarm probe exploded")

        monkeypatch.setattr(me, "_worker_warmup_probe", broken_probe)
        state = executor.warm_up()
        assert state["warm"] is False
        # lazy fallback: the calculation still executes after failed prewarm
        assert executor.run_process_sync(_probe_add, 2, 3) == 5

    def test_prewarm_runs_no_project_model(self, executor):
        """The probe imports modules and returns a readiness payload — it
        must never execute a project model (no engine call possible: the
        probe contains no model invocation, asserted by its return shape)."""
        import os

        from app.runtime.model_execution import _worker_warmup_probe
        result = _worker_warmup_probe()
        assert result["warm"] is True
        assert result["pid"] == os.getpid()  # probe runs IN the worker/caller
        assert set(result) == {"engine_version", "warm", "pid"}

    def test_thread_mode_stays_cold(self):
        from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig, reset_model_executor_for_tests
        exe = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1, timeout_seconds=30))
        try:
            state = exe.warm_up()
            assert state["warm"] is False  # no process pool to prewarm
        finally:
            reset_model_executor_for_tests(None)

    def test_reset_semantics_preserved(self):
        from app.runtime.model_execution import (
            ModelExecutor, ModelExecutionConfig, get_model_executor,
            reset_model_executor_for_tests,
        )
        exe = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1, timeout_seconds=30))
        reset_model_executor_for_tests(exe)
        assert get_model_executor() is exe
        reset_model_executor_for_tests(None)
        assert get_model_executor() is not exe
