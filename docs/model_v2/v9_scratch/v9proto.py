"""V9-A isolated numerical prototypes (scratch only — never imported by production).

Every candidate is built at runtime from the canonical source text of the production
function (inspect.getsource) with explicit, asserted text substitutions, compiled into a
COPY of the defining module's namespace, and installed by rebinding module attributes for
the duration of a context manager. No production file is written. All financial
calculations stay inside the canonical callbacks (Stage B2, run_project_financing_model,
run_senior_debt_model, solve_senior_debt, tax/CFADS, SHL, reconcile_financing_stack,
policy target function); the prototypes only change the ORDER and NUMBER of canonical
evaluations and the iterate that is fed to them.

Variants (combinable flags):
  B1  defer the G2A DSCR-only capacity run to the converged SHL candidate (structural)
  BA  safeguarded Anderson acceleration of the PR9 construction-IDC outer state
  BW  warm-start the SHL<->tax fixed point from the previous converged SHL interest vector
  C   joint reduced solver: DSRA initial funding + construction cost state iterated as ONE
      fixed point (Anderson, safeguarded) — replaces the DSRA-policy loop of full engine runs
  D   analytic G2A reduction: SHL candidate seeded from the Sources & Uses identity with the
      Senior predicted from the previous G2A evaluation (exact when the binding Senior
      constraint is unchanged); the canonical confirmation iteration still decides
"""
from __future__ import annotations

import contextlib
import dataclasses as dc
import importlib
import inspect
import math
import sys
import types

import os as _os
sys.path.insert(0, _os.environ.get("V9_ROOT", "/home/user/v9"))

import financial_engine.financing.project as P  # noqa: E402
import financial_engine.financing.generic_product_policy as GP  # noqa: E402
import financial_engine.orchestrator as O  # noqa: E402

ORIG_G2A = P.run_project_financing_model
ORIG_IDC = P._run_with_construction_idc
ORIG_POLICY = GP.run_with_generic_financing_policy
ORIG_SHLTAX = O._run_senior_debt_model_with_shl


def _sub(src: str, old: str, new: str) -> str:
    n = src.count(old)
    if n != 1:
        raise AssertionError(f"substitution anchor found {n}x: {old[:90]!r}")
    return src.replace(old, new)


def _compile(fn, src: str, extra: dict | None = None):
    ns = dict(fn.__globals__)
    if extra:
        ns.update(extra)
    code = compile(src, f"<v9-scratch:{fn.__name__}>", "exec")
    exec(code, ns)
    return ns[fn.__name__], ns


def _rebind(orig, new):
    """Rebind every module-level reference to ``orig``; return an undo list."""
    undo = []
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "") in ("v9proto", "harness", "__main__"):
            continue  # never rebind the prototype's own handles to the canonical originals
        d = getattr(mod, "__dict__", None)
        if not isinstance(d, dict):
            continue
        for k, v in list(d.items()):
            if v is orig:
                d[k] = new
                undo.append((d, k, orig))
    return undo


# ---------------------------------------------------------------------------
# Shared prototype state (lives only inside an installed context)
# ---------------------------------------------------------------------------
class V9State:
    def __init__(self, flags):
        self.flags = set(flags)
        self.joint = None            # JointCtx while a joint solve is active
        self.fallback = False        # True while the canonical path re-decides a Run
        self.patches = []            # (module dict, key, canonical, candidate)
        self.last_senior = None      # D: previous G2A Senior evaluation (same run)
        self.shl_memory = {}         # BW: axis -> converged SHL gross interest
        self.stats = {"aa_steps": 0, "aa_rejected": 0, "d_hits": 0, "d_miss": 0,
                      "joint_iters": 0, "joint_fallback": 0, "inject": 0}


STATE: V9State | None = None


