"""Stage 2 EXPERIMENTAL block: native SHL operating-period schedule (research; default disabled).

Served only when the Run-local configuration is ``NativeConfig(mode="candidate",
stage2_experimental=True)``. ``shl_schedules(...)`` never raises: it returns the canonical
``ShareholderLoanSchedules`` value or ``None`` (decline -> the canonical body runs unchanged).

Admission (exact types; everything else declines):
* ``periods`` exact tuple of exact ``OperatingPeriodResult``; construction periods form a prefix;
  period indices exact ints within +-2**53; ``day_fraction`` exact floats.
* ``shl_input`` exact ``ShareholderLoanModelInput`` with ``day_count_convention`` PERIOD_AXIS_ACTUAL_YEAR,
  ``repayment_mode`` BULLET or CASH_SWEEP.
* ``cash`` exact tuple/list of exact floats, same length.
* ``maturity_context`` None or exact ``ShlMaturityContext`` (provisional ledger exact type).
* Static canonical computations, executed by admission with the canonical code itself and cached per
  Run by object identity: the canonical function evaluated once with an all-zero cash vector
  (``enforce_maturity_residual=False``) — it performs every cash-independent validation and yields the
  construction rows and the operating chain's opening balance (both cash-independent) — and
  ``_shl_operating_accrual_start`` for every operating period. Any exception declines.
* Canonical-region identity (Stage 1 authentication + Stage 2 SHL functions) re-checked per call.
"""
from __future__ import annotations

import collections
import ctypes as C
import hashlib
import json
import threading
from contextvars import ContextVar
from pathlib import Path

from .config import current_config, current_stats

HERE = Path(__file__).resolve().parent
ABI = 20001
I64 = C.c_int64
D_P = C.POINTER(C.c_double)
I_P = C.POINTER(C.c_int64)
_TEMPLATE_KEY = "native_v10_stage2_shl_template_v1"
_IN_TEMPLATE: ContextVar[bool] = ContextVar("finco_native_v10_stage2_template", default=False)
_I53 = 2 ** 53
_FLOAT_ONLY = {float}


class ShlPlan(C.Structure):
    _fields_ = [("abi_version", I64), ("struct_size", I64), ("n", I64), ("n_con", I64),
                ("period_index", I_P), ("dcf", D_P),
                ("t_open", D_P), ("t_draw", D_P), ("t_gross", D_P), ("t_cint", D_P), ("t_pik", D_P),
                ("t_prin", D_P), ("t_serv", D_P), ("t_close", D_P),
                ("opening0", C.c_double), ("rate", C.c_double), ("conv_tol", C.c_double),
                ("mode", I64), ("repayment_start", I64), ("maturity_index", I64)]


class ShlOut(C.Structure):
    _fields_ = [(k, D_P) for k in ("open", "draw", "gross", "cint", "pik", "prin", "serv", "close", "cavail", "crem")] + [
        ("shortfall_count", I64), ("shortfall_period", I64), ("shortfall_closing", C.c_double)]


