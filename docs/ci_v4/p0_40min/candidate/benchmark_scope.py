"""Local pass -> real source mutation -> rejection -> restoration experiment.

Use only on a disposable clean accepted-main clone. The source is restored in
finally. The experiment changes neither pins nor expected historical outcomes.
It deliberately declines a claimed speedup ratio if the A run timed out.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"])
    sys.path.insert(0, str(root))
    from tests import fin_v2_cohorts as C
    from tests import wf03_lifecycle_scope as W
    assert W.ROOT.resolve() == root
    source = root / "app/trust_readiness/registry.py"
    original = source.read_bytes()
    rows = []
    def measure(label, expected, ref=None):
        started = time.monotonic()
        assert not C._CALL
        with C.call_scope():
            result = W.exact_blobs_ok(ref=ref)
        assert not C._CALL
        rows.append({"case": label, "result": result, "expected": expected, "elapsed_s": time.monotonic()-started})
        assert result is expected, rows[-1]
    try:
        measure("original_worktree", True)
        source.write_bytes(original+b"\n# synthetic negative control\n")
        measure("real_mutation_next_call", False)
        measure("immutable_head_while_worktree_mutated", True, "HEAD")
        source.write_bytes(original)
        measure("restored_next_call", True)
        measure("unknown_ref", False, "0"*40)
    finally:
        source.write_bytes(original)
        Path(args.output).write_text(json.dumps({"local_only": True, "source": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), "cases": rows}, indent=2))
    assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"])
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
