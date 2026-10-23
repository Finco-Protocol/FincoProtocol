"""V10 Stage 1 candidate dispatch: admission, immutable snapshot, native call, canonical result assembly.

Called only from the explicit hooks in ``senior_debt.solver`` and only while the current Run's
``NativeConfig.mode == "candidate"``. Every function here returns either a result that is
bit-identical to the canonical result, or ``None`` *before any native effect* so the canonical
Python runs (and raises whatever the canonical code raises). Nothing here raises to the engine.

Admission (all must hold, else decline with a recorded reason):
  1. verified loader + eligible runtime + authenticated canonical region still intact;
  2. the tax callback is one of the three canonical closures: exact canonical code object (from the
     authenticated factory), canonical globals, no defaults, every closure cell of the closure tree
     validated (function cells = authenticated functions / canonical nested closures sharing the
     same cell objects; module/class cells = the real objects; data cells = exact types);
  3. every numeric value crossing the ABI has the exact type ``float`` (or ``int`` for indices,
     years, counts) and every integer is representable, with derived additions checked natively;
  4. the structural predicates of the canonical raise sites in the replaced numeric region hold
     (vector/axis lengths, payment-period membership) - their violation means the canonical code
     would raise or take another path, so the kernel declines and the canonical code runs.
"""
from __future__ import annotations

import collections
import ctypes as C
import dataclasses
import struct
import types
from datetime import date

from . import loader as _loader
from .config import current_config, current_stats

_I64_LIMIT = 2 ** 53           # every Python int crossing the ABI is exactly representable and small
_GEOMETRY_KEY = "native_v10_geometry_v1"
_GEOMETRY_MAX = 64


