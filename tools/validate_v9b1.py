"""Uncached V9-B1 cross-checkout validation; no engine replacement or source compilation."""
from __future__ import annotations

import argparse
import ctypes
import dataclasses as dc
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time


def cases(*, include_extended=False):
    from app import project_factories as pf
    from dateutil.relativedelta import relativedelta
    from financial_engine.financing.generic_product_policy import GenericFinancingPolicy

    def scale(pi, k):
        changes = {name: dc.replace(getattr(pi.capex, name),
                       amount_keur=getattr(pi.capex, name).amount_keur * k)
                   for name in pi.capex._CAPEX_ITEM_FIELDS
                   if getattr(getattr(pi.capex, name), "amount_keur", 0)}
        return dc.replace(pi, capex=dc.replace(pi.capex, **changes))

    def fin(pi, **kw):
        return dc.replace(pi, financing=dc.replace(pi.financing, **kw))

    def opex(pi):
        return dc.replace(pi, opex=type(pi.opex)([
            dc.replace(item, y1_amount_keur=item.y1_amount_keur * 1.8) for item in pi.opex]))

    def leap(pi):
        fc = date(2028, 2, 29)
        return dc.replace(pi, info=dc.replace(pi.info, financial_close=fc,
            cod_date=fc + relativedelta(months=pi.info.construction_months)))

    def s16(**kw):
        return scale(pf.create_default_solar_project(capacity_mw=16., **kw), .26)

    def s16r():
        return scale(pf.create_default_solar_project(capacity_mw=16.), .18)

    def w25(**kw):
        return pf.create_default_wind_project(capacity_mw=25., **kw)

    def w25r():
        return scale(w25(), .7)

    dc_factory = pf.create_default_data_center_project
    entries = {
        "S16": (s16, "Solar", None), "W25": (w25, "Wind", None),
        "DC": (dc_factory, "DataCenter", None),
        "S50": (pf.create_default_solar_project, "Solar", None),
    }
    for prefix, factory, vertical in (("S16", s16, "Solar"), ("W25", w25, "Wind")):
        for dscr in (1.45, 2., 3.):
            entries[f"{prefix}-dscr{dscr}"] = (
                lambda f=factory, d=dscr: fin(f(), target_dscr=d), vertical, None)
        for gearing in (.5, .9) if prefix == "W25" else (.5,):
            entries[f"{prefix}-gear{gearing:.2f}"] = (
                lambda f=factory, g=gearing: fin(f(), gearing_ratio=g), vertical, None)
        entries[f"{prefix}-dsra12"] = (lambda f=factory: fin(f(), dsra_months=12), vertical, None)
        entries[f"{prefix}-noCF"] = (factory, vertical, GenericFinancingPolicy(apply_construction_financing=False))
        entries[f"{prefix}-taxloss"] = (lambda f=factory: opex(f()), vertical, None)
    entries.update({
        "DC-dscr2.0": (lambda: fin(dc_factory(), target_dscr=2.), "DataCenter", None),
        "S16-dsra0": (lambda: fin(s16(), dsra_months=0), "Solar", None),
        "W25-noDSRA": (w25, "Wind", GenericFinancingPolicy(apply_cash_dsra=False)),
        "S16-shl-small": (lambda: fin(s16(), share_capital_keur=4000.), "Solar", None),
        "S16-tenor10": (lambda: fin(s16(), senior_tenor_years=10), "Solar", None),
        "W25-tenor18": (lambda: fin(w25(), senior_tenor_years=18), "Wind", None),
        "S16-gear0": (lambda: fin(s16(), gearing_ratio=0.), "Solar", None),
        "S16-gear0.001": (lambda: fin(s16(), gearing_ratio=.001), "Solar", None),
        "S16-raw-infeasible": (lambda: pf.create_default_solar_project(capacity_mw=16.), "Solar", None),
        "S16-capex0.32-infeasible": (lambda: scale(pf.create_default_solar_project(capacity_mw=16.), .32), "Solar", None),
        "S16-gearbound": (lambda: scale(pf.create_default_solar_project(capacity_mw=16.), .24), "Solar", None),
        "W25-dscr9-infeasible": (lambda: fin(w25(), target_dscr=9.), "Wind", None),
        "S16-leap": (lambda: leap(s16()), "Solar", None),
        "S16-codstub9": (lambda: s16(construction_months=9), "Solar", None),
        "W25-codstub15": (lambda: w25(construction_months=15), "Wind", None),
        "DC-leap": (lambda: leap(dc_factory()), "DataCenter", None),
        "S16r": (s16r, "Solar", None),
    })
    for prefix, factory, vertical, modifications in (
        ("S16r", s16r, "Solar", {"dscr2.0": {"target_dscr": 2.}, "dscr3.0": {"target_dscr": 3.},
            "gear0.50": {"gearing_ratio": .5}, "tenor10": {"senior_tenor_years": 10},
            "tenor12": {"senior_tenor_years": 12}, "dsra12": {"dsra_months": 12},
            "gear0.001": {"gearing_ratio": .001}}),
        ("W25r", w25r, "Wind", {"dscr2.0": {"target_dscr": 2.}, "dscr3.0": {"target_dscr": 3.},
            "gear0.50": {"gearing_ratio": .5}, "tenor10": {"senior_tenor_years": 10}}),
    ):
        for suffix, kw in modifications.items():
            entries[f"{prefix}-{suffix}"] = (lambda f=factory, k=kw: fin(f(), **k), vertical, None)
        entries[f"{prefix}-taxloss"] = (lambda f=factory: opex(f()), vertical, None)
    assert len(entries) == 49
    if include_extended:
        from finco_core.inputs import DebtSizingMode, GearingBasisMode, GearingCapRepaymentMethod
        for kind, vertical in (("solar", "Solar"), ("wind", "Wind"),
                               ("data_center", "DataCenter"), ("ev_charging", "EVCharging")):
            entries[f"reference-{kind}"] = (getattr(pf, f"create_generic_{kind}_reference"), vertical, None)
        for name, method, gearing, dscr in (
            ("m6-level", GearingCapRepaymentMethod.LEVEL_PRINCIPAL, .95, 1.6),
            ("m6-sculpted", GearingCapRepaymentMethod.DSCR_SCULPTED, .95, 1.6),
            ("m6-infeasible", GearingCapRepaymentMethod.DSCR_SCULPTED, .9, 2.5),
        ):
            entries[name] = (lambda m=method, g=gearing, d=dscr: fin(
                pf.create_generic_solar_reference(), debt_sizing_mode=DebtSizingMode.GEARING_CAP,
                gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
                gearing_cap_repayment_method=m, gearing_ratio=g, target_dscr=d), "Solar", None)
    return entries


