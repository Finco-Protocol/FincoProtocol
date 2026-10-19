"""RC-7B exact 6/6 regression: canonical four-vertical runs, baseline ref vs working tree.

Usage::

    python tools/rc7b_semiannual_regression.py --baseline <git-ref> [--json out.json]

The baseline ref is checked out into a temporary detached worktree. Each tree
runs the canonical clean production calculation (cold policy cache) for the
Generic Solar, Wind, Data Center and EV Charging references in its own Python
process, and records the complete unrounded ``asdict`` structure (floats by
``repr``), the clean input fingerprint, the serialized ProjectInputs and the
cache key. Exit status 0 only when every structure is identical (maximum
financial difference ZERO); no tolerance is applied. Non-production tooling.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("solar", "wind", "data_center", "ev_charging")

_CHILD = r'''
import dataclasses, hashlib, json, math, pickle, sys
from datetime import date
from enum import Enum

def canon(o):
    if isinstance(o, Enum):
        return ["enum", type(o).__name__, canon(o.value)]
    if isinstance(o, float):
        return ["f", repr(o)] if math.isfinite(o) else ["f", str(o)]
    if isinstance(o, (bool, int, str, type(None))):
        return o
    if isinstance(o, date):
        return ["d", o.isoformat()]
    if isinstance(o, (list, tuple)):
        return [canon(v) for v in o]
    if isinstance(o, dict):
        return [["k", canon(k), canon(v)] for k, v in sorted(o.items(), key=lambda kv: repr(kv[0]))]
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return canon(dataclasses.asdict(o))
    return ["r", repr(o)]

from app import project_factories as pf
from app.services import production_financial_authority as authority
from finco_core.inputs import project_inputs_to_dict, hash_inputs_for_cache
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.provenance import compute_input_fingerprint

out = {}
for kind in sys.argv[2].split(","):
    pi = getattr(pf, "create_generic_" + kind + "_reference")()
    authority._POLICY_RUN_CACHE.clear()
    tree = canon(dataclasses.asdict(authority.run_clean_production(pi)))
    out[kind] = {
        "run_tree": tree,
        "run_sha256": hashlib.sha256(json.dumps(tree, separators=(",", ":")).encode()).hexdigest(),
        "input_dict": json.dumps(project_inputs_to_dict(pi), sort_keys=True, default=str),
        "cache_key": repr(hash_inputs_for_cache(pi)),
        "clean_fingerprint": compute_input_fingerprint(from_project_inputs(pi)),
    }
with open(sys.argv[1], "wb") as fh:
    pickle.dump(out, fh)
'''


def _snapshot(tree: Path, out: Path) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as script:
        script.write(_CHILD)
    subprocess.run([sys.executable, script.name, str(out), ",".join(KINDS)], cwd=tree, check=True,
                   env={**__import__("os").environ, "PYTHONPATH": str(tree)})
    with open(out, "rb") as fh:
        return pickle.load(fh)


def _first_difference(a, b, path="$"):
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, list):
        if len(a) != len(b):
            return path + ".len", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            found = _first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else (path, a, b)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", required=True, help="git ref of the released baseline")
    parser.add_argument("--json", help="write the comparison report to this path")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        base_tree = Path(tmp) / "baseline"
        subprocess.run(["git", "worktree", "add", "--detach", str(base_tree), args.baseline], cwd=ROOT, check=True,
                       capture_output=True)
        try:
            base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=base_tree, text=True).strip()
            before = _snapshot(base_tree, Path(tmp) / "before.pickle")
            after = _snapshot(ROOT, Path(tmp) / "after.pickle")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(base_tree)], cwd=ROOT, check=False,
                           capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {"baseline_ref": args.baseline, "baseline_sha": base_sha, "working_tree_head": head, "verticals": {}}
    identical = True
    for kind in KINDS:
        b, a = before[kind], after[kind]
        fields = {name: b[name] == a[name] for name in ("run_tree", "input_dict", "cache_key", "clean_fingerprint")}
        diff = None if fields["run_tree"] else _first_difference(b["run_tree"], a["run_tree"])
        identical &= all(fields.values())
        report["verticals"][kind] = {
            "baseline_run_sha256": b["run_sha256"], "candidate_run_sha256": a["run_sha256"],
            "input_dict_sha256": hashlib.sha256(a["input_dict"].encode()).hexdigest(),
            "clean_fingerprint": a["clean_fingerprint"], "identical": fields,
            "first_difference": None if diff is None else repr(diff)[:400],
        }
    report["maximum_financial_difference"] = "0 (bit-identical)" if identical else "NONZERO"
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
