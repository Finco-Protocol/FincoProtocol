"""V11 Stage 3 candidate: native senior-debt model evaluation (Stage 3a native tax + Stage 3b).

Served only while the current Run's ``Stage3Config.mode == "candidate"`` (Run-local, default OFF), from
the explicit hook in ``financial_engine.financing.project``. ``run_senior_debt_model(...)`` returns the
canonical ``ProjectModelResult`` value or ``None`` (decline: the canonical
``orchestrator.run_senior_debt_model`` then runs unchanged and decides — and raises — itself).

Boundary (one native call per iterative block, never per iteration):
* SHL path: the whole SHL -> tax -> CFADS -> senior fixed point (every iteration's senior solve with
  its finalisation, both iteration tax evaluations, post-senior cash, SHL operating roll and the
  convergence tests) and the final senior solve run in ONE kernel call (``fk3_shl_fixed_point``).
* Plain path: the senior solve in one kernel call (``fk3_plain``).
* Both: each full ``calculate_tax`` of the final recomputation is one kernel call (``fk3_full_tax``).
Everything else (operating model, axis contracts, typed merges of the FINAL inputs, contract and
final-state validation, DSRA, the handshake / final SHL schedules, schedule assembly, fingerprint and
provenance) is executed by the canonical functions themselves, in canonical order.

Materialisation: Python result objects are built only where the canonical caller consumes them. The
final senior schedule is rolled by the canonical ``_forward_roll`` / ``_to_schedules`` from the
native debt size and CFADS (as V10 Stage 1); full tax results become (a) real ``TaxAnnualResult``
objects with the canonical ``run_annual_fifo_ledger`` entries where the result stores them and (b)
lightweight period rows read by the canonical assembly helpers.

Exactness obligations (each enforced, else decline BEFORE any effect):
1. verified artifact (SHA256, build ID, ABI, layouts, sum canaries) and authenticated canonical region
   (approved git blobs, code fingerprints, live identities; re-checked per call);
2. exact types for every value crossing the ABI; ints representable;
3. the admitted configuration (no dynamic interest limitation, no maturity context, no bank tax
   periodisation override, payment-period cash timing, non-pairing tax basis, DSCR_SCULPTED or
   COMBINED_MINIMUM sizing, SHL BULLET/CASH_SWEEP on the period-axis day count, no deductible
   overrides);
4. every canonical raise predicate on the success path is evaluated natively; any hit declines;
5. the only state the canonical evaluation mutates (Run-scope memo caches) is reproduced by calling
   the same memoised canonical functions; there is no other side effect on the admitted path
   (no maturity ledger), so a decline at any point leaves nothing behind.
"""
from __future__ import annotations

import collections
import ctypes as C
import hashlib
import json
import math
import threading
from pathlib import Path
from typing import NamedTuple

from .config import current_config, current_stats

HERE = Path(__file__).resolve().parent
ABI = 30001
MANIFEST = "fk_v11_stage3_manifest.json"
APPROVED = HERE / "approved_canonical_blobs_stage3.json"
I64 = C.c_int64
DBL = C.c_double
D_P = C.POINTER(C.c_double)
I_P = C.POINTER(C.c_int64)
_I53 = 2 ** 53
_GEOM_KEY = "native_v11_stage3_geometry_v1"
_SHL_KEY = "native_v11_stage3_shl_template_v1"
_CACHE_MAX = 64

# ----------------------------------------------------------------------------------- ABI layouts


class TaxGeom(C.Structure):
    _fields_ = [("n_rows", I64), ("n_years", I64), ("n_slots", I64), ("n_sorted", I64), ("idx_span", I64),
                ("idx_min", I64), ("max_idx", I64),
                ("row_kind", I_P), ("row_slot_start", I_P), ("row_slot_count", I_P), ("slot_pos", I_P),
                ("slot_frac", D_P), ("y_ebitda", D_P), ("y_dep", D_P),
                ("year_key", I_P), ("payment_idx", I_P), ("idx_to_sorted", I_P), ("row_sorted", I_P),
                ("row_period", I_P), ("row_ebitda", D_P)]


class TaxPol(C.Structure):
    _fields_ = [("atad_enabled", I64), ("atad_limit", DBL), ("atad_threshold", DBL), ("loss_gate", I64),
                ("corporate_rate", DBL), ("lcf_years", I64), ("lag", I64), ("n_open", I64),
                ("open_last", I_P), ("open_amount", D_P)]


class IntCtx(C.Structure):
    _fields_ = [("e_has", I_P), ("e_senior", D_P), ("e_shl", D_P), ("e_other", D_P), ("reint", D_P),
                ("fin", D_P), ("shl_frac", DBL)]


class DebtGeom(C.Structure):
    _fields_ = [("n_d", I64), ("rates", D_P), ("dfs", D_P), ("dscr", D_P), ("avail", D_P), ("in_rep", I_P),
                ("d_row", I_P), ("row_cand", I_P), ("alpha", DBL), ("abs_tol", DBL), ("rel_tol", DBL),
                ("d0", DBL), ("gearing_cap", DBL), ("max_iter", I64), ("max_fin_iter", I64), ("mode", I64),
                ("permit_balloon", I64)]


class ShlGeom(C.Structure):
    _fields_ = [("n", I64), ("n_con", I64), ("period_index", I_P), ("is_con", I_P), ("dcf", D_P),
                ("t_gross", D_P), ("t_close", D_P), ("opening0", DBL), ("rate", DBL), ("conv_tol", DBL),
                ("mode", I64), ("repayment_start", I64), ("maturity_index", I64)]


class Stage3Plan(C.Structure):
    _fields_ = [("abi_version", I64), ("struct_size", I64), ("bank", TaxGeom), ("base", TaxGeom),
                ("pol", TaxPol), ("bank_ctx", IntCtx), ("base_ctx", IntCtx), ("debt", DebtGeom),
                ("shl", ShlGeom), ("shl_max_iter", I64), ("shl_abs_tol", DBL), ("shl_rel_tol", DBL),
                ("use_shl", I64)]


class SolveRes(C.Structure):
    _fields_ = [("debt", DBL), ("dscr_capacity", DBL), ("max_abs_diff", DBL), ("iteration", I64),
                ("binding", I64), ("tax_evals", I64)]


class Stage3Out(C.Structure):
    _fields_ = [("abi_version", I64), ("status_detail", I64), ("shl_iterations", I64),
                ("last_closing_delta", DBL), ("last_interest_delta", DBL), ("solve", SolveRes),
                ("loop_solves", I64), ("loop_tax_evals", I64)]


class FullTaxPlan(C.Structure):
    _fields_ = [("abi_version", I64), ("struct_size", I64), ("geom", TaxGeom), ("pol", TaxPol),
                ("gross", D_P), ("nd", D_P), ("elig", D_P), ("reint", D_P), ("fin", D_P)]


_YEAR_D = ("y_interest", "y_reint", "y_fin", "capacity", "deductible", "disallowed", "ti_before", "ti_after",
           "liability")
_SLOT_D = ("s_interest", "s_ded", "s_dis", "s_norm", "s_ebitda", "s_reint", "s_elig", "s_nd", "s_fin")
_ROW_D = ("r_ded", "r_dis", "r_ti_share", "r_cit", "r_elig", "r_nd", "r_cash", "r_cfads", "r_ti_after_share")


_RULES = ("disabled", "none", "ebitda_30pct", "min_threshold")
_BINDING = {1: "DSCR", 2: "BOTH", 3: "GEARING"}

# ------------------------------------------------------------------------- canonical region

# Every canonical function whose semantics the kernel or this module reproduces (instead of calling it)
# is authenticated: approved git blob of its module, code fingerprint against that approved source, and
# live identity re-checked before every admission. Functions this module CALLS are reached through the
# same live module globals as the canonical code, so a replacement affects both paths identically; they
# are covered by the blob of their module where it is listed.
STAGE3_REGION_FUNCTIONS = {
    "financial_engine.orchestrator": (
        "run_senior_debt_model", "_run_senior_debt_model_with_shl", "_make_solver_tax_cfads_fn",
        "_merge_financing_tax_input", "_assemble_post_senior_cash_schedules", "_strict_period_map",
        "_build_dynamic_interest_limitation_state", "_dynamic_interest_limitation_delta",
        "_field_converged_local", "_max_vector_delta", "_IterationCfads.__init__"),
    "financial_engine.tax.engine": (
        "calculate_tax", "calculate_cfads_and_cash_tax", "_cfads_and_cash_tax_via_full_tax", "_build_interest_map",
        "_build_adj_map", "_build_financing_income_map", "_fragments_by_period", "_build_tax_plan", "_tax_plan_for",
        "_prepare_numeric_tax_vectors", "_evaluate_numeric_tax_vectors", "_evaluate_numeric_tax_vectors_uncached",
        "_numeric_tax_static_token", "_pack_numeric_tax_vector", "_payment_period_for_year_lean",
        "SolverTaxPlan.__init__", "SolverTaxPlan.evaluate", "SolverTaxPlan.supports", "build_solver_tax_plan"),
    "financial_engine.tax.tax_year": (
        "build_tax_year_bases", "_split_period", "_payment_period_for_year", "_resolve_shl_tax_eligible_interest"),
    "financial_engine.tax.atad": ("calculate_annual_atad", "allocate_atad_to_periods"),
    "financial_engine.tax.loss_ledger": (
        "run_annual_fifo_ledger", "taxable_income_after_lcf_series", "_opening_states_from_inputs",
        "_make_vintage_record"),
    "financial_engine.tax.models": (),
    "financial_engine.cfads": ("calculate_canonical_cfads", "calculate_canonical_cfads_value"),
    "financial_engine.policies.tax": ("TaxPolicy.shl_tax_deductible_fraction",),
    "financial_engine.senior_debt.solver": (
        "solve_senior_debt", "_solve_dscr", "_solve_combined", "_finalise_authoritative", "_forward_roll",
        "_forward_roll_numeric", "_backward_dscr_capacity", "_schedules_converged", "_field_converged",
        "_compute_max_abs_diff", "_dscr_sculpting_infeasibility", "_make_diag", "_to_schedules", "_zero_rows",
        "build_roll_plan", "build_dscr_target_map", "build_debt_service_availability_map",
        "_native_v10_candidate"),
    "financial_engine.senior_debt.interest": ("period_day_fraction",),
    "financial_engine.shl.production": (
        "compute_shareholder_loan_schedules", "_ShlOperatingChain.__init__", "_ShlOperatingChain.evaluate",
        "_ShlOperatingChain.advance", "_new_operating_chain", "_check_finite", "_validate_shareholder_loan_input",
        "_shl_operating_accrual_start", "compute_shl_schedule", "_native_v10_stage2"),
    "financial_engine.shl.waterfall": ("compute_shl_waterfall_period", "_check_finite"),
    "financial_engine.shl.engine": ("compute_shl_period",),
    "financial_engine.run_scope": ("current_run_scope",),
    "financial_engine.financing.project": ("_senior_debt_model", "_native_v11_stage3"),
    "finco_core.engine.period_engine": ("map_period_vector",),
}
STAGE3_REGION_ATTRIBUTES = {
    "financial_engine.orchestrator": ("_IterationCfads", "map_period_vector", "_DynamicInterestLimitationState"),
    "financial_engine.tax.engine": (
        "calculate_canonical_cfads", "calculate_canonical_cfads_value", "taxable_income_after_lcf_series",
        "run_annual_fifo_ledger", "calculate_annual_atad", "allocate_atad_to_periods", "build_tax_year_bases",
        "_period_geometry", "_resolve_shl_tax_eligible_interest", "_AUTHENTIC_CALCULATE_CFADS_AND_CASH_TAX",
        "_current_run_scope", "SolverTaxPlan", "_TaxPlan", "TaxAnnualResult", "TaxAndCfadsResult",
        "PeriodCashTaxResult", "PeriodTaxYearAllocation"),
    "financial_engine.senior_debt.solver": ("_AUTHENTIC_FORWARD_ROLL", "period_day_fraction", "PeriodDebtRow",
                                            "SeniorDebtSchedules", "SolverDiagnostics"),
    "financial_engine.tax.loss_ledger": ("_VintageState",),
    "financial_engine.shl.production": ("compute_shl_waterfall_period", "compute_shl_period", "_ShlOperatingChain"),
}
STAGE3_ALIASES = (
    ("financial_engine.tax.engine", "calculate_canonical_cfads_value", "financial_engine.cfads", "calculate_canonical_cfads_value"),
    ("financial_engine.tax.engine", "calculate_canonical_cfads", "financial_engine.cfads", "calculate_canonical_cfads"),
    ("financial_engine.tax.engine", "taxable_income_after_lcf_series", "financial_engine.tax.loss_ledger", "taxable_income_after_lcf_series"),
    ("financial_engine.tax.engine", "run_annual_fifo_ledger", "financial_engine.tax.loss_ledger", "run_annual_fifo_ledger"),
    ("financial_engine.tax.engine", "calculate_annual_atad", "financial_engine.tax.atad", "calculate_annual_atad"),
    ("financial_engine.tax.engine", "allocate_atad_to_periods", "financial_engine.tax.atad", "allocate_atad_to_periods"),
    ("financial_engine.tax.engine", "build_tax_year_bases", "financial_engine.tax.tax_year", "build_tax_year_bases"),
    ("financial_engine.tax.engine", "_resolve_shl_tax_eligible_interest", "financial_engine.tax.tax_year", "_resolve_shl_tax_eligible_interest"),
    ("financial_engine.tax.engine", "_current_run_scope", "financial_engine.run_scope", "current_run_scope"),
    ("financial_engine.tax.engine", "_AUTHENTIC_CALCULATE_CFADS_AND_CASH_TAX", "financial_engine.tax.engine", "calculate_cfads_and_cash_tax"),
    ("financial_engine.senior_debt.solver", "_AUTHENTIC_FORWARD_ROLL", "financial_engine.senior_debt.solver", "_forward_roll"),
    ("financial_engine.senior_debt.solver", "period_day_fraction", "financial_engine.senior_debt.interest", "period_day_fraction"),
    ("financial_engine.shl.production", "compute_shl_waterfall_period", "financial_engine.shl.waterfall", "compute_shl_waterfall_period"),
    ("financial_engine.shl.production", "compute_shl_period", "financial_engine.shl.engine", "compute_shl_period"),
    ("financial_engine.orchestrator", "map_period_vector", "finco_core.engine.period_engine", "map_period_vector"),
)
STAGE3_EXTRA_SOURCES = (
    "financial_engine/native_v11/kernel_v11_stage3.c", "financial_engine/native_v11/config.py",
    "financial_engine/native_v11/stage3.py", "financial_engine/native_v10/eligibility.py",
    "financial_engine/native_v10/provenance.py",
)

