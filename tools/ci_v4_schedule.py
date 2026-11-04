"""CI V4 deterministic weighted scheduling (whole-module LPT) and worker-count simulation.

Pure functions; no pytest is run here. Weights are measured JUnit module seconds (docs/ci_v4/module_weights.json); a schedule built from them
is still a PREDICTION until a hosted run confirms it (see docs/ci_v4/CI_V4_WORKER_BENCHMARK_AND_SCHEDULING_HR.md). A module is an indivisible unit; never split across workers.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODULE_SECONDS = 30.0   # used only for a module with no recorded weight; flagged as projected in the plan
WORKER_CHOICES = (1, 2, 3, 4, 6, 8)


def load_weights(path=None):
    """Measured module seconds: docs/ci_v4/module_weights.json (JUnit of CI V3 run 41782498276, all 8 workers); older file only as fallback."""
    candidates = [Path(path)] if path else [ROOT / "docs" / "ci_v4" / "module_weights.json", ROOT / "tools" / "ci_module_weights.json"]
    for p in candidates:
        try:
            data = json.loads(p.read_text())
            return {k: float(v) for k, v in data["modules"].items()}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {}


def weight_of(module, weights):
    return weights.get(module, DEFAULT_MODULE_SECONDS)


def lpt(modules, weights, workers):
    """Longest-processing-time-first. Ties: lexical module path, then lowest worker index. Deterministic."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    mods = sorted(set(modules), key=lambda m: (-weight_of(m, weights), m))
    loads = [0.0] * workers
    shards = [[] for _ in range(workers)]
    for m in mods:
        i = min(range(workers), key=lambda w: (loads[w], w))
        shards[i].append(m)
        loads[i] += weight_of(m, weights)
    return [sorted(s) for s in shards], loads


def simulate(modules, weights, policy_tier, tier_cfg, counts=WORKER_CHOICES):
    """Projected wall clock / runner-minutes per worker count. wall = per-worker overhead + max shard load + aggregate overhead."""
    overhead = float(tier_cfg["fixed_overhead_seconds_per_worker"])
    agg = 60.0
    rows = []
    total = sum(weight_of(m, weights) for m in set(modules))
    heaviest = max((weight_of(m, weights) for m in set(modules)), default=0.0)
    for k in counts:
        if k > max(1, len(set(modules))):
            continue      # an empty / duplicate worker is useless
        _, loads = lpt(modules, weights, k)
        crit = max(loads) if loads else 0.0
        rows.append({"workers": k, "critical_path_s": round(overhead + crit + agg, 1),
                     "runner_minutes": round((k * overhead + sum(loads) + agg) / 60.0, 2),
                     "max_shard_s": round(crit, 1), "floor_indivisible_s": round(heaviest, 1)})
    return {"projected": True, "tier": policy_tier, "total_module_s": round(total, 1), "rows": rows}


def choose_workers(modules, weights, tier, tier_cfg):
    """Smallest worker count whose marginal gain justifies another runner (policy: min seconds saved per extra worker)."""
    cap = int(tier_cfg["max"])
    min_gain = float(tier_cfg["min_module_seconds_per_extra_worker"])
    n = len(set(modules))
    if n == 0:
        return 1
    best = 1
    _, loads = lpt(modules, weights, 1)
    best_crit = max(loads)
    for k in range(2, min(cap, n) + 1):
        _, loads = lpt(modules, weights, k)
        crit = max(loads)
        if best_crit - crit >= min_gain:      # saved wall time must beat the stated threshold
            best, best_crit = k, crit
        else:
            break
    return best


def predicted_critical_path_s(modules, weights, workers, tier_cfg):
    _, loads = lpt(modules, weights, workers)
    return round(float(tier_cfg["fixed_overhead_seconds_per_worker"]) + (max(loads) if loads else 0.0) + 60.0, 1)


def plan_shards(modules, weights, tier, policy):
    cfg = policy["workers"][tier]
    k = choose_workers(modules, weights, tier, cfg)
    shards, loads = lpt(modules, weights, k)
    nonempty = [s for s in shards if s]
    return {"workers": len(nonempty) or 1, "shards": nonempty or [[]],
            "predicted_critical_path_s": predicted_critical_path_s(modules, weights, len(nonempty) or 1, cfg),
            "predicted_runner_minutes": round(((len(nonempty) or 1) * cfg["fixed_overhead_seconds_per_worker"] + sum(loads) + 60) / 60.0, 2),
            "projected_weights": True, "unweighted_modules": sorted(m for m in set(modules) if m not in weights)}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Project LPT schedule for a module list")
    ap.add_argument("--policy", default=str(ROOT / "docs/ci_v4/ci-v4-policy.json"))
    ap.add_argument("--tier", choices=("fast", "risk", "full"), required=True)
    ap.add_argument("modules", nargs="+")
    a = ap.parse_args(argv)
    pol = json.loads(Path(a.policy).read_text())
    w = load_weights()
    print(json.dumps(simulate(a.modules, w, a.tier, pol["workers"][a.tier]), indent=2))


if __name__ == "__main__":
    main()
