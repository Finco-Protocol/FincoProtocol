"""P2: parallel, exact-inventory CI V4 FULL regression controller and its strict, authenticated release record. Fails closed.

Replaces the sequential, unsharded FULL step (one pytest process, 19,200 s budget, never finished) with disjoint shards whose union is
proven equal to ONE exact collection of the tested commit. Nothing is selected, skipped or deselected to fit a time target:

* ``plan``      collect EVERY pytest node of the checked-out commit once (the unchanged trusted ``tools.ci_v4_nodes`` plugin, the same plugin
                profile as execution); record collection-level skips and refuse collection errors; assign every module whole, or (only for a
                literal allowlist with a recorded isolation proof) as exact node-id parts, to an adaptively chosen number of shards; seal it.
* ``shard``     run exactly one sealed assignment in a fresh pytest process. The plugin aborts before any test runs unless the collection
                of EVERY assigned module equals the planned inventory (count and ordered-id digest). Bounded by a hard wall-clock limit.
* ``recollect`` an independent re-collection in another job (concurrent with the shards; never on the critical path).
* ``record``    download every artifact of THIS run attempt through the GitHub API, require each zip's SHA-256 to equal GitHub's digest,
                and require: plan seal intact and bound to this sha/tree/run/attempt; independent inventory == planned inventory; every shard
                present exactly once, bound to the plan, exit 0, within its limit, same plugin profile; executed nodes == collected nodes as a
                disjoint union (no omission, duplicate or foreign node, every node completed); JUnit reconciles 1:1 with the per-node evidence;
                collection skips reproduced; every skip is in the reviewed skip baseline (a skip is never a pass); F01 browser (4) + native (20)
                evidence present and unskipped. Any missing artifact, forged/partial JUnit, digest mismatch, stale sha, duplicate, timeout or API
                failure makes the record ``fail``. The record keeps the FINCO_CI_V4_FULL_RECORD_V1 fields the release gate already verifies.

Authority: a record is only ever a claim. The release gate and the V5 gate re-verify the GitHub run itself (repository, workflow path, event,
branch ``main``, exact sha, conclusion). A run on any other ref is labelled ``BENCHMARK_NOT_AUTHORITY``.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "ci_v4" / "p2_full" / "full_parallel_policy.json"
POLICY_SCHEMA = "FINCO_CI_FULL_PARALLEL_POLICY_V1"
INVENTORY_SCHEMA = "FINCO_CI_FULL_INVENTORY_V1"
PLAN_SCHEMA = "FINCO_CI_FULL_PARALLEL_PLAN_V1"
SHARD_SCHEMA = "FINCO_CI_FULL_SHARD_V1"
RECORD_SCHEMA = "FINCO_CI_V4_FULL_RECORD_V1"           # the release gate's schema; the strict section is additive
STRICT_SCHEMA = "FINCO_CI_FULL_STRICT_RECORD_V1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TIMEOUT_EXIT = 124
MAX_MEMBER_BYTES = 256 * 1024 * 1024


class FullError(ValueError):
    pass


def _need(cond, msg):
    if not cond:
        raise FullError(msg)


def canonical_digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal(obj):
    out = {k: v for k, v in obj.items() if k != "digest"}
    out["digest"] = canonical_digest(out)
    return out


def check_seal(obj, what):
    _need(isinstance(obj, dict) and obj.get("digest") == canonical_digest({k: v for k, v in obj.items() if k != "digest"}),
          "%s seal mismatch (tampered or partial)" % what)
    return obj


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()


def source(root):
    return {"sha": git(root, "rev-parse", "HEAD"), "tree": git(root, "rev-parse", "HEAD^{tree}")}


# ── policy ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_policy(path=POLICY_PATH):
    return validate_policy(json.loads(Path(path).read_text()))


def validate_policy(p):
    _need(isinstance(p, dict) and p.get("schema") == POLICY_SCHEMA, "unknown FULL parallel policy schema")
    w = p.get("workers", {})
    _need(isinstance(w.get("min"), int) and isinstance(w.get("max"), int) and 1 <= w["min"] <= w["max"] <= 64, "worker bounds out of range")
    for k in ("per_worker_overhead_s", "target_test_critical_path_s", "min_gain_s_per_extra_worker"):
        _need(isinstance(w.get(k), (int, float)) and w[k] >= 0, "worker field %s missing" % k)
    _need(isinstance(p.get("shard_timeout_s"), int) and 300 <= p["shard_timeout_s"] <= 7200, "shard timeout out of range")
    _need(isinstance(p.get("min_collected_nodes"), int) and p["min_collected_nodes"] >= 1, "minimum collected nodes missing")
    _need(p.get("skip_baseline") == "docs/ci_v4/full_skip_baseline.json", "skip baseline must be the reviewed release-gate baseline")
    split = p.get("node_split", {})
    _need(isinstance(split.get("modules"), dict) and isinstance(split.get("target_unit_s"), (int, float)) and split["target_unit_s"] >= 60
          and isinstance(split.get("max_parts"), int) and 2 <= split["max_parts"] <= 16, "node split policy malformed")
    for m, spec in split["modules"].items():
        _need(m.startswith("tests/") and m.endswith(".py") and "*" not in m and ".." not in m.split("/"), "split module must be a literal test path")
        _need(spec.get("verdict") in ("SPLIT_SAFE", "SPLIT_SAFE_FLOOR_LIMITED") and len(str(spec.get("isolation_proof", ""))) >= 40,
              "split module %s lacks a verdict / isolation proof" % m)
    scoped = p.get("scoped_modules")
    _need(isinstance(scoped, dict), "scoped_modules missing")
    for m, spec in scoped.items():
        _need(m.startswith("tests/test_") and m.endswith(".py") and "*" not in m and ".." not in m.split("/"), "scoped module must be a literal test path")
        _need(spec.get("verdict") == "READ_ONLY_PER_TEST_SCOPE_SAFE" and len(str(spec.get("proof", ""))) >= 80,
              "scoped module %s lacks a read-only proof" % m)
    nodes = p.get("scoped_nodes")
    _need(isinstance(nodes, dict), "scoped_nodes missing")
    for n, spec in nodes.items():
        mod, sep, name = n.partition("::")
        _need(sep == "::" and mod.startswith("tests/test_") and mod.endswith(".py") and name and not set(n) & set("*?[]!{} \n,")
              and ".." not in mod.split("/"), "scoped node must be one literal pytest node id (never a module or pattern): %r" % n)
        _need(mod not in scoped, "scoped node %s is inside a scoped module (one allowlist per node)" % n)
        _need(spec.get("verdict") == "READ_ONLY_PER_NODE_SCOPE_SAFE" and len(str(spec.get("proof", ""))) >= 80
              and str(spec.get("source", "")).startswith("docs/ci_v4/p2_full/"), "scoped node %s lacks a read-only proof" % n)
    f01 = p.get("f01", {})
    _need(f01.get("browser_cases") == 4 and f01.get("native_cases") == 20, "F01 acceptance counts are fixed (4 browser, 20 native)")
    return p


# ── collection ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

RECORDER = "finco_ci_full_recorder"
RECORDER_ENV = "FINCO_CI_FULL_RECORDER"
RECORDER_SCHEMA = "FINCO_CI_FULL_RECORDER_V1"
# Independent per-node recorder. The accepted node plugin decides "active" from os.environ on EVERY report, so a test that deletes those
# variables (tests/test_ci_v4_nodes.py's repo fixture does, via monkeypatch) silently loses its setup/call reports. This recorder binds its
# output path ONCE at configure time and removes the variable from the environment (no child process inherits it), so no test can switch
# it off; every phase report of this process is recorded. Materialized under a unique module name: no test imports it.
RECORDER_SOURCE = '''"""FINCO CI FULL per-node phase recorder (materialized copy; see tools/ci_full_parallel.py)."""
import json, os
_S = {"path": None, "pid": None, "nodes": {}, "session": None}


def pytest_configure(config):
    _S["path"] = os.environ.pop("FINCO_CI_FULL_RECORDER", None)
    _S["pid"] = os.getpid()
    _S["scoped"] = frozenset(m for m in os.environ.pop("FINCO_CI_FULL_SCOPED", "").split(",") if m)
    _S["scoped_calls"] = 0
    _S["scoped_nodes"] = frozenset(n for n in os.environ.pop("FINCO_CI_FULL_SCOPED_NODES", "").split("\\n") if n)
    _S["scoped_node_calls"] = []


import contextlib
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Literal allowlist only (policy ``scoped_modules``, each with a recorded read-only proof): the CALL phase of such a test is ONE outer
    governance call (tests.fin_v2_cohorts.call_scope, the scope the central gate itself uses) with content-addressed immutable Git reads
    (tests.ci_immutable_git_reads.scope). Both are dropped when the call returns: nothing is shared between tests, no assertion changes."""
    exact = item.nodeid in _S.get("scoped_nodes", ())       # policy ``scoped_nodes``: ONE literal node id, never its module
    if not exact and item.nodeid.split("::", 1)[0] not in _S.get("scoped", ()):
        yield
        return
    from tests import fin_v2_cohorts as C
    from tests import ci_immutable_git_reads as M
    _assert_closed = lambda: C._CALL or getattr(C, "_ENTERING", None)
    if _assert_closed():
        raise RuntimeError("a governance call scope is already open before a scoped test call")
    with contextlib.ExitStack() as stack:
        stack.enter_context(M.scope())
        stack.enter_context(C.call_scope())
        _S["scoped_calls"] += 1
        if exact:
            _S["scoped_node_calls"].append(item.nodeid)
        yield
    if _assert_closed():
        raise RuntimeError("a governance call scope outlived its test call")


