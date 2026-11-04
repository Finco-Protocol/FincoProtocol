"""Run ONE CI V4 shard of the plan and bind its evidence to the tested SHA/tree/plan. Never selects or deselects nodes itself."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tools.ci_v3_pytest_config import plugin_args


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True); ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--output", required=True)
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
    mods = shards[a.index]
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    junit = out / ("junit-shard-%d.xml" % a.index)
    t0 = time.monotonic()
    rc = 0
    if mods:
        # Same plugin contract as CI V3: no ambient entry-point autoload, the async plugins loaded explicitly exactly once.
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        rc = subprocess.call([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *plugin_args(),
                              "--junitxml", str(junit), *mods], env=env)
    wall = time.monotonic() - t0
    (out / ("shard-%d.json" % a.index)).write_text(json.dumps({
        "shard": a.index, "sha": head, "tree": tree, "plan_digest": plan["digest"], "modules": mods,
        "pytest_exit": rc, "wall_s": round(wall, 1)}, indent=2, sort_keys=True))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
