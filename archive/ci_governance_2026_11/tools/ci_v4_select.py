"""CI V4 risk-driven test selector (FAST / RISK / FULL). Fail closed.

Trust model: the CI workflow runs THIS file and the policy from the trusted BASE commit, never from the PR head. When the PR itself
changes the selector, the policy or CI control paths, the head policy must additionally select a SUPERSET of what the base policy selects
(``compare_with_head_policy``); a PR cannot shrink its own acceptance. Unknown paths select the extended RISK set, never FAST.
A non-selected test is reported NOT SELECTED, never PASS.
"""
from __future__ import annotations

import argparse
import ast
import functools
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "FINCO_CI_V4_PLAN_V1"
TIER_ORDER = {"fast": 0, "risk": 1, "full": 2}
SOURCE_DIRS = ("app", "finco_core", "financial_engine", "domain", "finco_app", "finco_radar", "finco_yield", "finco_protocol", "utils")
RISK_DEPENDENT_CAP = 200


class PolicyError(ValueError):
    pass


def _glob_to_re(pat):
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3; continue
        if pat.startswith("**", i):
            out.append(".*"); i += 2; continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)); i += 1
    return re.compile("^" + "".join(out) + "$")


def _matches(path, patterns):
    return any(_glob_to_re(p).match(path) for p in patterns)


def validate_policy(policy):
    """Structural validation; a malformed policy is a hard failure, never a silent FAST."""
    try:
        if policy.get("schema") != "FINCO_CI_V4_POLICY_V1":
            raise PolicyError("bad schema")
        if policy.get("default_tier_for_unknown_path") not in ("risk", "full"):
            raise PolicyError("unknown paths must default to risk or full")
        ids = [r["id"] for r in policy["rules"]]
        if len(ids) != len(set(ids)):
            raise PolicyError("duplicate rule id")
        for r in policy["rules"]:
            if r["tier"] not in TIER_ORDER or not r["patterns"]:
                raise PolicyError("bad rule " + r["id"])
            for s in r.get("suites", []):
                if s not in policy["suites"]:
                    raise PolicyError("rule %s references unknown suite %s" % (r["id"], s))
        if "fast_baseline" not in policy["suites"]:
            raise PolicyError("fast_baseline suite required")
        for tier in ("fast", "risk", "full"):
            if int(policy["workers"][tier]["max"]) < 1:
                raise PolicyError("workers.max")
        # No rule may route a financial/security/CI path to FAST.
        for r in policy["rules"]:
            if r["tier"] == "fast":
                for protected in ("financial_engine/x.py", "finco_core/x.py", "domain/x.py", "app/x.py", ".github/workflows/x.yml", "tools/ci_x.py", "main_web.py"):
                    if _matches(protected, r["patterns"]):
                        raise PolicyError("rule %s sends protected path %s to FAST" % (r["id"], protected))
    except (KeyError, TypeError, AttributeError) as exc:
        raise PolicyError("malformed policy: %r" % (exc,)) from exc
    return policy


def load_policy(path):
    return validate_policy(json.loads(Path(path).read_text()))