def pytest_sessionstart(session):
    _S["session"] = session


def pytest_runtest_logreport(report):
    if _S["path"] is None or os.getpid() != _S["pid"]:
        return
    rec = _S["nodes"].setdefault(report.nodeid, {"phases": {}, "duration": 0.0})
    if report.when in rec["phases"]:
        rec["phases"][report.when] = "duplicate"
    else:
        rec["phases"][report.when] = report.outcome
    rec["duration"] = round(rec["duration"] + float(getattr(report, "duration", 0.0) or 0.0), 6)


def pytest_unconfigure(config):
    if _S["path"] is None or os.getpid() != _S["pid"]:
        return
    s = _S["session"]
    with open(_S["path"], "w") as f:
        json.dump({"schema": "FINCO_CI_FULL_RECORDER_V1", "complete": True, "exitstatus": int(getattr(s, "exitstatus", -1)) if s else -1,
                   "scoped_modules": sorted(_S.get("scoped", ())), "scoped_calls": _S.get("scoped_calls", 0),
                   "scoped_nodes": sorted(_S.get("scoped_nodes", ())), "scoped_node_calls": list(_S.get("scoped_node_calls", ())),
                   "nodes": _S["nodes"]}, f, sort_keys=True)
'''


def _pytest_base():
    """The execution plugin is the unchanged accepted ``tools/ci_v4_nodes.py``, materialized under the unique module name of
    ``tools.ci_v4_activate`` so that tests which exercise ``tools.ci_v4_nodes`` itself never touch the measuring instance; the independent
    recorder (above) is loaded the same way in collection and execution (identical plugin profile)."""
    from tools.ci_v3_pytest_config import plugin_args
    from tools.ci_v4_activate import TRUSTED_PLUGIN
    return [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *plugin_args(), "-p", TRUSTED_PLUGIN, "-p", RECORDER]


def plugin(root, workdir):
    """(directory, SHA-256 over both materialized plugins) - the accepted node plugin and the recorder."""
    from tools.ci_v4_activate import materialize_plugin
    d, sha = materialize_plugin(Path(workdir), Path(root))
    (d / (RECORDER + ".py")).write_text(RECORDER_SOURCE)
    return d, hashlib.sha256((sha + "\0" + hashlib.sha256(RECORDER_SOURCE.encode()).hexdigest()).encode()).hexdigest()


def _clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FINCO_CI_V4_NODE_", "FINCO_CI_FULL_"))}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.update(extra)
    return env


def parse_junit(raw):
    """Testcases of one JUnit document. DTD/entities refused; every case needs an identity and a valid time."""
    _need(b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw, "JUnit with DTD/entities is refused")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FullError("unreadable JUnit: %s" % exc) from None
    _need(root.tag in ("testsuites", "testsuite"), "not a JUnit document")
    cases = []
    for c in root.iter("testcase"):
        status = "passed"
        for tag in ("failure", "error", "skipped"):
            if c.find(tag) is not None:
                status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                break
        skip = c.find("skipped")
        try:
            t = float(c.get("time", "0"))
        except ValueError:
            t = float("nan")
        _need(t >= 0, "testcase with an invalid time")
        cases.append({"classname": c.get("classname", ""), "name": c.get("name", ""), "status": status, "time": t,
                      "skip_message": skip.get("message", "") if skip is not None else None,
                      "skip_text": (skip.text or "") if skip is not None else None,
                      "collection_skip": (not c.get("classname") and skip is not None and skip.get("message") == "collection skipped")})
    return cases


def collection_skips(cases):
    """{module path: reason} for pytest's collection-level skip reports (empty classname, dotted module name)."""
    import ast
    out = {}
    for c in cases:
        if not c["collection_skip"]:
            continue
        module = c["name"].replace(".", "/") + ".py"
        try:
            loc = ast.literal_eval(c["skip_text"] or "")
            reason = loc[2] if isinstance(loc, tuple) and len(loc) == 3 and isinstance(loc[2], str) else ""
        except (ValueError, SyntaxError):
            reason = ""
        _need(reason.startswith("Skipped: ") and module.startswith("tests/"), "malformed collection skip for %s" % c["name"])
        _need(module not in out, "duplicate collection skip for %s" % module)
        out[module] = reason
    return out


def collect(root, workdir):
    """ONE collection of the whole suite (pytest.ini testpaths) at the clean checked-out commit, with the execution plugin profile."""
    from tools.ci_v4_nodes import ids_digest, junit_address, module_of
    root, workdir = Path(root), Path(workdir)
    _need(not git(root, "status", "--porcelain", "--untracked-files=normal", "--ignored=no"), "collection needs a clean checkout (no change, no untracked file)")
    workdir.mkdir(parents=True, exist_ok=True)
    raw_inv, junit = workdir / "collect.raw.json", workdir / "collect.xml"
    plugin_dir, plugin_sha = plugin(root, workdir / "plugin")
    rc = subprocess.call(_pytest_base() + ["--collect-only", "--junitxml", str(junit)], cwd=root,
                         env=_clean_env(FINCO_CI_V4_NODE_COLLECT=str(raw_inv), PYTHONPATH=str(plugin_dir)), stdout=subprocess.DEVNULL)
    _need(rc == 0 and raw_inv.is_file() and junit.is_file(), "full collection failed (pytest exit %s): no plan without a complete collection" % rc)
    raw = json.loads(raw_inv.read_text())
    _need(raw.get("complete") is True and raw.get("exitstatus") == 0, "collection incomplete")
    cases = parse_junit(junit.read_bytes())
    _need(not [c for c in cases if c["status"] in ("failed", "error")], "collection errors: no plan")
    skips = collection_skips(cases)
    modules = {}
    for m, spec in sorted(raw["modules"].items()):
        ids = spec["node_ids"]
        _need(ids and len(ids) == len(set(ids)) and all(module_of(i) == m for i in ids), "bad node inventory for %s" % m)
        _need(len({junit_address(i) for i in ids}) == len(ids), "node ids of %s are not losslessly identifiable in JUnit" % m)
        modules[m] = {"node_ids": ids, "count": len(ids), "digest": ids_digest(ids)}
    _need(not set(skips) & set(modules), "a module both collected nodes and was skipped at collection")
    src = source(root)
    inv = {"schema": INVENTORY_SCHEMA, "tested_sha": src["sha"], "tested_tree": src["tree"], "plugin_sha256": plugin_sha, "profile": raw["profile"],
           "profile_digest": raw["profile_digest"], "modules": modules, "collection_skips": skips,
           "node_count": sum(v["count"] for v in modules.values())}
    return seal(inv)


def verify_inventory(inv):
    from tools.ci_v4_nodes import ids_digest
    check_seal(inv, "inventory")
    _need(inv.get("schema") == INVENTORY_SCHEMA and SHA_RE.match(inv.get("tested_sha", "")) and SHA_RE.match(inv.get("tested_tree", "")),
          "inventory schema/source invalid")
    seen = set()
    for m, spec in inv["modules"].items():
        _need(spec["count"] == len(spec["node_ids"]) and spec["digest"] == ids_digest(spec["node_ids"]), "inventory of %s inconsistent" % m)
        _need(not seen & set(spec["node_ids"]), "duplicate node id across modules")
        seen |= set(spec["node_ids"])
    _need(inv["node_count"] == len(seen), "inventory node count inconsistent")
    return inv


# ── weights and scheduling ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

DEFAULT_NODE_S = 1.0


def load_weights(paths):
    """Measured seconds: {node id: s} and {module: s}. Later files win. Missing files are ignored (weights only steer balance)."""
    nodes, modules, sources = {}, {}, []
    for p in paths:
        try:
            d = json.loads(Path(p).read_text())
        except (OSError, ValueError):
            continue
        for k, v in (d.get("nodes") or {}).items():
            v = v if isinstance(v, (int, float)) else (v or {}).get("seconds")
            if isinstance(v, (int, float)) and v >= 0:
                nodes[k] = float(v)
        for k, v in (d.get("modules") or {}).items():
            if isinstance(v, (int, float)) and v >= 0:
                modules[k] = float(v)
        sources.append(str(p))
    return {"nodes": nodes, "modules": modules, "sources": sources}


def node_seconds(module, ids, weights):
    """Per-node estimate: measured node time; otherwise the module's measured remainder spread evenly; otherwise a flat default."""
    known = {n: weights["nodes"][n] for n in ids if n in weights["nodes"]}
    rest = [n for n in ids if n not in known]
    if module in weights["modules"]:
        fill = max(weights["modules"][module] - sum(known.values()), 0.0) / max(len(rest), 1)
    else:
        fill = DEFAULT_NODE_S
    return {n: known.get(n, fill) for n in ids}


def units_for(inv, policy, weights):
    """Schedulable units. Every module is ONE unit, except a literal allowlisted module heavier than the target, which becomes LPT node parts
    (never a pattern; each verdict carries a recorded isolation proof). Collection-skipped modules are tiny whole units."""
    split_cfg = policy["node_split"]
    target, max_parts = float(split_cfg["target_unit_s"]), int(split_cfg["max_parts"])
    units = []
    for m, spec in sorted(inv["modules"].items()):
        secs = node_seconds(m, spec["node_ids"], weights)
        total = sum(secs.values())
        if m in split_cfg["modules"] and total > target and len(spec["node_ids"]) >= 2:
            top = max(secs.values())
            want = 1 + math.ceil((total - top) / target) if top >= target else math.ceil(total / target)
            parts = max(2, min(max_parts, len(spec["node_ids"]), want))
            bins = [[] for _ in range(parts)]
            loads = [0.0] * parts
            for n in sorted(spec["node_ids"], key=lambda n: (-secs[n], n)):
                i = min(range(parts), key=lambda k: (loads[k], k))
                bins[i].append(n); loads[i] += secs[n]
            order = {n: i for i, n in enumerate(spec["node_ids"])}
            for k, (b, load) in enumerate(zip(bins, loads)):
                if b:
                    units.append({"id": "%s#%d/%d" % (m, k + 1, parts), "module": m, "kind": "nodes",
                                  "node_ids": sorted(b, key=order.get), "seconds": round(load, 3)})
        else:
            units.append({"id": m, "module": m, "kind": "module", "node_ids": list(spec["node_ids"]), "seconds": round(total, 3)})
    for m in sorted(inv["collection_skips"]):
        units.append({"id": m, "module": m, "kind": "collection_skip", "node_ids": [], "seconds": 1.0})
    return units


def lpt(units, k):
    loads = [0.0] * k
    shards = [[] for _ in range(k)]
    for u in sorted(units, key=lambda u: (-u["seconds"], u["id"])):
        i = min(range(k), key=lambda w: (loads[w], w))
        shards[i].append(u); loads[i] += u["seconds"]
    return shards, loads


def simulate(units, policy, counts=None):
    w = policy["workers"]
    counts = counts or sorted(set(range(w["min"], w["max"] + 1)) | {8, 10, 12, 16})
    rows = []
    for k in counts:
        _, loads = lpt(units, k)
        crit = max(loads)
        rows.append({"workers": k, "max_shard_s": round(crit, 1), "predicted_critical_path_s": round(w["per_worker_overhead_s"] + crit, 1),
                     "runner_minutes": round((k * w["per_worker_overhead_s"] + sum(loads)) / 60.0, 1),
                     "in_policy_range": w["min"] <= k <= w["max"]})
    return rows


def choose_workers(units, policy):
    """Meet the target with the fewest workers, or limit predicted overruns within the sealed worker range."""
    w = policy["workers"]
    target = w["target_test_critical_path_s"]
    timeout = policy["shard_timeout_s"]
    options = [(k, lpt(units, k)[1]) for k in range(w["min"], w["max"] + 1)]
    for k, loads in options:
        if max(loads) <= target:
            return k
    best_k, initial_loads = options[0]
    best = max(initial_loads)
    for k, loads in options[1:]:
        crit = max(loads)
        if best - crit < w["min_gain_s_per_extra_worker"]:
            break
        best_k, best = k, crit
    if best > timeout:
        # One indivisible unit can keep max(loads) flat while the other
        # shards still benefit. Score all loads against the sealed timeout.
        def overrun(option):
            k, loads = option
            return (sum(max(0, load - timeout) for load in loads),
                    sum(max(0, load - target) for load in loads), k)

        return min(options, key=overrun)[0]
    return best_k


def make_plan(inv, policy, weights, run_id, run_attempt, ref, event, repo):
    verify_inventory(inv)
    _need(inv["node_count"] >= policy["min_collected_nodes"], "collected %d nodes < policy floor %d (partial collection)"
          % (inv["node_count"], policy["min_collected_nodes"]))
    units = units_for(inv, policy, weights)
    k = choose_workers(units, policy)
    shards, loads = lpt(units, k)
    assignments = []
    for i, (s, load) in enumerate(zip(shards, loads)):
        _need(s, "empty shard %d (fewer units than workers)" % i)
        split = {}
        for u in s:
            if u["kind"] == "collection_skip":
                continue
            spec = inv["modules"][u["module"]]
            entry = split.setdefault(u["module"], {"count": spec["count"], "digest": spec["digest"], "keep": []})
            entry["keep"] += u["node_ids"]
        for m, entry in split.items():
            order = {n: j for j, n in enumerate(inv["modules"][m]["node_ids"])}
            entry["keep"] = sorted(entry["keep"], key=order.get)
        per_module = collections.Counter()
        for u in s:
            per_module[u["module"]] += u["seconds"]
        # heaviest modules first: the costly governance corpus runs early in a fresh process (order changes no assertion; each module is complete)
        order = sorted(per_module, key=lambda m: (-per_module[m], m))
        assignments.append({"shard": i, "units": sorted(u["id"] for u in s), "predicted_s": round(load, 1), "order": order,
                            "modules": split, "collection_skips": sorted(u["module"] for u in s if u["kind"] == "collection_skip")})
    plan = {"schema": PLAN_SCHEMA, "tier": "full", "tested_sha": inv["tested_sha"], "tested_tree": inv["tested_tree"],
            "repository": repo, "ref": ref, "event": event, "run_id": int(run_id), "run_attempt": int(run_attempt),
            "inventory_digest": inv["digest"], "profile_digest": inv["profile_digest"], "plugin_sha256": inv["plugin_sha256"],
            "node_count": inv["node_count"],
            "collection_skip_count": len(inv["collection_skips"]), "policy_digest": canonical_digest(policy),
            "weights_sources": weights["sources"], "workers": k, "simulation": simulate(units, policy),
            "split_modules": sorted({u["module"] for u in units if u["kind"] == "nodes"}),
            "scoped_modules": sorted(set(policy["scoped_modules"]) & set(inv["modules"])),
            "scoped_nodes": planned_scoped_nodes(policy, inv),
            "shard_timeout_s": policy["shard_timeout_s"], "assignments": assignments}
    plan = seal(plan)
    verify_plan_against_inventory(plan, inv)
    return plan


def planned_scoped_nodes(policy, inv):
    """The literal ``scoped_nodes`` allowlist, each id required to be EXACTLY one collected node of this inventory (no generalisation)."""
    collected = {n for spec in inv["modules"].values() for n in spec["node_ids"]}
    missing = sorted(set(policy["scoped_nodes"]) - collected)
    _need(not missing, "scoped node(s) not in the current collection: %s" % missing[:5])
    return sorted(policy["scoped_nodes"])


def shard_scoped_nodes(plan, a):
    """The allowlisted nodes this shard actually executes (its kept nodes only)."""
    kept = {n for entry in a["modules"].values() for n in entry["keep"]}
    return sorted(set(plan["scoped_nodes"]) & kept)


def verify_plan_against_inventory(plan, inv):
    """Union of the assignments == the exact inventory; disjoint; nothing foreign; every collection skip assigned once."""
    check_seal(plan, "plan")
    _need(plan.get("schema") == PLAN_SCHEMA and plan["inventory_digest"] == inv["digest"] and plan["tested_sha"] == inv["tested_sha"]
          and plan["tested_tree"] == inv["tested_tree"], "plan is not bound to this inventory/source")
    _need(len(plan["assignments"]) == plan["workers"] and [a["shard"] for a in plan["assignments"]] == list(range(plan["workers"])),
          "plan shard indices are not 0..workers-1")
    seen, skips = collections.Counter(), collections.Counter()
    for a in plan["assignments"]:
        for m, entry in a["modules"].items():
            spec = inv["modules"].get(m)
            _need(spec is not None and entry["count"] == spec["count"] and entry["digest"] == spec["digest"], "plan module %s not in inventory" % m)
            _need(set(entry["keep"]) <= set(spec["node_ids"]) and entry["keep"], "plan assigns a foreign or empty node set for %s" % m)
            seen.update(entry["keep"])
        skips.update(a["collection_skips"])
    every = [n for spec in inv["modules"].values() for n in spec["node_ids"]]
    _need(set(seen) == set(every), "plan union differs from the inventory (%d planned, %d collected)" % (len(seen), len(every)))
    _need(all(v == 1 for v in seen.values()), "a node is assigned to more than one shard")
    _need(set(skips) == set(inv["collection_skips"]) and all(v == 1 for v in skips.values()), "collection-skip modules not assigned exactly once")
    for a in plan["assignments"]:
        _need(sorted(a["order"]) == sorted(set(a["modules"]) | set(a["collection_skips"])) and len(a["order"]) == len(set(a["order"])),
              "shard %d run order is not exactly its modules" % a["shard"])
    return True


# ── shard execution ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def run_shard(root, plan, index, out, timeout_s=None):
    root, out = Path(root), Path(out)
    check_seal(plan, "plan")
    src = source(root)
    _need(src["sha"] == plan["tested_sha"] and src["tree"] == plan["tested_tree"], "checkout %s is not the planned source" % src["sha"])
    _need(isinstance(index, int) and 0 <= index < plan["workers"], "no shard %s in plan" % index)
    a = plan["assignments"][index]
    out.mkdir(parents=True, exist_ok=True)
    assign = {"schema": "FINCO_CI_V4_NODE_ASSIGN_V1", "tested_sha": plan["tested_sha"], "tested_tree": plan["tested_tree"],
              "plan_digest": plan["digest"], "shard": index, "whole": [], "split": a["modules"]}
    assign_path, evidence, junit = out / ("assign-%d.json" % index), out / ("nodes-%d.json" % index), out / ("junit-%d.xml" % index)
    phases = out / ("phases-%d.json" % index)
    assign_path.write_text(json.dumps(assign, sort_keys=True))
    plugin_dir, plugin_sha = plugin(root, out.parent / ("plugin-%d" % index))
    _need(plugin_sha == plan["plugin_sha256"], "shard plugin differs from the plugin that collected the plan inventory")
    targets = list(a["order"])
    _need(sorted(targets) == sorted(set(a["modules"]) | set(a["collection_skips"])), "shard order is not exactly its modules")
    scoped = sorted(set(a["modules"]) & set(plan["scoped_modules"]))
    env = _clean_env(FINCO_CI_V4_NODE_ASSIGN=str(assign_path), FINCO_CI_V4_NODE_EVIDENCE=str(evidence), PYTHONPATH=str(plugin_dir),
                     FINCO_CI_FULL_SCOPED=",".join(scoped), FINCO_CI_FULL_SCOPED_NODES="\n".join(shard_scoped_nodes(plan, a)),
                     **{RECORDER_ENV: str(phases)})
    limit = int(timeout_s or plan["shard_timeout_s"])
    t0 = time.monotonic()
    proc = subprocess.Popen(_pytest_base() + ["--junitxml", str(junit), *targets], cwd=root, env=env, start_new_session=True)
    timed_out = False
    try:
        rc = proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        timed_out = True
        # SIGINT first: pytest finishes the session (partial JUnit + phase record for diagnosis; the record still fails on timed_out)
        for sig, grace in ((signal.SIGINT, 90), (signal.SIGTERM, 30), (signal.SIGKILL, None)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        rc = TIMEOUT_EXIT
    wall = round(time.monotonic() - t0, 1)
    rec = seal({"schema": SHARD_SCHEMA, "shard": index, "tested_sha": src["sha"], "tested_tree": src["tree"], "plan_digest": plan["digest"],
                "run_id": plan["run_id"], "run_attempt": plan["run_attempt"], "plugin_sha256": plugin_sha, "pytest_exit": rc, "timed_out": timed_out,
                "limit_s": limit, "wall_s": wall, "targets": targets})
    (out / ("shard-%d.json" % index)).write_text(json.dumps(rec, indent=1, sort_keys=True))
    print("FULL shard %d: exit=%s wall=%.1fs timed_out=%s" % (index, rc, wall, timed_out))
    return 0 if rc == 0 else 1


# ── authenticated artifact transport ─────────────────────────────────────────────────────────────────────────────────────────────────────

def safe_members(blob, name):
    """{member name: bytes} of an artifact zip; refuses duplicates, encryption, symlinks, absolute/parent paths and oversized members."""
    out = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            _need(len(names) == len(set(names)), "artifact %s has duplicate members" % name)
            for i in infos:
                if i.is_dir():
                    continue
                p = PurePosixPath(i.filename)
                _need(not p.is_absolute() and ".." not in p.parts, "artifact %s has an unsafe member path" % name)
                _need(not i.flag_bits & 0x1, "artifact %s has an encrypted member" % name)
                _need((i.external_attr >> 16) & 0o170000 != 0o120000, "artifact %s has a symlink member" % name)
                _need(i.file_size <= MAX_MEMBER_BYTES, "artifact %s member too large" % name)
                out[i.filename] = z.read(i.filename)
    except zipfile.BadZipFile:
        raise FullError("artifact %s is not a zip" % name) from None
    return out


def fetch_artifacts(gh, run_id, run_attempt, workers):
    """Exactly the expected artifacts of THIS run attempt (no missing, duplicated or unexpected authoritative name); each zip's SHA-256 must
    equal GitHub's recorded digest. Returns {logical name: {member: bytes}} plus the per-artifact provenance."""
    arts = gh._pages("/repos/%s/actions/runs/%d/artifacts" % (gh.repo, int(run_id)), "artifacts")
    want = expected_artifact_names(workers, run_attempt)
    byname = collections.defaultdict(list)
    for a in arts:
        byname[a.get("name")].append(a)
    contents, provenance = {}, {}
    for logical, name in want.items():
        found = [a for a in byname.get(name, []) if not a.get("expired")]
        _need(len(found) == 1, "artifact %s: %d present (exactly one required)" % (name, len(found)))
        a = found[0]
        _need((a.get("workflow_run") or {}).get("id") in (None, int(run_id)), "artifact %s belongs to another run" % name)
        blob = gh.download(a)
        digest = "sha256:" + hashlib.sha256(blob).hexdigest()
        _need(a.get("digest") == digest, "artifact %s bytes do not match GitHub's digest" % name)
        contents[logical] = safe_members(blob, name)
        provenance[logical] = {"name": name, "id": a["id"], "digest": digest, "size": len(blob)}
    return contents, provenance


def expected_artifact_names(workers, attempt):
    names = {"plan": "ci-full-plan-attempt-%d" % attempt, "recollect": "ci-full-recollect-attempt-%d" % attempt,
             "f01": "ci-v4-f01-%d" % attempt}
    for i in range(workers):
        names["shard-%d" % i] = "ci-full-shard-%d-attempt-%d" % (i, attempt)
    return names


# ── strict record ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _one(members, suffix, what):
    hits = [k for k in members if k == suffix or k.endswith("/" + suffix)]
    _need(len(hits) == 1, "%s: expected exactly one %s, found %d" % (what, suffix, len(hits)))
    return members[hits[0]]


def skip_key(nodeid):
    from tools.ci_v4_nodes import junit_address
    cls, name = junit_address(nodeid)
    return "%s::%s" % (cls, name)


def verify_f01(members, policy):
    browser = parse_junit(_one(members, "financial-browser.xml", "F01"))
    native = parse_junit(_one(members, "native.xml", "F01"))
    _need(browser and all(c["status"] == "passed" for c in browser), "F01 financial/browser acceptance has a non-pass")
    _need(len([c for c in browser if c["classname"].endswith("finval_f01_browser_acceptance")]) == policy["f01"]["browser_cases"],
          "F01 browser acceptance is not exactly the four verticals")
    _need(len(native) == policy["f01"]["native_cases"] and all(c["status"] == "passed" for c in native), "F01 native identity is not 20 passes")
    return {"browser_financial_cases": len(browser), "browser_vertical_cases": policy["f01"]["browser_cases"], "native_cases": len(native)}


def build_record(contents, provenance, policy, skip_baseline, sha, tree, run_id, run_attempt, results, conftests, finished_at=None):
    """Pure verification of authenticated artifact contents. Returns (record, problems); conclusion is ``pass`` only with zero problems."""
    from tools.ci_v4_nodes import junit_address
    problems, counts, skipped = [], {"passed": 0, "failed": 0, "error": 0, "skipped": 0}, []
    junit_digests, shard_rows, f01 = [], [], None
    plan = inv = None
    try:
        plan = check_seal(json.loads(_one(contents["plan"], "plan.json", "plan")), "plan")
        inv = verify_inventory(json.loads(_one(contents["plan"], "inventory.json", "plan")))
        verify_plan_against_inventory(plan, inv)
        _need(plan["tested_sha"] == sha and plan["tested_tree"] == tree, "plan is for another source (stale sha/tree)")
        _need(plan["run_id"] == int(run_id) and plan["run_attempt"] == int(run_attempt), "plan belongs to another run/attempt (replay)")
        _need(plan["policy_digest"] == canonical_digest(policy), "plan was made under another policy")
        again = verify_inventory(json.loads(_one(contents["recollect"], "inventory.json", "recollect")))
        _need(again["digest"] == inv["digest"], "independent re-collection differs from the planned inventory")
        _need(plan["plugin_sha256"] == inv["plugin_sha256"], "plan and inventory name different execution plugins")
        for name, r in sorted(results.items()):
            _need(r == "success", "job %s concluded %s" % (name, r))
        f01 = verify_f01(contents["f01"], policy)
        executed = collections.Counter()
        node_status = {}
        for a in plan["assignments"]:
            i = a["shard"]
            m = contents.get("shard-%d" % i)
            _need(m is not None, "shard %d artifact missing" % i)
            rec = check_seal(json.loads(_one(m, "shard-%d.json" % i, "shard %d" % i)), "shard %d record" % i)
            _need(rec["schema"] == SHARD_SCHEMA and rec["shard"] == i and rec["plan_digest"] == plan["digest"] and rec["tested_sha"] == sha
                  and rec["tested_tree"] == tree and rec["run_id"] == int(run_id) and rec["run_attempt"] == int(run_attempt)
                  and rec.get("plugin_sha256") == plan["plugin_sha256"],
                  "shard %d record is bound to another plan/source/run" % i)
            _need(not rec["timed_out"] and rec["pytest_exit"] == 0, "shard %d exit %s timed_out=%s" % (i, rec["pytest_exit"], rec["timed_out"]))
            ev = json.loads(_one(m, "nodes-%d.json" % i, "shard %d" % i))
            _need(ev.get("complete") is True and ev.get("exitstatus") == 0, "shard %d node evidence incomplete" % i)
            _need(ev.get("binding") == {"tested_sha": sha, "tested_tree": tree, "plan_digest": plan["digest"], "shard": i},
                  "shard %d node evidence bound elsewhere" % i)
            _need(ev.get("profile") == expected_shard_profile(inv["profile"], a["order"], conftests)
                  and ev.get("profile_digest") == canonical_digest(ev.get("profile")), "shard %d ran under another plugin profile" % i)
            want = [n for mod in sorted(a["modules"]) for n in a["modules"][mod]["keep"]]
            for mod, entry in a["modules"].items():
                _need(ev["collected"].get(mod) == {"count": entry["count"], "digest": entry["digest"]}, "shard %d collected %s differently" % (i, mod))
            _need(set(ev["collected"]) == set(a["modules"]), "shard %d collected foreign modules" % i)
            _need(sorted(ev["kept"]) == sorted(want) and len(ev["kept"]) == len(set(ev["kept"])), "shard %d executed set != assigned set" % i)
            ph = json.loads(_one(m, "phases-%d.json" % i, "shard %d" % i))
            _need(ph.get("schema") == RECORDER_SCHEMA and ph.get("complete") is True and ph.get("exitstatus") == 0,
                  "shard %d phase recorder incomplete" % i)
            _need(set(ph["nodes"]) == set(want), "shard %d recorded a different node set than assigned" % i)
            _need(ph.get("scoped_modules") == sorted(set(a["modules"]) & set(plan["scoped_modules"])),
                  "shard %d used a different per-test scope allowlist than the plan" % i)
            sn = shard_scoped_nodes(plan, a)
            _need(ph.get("scoped_nodes") == sn, "shard %d used a different per-node scope allowlist than the plan" % i)
            calls = ph.get("scoped_node_calls")
            ran_call = sorted(n for n in sn if "call" in ph["nodes"].get(n, {}).get("phases", {}))
            _need(isinstance(calls, list) and len(calls) == len(set(calls)) and sorted(calls) == ran_call,
                  "shard %d scoped-node calls differ from its allowlisted nodes that ran a call phase" % i)
            raw = _one(m, "junit-%d.xml" % i, "shard %d" % i)
            junit_digests.append(hashlib.sha256(raw).hexdigest())
            cases = parse_junit(raw)
            ordinary = [c for c in cases if not c["collection_skip"]]
            by_addr = collections.Counter((c["classname"], c["name"]) for c in ordinary)
            _need(all(v == 1 for v in by_addr.values()), "shard %d JUnit has duplicate testcases" % i)
            addr = {junit_address(n): n for n in want}
            _need(set(by_addr) == set(addr), "shard %d JUnit does not reconcile 1:1 with its assigned nodes" % i)
            jstatus = {addr[(c["classname"], c["name"])]: c for c in ordinary}
            from tools.ci_v4_nodes import node_outcome
            for n in want:
                phase = ph["nodes"][n]["phases"]
                _need(set(phase) <= {"setup", "call", "teardown"} and "duplicate" not in phase.values() and "teardown" in phase and "setup" in phase,
                      "node %s has an incomplete or duplicated phase record" % n)
                st = node_outcome(phase)
                _need(st in ("passed", "skipped", "failed", "error"), "node %s did not complete (%s)" % (n, st))
                _need(st == jstatus[n]["status"], "node %s: evidence %s but JUnit %s" % (n, st, jstatus[n]["status"]))
                executed[n] += 1
                node_status[n] = (st, ph["nodes"][n]["duration"], i)
            got_skips = collection_skips(cases)
            _need(set(got_skips) == set(a["collection_skips"]), "shard %d collection skips differ from the plan" % i)
            for mod in a["collection_skips"]:
                _need(got_skips[mod] == inv["collection_skips"][mod], "collection skip reason of %s changed" % mod)
            shard_rows.append({"shard": i, "wall_s": rec["wall_s"], "limit_s": rec["limit_s"], "nodes": len(want),
                               "collection_skips": len(a["collection_skips"]), "predicted_s": a["predicted_s"]})
        every = [n for spec in inv["modules"].values() for n in spec["node_ids"]]
        _need(set(executed) == set(every), "executed nodes != collected nodes (%d of %d)" % (len(executed), len(every)))
        _need(all(v == 1 for v in executed.values()), "a node executed in more than one shard")
        for n in every:
            st = node_status[n][0]
            counts[st] += 1
            if st == "skipped":
                skipped.append(skip_key(n))
        for mod in inv["collection_skips"]:
            counts["skipped"] += 1
            skipped.append("::" + mod[:-3].replace("/", "."))
        extra = collections.Counter(skipped) - collections.Counter(skip_baseline)
        _need(not extra, "skips outside the reviewed baseline (a skip is never a pass): %s" % sorted(extra)[:10])
        _need(counts["failed"] == 0 and counts["error"] == 0, "failures %d / errors %d" % (counts["failed"], counts["error"]))
    except (FullError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        problems.append("%s: %s" % (type(exc).__name__, exc))
    executed_nodes = sum(counts.values())
    rec = {"schema": RECORD_SCHEMA, "tier": "full", "tested_sha": sha, "tested_tree": tree, "conclusion": "fail" if problems else "pass",
           "job_results": results, "duplicate_nodes": 0, "run_id": int(run_id), "run_attempt": int(run_attempt),
           "finished_at": finished_at or dt.datetime.now(dt.timezone.utc).isoformat(),
           "collected_nodes": (inv["node_count"] + len(inv["collection_skips"])) if inv else 0, "executed_nodes": executed_nodes,
           "counts": counts, "skipped_ids": sorted(skipped), "plan_digest": plan["digest"] if plan else None,
           "junit_sha256": sorted(junit_digests),
           "strict": {"schema": STRICT_SCHEMA, "problems": problems, "inventory_digest": inv["digest"] if inv else None,
                      "inventory_nodes": inv["node_count"] if inv else None,
                      "collection_skip_modules": sorted(inv["collection_skips"]) if inv else None,
                      "profile_digest": inv["profile_digest"] if inv else None, "workers": plan["workers"] if plan else None,
                      "split_modules": plan["split_modules"] if plan else None,
                      "scoped_modules": plan["scoped_modules"] if plan else None, "scoped_nodes": plan.get("scoped_nodes") if plan else None,
                      "shards": shard_rows, "f01": f01,
                      "artifacts": provenance, "authority_note": "a record is a claim; the release/V5 gates re-verify the GitHub run"}}
    return rec, problems


def conftest_dirs(root):
    """{sha256 of a tests/**/conftest.py at the checked-out commit: its directory ("tests/", "tests/sub/")}."""
    out = {}
    for rel in git(root, "ls-files", "--", "tests/conftest.py", "tests/**/conftest.py").splitlines():
        out[hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()] = rel[: -len("conftest.py")]
    return out


def expected_shard_profile(inv_profile, targets, conftests):
    """The collection profile restricted to what a shard can legitimately load: every non-conftest registration unchanged, and exactly the
    conftests whose directory is an ancestor of one of the shard's targets (pytest loads no other). Unknown conftest = mismatch."""
    regs = []
    for r in inv_profile["registrations"]:
        if r.get("registration") == "<conftest>":
            where = conftests.get(r.get("file_sha256"))
            _need(where is not None, "collection loaded an unknown conftest")
            if not any(t.startswith(where) for t in targets):
                continue
        regs.append(r)
    body = {k: v for k, v in inv_profile.items() if k != "registrations"}
    body["registrations"] = regs
    return body


def node_weights_from(contents, plan):
    """Measured per-node seconds of this run (input for the next plan's balance; never an acceptance input)."""
    out = {}
    for a in plan["assignments"]:
        m = contents.get("shard-%d" % a["shard"]) or {}
        try:
            ev = json.loads(_one(m, "phases-%d.json" % a["shard"], "weights"))
        except FullError:
            continue
        for n, v in ev.get("nodes", {}).items():
            out[n] = round(float(v.get("duration", 0.0)), 3)
    return out


# ── command line ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _env_required(name):
    v = os.environ.get(name, "")
    _need(v, "%s is required" % name)
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--expected", required=True); p.add_argument("--output", required=True)
    p.add_argument("--workdir", required=True); p.add_argument("--weights", action="append", default=[])
    s = sub.add_parser("shard"); s.add_argument("--plan", required=True); s.add_argument("--index", type=int, required=True)
    s.add_argument("--output", required=True)
    c = sub.add_parser("recollect"); c.add_argument("--expected", required=True); c.add_argument("--output", required=True)
    c.add_argument("--workdir", required=True)
    r = sub.add_parser("record"); r.add_argument("--expected", required=True); r.add_argument("--workers", type=int, required=True)
    r.add_argument("--output", required=True); r.add_argument("--result", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        root = Path.cwd()
        if a.cmd in ("plan", "recollect", "record"):
            _need(SHA_RE.match(a.expected) is not None, "expected sha must be 40-hex")
            _need(source(root)["sha"] == a.expected, "checkout is not the expected sha")
        out = Path(a.output)
        if a.cmd == "plan":
            policy = load_policy()
            inv = collect(root, a.workdir)
            plan = make_plan(inv, policy, load_weights(a.weights), _env_required("GITHUB_RUN_ID"), _env_required("GITHUB_RUN_ATTEMPT"),
                             _env_required("GITHUB_REF"), _env_required("GITHUB_EVENT_NAME"), _env_required("GITHUB_REPOSITORY"))
            out.mkdir(parents=True, exist_ok=True)
            (out / "inventory.json").write_text(json.dumps(inv, sort_keys=True))
            (out / "plan.json").write_text(json.dumps(plan, sort_keys=True))
            print("FULL plan: %d nodes + %d collection-skip modules, %d workers, split %s" % (
                inv["node_count"], len(inv["collection_skips"]), plan["workers"], plan["split_modules"]))
            for row in plan["simulation"]:
                print("  simulate %(workers)2d workers: predicted critical path %(predicted_critical_path_s)7.1fs, runner-min %(runner_minutes)7.1f" % row)
            gho = os.environ.get("GITHUB_OUTPUT")
            if gho:
                with open(gho, "a") as f:
                    print("matrix=" + json.dumps({"index": list(range(plan["workers"]))}, separators=(",", ":")), file=f)
                    print("workers=%d" % plan["workers"], file=f)
            return 0
        if a.cmd == "recollect":
            inv = collect(root, a.workdir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "inventory.json").write_text(json.dumps(inv, sort_keys=True))
            print("FULL independent re-collection: %d nodes, digest %s" % (inv["node_count"], inv["digest"]))
            return 0
        if a.cmd == "shard":
            return run_shard(root, json.loads(Path(a.plan).read_text()), a.index, out)
        # record
        from tools.ci_perf_guard import GitHub, GuardError, TransientError
        policy = load_policy()
        run_id, attempt = int(_env_required("GITHUB_RUN_ID")), int(_env_required("GITHUB_RUN_ATTEMPT"))
        repo = _env_required("GITHUB_REPOSITORY")
        _need(REPO_RE.match(repo) is not None, "bad repository")
        results = dict(x.split("=", 1) for x in a.result)
        baseline = json.loads((root / policy["skip_baseline"]).read_text())["skipped_nodes"]
        src = source(root)
        out.mkdir(parents=True, exist_ok=True)
        try:
            contents, prov = fetch_artifacts(GitHub(repo, _env_required("GH_TOKEN")), run_id, attempt, a.workers)
        except (GuardError, TransientError, FullError) as exc:
            contents, prov = {}, {"error": "%s: %s" % (type(exc).__name__, exc)}
        if not contents:
            rec = {"schema": RECORD_SCHEMA, "tier": "full", "tested_sha": src["sha"], "tested_tree": src["tree"], "conclusion": "fail",
                   "run_id": run_id, "run_attempt": attempt, "job_results": results, "counts": {}, "skipped_ids": [], "executed_nodes": 0,
                   "collected_nodes": 0, "junit_sha256": [], "strict": {"schema": STRICT_SCHEMA, "problems": [prov.get("error", "no artifacts")]}}
            problems = rec["strict"]["problems"]
        else:
            rec, problems = build_record(contents, prov, policy, baseline, src["sha"], src["tree"], run_id, attempt, results, conftest_dirs(root))
            for i in range(a.workers):
                m = contents.get("shard-%d" % i, {})
                for k, v in m.items():
                    if k.endswith("junit-%d.xml" % i):
                        (out / "junit").mkdir(exist_ok=True)
                        (out / "junit" / ("junit-%d.xml" % i)).write_bytes(v)
            try:
                plan = json.loads(_one(contents["plan"], "plan.json", "plan"))
                (out / "measured-node-weights.json").write_text(json.dumps(
                    {"schema": "FINCO_CI_FULL_MEASURED_WEIGHTS_V1", "run_id": run_id, "run_attempt": attempt, "tested_sha": src["sha"],
                     "nodes": node_weights_from(contents, plan)}, sort_keys=True))
            except (FullError, KeyError, ValueError):
                pass
        (out / "ci-v4-full-record.json").write_text(json.dumps(rec, indent=2, sort_keys=True))
        print("FULL %s executed=%s counts=%s" % (rec["conclusion"].upper(), rec.get("executed_nodes"), rec.get("counts")))
        for x in problems:
            print("  PROBLEM: " + x)
        return 0 if rec["conclusion"] == "pass" else 1
    except (FullError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print("CI FULL parallel FAIL CLOSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
