from __future__ import annotations

import argparse
import cProfile
import dataclasses
import io
import json
import multiprocessing
import os
import platform
import pstats
import statistics
import sys
import time
from collections import Counter
from datetime import date, datetime
from enum import Enum

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _freeze(value):
    if value is None or isinstance(value, (str, int, bool, bytes)):
        return value
    if isinstance(value, float):
        return ("float", value.hex())
    if isinstance(value, Enum):
        return (type(value).__module__, type(value).__qualname__, value.value)
    if isinstance(value, (date, datetime)):
        return (type(value).__name__, value.isoformat())
    if dataclasses.is_dataclass(value):
        return (
            type(value).__module__, type(value).__qualname__,
            tuple((f.name, _freeze(getattr(value, f.name))) for f in dataclasses.fields(value)),
        )
    if isinstance(value, dict):
        return tuple(sorted((_freeze(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(_freeze(v) for v in value))
    if hasattr(value, "__dict__"):
        return (type(value).__module__, type(value).__qualname__, _freeze(vars(value)))
    return (type(value).__module__, type(value).__qualname__, repr(value))

def _opex_edit(pi, scale: float, lines=None):
    items = [
        dataclasses.replace(it, y1_amount_keur=it.y1_amount_keur * scale)
        if (lines is None or i in lines) else it
        for i, it in enumerate(pi.opex)
    ]
    return dataclasses.replace(pi, opex=type(pi.opex)(items))

def _load_factory(name):
    from app import project_factories as pf
    return getattr(pf, name)

SCENARIOS = {
    "solar": ("Solar", "create_default_solar_project"),
    "wind": ("Wind", "create_default_wind_project"),
    "solar-ref": ("Generic Solar Reference", "create_generic_solar_reference"),
    "wind-ref": ("Generic Wind Reference", "create_generic_wind_reference"),
    "data-center": ("Data Center", "create_default_data_center_project"),
    "ev-charging": ("EV Charging", "create_default_ev_charging_project"),
}

def _timed_run(project_type, pi, *, clear_memo):
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    if clear_memo:
        pfa._POLICY_RUN_CACHE.clear()
    t0 = time.perf_counter()
    run_project(project_type, "Base", project_inputs_override=pi)
    return time.perf_counter() - t0

def _benchmark_one(label: str, repeats: int):
    project_type, factory_name = SCENARIOS[label]
    base = _load_factory(factory_name)()
    one_edit = _opex_edit(base, 1.10, lines=[0]) if hasattr(base, "opex") and len(base.opex) else base
    all_edit = _opex_edit(base, 1.25) if hasattr(base, "opex") and len(base.opex) else base
    out = {"label": label, "project_type": project_type, "samples": {}}
    out["samples"]["cold"] = [_timed_run(project_type, base, clear_memo=True)]
    modes = [("warm", base), ("opex_one", one_edit)]
    if label == "solar":
        modes.append(("opex_all", all_edit))
    for mode, pi in modes:
        samples = []
        for _ in range(repeats):
            samples.append(_timed_run(project_type, pi, clear_memo=True))
        out["samples"][mode] = samples
    for mode, samples in out["samples"].items():
        out[mode] = {
            "median_s": statistics.median(samples),
            "min_s": min(samples),
            "max_s": max(samples),
        }
    return out

def _counter_bucket():
    return {"total": 0, "keys": Counter(), "key_build_s": 0.0}

def _record(bucket, key):
    bucket["total"] += 1
    bucket["keys"][key] += 1

def _summarise_bucket(bucket):
    unique = len(bucket["keys"])
    total = bucket["total"]
    duplicate = total - unique
    return {
        "total": total,
        "unique": unique,
        "duplicates": duplicate,
        "duplicate_ratio": (duplicate / total) if total else 0.0,
        "max_multiplicity": max(bucket["keys"].values()) if bucket["keys"] else 0,
        "key_build_s": bucket["key_build_s"],
    }

def _instrumented_run(label: str):
    project_type, factory_name = SCENARIOS[label]
    base = _load_factory(factory_name)()
    pi = _opex_edit(base, 1.10, lines=[0]) if hasattr(base, "opex") and len(base.opex) else base

    import dataclasses as dc
    import financial_engine.orchestrator as orch
    import financial_engine.senior_debt.solver as solver
    import financial_engine.tax.engine as tax_engine
    import financial_engine.shl.production as shl_prod
    from app.services import production_financial_authority as pfa

    buckets = {
        "tax": _counter_bucket(),
        "senior_solve": _counter_bucket(),
        "roll_numeric": _counter_bucket(),
        "roll_full": _counter_bucket(),
        "shl": _counter_bucket(),
    }
    constructions = Counter()

    originals = {
        "replace": dc.replace,
        "make_tax": orch._make_solver_tax_cfads_fn,
        "tax": tax_engine.calculate_cfads_and_cash_tax,
        "solve": solver.solve_senior_debt,
        "roll_numeric": solver._forward_roll_numeric,
        "roll_full": solver._forward_roll,
        "authentic_roll": solver._AUTHENTIC_FORWARD_ROLL,
        "shl": shl_prod.compute_shareholder_loan_schedules,
    }

    def counted_replace(obj, /, **changes):
        name = type(obj).__name__
        if name in ("PeriodInterestInput", "TaxCalculationInput"):
            constructions[name + "_replace"] += 1
        return originals["replace"](obj, **changes)

    def make_tax_wrapper(*args, **kwargs):
        fn = originals["make_tax"](*args, **kwargs)
        context = (
            _freeze(kwargs.get("periods")),
            _freeze(kwargs.get("base_tax_input")),
            _freeze(kwargs.get("shl_interest_by_period")),
            _freeze(kwargs.get("limitation_by_period")),
            _freeze(kwargs.get("tax_periodisation_mode_override")),
            _freeze(kwargs.get("reset_candidate_components")),
        )
        setattr(fn, "__finco_profile_context__", context)
        return fn

    def tax_wrapper(periods, tax_input):
        t0 = time.perf_counter()
        key = (_freeze(periods), _freeze(tax_input))
        buckets["tax"]["key_build_s"] += time.perf_counter() - t0
        _record(buckets["tax"], key)
        return originals["tax"](periods, tax_input)

    def solve_wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        tax_fn = kwargs.get("tax_cfads_fn")
        ctx = getattr(tax_fn, "__finco_profile_context__", ("opaque", id(tax_fn)))
        key = (
            _freeze(kwargs.get("policy")),
            _freeze(kwargs.get("inputs")),
            _freeze(kwargs.get("periods")),
            ctx,
        )
        buckets["senior_solve"]["key_build_s"] += time.perf_counter() - t0
        _record(buckets["senior_solve"], key)
        return originals["solve"](*args, **kwargs)

    def roll_numeric_wrapper(plan, opening, cfads):
        t0 = time.perf_counter()
        key = (_freeze(plan), _freeze(opening), _freeze(cfads))
        buckets["roll_numeric"]["key_build_s"] += time.perf_counter() - t0
        _record(buckets["roll_numeric"], key)
        return originals["roll_numeric"](plan, opening, cfads)

    def roll_full_wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        key = (_freeze(args), _freeze(kwargs))
        buckets["roll_full"]["key_build_s"] += time.perf_counter() - t0
        _record(buckets["roll_full"], key)
        return originals["roll_full"](*args, **kwargs)

    def shl_wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        key = (
            _freeze(args[:3]),
            _freeze(kwargs.get("enforce_maturity_residual", True)),
        )
        buckets["shl"]["key_build_s"] += time.perf_counter() - t0
        _record(buckets["shl"], key)
        return originals["shl"](*args, **kwargs)

    dc.replace = counted_replace
    orch._make_solver_tax_cfads_fn = make_tax_wrapper
    tax_engine.calculate_cfads_and_cash_tax = tax_wrapper
    solver.solve_senior_debt = solve_wrapper
    solver._forward_roll_numeric = roll_numeric_wrapper
    solver._forward_roll = roll_full_wrapper
    solver._AUTHENTIC_FORWARD_ROLL = roll_full_wrapper
    shl_prod.compute_shareholder_loan_schedules = shl_wrapper
    try:
        pfa._POLICY_RUN_CACHE.clear()
        _timed_run(project_type, pi, clear_memo=True)
    finally:
        dc.replace = originals["replace"]
        orch._make_solver_tax_cfads_fn = originals["make_tax"]
        tax_engine.calculate_cfads_and_cash_tax = originals["tax"]
        solver.solve_senior_debt = originals["solve"]
        solver._forward_roll_numeric = originals["roll_numeric"]
        solver._forward_roll = originals["roll_full"]
        solver._AUTHENTIC_FORWARD_ROLL = originals["authentic_roll"]
        shl_prod.compute_shareholder_loan_schedules = originals["shl"]

    return {
        "buckets": {k: _summarise_bucket(v) for k, v in buckets.items()},
        "constructions": dict(constructions),
    }

def _profile_run(label: str):
    project_type, factory_name = SCENARIOS[label]
    base = _load_factory(factory_name)()
    pi = _opex_edit(base, 1.10, lines=[0]) if hasattr(base, "opex") and len(base.opex) else base
    from app.services import production_financial_authority as pfa
    pfa._POLICY_RUN_CACHE.clear()
    prof = cProfile.Profile()
    prof.enable()
    _timed_run(project_type, pi, clear_memo=True)
    prof.disable()
    buf = io.StringIO()
    pstats.Stats(prof, stream=buf).strip_dirs().sort_stats("cumulative").print_stats(100)
    return buf.getvalue()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", choices=list(SCENARIOS))
    args = parser.parse_args()
    print("ENV " + json.dumps({
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "mp_start_method": multiprocessing.get_start_method(allow_none=True),
        "FINCO_MODEL_WORKERS": os.getenv("FINCO_MODEL_WORKERS"),
    }, sort_keys=True))
    labels = [args.only] if args.only else list(SCENARIOS)
    benches = [_benchmark_one(label, args.repeats) for label in labels]
    print("BASELINE_JSON " + json.dumps(benches, sort_keys=True))
    for label in ("solar", "wind"):
        if args.only and args.only != label:
            continue
        print(f"PROFILE_BEGIN {label}")
        print(_profile_run(label))
        print(f"PROFILE_END {label}")
        dup = _instrumented_run(label)
        print(f"DUPLICATE_JSON {label} " + json.dumps(dup, sort_keys=True))

if __name__ == "__main__":
    main()
