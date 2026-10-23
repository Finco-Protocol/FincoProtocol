"""Isolated candidate execution (V10-04 containment, V10-07, review §7.4 "authoritative shadow").

A native fault (SIGSEGV, heap corruption, runaway loop, memory blow-up) cannot be caught by Python
``except``. Before native safety is admitted, the candidate therefore runs in a separate, killable,
resource-limited worker process and only *evidence* comes back:

* ``authoritative_shadow``: the canonical Run executes in the caller's process and alone determines
  the returned result, exceptions, Integrity and commit eligibility. The same inputs run in a worker
  with ``NativeConfig(mode="candidate")``; the worker returns verdict + exact digests + native
  counters. Mismatch / decline / crash / timeout / memory exhaustion are recorded, never returned.
* ``candidate_then_canonical``: research topology for the later replace-mode decision (NOT admitted):
  the candidate Run executes in a worker (as production already runs the engine in spawned workers);
  if the worker crashes or times out before returning, nothing was committed, so the canonical Run
  executes in a fresh worker with native OFF and the fallback is recorded explicitly.

Workers are spawned (no fork of a possibly-corrupted parent heap), single-use for shadow evidence,
with RLIMIT_AS / RLIMIT_CPU limits. Resource limits never become financial outcomes: a limited or
killed candidate yields CANDIDATE_* evidence, the canonical outcome is unaffected.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import time
from dataclasses import dataclass, field

CTX = mp.get_context("spawn")


@dataclass(frozen=True)
class WorkerLimits:
    timeout_seconds: float = 300.0
    address_space_bytes: int = 4 * 1024 ** 3
    cpu_seconds: int = 900


@dataclass
class CandidateEvidence:
    status: str                     # OK | CANDIDATE_EXCEPTION | CANDIDATE_CRASH | CANDIDATE_TIMEOUT
    verdict: str | None = None
    digests: dict = field(default_factory=dict)
    error: str | None = None
    native: dict = field(default_factory=dict)
    exitcode: int | None = None
    wall_seconds: float = 0.0


def _limit(limits: WorkerLimits) -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (limits.address_space_bytes, limits.address_space_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 5))
    except (ImportError, ValueError, OSError):
        pass


def _worker_main(conn, bootstrap: str | None, task: str, payload: dict, limits: WorkerLimits) -> None:
    _limit(limits)
    try:
        if bootstrap:
            __import__(bootstrap)
        module_name, _, func_name = task.rpartition(".")
        func = getattr(__import__(module_name, fromlist=[func_name]), func_name)
        conn.send(("OK", func(**payload)))
    except BaseException as exc:  # noqa: BLE001 - report, never re-raise across the boundary
        conn.send(("CANDIDATE_EXCEPTION", f"{type(exc).__name__}: {str(exc)[:500]}"))
    finally:
        conn.close()


def run_in_worker(task: str, payload: dict, *, bootstrap: str | None = None,
                  limits: WorkerLimits = WorkerLimits()) -> CandidateEvidence:
    """Run ``task(**payload)`` in a fresh spawned worker; return evidence, never raise."""
    parent, child = CTX.Pipe(duplex=False)
    proc = CTX.Process(target=_worker_main, args=(child, bootstrap, task, payload, limits), daemon=True)
    started = time.perf_counter()
    proc.start()
    child.close()
    result = None
    if parent.poll(limits.timeout_seconds):
        try:
            result = parent.recv()
        except (EOFError, OSError):
            result = None
    wall = time.perf_counter() - started
    if proc.is_alive():
        proc.kill()
    proc.join(10)
    if result is None:
        status = "CANDIDATE_TIMEOUT" if wall >= limits.timeout_seconds else "CANDIDATE_CRASH"
        return CandidateEvidence(status=status, exitcode=proc.exitcode, wall_seconds=wall)
    kind, body = result
    if kind != "OK":
        return CandidateEvidence(status=kind, error=body, exitcode=proc.exitcode, wall_seconds=wall)
    return CandidateEvidence(status="OK", verdict=body.get("verdict"), digests=body.get("digests", {}),
                             error=body.get("error"), native=body.get("native", {}), exitcode=proc.exitcode,
                             wall_seconds=wall)


def compare(canonical: dict, candidate: CandidateEvidence) -> dict:
    """Exact comparison of canonical evidence with candidate evidence (verdict, error text, digests)."""
    if candidate.status != "OK":
        return {"outcome": candidate.status, "equal": False}
    keys = sorted(set(canonical["digests"]) | set(candidate.digests))
    diff = [k for k in keys if canonical["digests"].get(k) != candidate.digests.get(k)]
    same_verdict = canonical["verdict"] == candidate.verdict and canonical.get("error") == candidate.error
    return {"outcome": "MATCH" if same_verdict and not diff else "MISMATCH", "equal": same_verdict and not diff,
            "differing": diff, "native": candidate.native}
