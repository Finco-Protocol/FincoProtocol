"""Uncached cross-checkout V9 financial acceptance; no source rewriting or engine patching."""
from __future__ import annotations

import argparse
import dataclasses as dc
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import time


def cases():
    from app import project_factories as pf
    from dateutil.relativedelta import relativedelta
    from financial_engine.financing.generic_product_policy import GenericFinancingPolicy

    def scale(pi, factor):
        fields = {name: dc.replace(getattr(pi.capex, name),
                  amount_keur=getattr(pi.capex, name).amount_keur * factor)
                  for name in pi.capex._CAPEX_ITEM_FIELDS
                  if getattr(getattr(pi.capex, name), "amount_keur", 0)}
        return dc.replace(pi, capex=dc.replace(pi.capex, **fields))

    def fin(pi, **fields):
        return dc.replace(pi, financing=dc.replace(pi.financing, **fields))

    def loss(pi):
        return dc.replace(pi, opex=type(pi.opex)([
            dc.replace(item, y1_amount_keur=item.y1_amount_keur * 1.8) for item in pi.opex]))

    def leap(pi):
        fc = date(2028, 2, 29)
        return dc.replace(pi, info=dc.replace(pi.info, financial_close=fc,
                          cod_date=fc + relativedelta(months=pi.info.construction_months)))

    def s16(**fields):
        return scale(pf.create_default_solar_project(capacity_mw=16., **fields), .26)

    def s16r():
        return scale(pf.create_default_solar_project(capacity_mw=16.), .18)

    def wind(**fields):
        return pf.create_default_wind_project(capacity_mw=25., **fields)

    def windr():
        return scale(wind(), .7)

    entries = {"S16": (s16, "Solar", None), "W25": (wind, "Wind", None),
               "DC": (pf.create_default_data_center_project, "DataCenter", None),
               "S50": (pf.create_default_solar_project, "Solar", None)}
    for prefix, factory, vertical in (("S16", s16, "Solar"), ("W25", wind, "Wind")):
        for dscr in (1.45, 2., 3.):
            entries[f"{prefix}-dscr{dscr}"] = (
                lambda f=factory, d=dscr: fin(f(), target_dscr=d), vertical, None)
        for gearing in ((.5, .9) if prefix == "W25" else (.5,)):
            entries[f"{prefix}-gear{gearing:.2f}"] = (
                lambda f=factory, g=gearing: fin(f(), gearing_ratio=g), vertical, None)
        entries[f"{prefix}-dsra12"] = (lambda f=factory: fin(f(), dsra_months=12), vertical, None)
        entries[f"{prefix}-noCF"] = (factory, vertical, GenericFinancingPolicy(apply_construction_financing=False))
        entries[f"{prefix}-taxloss"] = (lambda f=factory: loss(f()), vertical, None)
    entries.update({
        "DC-dscr2.0": (lambda: fin(pf.create_default_data_center_project(), target_dscr=2.), "DataCenter", None),
        "S16-dsra0": (lambda: fin(s16(), dsra_months=0), "Solar", None),
        "W25-noDSRA": (wind, "Wind", GenericFinancingPolicy(apply_cash_dsra=False)),
        "S16-shl-small": (lambda: fin(s16(), share_capital_keur=4000.), "Solar", None),
        "S16-tenor10": (lambda: fin(s16(), senior_tenor_years=10), "Solar", None),
        "W25-tenor18": (lambda: fin(wind(), senior_tenor_years=18), "Wind", None),
        "S16-gear0": (lambda: fin(s16(), gearing_ratio=0.), "Solar", None),
        "S16-gear0.001": (lambda: fin(s16(), gearing_ratio=.001), "Solar", None),
        "S16-raw-infeasible": (lambda: pf.create_default_solar_project(capacity_mw=16.), "Solar", None),
        "S16-capex0.32-infeasible": (lambda: scale(pf.create_default_solar_project(capacity_mw=16.), .32), "Solar", None),
        "S16-gearbound": (lambda: scale(pf.create_default_solar_project(capacity_mw=16.), .24), "Solar", None),
        "W25-dscr9-infeasible": (lambda: fin(wind(), target_dscr=9.), "Wind", None),
        "S16-leap": (lambda: leap(s16()), "Solar", None),
        "S16-codstub9": (lambda: s16(construction_months=9), "Solar", None),
        "W25-codstub15": (lambda: wind(construction_months=15), "Wind", None),
        "DC-leap": (lambda: leap(pf.create_default_data_center_project()), "DataCenter", None),
        "S16r": (s16r, "Solar", None),
    })
    for prefix, factory, vertical, changes in (
        ("S16r", s16r, "Solar", {"dscr2.0": {"target_dscr": 2.}, "dscr3.0": {"target_dscr": 3.},
         "gear0.50": {"gearing_ratio": .5}, "tenor10": {"senior_tenor_years": 10},
         "tenor12": {"senior_tenor_years": 12}, "dsra12": {"dsra_months": 12}, "gear0.001": {"gearing_ratio": .001}}),
        ("W25r", windr, "Wind", {"dscr2.0": {"target_dscr": 2.}, "dscr3.0": {"target_dscr": 3.},
         "gear0.50": {"gearing_ratio": .5}, "tenor10": {"senior_tenor_years": 10}}),
    ):
        for suffix, fields in changes.items():
            entries[f"{prefix}-{suffix}"] = (lambda f=factory, k=fields: fin(f(), **k), vertical, None)
        entries[f"{prefix}-taxloss"] = (lambda f=factory: loss(f()), vertical, None)
    assert len(entries) == 49
    for kind, vertical in (("solar", "Solar"), ("wind", "Wind"),
                           ("data_center", "DataCenter"), ("ev_charging", "EVCharging")):
        entries[f"reference-{kind}"] = (getattr(pf, f"create_generic_{kind}_reference"), vertical, None)
    from finco_core.inputs import SponsorFundingMode
    entries["Solar-equity-only"] = (lambda: fin(pf.create_generic_solar_reference(),
        sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, shl_amount_keur=0.,
        clean_shl_principal_keur=0., dsra_months=0), "Solar", None)
    for name, gearing in (("EQ-DSRA", .7), ("EQ-zero", 0.), ("EQ-nearzero", 1e-12)):
        entries[name] = (lambda g=gearing: fin(pf.create_default_solar_project(),
            sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, shl_amount_keur=0.,
            clean_shl_principal_keur=0., dsra_months=6, gearing_ratio=g), "Solar", None)
    for target in (1.4, 1.6, 1.8, 2.2):
        entries[f"boundary-S16r-{target}"] = (lambda d=target: fin(s16r(), target_dscr=d), "Solar", None)
    for kind in ("solar", "wind"):
        entries[f"quarterly-{kind}"] = (lambda k=kind: quarterly_inputs(k), "QUARTERLY_TEST_ONLY", None)
    return entries