class _Decline(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _decline(reason: str):
    raise _Decline(reason)


def _record_decline(reason: str) -> None:
    stats = current_stats()
    if stats is not None:
        stats.declines[reason] += 1


# ------------------------------------------------------------------ exact-type helpers
def _f(x, what: str) -> float:
    if type(x) is not float:
        _decline(f"TYPE_NOT_FLOAT:{what}")
    return x


def _i(x, what: str) -> int:
    if type(x) is not int or not (-_I64_LIMIT <= x <= _I64_LIMIT):
        _decline(f"INT_NOT_REPRESENTABLE:{what}")
    return x


def _floats(values, what: str) -> list:
    out = list(values)
    for v in out:
        if type(v) is not float:
            _decline(f"TYPE_NOT_FLOAT:{what}")
    return out


def _ints(values, what: str) -> list:
    out = list(values)
    for v in out:
        if type(v) is not int or not (-_I64_LIMIT <= v <= _I64_LIMIT):
            _decline(f"INT_NOT_REPRESENTABLE:{what}")
    return out


def _darr(values):
    return (C.c_double * max(1, len(values)))(*values)


def _iarr(values):
    return (C.c_int64 * max(1, len(values)))(*values)


# ------------------------------------------------------------------ canonical closure authentication
def _modules():
    import financial_engine.orchestrator as orch
    import financial_engine.run_scope as run_scope
    import financial_engine.senior_debt.solver as solver
    import financial_engine.tax.engine as tax
    import financial_engine.tax.loss_ledger as loss_ledger
    return orch, tax, solver, loss_ledger, run_scope


def _nested_code(func, qualname):
    from .provenance import _find_code
    return _find_code(func.__code__, qualname)


def _closure_cells(fn) -> dict:
    return dict(zip(fn.__code__.co_freevars, fn.__closure__ or ()))


def _authenticate_closure_tree(fn, factory, allowed_nested: tuple, cell_checks: dict) -> dict:
    """Validate a canonical closure and every nested closure it can call; return name -> value."""
    orch = _modules()[0]
    seen_cells: dict = {}
    values: dict = {}
    stack = [fn]
    visited = set()
    while stack:
        f = stack.pop()
        if id(f) in visited:
            continue
        visited.add(id(f))
        expected = _nested_code(factory, f.__code__.co_qualname)
        if f.__code__.co_qualname not in allowed_nested or expected is None or f.__code__ is not expected:
            _decline("CALLBACK_CODE_NOT_CANONICAL")
        if f.__globals__ is not orch.__dict__ or f.__defaults__ is not None or f.__kwdefaults__ is not None:
            _decline("CALLBACK_FUNCTION_ATTRIBUTES")
        if getattr(f, "__dict__", None):
            _decline("CALLBACK_FUNCTION_DICT")
        for name, cell in _closure_cells(f).items():
            if name in seen_cells and seen_cells[name] is not cell:
                _decline("CALLBACK_CELL_NOT_SHARED")      # closures must come from one factory frame
            seen_cells[name] = cell
            try:
                value = cell.cell_contents
            except ValueError:
                _decline("CALLBACK_CELL_EMPTY")
            values[name] = value
            if isinstance(value, types.FunctionType) and value.__code__.co_qualname.startswith(
                    factory.__code__.co_qualname + ".<locals>."):
                stack.append(value)
            else:
                check = cell_checks.get(name)
                if check is None:
                    _decline(f"CALLBACK_CELL_UNKNOWN:{name}")
                if not check(value):
                    _decline(f"CALLBACK_CELL_INVALID:{name}")
    return values


def _is(obj):
    return lambda v: v is obj


def _exact(cls, optional=False):
    return lambda v: (optional and v is None) or type(v) is cls


def _int_float_dict(optional=True):
    def check(v):
        if v is None:
            return optional
        return type(v) is dict and all(type(k) is int and type(x) is float for k, x in v.items())
    return check


def _periods_ok(v):
    from financial_engine.results import OperatingPeriodResult
    return type(v) is tuple and len(v) > 0 and all(type(p) is OperatingPeriodResult for p in v)


def _limitation_dict_ok(v):
    if v is None:
        return True
    if type(v) is not dict:
        return False
    for k, x in v.items():
        if type(k) is not int or x is None:
            return False
        home = getattr(type(x), "__module__", "")
        if not home.startswith("financial_engine.") or not dataclasses.is_dataclass(x):
            return False
    return True


def _callback_kind_and_cells(fn):
    orch, tax, solver, loss_ledger, run_scope = _modules()
    from financial_engine.inputs import TaxCalculationInput
    if not isinstance(fn, types.FunctionType):
        _decline("CALLBACK_NOT_FUNCTION")
    qn = fn.__code__.co_qualname
    if qn == "_make_solver_tax_cfads_fn.<locals>.tax_cfads_fn":
        checks = {
            "periods": _periods_ok, "base_tax_input": _exact(TaxCalculationInput),
            "template": _exact(TaxCalculationInput),
            "shl_interest_by_period": _int_float_dict(), "limitation_by_period": _limitation_dict_ok,
            "tax_periodisation_mode_override": lambda v: v is None or type(v) is str,
            "reset_candidate_components": lambda v: type(v) is bool,
            "_OrderedDict": _is(collections.OrderedDict), "_build_solver_tax_plan": _is(tax.build_solver_tax_plan),
            "_current_run_scope": _is(run_scope.current_run_scope), "_replace": _is(dataclasses.replace),
            "_struct": _is(struct), "_tax_engine": _is(tax),
            "calculate_cfads_and_cash_tax": _is(tax._AUTHENTIC_CALCULATE_CFADS_AND_CASH_TAX),
            "_solver_plan": lambda v: v is None or type(v) is tax.SolverTaxPlan,
            "_solver_plan_unavailable": lambda v: type(v) is bool,
            "_solver_context_key": lambda v: v is None or type(v) is tuple,
            "template_keys": lambda v: type(v) is frozenset and all(type(k) is int for k in v),
            "template_periods": lambda v: type(v) is tuple,
        }
        allowed = tuple(f"_make_solver_tax_cfads_fn.<locals>.{n}" for n in
                        ("tax_cfads_fn", "_evaluate_fast", "_candidate_key", "_context_key", "_pack_floats"))
        return "SOLVER_PLAN", _authenticate_closure_tree(fn, orch._make_solver_tax_cfads_fn, allowed, checks)
    from financial_engine.inputs import SeniorDebtModelInput
    from financial_engine.results import ProjectModelResult
    common = {
        "base_tax_input": _exact(TaxCalculationInput), "inputs": _exact(SeniorDebtModelInput),
        "bank_phase2a_result": _exact(ProjectModelResult),
        "calculate_cfads_and_cash_tax": _is(tax._AUTHENTIC_CALCULATE_CFADS_AND_CASH_TAX),
    }
    if qn == "run_senior_debt_model.<locals>.tax_cfads_fn":
        return "MERGE_SENIOR", _authenticate_closure_tree(
            fn, orch.run_senior_debt_model, ("run_senior_debt_model.<locals>.tax_cfads_fn",), common)
    if qn == "_run_senior_debt_model_with_shl.<locals>.final_tax_cfads_fn":
        checks = dict(common, final_shl_interest=_int_float_dict(optional=False),
                      bank_limitation_state=_exact(orch._DynamicInterestLimitationState))
        return "MERGE_FINAL", _authenticate_closure_tree(
            fn, orch._run_senior_debt_model_with_shl,
            ("_run_senior_debt_model_with_shl.<locals>.final_tax_cfads_fn",), checks)
    _decline("CALLBACK_NOT_ADMITTED")


# ------------------------------------------------------------------ tax context (static operands)
def _context_from_solver_plan(cells, cand_keys):
    orch, tax, *_ = _modules()
    if cells["_solver_plan_unavailable"]:
        _decline("SOLVER_PLAN_UNAVAILABLE")
    template_keys = cells["template_keys"]
    if not template_keys.issuperset(cand_keys):
        # canonical slow branch: typed merge + lean numeric tax
        merged = orch._merge_financing_tax_input(
            cells["base_tax_input"], {k: 0.0 for k in cand_keys}, cells["shl_interest_by_period"],
            cells["limitation_by_period"], tax_periodisation_mode_override=cells["tax_periodisation_mode_override"])
        return _context_from_merge(cells["periods"], merged, cand_keys)
    periods = cells["periods"]
    sp = tax.build_solver_tax_plan(periods, cells["template"], reset_candidate_components=cells["reset_candidate_components"])
    if sp is None:
        _decline("SOLVER_PLAN_NONE")         # canonical uses the typed replace path
    n = len(sp.tax_plan.rows)
    vecs = {k: _floats(getattr(sp, k), f"plan.{k}") for k in
            ("base_senior", "other_interest", "shl_tax_eligible", "shl_non_deductible", "reintegration", "financing_income")}
    if any(len(v) != n for v in vecs.values()):
        _decline("NUMERIC_TAX_VECTOR_AXIS_MISMATCH")
    reset = sp.reset_candidate_components
    other = [0.0] * n if reset else vecs["other_interest"]
    elig = [0.0] * n if reset else vecs["shl_tax_eligible"]
    nd = [0.0] * n if reset else vecs["shl_non_deductible"]
    sgross = [vecs["base_senior"][r] + vecs["other_interest"][r] + vecs["shl_tax_eligible"][r] for r in range(n)]
    return dict(periods=periods, policy=sp.policy, opening=sp.opening_loss_vintages, plan=sp.tax_plan,
                other=other, elig=elig, nd=nd, sgross=sgross, snd=vecs["shl_non_deductible"],
                reint=vecs["reintegration"], fin=vecs["financing_income"])


def _context_from_merge(periods, merged, cand_keys):
    orch, tax, *_ = _modules()
    from financial_engine.policies.tax import TaxBasisPeriodisation, TaxPolicy
    from financial_engine.tax.tax_year import _resolve_shl_tax_eligible_interest
    policy = merged.policy
    if type(policy) is not TaxPolicy:
        _decline("TAX_POLICY_TYPE")
    if policy.tax_basis_periodisation == TaxBasisPeriodisation.MODEL_YEAR_PAIRING:
        _decline("TAX_PATH_MODEL_YEAR_PAIRING")
    plan = tax._tax_plan_for(periods)
    if plan.fallback:
        _decline("TAX_PLAN_FALLBACK")
    interest_map = tax._build_interest_map(merged.period_interest)
    adj_map = tax._build_adj_map(merged.period_adjustments)
    fin_map = tax._build_financing_income_map(merged)
    other, elig, nd, sgross, snd, reint, fin = [], [], [], [], [], [], []
    for idx, _k, _s in plan.rows:
        pi = interest_map.get(idx)
        if pi:
            e, n = _resolve_shl_tax_eligible_interest(pi, policy)
            o = _f(pi.other_interest_keur, "other_interest")
            other.append(o); elig.append(_f(e, "shl_eligible")); nd.append(_f(n, "shl_nd"))
            sgross.append(_f(pi.senior_interest_keur, "senior_interest") + o + e); snd.append(n)
        else:
            if idx in cand_keys:
                _decline("CANDIDATE_ROW_WITHOUT_INTEREST_INPUT")
            other.append(0.0); elig.append(0.0); nd.append(0.0); sgross.append(0.0); snd.append(0.0)
        reint.append(_f(adj_map.get(idx, 0.0), "reintegration"))
        fin.append(_f(fin_map.get(idx, 0.0), "financing_income"))
    return dict(periods=periods, policy=policy, opening=merged.opening_loss_vintages, plan=plan,
                other=other, elig=elig, nd=nd, sgross=sgross, snd=snd, reint=reint, fin=fin)


def _tax_context(fn, cand_keys):
    orch = _modules()[0]
    kind, cells = _callback_kind_and_cells(fn)
    zeros = {k: 0.0 for k in cand_keys}
    if kind == "SOLVER_PLAN":
        return _context_from_solver_plan(cells, cand_keys)
    inputs = cells["inputs"]
    override = inputs.debt_sizing_case.tax_periodisation_mode_override
    if not (override is None or type(override) is str):
        _decline("OVERRIDE_TYPE")
    if kind == "MERGE_SENIOR":
        merged = orch._merge_financing_tax_input(cells["base_tax_input"], zeros, tax_periodisation_mode_override=override)
    else:
        merged = orch._merge_financing_tax_input(cells["base_tax_input"], zeros, cells["final_shl_interest"],
                                                 cells["bank_limitation_state"].limitation_by_period,
                                                 tax_periodisation_mode_override=override)
    periods = cells["bank_phase2a_result"].periods
    if not _periods_ok(periods):
        _decline("PERIODS_TYPE")
    return _context_from_merge(periods, merged, cand_keys)


# ------------------------------------------------------------------ geometry (Run-scoped, bounded)
def _geometry(tp, periods):
    _, _, _, _, run_scope = _modules()
    scope = run_scope.current_run_scope()
    cache = None
    if scope is not None:
        cache = scope.get(_GEOMETRY_KEY)
        if cache is None:
            cache = scope[_GEOMETRY_KEY] = collections.OrderedDict()
        hit = cache.get(id(tp))
        if hit is not None and hit[0] is tp and hit[1] is periods:
            cache.move_to_end(id(tp))
            return hit[2]
    rows = tp.rows
    row_kind, slot_start, slot_count, slot_pos, slot_frac = [], [], [], [], []
    for idx, kind, slots in rows:
        row_kind.append(_i(kind, "row_kind")); slot_start.append(len(slot_pos)); slot_count.append(len(slots))
        for pos, frac in slots:
            slot_pos.append(_i(pos, "slot_pos")); slot_frac.append(_f(frac, "slot_frac"))
    sorted_idx = _ints(tp.sorted_idx, "sorted_idx")
    idx_min = min(sorted_idx); span = max(sorted_idx) - idx_min + 1
    if span > 1_000_000:
        _decline("PERIOD_INDEX_SPAN")
    idx_to_sorted = [-1] * span
    for s, idx in enumerate(sorted_idx):
        idx_to_sorted[idx - idx_min] = s
    sp_start, sp_count, sp_k, sp_nf = [], [], [], []
    for idx in sorted_idx:
        contrib = tp.same_period_contributions[idx]
        sp_start.append(len(sp_k)); sp_count.append(len(contrib))
        for k, nf in contrib:
            sp_k.append(_i(k, "sp_k")); sp_nf.append(_f(nf, "sp_nf"))
    row_idx = _ints((p.period_index for p in periods), "period_index")
    if [r[0] for r in rows] != row_idx:
        _decline("TAX_PLAN_ROW_AXIS")
    year_keys = _ints(tp.year_keys, "year_key")
    payment_idx = _ints(tp.payment_idx, "payment_idx")
    if not (len(year_keys) == len(payment_idx) == len(tp.y_ebitda) == len(tp.y_dep)):
        _decline("TAX_PLAN_YEAR_AXIS")
    g = dict(
        n_rows=len(rows), n_years=len(year_keys), n_slots=len(slot_pos), n_sp=len(sp_k), n_sorted=len(sorted_idx),
        idx_span=span, idx_min=idx_min, max_idx=_i(tp.max_idx, "max_idx"),
        sorted_set=frozenset(sorted_idx), payment_list=payment_idx,
        row_kind=_iarr(row_kind), slot_start=_iarr(slot_start), slot_count=_iarr(slot_count),
        slot_pos=_iarr(slot_pos), slot_frac=_darr(slot_frac),
        y_ebitda=_darr(_floats(tp.y_ebitda, "y_ebitda")), y_dep=_darr(_floats(tp.y_dep, "y_dep")),
        year_key=_iarr(year_keys), payment_idx=_iarr(payment_idx),
        sp_start=_iarr(sp_start), sp_count=_iarr(sp_count), sp_k=_iarr(sp_k), sp_nf=_darr(sp_nf),
        idx_to_sorted=_iarr(idx_to_sorted),
        row_sorted=_iarr([idx_to_sorted[i - idx_min] for i in row_idx]),
        ebitda=_darr(_floats((p.ebitda_keur for p in periods), "ebitda")),
        row_pos_of={idx: r for r, idx in enumerate(row_idx)}, year_list=year_keys,
    )
    if cache is not None:
        cache[id(tp)] = (tp, periods, g)
        while len(cache) > _GEOMETRY_MAX:
            cache.popitem(last=False)
    return g


def _build_plan(ctx, roll_plan, policy):
    from financial_engine.policies.tax import CashTaxTiming, TaxLossUtilisationGate
    from financial_engine.tax import loss_ledger
    tp, periods, pol = ctx["plan"], ctx["periods"], ctx["policy"]
    if not tp.rows or len(tp.rows) != len(periods):
        _decline("TAX_PLAN_ROWS")
    g = _geometry(tp, periods)
    n = g["n_rows"]
    for key in ("other", "elig", "nd", "sgross", "snd", "reint", "fin"):
        if len(ctx[key]) != n:
            _decline("NUMERIC_TAX_VECTOR_AXIS_MISMATCH")   # canonical raise site engine.py:689 / its predicate
        _floats(ctx[key], key)
    timing = 1 if pol.cash_tax_timing in (CashTaxTiming.TAX_YEAR_LAST_PERIOD, CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD) else 0
    lag = _i(pol.cash_tax_payment_lag_periods, "cash_tax_payment_lag_periods")
    lcf = _i(pol.loss_carryforward_years, "loss_carryforward_years")
    if timing:
        # canonical: cash_tax_by_period[payment_period] raises KeyError if the period does not exist
        for base in g["payment_list"]:
            pp = base + lag
            if pp <= g["max_idx"] and pp not in g["sorted_set"]:
                _decline("CASH_TAX_PAYMENT_PERIOD_MISSING")
    for y in g["year_list"]:
        if not (-_I64_LIMIT <= y + lcf <= _I64_LIMIT):
            _decline("INT_NOT_REPRESENTABLE:year_plus_carryforward")
    first = g["year_list"][0] if g["year_list"] else None
    pool = loss_ledger._opening_states_from_inputs(ctx["opening"], lcf, first_tax_year=first)
    open_last = _ints((s.last_usable_tax_year for s in pool), "open_last_usable")
    open_amount = _floats((s.amount_keur for s in pool), "open_amount")
    atad = pol.atad_enabled
    if type(atad) is not bool:
        _decline("TYPE_NOT_BOOL:atad_enabled")
    atad_limit = _f(pol.atad_ebitda_limit, "atad_ebitda_limit") if atad else 0.0
    atad_thr = _f(pol.atad_de_minimis_threshold_keur_annual, "atad_threshold") if atad else 0.0
    d_indices = _ints(roll_plan.period_indices, "debt_period_index")
    row_pos_of = g["row_pos_of"]
    row_cand = [-1] * n
    d_row = []
    for j, idx in enumerate(d_indices):
        r = row_pos_of.get(idx)
        if r is None or row_cand[r] != -1:
            _decline("DEBT_PERIOD_NOT_ON_TAX_AXIS")
        row_cand[r] = j; d_row.append(r)
    if roll_plan.repayment_method != "dscr_sculpted" or roll_plan.debt_service_scale != 1.0:
        _decline("ROLL_METHOD")
    in_rep = list(roll_plan.in_repayment)
    if any(type(x) is not bool for x in in_rep):
        _decline("TYPE_NOT_BOOL:in_repayment")
    dscr = [(_f(t, "dscr_target") if r else 0.0) for t, r in zip(roll_plan.dscr_targets or (), in_rep)]
    avail = [(_f(a, "availability") if r else 0.0) for a, r in zip(roll_plan.availabilities or (), in_rep)]
    if len(dscr) != len(d_indices) or len(avail) != len(d_indices):
        _decline("ROLL_PLAN_AXIS")
    keep = [g]
    def D(v):
        a = _darr(v); keep.append(a); return a
    def I(v):
        a = _iarr(v); keep.append(a); return a
    P = _loader.Plan(
        abi_version=_loader.ABI_VERSION, struct_size=C.sizeof(_loader.Plan),
        n_rows=n, n_years=g["n_years"], n_slots=g["n_slots"], n_sp=g["n_sp"], n_sorted=g["n_sorted"],
        n_open=len(pool), idx_span=g["idx_span"],
        row_kind=g["row_kind"], row_slot_start=g["slot_start"], row_slot_count=g["slot_count"],
        slot_pos=g["slot_pos"], slot_frac=g["slot_frac"], y_ebitda=g["y_ebitda"], y_dep=g["y_dep"],
        year_key=g["year_key"], payment_idx=g["payment_idx"],
        timing_payment=timing, lag=lag, max_idx=g["max_idx"],
        sp_start=g["sp_start"], sp_count=g["sp_count"], sp_k=g["sp_k"], sp_nf=g["sp_nf"],
        idx_min=g["idx_min"], idx_to_sorted=g["idx_to_sorted"], row_sorted=g["row_sorted"],
        atad_enabled=1 if atad else 0, atad_limit=atad_limit, atad_threshold=atad_thr,
        loss_gate=1 if pol.loss_utilisation_gate == TaxLossUtilisationGate.EBT_POSITIVE else 0,
        corporate_rate=_f(pol.corporate_rate, "corporate_rate"), lcf_years=lcf,
        open_last=I(open_last), open_amount=D(open_amount),
        row_cand=I(row_cand), row_other=D(ctx["other"]), row_elig=D(ctx["elig"]), row_nd=D(ctx["nd"]),
        row_static_gross=D(ctx["sgross"]), row_static_nd=D(ctx["snd"]), row_reint=D(ctx["reint"]),
        row_fin=D(ctx["fin"]), row_ebitda=g["ebitda"],
        n_d=len(d_indices), rates=D(_floats(roll_plan.rates, "rate")), dfs=D(_floats(roll_plan.day_fracs, "day_frac")),
        dscr=D(dscr), avail=D(avail), in_rep=I([1 if x else 0 for x in in_rep]), d_row=I(d_row),
        alpha=_f(policy.damping_alpha, "damping_alpha"), max_iter=_i(policy.maximum_iterations, "maximum_iterations"),
        abs_tol=_f(policy.convergence_tolerance_keur, "abs_tol"),
        rel_tol=_f(policy.convergence_relative_tolerance, "rel_tol"),
        max_fin_iter=_i(_modules()[2]._MAX_FINALISATION_ITERATIONS, "max_finalisation_iterations"),
    )
    return P, keep, periods


# ------------------------------------------------------------------ admission front door
def _native_or_decline():
    cfg = current_config()
    if cfg.mode != "candidate":
        _decline("MODE_OFF")
    native, reason = _loader.get_native()
    stats = current_stats()
    if native is None:
        if stats is not None:
            stats.loader_reason = reason
        _decline(f"LOADER:{reason}")
    if cfg.require_build_id is not None and native.build_id != cfg.require_build_id:
        _decline("BUILD_ID_PIN_MISMATCH")
    if not native.auth.still_intact():
        _decline("CANONICAL_REGION_REPLACED")
    if stats is not None:
        stats.build_id = native.build_id
    return native


def _common_admission(policy, inputs, period_indices, period_start_end, rate_map, dscr_map, availability_map):
    from financial_engine.senior_debt.policy import SeniorDebtPolicy
    solver = _modules()[2]
    if type(policy) is not SeniorDebtPolicy:
        _decline("SENIOR_POLICY_TYPE")
    if solver._forward_roll is not solver._AUTHENTIC_FORWARD_ROLL:
        _decline("FORWARD_ROLL_REPLACED")
    if type(period_indices) is not tuple:
        _decline("PERIOD_INDICES_TYPE")
    _ints(period_indices, "period_indices")
    if type(period_start_end) is not dict or any(
            type(v) is not tuple or len(v) != 2 or type(v[0]) is not date or type(v[1]) is not date
            for v in period_start_end.values()):
        _decline("PERIOD_DATES_TYPE")
    for m, what in ((rate_map, "rate_map"), (dscr_map, "dscr_map"), (availability_map, "availability_map")):
        if m is not None and (type(m) is not dict or any(type(k) is not int or type(v) is not float for k, v in m.items())):
            _decline(f"MAP_TYPE:{what}")
    _i(policy.repayment_start_period_index, "repayment_start"); _i(policy.maturity_period_index, "maturity")


def solve_dscr(*, policy, inputs, period_indices, period_start_end, rate_map, tax_cfads_fn,
               binding_constraint, dscr_map=None, availability_map=None):
    """Kernel-served _solve_dscr, or None (decline) - never raises."""
    try:
        native = _native_or_decline()
        solver = _modules()[2]
        _common_admission(policy, inputs, period_indices, period_start_end, rate_map, dscr_map, availability_map)
        roll_plan = solver.build_roll_plan(
            policy=policy, period_indices=period_indices, period_start_end=period_start_end, rate_map=rate_map,
            repayment_method_str="dscr_sculpted", dscr_map=dscr_map, availability_map=availability_map)
        ctx = _tax_context(tax_cfads_fn, frozenset(period_indices))
        P, keep, periods = _build_plan(ctx, roll_plan, policy)
        d0 = _f(inputs.initial_debt_guess_keur, "initial_debt_guess")
        n, nr = len(period_indices), len(periods)
    except _Decline as d:
        _record_decline(d.reason); return None
    except Exception as exc:  # noqa: BLE001 - canonical code decides (and raises) on replay
        _record_decline(f"ADMISSION_EXCEPTION:{type(exc).__name__}:{str(exc)[:120]}"); return None
    out = _loader.SolveOut()
    cf_final = (C.c_double * n)(); ncf = (C.c_double * nr)(); ntx = (C.c_double * nr)()
    status = native.lib.fk_solve_dscr(C.byref(P), d0, C.byref(out), cf_final, n, ncf, ntx, nr)
    del keep  # buffers were alive for the whole synchronous call
    if status != 0:
        _record_decline(f"KERNEL_STATUS_{status}"); return None
    stats = current_stats()
    if stats is not None:
        stats.native_solves += 1; stats.native_tax_evaluations += out.tax_evals
    new_D = out.new_D
    cf_final_dict = {idx: cf_final[i] for i, idx in enumerate(period_indices)}
    new_cfads = {p.period_index: ncf[r] for r, p in enumerate(periods)}
    # canonical tail of _solve_dscr after a successful _finalise_authoritative
    final_rows = solver._forward_roll(new_D, period_indices, rate_map, period_start_end, cf_final_dict, policy,
                                      "dscr_sculpted", dscr_map=dscr_map, availability_map=availability_map)
    if solver._dscr_sculpting_infeasibility(final_rows, new_cfads, policy, dscr_map, availability_map) is not None:
        diag = solver._make_diag(converged=False, iteration=out.iteration, initial_guess=inputs.initial_debt_guess_keur,
                                 final_d=new_D, max_abs_diff=out.max_abs_diff, binding=binding_constraint,
                                 termination_reason=solver.DSCR_SCULPTING_INFEASIBLE)
        return solver._to_schedules(final_rows, new_D, binding_constraint, diag)
    diag = solver._make_diag(converged=True, iteration=out.iteration, initial_guess=inputs.initial_debt_guess_keur,
                             final_d=new_D, max_abs_diff=out.max_abs_diff, binding=binding_constraint,
                             termination_reason="CONVERGED")
    return solver._to_schedules(final_rows, new_D, binding_constraint, diag)


def finalise(D, period_indices, rate_map, period_start_end, cfads_by, policy, repayment_str, tax_cfads_fn,
             explicit_by=None, dscr_map=None, availability_map=None, roll=None):
    """Kernel-served _finalise_authoritative, or None (decline) - never raises."""
    try:
        native = _native_or_decline()
        solver = _modules()[2]
        if roll is not None or repayment_str != "dscr_sculpted":
            _decline("FINALISE_SHAPE")
        _common_admission(policy, None, period_indices, period_start_end, rate_map, dscr_map, availability_map)
        if type(cfads_by) is not dict:
            _decline("CFADS_TYPE")
        roll_plan = solver.build_roll_plan(
            policy=policy, period_indices=period_indices, period_start_end=period_start_end, rate_map=rate_map,
            repayment_method_str=repayment_str, dscr_map=dscr_map, availability_map=availability_map)
        ctx = _tax_context(tax_cfads_fn, frozenset(period_indices))
        P, keep, periods = _build_plan(ctx, roll_plan, policy)
        cf_in = _floats((cfads_by.get(idx, 0.0) for idx in period_indices), "cfads_in")
        d = _f(D, "debt")
        n, nr = len(period_indices), len(periods)
    except _Decline as dcl:
        _record_decline(dcl.reason); return None
    except Exception as exc:  # noqa: BLE001
        _record_decline(f"ADMISSION_EXCEPTION:{type(exc).__name__}:{str(exc)[:120]}"); return None
    cf_final = (C.c_double * n)(); ncf = (C.c_double * nr)(); ntx = (C.c_double * nr)()
    evals = C.c_int64(0)
    status = native.lib.fk_finalise(C.byref(P), d, _darr(cf_in), n, cf_final, n, ncf, ntx, nr, C.byref(evals))
    del keep
    if status != 0:
        _record_decline(f"FINALISE_KERNEL_STATUS_{status}"); return None
    stats = current_stats()
    if stats is not None:
        stats.native_finalisations += 1; stats.native_tax_evaluations += evals.value
    cf_final_dict = {idx: cf_final[i] for i, idx in enumerate(period_indices)}
    rows = solver._forward_roll(D, period_indices, rate_map, period_start_end, cf_final_dict, policy, repayment_str,
                                explicit_by=explicit_by, dscr_map=dscr_map, availability_map=availability_map)
    new_cfads = {p.period_index: ncf[r] for r, p in enumerate(periods)}
    new_tax = {p.period_index: ntx[r] for r, p in enumerate(periods)}
    return rows, new_cfads, new_tax, True
