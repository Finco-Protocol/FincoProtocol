"""Isolated pytest bootstrap; OS exit is observed by the separate parent process."""
from __future__ import annotations

import atexit
import json
from pathlib import Path
import sys
import time

# Executed by absolute path with python -I; never load a subject's tools package.
TRUSTED_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRUSTED_ROOT))


def classify_threads(live, allowed):
    """Split live non-main threads into unapproved leaks and owner-approved daemon threads.

    Only a DAEMON thread whose exact name appears in the approved isolation policy is tolerated; anything else
    (non-daemon, unlisted, or any thread when the allowlist is empty) stays a leak."""
    unapproved, approved = [], []
    for name, daemon in live:
        (approved if daemon and name in allowed else unapproved).append(name)
    return unapproved, approved


def main():
    request_path = Path(sys.argv[1]).resolve()
    directory = request_path.parent
    clock = time.perf_counter()
    from tools.ci_v3_schema import read_json, write_json
    write_json(directory / "bootstrap-start.json", {"perf_ns": round(clock * 1_000_000_000)})
    request = read_json(request_path)
    if request.get("hosted"):
        import os
        Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)
    # Parent must establish process-tree containment before allowing test imports.
    deadline = time.monotonic() + 30
    while not (directory / "release").exists():
        if time.monotonic() > deadline:
            return 125
        time.sleep(0.01)

    def finalizing():
        write_json(directory / "interpreter-exit.json", {"finalizing": True,
            "at_ms": round((time.perf_counter() - clock) * 1000)})
    atexit.register(finalizing)
    if request.get("target_calibration") is not None:
        from tools.ci_v3_calibrate import worker_cold_start_s, verdict
        contract = request["target_calibration"]
        if contract.get("ceiling_s") != .6 or contract.get("statistic") != "maximum":
            raise ValueError("unapproved calibration contract")
        median, samples = worker_cold_start_s(request["project"], repeats=contract["samples"])
        calibration = {"context": request["context"], "samples_s": samples,
                       "median_s": median, "acceptance_statistic": "maximum",
                       **verdict(max(samples))}
        write_json(directory / "calibration.json", calibration)
        if not calibration["meets_test_assumption"]:
            return 124  # no full test execution on a failed target calibration
    before = time.perf_counter()
    import pytest
    pytest_import_ms = round((time.perf_counter() - before) * 1000)
    before = time.perf_counter()
    from tools.ci_v3_pytest_adapter import Adapter
    adapter_import_ms = round((time.perf_counter() - before) * 1000)
    adapter = Adapter(request, directory / "adapter.json")
    args = ["-q", "--tb=short", "-p", "no:cacheprovider", "--rootdir", request["project"],
            "--basetemp", str(directory / "tmp" / "pytest"),
            "--junitxml", str(directory / "native.xml")]
    if request["mode"] == "discover":
        args.append("--collect-only")
    from tools.ci_v3_pytest_config import plugin_args
    args += plugin_args()  # no ambient autoload or missing-plugin fallback
    args.append("tests")
    started = round((time.perf_counter() - clock) * 1000)
    code = int(pytest.main(args, plugins=[adapter]))
    ipc = None
    if request.get('finalize_owned_multiprocessing'):
        from tools.ci_v3_built_image_child import finalize_multiprocessing
        ipc = finalize_multiprocessing()
    import multiprocessing
    import threading
    live = [(t.name, t.daemon) for t in threading.enumerate() if t is not threading.main_thread() and t.is_alive()]
    unapproved, approved = classify_threads(live, request.get("allowed_daemon_threads") or {})
    leaks = {"threads": unapproved, "children": [p.pid for p in multiprocessing.active_children() if p.is_alive()]}
    write_json(directory / "pytest-return.json", {"code": code, "pytest_started_ms": started,
        "pytest_returned_ms": round((time.perf_counter() - clock) * 1000), "leaks": leaks,
        "threads_observed": [{"name": n, "daemon": d} for n, d in live], "threads_approved_daemon": approved,
        "owned_multiprocessing_cleanup": ipc,
        "pytest_import_ms": pytest_import_ms, "adapter_import_ms": adapter_import_ms})
    return code if code else (125 if ipc is not None and not ipc['verified'] else 0)


if __name__ == "__main__":
    sys.exit(main())