# ------------------------------------------------------------------------------- loader


class _Decline(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _decline(reason: str):
    raise _Decline(reason)


class Stage3Library:
    __slots__ = ("lib", "manifest", "build_id", "auth")

    def __init__(self, lib, manifest, auth):
        self.lib, self.manifest, self.build_id, self.auth = lib, manifest, manifest["build_id"], auth


_LOCK = threading.Lock()
_RESULT: dict = {}


def _verify(directory: Path, manifest_name: str):
    from financial_engine.native_v10 import eligibility, provenance
    reason = eligibility.check_runtime()
    if reason:
        return None, reason
    try:
        manifest = json.loads((directory / manifest_name).read_text(encoding="utf-8"))
        blob = (directory / manifest["artifact"]).read_bytes()
    except (OSError, ValueError, KeyError) as exc:
        return None, f"LOADER3_ARTIFACT_UNAVAILABLE:{type(exc).__name__}"
    if manifest.get("abi_version") != ABI:
        return None, "LOADER3_ABI_VERSION_MANIFEST"
    if hashlib.sha256(blob).hexdigest() != manifest.get("artifact_sha256"):
        return None, "LOADER3_ARTIFACT_SHA256_MISMATCH"
    try:
        approved = (directory / APPROVED.name).read_bytes()
    except OSError as exc:
        return None, f"LOADER3_APPROVED_MANIFEST_UNAVAILABLE:{type(exc).__name__}"
    if hashlib.sha256(approved).hexdigest() != manifest.get("approved_blobs_sha256"):
        return None, "LOADER3_APPROVED_MANIFEST_NOT_SEALED"
    try:
        lib = C.CDLL(str(directory / manifest["artifact"]))
        lib.fk3_abi_version.restype = C.c_int
        lib.fk3_build_id.restype = C.c_char_p
        for name in ("fk3_plan_size", "fk3_geom_size", "fk3_out_size", "fk3_full_tax_plan_size"):
            getattr(lib, name).restype = I64
        lib.fk3_py_sum.argtypes = [D_P, I64]
        lib.fk3_py_sum.restype = DBL
        lib.fk3_plain.argtypes = [C.POINTER(Stage3Plan), C.POINTER(Stage3Out), D_P, D_P, D_P, D_P, I64]
        lib.fk3_plain.restype = C.c_int
        lib.fk3_shl_fixed_point.argtypes = [C.POINTER(Stage3Plan), C.POINTER(Stage3Out), D_P, D_P, I64,
                                            D_P, D_P, D_P, D_P, I64]
        lib.fk3_shl_fixed_point.restype = C.c_int
        lib.fk3_full_tax.argtypes = [C.POINTER(FullTaxPlan), D_P, I64, I_P, I64]
        lib.fk3_full_tax.restype = C.c_int
    except (OSError, AttributeError) as exc:
        return None, f"LOADER3_DLOPEN:{type(exc).__name__}"
    if lib.fk3_abi_version() != ABI:
        return None, "LOADER3_ABI_VERSION_BINARY"
    sizes = ((lib.fk3_plan_size(), Stage3Plan), (lib.fk3_geom_size(), TaxGeom), (lib.fk3_out_size(), Stage3Out),
             (lib.fk3_full_tax_plan_size(), FullTaxPlan))
    if any(n != C.sizeof(t) for n, t in sizes):
        return None, "LOADER3_LAYOUT"
    if lib.fk3_build_id().decode() != manifest.get("build_id"):
        return None, "LOADER3_BUILD_ID"
    for canary in eligibility.SUM_CANARIES:
        a = (C.c_double * len(canary))(*canary)
        if lib.fk3_py_sum(a, len(canary)).hex() != float(sum(canary)).hex():
            return None, "LOADER3_SUM_SEMANTICS"
    auth, reason = provenance.authenticate(directory / APPROVED.name, functions=STAGE3_REGION_FUNCTIONS,
                                           attributes=STAGE3_REGION_ATTRIBUTES, aliases=STAGE3_ALIASES,
                                           extra_sources=STAGE3_EXTRA_SOURCES)
    if auth is None:
        return None, f"STAGE3_{reason}"
    return Stage3Library(lib, manifest, auth), None


def get_stage3(directory: Path | None = None, manifest_name: str = MANIFEST):
    """(Stage3Library, None) or (None, reason). Never compiles; never raises; cached per process."""
    key = (str(directory or HERE), manifest_name)
    with _LOCK:
        if key not in _RESULT:
            try:
                _RESULT[key] = _verify(Path(key[0]), manifest_name)
            except Exception as exc:  # noqa: BLE001 - verification failure always means canonical
                _RESULT[key] = (None, f"LOADER3_UNEXPECTED:{type(exc).__name__}")
        return _RESULT[key]


def _reset_for_tests() -> None:
    with _LOCK:
        _RESULT.clear()


# ------------------------------------------------------------------------- exact-type helpers

def _f(x, what):
    if type(x) is not float:
        _decline(f"TYPE_NOT_FLOAT:{what}")
    return x


def _i(x, what):
    if type(x) is not int or not -_I53 <= x <= _I53:
        _decline(f"INT_NOT_REPRESENTABLE:{what}")
    return x


def _b(x, what):
    if type(x) is not bool:
        _decline(f"TYPE_NOT_BOOL:{what}")
    return x


def _darr(values):
    values = list(values)
    return (C.c_double * max(1, len(values)))(*values)


def _iarr(values):
    values = list(values)
    return (C.c_int64 * max(1, len(values)))(*values)


def _dvec(buf, n):
    """Exact binary64 values of a ctypes double buffer as a Python list."""
    return memoryview(buf).cast("B").cast("d").tolist()[:n]


def _modules():
    import financial_engine.orchestrator as orch
    import financial_engine.senior_debt.solver as solver
    import financial_engine.tax.engine as tax
    import financial_engine.tax.loss_ledger as loss_ledger
    from financial_engine import run_scope
    return orch, tax, solver, loss_ledger, run_scope


# ------------------------------------------------------------------------------- tax geometry

class _Geometry:
    """Static per-axis kernel geometry derived from the canonical ``_TaxPlan`` (Run-scope cached)."""

    __slots__ = ("struct", "keep", "plan", "periods", "row_idx", "year_keys", "year_periods", "slot_year",
                 "slot_row", "n_rows", "n_years", "n_slots", "sorted_set", "payment_list", "max_idx",
                 "row_pos", "is_con", "slots_by_year", "ebitda")


def _geometry(periods) -> _Geometry:
    orch, tax, _solver, _ll, run_scope = _modules()
    from financial_engine.results import OperatingPeriodResult
    if type(periods) is not tuple or not periods or any(type(p) is not OperatingPeriodResult for p in periods):
        _decline("PERIODS_TYPE")
    plan = tax._tax_plan_for(periods)
    if plan.fallback:
        _decline("TAX_PLAN_FALLBACK")
    scope = run_scope.current_run_scope()
    cache = None
    if scope is not None:
        cache = scope.get(_GEOM_KEY)
        if cache is None:
            cache = scope[_GEOM_KEY] = collections.OrderedDict()
        hit = cache.get(id(plan))
        if hit is not None and hit[0] is plan and hit[1] is periods:
            cache.move_to_end(id(plan))
            return hit[2]
    g = _build_geometry(plan, periods)
    if cache is not None:
        cache[id(plan)] = (plan, periods, g)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)
    return g


