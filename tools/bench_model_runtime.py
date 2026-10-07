"""Reproducible benchmark of ONE canonical interactive Model Run.

Reports, per project, in a fresh interpreter each time:

* ``cold``       first Run in the process (imports + first-call costs included),
* ``warm``       the same inputs again with the process-level policy memo cleared,
* ``memo_hit``   the same inputs again with the memo left in place (the identical re-run),
* ``opex_one``   one OPEX line edited +10 % (the typical interactive edit),
* ``opex_all``   every OPEX line edited +25 %,

plus how the time splits between the financial engine and everything around it, and the
*actual* number of calls and fixed-point iterations one Run executes (not the configured
ceilings), taken from a separate instrumented run so instrumentation never distorts timings.

Not part of CI (wall-clock depends on the machine). Correctness is pinned by
tests/test_perf_model_runtime_equivalence.py; this tool only measures.

    python tools/bench_model_runtime.py                     # table
    python tools/bench_model_runtime.py --json out.json     # also write structured output
    python tools/bench_model_runtime.py --only solar        # solar | wind | solar-ref | wind-ref
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import subprocess
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCENARIOS = {
    "solar": ("Solar", "create_default_solar_project"),
    "wind": ("Wind", "create_default_wind_project"),
    "solar-ref": ("Generic Solar Reference", "create_generic_solar_reference"),
    "wind-ref": ("Generic Wind Reference", "create_generic_wind_reference"),
}

# (module, attribute, label): wrapped only in the instrumented run.
COUNTED = (
    ("financial_engine.shareholder_waterfall", "run_project_shareholder_waterfall_model", "g2c_engine_evaluations"),
    ("financial_engine.shareholder_waterfall.model", "run_project_financing_model", "financing_model_runs_by_waterfall"),
    ("financial_engine.financing.project", "run_project_financing_model", "financing_model_runs_total"),
    ("financial_engine.orchestrator", "run_senior_debt_model", "senior_debt_model_runs"),
    ("financial_engine.senior_debt.solver", "solve_senior_debt", "solve_senior_debt_calls"),
    ("financial_engine.senior_debt.solver", "_finalise_authoritative", "senior_finalisation_calls"),
    ("financial_engine.senior_debt.solver", "_forward_roll", "forward_rolls"),
    ("financial_engine.tax.engine", "calculate_tax", "tax_full_evaluations"),
    ("financial_engine.tax.engine", "calculate_cfads_and_cash_tax", "tax_solver_evaluations"),
    ("financial_engine.shl.production", "compute_shareholder_loan_schedules", "shl_schedule_computations"),
    ("financial_engine.orchestrator", "run_operating_model", "operating_model_calls"),
    ("financial_engine.orchestrator", "run_tax_cfads_model", "tax_cfads_model_calls"),
    ("financial_engine.financial_statements", "assemble_decision_complete_financial_statements", "fs_assemblies"),
)


def _opex_edit(pi, scale: float, lines=None):
    items = [
        dataclasses.replace(it, y1_amount_keur=it.y1_amount_keur * scale)
        if (lines is None or i in lines) else it
        for i, it in enumerate(pi.opex)
    ]
    return dataclasses.replace(pi, opex=type(pi.opex)(items))


def _child(label: str) -> dict:
    project_type, factory_name = SCENARIOS[label]
    t = time.perf_counter()
    from app import project_factories as pf
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    import_s = time.perf_counter() - t

    spent = {"engine": 0.0}
    real_clean = pfa.run_clean_production

    def timed_clean(*a, **k):
        t0 = time.perf_counter()
        try:
            return real_clean(*a, **k)
        finally:
            spent["engine"] += time.perf_counter() - t0

    pfa.run_clean_production = timed_clean  # the product imports it from this module at call time

    def one(pi, *, clear_memo: bool) -> dict:
        if clear_memo:
            pfa._POLICY_RUN_CACHE.clear()
        spent["engine"] = 0.0
        t0 = time.perf_counter()
        run_project(project_type, "Base", project_inputs_override=pi)
        total = time.perf_counter() - t0
        return {"total_s": round(total, 3), "engine_s": round(spent["engine"], 3),
                "outside_engine_s": round(total - spent["engine"], 3)}

    base = getattr(pf, factory_name)()
    out = {"label": label, "project_type": project_type, "import_s": round(import_s, 3)}
    out["cold"] = one(base, clear_memo=True)
    out["warm"] = one(base, clear_memo=True)
    out["memo_hit"] = one(base, clear_memo=False)
    out["opex_one"] = one(_opex_edit(base, 1.10, lines=[0]), clear_memo=False)
    out["opex_all"] = one(_opex_edit(base, 1.25), clear_memo=False)
    out["counts"] = _counts(base, project_type, pfa, real_clean)
    return out


def _counts(base, project_type: str, pfa, real_clean) -> dict:
    pfa.run_clean_production = real_clean
    counts: Counter = Counter()
    for module_name, attr, key in COUNTED:
        module = importlib.import_module(module_name)
        original = getattr(module, attr, None)
        if original is None:
            continue

        def make(fn, key):
            def wrapper(*a, **k):
                counts[key] += 1
                return fn(*a, **k)
            return wrapper

        setattr(module, attr, make(original, key))

    evidence = {}
    policy = importlib.import_module("financial_engine.financing.generic_product_policy")
    real_policy = policy.run_with_generic_financing_policy

    def policy_wrapper(*a, **k):
        result, applied, ev = real_policy(*a, **k)
        evidence["dsra_iterations"] = ev.dsra_iterations
        return result, applied, ev

    policy.run_with_generic_financing_policy = policy_wrapper
    pfa._POLICY_RUN_CACHE.clear()
    run = real_clean(base, project_type=project_type)

    model = run.g2c_result.financing_result.project_model_result
    out = dict(counts)
    out["dsra_fixed_point_iterations"] = evidence.get("dsra_iterations")
    senior = getattr(model, "senior_debt", None)
    if senior is not None:
        out["senior_solver_iterations_final"] = senior.diagnostics.get("iteration_count") \
            if isinstance(senior.diagnostics, dict) else getattr(senior.diagnostics, "iteration_count", None)
    shl = getattr(model, "shareholder_loan", None)
    if shl is not None:
        out["shl_tax_feedback_iterations_final"] = getattr(shl.diagnostics, "iteration_count", None)
    return out


def _run_child(label: str) -> dict:
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--child", label],
        capture_output=True, text=True, cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{label}: benchmark child failed\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _table(results: list[dict]) -> str:
    cols = ("cold", "warm", "memo_hit", "opex_one", "opex_all")
    lines = [f"{'':26s}" + "".join(f"{c:>11s}" for c in cols) + f"{'import':>9s}"]
    for r in results:
        lines.append(f"{r['label']:26s}" + "".join(f"{r[c]['total_s']:10.2f}s" for c in cols)
                     + f"{r['import_s']:8.2f}s")
    lines.append("")
    lines.append("outside the engine (tables, adapter, serialisation) on the cold run: "
                 + ", ".join(f"{r['label']} {r['cold']['outside_engine_s']:.2f}s" for r in results))
    lines.append("")
    keys = sorted({k for r in results for k in r["counts"]})
    lines.append(f"{'actual counts per Run':44s}" + "".join(f"{r['label']:>12s}" for r in results))
    for k in keys:
        lines.append(f"{k:44s}" + "".join(f"{str(r['counts'].get(k, '-')):>12s}" for r in results))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--only", choices=sorted(SCENARIOS))
    parser.add_argument("--json", help="also write structured results to this path")
    args = parser.parse_args()
    if args.child:
        print(json.dumps(_child(args.child)))
        return
    labels = [args.only] if args.only else list(SCENARIOS)
    results = [_run_child(label) for label in labels]
    print(_table(results))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"python": sys.version.split()[0], "results": results}, handle, indent=2)


if __name__ == "__main__":
    main()