# ---------------------------------------------------------------------------
# Anderson accelerator (type II), safeguarded, with terminal Picard phase
# ---------------------------------------------------------------------------
class Anderson:
    def __init__(self, m=2, switch_tol=1e-4, decrease=0.5):
        self.m, self.switch_tol, self.decrease = m, switch_tol, decrease
        self.xs, self.gs = [], []
        self.x_prev = None
        self.r_prev = math.inf
        self.terminal = False

    def step(self, g):
        """Given g = G(x_prev), return (x_next, plain_flag)."""
        if self.x_prev is None:
            self.x_prev = list(g)
            return list(g), True
        x = self.x_prev
        f = [gi - xi for gi, xi in zip(g, x)]
        r = max(abs(v) for v in f)
        accelerate = STATE is not None and not self.terminal
        if r <= self.switch_tol:
            self.terminal = True
            accelerate = False
        if accelerate and r > self.decrease * self.r_prev and self.xs:
            # insufficient decrease after an accelerated step: reset and fall back
            STATE.stats["aa_rejected"] += 1
            self.xs, self.gs = [], []
            accelerate = False
        self.xs.append(list(x))
        self.gs.append(list(g))
        self.xs, self.gs = self.xs[-(self.m + 1):], self.gs[-(self.m + 1):]
        self.r_prev = r
        out, plain = list(g), True
        if accelerate and len(self.xs) >= 2:
            cand = self._aa()
            if cand is not None and all(math.isfinite(v) for v in cand) and all(v >= 0.0 for v in cand):
                out, plain = cand, False
                STATE.stats["aa_steps"] += 1
        self.x_prev = list(out)
        return out, plain

    def _aa(self):
        import numpy as np
        X = np.array(self.xs, dtype=float)
        G = np.array(self.gs, dtype=float)
        F = G - X
        dF = (F[1:] - F[:-1]).T
        dG = (G[1:] - G[:-1]).T
        if not np.all(np.isfinite(dF)) or np.linalg.norm(dF) == 0.0:
            return None
        gamma, *_ = np.linalg.lstsq(dF, F[-1], rcond=None)
        return [float(v) for v in (G[-1] - dG @ gamma)]  # plain Python floats only


class JointCtx:
    """C: DSRA initial funding as an extra component of the construction fixed-point state."""

    def __init__(self, inputs_for, target, F0, dsra_tol):
        self.inputs_for, self.target, self.F0, self.dsra_tol = inputs_for, target, F0, dsra_tol
        self.final_inputs = None
        self.final_F = None
        self.result = None
        self.key = None


class _JointProbeDone(Exception):
    pass


class _JointBudgetExceeded(Exception):
    """The joint iteration budget is exhausted: hand the Run back to the canonical path."""


JOINT_MAX_ITERATIONS = 15


