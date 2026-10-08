"""Child process of tools/ci_pytest_runner.py: runs pytest with hang diagnostics.

Prints explicit markers so a supervisor can tell WHERE a stall happens:
  A. before ``pytest.main`` returns        -> tests / fixture teardown / session finish
  B. after ``pytest.main`` returned        -> interpreter shutdown (threads, pools, atexit)
The exit code is exactly pytest's; nothing here converts a stall into success.
"""
from __future__ import annotations

import faulthandler
import multiprocessing
import signal
import sys
import threading

MARK = "FINCO_CI_MARKER"


def _live_state() -> str:
    lines = []
    for t in threading.enumerate():
        if t is threading.main_thread():
            continue
        lines.append(f"  thread name={t.name!r} daemon={t.daemon} alive={t.is_alive()}")
    for p in multiprocessing.active_children():
        lines.append(f"  child pid={p.pid} name={p.name!r} alive={p.is_alive()}")
    return "\n".join(lines) or "  (none)"


def main() -> int:
    faulthandler.enable(all_threads=True)
    faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
    print(f"PYTEST_MAIN_STARTED {MARK} before pytest.main pid={__import__('os').getpid()}", flush=True)
    import pytest

    rc = int(pytest.main(sys.argv[1:]))
    print(f"PYTEST_MAIN_RETURNED {MARK} after pytest.main rc={rc}", flush=True)
    print(f"{MARK} live threads/children after pytest.main:\n{_live_state()}", flush=True)
    return rc


if __name__ == "__main__":
    code = main()
    print(f"{MARK} interpreter exit begins rc={code}", flush=True)
    sys.stdout.flush()
    sys.exit(code)  # normal interpreter shutdown: never os._exit, never forced success