class _Decline(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_LOCK = threading.Lock()
_LIB: dict = {}


def _verify():
    from . import eligibility, loader
    reason = eligibility.check_runtime()
    if reason:
        return None, reason
    stage1, reason = loader.get_native()          # Stage 2 requires an authenticated Stage 1 region
    if stage1 is None:
        return None, f"STAGE1:{reason}"
    try:
        manifest = json.loads((HERE / "fk_v10_stage2_manifest.json").read_text(encoding="utf-8"))
        blob = (HERE / manifest["artifact"]).read_bytes()
    except (OSError, ValueError, KeyError) as exc:
        return None, f"LOADER2_ARTIFACT_UNAVAILABLE:{type(exc).__name__}"
    if manifest.get("abi_version") != ABI:
        return None, "LOADER2_ABI_VERSION_MANIFEST"
    if hashlib.sha256(blob).hexdigest() != manifest.get("artifact_sha256"):
        return None, "LOADER2_ARTIFACT_SHA256_MISMATCH"
    try:
        approved = (HERE / "approved_canonical_blobs_stage2.json").read_bytes()
    except OSError as exc:
        return None, f"LOADER2_APPROVED_MANIFEST_UNAVAILABLE:{type(exc).__name__}"
    if hashlib.sha256(approved).hexdigest() != manifest.get("approved_blobs_sha256"):
        return None, "LOADER2_APPROVED_MANIFEST_NOT_SEALED"
    try:
        lib = C.CDLL(str(HERE / manifest["artifact"]))
        lib.fk2_abi_version.restype = C.c_int
        lib.fk2_plan_size.restype = I64
        lib.fk2_out_size.restype = I64
        lib.fk2_build_id.restype = C.c_char_p
        lib.fk2_shl_schedule.argtypes = [C.POINTER(ShlPlan), D_P, I64, C.POINTER(ShlOut), I64, I64]
        lib.fk2_shl_schedule.restype = C.c_int
    except (OSError, AttributeError) as exc:
        return None, f"LOADER2_DLOPEN:{type(exc).__name__}"
    if lib.fk2_abi_version() != ABI or lib.fk2_plan_size() != C.sizeof(ShlPlan) or lib.fk2_out_size() != C.sizeof(ShlOut):
        return None, "LOADER2_ABI_LAYOUT"
    if lib.fk2_build_id().decode() != manifest.get("build_id"):
        return None, "LOADER2_BUILD_ID"
    from . import provenance
    auth, reason = provenance.authenticate_stage2(stage1.auth)
    if auth is None:
        return None, reason
    return (lib, manifest["build_id"], stage1, auth), None


def get_stage2():
    with _LOCK:
        if "r" not in _LIB:
            try:
                _LIB["r"] = _verify()
            except Exception as exc:  # noqa: BLE001
                _LIB["r"] = (None, f"LOADER2_UNEXPECTED:{type(exc).__name__}")
        return _LIB["r"]


def _reset_for_tests():
    with _LOCK:
        _LIB.clear()


def in_template() -> bool:
    return _IN_TEMPLATE.get()


def _darr(values):
    return (C.c_double * len(values))(*values)


def _static_admission(periods, shl_input):
    """Cash-independent admission predicates (periods / shl_input are frozen dataclasses: cacheable)."""
    from financial_engine.inputs import ShareholderLoanModelInput
    from financial_engine.results import OperatingPeriodResult
    from financial_engine.shl.contracts import ShlRepaymentMode
    from financial_engine.shl.day_count import ShlDayCountConvention
    if type(periods) is not tuple or not periods or any(type(p) is not OperatingPeriodResult for p in periods):
        raise _Decline("PERIODS_TYPE")
    if type(shl_input) is not ShareholderLoanModelInput:
        raise _Decline("SHL_INPUT_TYPE")
    if shl_input.day_count_convention is not ShlDayCountConvention.PERIOD_AXIS_ACTUAL_YEAR:
        raise _Decline("DAY_COUNT_CONVENTION")
    if type(shl_input.repayment_mode) is not ShlRepaymentMode:
        raise _Decline("REPAYMENT_MODE")
    mode = {ShlRepaymentMode.BULLET: 1, ShlRepaymentMode.CASH_SWEEP: 2}.get(shl_input.repayment_mode)
    if mode is None:
        raise _Decline("REPAYMENT_MODE")
    seen_operating = False
    for p in periods:
        if type(p.period_index) is not int or not -_I53 <= p.period_index <= _I53:
            raise _Decline("INT_NOT_REPRESENTABLE:period_index")
        if p.is_construction is True:
            if seen_operating:
                raise _Decline("CONSTRUCTION_NOT_PREFIX")
        elif p.is_construction is False:
            seen_operating = True
            if type(p.day_fraction) is not float:
                raise _Decline("DAY_FRACTION_TYPE")
        else:
            raise _Decline("IS_CONSTRUCTION_TYPE")
    for name in ("repayment_start_period_index", "maturity_period_index"):
        v = getattr(shl_input, name)
        if type(v) is not int or not -_I53 <= v <= _I53:
            raise _Decline(f"INT_NOT_REPRESENTABLE:{name}")
    for name in ("annual_fixed_rate", "convergence_tolerance_keur"):
        if type(getattr(shl_input, name)) is not float:
            raise _Decline(f"FLOAT_TYPE:{name}")
    return mode


def _template(periods, shl_input, diagnostics):
    """Static admission + cash-independent canonical evaluation + kernel plan, cached in the Run scope
    by object identity (both arguments are frozen dataclass values). A cached decline is re-raised."""
    from financial_engine import run_scope
    from financial_engine.shl import production
    scope = run_scope.current_run_scope()
    cache = None
    key = (id(periods), id(shl_input))
    if scope is not None:
        cache = scope.get(_TEMPLATE_KEY)
        if cache is None:
            cache = scope[_TEMPLATE_KEY] = collections.OrderedDict()
        hit = cache.get(key)
        if hit is not None and hit[0] is periods and hit[1] is shl_input:
            cache.move_to_end(key)
            if isinstance(hit[2], _Decline):
                raise _Decline(hit[2].reason)
            return hit[2]
    try:
        keep = _build_template(periods, shl_input, diagnostics, production)
    except _Decline as d:
        keep = d
    if cache is not None:
        cache[key] = (periods, shl_input, keep)
        while len(cache) > 64:
            cache.popitem(last=False)
    if isinstance(keep, _Decline):
        raise _Decline(keep.reason)
    return keep


def _build_template(periods, shl_input, diagnostics, production):
    mode = _static_admission(periods, shl_input)
    n = len(periods)
    token = _IN_TEMPLATE.set(True)
    try:
        tpl = production.compute_shareholder_loan_schedules(
            periods, shl_input, (0.0,) * n, diagnostics=diagnostics, enforce_maturity_residual=False,
            maturity_context=None)
        for p in periods:
            if not p.is_construction:
                production._shl_operating_accrual_start(p)     # static; may raise -> decline
    except Exception as exc:  # noqa: BLE001 - static canonical raise: decline, canonical replays it
        raise _Decline(f"TEMPLATE_RAISES:{type(exc).__name__}") from None
    finally:
        _IN_TEMPLATE.reset(token)
    n_con = sum(1 for p in periods if p.is_construction)
    idx = [p.period_index for p in periods]
    dcf = [p.day_fraction if not p.is_construction else 0.0 for p in periods]
    arrays = {"idx": (C.c_int64 * n)(*idx), "dcf": _darr(dcf),
              "t": [_darr(getattr(tpl, f)[:n_con]) for f in (
                  "shl_opening_keur", "shl_drawdown_keur", "shl_gross_interest_keur", "shl_cash_interest_keur",
                  "shl_pik_interest_keur", "shl_principal_keur", "shl_debt_service_keur", "shl_closing_keur")]}
    plan = ShlPlan(ABI, C.sizeof(ShlPlan), n, n_con, arrays["idx"], arrays["dcf"], *arrays["t"],
                   tpl.shl_opening_keur[n_con] if n_con < n else 0.0, shl_input.annual_fixed_rate,
                   shl_input.convergence_tolerance_keur, mode, shl_input.repayment_start_period_index,
                   shl_input.maturity_period_index)
    # the plan is read-only for the kernel; ``arrays`` keeps its buffers alive with it
    return {"n": n, "plan": plan, "arrays": arrays, "period_indices": tuple(idx)}


def shl_schedules(periods, shl_input, cash, *, diagnostics, enforce_maturity_residual, maturity_context):
    cfg = current_config()
    if cfg.mode != "candidate" or not cfg.stage2_experimental or _IN_TEMPLATE.get():
        return None
    stats = current_stats()
    try:
        return _serve(periods, shl_input, cash, diagnostics, enforce_maturity_residual, maturity_context, stats)
    except _Decline as d:
        if stats is not None:
            stats.declines[f"STAGE2:{d.reason}"] += 1
        return None
    except Exception as exc:  # noqa: BLE001 - admission helper raised: canonical decides
        if stats is not None:
            stats.declines[f"STAGE2:ADMISSION_EXCEPTION:{type(exc).__name__}:{str(exc)[:120]}"] += 1
        return None


def _serve(periods, shl_input, cash, diagnostics, enforce, maturity_context, stats):
    from financial_engine.results import ShareholderLoanSchedules
    from financial_engine.shl.maturity_authority import (ShlMaturityContext, ShlMaturityLedger,
                                                         ShlMaturityShortfall)
    got, reason = get_stage2()
    if got is None:
        raise _Decline(f"LOADER:{reason}")
    lib, build_id, stage1, auth = got
    if cfg_pin := current_config().require_build_id:
        if cfg_pin != stage1.build_id:
            raise _Decline("BUILD_ID_PIN_MISMATCH")
    if not auth.extra.still_intact():        # the SHL path executes only the Stage 2 region
        raise _Decline("CANONICAL_REGION_REPLACED")
    if type(cash) not in (tuple, list) or len(cash) != len(periods) or set(map(type, cash)) != _FLOAT_ONLY:
        raise _Decline("CASH_TYPE")
    if type(enforce) is not bool:
        raise _Decline("ENFORCE_TYPE")
    provisional = False
    if maturity_context is not None:
        if type(maturity_context) is not ShlMaturityContext:
            raise _Decline("MATURITY_CONTEXT_TYPE")
        provisional = maturity_context.provisional
        if provisional and type(maturity_context.ledger) is not ShlMaturityLedger:
            raise _Decline("MATURITY_LEDGER_TYPE")
    tpl = _template(periods, shl_input, diagnostics)
    n = tpl["n"]
    buf = (C.c_double * (10 * n))()
    base = C.addressof(buf)
    out = ShlOut(*[C.cast(base + 8 * n * k, D_P) for k in range(10)], 0, 0, 0.0)
    level = 0 if not enforce else (1 if provisional else 2)
    status = lib.fk2_shl_schedule(C.byref(tpl["plan"]), _darr(cash), n, C.byref(out), n, level)
    if status != 0:
        raise _Decline(f"KERNEL_STATUS_{status}")
    flat = memoryview(buf).cast("B").cast("d").tolist()   # native-endian binary64, exact bits
    vec = [tuple(flat[k * n:(k + 1) * n]) for k in range(10)]
    result = ShareholderLoanSchedules(
        period_indices=tpl["period_indices"], shl_opening_keur=vec[0], shl_drawdown_keur=vec[1],
        shl_gross_interest_keur=vec[2], shl_cash_interest_keur=vec[3], shl_pik_interest_keur=vec[4],
        shl_principal_keur=vec[5], shl_debt_service_keur=vec[6], shl_closing_keur=vec[7],
        cash_available_for_shl_before_reserves_keur=vec[8],
        cash_remaining_after_shl_before_reserves_keur=vec[9], diagnostics=diagnostics)
    if out.shortfall_count:
        # recorded only after the result object exists, so a decline can never double-record
        maturity_context.ledger.record(ShlMaturityShortfall(
            closing_keur=out.shortfall_closing, period_index=int(out.shortfall_period),
            tolerance_keur=shl_input.convergence_tolerance_keur))
    if stats is not None:
        stats.stage2_native_calls += 1
    return result
