"""Performance V4 discovery probe.

Engineering-only workflow helper. It changes no financial logic. It records:
- repeated benchmark samples,
- cProfile cumulative hotspots,
- exact complete-input duplicate ratios for tax / senior solve / forward roll / SHL.
"""
from __future__ import annotations

import cProfile
import dataclasses
import enum
import io
import json
import os
import pstats
import statistics
import sys
import time
from collections import Counter
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _canon(value):
    """Collision-free structural value for profiling exact economic identity."""
    if isinstance(value, float):
        return ("float", value.hex())
    if value is None or isinstance(value, (str, int, bool)):
        return (type(value).__name__, value)
    if isinstance(value, enum.Enum):
        return ("enum", value.__class__.__module__, value.__class__.__qualname__, value.value)
    if isinstance(value, (date, datetime)):
        return (type(value).__name__, value.isoformat())
    if dataclasses.is_dataclass(value):
        return (
            "dc", value.__class__.__module__, value.__class__.__qualname__,
            tuple((f.name, _canon(getattr(value, f.name))) for f in dataclasses.fields(value)),
        )
    if isinstance(value, dict):
        return ("dict", tuple(sorted((_canon(k), _canon(v)) for k, v in value.items())))
    if isinstance(value, (tuple, list)):
        return (type(value).__name__, tuple(_canon(v) for v in value))
    if isinstance(value, (set, frozenset)):
        return (type(value).__name__, tuple(sorted(_canon(v) for v in value)))
    return ("repr", value.__class__.__module__, value.__class__.__qualname__, repr(value))


def _opex_edit(pi, scale=1.10, lines=(0,)):
    items = [
        dataclasses.replace(it, y1_amount_keur=it.y1_amount_keur * scale)
        if i in lines else it
        for i, it in enumerate(pi.opex)
    ]
    return dataclasses.replace(pi, opex=type(pi.opex)(items))


class ExactTracker:
    def __init__(self):
        self.total = Counter()
        self.keys = {
            "tax": set(), "solve": set(), "forward": set(), "shl": set(),
        }
        self.period_keys = {}

    def period_key(self, periods):
        k = id(periods)
        entry = self.period_keys.get(k)
        if entry is not None and entry[0] is periods:
            return entry[1]
        value = _canon(periods)
        self.period_keys[k] = (periods, value)
        return value

    def add(self, name, key):
        self.total[name] += 1
        self.keys[name].add(key)

    def summary(self):
        out = {}
        for name in self.keys:
            total = self.total[name]
            unique = len(self.keys[name])
            out[name] = {
                "total": total,
                "unique": unique,
                "duplicates": total - unique,
                "duplicate_ratio": round((total - unique) / total, 6) if total else 0.0,
            }
        return out


def _instrument(tracker):
    import financial_engine.orchestrator as orch
    import financial_engine.senior_debt.solver as solver
    import financial_engine.tax.engine as tax
    import financial_engine.shl.production as shl

    originals = {}

    originals["tax"] = tax.calculate_cfads_and_cash_tax
    def tax_wrap(periods, tax_input):
        tracker.add("tax", (tracker.period_key(periods), _canon(tax_input)))
        return originals["tax"](periods, tax_input)
    tax.calculate_cfads_and_cash_tax = tax_wrap

    originals["factory"] = orch._make_solver_tax_cfads_fn
    def factory_wrap(**kwargs):
        fn = originals["factory"](**kwargs)
        static_key = (
            tracker.period_key(kwargs["periods"]),
            _canon(kwargs["base_tax_input"]),
            _canon(kwargs.get("shl_interest_by_period")),
            _canon(kwargs.get("limitation_by_period")),
            _canon(kwargs.get("tax_periodisation_mode_override")),
            _canon(kwargs.get("reset_candidate_components", False)),
        )
        setattr(fn, "_v4_context_key", static_key)
        return fn
    orch._make_solver_tax_cfads_fn = factory_wrap

    originals["solve"] = solver.solve_senior_debt
    def solve_wrap(*args, **kwargs):
        policy = kwargs.get("policy", args[0] if len(args) > 0 else None)
        inputs = kwargs.get("inputs", args[1] if len(args) > 1 else None)
        periods = kwargs.get("periods", args[2] if len(args) > 2 else ())
        tax_fn = kwargs.get("tax_cfads_fn", args[3] if len(args) > 3 else None)
        context = getattr(tax_fn, "_v4_context_key", ("callable-id", id(tax_fn)))
        tracker.add("solve", (_canon(policy), _canon(inputs), tracker.period_key(periods), context))
        return originals["solve"](*args, **kwargs)
    solver.solve_senior_debt = solve_wrap

    originals["forward_num"] = solver._forward_roll_numeric
    def forward_num_wrap(plan, D, cfads):
        tracker.add("forward", (_canon(plan), _canon(D), _canon(cfads)))
        return originals["forward_num"](plan, D, cfads)
    solver._forward_roll_numeric = forward_num_wrap

    originals["forward"] = solver._forward_roll
    def forward_wrap(*args, **kwargs):
        tracker.add("forward", (_canon(args), _canon(kwargs)))
        return originals["forward"](*args, **kwargs)
    solver._forward_roll = forward_wrap

    originals["shl"] = shl.compute_shareholder_loan_schedules
    def shl_wrap(periods, shl_input, cash_available_for_shl_before_reserves_keur, *args, **kwargs):
        tracker.add("shl", (
            tracker.period_key(periods), _canon(shl_input),
            _canon(tuple(cash_available_for_shl_before_reserves_keur)),
            _canon(args), _canon(kwargs),
        ))
        return originals["shl"](
            periods, shl_input, cash_available_for_shl_before_reserves_keur, *args, **kwargs
        )
    shl.compute_shareholder_loan_schedules = shl_wrap

    return originals