# ---------------------------------------------------------------------------
# G2A replica (B1, D)
# ---------------------------------------------------------------------------
def build_g2a(flags):
    src = inspect.getsource(ORIG_G2A)
    if "B1" in flags:
        src = _sub(src,
            "        capacity_result = run_senior_debt_model(capacity_model_input)\n"
            "        if capacity_result.senior_debt is None:\n"
            "            raise RuntimeError(\"G2A DSCR capacity result is unavailable\")\n"
            "        authoritative_dscr_capacity = capacity_result.senior_debt.debt_size_keur\n"
            "        if fin.debt_sizing_mode == DebtSizingMode.GEARING_CAP:\n",
            "        _v9_capacity_input = capacity_model_input\n"
            "        if fin.debt_sizing_mode == DebtSizingMode.GEARING_CAP:\n")
        src = _sub(src,
            "        else:\n"
            "            expected_final_senior = min(authoritative_dscr_capacity, gearing_capacity)\n",
            "")
        src = _sub(src,
            "    else:\n"
            "        raise RuntimeError(\"G2A_SHL_SENIOR_FIXED_POINT_DID_NOT_CONVERGE\")\n",
            "    else:\n"
            "        raise RuntimeError(\"G2A_SHL_SENIOR_FIXED_POINT_DID_NOT_CONVERGE\")\n"
            "    # V9 B1: the DSCR-only capacity pass is evaluated once, at the converged candidate.\n"
            "    capacity_result = run_senior_debt_model(_v9_capacity_input)\n"
            "    if capacity_result.senior_debt is None:\n"
            "        raise RuntimeError(\"G2A DSCR capacity result is unavailable\")\n"
            "    authoritative_dscr_capacity = capacity_result.senior_debt.debt_size_keur\n")
    if "BG" in flags:
        src = _sub(src,
            "        maximum_difference = abs(derived_shl - candidate_shl)\n"
            "        if maximum_difference <= convergence_tolerance_keur:\n"
            "            break\n"
            "        candidate_shl = derived_shl\n",
            "        maximum_difference = abs(derived_shl - candidate_shl)\n"
            "        if maximum_difference <= convergence_tolerance_keur:\n"
            "            break\n"
            "        # V9 BG: safeguarded secant on the scalar SHL map (plain step unless the\n"
            "        # secant slope certifies a contraction and the step stays bounded)\n"
            "        _v9_f = derived_shl - candidate_shl\n"
            "        _v9_next = derived_shl\n"
            "        if _v9_prev is not None and candidate_shl != _v9_prev[0] and _v9_f != _v9_prev[1]:\n"
            "            _v9_slope = (_v9_f - _v9_prev[1]) / (candidate_shl - _v9_prev[0])\n"
            "            _v9_rho = 1.0 + _v9_slope\n"
            "            if abs(_v9_rho) < 0.9 and abs(_v9_f) < abs(_v9_prev[1]):\n"
            "                _v9_try = candidate_shl - _v9_f / _v9_slope\n"
            "                if math.isfinite(_v9_try) and _v9_try >= 0.0 and abs(_v9_try - derived_shl) <= 10.0 * abs(_v9_f):\n"
            "                    _v9_next = _v9_try\n"
            "                    if _v9_state() is not None:\n"
            "                        _v9_state().stats['bg_steps'] = _v9_state().stats.get('bg_steps', 0) + 1\n"
            "        _v9_prev = (candidate_shl, _v9_f)\n"
            "        candidate_shl = _v9_next\n")
        src = _sub(src,
            "    maximum_difference = float(\"inf\")\n",
            "    maximum_difference = float(\"inf\")\n"
            "    _v9_prev = None\n")
    if "D" in flags:
        src = _sub(src,
            "    model_result = None\n"
            "    authoritative_dscr_capacity = 0.0\n",
            "    model_result = None\n"
            "    authoritative_dscr_capacity = 0.0\n"
            "    _v9_pred = _v9_state().last_senior if _v9_state() is not None else None\n"
            "    _v9_seeded = False\n"
            "    if _v9_pred is not None and _v9_pred[0] == fin.debt_sizing_mode:\n"
            "        _v9_mode, _v9_binding, _v9_sen = _v9_pred\n"
            "        _v9_s = gearing_capacity if _v9_binding == 'GEARING' else min(_v9_sen, gearing_capacity)\n"
            "        candidate_shl, additional_equity = reconcile_financing_stack(\n"
            "            total_project_uses_keur=uses.total_project_uses_keur,\n"
            "            final_senior_commitment_keur=_v9_s,\n"
            "            junior_or_other_main_project_funding_keur=fin.junior_or_other_project_funding_keur,\n"
            "            share_capital_keur=fin.share_capital_keur,\n"
            "            share_premium_keur=fin.share_premium_keur,\n"
            "            other_equity_funding_before_shl_keur=fin.other_equity_funding_before_shl_keur,\n"
            "            sponsor_funding_mode=fin.sponsor_funding_mode,\n"
            "        )\n"
            "        _v9_seeded = True\n")
        # the canonical seed initialiser below resets additional_equity; keep the S&U value when seeded
        src = _sub(src,
            "    derived_shl = candidate_shl\n"
            "    additional_equity = 0.0  # derived residual; overwritten each iteration by reconcile_financing_stack\n",
            "    derived_shl = candidate_shl\n"
            "    if not _v9_seeded:\n"
            "        additional_equity = 0.0\n")
        src = _sub(src,
            "    assert model_result is not None and model_result.senior_debt is not None\n",
            "    assert model_result is not None and model_result.senior_debt is not None\n"
            "    if _v9_state() is not None:\n"
            "        _v9_st = _v9_state()\n"
            "        _v9_st.stats['d_hits' if (_v9_seeded and iteration == 1) else 'd_miss'] += 1\n"
            "        _v9_b = 'GEARING' if abs(model_result.senior_debt.debt_size_keur - gearing_capacity) <= convergence_tolerance_keur else 'DSCR'\n"
            "        _v9_st.last_senior = (fin.debt_sizing_mode, _v9_b, model_result.senior_debt.debt_size_keur)\n")
    return _compile(ORIG_G2A, src, {"_v9_state": lambda: STATE})


# ---------------------------------------------------------------------------
# IDC outer loop replica (BA, C)
# ---------------------------------------------------------------------------
_LOOP_START = (
    "    stage_b2_result = None\n"
    "    prev_unfunded = float(\"inf\")\n"
)
_LOOP_END = "    # Final invariant: unfunded must be zero at convergence.\n"

