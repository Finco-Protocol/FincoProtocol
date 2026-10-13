"""Opt-in, CI-only pytest progress recorder with flush-safe partial evidence.

Purpose: when a full-suite job is killed by the supervisor (exit 124) the normal evidence
(inventory.json, JUnit) is never written.  This plugin keeps a small, always-current record
of WHICH test/fixture phase was running and how long every finished test took, so a timeout
is diagnosable from the uploaded artifact instead of from a percentage counter.

Inert unless ``--ci-progress=DIR`` is given.  It never selects, deselects, reorders, skips,
reports or alters a test; it only observes hooks and writes files:

  DIR/active.json   atomically replaced at each setup/call/teardown transition
                    (active node, phase, phase start, last completed node, counters)
  DIR/tests.jsonl   one line per finished test: phase durations and outcome (flushed per line)
  DIR/summary.json  written at session finish (totals, slowest tests, slowest modules)

I/O failures are swallowed: evidence must never turn a passing suite into a failing one.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import pytest

SCHEMA = 1
PHASES = ("setup", "call", "teardown")


def pytest_addoption(parser):
    parser.getgroup("finco-ci-evidence").addoption(
        "--ci-progress", default=None,
        help="directory for flush-safe active-test/progress evidence (CI only)")


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{int((ts % 1) * 1000):03d}Z"


class Recorder:
    def __init__(self, directory: Path):
        self.dir = directory
        self.active = directory / "active.json"
        self.lines = None
        self.state = {"schema": SCHEMA, "pid": os.getpid(), "selected": 0, "completed": 0,
                      "last_completed": None, "node": None, "phase": None,
                      "phase_started_epoch": None, "phase_started_utc": None, "updated_utc": None}
        self.durations: dict[str, dict] = {}
        self.started = time.time()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.lines = (directory / "tests.jsonl").open("a", encoding="utf-8", buffering=1)
        except OSError:
            self.lines = None

    def _write_active(self) -> None:
        try:
            tmp = self.active.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, self.active)          # readers never see a torn file
        except OSError:
            pass

    def phase(self, node: str | None, phase: str | None) -> None:
        now = time.time()
        self.state.update(node=node, phase=phase, phase_started_epoch=round(now, 3),
                          phase_started_utc=_utc(now), updated_utc=_utc(now))
        self._write_active()

    def finished(self, node: str, record: dict) -> None:
        self.durations[node] = record
        self.state["completed"] += 1
        self.state["last_completed"] = node
        if self.lines is not None:
            try:
                self.lines.write(json.dumps({"n": node, **record}, sort_keys=True) + "\n")
                self.lines.flush()
            except OSError:
                pass

    def summary(self) -> dict:
        return summarize(self.durations, wall=time.time() - self.started)


def summarize(durations: dict, wall: float | None = None) -> dict:
    totals = {n: round(sum(r.get(p, 0.0) for p in ("s", "c", "t")), 3) for n, r in durations.items()}
    modules: dict[str, float] = defaultdict(float)
    for node, total in totals.items():
        modules[node.split("::", 1)[0]] += total
    slow = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:50]
    return {"schema": SCHEMA, "tests_recorded": len(totals), "sum_test_seconds": round(sum(totals.values()), 3),
            "wall_seconds": None if wall is None else round(wall, 3),
            "slowest_tests": [[n, t] for n, t in slow],
            "slowest_modules": [[m, round(t, 3)] for m, t in sorted(modules.items(), key=lambda kv: (-kv[1], kv[0]))[:40]]}


def report(directory: Path, top: int = 40) -> str:
    """Human-readable job-log rendering of the (possibly partial) progress evidence."""
    out = []
    try:
        active = json.loads((directory / "active.json").read_text(encoding="utf-8"))
        out.append(f"CI_PROGRESS active={active.get('node')!r} phase={active.get('phase')!r} "
                   f"since={active.get('phase_started_utc')} completed={active.get('completed')}/{active.get('selected')} "
                   f"last_completed={active.get('last_completed')!r}")
    except (OSError, ValueError):
        out.append("CI_PROGRESS no active.json")
    durations = {}
    try:
        for line in (directory / "tests.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)          # a line torn by a kill is skipped, never trusted
                durations[record.pop("n")] = record
            except (ValueError, KeyError, AttributeError):
                continue
    except OSError:
        out.append("CI_PROGRESS no tests.jsonl")
        return "\n".join(out)
    summary = summarize(durations)
    out.append(f"CI_PROGRESS tests_recorded={summary['tests_recorded']} sum_test_seconds={summary['sum_test_seconds']}")
    for module, seconds in summary["slowest_modules"][:top // 2]:
        out.append(f"CI_PROGRESS module {seconds:9.1f}s {module}")
    for node, seconds in summary["slowest_tests"][:top]:
        out.append(f"CI_PROGRESS test   {seconds:9.1f}s {node}")
    return "\n".join(out)


_REC: Recorder | None = None


def pytest_configure(config):
    global _REC
    target = config.getoption("ci_progress", None)
    _REC = Recorder(Path(target)) if target else None


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    rec = _REC
    if rec:
        rec.state["selected"] = len(items)
        rec.phase(None, "collected")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    rec = _REC
    if rec:
        rec.phase(item.nodeid, "setup")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item):
    rec = _REC
    if rec:
        rec.phase(item.nodeid, "call")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    rec = _REC
    if rec:
        rec.phase(item.nodeid, "teardown" if nextitem is not None else "teardown(session/module fixtures)")


def pytest_runtest_logreport(report):
    rec = _REC
    if rec is None or report.when not in PHASES:
        return
    node = report.nodeid
    current = rec.durations.setdefault(node, {})
    current[{"setup": "s", "call": "c", "teardown": "t"}[report.when]] = round(float(report.duration), 3)
    outcome = report.outcome
    if hasattr(report, "wasxfail"):
        outcome = "xpass" if report.passed else "xfail"
    if report.when != "call" or report.failed or report.skipped:
        current.setdefault("o", outcome)
    if report.failed:
        current["o"] = "failed"
    if report.when == "teardown":
        current.setdefault("o", "passed")
        current["u"] = _utc(time.time())
        rec.durations.pop(node, None)
        rec.finished(node, current)
        rec.phase(None, "between-tests")


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    rec = _REC
    if rec is None:
        return
    rec.phase(None, "session-finished")
    try:
        (rec.dir / "summary.json").write_text(json.dumps(rec.summary(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if rec.lines is not None:
            rec.lines.close()
    except OSError:
        pass


if __name__ == "__main__":      # python -m tools.ci_pytest_progress [DIR]  (always exits 0: evidence, not a gate)
    import sys
    print(report(Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/progress")))