def _run_profile(label):
    from app import project_factories as pf
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa

    if label == "solar":
        project_type, base = "Solar", pf.create_default_solar_project()
    elif label == "wind":
        project_type, base = "Wind", pf.create_default_wind_project()
    else:
        raise ValueError(label)
    edited = _opex_edit(base)

    pfa._POLICY_RUN_CACHE.clear()
    tracker = ExactTracker()
    _instrument(tracker)

    profiler = cProfile.Profile()
    t0 = time.perf_counter()
    profiler.enable()
    run_project(project_type, "Base", project_inputs_override=edited)
    profiler.disable()
    elapsed = time.perf_counter() - t0

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative")
    stats.print_stats(80)
    return {
        "label": label,
        "elapsed_profiled_s": round(elapsed, 3),
        "duplicates": tracker.summary(),
        "profile": stream.getvalue(),
    }


def _bench_once(label):
    from app import project_factories as pf
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa

    factories = {
        "solar": ("Solar", pf.create_default_solar_project),
        "wind": ("Wind", pf.create_default_wind_project),
        "solar-ref": ("Solar", pf.create_generic_solar_reference),
        "wind-ref": ("Wind", pf.create_generic_wind_reference),
        "data-center": ("Data Center", pf.create_default_data_center_project),
        "ev-charging": ("EV Charging", pf.create_default_ev_charging_project),
    }
    project_type, factory = factories[label]
    base = factory()

    def one(pi, clear):
        if clear:
            pfa._POLICY_RUN_CACHE.clear()
        t0 = time.perf_counter()
        run_project(project_type, "Base", project_inputs_override=pi)
        return time.perf_counter() - t0

    return {
        "cold": one(base, True),
        "warm": one(base, True),
        "opex_one": one(_opex_edit(base), False) if label in {"solar", "wind"} else None,
        "opex_all": one(_opex_edit(base, 1.25, tuple(range(len(base.opex)))), False)
            if label == "solar" else None,
    }


def _benchmark(samples=3):
    labels = ["solar", "wind", "solar-ref", "wind-ref", "data-center", "ev-charging"]
    raw = {label: [] for label in labels}
    for _ in range(samples):
        for label in labels:
            raw[label].append(_bench_once(label))
    summary = {}
    for label, rows in raw.items():
        summary[label] = {}
        for metric in ("cold", "warm", "opex_one", "opex_all"):
            vals = [r[metric] for r in rows if r[metric] is not None]
            if vals:
                summary[label][metric] = {
                    "median_s": round(statistics.median(vals), 3),
                    "min_s": round(min(vals), 3),
                    "max_s": round(max(vals), 3),
                    "samples": len(vals),
                }
    return summary


def main():
    print("V4_ENV", json.dumps({
        "python": sys.version,
        "platform": sys.platform,
        "cpu_count": os.cpu_count(),
        "model_workers": os.getenv("FINCO_MODEL_WORKERS"),
    }, sort_keys=True))
    print("V4_BASELINE", json.dumps(_benchmark(), sort_keys=True))
    for label in ("solar", "wind"):
        result = _run_profile(label)
        print("V4_DUPLICATES", json.dumps({
            "label": label,
            "elapsed_profiled_s": result["elapsed_profiled_s"],
            "duplicates": result["duplicates"],
        }, sort_keys=True))
        print(f"V4_PROFILE_BEGIN {label}")
        print(result["profile"])
        print(f"V4_PROFILE_END {label}")


if __name__ == "__main__":
    main()