def flatten(value, path="", out=None):
    """Lossless leaves: IEEE bytes, types, structure; no diagnostic exclusions."""
    if out is None:
        out = {}
    if isinstance(value, Enum):
        out[path] = [type(value).__qualname__, value.name]
    elif isinstance(value, float):
        out[path] = ["float64", struct.pack(">d", value).hex()]
    elif value is None or isinstance(value, (str, bool, int)):
        out[path] = [type(value).__name__, value]
    elif isinstance(value, (date, datetime, Decimal)):
        out[path] = [type(value).__name__, str(value)]
    elif dc.is_dataclass(value):
        out[path] = ["dataclass", type(value).__qualname__]
        for field in dc.fields(value):
            flatten(getattr(value, field.name), f"{path}.{field.name}", out)
    elif isinstance(value, dict):
        out[path] = ["dict", len(value)]
        for key in sorted(value, key=repr):
            flatten(value[key], f"{path}[{key!r}]", out)
    elif isinstance(value, (list, tuple, set, frozenset)):
        out[path] = [type(value).__name__, len(value)]
        seq = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        for index, item in enumerate(seq):
            flatten(item, f"{path}[{index}]", out)
    elif hasattr(value, "__dict__"):
        out[path] = ["object", type(value).__qualname__]
        flatten(vars(value), path + ".__dict__", out)
    else:
        raise TypeError(f"Unrepresented result leaf: {path}: {type(value)}")
    return out


def run_case(name, *, profile=False):
    from app.services import production_financial_authority as pfa
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    factory, vertical, policy = cases(include_extended=True)[name]
    inputs = factory()
    pfa._POLICY_RUN_CACHE.clear()
    counts = {name: 0 for name in ("run_senior_debt_model", "_run_senior_debt_model_with_shl",
        "solve_senior_debt", "calculate_cfads_and_cash_tax", "run_project_financing_model",
        "capacity_passes", "funded_senior_passes", "g2a_iterations", "canonical_fallbacks")} if profile else {}

    def observe(frame, event, arg):
        if event != "call":
            return
        name = frame.f_code.co_name
        if name in {"run_senior_debt_model", "_run_senior_debt_model_with_shl", "solve_senior_debt",
                    "calculate_cfads_and_cash_tax", "run_project_financing_model"}:
            counts[name] = counts.get(name, 0) + 1
        if name == "run_senior_debt_model" and frame.f_back.f_code.co_name in {
            "run_project_financing_model", "_run_shl_senior_fixed_point"
        }:
            mode = frame.f_locals["inputs"].senior_debt_policy.sizing_mode.value
            key = "capacity_passes" if mode == "DSCR_SCULPTED" else "funded_senior_passes"
            counts[key] = counts.get(key, 0) + 1
        if name == "reconcile_financing_stack" and frame.f_back.f_code.co_name in {
            "run_project_financing_model", "_run_shl_senior_fixed_point"
        }:
            counts["g2a_iterations"] = counts.get("g2a_iterations", 0) + 1
        if name == "_run_shl_senior_fixed_point" and not frame.f_locals["defer_capacity"]:
            counts["canonical_fallbacks"] = counts.get("canonical_fallbacks", 0) + 1

    started = time.perf_counter()
    if profile:
        sys.setprofile(observe)
    try:
        kwargs = {"financing_policy": policy} if policy is not None else {}
        result = pfa.run_clean_production(inputs, project_type=vertical, **kwargs)
    except pfa.CleanProductionRunUnavailable as error:
        duration = time.perf_counter() - started
        if profile:
            sys.setprofile(None)
        evidence = {"exception": type(error).__qualname__, "reason": error.reason_code, "text": str(error)}
        status = "rejected"
    else:
        duration = time.perf_counter() - started
        if profile:
            sys.setprofile(None)
        evidence = flatten(result)
        evidence.update(flatten(run_integrity_checks(build_run_integrity_evidence(result)).to_dict(), ".integrity"))
        status = "feasible"
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"status": status, "seconds": duration, "digest": hashlib.sha256(payload).hexdigest(),
            "leaves": len(evidence), "counts": counts, "peak_working_set_bytes": peak_memory(),
            "evidence": evidence}


def peak_memory():
    """OS process peak, including imports/result serialization; not a Run-only delta."""
    if sys.platform != "win32":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    names = args.cases or sorted(cases())
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip(),
              "working_project_blob": subprocess.check_output([
                  "git", "hash-object", "--no-filters", "financial_engine/financing/project.py"],
                  cwd=args.repo, text=True).strip(),
              "python": sys.version, "results": {}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for name in names:
        row = run_case(name, profile=args.profile)
        report["results"][name] = row
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{name}: {row['status']} {row['seconds']:.3f}s {row['digest']}", flush=True)


if __name__ == "__main__":
    main()