def _build_geometry(plan, periods) -> _Geometry:
    rows = plan.rows
    row_idx = [_i(p.period_index, "period_index") for p in periods]
    if [r[0] for r in rows] != row_idx or len(set(row_idx)) != len(row_idx):
        _decline("TAX_PLAN_ROW_AXIS")
    row_kind, slot_start, slot_count, slot_pos, slot_frac, slot_row = [], [], [], [], [], []
    for r, (_idx, kind, slots) in enumerate(rows):
        row_kind.append(_i(kind, "row_kind")); slot_start.append(len(slot_pos)); slot_count.append(len(slots))
        for pos, frac in slots:
            slot_pos.append(_i(pos, "slot_pos")); slot_frac.append(_f(frac, "slot_frac")); slot_row.append(r)
    year_keys = [_i(y, "year_key") for y in plan.year_keys]
    payment = [_i(x, "payment_idx") for x in plan.payment_idx]
    y_e = [_f(x, "y_ebitda") for x in plan.y_ebitda]
    y_d = [_f(x, "y_dep") for x in plan.y_dep]
    if not (len(year_keys) == len(payment) == len(y_e) == len(y_d)) or not year_keys:
        _decline("TAX_PLAN_YEAR_AXIS")
    sorted_idx = [_i(x, "sorted_idx") for x in plan.sorted_idx]
    if sorted_idx != sorted(row_idx):
        _decline("TAX_PLAN_SORTED_AXIS")
    idx_min = sorted_idx[0]
    span = sorted_idx[-1] - idx_min + 1
    if span > 1_000_000:
        _decline("PERIOD_INDEX_SPAN")
    idx_to_sorted = [-1] * span
    for s, idx in enumerate(sorted_idx):
        idx_to_sorted[idx - idx_min] = s
    ebitda = [_f(p.ebitda_keur, "ebitda") for p in periods]
    for p in periods:
        _f(p.tax_depreciation_keur, "tax_depreciation")
    g = _Geometry()
    g.keep = keep = dict(
        row_kind=_iarr(row_kind), slot_start=_iarr(slot_start), slot_count=_iarr(slot_count),
        slot_pos=_iarr(slot_pos), slot_frac=_darr(slot_frac), y_ebitda=_darr(y_e), y_dep=_darr(y_d),
        year_key=_iarr(year_keys), payment_idx=_iarr(payment), idx_to_sorted=_iarr(idx_to_sorted),
        row_sorted=_iarr([idx_to_sorted[i - idx_min] for i in row_idx]), row_period=_iarr(row_idx),
        row_ebitda=_darr(ebitda))
    g.struct = TaxGeom(
        n_rows=len(rows), n_years=len(year_keys), n_slots=len(slot_pos), n_sorted=len(sorted_idx), idx_span=span,
        idx_min=idx_min, max_idx=_i(plan.max_idx, "max_idx"),
        row_kind=keep["row_kind"], row_slot_start=keep["slot_start"], row_slot_count=keep["slot_count"],
        slot_pos=keep["slot_pos"], slot_frac=keep["slot_frac"], y_ebitda=keep["y_ebitda"], y_dep=keep["y_dep"],
        year_key=keep["year_key"], payment_idx=keep["payment_idx"], idx_to_sorted=keep["idx_to_sorted"],
        row_sorted=keep["row_sorted"], row_period=keep["row_period"], row_ebitda=keep["row_ebitda"])
    g.plan, g.periods = plan, periods
    g.row_idx = tuple(row_idx)
    g.year_keys = tuple(year_keys)
    by_year = [[] for _ in year_keys]
    for s, (pos, r) in enumerate(zip(slot_pos, slot_row)):
        by_year[pos].append(s)
    g.year_periods = tuple(tuple(row_idx[slot_row[s]] for s in slots) for slots in by_year)
    g.slot_year = tuple(slot_pos)
    g.slot_row = tuple(slot_row)
    g.n_rows, g.n_years, g.n_slots = len(rows), len(year_keys), len(slot_pos)
    g.sorted_set = frozenset(sorted_idx)
    g.payment_list = tuple(payment)
    g.max_idx = plan.max_idx
    g.row_pos = {idx: r for r, idx in enumerate(row_idx)}
    g.is_con = tuple(_b(p.is_construction, "is_construction") for p in periods)
    for p in periods:
        _b(p.is_operation, "is_operation")
    g.ebitda = tuple(ebitda)
    g.slots_by_year = tuple(tuple(slots) for slots in by_year)
    return g


def _tax_policy(policy, opening, g: _Geometry):
    """TaxPol for one (policy, opening vintages) on axis ``g``; admission of the policy space."""
    _orch, _tax, _solver, loss_ledger, _rs = _modules()
    from financial_engine.policies.tax import CashTaxTiming, TaxBasisPeriodisation, TaxLossUtilisationGate, TaxPolicy
    if type(policy) is not TaxPolicy:
        _decline("TAX_POLICY_TYPE")
    if policy.tax_basis_periodisation == TaxBasisPeriodisation.MODEL_YEAR_PAIRING:
        _decline("TAX_PATH_MODEL_YEAR_PAIRING")
    if policy.cash_tax_timing not in (CashTaxTiming.TAX_YEAR_LAST_PERIOD, CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD):
        _decline("CASH_TAX_TIMING")
    lag = _i(policy.cash_tax_payment_lag_periods, "cash_tax_payment_lag_periods")
    lcf = _i(policy.loss_carryforward_years, "loss_carryforward_years")
    for base in g.payment_list:
        pp = base + lag
        if pp <= g.max_idx and pp not in g.sorted_set:
            _decline("CASH_TAX_PAYMENT_PERIOD_MISSING")     # canonical KeyError
    for y in g.year_keys:
        if not -_I53 <= y + lcf <= _I53:
            _decline("INT_NOT_REPRESENTABLE:year_plus_carryforward")
    pool = loss_ledger._opening_states_from_inputs(opening, lcf, first_tax_year=g.year_keys[0])
    open_last = [_i(s.last_usable_tax_year, "open_last_usable") for s in pool]
    open_amount = [_f(s.amount_keur, "open_amount") for s in pool]
    atad = _b(policy.atad_enabled, "atad_enabled")
    keep = (_iarr(open_last), _darr(open_amount))
    pol = TaxPol(
        atad_enabled=1 if atad else 0,
        atad_limit=_f(policy.atad_ebitda_limit, "atad_ebitda_limit") if atad else 0.0,
        atad_threshold=_f(policy.atad_de_minimis_threshold_keur_annual, "atad_threshold") if atad else 0.0,
        loss_gate=1 if policy.loss_utilisation_gate == TaxLossUtilisationGate.EBT_POSITIVE else 0,
        corporate_rate=_f(policy.corporate_rate, "corporate_rate"), lcf_years=lcf, lag=lag, n_open=len(pool),
        open_last=keep[0], open_amount=keep[1])
    return pol, keep


def _merge_source(base_tax_input, g: _Geometry, policy):
    """IntCtx of the merge source (base TaxCalculationInput) on axis ``g`` (static per evaluation)."""
    _orch, tax, *_ = _modules()
    existing = {pi.period_index: pi for pi in base_tax_input.period_interest}
    adj = tax._build_adj_map(base_tax_input.period_adjustments)
    fin = tax._build_financing_income_map(base_tax_input)
    for idx, pi in existing.items():
        _i(idx, "interest_period_index")
        if pi.shl_deductible_interest_keur is not None:
            _decline("SHL_DEDUCTIBLE_OVERRIDE")
        _f(pi.senior_interest_keur, "senior_interest"); _f(pi.shl_interest_keur, "shl_interest")
        _f(pi.other_interest_keur, "other_interest")
    e_has, e_sen, e_shl, e_oth, reint, fi = [], [], [], [], [], []
    for idx in g.row_idx:
        pi = existing.get(idx)
        if pi is not None:
            e_has.append(1); e_sen.append(pi.senior_interest_keur); e_shl.append(pi.shl_interest_keur)
            e_oth.append(pi.other_interest_keur)
        else:
            e_has.append(0); e_sen.append(0.0); e_shl.append(0.0); e_oth.append(0.0)
        reint.append(_f(adj.get(idx, 0.0), "reintegration"))
        fi.append(_f(fin.get(idx, 0.0), "financing_income"))
    frac = _f(policy.shl_tax_deductible_fraction(), "shl_tax_deductible_fraction")
    keep = (_iarr(e_has), _darr(e_sen), _darr(e_shl), _darr(e_oth), _darr(reint), _darr(fi))
    return IntCtx(*keep, frac), keep


# ------------------------------------------------------------------------------- debt geometry

class _Debt:
    __slots__ = ("struct", "keep", "period_indices", "period_start_end", "rate_map", "dscr_map", "availability_map",
                 "gearing_cap", "combined")


def _debt_geometry(policy, sd_inputs, debt_periods, g_bank: _Geometry) -> _Debt:
    _orch, _tax, solver, *_ = _modules()
    from financial_engine.senior_debt.inputs import SeniorDebtInputs
    from financial_engine.senior_debt.policy import SeniorDebtPolicy, SeniorDebtSizingMode
    from financial_engine.senior_debt.validation import validate_senior_debt_inputs
    if type(policy) is not SeniorDebtPolicy or type(sd_inputs) is not SeniorDebtInputs:
        _decline("SENIOR_INPUT_TYPES")
    if solver._forward_roll is not solver._AUTHENTIC_FORWARD_ROLL:
        _decline("FORWARD_ROLL_REPLACED")
    op_periods = tuple(p for p in debt_periods if p.is_operation)
    period_indices = tuple(p.period_index for p in op_periods)
    if not period_indices:
        _decline("NO_DEBT_PERIODS")
    period_start_end = {p.period_index: (p.period_start, p.period_end) for p in op_periods}
    if validate_senior_debt_inputs(sd_inputs, policy, frozenset(period_indices)):
        _decline("SENIOR_INVALID_INPUT")                   # INVALID_INPUT -> non-authoritative
    rate_map = solver.build_rate_map(sd_inputs.period_rates, period_indices, policy.annual_fixed_rate)
    dscr_map = solver.build_dscr_target_map(policy, sd_inputs, period_indices)
    availability_map = solver.build_debt_service_availability_map(sd_inputs, period_indices)
    mode = policy.sizing_mode
    if mode == SeniorDebtSizingMode.DSCR_SCULPTED:
        combined, gearing = False, 0.0
    elif mode == SeniorDebtSizingMode.COMBINED_MINIMUM:
        if policy.maximum_gearing is None:
            _decline("COMBINED_WITHOUT_GEARING")
        combined = True
        gearing = _f(_f(sd_inputs.eligible_project_cost_keur, "eligible_cost") * _f(policy.maximum_gearing, "gearing"),
                     "gearing_cap")
    else:
        _decline("SIZING_MODE")
    rp = solver.build_roll_plan(policy=policy, period_indices=period_indices, period_start_end=period_start_end,
                                rate_map=rate_map, repayment_method_str="dscr_sculpted", dscr_map=dscr_map,
                                availability_map=availability_map)
    if rp.debt_service_scale != 1.0 or rp.repayment_method != "dscr_sculpted":
        _decline("ROLL_PLAN_SHAPE")
    in_rep = [_b(x, "in_repayment") for x in rp.in_repayment]
    rates = [_f(x, "rate") for x in rp.rates]
    dfs = [_f(x, "day_fraction") for x in rp.day_fracs]
    dscr = [(_f(t, "dscr_target") if r else 0.0) for t, r in zip(rp.dscr_targets, in_rep)]
    avail = [(_f(a, "availability") if r else 0.0) for a, r in zip(rp.availabilities, in_rep)]
    if not (len(rates) == len(dfs) == len(in_rep) == len(dscr) == len(avail) == len(period_indices)):
        _decline("ROLL_PLAN_AXIS")
    row_cand = [-1] * g_bank.n_rows
    d_row = []
    for j, idx in enumerate(period_indices):
        r = g_bank.row_pos.get(idx)
        if r is None or row_cand[r] != -1:
            _decline("DEBT_PERIOD_NOT_ON_TAX_AXIS")
        row_cand[r] = j; d_row.append(r)
    _b(policy.permit_terminal_balloon, "permit_terminal_balloon")
    d = _Debt()
    d.keep = keep = dict(rates=_darr(rates), dfs=_darr(dfs), dscr=_darr(dscr), avail=_darr(avail),
                         in_rep=_iarr(1 if x else 0 for x in in_rep), d_row=_iarr(d_row), row_cand=_iarr(row_cand))
    d.struct = DebtGeom(
        n_d=len(period_indices), rates=keep["rates"], dfs=keep["dfs"], dscr=keep["dscr"], avail=keep["avail"],
        in_rep=keep["in_rep"], d_row=keep["d_row"], row_cand=keep["row_cand"],
        alpha=_f(policy.damping_alpha, "damping_alpha"), abs_tol=_f(policy.convergence_tolerance_keur, "abs_tol"),
        rel_tol=_f(policy.convergence_relative_tolerance, "rel_tol"), d0=_f(sd_inputs.initial_debt_guess_keur, "d0"),
        gearing_cap=gearing, max_iter=_i(policy.maximum_iterations, "maximum_iterations"),
        max_fin_iter=_i(solver._MAX_FINALISATION_ITERATIONS, "max_finalisation_iterations"),
        mode=2 if combined else 1, permit_balloon=1 if policy.permit_terminal_balloon else 0)
    d.period_indices, d.period_start_end = period_indices, period_start_end
    d.rate_map, d.dscr_map, d.availability_map = rate_map, dscr_map, availability_map
    d.gearing_cap, d.combined = gearing, combined
    return d


