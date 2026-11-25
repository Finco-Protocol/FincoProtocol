"""FINCO43 — complete-object financial equivalence recorder (baseline tree vs candidate tree).

Unlike ``tools/model_runtime_parity.py`` (which fingerprints a selected subset of the G2C / statements payload), this
walks the ENTIRE ``CleanProductionRun`` object graph returned by ``run_clean_production`` — every dataclass field,
slot, mapping and sequence, including the financing / project model results and the Senior solver diagnostics
(``maximum_absolute_difference_keur``, iteration counts, termination reasons) — and emits one canonical line per
leaf: floats as ``float.hex()`` (exact IEEE representation, signed zero and NaN payload class preserved), dates ISO,
enums by class + name, Decimal by ``str``. Array order is preserved; mapping keys are emitted in insertion order
AND checked in sorted order, so a key-order change is also visible. Nothing financial is rounded or normalised.

Only the explicitly enumerated ``EXCLUDED_KEYS`` (wall-clock / request metadata, none of them financial) are
skipped; the list is printed in every record. Fail-closed scenarios record the exception type and full message,
so the rejection class AND its first-failure detail must match.

    python tools/finco43_equivalence.py --tree /path/to/baseline --record base.json
    python tools/finco43_equivalence.py --tree .                 --record cand.json
    python tools/finco43_equivalence.py --diff base.json cand.json

Scenarios: the 17 ``model_runtime_parity`` scenarios (Solar/Wind/DC/EV, OPEX edit, ATAD, SHL deductibility, LCF,
alt tax rate, gearing low/high, lock-up, DSCR-infeasible rejection) + the 8 explicit dated OD-TIME-01/R04
Solar/Wind cases admitted by #482 + a maturity rejection witness and a high-DSCR stress case. Every Senior solver
return during the Run (~280 intermediate solves) is also digested in call order (``solver_trace_sha256``). Canonical Python (native OFF, the
production default). Run each tree in a fresh interpreter on the same Python.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import decimal
import enum
import hashlib
import json
import os
import sys
from typing import Any

EXCLUDED_KEYS = frozenset({
    # wall-clock / request metadata only (never financial)
    "duration_s", "elapsed_s", "timestamp", "generated_at", "created_at", "ran_at", "request_id",
    "wall_time_s", "computed_at",
})


def _emit(obj: Any, path: str, out: list[str], seen: set[int]) -> None:
    if obj is None or isinstance(obj, (bool, int, str)) and not isinstance(obj, enum.Enum):
        out.append(f"{path}={type(obj).__name__}:{obj!r}")
        return
    if isinstance(obj, float):
        out.append(f"{path}=float:{obj.hex()}")
        return
    if isinstance(obj, enum.Enum):
        out.append(f"{path}=enum:{type(obj).__qualname__}.{obj.name}")
        return
    if isinstance(obj, decimal.Decimal):
        out.append(f"{path}=decimal:{obj}")
        return
    if isinstance(obj, (datetime.date, datetime.datetime)):
        out.append(f"{path}={type(obj).__name__}:{obj.isoformat()}")
        return
    if isinstance(obj, bytes):
        out.append(f"{path}=bytes:{hashlib.sha256(obj).hexdigest()}")
        return
    oid = id(obj)
    if oid in seen:  # shared sub-objects are emitted again by value; only true cycles are cut
        out.append(f"{path}=<cycle {type(obj).__name__}>")
        return
    seen.add(oid)
    try:
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            out.append(f"{path}=<{type(obj).__qualname__}>")
            for f in dataclasses.fields(obj):
                if f.name in EXCLUDED_KEYS:
                    continue
                _emit(getattr(obj, f.name), f"{path}.{f.name}", out, seen)
            return
        if isinstance(obj, dict) or hasattr(obj, "items") and hasattr(obj, "keys"):
            keys = list(obj.keys())
            out.append(f"{path}=<map {len(keys)} order={hashlib.sha256(repr(keys).encode()).hexdigest()[:16]}>")
            for k in sorted(keys, key=lambda k: (type(k).__name__, str(k))):
                if isinstance(k, str) and k in EXCLUDED_KEYS:
                    continue
                _emit(obj[k], f"{path}[{k!r}]", out, seen)
            return
        if isinstance(obj, (list, tuple, frozenset, set)):
            items = list(obj) if isinstance(obj, (list, tuple)) else sorted(obj, key=repr)
            out.append(f"{path}=<{type(obj).__name__} {len(items)}>")
            for i, item in enumerate(items):
                _emit(item, f"{path}[{i}]", out, seen)
            return
        slots = [s for c in type(obj).__mro__ for s in getattr(c, "__slots__", ())]
        if slots:
            out.append(f"{path}=<{type(obj).__qualname__} slots>")
            for s in sorted(set(slots)):
                if s in EXCLUDED_KEYS or not hasattr(obj, s):
                    continue
                _emit(getattr(obj, s), f"{path}.{s}", out, seen)
            return
        if hasattr(obj, "__dict__") and not callable(obj):
            out.append(f"{path}=<{type(obj).__qualname__} dict>")
            for k in sorted(vars(obj)):
                if k in EXCLUDED_KEYS:
                    continue
                _emit(vars(obj)[k], f"{path}.{k}", out, seen)
            return
        out.append(f"{path}=other:{type(obj).__qualname__}")
    finally:
        seen.discard(oid)


def _scenarios():
    from dataclasses import replace
    from datetime import date

    from app import project_factories as pf
    from tools.model_runtime_parity import SCENARIOS as PARITY

    out = {f"parity:{name}": (lambda b=build, m=mutate: m(b()), name.split("_")[0])
           for name, (build, mutate) in PARITY.items()}
    try:
        from tests.test_finco39_dated_native_parity import _make_dated
        from tests.test_fable_batch3_date_authority_generation import _with_r04
    except Exception as exc:  # pragma: no cover - reported, never silently dropped
        print(f"DATED_SCENARIOS_UNAVAILABLE: {type(exc).__name__}: {exc}", file=sys.stderr)
        return out
    sol, wnd = pf.create_generic_solar_reference, pf.create_generic_wind_reference
    out.update({
        "dated:solar_jan1": (lambda: _make_dated(sol(), date(2030, 1, 1), date(2029, 1, 1)), "solar"),
        "dated:solar_mid_month": (lambda: _make_dated(sol(), date(2031, 5, 15), date(2030, 5, 15)), "solar"),
        "dated:solar_leap": (lambda: _make_dated(sol(), date(2032, 2, 29), date(2031, 1, 29), 13), "solar"),
        "dated:solar_7day_window": (lambda: _make_dated(sol(), date(2030, 6, 29), date(2029, 6, 29)), "solar"),
        "dated:solar_r04": (lambda: _with_r04(sol(), "solar"), "solar"),
        "dated:solar_opex_override": (
            lambda: _make_dated(sol(), date(2031, 5, 15), date(2030, 5, 15), with_opex_override=True), "solar"),
        "dated:wind_sep1": (lambda: _make_dated(wnd(), date(2031, 9, 1), date(2030, 3, 1), 18), "wind"),
        "dated:wind_r04": (lambda: _with_r04(wnd(), "wind"), "wind"),
    })
    # stress / rejection witnesses (DSCR-infeasible rejection is parity:infeasible_debt above)
    out["stress:target_dscr_50"] = (
        lambda: replace(sol(), financing=replace(sol().financing, target_dscr=50.0)), "solar")
    out["reject:maturity_beyond_axis"] = (
        lambda: replace(wnd(), financing=replace(wnd().financing, senior_tenor_years=99)), "wind")
    return out


def _install_solver_trace(trace: list) -> None:
    """Record EVERY Senior solver return (and raise) of the Run in call order: intermediate IDC / DSRA / G2A / SHL
    fixed-point solves included, so equivalence is proven on the whole trajectory, not only on the final result."""
    import financial_engine.senior_debt.solver as solver

    real = solver.solve_senior_debt

    def traced(**kwargs):
        try:
            result = real(**kwargs)
        except Exception as exc:
            trace.append(f"raise {type(exc).__qualname__}: {exc}")
            raise
        lines: list[str] = []
        _emit(result, "solve", lines, set())
        trace.append(hashlib.sha256("\n".join(lines).encode()).hexdigest())
        return result

    solver.solve_senior_debt = traced


def record(path: str) -> None:
    from app.services.production_financial_authority import _POLICY_RUN_CACHE, run_clean_production

    trace: list = []
    _install_solver_trace(trace)
    results = {}
    for name, (build, project_type) in sorted(_scenarios().items()):
        _POLICY_RUN_CACHE.clear()
        trace.clear()
        try:
            pi = build()
        except Exception as exc:
            results[name] = {"kind": "build_failed", "error": f"{type(exc).__name__}: {exc}"[:2000]}
            continue
        try:
            run = run_clean_production(pi, "Base", project_type=project_type)
        except Exception as exc:  # typed rejection: class + full first-failure message must match
            results[name] = {"kind": "rejected", "error_type": type(exc).__qualname__,
                             "reason_code": str(getattr(exc, "reason_code", "")), "message": str(exc)[:4000],
                             "solver_calls": len(trace),
                             "solver_trace_sha256": hashlib.sha256("\n".join(trace).encode()).hexdigest()}
            print(f"{name:40s} rejected {type(exc).__name__}", flush=True)
            continue
        lines: list[str] = []
        _emit(run, "run", lines, set())
        payload = "\n".join(lines).encode()
        senior = []
        for ln in lines:
            if any(k in ln for k in ("maximum_absolute_difference_keur", "iteration_count", "termination_reason")):
                senior.append(ln)
        results[name] = {"kind": "digest", "sha256": hashlib.sha256(payload).hexdigest(), "leaves": len(lines),
                         "solver_diagnostic_leaves": len(senior),
                         "solver_diagnostic_sha256": hashlib.sha256("\n".join(senior).encode()).hexdigest(),
                         "solver_calls": len(trace),
                         "solver_trace_sha256": hashlib.sha256("\n".join(trace).encode()).hexdigest()}
        print(f"{name:40s} {results[name]['sha256'][:16]} leaves={len(lines)} solver_calls={len(trace)}", flush=True)
    meta = {"python": sys.version, "excluded_keys": sorted(EXCLUDED_KEYS), "native": "off (default)"}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "results": results}, fh, indent=1, sort_keys=True)


def diff(a: str, b: str) -> int:
    ra, rb = (json.load(open(p, encoding="utf-8"))["results"] for p in (a, b))
    # a scenario that failed to BUILD proves nothing, even when it failed identically in both trees
    bad = [n for n in sorted(set(ra) | set(rb))
           if ra.get(n) != rb.get(n) or (ra.get(n) or {}).get("kind") == "build_failed"]
    for n in sorted(set(ra) | set(rb)):
        print(f"{'DIFF' if n in bad else 'same':4s} {n:40s} {ra.get(n, {}).get('kind')} "
              f"{ra.get(n, {}).get('sha256', ra.get(n, {}).get('error_type', ''))[:16]} leaves={ra.get(n, {}).get('leaves')}")
    print(f"{len(ra)} scenarios, {len(bad)} differences")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--record")
    ap.add_argument("--diff", nargs=2)
    args = ap.parse_args(argv)
    if args.diff:
        return diff(*args.diff)
    tree = os.path.abspath(args.tree)
    sys.path.insert(0, tree)
    os.chdir(tree)
    if args.record:
        record(os.path.abspath(args.record) if os.path.isabs(args.record) else os.path.join(os.getcwd(), args.record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