_NEW_LOOP = '''
    stage_b2_result = None
    prev_unfunded = float("inf")
    _v9_st = _v9_state()
    _v9_joint = _v9_st.joint if _v9_st is not None else None
    _v9_acc = _V9Anderson() if (_v9_st is not None and not _v9_st.fallback and ({"BA", "C"} & _v9_st.flags)) else None
    _v9_F = _v9_joint.F0 if _v9_joint is not None else None
    _v9_target = _v9_joint.target(inner_result) if _v9_joint is not None else None

    for outer_iteration in range(1, outer_max_iterations + 1):
        uses = _project_uses(working_inputs)
        working_fin = working_inputs.financing
        runtime_cfg = build_construction_runtime_config(
            construction=cf,
            senior_commitment_keur=inner_result.final_senior_commitment_keur,
            equity_available_keur=inner_result.share_capital_keur,
            shl_available_keur=inner_result.derived_shl_cash_principal_keur,
            capex_amounts_keur=capex_amounts,
            share_premium_keur=inner_result.share_premium_keur,
            other_committed_equity_keur=inner_result.other_equity_funding_before_shl_keur,
            additional_equity_keur=inner_result.additional_equity_keur,
            junior_keur=inner_result.junior_or_other_main_project_funding_keur,
        )
        stage_b2_prov = run_stage_b2_provisional(runtime_cfg)
        _g = stage_b2_prov.capitalized_financing_costs
        _gv = [_g.senior_idc_keur, _g.senior_commitment_fee_keur, _g.structuring_fee_keur,
               _g.vat_idc_keur, _g.vat_commitment_fee_keur]
        if _v9_joint is not None:
            _gv.append(_v9_target)
        if _v9_acc is not None:
            _xv, _plain = _v9_acc.step(_gv)
        else:
            _xv, _plain = _gv, True
        if _plain:
            new_financing = _g
        else:
            new_financing = replace(_g, senior_idc_keur=_xv[0], senior_commitment_fee_keur=_xv[1],
                                    structuring_fee_keur=_xv[2], vat_idc_keur=_xv[3],
                                    vat_commitment_fee_keur=_xv[4])
        if _v9_joint is not None:
            _v9_F_prev, _v9_F = _v9_F, _xv[5]
            project_inputs = _v9_joint.inputs_for(_v9_F)
            fin = project_inputs.financing
        _iteration_shl_context = _typed_construction_shl_context(
            construction=cf,
            financing=fin,
            canonical_allocations=stage_b2_prov.canonical_allocations,
            provisional=True,
        )
        updated_capex = apply_capitalized_financing_costs(orig_capex, new_financing)
        working_inputs = replace(project_inputs, capex=updated_capex)
        inner_fin = replace(working_inputs.financing, construction_financing=None)
        inner_inputs = replace(working_inputs, financing=inner_fin)
        inner_result = run_project_financing_model(
            inner_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
            convergence_tolerance_keur=outer_tolerance_keur,
            maximum_iterations=outer_max_iterations,
            _typed_shl_context=(
                _iteration_shl_context
                if _iteration_shl_context.accrual_enabled
                else None
            ),
            _u2_period_financing_income=_u2_period_financing_income,
        )
        d_idc = abs(new_financing.senior_idc_keur - prev_idc)
        d_fee = abs(new_financing.senior_commitment_fee_keur - prev_fee)
        d_struct = abs(new_financing.structuring_fee_keur - prev_struct)
        d_senior = abs(inner_result.final_senior_commitment_keur - prev_senior)
        d_shl = abs(inner_result.derived_shl_cash_principal_keur - prev_shl)
        d_pik = abs(inner_result.shl_construction_pik_keur - prev_pik)
        d_uses = abs(inner_result.project_uses.total_project_uses_keur - prev_uses)
        d_unfunded = abs(stage_b2_prov.unfunded_uses_keur - prev_unfunded)
        outer_residual = max(d_idc, d_fee, d_struct, d_senior, d_shl, d_pik, d_uses, d_unfunded)
        prev_idc = new_financing.senior_idc_keur
        prev_fee = new_financing.senior_commitment_fee_keur
        prev_struct = new_financing.structuring_fee_keur
        prev_senior = inner_result.final_senior_commitment_keur
        prev_shl = inner_result.derived_shl_cash_principal_keur
        prev_pik = inner_result.shl_construction_pik_keur
        prev_uses = inner_result.project_uses.total_project_uses_keur
        prev_unfunded = stage_b2_prov.unfunded_uses_keur

        _v9_dsra_ok = True
        if _v9_joint is not None:
            _v9_target = _v9_joint.target(inner_result)
            _v9_dsra_ok = abs(_v9_target - _v9_F) <= _v9_joint.dsra_tol
            _v9_st.stats["joint_iters"] += 1
        if outer_residual <= outer_tolerance_keur and _plain and _v9_dsra_ok:
            break
        if _v9_joint is not None and outer_iteration >= _V9_JOINT_MAX:
            raise _V9JointBudget()
    else:
        raise RuntimeError(
            f"PR9_OUTER_G2A_CONSTRUCTION_FIXED_POINT_DID_NOT_CONVERGE: "
            f"outer_residual={outer_residual:.12f} kEUR after {outer_max_iterations} iterations"
        )
    if _v9_joint is not None:
        _v9_joint.final_inputs = project_inputs
        _v9_joint.final_F = _v9_F

'''


