"""CI V4 deterministic weighted scheduling (whole-module LPT) and worker-count simulation.

Pure functions; no pytest is run here. Weights are measured JUnit module seconds (docs/ci_v4/module_weights.json); a schedule built from them
is still a PREDICTION until a hosted run confirms it (see docs/ci_v4/CI_V4_WORKER_BENCHMARK_AND_SCHEDULING_HR.md). A module is an indivisible unit, except
the closed node-split allowlist (docs/ci_v4/node_split_policy.json), whose exact collected node ids may be partitioned by ``apply_node_split``.
"""
from __future__ import annotations

import hashlib
import json
import math
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
    """Smallest worker count whose marginal gain justifies another runner (policy: min seconds saved per extra worker).

    Correction (2026-11-14, PR #446 shard-2 forensics): the LPT critical path is NOT monotonic in the worker count - one
    sub-threshold step can precede a materially better k+2 (deterministic repro in tests/test_ci_v4_schedule.py), so the scan
    continues to the cap instead of stopping at the first sub-threshold step. The per-extra-worker policy is kept exactly: a larger
    k is accepted only when it saves at least min_module_seconds_per_extra_worker for EVERY worker it adds over the last accepted
    count (``saved >= min_gain * (k - best)``). One threshold never pays for two runners: skipping a bad step cannot turn a one-worker
    justification into a multi-worker purchase. Fail-closed, tier cap unchanged, no empty workers (plan_shards).
    """
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
        if best_crit - crit >= min_gain * (k - best):      # every added worker must earn the stated threshold
            best, best_crit = k, crit
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


# ── Node-level splitting of specifically proven-heavy modules (applied only AFTER selection; never changes what is selected) ───────────────
NODE_SPLIT_POLICY_SCHEMA = "FINCO_CI_V4_NODE_SPLIT_POLICY_V1"
NODE_SPLIT_SCHEMA = "FINCO_CI_V4_NODE_SPLIT_V1"
SPLIT_VERDICTS = ("SPLIT_SAFE", "SPLIT_SAFE_FLOOR_LIMITED")