def _materialise_senior(debt: _Debt, policy, sd_inputs, res: SolveRes, cf_final, fcf):
    """Canonical SeniorDebtSchedules of the authoritative native solve (canonical roll / diag / schedules)."""
    _orch, _tax, solver, *_ = _modules()
    n = len(debt.period_indices)
    cf_dict = dict(zip(debt.period_indices, _dvec(cf_final, n)))
    f_dict = dict(zip(debt.period_indices, _dvec(fcf, n)))
    final_d = res.debt
    rows = solver._forward_roll(final_d, debt.period_indices, debt.rate_map, debt.period_start_end, cf_dict, policy,
                                "dscr_sculpted", dscr_map=debt.dscr_map, availability_map=debt.availability_map)
    if solver._dscr_sculpting_infeasibility(rows, f_dict, policy, debt.dscr_map, debt.availability_map) is not None:
        _decline("FEASIBILITY_REPLAY")
    if not debt.combined:
        diag = solver._make_diag(converged=True, iteration=res.iteration, initial_guess=sd_inputs.initial_debt_guess_keur,
                                 final_d=final_d, max_abs_diff=res.max_abs_diff, binding="DSCR",
                                 termination_reason="CONVERGED")
        return solver._to_schedules(rows, final_d, "DSCR", diag)
    binding = _BINDING[res.binding]
    diag = solver._make_diag(converged=True, iteration=res.iteration, initial_guess=sd_inputs.initial_debt_guess_keur,
                             final_d=final_d, max_abs_diff=res.max_abs_diff, binding=binding,
                             termination_reason="CONVERGED", dscr_capacity=res.dscr_capacity,
                             gearing_capacity=debt.gearing_cap)
    return solver._to_schedules(rows, final_d, binding, diag)


# ------------------------------------------------------------------------------- SHL geometry

def _shl_static_admission(periods, shl_input):
    from financial_engine.inputs import ShareholderLoanModelInput
    from financial_engine.shl.contracts import ShlRepaymentMode
    from financial_engine.shl.day_count import ShlDayCountConvention
    if type(shl_input) is not ShareholderLoanModelInput:
        _decline("SHL_INPUT_TYPE")
    if shl_input.day_count_convention is not ShlDayCountConvention.PERIOD_AXIS_ACTUAL_YEAR:
        _decline("SHL_DAY_COUNT_CONVENTION")
    if type(shl_input.repayment_mode) is not ShlRepaymentMode:
        _decline("SHL_REPAYMENT_MODE")
    mode = {ShlRepaymentMode.BULLET: 1, ShlRepaymentMode.CASH_SWEEP: 2}.get(shl_input.repayment_mode)
    if mode is None:
        _decline("SHL_REPAYMENT_MODE")
    seen_operating = False
    for p in periods:
        if p.is_construction is True:
            if seen_operating:
                _decline("SHL_CONSTRUCTION_NOT_PREFIX")
        elif p.is_construction is False:
            seen_operating = True
            _f(p.day_fraction, "day_fraction")
        else:
            _decline("IS_CONSTRUCTION_TYPE")
    _i(shl_input.repayment_start_period_index, "shl_repayment_start")
    _i(shl_input.maturity_period_index, "shl_maturity")
    _f(shl_input.annual_fixed_rate, "shl_rate")
    _f(shl_input.convergence_tolerance_keur, "shl_tol")
    _f(shl_input.convergence_relative_tolerance, "shl_rel_tol")
    _i(shl_input.maximum_iterations, "shl_max_iterations")
    return mode


def _shl_template(periods, shl_input):
    """Cash-independent canonical SHL evaluation (zero cash, no residual check) -> construction rows and the
    operating chain opening, cached in the Run scope by identity (frozen dataclass values). Any exception of
    the canonical function declines (the canonical replay raises it)."""
    from financial_engine import run_scope
    from financial_engine.results import ShareholderLoanDiagnostics
    from financial_engine.shl import production
    scope = run_scope.current_run_scope()
    key = (id(periods), id(shl_input))
    cache = None
    if scope is not None:
        cache = scope.get(_SHL_KEY)
        if cache is None:
            cache = scope[_SHL_KEY] = collections.OrderedDict()
        hit = cache.get(key)
        if hit is not None and hit[0] is periods and hit[1] is shl_input:
            cache.move_to_end(key)
            if isinstance(hit[2], _Decline):
                raise _Decline(hit[2].reason)
            return hit[2]
    try:
        out = _build_shl_template(periods, shl_input, production, ShareholderLoanDiagnostics)
    except _Decline as d:
        out = d
    if cache is not None:
        cache[key] = (periods, shl_input, out)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)
    if isinstance(out, _Decline):
        raise _Decline(out.reason)
    return out


def _build_shl_template(periods, shl_input, production, diag_cls):
    mode = _shl_static_admission(periods, shl_input)
    n = len(periods)
    diag = diag_cls(converged=False, is_authoritative=False, iteration_count=0, max_iterations=0,
                    convergence_tolerance_keur=0.0, convergence_relative_tolerance=0.0,
                    max_closing_delta_keur=0.0, max_interest_delta_keur=0.0, termination_reason="NATIVE_V11_TEMPLATE")
    try:
        tpl = production.compute_shareholder_loan_schedules(periods, shl_input, (0.0,) * n, diagnostics=diag,
                                                            enforce_maturity_residual=False, maturity_context=None)
        for p in periods:
            if not p.is_construction:
                production._shl_operating_accrual_start(p)
    except Exception as exc:  # noqa: BLE001 - static canonical raise: decline, the canonical replay raises it
        raise _Decline(f"SHL_TEMPLATE_RAISES:{type(exc).__name__}") from None
    n_con = sum(1 for p in periods if p.is_construction)
    if tuple(tpl.period_indices) != tuple(p.period_index for p in periods):
        _decline("SHL_TEMPLATE_AXIS")
    t_gross = [_f(x, "shl_t_gross") for x in tpl.shl_gross_interest_keur[:n_con]]
    t_close = [_f(x, "shl_t_close") for x in tpl.shl_closing_keur[:n_con]]
    opening0 = _f(tpl.shl_opening_keur[n_con], "shl_opening0") if n_con < n else 0.0
    keep = dict(idx=_iarr(p.period_index for p in periods), is_con=_iarr(1 if p.is_construction else 0 for p in periods),
                dcf=_darr(p.day_fraction if not p.is_construction else 0.0 for p in periods),
                t_gross=_darr(t_gross), t_close=_darr(t_close))
    struct = ShlGeom(n=n, n_con=n_con, period_index=keep["idx"], is_con=keep["is_con"], dcf=keep["dcf"],
                     t_gross=keep["t_gross"], t_close=keep["t_close"], opening0=opening0,
                     rate=shl_input.annual_fixed_rate, conv_tol=shl_input.convergence_tolerance_keur, mode=mode,
                     repayment_start=shl_input.repayment_start_period_index,
                     maturity_index=shl_input.maturity_period_index)
    return struct, keep


# ------------------------------------------------------------------------------- Stage 3a full tax

class _AllocRow(NamedTuple):
    """The two ``PeriodTaxYearAllocation`` fields the canonical assembly reads."""
    tax_year: int
    allocation_fraction: float


class _PeriodTaxRow(NamedTuple):
    """The ``PeriodCashTaxResult`` fields read by the canonical CFADS / schedule assembly helpers."""
    period_index: int
    primary_tax_year: int
    tax_year_allocations: tuple
    deductible_interest_keur: float
    disallowed_interest_keur: float
    other_fiscal_reintegration_keur: float
    taxable_income_before_lcf_share_keur: float
    cit_accrual_share_keur: float
    cash_tax_keur: float
    shl_tax_eligible_interest_keur: float
    shl_non_deductible_interest_keur: float
    capitalisation_ratio: object
    capitalisation_gate_active: object
    shl_absolute_limit_component_keur: float
    shl_ebitda_limit_component_keur: float
    shl_additional_non_deductible_component_keur: float
    financing_income_keur: float


class _CfadsRow(NamedTuple):
    """The ``PeriodCfadsResult`` fields (same values as ``calculate_canonical_cfads``)."""
    period_index: int
    ebitda_keur: float
    cash_tax_keur: float
    cfads_keur: float
    financing_income_keur: float


class _TaxResult(NamedTuple):
    """``TaxAndCfadsResult`` shape for the canonical consumers (annual results only where stored)."""
    annual_results: tuple
    period_results: tuple
    terminal_unpaid_tax_keur: float


class _CashRow(NamedTuple):
    """The two ``PeriodCashTaxResult`` fields ``_build_debt_sizing_schedules_from_bank`` reads."""
    period_index: int
    cash_tax_keur: float


_FLOAT_ONLY = {float}