def build_idc(flags):
    src = inspect.getsource(ORIG_IDC)
    i0 = src.index(_LOOP_START)
    i1 = src.index(_LOOP_END)
    seg = src[i0:i1]
    # sanity: the replaced segment is exactly the canonical loop (one for-loop, one raise)
    assert seg.count("for outer_iteration in range(1, outer_max_iterations + 1):") == 1
    assert seg.count("PR9_OUTER_G2A_CONSTRUCTION_FIXED_POINT_DID_NOT_CONVERGE") == 1
    src = src[:i0] + _NEW_LOOP.lstrip("\n") + src[i1:]
    return _compile(ORIG_IDC, src, {"_v9_state": lambda: STATE, "_V9Anderson": Anderson,
                                    "_V9JointBudget": _JointBudgetExceeded, "_V9_JOINT_MAX": JOINT_MAX_ITERATIONS})


# ---------------------------------------------------------------------------
# BW: SHL<->tax warm start
# ---------------------------------------------------------------------------
def build_shltax():
    def warm(inputs, *, _test_only_initial_shl_interest_guess=None):
        st = STATE
        if st is None or _test_only_initial_shl_interest_guess is not None:
            return ORIG_SHLTAX(inputs, _test_only_initial_shl_interest_guess=_test_only_initial_shl_interest_guess)
        key = (inputs.senior_debt_policy.repayment_start_period_index,
               inputs.senior_debt_policy.maturity_period_index)
        guess = st.shl_memory.get(key)
        result = ORIG_SHLTAX(inputs, _test_only_initial_shl_interest_guess=guess)
        shl = result.shareholder_loan
        if shl is not None:
            st.shl_memory[key] = dict(zip(shl.period_indices, shl.shl_gross_interest_keur))
        return result
    return warm


# ---------------------------------------------------------------------------
# C: joint DSRA + construction solve replacing the policy loop of full engine runs
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _all_canonical():
    """Temporarily remove every candidate: the canonical code alone decides."""
    st = STATE
    saved = [(d, k, d[k]) for d, k, orig in st.undo_list]
    for d, k, orig in st.undo_list:
        d[k] = orig
    st.fallback = True
    try:
        yield
    finally:
        st.fallback = False
        for d, k, cur in saved:
            d[k] = cur


def _canonical(pi, run, policy):
    """Fallback: the canonical policy loop with every candidate removed."""
    with _all_canonical():
        return ORIG_POLICY(pi, run, policy)


