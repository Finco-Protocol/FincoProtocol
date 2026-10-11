"""Bounded, instrumented pytest supervisor for CI (Linux).

Runs ``tools/ci_pytest_child.py`` in its own process group and watches it from OUTSIDE
the pytest process.  If the child exceeds the budget, or does not exit within
``FINCO_CI_EXIT_GRACE_S`` after pytest.main() returned, the supervisor records the process
tree and per-thread Python stacks (SIGUSR1 -> faulthandler), terminates the group and
exits NONZERO (124).  A timeout is never reported as success; pytest's own exit code is
propagated unchanged otherwise.  No test is skipped, deselected or time-limited here.

Usage: python tools/ci_pytest_runner.py [pytest args...]
Env:   FINCO_CI_PYTEST_BUDGET_S (default 3000)   total wall-clock budget
       FINCO_CI_EXIT_GRACE_S    (default 180)    max time to exit after pytest.main returns
       FINCO_CI_DIAG_PATH       (default artifacts/ci-hang-diagnostics.txt)
       FINCO_CI_PROGRESS_DIR    (default artifacts/progress)  written by tools.ci_pytest_progress
       FINCO_CI_STALL_S         (default 300)    one bounded stall snapshot per phase lasting longer
       FINCO_CI_MAX_STALL_SNAPSHOTS (default 6)  hard cap on stall snapshots per run
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT_EXIT = 124


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def read_progress(progress_dir: Path | None) -> dict | None:
    """Last atomically written active-test record, or None (missing/torn/unreadable)."""
    if progress_dir is None:
        return None
    try:
        value = json.loads((progress_dir / "active.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _progress_line(progress_dir: Path | None, now: float | None = None) -> str:
    record = read_progress(progress_dir)
    if not record:
        return "no progress evidence (plugin inactive or no test started)"
    started = record.get("phase_started_epoch")
    age = f" for {(now if now is not None else time.time()) - started:.0f}s" if isinstance(started, (int, float)) else ""
    return (f"active={record.get('node')!r} phase={record.get('phase')!r}{age} "
            f"completed={record.get('completed')}/{record.get('selected')} last_completed={record.get('last_completed')!r}")


def _snapshot(pid: int, diag: Path, reason: str, progress_dir: Path | None = None) -> None:
    diag.parent.mkdir(parents=True, exist_ok=True)
    with diag.open("a", encoding="utf-8") as fh:
        fh.write(f"=== CI HANG DIAGNOSTICS ({reason}) at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ===\n")
        # every process of the pytest session (the child leads its own session)
        for cmd in (["ps", "--sid", str(pid), "-o", "pid,ppid,pgid,stat,etimes,nlwp,cmd", "--forest"],):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
            except Exception as exc:  # diagnostics must never mask the failure
                out = f"{cmd}: {exc}"
            fh.write(out + "\n")
        try:
            threads = Counter()
            for tid in os.listdir(f"/proc/{pid}/task"):
                comm = Path(f"/proc/{pid}/task/{tid}/comm").read_text().strip()
                wchan = Path(f"/proc/{pid}/task/{tid}/wchan").read_text().strip()
                threads[(comm, wchan)] += 1
            fh.write(f"  native threads: {sum(threads.values())} (bounded summary by comm/wchan)\n")
            for (comm, wchan), count in threads.most_common(12):
                fh.write(f"    {count:4d} x comm={comm} wchan={wchan}\n")
        except Exception as exc:
            fh.write(f"  /proc task listing unavailable: {exc}\n")
        fh.write(f"  progress: {_progress_line(progress_dir)}\n")
    print(f"FINCO_CI_SUPERVISOR diagnostics appended to {diag}", flush=True)


def main(argv: list[str]) -> int:
    budget = _env_int("FINCO_CI_PYTEST_BUDGET_S", 3000)
    grace = _env_int("FINCO_CI_EXIT_GRACE_S", 180)
    diag = Path(os.environ.get("FINCO_CI_DIAG_PATH", "artifacts/ci-hang-diagnostics.txt"))
    progress_dir = Path(os.environ.get("FINCO_CI_PROGRESS_DIR", "artifacts/progress"))
    stall = _env_int("FINCO_CI_STALL_S", 300)
    max_stall_snapshots = _env_int("FINCO_CI_MAX_STALL_SNAPSHOTS", 6)
    stall_snapshots, last_stall_key = 0, None
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    child = subprocess.Popen(
        [sys.executable, "-u", str(HERE / "ci_pytest_child.py"), *argv],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        start_new_session=True, env=env,
    )
    state = {"main_returned_at": None}

    def pump() -> None:
        assert child.stdout is not None
        for line in child.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if "FINCO_CI_MARKER after pytest.main" in line:
                state["main_returned_at"] = time.monotonic()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    started = time.monotonic()
    reason = None
    while child.poll() is None:
        now = time.monotonic()
        if now - started > budget:
            reason = f"budget {budget}s exceeded while pytest was still running (tests/fixtures/session finish)"
        elif state["main_returned_at"] and now - state["main_returned_at"] > grace:
            reason = f"pytest.main returned but interpreter did not exit within {grace}s (shutdown hang)"
        if reason:
            break
        if stall_snapshots < max_stall_snapshots:
            record = read_progress(progress_dir)
            started_at = record.get("phase_started_epoch") if record else None
            if isinstance(started_at, (int, float)) and record.get("node") and time.time() - started_at > stall:
                key = (record.get("node"), record.get("phase"), started_at)
                if key != last_stall_key:
                    last_stall_key = key
                    stall_snapshots += 1
                    line = _progress_line(progress_dir)
                    print(f"FINCO_CI_SUPERVISOR STALL (> {stall}s in one phase): {line}", flush=True)
                    _snapshot(child.pid, diag, f"stall > {stall}s", progress_dir)
        time.sleep(2)

    if reason is None:
        reader.join(timeout=10)
        print(f"PYTHON_PROCESS_EXITED FINCO_CI_SUPERVISOR child exit code {child.returncode}", flush=True)
        return int(child.returncode)

    print(f"FINCO_CI_SUPERVISOR TIMEOUT: {reason}", flush=True)
    print(f"FINCO_CI_SUPERVISOR ACTIVE AT TIMEOUT: {_progress_line(progress_dir)}", flush=True)
    _snapshot(child.pid, diag, reason, progress_dir)
    try:
        os.kill(child.pid, signal.SIGUSR1)   # faulthandler: all Python thread stacks -> child's stderr
    except ProcessLookupError:
        pass
    time.sleep(5)                            # let the stacks reach the log
    reader.join(timeout=3)
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            break
        try:
            child.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
    with diag.open("a", encoding="utf-8") as fh:
        fh.write("Python thread stacks (faulthandler/SIGUSR1) are in the job log after the TIMEOUT marker.\n")
    return TIMEOUT_EXIT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