def _full_tax(native, periods, tax_input, *, annual: bool, stats):
    """calculate_tax(periods, tax_input) + calculate_canonical_cfads(...) via one kernel call.

    ``annual``: the result is stored (Base tax-and-CFADS schedules): real ``TaxAnnualResult`` objects and
    full period rows. Otherwise (Bank debt-sizing tax) only the period cash tax and CFADS are consumed."""
    _orch, tax, _s, loss_ledger, _rs = _modules()
    from financial_engine.inputs import TaxCalculationInput
    if type(tax_input) is not TaxCalculationInput:
        _decline("TAX_INPUT_TYPE")
    policy = tax_input.policy
    g = _geometry(periods)
    pol, pol_keep = _tax_policy(policy, tax_input.opening_loss_vintages, g)
    interest_map = tax._build_interest_map(tax_input.period_interest)
    adj_map = tax._build_adj_map(tax_input.period_adjustments)
    fin_map = tax._build_financing_income_map(tax_input)
    resolve = tax._resolve_shl_tax_eligible_interest
    gross, nd, elig, caps, checked = [], [], [], [], []
    for idx in g.row_idx:
        pi = interest_map.get(idx)
        if pi:
            if pi.shl_deductible_interest_keur is not None:
                _decline("SHL_DEDUCTIBLE_OVERRIDE")
            e, n = resolve(pi, policy)
            checked += (pi.senior_interest_keur, pi.other_interest_keur, pi.shl_interest_keur, e, n)
            gross.append(pi.senior_interest_keur + pi.other_interest_keur + e)
            nd.append(n); elig.append(e)
            caps.append((pi.capitalisation_ratio, pi.capitalisation_gate_active, pi.absolute_limit_component_keur,
                         pi.ebitda_limit_component_keur, pi.additional_non_deductible_component_keur))
        else:
            gross.append(0.0); nd.append(0.0); elig.append(0.0)
            caps.append((None, None, 0.0, 0.0, 0.0))
    reint = [adj_map.get(idx, 0.0) for idx in g.row_idx]
    fin = [fin_map.get(idx, 0.0) for idx in g.row_idx]
    if not set(map(type, checked)) <= _FLOAT_ONLY or set(map(type, reint)) != _FLOAT_ONLY or \
            set(map(type, fin)) != _FLOAT_ONLY:
        _decline("TYPE_NOT_FLOAT:tax_rows")
    keep = [pol_keep, _darr(gross), _darr(nd), _darr(elig), _darr(reint), _darr(fin)]
    plan = FullTaxPlan(abi_version=ABI, struct_size=C.sizeof(FullTaxPlan), geom=g.struct, pol=pol,
                       gross=keep[1], nd=keep[2], elig=keep[3], reint=keep[4], fin=keep[5])
    ny, ns, nr = g.n_years, g.n_slots, g.n_rows
    nd_, ni_ = 9 * (ny + ns + nr) + 1, 2 * ny + nr
    out_d, out_i = (C.c_double * nd_)(), (C.c_int64 * ni_)()          # per call: never shared
    status = native.lib.fk3_full_tax(C.byref(plan), out_d, nd_, out_i, ni_)
    del keep
    if status != 0:
        _decline(f"FULL_TAX_KERNEL_STATUS_{status}")
    if stats is not None:
        stats.native_full_tax += 1
    flat = memoryview(out_d).cast("B").cast("d").tolist()       # native-endian binary64, exact bits
    ints = list(out_i)
    terminal_unpaid = flat[-1]
    o = 9 * ny + 9 * ns
    r_cash, r_cfads = flat[o + 6 * nr:o + 7 * nr], flat[o + 7 * nr:o + 8 * nr]
    row_idx = g.row_idx
    cfads = tuple(map(_CfadsRow, row_idx, g.ebitda, r_cash, r_cfads, fin))
    if not annual:
        return _TaxResult((), tuple(map(_CashRow, row_idx, r_cash)), terminal_unpaid), cfads
    Y = {k: flat[i * ny:(i + 1) * ny] for i, k in enumerate(_YEAR_D)}
    so = 9 * ny
    S = {k: flat[so + i * ns:so + (i + 1) * ns] for i, k in enumerate(_SLOT_D)}
    R = {k: flat[o + i * nr:o + (i + 1) * nr] for i, k in enumerate(_ROW_D)}
    years, s_norm, slot_row, slot_year = g.year_keys, S["s_norm"], g.slot_row, g.slot_year
    allocs_by_row = [[] for _ in range(nr)]
    for s_ in range(ns):
        allocs_by_row[slot_row[s_]].append(_AllocRow(years[slot_year[s_]], s_norm[s_]))
    prim = ints[2 * ny:2 * ny + nr]
    period_results = tuple(
        _PeriodTaxRow(idx, prim[r], tuple(allocs_by_row[r]), R["r_ded"][r], R["r_dis"][r], reint[r],
                      R["r_ti_share"][r], R["r_cit"][r], r_cash[r], R["r_elig"][r], R["r_nd"][r],
                      *caps[r], fin[r])
        for r, idx in enumerate(row_idx))
    annual_results = _annual_results(tax, policy, tax_input, g, Y, S, ints[:ny], ints[ny:2 * ny])
    return _TaxResult(annual_results, period_results, terminal_unpaid), cfads


def _annual_results(tax, policy, tax_input, g: _Geometry, Y, S, rule, allow):
    """TaxAnnualResult objects of calculate_tax: native numerics + the canonical vintage ledger."""
    from financial_engine.policies.tax import TaxLossUtilisationGate
    ti_before = tuple(Y["ti_before"])
    gate = policy.loss_utilisation_gate == TaxLossUtilisationGate.EBT_POSITIVE
    entries = tax.run_annual_fifo_ledger(
        taxable_income_before_lcf=ti_before, tax_year_indices=g.year_keys,
        opening_inputs=tax_input.opening_loss_vintages, loss_carryforward_years=policy.loss_carryforward_years,
        loss_use_allowed=tuple(bool(a) for a in allow) if gate else None)
    if len(entries) != g.n_years:
        _decline("LEDGER_AXIS")
    slots_by_year = g.slots_by_year
    out = []
    y_e, y_d = g.plan.y_ebitda, g.plan.y_dep
    TaxAnnualResult = tax.TaxAnnualResult
    for k, (yr, lcf) in enumerate(zip(g.year_keys, entries)):
        ti_after = lcf.taxable_income_after_lcf_keur
        if type(ti_after) is not float or ti_after.hex() != Y["ti_after"][k].hex():
            _decline("LEDGER_TWIN_MISMATCH")
        liability = policy.corporate_rate * max(0.0, ti_after)
        if liability.hex() != Y["liability"][k].hex():
            _decline("LIABILITY_TWIN_MISMATCH")
        sl = slots_by_year[k]
        out.append(TaxAnnualResult(
            tax_year=yr, period_indices=g.year_periods[k], total_interest_keur=Y["y_interest"][k],
            deduction_capacity_keur=Y["capacity"][k], deductible_interest_keur=Y["deductible"][k],
            disallowed_interest_keur=Y["disallowed"][k], atad_binding_rule=_RULES[rule[k]],
            ebitda_keur=y_e[k], financing_income_keur=Y["y_fin"][k], tax_depreciation_keur=y_d[k],
            other_fiscal_reintegration_keur=Y["y_reint"][k], taxable_income_before_lcf_keur=ti_before[k],
            loss_opening_keur=lcf.opening_loss_pre_expiry_keur, loss_expired_keur=lcf.loss_expired_keur,
            loss_used_keur=lcf.loss_used_keur, loss_generated_keur=lcf.loss_generated_keur,
            loss_closing_keur=lcf.closing_loss_keur, taxable_income_after_lcf_keur=ti_after, ledger_entry=lcf,
            current_tax_liability_keur=liability,
            period_atad_deductible=tuple(S["s_ded"][s] for s in sl),
            period_atad_disallowed=tuple(S["s_dis"][s] for s in sl)))
    return tuple(out)



# ------------------------------------------------------------------------------- canonical constants

def _code_constants(fn) -> dict:
    """(type, value) -> the constant OBJECT the canonical function's code uses (the compiler merges equal
    constants of one module), so strings and tuples this module places in a result are the very objects the
    canonical evaluation places there: identical values AND identical object sharing (pickle bytes)."""
    import types as _types
    out: dict = {}
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        for c in code.co_consts:
            if isinstance(c, _types.CodeType):
                stack.append(c)
            elif type(c) in (str, tuple):
                out.setdefault((type(c), c), c)
    return out


def _canonical_evidence(fn, items: tuple) -> tuple:
    """DerivationEvidence built here, with every literal replaced by the canonical function's constant."""
    from financial_engine.provenance import DerivationEvidence
    k = _code_constants(fn)

    def c(v):
        try:
            return k.get((type(v), v), v)
        except TypeError:                     # unhashable: not a constant
            return v

    return tuple(DerivationEvidence(output_path=c(e.output_path), source_module=c(e.source_module),
                                    source_function=c(e.source_function), input_paths=c(e.input_paths),
                                    notes=c(e.notes)) for e in items)

# ------------------------------------------------------------------------------- front door

def _native_or_decline(stats):
    cfg = current_config()
    if cfg.mode != "candidate":
        _decline("MODE_OFF")
    native, reason = get_stage3()
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


class _Commit:
    """Set once the canonical maturity ledger may have been written (OD-R provisional context). From then on
    the evaluation is the canonical statement sequence and its exceptions propagate unchanged: a decline
    (and canonical replay) would record the same breaches twice."""

    __slots__ = ("committed",)

    def __init__(self) -> None:
        self.committed = False


def run_senior_debt_model(inputs, *, shl_maturity_context=None):
    """Stage 3 served ``orchestrator.run_senior_debt_model(inputs, shl_maturity_context=...)`` or None."""
    if current_config().mode != "candidate":
        return None
    stats = current_stats()
    commit = _Commit()
    try:
        native = _native_or_decline(stats)
        result = _serve(native, inputs, shl_maturity_context, stats, commit)
    except _Decline as d:
        if commit.committed:                     # never reached: no decline site after the commit point
            raise RuntimeError(f"NATIVE_V11_DECLINE_AFTER_COMMIT:{d.reason}") from None
        if stats is not None:
            stats.declines[d.reason] += 1
        return None
    except Exception as exc:  # noqa: BLE001 - before the commit point the canonical replay decides (and raises)
        if commit.committed:
            raise
        if stats is not None:
            stats.declines[f"ADMISSION_EXCEPTION:{type(exc).__name__}:{str(exc)[:120]}"] += 1
        return None
    if stats is not None:
        stats.native_models += 1
    return result


def _model_admission(inputs, shl_maturity_context):
    from financial_engine.inputs import SeniorDebtModelInput, TaxCalculationInput
    from financial_engine.shl.maturity_authority import ShlMaturityContext, ShlMaturityLedger
    if type(inputs) is not SeniorDebtModelInput:
        _decline("MODEL_INPUT_TYPE")
    if shl_maturity_context is not None:
        if inputs.shareholder_loan is None:
            _decline("SHL_MATURITY_CONTEXT_WITHOUT_SHL")      # canonical raises ValueError
        if type(shl_maturity_context) is not ShlMaturityContext:
            _decline("SHL_MATURITY_CONTEXT_TYPE")
        if shl_maturity_context.provisional and type(shl_maturity_context.ledger) is not ShlMaturityLedger:
            _decline("SHL_MATURITY_LEDGER_TYPE")
    if type(inputs.tax) is not TaxCalculationInput:
        _decline("TAX_INPUT_TYPE")
    lp = getattr(inputs.tax.policy, "interest_limitation_policy", None)
    if lp is not None and lp.enabled:
        _decline("DYNAMIC_INTEREST_LIMITATION")
    if inputs.debt_sizing_case.tax_periodisation_mode_override is not None:
        _decline("BANK_TAX_PERIODISATION_OVERRIDE")


def _serve(native, inputs, shl_maturity_context, stats, commit):
    _model_admission(inputs, shl_maturity_context)
    if inputs.shareholder_loan is not None:
        return _serve_shl(native, inputs, shl_maturity_context, stats, commit)
    return _serve_plain(native, inputs, stats)


def _plan(native_kind_shl: bool, g_bank, g_base, pol, bank_ctx, base_ctx, debt, shl=None, shl_input=None):
    P = Stage3Plan()
    P.abi_version, P.struct_size = ABI, C.sizeof(Stage3Plan)
    P.bank, P.pol, P.bank_ctx, P.debt = g_bank.struct, pol, bank_ctx, debt.struct
    if native_kind_shl:
        P.base, P.base_ctx, P.shl = g_base.struct, base_ctx, shl
        P.shl_max_iter = shl_input.maximum_iterations
        P.shl_abs_tol = shl_input.convergence_tolerance_keur
        P.shl_rel_tol = shl_input.convergence_relative_tolerance
        P.use_shl = 1
    return P


