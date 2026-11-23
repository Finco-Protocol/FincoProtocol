"""CI V4 exact pytest node identity: collection inventory, bounded node assignment and per-node execution evidence.

Loaded explicitly as a pytest plugin (``-p tools.ci_v4_nodes``) and inert unless one of its environment variables is set:

* ``FINCO_CI_V4_NODE_COLLECT=<file>``  - collect-only run: write the ordered ``item.nodeid`` inventory of every collected module.
* ``FINCO_CI_V4_NODE_ASSIGN=<file>``   - execution run: the shard's assignment (whole modules + exact node ids of split modules). Before anything
  runs, the FULL collection of every split module must equal the planned inventory (same ordered ids, same digest); every assigned id must be
  collected; no foreign module may be collected. Only the assigned items are kept; the rest is reported as deselected (never run, never PASS).
  Any disagreement aborts the session (``pytest.UsageError``) before a single test runs.
* ``FINCO_CI_V4_NODE_EVIDENCE=<file>`` - per node: phase outcomes and duration, the final session exit status, the plugin/conftest profile.
  The file is written only at ``pytest_unconfigure``; an interrupted or killed session leaves no evidence (the aggregator fails closed).

The command line (``python -m tools.ci_v4_nodes collect|plan|calibrate``) builds an inventory, a shadow node plan and a filesystem calibration.
Nothing here selects or deselects a MODULE: selection stays with the trusted-base selector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_COLLECT = "FINCO_CI_V4_NODE_COLLECT"
ENV_ASSIGN = "FINCO_CI_V4_NODE_ASSIGN"
ENV_EVIDENCE = "FINCO_CI_V4_NODE_EVIDENCE"
PLUGIN = "tools.ci_v4_nodes"
INVENTORY_SCHEMA = "FINCO_CI_V4_NODE_INVENTORY_V1"
EVIDENCE_SCHEMA = "FINCO_CI_V4_NODE_EVIDENCE_V1"
ASSIGN_SCHEMA = "FINCO_CI_V4_NODE_ASSIGN_V1"


class NodeError(ValueError):
    pass


# ── pure helpers (also used by the scheduler and the aggregator) ──────────────────────────────────────────────────────────────────────────

def ids_digest(ids):
    """SHA-256 over the ORDERED node ids (one per line). Order is part of the identity: a re-ordered collection is a different collection."""
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def module_of(nodeid):
    return nodeid.split("::", 1)[0]


def junit_address(nodeid):
    """(classname, name) exactly as pytest's junitxml derives them (``_pytest.junitxml.mangle_test_address``, no prefix)."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def node_outcome(phases):
    """One outcome per node from its phase reports. A failing setup/teardown is an error, a failing call a failure; no call phase and no
    skip/failure means the node never completed (``incomplete``), which is never a pass."""
    for when in ("setup", "call", "teardown"):
        if phases.get(when) == "failed":
            return "failed" if when == "call" else "error"
    if "skipped" in phases.values():
        return "skipped"
    if phases.get("call") == "passed":
        return "passed"
    return "incomplete"