def plan_digest(plan):
    return hashlib.sha256(json.dumps({k: v for k, v in plan.items() if k != "digest"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_node_split_policy(path=None):
    p = Path(path) if path else ROOT / "docs" / "ci_v4" / "node_split_policy.json"
    data = json.loads(p.read_text())
    validate_node_split_policy(data)
    return data


def validate_node_split_policy(data):
    """Closed allowlist: literal test-module paths with a recorded safety verdict; bounded parts; never a pattern."""
    if data.get("schema") != NODE_SPLIT_POLICY_SCHEMA:
        raise ValueError("node split policy: unknown schema")
    if not isinstance(data.get("enabled_in_required_pr_gate"), bool):
        raise ValueError("node split policy: enabled_in_required_pr_gate must be a boolean")
    if not 2 <= int(data["max_parts_per_module"]) <= 8 or float(data["target_unit_seconds"]) < 60:
        raise ValueError("node split policy: parts/target out of bounds")
    for m, spec in data["modules"].items():
        if not (m.startswith("tests/test_") and m.endswith(".py")) or any(ch in m for ch in "*?[") or ".." in m.split("/"):
            raise ValueError("node split policy: %r is not a literal test module" % m)
        if spec.get("verdict") not in SPLIT_VERDICTS or not spec.get("isolation_proof"):
            raise ValueError("node split policy: %s lacks a split-safe verdict and isolation proof" % m)
    return data


def load_node_weights(path=None):
    """Measured per-node seconds keyed by exact node id (docs/ci_v4/node_weights.json); provenance is kept in the file, not here."""
    p = Path(path) if path else ROOT / "docs" / "ci_v4" / "node_weights.json"
    try:
        return {k: float(v) for k, v in json.loads(p.read_text())["nodes"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def split_module_nodes(node_ids, seconds, parts):
    """LPT of the module's nodes into ``parts`` bins (ties: collection order, lowest bin); each bin keeps COLLECTION order; empty bins dropped."""
    order = {n: i for i, n in enumerate(node_ids)}
    bins = [[] for _ in range(parts)]
    loads = [0.0] * parts
    for n in sorted(node_ids, key=lambda n: (-seconds[n], order[n])):
        i = min(range(parts), key=lambda b: (loads[b], b))
        bins[i].append(n)
        loads[i] += seconds[n]
    out = [(sorted(b, key=order.__getitem__), l) for b, l in zip(bins, loads) if b]
    return [b for b, _ in out], [l for _, l in out]


def _lpt_units(units, workers):
    """LPT over named units {id: seconds}. Ties: unit id, lowest worker. Deterministic."""
    loads = [0.0] * workers
    shards = [[] for _ in range(workers)]
    for u in sorted(units, key=lambda u: (-units[u], u)):
        i = min(range(workers), key=lambda w: (loads[w], w))
        shards[i].append(u)
        loads[i] += units[u]
    return [sorted(s) for s in shards], loads


def apply_node_split(plan, inventory, split_policy, weights, node_weights, policy, shadow=False):
    """Return ``plan`` with selected, allowlisted, heavy modules split into exact node units, or ``plan`` unchanged.

    The module selection (``pytest_modules``), tier, suites and every other selector field are untouched. Splitting runs only when the policy
    enables it for the required gate, or for a labelled shadow benchmark (``shadow=True``). The inventory must be bound to the tested SHA/tree.
    """
    if not (split_policy["enabled_in_required_pr_gate"] or shadow):
        return plan
    if inventory["tested_sha"] != plan["tested_sha"] or inventory["tested_tree"] != plan["tested_tree"]:
        raise ValueError("node inventory is bound to a different sha/tree than the plan")
    cfg = policy["workers"][plan["tier"]]
    target, max_parts = float(split_policy["target_unit_seconds"]), int(split_policy["max_parts_per_module"])
    units, unit_spec, split, estimated = {}, {}, {}, []
    for m in sorted(set(plan["pytest_modules"])):
        inv = inventory["modules"].get(m)
        if m in split_policy["modules"] and inv is not None:
            ids = inv["node_ids"]
            known = [n for n in ids if n in node_weights]
            fallback = max(weight_of(m, weights) - sum(node_weights[n] for n in known), 0.0) / max(len(ids) - len(known), 1)
            secs = {n: node_weights.get(n, fallback) for n in ids}
            estimated += [n for n in ids if n not in node_weights]
            total, top = sum(secs.values()), max(secs.values())
            # a node heavier than the target is an indivisible floor: it gets its own part, the rest is split by the target
            want = 1 + math.ceil((total - top) / target) if top >= target else math.ceil(total / target)
            parts = min(max_parts, len(ids), max(1, want))
            if parts >= 2:
                bins, loads = split_module_nodes(ids, secs, parts)
                split[m] = {"count": len(ids), "digest": inv["digest"], "node_ids": ids, "parts": len(bins),
                            "verdict": split_policy["modules"][m]["verdict"]}
                for k, (b, load) in enumerate(zip(bins, loads)):
                    uid = "%s#%d/%d" % (m, k + 1, len(bins))
                    units[uid] = load
                    unit_spec[uid] = {"kind": "nodes", "module": m, "part": k + 1, "of": len(bins), "node_ids": b}
                continue
        # whole module: the newer per-node V4 measurement when it covers >= 90 % of its collected nodes, else the stored module weight
        ids = inv["node_ids"] if inv is not None else []
        known = [n for n in ids if n in node_weights]
        units[m] = sum(node_weights[n] for n in known) if ids and len(known) >= 0.9 * len(ids) else weight_of(m, weights)
        unit_spec[m] = {"kind": "module", "module": m}
    if not split:
        return plan
    cap = int(cfg["max"]); min_gain = float(cfg["min_module_seconds_per_extra_worker"])
    # Same correction as choose_workers: keep scanning to the cap (unit critical path is not monotonic in k) and price every
    # added worker at the policy threshold, so no worker is added without its own policy-justified saving.
    best, (best_shards, best_loads) = 1, _lpt_units(units, 1)
    for k in range(2, min(cap, len(units)) + 1):
        shards, loads = _lpt_units(units, k)
        if max(best_loads) - max(loads) >= min_gain * (k - best):
            best, best_shards, best_loads = k, shards, loads
    pairs = [(s, l) for s, l in zip(best_shards, best_loads) if s]
    over = float(cfg["fixed_overhead_seconds_per_worker"])
    out = {k: v for k, v in plan.items() if k not in ("digest", "schedule")}
    out["schedule"] = {
        "workers": len(pairs),
        "shards": [sorted({unit_spec[u]["module"] for u in s}) for s, _ in pairs],
        "units": [[unit_spec[u] for u in s] for s, _ in pairs],
        "predicted_critical_path_s": round(over + max(l for _, l in pairs) + 60.0, 1),
        "predicted_runner_minutes": round((len(pairs) * over + sum(l for _, l in pairs) + 60.0) / 60.0, 2),
        "projected_weights": True, "unweighted_modules": sorted(m for m in set(plan["pytest_modules"]) if m not in weights),
        "estimated_node_weights": len(estimated), "module_plan_superseded": plan["schedule"],
    }
    out["node_split"] = {"schema": NODE_SPLIT_SCHEMA, "shadow": bool(shadow), "inventory_digest": inventory["digest"],
                         "profile_digest": inventory["profile_digest"], "modules": split,
                         "policy_digest": hashlib.sha256(json.dumps(split_policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    out["digest"] = plan_digest(out)
    return out


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