# ------------------------------------------------------------------------------- plain path

def _serve_plain(native, inputs, stats):
    """Mirror of ``orchestrator.run_senior_debt_model`` (no SHL) with the solve and both full tax
    evaluations served natively. Canonical statement order; every canonical helper called as is."""
    orch, _tax, _solver, *_ = _modules()
    from financial_engine.inputs import TaxCalculationInput, PeriodInterestInput

    policy = inputs.senior_debt_policy
    sd_inputs = inputs.senior_debt_inputs

    bank_op = orch.derive_debt_sizing_operating_input(inputs.operating, inputs.debt_sizing_case)
    phase2b_inputs = orch.TaxCfadsModelInput(operating=inputs.operating, tax=inputs.tax)
    phase2b_result = orch.run_tax_cfads_model(phase2b_inputs)
    bank_phase2a_result = orch.run_operating_model(bank_op)
    base_tax_input = inputs.tax

    debt_start = policy.repayment_start_period_index
    debt_end = policy.maturity_period_index
    debt_periods = tuple(
        p for p in bank_phase2a_result.periods
        if p.is_operation and debt_start <= p.period_index <= debt_end
    )
    full_axis = tuple(p.period_index for p in phase2b_result.periods)
    senior_axis = tuple(p.period_index for p in debt_periods)
    axis_contract = orch.CanonicalAxisContract.from_periods_and_policy(phase2b_result.periods, policy)

    # ---- native solve (solve_senior_debt with the MERGE_SENIOR tax callback on the bank axis)
    g_bank = _geometry(bank_phase2a_result.periods)
    pol, pol_keep = _tax_policy(base_tax_input.policy, base_tax_input.opening_loss_vintages, g_bank)
    bank_ctx, ctx_keep = _merge_source(base_tax_input, g_bank, base_tax_input.policy)
    debt = _debt_geometry(policy, sd_inputs, debt_periods, g_bank)
    P = _plan(False, g_bank, None, pol, bank_ctx, None, debt)
    out = Stage3Out()
    n = len(debt.period_indices)
    cf_final, fcf, row_in, row_ds = ((C.c_double * n)() for _ in range(4))
    status = native.lib.fk3_plain(C.byref(P), C.byref(out), cf_final, fcf, row_in, row_ds, n)
    del pol_keep, ctx_keep
    if status != 0:
        _decline(f"PLAIN_KERNEL_STATUS_{status}")
    if stats is not None:
        stats.native_plain += 1; stats.native_solves += 1; stats.native_tax_evaluations += out.solve.tax_evals
    sd_result = _materialise_senior(debt, policy, sd_inputs, out.solve, cf_final, fcf)

    if not sd_result.diagnostics.is_authoritative:
        _decline("NOT_AUTHORITATIVE")

    final_senior_interest = orch._strict_period_map(
        sd_result.period_indices, sd_result.senior_interest_keur,
        label="senior_debt.final_senior_interest", expected_indices=senior_axis)
    merged_base: dict = {}
    for pi in base_tax_input.period_interest:
        merged_base[pi.period_index] = pi
    for idx, senior_keur in final_senior_interest.items():
        existing = merged_base.get(idx)
        if existing is not None:
            merged_base[idx] = PeriodInterestInput(
                period_index=idx, senior_interest_keur=senior_keur,
                shl_interest_keur=existing.shl_interest_keur, other_interest_keur=existing.other_interest_keur)
        else:
            merged_base[idx] = PeriodInterestInput(period_index=idx, senior_interest_keur=senior_keur)
    base_updated_tax = TaxCalculationInput(
        policy=base_tax_input.policy, opening_loss_vintages=base_tax_input.opening_loss_vintages,
        period_interest=tuple(merged_base.values()), period_adjustments=base_tax_input.period_adjustments,
        period_financing_income=base_tax_input.period_financing_income)
    base_tax_result, base_cfads_results = _full_tax(native, phase2b_result.periods, base_updated_tax,
                                                    annual=True, stats=stats)
    final_tax_cfads = orch._assemble_tax_cfads_schedules(
        phase2b_result, base_tax_result, base_tax_result.period_results, base_cfads_results)

    _bank_final_tax_input = orch._merge_financing_tax_input(
        base_tax_input, final_senior_interest,
        tax_periodisation_mode_override=inputs.debt_sizing_case.tax_periodisation_mode_override)
    final_bank_tax_result, final_bank_cfads_results = _full_tax(native, bank_phase2a_result.periods,
                                                                _bank_final_tax_input, annual=False, stats=stats)
    debt_sizing_schedules = orch._build_debt_sizing_schedules_from_bank(
        bank_phase2a_result=bank_phase2a_result, final_bank_tax_result=final_bank_tax_result,
        final_bank_cfads_results=final_bank_cfads_results, senior_debt_result=sd_result,
        senior_axis=senior_axis, base_periods=phase2b_result.periods)

    _sd_service_by_idx = orch._strict_period_map(
        sd_result.period_indices, sd_result.senior_debt_service_keur,
        label="senior_debt.result_service", expected_indices=senior_axis)
    _base_cfads_by_idx = orch._strict_period_map(
        final_tax_cfads.period_indices, final_tax_cfads.cfads_keur,
        label="senior_debt.result_base_cfads", expected_indices=full_axis)
    _base_dscr = tuple(
        (
            _base_cfads_by_idx.get(idx, 0.0) / ds
            if (ds := _sd_service_by_idx.get(idx, 0.0)) > 0.0
            and math.isfinite(_base_cfads_by_idx.get(idx, 0.0))
            else None
        )
        for idx in sd_result.period_indices
    )
    diag_dict = {
        "converged": sd_result.diagnostics.converged,
        "is_authoritative": sd_result.diagnostics.is_authoritative,
        "iteration_count": sd_result.diagnostics.iteration_count,
        "initial_debt_guess_keur": sd_result.diagnostics.initial_debt_guess_keur,
        "final_debt_size_keur": sd_result.diagnostics.final_debt_size_keur,
        "maximum_absolute_difference_keur": sd_result.diagnostics.maximum_absolute_difference_keur,
        "maximum_relative_difference": sd_result.diagnostics.maximum_relative_difference,
        "binding_constraint": sd_result.diagnostics.binding_constraint,
        "termination_reason": sd_result.diagnostics.termination_reason,
        "dscr_debt_capacity_keur": sd_result.diagnostics.dscr_debt_capacity_keur,
        "gearing_debt_capacity_keur": sd_result.diagnostics.gearing_debt_capacity_keur,
    }
    result_schedules = orch._SeniorDebtSchedulesResult(
        period_indices=sd_result.period_indices,
        senior_debt_opening_keur=sd_result.senior_debt_opening_keur,
        senior_interest_keur=sd_result.senior_interest_keur,
        senior_principal_keur=sd_result.senior_principal_keur,
        senior_debt_service_keur=sd_result.senior_debt_service_keur,
        senior_debt_closing_keur=sd_result.senior_debt_closing_keur,
        base_dscr=_base_dscr,
        debt_size_keur=sd_result.debt_size_keur,
        binding_constraint=sd_result.binding_constraint,
        diagnostics=diag_dict,
    )

    _period_is_constr = {p.period_index: p.is_construction for p in phase2b_result.periods}
    _all_period_indices = tuple(p.period_index for p in phase2b_result.periods)
    _cash_after: list = []
    _cash_avail: list = []
    for _idx in _all_period_indices:
        _bcfads = _base_cfads_by_idx.get(_idx, 0.0)
        _sds = _sd_service_by_idx.get(_idx, 0.0)
        _after = _bcfads - _sds
        _cash_after.append(_after)
        _cash_avail.append(0.0 if _period_is_constr.get(_idx, False) else max(0.0, _after))
    _base_cfads_all = tuple(_base_cfads_by_idx.get(i, 0.0) for i in _all_period_indices)
    _sd_service_all = tuple(_sd_service_by_idx.get(i, 0.0) for i in _all_period_indices)
    post_senior_cash = orch.PostSeniorCashSchedules(
        period_indices=_all_period_indices,
        base_cfads_keur=_base_cfads_all,
        senior_debt_service_keur=_sd_service_all,
        cash_after_senior_before_reserves_keur=tuple(_cash_after),
        cash_available_for_shl_before_reserves_keur=tuple(_cash_avail),
    )

    from financial_engine.dsra.model import run_cash_dsra_model
    from financial_engine.dsra.contracts import CashDsraInput
    from financial_engine.dsra.target import SCHEDULE_TARGET_POLICIES, build_dsra_required_balance_schedule
    _dsra_input = inputs.dsra if isinstance(inputs.dsra, CashDsraInput) else None
    if _dsra_input is not None and _dsra_input.target_policy in SCHEDULE_TARGET_POLICIES:
        _all_starts = tuple(p.period_start for p in phase2b_result.periods)
        _all_ends = tuple(p.period_end for p in phase2b_result.periods)
        _all_is_constr = tuple(p.is_construction for p in phase2b_result.periods)
        _dynamic_schedule = build_dsra_required_balance_schedule(
            period_indices=_all_period_indices,
            period_start_dates=_all_starts,
            period_end_dates=_all_ends,
            is_construction=_all_is_constr,
            senior_debt_service_keur=post_senior_cash.senior_debt_service_keur,
            coverage_months=_dsra_input.dsra_months,
            periods_per_year=inputs.senior_debt_policy.periods_per_year,
            policy=_dsra_input.target_policy,
        )
        _dsra_input = CashDsraInput(
            mode=_dsra_input.mode,
            requirement_keur=_dsra_input.requirement_keur,
            required_balance_schedule=_dynamic_schedule,
            target_policy=_dsra_input.target_policy,
            dsra_months=_dsra_input.dsra_months,
        )
    cash_dsra = run_cash_dsra_model(post_senior_cash, _dsra_input, phase2b_result.periods)

    fingerprint = orch.compute_senior_debt_fingerprint(inputs)
    DerivationEvidence = orch.DerivationEvidence
    evidence = phase2b_result.provenance.derivation_evidence + _canonical_evidence(orch.run_senior_debt_model, (
        DerivationEvidence(
            output_path="senior_debt.senior_interest_keur",
            source_module="financial_engine.senior_debt.interest",
            source_function="period_interest",
            input_paths=("senior_debt_inputs.period_rates", "senior_debt_policy"),
            notes=("interest = opening_balance × annual_rate × day_count_fraction",),
        ),
        DerivationEvidence(
            output_path="senior_debt.senior_principal_keur",
            source_module="financial_engine.senior_debt.sculpting",
            source_function="build_schedule",
            input_paths=(
                "debt_sizing.bank_cfads_keur",
                "senior_debt_inputs.period_rates",
                "senior_debt_inputs.period_dscr_targets",
                "senior_debt_inputs.period_debt_service_availability",
                "senior_debt_policy.target_dscr",
                "senior_debt_policy.day_count_convention",
            ),
            notes=(
                "C3B3A algorithm: "
                "resolved_target_dscr[p] = period_dscr_targets[p].target_dscr "
                "if p in period_dscr_targets else policy.target_dscr; "
                "resolved_availability[p] = period_debt_service_availability[p].availability_fraction "
                "if p in period_debt_service_availability else 1.0; "
                "allowed_debt_service[p] = max(0, bank_cfads[p] / resolved_target_dscr[p]) "
                "* resolved_availability[p]; "
                "principal[p] = min(opening_balance[p], max(0, allowed_debt_service[p] - interest[p]))",
            ),
        ),
        DerivationEvidence(
            output_path="post_senior_cash",
            source_module="financial_engine.orchestrator",
            source_function="run_senior_debt_model",
            input_paths=(
                "tax_and_cfads.cfads_keur",
                "senior_debt.senior_debt_service_keur",
            ),
            notes=(
                "post_senior_cash uses Base CFADS (tax_and_cfads.cfads_keur), NOT bank CFADS; "
                "cash_after_senior = base_cfads - senior_ds (signed); "
                "cash_available_for_shl = max(0, cash_after_senior); "
                "DSRA_NOT_IMPLEMENTED: pre-reserve figures; DSRA ordering unresolved",
            ),
        ),
        DerivationEvidence(
            output_path="senior_debt.debt_size_keur",
            source_module="financial_engine.senior_debt.solver",
            source_function="solve_senior_debt",
            input_paths=("senior_debt_inputs", "senior_debt_policy"),
            notes=(
                f"fixed-point sizing; termination={sd_result.diagnostics.termination_reason}; "
                f"iterations={sd_result.diagnostics.iteration_count}",
            ),
        ),
    ))
    provenance = orch.EngineProvenance(
        engine_version=orch.ENGINE_VERSION,
        run_path_id=orch.SENIOR_DEBT_RUN_PATH_ID,
        input_fingerprint=fingerprint,
        derivation_evidence=evidence,
    )
    validation_issues = phase2b_result.validation_issues
    warnings = phase2b_result.warnings + tuple(
        f"{i.code} {i.path}: {i.message}" for i in validation_issues
        if i.severity.value == "WARNING"
    )
    return orch.ProjectModelResult(
        provenance=provenance,
        periods=phase2b_result.periods,
        operating_schedules=phase2b_result.operating_schedules,
        tax_and_cfads=final_tax_cfads,
        senior_debt=result_schedules,
        debt_sizing=debt_sizing_schedules,
        post_senior_cash=post_senior_cash,
        cash_dsra=cash_dsra,
        axis_contract=axis_contract,
        unavailable_sections=orch._PHASE_2C_UNAVAILABLE,
        validation_issues=validation_issues,
        warnings=warnings,
    )


