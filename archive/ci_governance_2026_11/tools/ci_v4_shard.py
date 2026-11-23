"""Run ONE CI V4 shard of the plan and bind its evidence to the tested SHA/tree/plan. Never selects or deselects modules itself.

A module plan (``schedule.shards``: module lists) runs exactly as before. A node plan (``schedule.units``, produced only by
``tools.ci_v4_schedule.apply_node_split`` for allowlisted modules) runs the shard's whole modules plus the exact assigned node ids of its split
modules in ONE pytest process with the ``tools.ci_v4_nodes`` plugin: the full collection of each split module must equal the planned inventory
before anything runs, and per-node evidence is written for the independent aggregator.

``--tmp disk`` (default, unchanged behaviour) keeps the runner's temp directory; ``--tmp auto`` uses a private directory on a verified tmpfs
(``/dev/shm``: present, writable, >= 2 GiB free) for pytest's tmp_path/worktrees and falls back to an isolated disk directory otherwise.
The choice and the measured free space are recorded; the tested checkout itself is never moved.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.ci_v3_pytest_config import plugin_args

TMPFS = Path("/dev/shm")
TMPFS_MIN_FREE = 2 * 1024 ** 3


def choose_tmp(mode, index, tmpfs=TMPFS, min_free=TMPFS_MIN_FREE, disk_base=None):
    """Return (path or None, record). ``None`` means: inherit the runner's temp directory (unchanged behaviour)."""
    if mode == "disk":
        return None, {"mode": "disk", "reason": "default"}
    rec = {"requested": mode}
    try:
        st = os.statvfs(tmpfs)
        free = st.f_bavail * st.f_frsize
        rec["tmpfs_free_bytes"] = free
        usable = tmpfs.is_dir() and os.access(tmpfs, os.W_OK) and free >= min_free
    except OSError as exc:
        usable, rec["tmpfs_error"] = False, str(exc)
    if usable:
        path = Path(tempfile.mkdtemp(prefix="ci-v4-shard-%d-" % index, dir=tmpfs))
        os.chmod(path, 0o700)
        rec.update({"mode": "tmpfs", "path": str(path)})
        return path, rec
    if mode == "tmpfs":
        raise SystemExit("tmpfs requested but %s is unavailable or too small: %s" % (tmpfs, rec))
    path = Path(tempfile.mkdtemp(prefix="ci-v4-shard-%d-" % index, dir=disk_base))
    rec.update({"mode": "disk_fallback", "path": str(path)})
    return path, rec


def assignment(plan, index):
    """The shard's node assignment: whole modules + {split module: inventory count/digest + its kept ids in collection order}."""
    units = plan["schedule"]["units"][index]
    split_meta = plan["node_split"]["modules"]
    whole = sorted({u["module"] for u in units if u["kind"] == "module"})
    split = {}
    for u in units:
        if u["kind"] != "nodes":
            continue
        meta = split_meta[u["module"]]
        spec = split.setdefault(u["module"], {"count": meta["count"], "digest": meta["digest"], "keep": []})
        spec["keep"] += u["node_ids"]
    for m, spec in split.items():
        order = {n: i for i, n in enumerate(split_meta[m]["node_ids"])}
        # an id outside the inventory sorts last and is refused by the plugin before any test runs
        spec["keep"] = sorted(spec["keep"], key=lambda n: (order.get(n, len(order)), n))
    if set(whole) & set(split):
        raise SystemExit("a module is both whole and split in shard %d" % index)
    return {"schema": "FINCO_CI_V4_NODE_ASSIGN_V1", "tested_sha": plan["tested_sha"], "tested_tree": plan["tested_tree"],
            "plan_digest": plan["digest"], "shard": index, "whole": whole, "split": split}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True); ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--tmp", choices=("disk", "auto", "tmpfs"), default="disk")
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"]).decode().strip()
    if head != plan["tested_sha"] or tree != plan["tested_tree"]:
        print("checkout %s/%s is not the planned source %s/%s" % (head, tree, plan["tested_sha"], plan["tested_tree"]), file=sys.stderr)
        return 2
    shards = plan["schedule"]["shards"]
    if not 0 <= a.index < len(shards):
        print("no shard %d in plan (workers=%d)" % (a.index, len(shards)), file=sys.stderr)
        return 2
    node_plan = "units" in plan["schedule"]
    if node_plan:
        from tools.ci_v4_schedule import plan_digest
        if "node_split" not in plan or plan_digest(plan) != plan.get("digest") or len(plan["schedule"]["units"]) != len(shards):
            print("node plan without a valid node_split section / digest", file=sys.stderr)
            return 2
    mods = shards[a.index]
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    junit = out / ("junit-shard-%d.xml" % a.index)
    tmp, tmp_rec = choose_tmp(a.tmp, a.index)
    # Same plugin contract as CI V3: no ambient entry-point autoload, the async plugins loaded explicitly exactly once.
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for k in ("FINCO_CI_V4_NODE_COLLECT", "FINCO_CI_V4_NODE_ASSIGN", "FINCO_CI_V4_NODE_EVIDENCE"):
        env.pop(k, None)
    if tmp is not None:
        env.update(TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp))
    record = {"shard": a.index, "sha": head, "tree": tree, "plan_digest": plan["digest"], "modules": mods, "tmp": tmp_rec}
    t0 = time.monotonic()
    rc = 0
    try:
        if node_plan:
            assign = assignment(plan, a.index)
            (out / ("assign-shard-%d.json" % a.index)).write_text(json.dumps(assign, indent=1, sort_keys=True))
            evidence = out / ("nodes-shard-%d.json" % a.index)
            env.update(FINCO_CI_V4_NODE_ASSIGN=str(out / ("assign-shard-%d.json" % a.index)), FINCO_CI_V4_NODE_EVIDENCE=str(evidence))
            targets = sorted(set(assign["whole"]) | set(assign["split"]))
            rc = subprocess.call([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *plugin_args(), "-p", "tools.ci_v4_nodes",
                                  "--junitxml", str(junit), *targets], env=env)
            record.update({"units": plan["schedule"]["units"][a.index], "node_evidence": evidence.name})
        elif mods:
            rc = subprocess.call([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *plugin_args(),
                                  "--junitxml", str(junit), *mods], env=env)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    wall = time.monotonic() - t0
    record.update({"pytest_exit": rc, "wall_s": round(wall, 1)})
    (out / ("shard-%d.json" % a.index)).write_text(json.dumps(record, indent=2, sort_keys=True))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
