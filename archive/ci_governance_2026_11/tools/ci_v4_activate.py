"""CI V4 PR-B: trusted-base activation of exact-node sharding in the REQUIRED PR gate.

Run ONLY from a checkout (or extracted tree) of the TRUSTED base commit; ``--subject`` is the PR head under test. Everything that decides
coverage comes from this trusted tree: the node-split policy (enablement + closed allowlist), worker policy, weights, scheduler, the pytest
node plugin and the aggregator. The PR head contributes only its tests (the subject), never its own policy or tooling:

* a PR whose trusted base still has ``enabled_in_required_pr_gate: false`` (e.g. this PR-B itself) keeps the sealed module plan unchanged;
* when the trusted base enables it, only selected modules on the trusted allowlist are split; the selection (``pytest_modules``, tier, suites,
  no-skip, F01/native flags, NOT SELECTED metadata) is never changed, and the change is proven field by field before the plan is re-sealed.

The trusted plugin is materialized under a unique module name (``finco_ci_v4_trusted_nodes``) in a private directory and loaded with ``-p``;
the subject's own ``tools/ci_v4_nodes.py`` is never imported by collection, execution or re-collection, and the subject's ``tools`` package
stays the one its tests import. Provenance (trusted SHA, policy/plugin SHA-256, Python) is sealed into the plan.

Subcommands: ``decide`` (does this sealed plan need a node collection under the trusted policy?), ``apply`` (collect at the tested head and
re-seal the plan), ``shard`` (execute one node-plan shard against the subject), ``verify`` (independent re-collection in the gate job and the
trusted aggregator), ``seal`` (labelled CANDIDATE module plan for the not-required shadow workflow only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRUSTED_PLUGIN = "finco_ci_v4_trusted_nodes"
TRUSTED_CONF = "finco_ci_v4_trusted_pyconf"
ACTIVATION_SCHEMA = "FINCO_CI_V4_ACTIVATION_V1"
SPLIT_FIELDS = ("schedule", "node_split", "digest")       # the only plan fields activation may change


class ActivationError(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def trusted_policies(trusted=ROOT):
    """(node-split policy, worker/selection policy, node-split policy bytes SHA-256) read from the TRUSTED tree only."""
    from tools.ci_v4_schedule import load_node_split_policy
    split_path = Path(trusted) / "docs/ci_v4/node_split_policy.json"
    split = load_node_split_policy(split_path)
    policy = json.loads((Path(trusted) / "docs/ci_v4/ci-v4-policy.json").read_text())
    return split, policy, _sha(split_path.read_bytes())


def check_sealed(plan, policy):
    """The plan must be the trusted selector's sealed output: intact digest, and selected under THIS trusted policy."""
    from tools.ci_v4_aggregate import AggregateError, verify_plan_digest
    from tools.ci_v4_select import policy_digest
    try:
        verify_plan_digest(plan)
    except AggregateError as exc:
        raise ActivationError(str(exc)) from exc
    if plan.get("policy_digest") != policy_digest(policy):
        raise ActivationError("plan was not selected under the trusted base policy (policy digest mismatch)")
    if "node_split" in plan or "units" in plan.get("schedule", {}):
        raise ActivationError("plan is already a node plan (activation runs once, on the sealed module plan)")


def check_subject(plan, subject):
    head, tree = _git(subject, "rev-parse", "HEAD"), _git(subject, "rev-parse", "HEAD^{tree}")
    if (head, tree) != (plan["tested_sha"], plan["tested_tree"]):
        raise ActivationError("subject checkout %s/%s is not the planned source %s/%s" % (head, tree, plan["tested_sha"], plan["tested_tree"]))


def decide(plan, split_policy):
    """Which selected modules the TRUSTED policy would split (empty: keep the module plan). Never reads the PR head's policy."""
    if not split_policy["enabled_in_required_pr_gate"]:
        return {"decision": "module_plan", "reason": "trusted base node-split policy is disabled for the required gate", "eligible": []}
    eligible = sorted(set(plan["pytest_modules"]) & set(split_policy["modules"]))
    if not eligible:
        return {"decision": "module_plan", "reason": "no selected module is on the trusted node-split allowlist", "eligible": []}
    return {"decision": "collect", "reason": "selected allowlisted modules", "eligible": eligible}