# ------------------------------------------------------------------------------- SHL path

def _serve_shl(native, inputs, shl_maturity_context, stats, commit):
    """Mirror of ``orchestrator._run_senior_debt_model_with_shl`` (dynamic interest limitation disabled):
    the fixed point and the final solve are one kernel call; the final recomputation is the canonical
    statement sequence with the two full tax evaluations served natively.

    Effects: the only state the canonical evaluation writes (besides Run-scope memo caches) is the OD-R
    maturity ledger of a PROVISIONAL ``shl_maturity_context``, written by the handshake and the final SHL
    schedules. Every pure statement the canonical code evaluates after the handshake schedule is therefore
    evaluated first (the SHL schedule values do not depend on the context - its contract changes no
    value - so a context-free probe of the same schedule supplies the handshake values), every decline
    happens before the handshake, and from the handshake on the canonical calls run in canonical order
    with their exceptions propagating unchanged (``commit``)."""
    orch, _tax, _solver, *_ = _modules()
    from financial_engine.shl.production import compute_shareholder_loan_schedules
    from financial_engine.inputs import TaxCfadsModelInput

    policy = inputs.senior_debt_policy
    sd_inputs = inputs.senior_debt_inputs
    shl_input = inputs.shareholder_loan

    bank_op = orch.derive_debt_sizing_operating_input(inputs.operating, inputs.debt_sizing_case)
    phase2b_result = orch.run_tax_cfads_model(TaxCfadsModelInput(operating=inputs.operating, tax=inputs.tax))
    bank_phase2a_result = orch.run_operating_model(bank_op)
    base_tax_input = inputs.tax

    debt_start = policy.repayment_start_period_index
    debt_end = policy.maturity_period_index
    debt_periods = tuple(
        p for p in bank_phase2a_result.periods
        if p.is_operation and debt_start <= p.period_index <= debt_end
    )
    axis_contract_shl = orch.CanonicalAxisContract.from_periods_and_policy(phase2b_result.periods, policy)
    full_axis_shl = axis_contract_shl.full_axis
    senior_axis_shl = axis_contract_shl.senior_axis

    dynamic_policy_enabled = bool(
        getattr(base_tax_input.policy, "interest_limitation_policy", None) is not None
        and base_tax_input.policy.interest_limitation_policy.enabled
    )
    if dynamic_policy_enabled:
        _decline("DYNAMIC_INTEREST_LIMITATION")
    seed_shl_closing = {period.period_index: shl_input.initial_principal_keur for period in phase2b_result.periods}
    base_limitation_state = orch._build_dynamic_interest_limitation_state(
        periods=phase2b_result.periods, tax_policy=base_tax_input.policy,
        equity_input=inputs.capitalisation_gate_equity, senior_interest_by_period={},
        shl_gross_interest_by_period={}, shl_closing_by_period=seed_shl_closing, tax_result=None)
    bank_limitation_state = orch._build_dynamic_interest_limitation_state(
        periods=bank_phase2a_result.periods, tax_policy=base_tax_input.policy,
        equity_input=inputs.capitalisation_gate_equity, senior_interest_by_period={},
        shl_gross_interest_by_period={}, shl_closing_by_period=seed_shl_closing, tax_result=None)
    if base_limitation_state.limitation_by_period or bank_limitation_state.limitation_by_period:
        _decline("LIMITATION_STATE_NOT_EMPTY")
    last_max_retained_delta = 0.0
    last_max_ratio_delta = 0.0
    last_gate_mismatch_count = 0

    # ---- static admission of the fixed-point structure (every loop-invariant canonical raise predicate)
    g_bank = _geometry(bank_phase2a_result.periods)
    g_base = _geometry(phase2b_result.periods)
    if g_base.row_idx != g_bank.row_idx or g_base.row_idx != tuple(full_axis_shl):
        _decline("BASE_BANK_AXIS")
    debt = _debt_geometry(policy, sd_inputs, debt_periods, g_bank)
    if debt.period_indices != tuple(senior_axis_shl):
        _decline("SENIOR_AXIS")                     # _strict_period_map(shl_fixed_point.senior_interest) raises
    pol, pol_keep = _tax_policy(base_tax_input.policy, base_tax_input.opening_loss_vintages, g_bank)
    pol_base, pol_base_keep = _tax_policy(base_tax_input.policy, base_tax_input.opening_loss_vintages, g_base)
    bank_ctx, bank_keep = _merge_source(base_tax_input, g_bank, base_tax_input.policy)
    base_ctx, base_keep = bank_ctx, bank_keep            # identical period axis (checked above)
    shl_struct, shl_keep = _shl_template(phase2b_result.periods, shl_input)
    P = _plan(True, g_bank, g_base, pol, bank_ctx, base_ctx, debt, shl_struct, shl_input)
    out = Stage3Out()
    n, nr = len(debt.period_indices), g_base.n_rows
    shl_gross, shl_close = (C.c_double * nr)(), (C.c_double * nr)()
    cf_final, fcf, row_in, row_ds = ((C.c_double * n)() for _ in range(4))
    status = native.lib.fk3_shl_fixed_point(C.byref(P), C.byref(out), shl_gross, shl_close, nr,
                                            cf_final, fcf, row_in, row_ds, n)
    del pol_keep, pol_base_keep, bank_keep, base_keep
    if status != 0:
        _decline(f"SHL_KERNEL_STATUS_{status}")
    if stats is not None:
        stats.native_shl_fixed_points += 1
        stats.native_solves += out.loop_solves + 1
        stats.native_tax_evaluations += out.loop_tax_evals + out.solve.tax_evals
    iteration = out.shl_iterations
    last_max_closing_delta = out.last_closing_delta
    last_max_interest_delta = out.last_interest_delta
    shl_period_indices = g_base.row_idx
    prev_shl_closing = tuple(_dvec(shl_close, nr))

    # ---- canonical final recomputation (statement order of _run_senior_debt_model_with_shl)
    final_shl_interest = orch._strict_period_map(
        shl_period_indices, tuple(_dvec(shl_gross, nr)),
        label="shl_fixed_point.final_gross_interest", expected_indices=full_axis_shl)

    final_senior_result = _materialise_senior(debt, policy, sd_inputs, out.solve, cf_final, fcf)
    if not final_senior_result.diagnostics.is_authoritative:
        _decline("FINAL_NOT_AUTHORITATIVE")

    final_senior_interest = orch._strict_period_map(
        final_senior_result.period_indices, final_senior_result.senior_interest_keur,
        label="shl_fixed_point.final_senior_interest", expected_indices=senior_axis_shl)
    _final_senior_full = tuple(final_senior_interest.get(idx, 0.0) for idx in full_axis_shl)
    _final_shl_full = tuple(final_shl_interest.get(idx, 0.0) for idx in full_axis_shl)
    _senior_axis_set = set(senior_axis_shl)
    for _ci, _idx in enumerate(full_axis_shl):
        if _idx not in _senior_axis_set:
            if _final_senior_full[_ci] != 0.0:
                _decline("AXIS_PERIOD_EXTRA")
    _final_fp = orch.FinancingInterestContract.compute_fingerprint(full_axis_shl, _final_senior_full, _final_shl_full)
    final_financing_contract = orch.FinancingInterestContract(
        period_indices=full_axis_shl,
        senior_interest_keur=_final_senior_full,
        shl_gross_interest_keur=_final_shl_full,
        iteration_id=iteration,
        final_iteration_id=iteration,
        is_final=True,
        content_fingerprint=_final_fp,
    )
    orch._require_final_financing_contract(final_financing_contract, context="B5_FINAL_CONVERGENCE_FULL_AXIS")
    _contract_senior_map, _contract_shl_map = orch.financing_interest_maps_from_contract(
        final_financing_contract, context="BASE_TAX_FROM_CONTRACT")
    final_base_tax_input = orch._merge_financing_tax_input(
        base_tax_input, _contract_senior_map, _contract_shl_map, base_limitation_state.limitation_by_period)
    orch._validate_final_financing_state(
        required_period_indices=senior_axis_shl,
        final_senior_result=final_senior_result,
        final_shl_interest=final_shl_interest,
        final_base_tax_input=final_base_tax_input,
        context="B5_FINAL_CONVERGENCE_3WAY",
    )
    final_base_tax, final_base_cfads = _full_tax(native, phase2b_result.periods, final_base_tax_input,
                                                 annual=True, stats=stats)
    final_tax_cfads = orch._assemble_tax_cfads_schedules(
        phase2b_result, final_base_tax, final_base_tax.period_results, final_base_cfads)
    final_post_senior_cash = orch._assemble_post_senior_cash_schedules(
        phase2b_result.periods, final_tax_cfads, final_senior_result, senior_axis=senior_axis_shl)

    from financial_engine.dsra.model import run_cash_dsra_model as _run_dsra
    from financial_engine.dsra.contracts import CashDsraInput as _CashDsraInput
    from financial_engine.dsra.target import (
        SCHEDULE_TARGET_POLICIES as _SCHEDULE_TARGET_POLICIES,
        build_dsra_required_balance_schedule as _build_dsra_schedule,
    )
    _shl_dsra_input = inputs.dsra if isinstance(inputs.dsra, _CashDsraInput) else None
    if _shl_dsra_input is not None and _shl_dsra_input.target_policy in _SCHEDULE_TARGET_POLICIES:
        _shl_all_indices = tuple(p.period_index for p in phase2b_result.periods)
        _shl_all_starts = tuple(p.period_start for p in phase2b_result.periods)
        _shl_all_ends = tuple(p.period_end for p in phase2b_result.periods)
        _shl_all_is_constr = tuple(p.is_construction for p in phase2b_result.periods)
        _shl_dynamic_schedule = _build_dsra_schedule(
            period_indices=_shl_all_indices,
            period_start_dates=_shl_all_starts,
            period_end_dates=_shl_all_ends,
            is_construction=_shl_all_is_constr,
            senior_debt_service_keur=final_post_senior_cash.senior_debt_service_keur,
            coverage_months=_shl_dsra_input.dsra_months,
            periods_per_year=inputs.senior_debt_policy.periods_per_year,
            policy=_shl_dsra_input.target_policy,
        )
        _shl_dsra_input = _CashDsraInput(
            mode=_shl_dsra_input.mode,
            requirement_keur=_shl_dsra_input.requirement_keur,
            required_balance_schedule=_shl_dynamic_schedule,
            target_policy=_shl_dsra_input.target_policy,
            dsra_months=_shl_dsra_input.dsra_months,
        )
    _shl_cash_dsra = _run_dsra(final_post_senior_cash, _shl_dsra_input, phase2b_result.periods)
    ShareholderLoanDiagnostics = orch.ShareholderLoanDiagnostics
    handshake_probe_diag = ShareholderLoanDiagnostics(
        converged=False,
        is_authoritative=False,
        iteration_count=iteration,
        max_iterations=shl_input.maximum_iterations,
        convergence_tolerance_keur=shl_input.convergence_tolerance_keur,
        convergence_relative_tolerance=shl_input.convergence_relative_tolerance,
        max_closing_delta_keur=last_max_closing_delta,
        max_interest_delta_keur=last_max_interest_delta,
        termination_reason="FINAL_HANDSHAKE_PROBE",
    )
    # ---- pure statements of the canonical post-handshake sequence, evaluated before any effect
    _cash_for_shl = final_post_senior_cash.cash_available_for_shl_before_reserves_keur
    handshake_values = compute_shareholder_loan_schedules(
        phase2b_result.periods, shl_input, _cash_for_shl, diagnostics=handshake_probe_diag,
        enforce_maturity_residual=False, maturity_context=None)
    _contract_bank_senior_map, _contract_bank_shl_map = orch.financing_interest_maps_from_contract(
        final_financing_contract, context="BANK_TAX_FROM_CONTRACT")
    final_bank_tax_input = orch._merge_financing_tax_input(
        base_tax_input, _contract_bank_senior_map, _contract_bank_shl_map,
        bank_limitation_state.limitation_by_period,
        tax_periodisation_mode_override=inputs.debt_sizing_case.tax_periodisation_mode_override)
    final_bank_tax, final_bank_cfads = _full_tax(native, bank_phase2a_result.periods, final_bank_tax_input,
                                                 annual=False, stats=stats)
    _handshake_closing_map = orch._strict_period_map(
        handshake_values.period_indices, handshake_values.shl_closing_keur,
        label="shl_fixed_point.final_limitation_handshake_closing", expected_indices=full_axis_shl)
    _final_base_limitation_state = orch._build_dynamic_interest_limitation_state(
        periods=phase2b_result.periods, tax_policy=base_tax_input.policy,
        equity_input=inputs.capitalisation_gate_equity, senior_interest_by_period=_contract_senior_map,
        shl_gross_interest_by_period=_contract_shl_map, shl_closing_by_period=_handshake_closing_map,
        tax_result=final_base_tax)
    _final_bank_limitation_state = orch._build_dynamic_interest_limitation_state(
        periods=bank_phase2a_result.periods, tax_policy=base_tax_input.policy,
        equity_input=inputs.capitalisation_gate_equity, senior_interest_by_period=_contract_bank_senior_map,
        shl_gross_interest_by_period=_contract_bank_shl_map, shl_closing_by_period=_handshake_closing_map,
        tax_result=final_bank_tax)
    _base_final_dynamic_delta = orch._dynamic_interest_limitation_delta(base_limitation_state, _final_base_limitation_state)
    _bank_final_dynamic_delta = orch._dynamic_interest_limitation_delta(bank_limitation_state, _final_bank_limitation_state)
    last_max_retained_delta = max(last_max_retained_delta, _base_final_dynamic_delta[0], _bank_final_dynamic_delta[0])
    last_max_ratio_delta = max(last_max_ratio_delta, _base_final_dynamic_delta[1], _bank_final_dynamic_delta[1])
    last_gate_mismatch_count = max(last_gate_mismatch_count,
                                   _base_final_dynamic_delta[2] + _bank_final_dynamic_delta[2])
    final_base_tax_shl = {pi.period_index: pi.shl_interest_keur for pi in final_base_tax_input.period_interest}
    final_bank_tax_shl = {pi.period_index: pi.shl_interest_keur for pi in final_bank_tax_input.period_interest}
    authoritative_interest_vector = tuple(
        final_shl_interest.get(idx, 0.0) for idx in handshake_values.period_indices)
    base_tax_interest_vector = tuple(
        final_base_tax_shl.get(idx, 0.0) for idx in handshake_values.period_indices)
    bank_tax_interest_vector = tuple(
        final_bank_tax_shl.get(idx, 0.0) for idx in handshake_values.period_indices)
    max_final_shl_interest_handshake_delta = max(
        orch._max_vector_delta(authoritative_interest_vector, handshake_values.shl_gross_interest_keur),
        orch._max_vector_delta(authoritative_interest_vector, base_tax_interest_vector),
        orch._max_vector_delta(authoritative_interest_vector, bank_tax_interest_vector),
    )
    max_final_shl_closing_handshake_delta = orch._max_vector_delta(
        prev_shl_closing, handshake_values.shl_closing_keur)
    if not orch._field_converged_local(
        max_final_shl_interest_handshake_delta, 0.0,
        shl_input.convergence_tolerance_keur, shl_input.convergence_relative_tolerance,
    ) or not orch._field_converged_local(
        max_final_shl_closing_handshake_delta, 0.0,
        shl_input.convergence_tolerance_keur, shl_input.convergence_relative_tolerance,
    ):
        _decline("FINAL_FINANCING_STATE_NOT_SELF_CONSISTENT")
    authoritative_diag = ShareholderLoanDiagnostics(
        converged=True,
        is_authoritative=True,
        iteration_count=iteration,
        max_iterations=shl_input.maximum_iterations,
        convergence_tolerance_keur=shl_input.convergence_tolerance_keur,
        convergence_relative_tolerance=shl_input.convergence_relative_tolerance,
        max_closing_delta_keur=last_max_closing_delta,
        max_interest_delta_keur=last_max_interest_delta,
        termination_reason="CONVERGED_FINAL_RECOMPUTE",
        max_final_shl_interest_handshake_delta_keur=max_final_shl_interest_handshake_delta,
        max_final_shl_closing_handshake_delta_keur=max_final_shl_closing_handshake_delta,
        max_retained_earnings_delta_keur=last_max_retained_delta,
        max_capitalisation_ratio_delta=last_max_ratio_delta,
        capitalisation_gate_mismatch_count=last_gate_mismatch_count,
    )
    debt_sizing_schedules = orch._build_debt_sizing_schedules_from_bank(
        bank_phase2a_result=bank_phase2a_result,
        final_bank_tax_result=final_bank_tax,
        final_bank_cfads_results=final_bank_cfads,
        senior_debt_result=final_senior_result,
        senior_axis=senior_axis_shl,
        base_periods=phase2b_result.periods,
    )
    result_schedules = orch._build_result_senior_debt_schedules(
        senior_debt_result=final_senior_result,
        final_tax_cfads=final_tax_cfads,
        senior_axis=senior_axis_shl,
        full_axis=full_axis_shl,
    )
    fingerprint = orch.compute_senior_debt_fingerprint(inputs)
    DerivationEvidence = orch.DerivationEvidence
    evidence = phase2b_result.provenance.derivation_evidence + _canonical_evidence(orch._run_senior_debt_model_with_shl, (
        DerivationEvidence(
            output_path="shareholder_loan.shl_gross_interest_keur",
            source_module="financial_engine.shl.production",
            source_function="compute_shareholder_loan_schedules",
            input_paths=("shareholder_loan", "post_senior_cash"),
            notes=(
                "SHL gross interest is included in TaxCalculationInput.period_interest.shl_interest_keur; "
                "TaxPolicy controls the tax-eligible SHL portion; "
                "CLEAN_ENGINE_NON_DEDUCTIBLE_SHL_TREATMENT; "
                "POST_SHL_CASH_IS_PRE_RESERVE",
            ),
        ),
        DerivationEvidence(
            output_path="senior_debt.debt_size_keur",
            source_module="financial_engine.orchestrator",
            source_function="_run_senior_debt_model_with_shl",
            input_paths=("senior_debt_inputs", "senior_debt_policy", "shareholder_loan"),
            notes=(
                "Senior debt is solved inside the SHL/tax fixed point; "
                "FINAL_FINANCING_STATE_RECOMPUTED_FROM_CONVERGED_SHL_AND_SENIOR_SCHEDULES",
            ),
        ),
    ))
    provenance = orch.EngineProvenance(
        engine_version=orch.ENGINE_VERSION,
        run_path_id=orch.SENIOR_DEBT_RUN_PATH_ID,
        input_fingerprint=fingerprint,
        derivation_evidence=evidence,
    )
    validation_issues = phase2b_result.validation_issues
    warnings = phase2b_result.warnings + tuple(
        f"{i.code} {i.path}: {i.message}" for i in validation_issues
        if i.severity.value == "WARNING"
    )
    # ---- effectful canonical tail, in canonical order. With a PROVISIONAL context the ledger may now be
    # written: no decline from here on. Otherwise these calls have no effect and a raise (the canonical
    # fail-closed maturity residual) still declines, so the canonical replay raises it itself.
    commit.committed = shl_maturity_context is not None and shl_maturity_context.provisional
    handshake_shl_schedule = compute_shareholder_loan_schedules(
        phase2b_result.periods,
        shl_input,
        final_post_senior_cash.cash_available_for_shl_before_reserves_keur,
        diagnostics=handshake_probe_diag,
        maturity_context=shl_maturity_context,
    )
    if handshake_shl_schedule != handshake_values:
        raise RuntimeError("NATIVE_V11_HANDSHAKE_PROBE_DIVERGED")      # impossible: the context changes no value
    final_shl_schedule = compute_shareholder_loan_schedules(
        phase2b_result.periods,
        shl_input,
        final_post_senior_cash.cash_available_for_shl_before_reserves_keur,
        diagnostics=authoritative_diag,
        maturity_context=shl_maturity_context,
    )
    return orch.ProjectModelResult(
        provenance=provenance,
        periods=phase2b_result.periods,
        operating_schedules=phase2b_result.operating_schedules,
        tax_and_cfads=final_tax_cfads,
        senior_debt=result_schedules,
        debt_sizing=debt_sizing_schedules,
        post_senior_cash=final_post_senior_cash,
        shareholder_loan=final_shl_schedule,
        cash_dsra=_shl_cash_dsra,
        axis_contract=axis_contract_shl,
        unavailable_sections=orch._PHASE_2C_UNAVAILABLE,
        validation_issues=validation_issues,
        warnings=warnings,
    )