def policy_digest(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _is_control(path, policy, rule):
    return bool((rule or {}).get("control")) or _matches(path, policy.get("control_paths", []))


def classify(path, policy):
    for r in policy["rules"]:
        if _matches(path, r["patterns"]):
            return r
    return None


def _module_name(path):
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _imports(src):
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return set()
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            found.add(n.module)
            found.update(n.module + "." + a.name for a in n.names)
    return found


def build_import_graph(root):
    return _graph(str(Path(root).resolve()))


@functools.lru_cache(maxsize=4)
def _graph(root):
    root = Path(root)
    graph = {}                      # module -> set(imported dotted names)
    for d in SOURCE_DIRS:
        for f in sorted((root / d).rglob("*.py")) if (root / d).is_dir() else []:
            name = _module_name(f.relative_to(root).as_posix())
            if name:
                graph[name] = _imports(f.read_text(errors="replace"))
    tests = {}
    for f in sorted((root / "tests").glob("test_*.py")) if (root / "tests").is_dir() else []:
        tests[f.relative_to(root).as_posix()] = _imports(f.read_text(errors="replace"))
    return graph, tests


def dependents(changed_paths, root, depth=2):
    """Test modules that import (directly or through <=depth source modules) any changed Python source. Ordered by distance then path."""
    graph, tests = build_import_graph(root)
    seeds = {n for n in (_module_name(p) for p in changed_paths) if n}
    frontier, seen, dist = set(seeds), set(seeds), {}
    for level in range(depth + 1):
        for t, imps in tests.items():
            if t not in dist and imps & frontier:
                dist[t] = level
        nxt = {m for m, imps in graph.items() if m not in seen and imps & frontier}
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return [t for t, _ in sorted(dist.items(), key=lambda kv: (kv[1], kv[0]))]


def _all_test_modules(root):
    return sorted(f.relative_to(root).as_posix() for f in (Path(root) / "tests").glob("test_*.py"))


def select(changed, policy, root=ROOT, base_sha="", head_sha="", tree_sha="", event="pull_request", force_tier=None):
    validate_policy(policy)
    root = Path(root)
    changed = sorted(set(changed))
    tier = "fast"
    triggers, suites, rule_ids = [], set(), set()
    self_select, dep_inputs, control = [], [], False
    unknown = []
    for p in changed:
        if p.startswith("/") or ".." in p.split("/"):
            raise PolicyError("illegal path %r" % p)
        r = classify(p, policy)
        if r is None:
            unknown.append(p)
            rule = {"id": "unknown_path", "tier": policy["default_tier_for_unknown_path"], "suites": [k for k in policy["suites"] if k.startswith("risk_") and k != "risk_f01_native"]}
            triggers.append({"path": p, "rule": "unknown_path", "tier": rule["tier"], "fail_closed": True})
            r = rule
        else:
            triggers.append({"path": p, "rule": r["id"], "tier": r["tier"]})
        rule_ids.add(r["id"])
        if TIER_ORDER[r["tier"]] > TIER_ORDER[tier]:
            tier = r["tier"]
        suites.update(r.get("suites", []))
        if r.get("select_self") and (root / p).is_file():
            self_select.append(p)
        if r.get("select_dependents"):
            dep_inputs.append(p)
        if _is_control(p, policy, r):
            control = True
    if control and TIER_ORDER[tier] < TIER_ORDER["risk"]:
        # A CI/governance self-modification is never FAST, whatever rule matched first.
        tier = "risk"
        rule_ids.add("control_change_minimum_risk")
    if control:
        suites.add("risk_governance")
    if force_tier:
        if TIER_ORDER[force_tier] < TIER_ORDER[tier]:
            raise PolicyError("force_tier may only raise the tier")
        tier = force_tier
    if tier == "full":
        modules = _all_test_modules(root)
        return _finish(policy, tier, changed, triggers, rule_ids, sorted(policy["suites"]), modules, [], control, unknown, base_sha, head_sha, tree_sha, event, root, False, 0)
    dep = dependents(dep_inputs, root) if dep_inputs else []
    # CI V4 rules v2: historical exactness / governance test modules are FULL (nightly + release) criteria. A PR runs ONE central bounded
    # governance check (tools/ci_v4_governance_gate.py, every PR) instead; such a module is selected only when the PR changes the module
    # itself or its own cohort module (tests/X_scope.py -> tests/test_X_scope.py). Deferred modules are reported, never counted as PASS.
    hist = policy.get("history_governance", {}).get("patterns", [])
    deferred = sorted({m for m in dep if _matches(m, hist)})
    dep = [m for m in dep if not _matches(m, hist)]
    for p in changed:
        name = p.rsplit("/", 1)[-1]
        if p.startswith("tests/") and p.count("/") == 1 and name.endswith("_scope.py") and not name.startswith("test_"):
            paired = "tests/test_" + name
            if (root / paired).is_file() and paired not in self_select:
                self_select.append(paired)
                rule_ids.add("governance_pair")
    truncated, dep_total = False, len(dep)
    if tier == "fast" and len(dep) > policy["dependency_escalation"]["fast_max_dependent_modules"]:
        tier = "risk"
        suites.update(k for k in policy["suites"] if k.startswith("risk_") and k != "risk_f01_native")
        rule_ids.add("dependency_escalation")
    if tier == "risk" and len(dep) > RISK_DEPENDENT_CAP:
        dep, truncated = dep[:RISK_DEPENDENT_CAP], True
    if tier == "risk" and truncated:
        rule_ids.add("dependents_truncated_full_recommended")
    suite_names = sorted(suites | {"fast_baseline"})
    return _finish(policy, tier, changed, triggers, rule_ids, suite_names, self_select, dep, control, unknown, base_sha, head_sha, tree_sha, event, root,
                   truncated, dep_total, deferred=[m for m in deferred if m not in self_select])


def _finish(policy, tier, changed, triggers, rule_ids, suite_names, extra, dep, control, unknown, base_sha, head_sha, tree_sha, event, root, truncated, dep_total,
            deferred=()):
    modules, kinds = set(), {}
    for s in suite_names:
        spec = policy["suites"][s]
        for m in spec["modules"]:
            kinds.setdefault(spec["kind"], set()).add(m)
            if spec["kind"] == "pytest":
                modules.add(m)
    pytest_extra = [m for m in list(extra) + list(dep) if m.startswith("tests/test_") and (Path(root) / m).is_file()]
    modules |= set(pytest_extra)
    # Only modules that exist are runnable; a missing declared suite module is a plan error, never skipped silently.
    missing = sorted(m for m in modules if not (Path(root) / m).is_file())
    if missing:
        raise PolicyError("selected test modules missing from tree: %s" % missing)
    no_skip = {m for s in suite_names if policy["suites"][s].get("no_skip") and policy["suites"][s]["kind"] == "pytest"
               for m in policy["suites"][s]["modules"]} | set(m for m in extra if m in modules and "browser" not in m)
    # A changed *browser* module runs in its mandatory browser role / F01 job (the shard runtime has no Chromium, as in CI V3);
    # in a shard it may only skip, and that skip is listed SKIPPED (not PASS).
    all_tests = set(_all_test_modules(root))
    plan = {
        "schema": SCHEMA, "event": event, "tier": tier,
        "tested_sha": head_sha, "tested_tree": tree_sha, "base_sha": base_sha,
        "policy_digest": policy_digest(policy),
        "changed_paths": changed, "triggers": triggers, "rule_ids": sorted(rule_ids),
        "control_changed": control, "unknown_paths": unknown,
        "suites": suite_names,
        "pytest_modules": sorted(modules),
        "needs_browser": any(policy["suites"][s].get("browser") for s in suite_names),
        "needs_native_docker": "risk_f01_native" in suite_names,
        "needs_frontend_build": "risk_ui_build" in suite_names or tier == "full",
        "dependents": {"total": dep_total, "selected": len(dep), "truncated": truncated, "full_recommended": truncated},
        "not_selected": {"count": len(all_tests - modules), "label": "NOT SELECTED (not PASS)"},
        "no_skip_modules": sorted(no_skip),
        "history_deferred_to_full": {"count": len([m for m in deferred if m not in modules]), "modules": [m for m in deferred if m not in modules],
                                     "label": "NOT SELECTED on the PR: FULL (nightly + release gate); central governance gate runs instead"},
    }
    from tools.ci_v4_schedule import load_weights, plan_shards
    plan["schedule"] = plan_shards(sorted(modules), load_weights(), tier, policy)
    plan["digest"] = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return plan


def covers(superset_plan, subset_plan):
    """True when the first plan selects at least everything the second selects (tier and module set)."""
    return (TIER_ORDER[superset_plan["tier"]] >= TIER_ORDER[subset_plan["tier"]]
            and set(superset_plan["pytest_modules"]) >= set(subset_plan["pytest_modules"])
            and set(superset_plan["suites"]) >= set(subset_plan["suites"]))


def compare_with_head_policy(base_plan, head_policy, changed, root=ROOT, **kw):
    """Control-change guard: the policy of the PR head may not select less than the trusted base policy."""
    head_plan = select(changed, head_policy, root=root, **kw)
    if not covers(head_plan, base_plan):
        raise PolicyError("head policy selects less than the trusted base policy (self-weakening change refused)")
    return head_plan


def union_plan(base_plan, head_plan, policy, root=ROOT):
    """Trusted base plan widened by everything the head plan adds; tier is the max. Re-scheduled and re-digested; flagged."""
    plan = {k: v for k, v in base_plan.items() if k not in ("digest", "schedule")}
    plan["tier"] = max(base_plan["tier"], head_plan["tier"], key=lambda t: TIER_ORDER[t])
    for key in ("pytest_modules", "suites", "no_skip_modules", "rule_ids"):
        plan[key] = sorted(set(base_plan.get(key, [])) | set(head_plan.get(key, [])))
    for key in ("needs_browser", "needs_native_docker", "needs_frontend_build", "control_changed"):
        plan[key] = bool(base_plan.get(key)) or bool(head_plan.get(key))
    plan["head_policy_narrower"] = {"flag": True, "base_only_modules": sorted(set(base_plan["pytest_modules"]) - set(head_plan["pytest_modules"])),
                                    "rule": "a PR never runs under its own narrower policy; union plan executed"}
    all_tests = set(_all_test_modules(root))
    plan["not_selected"] = {"count": len(all_tests - set(plan["pytest_modules"])), "label": "NOT SELECTED (not PASS)"}
    from tools.ci_v4_schedule import load_weights, plan_shards
    plan["schedule"] = plan_shards(plan["pytest_modules"], load_weights(), plan["tier"], policy)
    plan["digest"] = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return plan


def git_changed(base, head, repo=ROOT):
    out = subprocess.check_output(["git", "diff", "--name-only", "--no-renames", "%s...%s" % (base, head)], cwd=repo).decode()
    return [p for p in out.splitlines() if p]


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V4 selector (run from the TRUSTED base checkout)")
    ap.add_argument("--policy", required=True, help="policy from the trusted base commit")
    ap.add_argument("--head-policy", help="PR head policy; checked for self-weakening when given")
    ap.add_argument("--repo", default=".", help="checkout of the tested head (for the file/import inventory)")
    ap.add_argument("--base", default=""); ap.add_argument("--head", required=True)
    ap.add_argument("--event", default="pull_request")
    ap.add_argument("--tier", choices=("fast", "risk", "full"), help="raise the tier (workflow_dispatch / schedule)")
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    try:
        policy = load_policy(a.policy)
        tree = subprocess.check_output(["git", "rev-parse", a.head + "^{tree}"], cwd=repo).decode().strip()
        head = subprocess.check_output(["git", "rev-parse", a.head], cwd=repo).decode().strip()
        if a.tier == "full" or a.event in ("schedule", "workflow_dispatch", "release"):
            changed = []
            plan = select(changed, policy, repo, a.base, head, tree, a.event, force_tier=a.tier or "full")
        else:
            changed = git_changed(a.base, head, repo)
            plan = select(changed, policy, repo, a.base, head, tree, a.event, force_tier=a.tier)
            if a.head_policy:
                head_plan = select(changed, load_policy(a.head_policy), repo, a.base, head, tree, a.event, force_tier=a.tier)
                if not covers(head_plan, plan):
                    # Self-narrowing PR (e.g. an owner-approved policy change): it can never use its own narrower policy. It runs the
                    # UNION of the trusted base plan and its own plan (nothing the base selects is skipped) and is flagged for review.
                    plan = union_plan(plan, head_plan, load_policy(a.policy), repo)
                    print("CI V4 selector: head policy is NARROWER than the trusted base; running the union plan (flagged)", file=sys.stderr)
    except (PolicyError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print("CI V4 selector FAIL CLOSED: %s" % exc, file=sys.stderr)
        return 2
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(plan, indent=2, sort_keys=True))
    print("tier=%s modules=%d control=%s rules=%s" % (plan["tier"], len(plan["pytest_modules"]), plan["control_changed"], ",".join(plan["rule_ids"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
