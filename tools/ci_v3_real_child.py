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
    if request.get("hosted"):
        # The approved image includes this explicitly; no ambient plugin autoload.
        args += ["-p", "pytest_asyncio.plugin"]
    args.append("tests")
    started = round((time.perf_counter() - clock) * 1000)
    code = int(pytest.main(args, plugins=[adapter]))
    import multiprocessing
    import threading
    leaks = {"threads": [t.name for t in threading.enumerate() if t is not threading.main_thread() and t.is_alive()],
             "children": [p.pid for p in multiprocessing.active_children() if p.is_alive()]}
    write_json(directory / "pytest-return.json", {"code": code, "pytest_started_ms": started,
        "pytest_returned_ms": round((time.perf_counter() - clock) * 1000), "leaks": leaks,
        "pytest_import_ms": pytest_import_ms, "adapter_import_ms": adapter_import_ms})
    return code


if __name__ == "__main__":
    sys.exit(main())