def quarterly_inputs(kind):
    from dateutil.relativedelta import relativedelta
    from app import project_factories as pf
    from finco_core.inputs import PeriodFrequency, SponsorFundingMode
    from finco_core.inputs._models import QuarterlyProjectInfo
    from finco_core.engine.calendar_policy import quarterly_candidate_policy_v2
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    cod = date(2031, 3, 31)
    months = pi.info.construction_months
    values = {field.name: getattr(pi.info, field.name) for field in dc.fields(pi.info)}
    values.update(financial_close=cod - relativedelta(months=months), cod_date=cod,
                  period_frequency=PeriodFrequency.QUARTERLY,
                  operating_calendar_policy=quarterly_candidate_policy_v2())
    info = QuarterlyProjectInfo(**values)
    return dc.replace(pi, info=info, financing=dc.replace(pi.financing,
        sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, shl_amount_keur=0.,
        clean_shl_principal_keur=0., dsra_months=0))


def flatten(value, path="", out=None):
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
            flatten(getattr(value, field.name), path + "." + field.name, out)
    elif isinstance(value, dict):
        out[path] = ["dict", len(value)]
        for key in sorted(value, key=repr):
            flatten(value[key], path + f"[{key!r}]", out)
    elif isinstance(value, (tuple, list, set, frozenset)):
        out[path] = [type(value).__name__, len(value)]
        sequence = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        for index, item in enumerate(sequence):
            flatten(item, path + f"[{index}]", out)
    elif hasattr(value, "__dict__"):
        out[path] = ["object", type(value).__qualname__]
        flatten(vars(value), path + ".__dict__", out)
    else:
        raise TypeError(f"Unsupported evidence leaf {path}: {type(value)}")
    return out