def materialize_plugin(dest, trusted=ROOT):
    """Copy the TRUSTED node plugin and its pytest-config helper into ``dest`` under unique module names. Returns (dir, SHA-256 of both)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    nodes = (Path(trusted) / "tools/ci_v4_nodes.py").read_text()
    conf = (Path(trusted) / "tools/ci_v3_pytest_config.py").read_text()
    if nodes.count("from tools.ci_v3_pytest_config import") < 2:
        raise ActivationError("trusted plugin layout changed; refusing to materialize")
    nodes = nodes.replace("from tools.ci_v3_pytest_config import", "from %s import" % TRUSTED_CONF)
    (dest / (TRUSTED_PLUGIN + ".py")).write_text(nodes)
    (dest / (TRUSTED_CONF + ".py")).write_text(conf)
    digest = _sha((dest / (TRUSTED_PLUGIN + ".py")).read_bytes() + b"\0" + (dest / (TRUSTED_CONF + ".py")).read_bytes())
    return dest, digest


def check_invariants(original, split):
    """The node plan may differ from the sealed module plan ONLY in schedule/node_split/digest, and must partition exactly."""
    from tools.ci_v4_schedule import plan_digest
    changed = sorted(k for k in set(original) | set(split) if k not in SPLIT_FIELDS and original.get(k) != split.get(k))
    if changed:
        raise ActivationError("node split changed selection fields: %s" % changed)
    if plan_digest(split) != split.get("digest"):
        raise ActivationError("node plan digest mismatch")
    sched, ns = split["schedule"], split["node_split"]
    if len(sched["units"]) != len(sched["shards"]) or not all(sched["units"]):
        raise ActivationError("units/shards mismatch or empty shard")
    if {u["module"] for s in sched["units"] for u in s} != set(original["pytest_modules"]):
        raise ActivationError("planned module union differs from the selected modules")
    for s, us in zip(sched["shards"], sched["units"]):
        if sorted(s) != sorted({u["module"] for u in us}):
            raise ActivationError("a shard's module list differs from its units")
    whole = [u["module"] for s in sched["units"] for u in s if u["kind"] == "module"]
    if len(whole) != len(set(whole)) or set(whole) & set(ns["modules"]):
        raise ActivationError("a whole module is planned twice or is also split")
    for m, meta in ns["modules"].items():
        parts = [n for s in sched["units"] for u in s if u["kind"] == "nodes" and u["module"] == m for n in u["node_ids"]]
        if sorted(parts) != sorted(meta["node_ids"]) or len(parts) != len(set(parts)):
            raise ActivationError("units of %s do not partition its collected nodes exactly once" % m)


def apply(plan_path, subject, workdir, evidence, trusted=ROOT, split_policy=None, policy=None, trusted_sha=None):
    """Seal check -> trusted decision -> (collect at the tested head with the trusted plugin -> trusted split -> invariants -> re-seal)."""
    from tools.ci_v4_nodes import collect
    from tools.ci_v4_schedule import apply_node_split, load_node_weights, load_weights, plan_digest
    plan_path, evidence = Path(plan_path), Path(evidence)
    plan = json.loads(plan_path.read_text())
    if split_policy is None:
        split_policy, policy, policy_sha = trusted_policies(trusted)
    else:
        policy_sha = _sha(json.dumps(split_policy, sort_keys=True).encode())
    check_sealed(plan, policy)
    check_subject(plan, subject)
    record = {"schema": ACTIVATION_SCHEMA, "original_plan_digest": plan["digest"], "tested_sha": plan["tested_sha"],
              "trusted_base_sha": trusted_sha or _git(trusted, "rev-parse", "HEAD"), "node_split_policy_sha256": policy_sha,
              "python": platform.python_version(), **decide(plan, split_policy)}
    if record["decision"] == "collect":
        plugin_dir, plugin_sha = materialize_plugin(workdir, trusted)
        inv = collect(record["eligible"], evidence / "node-inventory.json", root=subject, plugin=TRUSTED_PLUGIN, plugin_path=plugin_dir)
        split = apply_node_split(plan, inv, split_policy, load_weights(), load_node_weights(), policy)
        if split is plan:
            record.update(decision="module_plan", reason="allowlisted modules selected but below the split target")
        else:
            split["node_split"]["activation"] = {"trusted_base_sha": record["trusted_base_sha"], "node_split_policy_sha256": policy_sha,
                                                 "plugin": TRUSTED_PLUGIN, "plugin_sha256": plugin_sha, "python": record["python"],
                                                 "original_plan_digest": plan["digest"], "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
            split["digest"] = plan_digest(split)
            check_invariants(plan, split)
            (evidence / "ci-v4-module-plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True))
            plan_path.write_text(json.dumps(split, indent=2, sort_keys=True))
            record.update(decision="node_plan", plan_digest=split["digest"], plugin_sha256=plugin_sha,
                          workers=split["schedule"]["workers"], split_modules=sorted(split["node_split"]["modules"]))
    (evidence / "node-split-activation.json").write_text(json.dumps(record, indent=2, sort_keys=True))
    return record


def _check_activation(plan, trusted_sha, plugin_sha):
    act = plan.get("node_split", {}).get("activation") or {}
    if act.get("trusted_base_sha") != trusted_sha:
        raise ActivationError("node plan was activated by %s, not by the trusted base %s" % (act.get("trusted_base_sha"), trusted_sha))
    if act.get("plugin") != TRUSTED_PLUGIN or act.get("plugin_sha256") != plugin_sha:
        raise ActivationError("node plan was collected with a different plugin than the trusted one")


def shard(plan_path, index, subject, workdir, output, trusted_sha, tmp_mode="disk", trusted=ROOT):
    """Execute ONE node-plan shard against the subject with the trusted plugin (whole modules + exact assigned node ids)."""
    from tools.ci_v4_schedule import plan_digest
    from tools.ci_v4_shard import assignment, choose_tmp
    from tools.ci_v3_pytest_config import plugin_args
    plan = json.loads(Path(plan_path).read_text())
    if "node_split" not in plan or plan_digest(plan) != plan.get("digest"):
        raise ActivationError("not a sealed node plan")
    plugin_dir, plugin_sha = materialize_plugin(workdir, trusted)
    _check_activation(plan, trusted_sha, plugin_sha)
    check_subject(plan, subject)
    shards = plan["schedule"]["shards"]
    if not 0 <= index < len(shards) or len(plan["schedule"]["units"]) != len(shards):
        raise ActivationError("no shard %d in plan (workers=%d)" % (index, len(shards)))
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    assign = assignment(plan, index)
    (out / ("assign-shard-%d.json" % index)).write_text(json.dumps(assign, indent=1, sort_keys=True))
    evidence = out / ("nodes-shard-%d.json" % index)
    junit = out / ("junit-shard-%d.xml" % index)
    tmp, tmp_rec = choose_tmp(tmp_mode, index)
    env = {k: v for k, v in os.environ.items() if not k.startswith("FINCO_CI_V4_NODE_")}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(plugin_dir), FINCO_CI_V4_NODE_ASSIGN=str(out / ("assign-shard-%d.json" % index)),
               FINCO_CI_V4_NODE_EVIDENCE=str(evidence))
    if tmp is not None:
        env.update(TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp))
    targets = sorted(set(assign["whole"]) | set(assign["split"]))
    t0 = time.monotonic()
    try:
        rc = subprocess.call([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *plugin_args(), "-p", TRUSTED_PLUGIN,
                              "--junitxml", str(junit), *targets], cwd=subject, env=env)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    record = {"shard": index, "sha": plan["tested_sha"], "tree": plan["tested_tree"], "plan_digest": plan["digest"], "modules": shards[index],
              "units": plan["schedule"]["units"][index], "node_evidence": evidence.name, "tmp": tmp_rec, "pytest_exit": rc,
              "wall_s": round(time.monotonic() - t0, 1), "executor": {"trusted_base_sha": trusted_sha, "plugin": TRUSTED_PLUGIN,
                                                                      "plugin_sha256": plugin_sha, "python": platform.python_version()}}
    (out / ("shard-%d.json" % index)).write_text(json.dumps(record, indent=2, sort_keys=True))
    return rc


def verify(plan_path, subject, shards_dir, workdir, output, trusted_sha, trusted=ROOT):
    """Gate job: independent re-collection of every split module at the tested head (trusted plugin, THIS job), then the trusted aggregator."""
    from tools.ci_v4_aggregate import AggregateError, aggregate
    from tools.ci_v4_nodes import collect
    plan = json.loads(Path(plan_path).read_text())
    if "node_split" not in plan:
        raise ActivationError("verify is for node plans; module plans use the unchanged aggregator")
    plugin_dir, plugin_sha = materialize_plugin(workdir, trusted)
    _check_activation(plan, trusted_sha, plugin_sha)
    check_subject(plan, subject)
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    inventory = collect(sorted(plan["node_split"]["modules"]), out / "independent-inventory.json", root=subject,
                        plugin=TRUSTED_PLUGIN, plugin_path=plugin_dir)
    shards_dir = Path(shards_dir)
    records = [json.loads(p.read_text()) for p in sorted(shards_dir.glob("**/shard-*.json"))]
    junit = sorted(shards_dir.glob("**/*.xml"))
    evidence = {}
    for p in sorted(shards_dir.glob("**/nodes-shard-*.json")):
        idx = p.name[len("nodes-shard-"):-5]
        if not idx.isdigit() or int(idx) in evidence:
            raise ActivationError("unexpected or duplicate node evidence %s" % p.name)
        evidence[int(idx)] = json.loads(p.read_text())
    try:
        if not records or not junit:
            raise AggregateError("no shard evidence / junit found")
        res = aggregate(plan, records, junit, node_evidence=evidence, inventory=inventory)
    except AggregateError as exc:
        res = {"verdict": "FAIL", "problems": ["aggregate fail closed: %s" % exc], "executed_nodes": 0, "counts": {}}
    res["verifier"] = {"trusted_base_sha": trusted_sha, "plugin_sha256": plugin_sha, "python": platform.python_version(),
                       "independent_inventory_digest": inventory["digest"]}
    (out / "ci-v4-result.json").write_text(json.dumps(res, indent=2, sort_keys=True))
    return res


def seal(modules, tier, subject, output, trusted=ROOT):
    """CANDIDATE module plan for the NOT REQUIRED shadow workflow (a fixed module list stands in for the selector's output)."""
    from tools.ci_v4_schedule import load_weights, plan_digest, plan_shards
    from tools.ci_v4_select import policy_digest
    policy = json.loads((Path(trusted) / "docs/ci_v4/ci-v4-policy.json").read_text())
    mods = sorted(set(modules))
    plan = {"schema": "FINCO_CI_V4_PLAN_V1", "event": "candidate_activation", "tier": tier, "shadow": True, "required": False,
            "label": "CANDIDATE ACTIVATION - NOT REQUIRED - never satisfies the CI V4 gate",
            "tested_sha": _git(subject, "rev-parse", "HEAD"), "tested_tree": _git(subject, "rev-parse", "HEAD^{tree}"),
            "policy_digest": policy_digest(policy), "pytest_modules": mods, "no_skip_modules": mods, "suites": [], "rule_ids": ["candidate"],
            "triggers": [], "not_selected": {"count": 0, "label": "NOT SELECTED (not PASS)"}}
    plan["schedule"] = plan_shards(mods, load_weights(), tier, policy)
    plan["digest"] = plan_digest(plan)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(plan, indent=2, sort_keys=True))
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide"); d.add_argument("--plan", required=True); d.add_argument("--output", required=True)
    a = sub.add_parser("apply")
    for x in (a,):
        x.add_argument("--plan", required=True); x.add_argument("--subject", required=True); x.add_argument("--workdir", required=True)
        x.add_argument("--evidence", required=True); x.add_argument("--trusted-sha", default=None)
    s = sub.add_parser("shard")
    s.add_argument("--plan", required=True); s.add_argument("--index", type=int, required=True); s.add_argument("--subject", required=True)
    s.add_argument("--workdir", required=True); s.add_argument("--output", required=True); s.add_argument("--trusted-sha", required=True)
    s.add_argument("--tmp", choices=("disk", "auto", "tmpfs"), default="disk")
    v = sub.add_parser("verify")
    v.add_argument("--plan", required=True); v.add_argument("--subject", required=True); v.add_argument("--shards", required=True)
    v.add_argument("--workdir", required=True); v.add_argument("--output", required=True); v.add_argument("--trusted-sha", required=True)
    c = sub.add_parser("seal"); c.add_argument("--subject", required=True); c.add_argument("--output", required=True)
    c.add_argument("--tier", default="risk"); c.add_argument("modules", nargs="+")
    o = ap.parse_args(argv)
    try:
        if o.cmd == "decide":
            split_policy, policy, sha = trusted_policies()
            plan = json.loads(Path(o.plan).read_text())
            check_sealed(plan, policy)
            rec = dict(decide(plan, split_policy), node_split_policy_sha256=sha)
            Path(o.output).write_text(json.dumps(rec, indent=2, sort_keys=True))
            print("decision=%s eligible=%s" % (rec["decision"], rec["eligible"]))
        elif o.cmd == "apply":
            rec = apply(o.plan, o.subject, o.workdir, o.evidence, trusted_sha=o.trusted_sha)
            print("activation: %s (%s)" % (rec["decision"], rec["reason"]))
        elif o.cmd == "shard":
            return 0 if shard(o.plan, o.index, o.subject, o.workdir, o.output, o.trusted_sha, o.tmp) == 0 else 1
        elif o.cmd == "verify":
            res = verify(o.plan, o.subject, o.shards, o.workdir, o.output, o.trusted_sha)
            print("%s executed=%s problems=%s" % (res["verdict"], res.get("executed_nodes"), res["problems"]))
            return 0 if res["verdict"] == "PASS" else 1
        else:
            plan = seal(o.modules, o.tier, o.subject, o.output)
            print("candidate module plan: %d modules" % len(plan["pytest_modules"]))
    except (ActivationError, subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
        print("CI V4 activation FAIL CLOSED: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