def profile(config):
    """Plugin/conftest profile of this pytest process: every registration (process addresses and conftest roots normalized), file hashes,
    pytest and Python versions. Collection and execution must present the same profile digest."""
    import pytest
    from tools.ci_v3_pytest_config import all_plugin_registrations, semantic_plugin_profile
    regs = [r for r in semantic_plugin_profile(all_plugin_registrations(config))]
    body = {"pytest": pytest.__version__, "python": platform.python_version(), "implementation": platform.python_implementation(),
            "autoload_disabled": os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1", "registrations": regs}
    return body, hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ── pytest plugin ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

_STATE = {"session": None, "collected": None, "kept": None, "nodes": {}, "profile": None, "assign": None}


def _per_module(nodeids):
    out = {}
    for n in nodeids:
        out.setdefault(module_of(n), []).append(n)
    return out


def pytest_sessionstart(session):
    _STATE["session"] = session


def _active():
    return any(os.environ.get(k) for k in (ENV_COLLECT, ENV_ASSIGN, ENV_EVIDENCE))


def pytest_collection_modifyitems(session, config, items):
    """Runs LAST (after conftest/other plugins): the observed list is the final collection."""
    if not _active():
        return
    import pytest
    collected = _per_module([it.nodeid for it in items])
    _STATE["collected"] = collected
    _STATE["profile"] = profile(config)
    path = os.environ.get(ENV_ASSIGN)
    if not path:
        return
    data = json.loads(Path(path).read_text())
    if data.get("schema") != ASSIGN_SCHEMA:
        raise pytest.UsageError("CI V4 node assignment: unknown schema")
    _STATE["assign"] = data
    whole, split = set(data["whole"]), data["split"]
    foreign = sorted(set(collected) - whole - set(split))
    if foreign:
        raise pytest.UsageError("CI V4 node assignment: collected modules outside the assignment: %s" % foreign[:5])
    keep_ids = set()
    for module, spec in sorted(split.items()):
        got = collected.get(module, [])
        if len(got) != spec["count"] or ids_digest(got) != spec["digest"]:
            raise pytest.UsageError("CI V4 node assignment: collection of %s (%d nodes, %s) differs from the planned inventory (%d, %s)"
                                    % (module, len(got), ids_digest(got)[:12], spec["count"], spec["digest"][:12]))
        keep = spec["keep"]
        if len(keep) != len(set(keep)) or not keep:
            raise pytest.UsageError("CI V4 node assignment: empty or duplicated node list for %s" % module)
        missing = sorted(set(keep) - set(got))
        if missing:
            raise pytest.UsageError("CI V4 node assignment: assigned nodes not collected: %s" % missing[:5])
        keep_ids |= set(keep)
    for module in whole:
        if not collected.get(module):
            raise pytest.UsageError("CI V4 node assignment: whole module %s collected no node" % module)
    kept = [it for it in items if module_of(it.nodeid) in whole or it.nodeid in keep_ids]
    dropped = [it for it in items if not (module_of(it.nodeid) in whole or it.nodeid in keep_ids)]
    items[:] = kept
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    _STATE["kept"] = [it.nodeid for it in kept]


def _mark_trylast():
    try:
        import pytest
        globals()["pytest_collection_modifyitems"] = pytest.hookimpl(trylast=True)(pytest_collection_modifyitems)
    except ImportError:          # importing the helpers without pytest (aggregator, scheduler) is fine
        pass


_mark_trylast()


def pytest_runtest_logreport(report):
    if not _active():
        return
    rec = _STATE["nodes"].setdefault(report.nodeid, {"phases": {}, "duration": 0.0})
    rec["phases"][report.when] = report.outcome
    rec["duration"] = round(rec["duration"] + float(getattr(report, "duration", 0.0) or 0.0), 6)


def pytest_unconfigure(config):
    session = _STATE["session"]
    exitstatus = int(getattr(session, "exitstatus", -1)) if session is not None else -1
    prof, prof_digest = _STATE["profile"] or (None, None)
    collected = _STATE["collected"] or {}
    inventory = {m: {"node_ids": ids, "count": len(ids), "digest": ids_digest(ids)} for m, ids in collected.items()}
    if os.environ.get(ENV_COLLECT):
        Path(os.environ[ENV_COLLECT]).write_text(json.dumps({
            "schema": INVENTORY_SCHEMA, "complete": True, "exitstatus": exitstatus, "profile": prof, "profile_digest": prof_digest,
            "modules": inventory}, indent=1, sort_keys=True))
    if os.environ.get(ENV_EVIDENCE):
        assign = _STATE["assign"] or {}
        nodes = {n: {"outcome": node_outcome(r["phases"]), "phases": r["phases"], "duration": r["duration"]} for n, r in _STATE["nodes"].items()}
        Path(os.environ[ENV_EVIDENCE]).write_text(json.dumps({
            "schema": EVIDENCE_SCHEMA, "complete": True, "exitstatus": exitstatus,
            "binding": {k: assign.get(k) for k in ("tested_sha", "tested_tree", "plan_digest", "shard")},
            "profile_digest": prof_digest, "profile": prof,
            "collected": {m: {"count": v["count"], "digest": v["digest"]} for m, v in inventory.items()},
            "kept": _STATE["kept"], "nodes": nodes}, indent=1, sort_keys=True))


# ── command line ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def _pytest_argv(extra, plugin=PLUGIN):
    from tools.ci_v3_pytest_config import plugin_args
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *plugin_args(), "-p", plugin, *extra]


