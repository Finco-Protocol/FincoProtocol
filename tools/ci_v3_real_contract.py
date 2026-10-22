"""Phase 2 envelopes and real-report checks, layered over unchanged V1 contracts."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import io
import tarfile

from tools.ci_v3_schema import canonical_bytes, digest, require

REAL_SCHEMA = 2
REAL_EVALUATOR = "ci-v3-observed/2"
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def envelope(kind, **values):
    body = {"schema": REAL_SCHEMA, "kind": kind, **values}
    return {**body, "digest": digest(body)}


def check_envelope(value, kind):
    require(isinstance(value, dict) and type(value.get("schema")) is int
            and value["schema"] == REAL_SCHEMA and value.get("kind") == kind, "Phase 2 envelope shape")
    require(value.get("digest") == digest({k: v for k, v in value.items() if k != "digest"}),
            "Phase 2 envelope digest mismatch")


def environment_record():
    packages = sorted({(d.metadata["Name"].lower().replace("_", "-"), d.version)
                       for d in importlib.metadata.distributions() if d.metadata["Name"]})
    from tools.ci_v3_runtime_fingerprint import capture
    fingerprint = capture()
    # Software identity is independent of incidental runner CPU addresses/limits.
    # Full host observations remain in adapter/control reports and pair review.
    for key in ("cpu", "cpu_count", "affinity", "cgroup_limits", "kernel"):
        fingerprint.pop(key, None)
    return {"runtime_fingerprint": fingerprint, "python": sys.version, "executable": str(Path(sys.executable).resolve()),
            "platform": sys.platform, "machine": platform.machine(), "packages": packages,
            "native_thread_environment": {k: os.environ.get(k) for k in THREAD_ENV},
            "pytest_plugin_autoload": os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "")}


def report_reason(report):
    value = report.longrepr
    return str(value[2]) if isinstance(value, tuple) and len(value) == 3 else str(value or "")


def phase_record(report):
    """Lossless outcome fields shared by observational control and shadow hooks."""
    value = report.longrepr
    # The expected-failure reason is pytest's declared policy reason. Keep the
    # original traceback separately; it can contain PID/address/temp-path noise.
    reason = str(report.wasxfail) if hasattr(report, "wasxfail") else report_reason(report)
    return {"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
            "reason": reason if not report.passed else "",
            "wasxfail": str(report.wasxfail) if hasattr(report, "wasxfail") else None,
            "duration_ms": round(report.duration * 1000), "longrepr": str(value or "")}


def git_source(project):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(project), *args], text=True).strip()
    require(Path(git("rev-parse", "--show-toplevel")).resolve() == Path(project).resolve(), "project is not Git root")
    require(not git("status", "--porcelain", "--untracked-files=all"), "tested source is dirty")
    paths = subprocess.check_output(["git", "-C", str(project), "ls-files", "-z"]).decode("utf-8").split("\0")
    # One Git process rather than one per file; retain exact-byte verification.
    archive = subprocess.check_output(["git", "-C", str(project), "archive", "--format=tar", "HEAD"])
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(archive)) as members:
        for member in members:
            if member.isdir():
                continue
            require(member.isfile(), "non-regular tested source")
            actual = Path(project) / member.name
            require(not actual.is_symlink() and actual.is_file(), "non-regular tested source")
            require(actual.read_bytes() == members.extractfile(member).read(), "tested working bytes differ from exact Git source")
            seen.add(member.name)
    require(seen == set(filter(None, paths)), "Git archive omits tracked source; export-ignore unsupported")
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def outcome(phases, complete=True):
    """Derive status from actual reports only, never from collection membership."""
    require(phases, "missing actual execution")
    counts = Counter(p["when"] for p in phases)
    require(set(counts) <= {"setup", "call", "teardown"} and all(v == 1 for v in counts.values()),
            "duplicate/unknown execution phase")
    if complete:
        require(counts["setup"] == counts["teardown"] == 1, "incomplete setup/teardown execution")
        setup = next(p for p in phases if p["when"] == "setup")
        if setup["outcome"] == "passed":
            require(counts["call"] == 1, "collection-only or missing call false PASS")
    require(all(p["outcome"] in ("passed", "failed", "skipped") for p in phases), "invalid phase outcome")
    failed = next((p for p in phases if p["outcome"] == "failed"), None)
    if failed:
        return {"status": "failed", "reason": failed["reason"]}
    xfail = next((p for p in phases if p.get("wasxfail") is not None), None)
    if xfail:
        return {"status": "xpass" if xfail["outcome"] == "passed" else "xfail", "reason": xfail["wasxfail"]}
    skipped = next((p for p in phases if p["outcome"] == "skipped"), None)
    return {"status": "skipped", "reason": skipped["reason"]} if skipped else {"status": "passed", "reason": ""}


def actual_execution_records(report):
    groups = defaultdict(list)
    for phase in report["phases"]:
        require(phase.get("nodeid") in report["selected"], "executed unowned node")
        groups[phase["nodeid"]].append(phase)
    require(set(groups) == set(report["selected"]), "missing actual execution; collection is not PASS")
    return [{"nodeid": n, **outcome(groups[n])} for n in report["selected"]]


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def producer_identity():
    root = Path(__file__).resolve().parents[1]
    names = ["ci_v3_real_contract.py", "ci_v3_pytest_adapter.py", "ci_v3_real_child.py", "ci_v3_pytest_config.py",
             "ci_v3_process_observer.py", "ci_v3_shadow_local.py", "ci_v3_observed_verify.py",
             "ci_v3_evidence_verify.py", "ci_v3_schema.py", "ci_v3_partition_plan.py",
             "ci_v3_runtime_fingerprint.py"]
    return {"evaluator": REAL_EVALUATOR, "files_sha256": {"tools/" + n: file_sha(root / "tools" / n) for n in names}}