def digest(evidence):
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def peak_memory():
    if sys.platform != "win32":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "working", "paged_peak", "paged",
                                                "nonpaged_peak", "nonpaged", "pagefile", "pagefile_peak")]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not api(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(value.peak)


class Profile:
    def __init__(self):
        self.counts, self.seconds, self.starts = {}, {}, {}
        self.final_starts = {}
        self.labels = {"run_with_generic_financing_policy": "L1_policy",
                  "_run_with_construction_idc": "L2_IDC", "run_project_financing_model": "L3_G2A",
                  "_run_senior_debt_model_with_shl": "L4_SHL_tax", "solve_senior_debt": "L5_senior",
                  "run_senior_debt_model": "Senior_model",
                  "calculate_cfads_and_cash_tax": "tax_CFADS", "_finalise_authoritative": "final_verification",
                  "_require_settled_senior_maturity": "maturity_verification",
                  "assemble_decision_complete_financial_statements": "statements",
                  "run_stage_b2": "strict_StageB2", "run_stage_b2_provisional": "provisional_StageB2"}

    def __call__(self, frame, event, arg):
        name = frame.f_code.co_name
        label = self.labels.get(name)
        if not label:
            return
        if event == "call":
            self.counts[label] = self.counts.get(label, 0) + 1
            self.starts[id(frame)] = time.perf_counter()
            parent = frame.f_back
            if name == "run_project_financing_model" and parent is not None and parent.f_code.co_name == "_run_with_construction_idc" and "_verify_inputs" in parent.f_locals:
                self.counts["construction_final_verification_G2A"] = self.counts.get("construction_final_verification_G2A", 0) + 1
                self.final_starts[id(frame)] = time.perf_counter()
            if name == "run_senior_debt_model" and parent is not None and parent.f_code.co_name == "run_project_financing_model":
                policy = getattr(frame.f_locals.get("inputs"), "senior_debt_policy", None)
                mode = getattr(getattr(policy, "sizing_mode", None), "value", None)
                key = "capacity_passes" if mode == "DSCR_SCULPTED" else "funded_senior_passes"
                self.counts[key] = self.counts.get(key, 0) + 1
        elif event == "return":
            start = self.starts.pop(id(frame), None)
            if start is not None:
                self.seconds[label] = self.seconds.get(label, 0.) + time.perf_counter() - start
            final_start = self.final_starts.pop(id(frame), None)
            if final_start is not None:
                self.seconds["construction_final_verification_G2A"] = self.seconds.get("construction_final_verification_G2A", 0.) + time.perf_counter() - final_start
            if name == "_run_with_construction_idc":
                self.counts["construction_iterations"] = self.counts.get("construction_iterations", 0) + int(frame.f_locals.get("outer_iteration", 0))
            if name == "_run_senior_debt_model_with_shl":
                self.counts["SHL_tax_iterations"] = self.counts.get("SHL_tax_iterations", 0) + int(frame.f_locals.get("iteration", 0))
            if name == "run_project_financing_model":
                self.counts["SHL_senior_iterations"] = self.counts.get("SHL_senior_iterations", 0) + int(frame.f_locals.get("iteration", 0))
            if name == "run_with_generic_financing_policy":
                self.counts["DSRA_policy_iterations"] = self.counts.get("DSRA_policy_iterations", 0) + int(frame.f_locals.get("iteration", 0))


def run_case(name, mode="canonical", profile=False):
    from app.services import production_financial_authority as pfa
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    factory, vertical, policy = cases()[name]
    inputs = factory()
    input_digest = digest(flatten((inputs, policy)))
    pfa._POLICY_RUN_CACHE.clear()
    observer = Profile()
    start = time.perf_counter()
    details = {}
    if profile:
        sys.setprofile(observer)
    try:
        if vertical == "QUARTERLY_TEST_ONLY":
            result = quarterly_run(inputs)
            details = {"candidate_eligible": False, "reason": "QUARTERLY_CANONICAL_ONLY"}
        elif mode != "canonical":
            from financial_engine.financing.v9_candidate import evaluate_candidate
            result, details = evaluate_candidate(inputs, policy=policy, project_type=vertical,
                                                  verify_canonical=mode == "guarded")
        else:
            kwargs = {"financing_policy": policy} if policy is not None else {}
            result = pfa.run_clean_production(inputs, project_type=vertical, **kwargs)
    except Exception as error:
        details = getattr(error, "v9_candidate_evidence", details)
        status = "REJECTED"
        evidence = {"exception": type(error).__qualname__, "reason": getattr(error, "reason_code", None),
                    "text": str(error)}
    else:
        status = "FEASIBLE"
        evidence = None
    finally:
        seconds = time.perf_counter() - start
        if profile:
            sys.setprofile(None)
    if evidence is None:
        evidence = flatten(result)
        if vertical != "QUARTERLY_TEST_ONLY":
            evidence.update(flatten(run_integrity_checks(build_run_integrity_evidence(result)).to_dict(), ".integrity"))
    return {"status": status, "seconds": seconds, "digest": digest(evidence), "input_digest": input_digest, "leaves": len(evidence),
            "evidence": evidence, "counts": observer.counts, "inclusive_profile_seconds": observer.seconds,
            "candidate_evidence": details, "process_peak_bytes": peak_memory()}


def quarterly_run(inputs, runner=None):
    from types import SimpleNamespace
    from financial_engine.financing.generic_product_policy import run_with_generic_financing_policy
    from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
    from financial_engine.financial_statements import assemble_decision_complete_financial_statements
    from financial_engine.run_scope import engine_run_scope
    with engine_run_scope():
        g2c, applied, evidence = (runner or run_with_generic_financing_policy)(
            inputs, lambda value: run_project_shareholder_waterfall_model(value, source_id="v9_quarterly_isolated"))
    return SimpleResult(g2c, applied, assemble_decision_complete_financial_statements(g2c, applied), evidence)


@dc.dataclass
class SimpleResult:
    g2c_result: object
    project_inputs: object
    financial_statements_result: object
    policy_evidence: object


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--mode", choices=("canonical", "proposal", "guarded"), default="canonical")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--inputs-only", action="store_true")
    parser.add_argument("--warm-numerics", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    preparation = time.perf_counter()
    if args.warm_numerics:
        import numpy  # noqa: F401 - explicit identical worker preparation for both checkouts
    preparation = time.perf_counter() - preparation
    selected = args.cases or list(cases())
    source_paths = ("financial_engine/financing/project.py", "financial_engine/financing/v9_candidate.py",
                    "financial_engine/financing/v9_numerics.py", "financial_engine/shareholder_waterfall/model.py",
                    "app/services/production_financial_authority.py", "financial_engine/orchestrator.py",
                    "financial_engine/senior_debt/solver.py", "finco_core/engine/period_engine.py")
    report = {"source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo).decode().strip(),
              "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=args.repo)),
              "runtime_source_sha256": {name: hashlib.sha256((args.repo / name).read_bytes()).hexdigest()
                                        if (args.repo / name).exists() else None for name in source_paths},
              "numpy_preloaded_before_run": args.warm_numerics,
              "numeric_library_preparation_seconds": preparation,
              "environment": {"python": sys.version, "platform": platform.platform(),
                              "processor": platform.processor(), "logical_cpus": os.cpu_count(),
                              "numeric_thread_env": {name: os.environ.get(name) for name in
                                                     ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")}},
              "mode": args.mode, "profiled": args.profile, "results": {}}
    for name in selected:
        if args.inputs_only:
            factory, vertical, policy = cases()[name]
            report["results"][name] = {"input_digest": digest(flatten((factory(), policy))), "vertical": vertical}
            write(args.out, report)
            continue
        row = run_case(name, args.mode, args.profile)
        report["results"][name] = row
        write(args.out, report)
        print(name, row["status"], f"{row['seconds']:.4f}s", row["digest"], flush=True)


if __name__ == "__main__":
    main()
