"""One uncached canonical financial Run, including helper startup and OS resources."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--workers", type=int, choices=(0, 1, 2, 3), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    os.environ.update(FINCO_G2A_WORKERS=str(args.workers), FINCO_WEB_WORKERS="1",
                      FINCO_MODEL_EXECUTION_CONCURRENCY="1")
    spec = importlib.util.spec_from_file_location("v9_inventory", args.inventory)
    inv = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = inv
    spec.loader.exec_module(inv)
    resource_spec = importlib.util.spec_from_file_location(
        "v9p1_resources", Path(__file__).with_name("v9p1_worker_benchmark.py"))
    resources_module = importlib.util.module_from_spec(resource_spec)
    resource_spec.loader.exec_module(resources_module)
    process_resources = resources_module.process_resources
    from app.services import production_financial_authority as pfa
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    import numpy  # noqa: F401 - identical preparation in both uncached arms
    factory, vertical, policy = inv.cases()[args.case]
    assert vertical != "QUARTERLY_TEST_ONLY"
    pi = factory()
    input_digest = inv.digest(inv.flatten((pi, policy)))
    pfa._POLICY_RUN_CACHE.clear()
    before = process_resources(os.getpid())
    started = time.perf_counter()
    try:
        kwargs = {"financing_policy": policy} if policy is not None else {}
        result = pfa.run_clean_production(pi, project_type=vertical, **kwargs)
    except Exception as error:
        seconds = time.perf_counter() - started
        status = "REJECTED"
        evidence = {"exception": type(error).__qualname__, "reason": getattr(error, "reason_code", None),
                    "text": str(error)}
    else:
        seconds = time.perf_counter() - started
        status, evidence = "FEASIBLE", None
    helpers, metrics, actual = [], None, 0
    try:
        from financial_engine.financing import speculative as sp
    except ImportError:
        sp = None
    if sp is not None:
        actual = sp.configured_workers()
        if sp._POOL is not None:
            assert not sp._POOL.broken, sp._POOL.last_failure
            helpers = list(sp._POOL.executor._processes or {})
            metrics = sp._POOL.metrics
    resources = {pid: process_resources(pid) for pid in [os.getpid(), *helpers]}
    aggregate_cpu = sum(value["cpu_s"] for value in resources.values()) - before["cpu_s"]
    if evidence is None:
        evidence = inv.flatten(result)
        evidence.update(inv.flatten(run_integrity_checks(build_run_integrity_evidence(result)).to_dict(), ".integrity"))
    report = {"case": args.case, "status": status, "input_digest": input_digest,
              "digest": inv.digest(evidence), "seconds": seconds,
              "aggregate_cpu_s": aggregate_cpu, "resources": resources,
              "requested_helpers": args.workers, "configured_helpers": actual,
              "helper_metrics": metrics, "platform": platform.platform(), "python": sys.version,
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip(),
              "protected_git_blobs": {path: subprocess.check_output(
                  ["git", "hash-object", "--path=" + path, path], cwd=args.repo, text=True).strip()
                  if (args.repo / path).is_file() else None for path in (
                  "financial_engine/financing/project.py", "financial_engine/financing/speculative.py")}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if sp is not None:
        sp.shutdown_helpers()
    print(args.case, status, seconds, report["digest"], flush=True)


if __name__ == "__main__":
    main()