def collect(modules, output, root=ROOT, plugin=PLUGIN, plugin_path=None):
    """Collect the exact node inventory of ``modules`` at the checked-out commit with the SAME plugin profile as shard execution.

    ``plugin``/``plugin_path``: the plugin module name and the directory it is imported from. The trusted-base activation
    (tools/ci_v4_activate.py) passes an isolated copy of the TRUSTED plugin so the PR head's own plugin never measures its own tests."""
    root = Path(root)
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise NodeError("collection needs a clean tracked tree")
    out = Path(output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".raw.json")
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", **{ENV_COLLECT: str(tmp)})
    if plugin_path is not None:
        env["PYTHONPATH"] = str(plugin_path)
    env.pop(ENV_ASSIGN, None); env.pop(ENV_EVIDENCE, None)
    # --junitxml registers the same reporter plugin as a shard does, so collection and execution present the SAME plugin profile
    rc = subprocess.call(_pytest_argv(["-rs", "--collect-only", "--junitxml", str(out.with_suffix(".collect.xml")), *sorted(set(modules))], plugin),
                         cwd=root, env=env, stdout=subprocess.DEVNULL)
    out.with_suffix(".collect.xml").unlink(missing_ok=True)
    if rc != 0 or not tmp.is_file():
        raise NodeError("collection failed (pytest exit %s)" % rc)
    raw = json.loads(tmp.read_text()); tmp.unlink()
    if not raw.get("complete") or raw.get("exitstatus") != 0:
        raise NodeError("collection incomplete")
    mods = raw["modules"]
    if set(mods) != set(modules):
        raise NodeError("collected modules %s differ from requested %s" % (sorted(mods), sorted(set(modules))))
    for m, spec in mods.items():
        ids = spec["node_ids"]
        if not ids or len(ids) != len(set(ids)) or any(module_of(i) != m for i in ids):
            raise NodeError("bad node inventory for %s" % m)
        if len({junit_address(i) for i in ids}) != len(ids):
            raise NodeError("node ids of %s are not losslessly identifiable in JUnit" % m)
    inv = {"schema": INVENTORY_SCHEMA, "tested_sha": _git(root, "rev-parse", "HEAD"), "tested_tree": _git(root, "rev-parse", "HEAD^{tree}"),
           "profile": raw["profile"], "profile_digest": raw["profile_digest"], "modules": mods}
    inv["digest"] = hashlib.sha256(json.dumps({k: v for k, v in inv.items() if k != "digest"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    out.write_text(json.dumps(inv, indent=1, sort_keys=True))
    return inv


def verify_inventory(inv):
    body = {k: v for k, v in inv.items() if k != "digest"}
    if inv.get("schema") != INVENTORY_SCHEMA or inv.get("digest") != hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
        raise NodeError("inventory digest mismatch")
    for m, spec in inv["modules"].items():
        if spec["count"] != len(spec["node_ids"]) or spec["digest"] != ids_digest(spec["node_ids"]):
            raise NodeError("inventory of %s is internally inconsistent" % m)
    return inv


def shadow_plan(modules, inventory, tier, output, root=ROOT):
    """A labelled, NOT REQUIRED benchmark plan for ``modules`` (selection is the caller's fixed list, never a selector decision)."""
    from tools import ci_v4_schedule as S
    policy = json.loads((Path(root) / "docs/ci_v4/ci-v4-policy.json").read_text())
    base = {"schema": "FINCO_CI_V4_PLAN_V1", "event": "shadow_benchmark", "tier": tier, "shadow": True, "required": False,
            "label": "SHADOW BENCHMARK - NOT REQUIRED - never satisfies the CI V4 gate",
            "tested_sha": inventory["tested_sha"], "tested_tree": inventory["tested_tree"], "base_sha": None,
            "changed_paths": [], "triggers": [], "rule_ids": ["shadow_node_split_benchmark"], "suites": [],
            "pytest_modules": sorted(set(modules)), "no_skip_modules": sorted(set(modules)),
            "not_selected": {"count": 0, "label": "NOT SELECTED (not PASS)"}}
    base["schedule"] = S.plan_shards(sorted(set(modules)), S.load_weights(), tier, policy)
    base["digest"] = S.plan_digest(base)
    plan = S.apply_node_split(base, inventory, S.load_node_split_policy(), S.load_weights(), S.load_node_weights(), policy, shadow=True)
    Path(output).write_text(json.dumps(plan, indent=1, sort_keys=True))
    return plan


CALIBRATE_CODE = r"""
import importlib, json, sys, time, subprocess
calls = [0]; orig = subprocess.check_output
def counted(*a, **k):
    calls[0] += 1; return orig(*a, **k)
subprocess.check_output = counted
t = time.monotonic(); import tests.fin_v2_cohorts as C; imp = time.monotonic() - t
out = {"import_s": round(imp, 3), "composite_valid_s": [], "composite_ok": None}
for _ in range(3):
    t = time.monotonic(); ok = C.valid(); out["composite_valid_s"].append(round(time.monotonic() - t, 3)); out["composite_ok"] = ok
D = importlib.import_module("tests.fin_v2_d01_scope"); import tests.wf06b_scope as W
path = sorted(set(D.manifest()["source_blobs"]) - W.SUPERSEDED)[0]
raw = (W.ROOT / path).read_bytes(); c0 = calls[0]
t = time.monotonic(); refused = D.matches(path, raw + b"\n") is False
out.update({"one_matches_call_s": round(time.monotonic() - t, 3), "one_matches_git_calls": calls[0] - c0, "refused": refused, "git_calls_total": calls[0]})
print(json.dumps(out))
"""


def calibrate(output, root=ROOT, tmpfs="/dev/shm"):
    """Same SHA, same Python, same code: the per-call cost of the cohort composite on the runner's disk checkout vs an exact clone on tmpfs."""
    root = Path(root)
    head = _git(root, "rev-parse", "HEAD")
    rows = {"tested_sha": head, "tested_tree": _git(root, "rev-parse", "HEAD^{tree}"), "runs": []}
    targets = [("disk_checkout", root)]
    shm = Path(tmpfs)
    if shm.is_dir() and os.access(shm, os.W_OK):
        st = os.statvfs(shm)
        rows["tmpfs_free_bytes"] = st.f_bavail * st.f_frsize
        if rows["tmpfs_free_bytes"] >= 2 * 1024 ** 3:
            clone = shm / "ci-v4-calibrate"
            subprocess.check_call(["git", "clone", "--quiet", "--no-local", "--no-checkout", str(root), str(clone)])
            subprocess.check_call(["git", "-C", str(clone), "checkout", "--quiet", "--detach", head])
            targets.append(("tmpfs_clone", clone))
    for label, where in targets:
        t = time.monotonic()
        res = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r)\n" % str(where) + CALIBRATE_CODE],
                             cwd=where, capture_output=True, text=True)
        row = {"target": label, "wall_s": round(time.monotonic() - t, 3), "rc": res.returncode}
        try:
            row.update(json.loads(res.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            row["stderr_tail"] = res.stderr[-2000:]
        rows["runs"].append(row)
    Path(output).write_text(json.dumps(rows, indent=1, sort_keys=True))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--output", required=True); c.add_argument("modules", nargs="+")
    p = sub.add_parser("plan"); p.add_argument("--inventory", required=True); p.add_argument("--tier", default="risk", choices=("fast", "risk", "full"))
    p.add_argument("--output", required=True); p.add_argument("modules", nargs="+")
    k = sub.add_parser("calibrate"); k.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "collect":
            inv = collect(a.modules, a.output)
            print("collected %s" % {m: v["count"] for m, v in sorted(inv["modules"].items())})
        elif a.cmd == "plan":
            plan = shadow_plan(a.modules, verify_inventory(json.loads(Path(a.inventory).read_text())), a.tier, a.output)
            print("shadow plan: workers=%d units=%d" % (plan["schedule"]["workers"], sum(len(u) for u in plan["schedule"].get("units", []))))
        else:
            print(json.dumps(calibrate(a.output), indent=1))
    except NodeError as exc:
        print("CI V4 nodes FAIL CLOSED: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
