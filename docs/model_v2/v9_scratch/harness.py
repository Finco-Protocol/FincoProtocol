"""V9-A scratch harness: uncached runs, full-result flattening, parity classification."""
from __future__ import annotations

import dataclasses as dc
import datetime as _dt
import enum
import math
import re
import time

import v9proto
from app.services import production_financial_authority as pfa

# Solver/iteration bookkeeping that legitimately differs when the iterate path changes.
DIAG_RE = re.compile(
    r"(iteration|residual|maximum_difference|max_closing_delta|max_interest_delta|"
    r"termination_reason|evaluation_count|calculation_count|elapsed|duration|timing|input_fingerprint|"
    r"run_id|created_at|timestamp|fingerprint|digest|hash|handshake_delta)", re.I)
# Categorical leaves whose change means NOT FINANCIALLY EQUIVALENT.
CAT_HINT = re.compile(r"(status|classification|binding|feasib|repaid|outstanding|gate|"
                      r"is_|converged|authoritative|reason|mode|state|flag|breach|lockup)", re.I)


_NUM = re.compile(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?")


def flatten(obj, path="", out=None, seen=None, depth=0):
    if out is None:
        out, seen = {}, set()
    if depth > 60:
        out[path] = ("<depth>",)
        return out
    if obj is None or isinstance(obj, (bool, int, float, str, _dt.date, _dt.datetime)):
        out[path] = obj
        return out
    if isinstance(obj, enum.Enum):
        out[path] = f"{type(obj).__name__}.{obj.name}"
        return out
    if callable(obj) and not dc.is_dataclass(obj):
        return out
    oid = id(obj)
    if oid in seen:
        out[path] = "<ref>"
        return out
    seen.add(oid)
    try:
        if dc.is_dataclass(obj):
            for f in dc.fields(obj):
                flatten(getattr(obj, f.name), f"{path}.{f.name}", out, seen, depth + 1)
        elif isinstance(obj, dict):
            for k in sorted(obj, key=repr):
                flatten(obj[k], f"{path}[{k!r}]", out, seen, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                flatten(v, f"{path}[{i}]", out, seen, depth + 1)
        elif isinstance(obj, (set, frozenset)):
            for i, v in enumerate(sorted(obj, key=repr)):
                flatten(v, f"{path}{{{i}}}", out, seen, depth + 1)
        elif hasattr(obj, "__dict__"):
            for k, v in sorted(vars(obj).items()):
                if not k.startswith("__"):
                    flatten(v, f"{path}.{k}", out, seen, depth + 1)
        else:
            out[path] = repr(obj)
    finally:
        seen.discard(oid)
    return out


def _family(path):
    return re.sub(r"\[\d+\]", "[]", path)


def compare(a: dict, b: dict):
    """Classify differences between two flattened results."""
    rep = {"leaves": len(a), "float_leaves": 0, "bit_identical_floats": 0,
           "max_abs": 0.0, "max_abs_path": None, "max_rel": 0.0, "max_rel_path": None,
           "categorical": [], "diagnostic": [], "structural": [], "families": {}}
    keys = set(a) | set(b)
    for k in sorted(keys):
        if k not in a or k not in b:
            (rep["diagnostic"] if DIAG_RE.search(k) else rep["structural"]).append(k)
            continue
        x, y = a[k], b[k]
        if isinstance(x, float) and isinstance(y, float) and not isinstance(x, bool):
            rep["float_leaves"] += 1
            if x == y or (math.isnan(x) and math.isnan(y)):
                if math.copysign(1, x) == math.copysign(1, y):
                    rep["bit_identical_floats"] += 1
                    continue
            d = abs(x - y)
            if DIAG_RE.search(k):
                rep["diagnostic"].append((k, x, y))
                continue
            rel = d / max(abs(x), abs(y), 1e-300)
            fam = _family(k)
            f = rep["families"].setdefault(fam, [0, 0.0, 0.0])
            f[0] += 1
            f[1] = max(f[1], d)
            f[2] = max(f[2], rel)
            if d > rep["max_abs"]:
                rep["max_abs"], rep["max_abs_path"] = d, k
            if rel > rep["max_rel"] and abs(x) > 1e-6:
                rep["max_rel"], rep["max_rel_path"] = rel, k
        elif x != y or type(x) is not type(y):
            if DIAG_RE.search(k):
                rep["diagnostic"].append((k, x, y))
            elif isinstance(x, str) and isinstance(y, str) and _NUM.sub("#", x) == _NUM.sub("#", y):
                # same text, only an embedded number differs: numeric evidence, not a category
                nx = [float(v) for v in _NUM.findall(x)]
                ny = [float(v) for v in _NUM.findall(y)]
                d = max((abs(a - b) for a, b in zip(nx, ny)), default=0.0)
                rep.setdefault("text_numeric", []).append((k, d))
                if d > rep["max_abs"]:
                    rep["max_abs"], rep["max_abs_path"] = d, k + " (text)"
            else:
                rep["categorical"].append((k, x, y))
    return rep


def clear_caches():
    pfa._POLICY_RUN_CACHE.clear()
    try:
        from financial_engine.tax import tax_year
        tax_year._tax_year_cache_clear = None
        for v in vars(tax_year).values():
            if hasattr(v, "cache_clear"):
                v.cache_clear()
    except Exception:
        pass


def run_case(case, flags=(), *, keep=True):
    """One genuine uncached production run. Returns (outcome, seconds, stats)."""
    pi, ptype = case["build"](), case["ptype"]
    kw = {"financing_policy": case["policy"]} if case.get("policy") is not None else {}
    clear_caches()
    if flags:
        with v9proto.installed(flags) as st:
            v9proto.reset_run_state()
            t = time.perf_counter()
            try:
                out = pfa.run_clean_production(pi, project_type=ptype, **kw)
            except Exception as e:  # noqa: BLE001
                out = e
            dt = time.perf_counter() - t
            stats = dict(st.stats)
    else:
        t = time.perf_counter()
        try:
            out = pfa.run_clean_production(pi, project_type=ptype, **kw)
        except Exception as e:  # noqa: BLE001
            out = e
        dt = time.perf_counter() - t
        stats = {}
    return out, dt, stats


def outcome_digest(out):
    if isinstance(out, Exception):
        return {"<exception>": f"{type(out).__name__}: {getattr(out, 'reason_code', '')} {str(out)[:400]}"}
    return flatten(out)


SUMMARY_KEYS = (
    ".g2c_result.financing_result.final_senior_commitment_keur",
    ".g2c_result.financing_result.binding_senior_constraint",
    ".g2c_result.financing_result.derived_shl_cash_principal_keur",
    ".g2c_result.financing_result.project_uses.total_project_uses_keur",
    ".g2c_result.financing_result.dscr_debt_capacity_keur",
    ".g2c_result.financing_result.gearing_debt_capacity_keur",
)
STATUS_RE = re.compile(r"terminal|_status$|status\b", re.I)


def summary(out):
    if isinstance(out, Exception):
        return {"exception": f"{type(out).__name__}: {getattr(out, 'reason_code', '')}"}
    d = flatten(out)
    s = {k.rsplit(".", 1)[-1]: d.get(k) for k in SUMMARY_KEYS}
    s["statuses"] = {k: str(v) for k, v in d.items()
                     if STATUS_RE.search(k.rsplit(".", 1)[-1]) and not isinstance(v, float)
                     and "[" not in k.rsplit(".", 1)[-1]}
    return s