def build_policy(g2a_fn):
    def joint_policy(pi, run, policy=GP.DEFAULT_GENERIC_FINANCING_POLICY):
        applied, construction_on, dsra_on = GP.apply_generic_financing_policy(pi, policy)
        if not (dsra_on and construction_on):
            return ORIG_POLICY(pi, run, policy)
        multiplier = int(pi.financing.dsra_months) * GP._PERIODS_PER_YEAR / 12.0

        def inputs_for(F):
            return GP.apply_generic_financing_policy(pi, policy, initial_dsra_keur=F)[0]

        def target(inner):
            return GP._peak_forward_debt_service_keur(
                types.SimpleNamespace(financing_result=inner)) * multiplier

        ctx = JointCtx(inputs_for, target, 0.0, policy.dsra_tolerance_keur)
        st = STATE
        probe_inputs = inputs_for(0.0)

        def patched(project_inputs, *a, **k):
            if st.joint is ctx and ctx.result is None and project_inputs is probe_inputs \
                    and not k.get("_u2_period_financing_income"):
                res = g2a_fn(project_inputs, *a, **k)
                ctx.result, ctx.key = res, (a, tuple(sorted((kk, repr(vv)) for kk, vv in k.items())))
                raise _JointProbeDone()
            if ctx.result is not None and project_inputs is ctx.final_inputs \
                    and not k.get("_u2_period_financing_income") \
                    and (a, tuple(sorted((kk, repr(vv)) for kk, vv in k.items()))) == ctx.key:
                st.stats["inject"] += 1
                return ctx.result
            return g2a_fn(project_inputs, *a, **k)

        undo = _rebind(g2a_fn, patched)
        try:
            st.joint = ctx
            try:
                run(probe_inputs)
            except _JointProbeDone:
                pass
            except Exception:  # noqa: BLE001 - any joint failure: the canonical path decides
                ctx.result = None
            st.joint = None
            if ctx.result is None or ctx.final_inputs is None:
                st.stats["joint_fallback"] += 1
                return _canonical(pi, run, policy)
            result = run(ctx.final_inputs)
        finally:
            st.joint = None
            for d, k, v in undo:
                d[k] = g2a_fn
        # canonical DSRA acceptance on the returned result (same test as the policy loop)
        funding = ctx.final_F
        residual = abs(GP._peak_forward_debt_service_keur(result) * multiplier - funding)
        if residual > policy.dsra_tolerance_keur:
            st.stats["joint_fallback"] += 1
            return _canonical(pi, run, policy)
        return result, ctx.final_inputs, GP.FinancingPolicyEvidence(
            GP.POLICY_AUTHORITY, construction_on, True, funding, st.stats["joint_iters"], residual)
    return joint_policy


@contextlib.contextmanager
def installed(flags):
    """Install a candidate (set of flags) for the duration of the block."""
    global STATE
    flags = set(flags)
    undo = []
    STATE = V9State(flags)
    try:
        g2a, idc = ORIG_G2A, ORIG_IDC
        g2a_ns = idc_ns = None
        if {"B1", "D", "BG"} & flags:
            g2a, g2a_ns = build_g2a(flags)
        if {"BA", "C", "R"} & flags:
            idc, idc_ns = build_idc(flags)
        # cross-link the scratch namespaces (each is a private copy of the module dict)
        if g2a_ns is not None:
            g2a_ns["_run_with_construction_idc"] = idc
        if idc_ns is not None:
            idc_ns["run_project_financing_model"] = g2a
        if g2a is not ORIG_G2A and "B1" in flags and not ({"D", "BG"} & flags):
            _g2a_replica = g2a

            def g2a(*a, _r=_g2a_replica, **k):  # noqa: F811 - B1 failure re-decision
                if STATE.joint is not None:
                    return _r(*a, **k)  # inside a joint solve the joint policy re-decides
                try:
                    return _r(*a, **k)
                except Exception:  # noqa: BLE001 - the canonical G2A decides failures
                    STATE.stats["redecide"] = STATE.stats.get("redecide", 0) + 1
                    with _all_canonical():
                        return ORIG_G2A(*a, **k)
            if idc_ns is not None:
                idc_ns["run_project_financing_model"] = g2a
        if g2a is not ORIG_G2A:
            undo += _rebind(ORIG_G2A, g2a)
        if idc is not ORIG_IDC:
            undo += _rebind(ORIG_IDC, idc)
        if "BW" in flags:
            undo += _rebind(ORIG_SHLTAX, build_shltax())
        if "C" in flags:
            undo += _rebind(ORIG_POLICY, build_policy(g2a))
        STATE.undo_list = undo
        yield STATE
    finally:
        for d, k, v in reversed(undo):
            d[k] = v
        STATE = None


def reset_run_state():
    """Per-run reset: no prototype memory survives between measured runs."""
    if STATE is not None:
        STATE.last_senior = None
        STATE.shl_memory = {}
