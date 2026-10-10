"""Build the F3 acceptance evidence bundle for the exact checked-out HEAD.

    python -m tools.model_financing_f3_evidence_bundle --out artifacts/f3-evidence --base-checkout <dir at BASE_SHA>

Runs (1) the cold-process four-vertical legacy-equivalence comparison, (2) the Solar/Wind financial-evidence
reconciliation and (3) the authenticated Chromium acceptance, then writes ``evidence-manifest.json`` with the exact
HEAD, base SHA, commands, exit codes and the SHA-256 of every produced file.  Synthetic data only.  Screenshots are
bundle artifacts; they are never committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.model_financing_f3_legacy_equivalence import BASE_SHA


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(name: str, cmd: list[str], env: dict, log: Path) -> dict:
    started = time.time()
    with log.open("w", encoding="utf-8") as handle:
        rc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, env=env, check=False).returncode
    return {"name": name, "command": " ".join(cmd), "exit_code": rc, "seconds": round(time.time() - started, 1), "log": log.name}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-checkout", required=True)
    parser.add_argument("--pr", default="240")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": ".", "FINCO_MODEL_EXECUTION_MODE": "thread"}
    py = sys.executable
    steps = [
        _run("legacy-equivalence", [py, "-m", "tools.model_financing_f3_legacy_equivalence", "--base-checkout", args.base_checkout,
                                    "--output", str(out / "legacy-equivalence.json")], env, out / "legacy-equivalence.log"),
        _run("financial-evidence", [py, "-m", "tools.model_financing_f3_evidence", "--out", str(out / "financial-evidence.json")],
             env, out / "financial-evidence.log"),
        _run("browser-acceptance", [py, "-m", "tests.model_financing_f3_q3_acceptance", "--out", str(out / "browser")],
             env, out / "browser-acceptance.log"),
    ]
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "evidence-manifest.json")
    manifest = {
        "schema": "finco.f3.evidence-manifest.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": os.environ.get("GITHUB_REPOSITORY", "Finco-Protocol/FincoProtocol"), "pull_request": args.pr,
        "head_sha": os.environ.get("FINCO_PR_HEAD_SHA") or head, "checked_out_sha": head,
        "github_sha": os.environ.get("GITHUB_SHA"), "base_sha_for_legacy_equivalence": BASE_SHA, "steps": steps,
        "all_steps_exit_zero": all(s["exit_code"] == 0 for s in steps),
        "files": [{"path": str(p.relative_to(out)), "sha256": _sha(p), "bytes": p.stat().st_size} for p in files],
    }
    (out / "evidence-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"head_sha": manifest["head_sha"], "all_steps_exit_zero": manifest["all_steps_exit_zero"], "files": len(files)}))
    return 0 if manifest["all_steps_exit_zero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
