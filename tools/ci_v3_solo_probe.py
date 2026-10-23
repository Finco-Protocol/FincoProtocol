"""Run each test module alone in a fresh private copy of the subject (executed inside the image).

Empirical independence evidence only: a module that passes alone has no dependency on state left by other
modules. It is not an approval of shared-fixture isolation and never changes a test outcome."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# This file is also run with python -I from a read-only standalone bootstrap.
# Resolve only the trusted adjacent configuration, never the subject's tools.
if __package__:
    from .ci_v3_pytest_config import plugin_args
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ci_v3_pytest_config import plugin_args


def run_module(source, module, out, timeout, tag=None):
    work = Path("/tmp/work"); shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(source, work, symlinks=True)
    tmp = Path("/tmp/pt"); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
    xml = out / (module.replace("/", "__") + (f"__{tag}" if tag else "") + ".xml")
    env = {**os.environ, "TMPDIR": str(tmp), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    started = time.perf_counter(); timed_out = False
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider",
            *plugin_args(), "--basetemp", str(tmp / "b"), "--junitxml", str(xml), module],
            cwd=work, env=env, capture_output=True, timeout=timeout)
        code, tail = proc.returncode, proc.stdout.decode("utf-8", "replace")[-1500:]
    except subprocess.TimeoutExpired as exc:
        code, timed_out, tail = None, True, (exc.stdout or b"").decode("utf-8", "replace")[-1500:]
    counts = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    if xml.exists():
        suite = ET.parse(xml).getroot()
        suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
        counts = {k: int(suite.get(k, 0)) for k in counts}
    digest = hashlib.sha256(xml.read_bytes()).hexdigest() if xml.exists() else None
    blob = hashlib.sha256((Path(source) / module).read_bytes()).hexdigest()
    return {"module": module, "module_sha256": blob, "tag": tag, "junit_sha256": digest, "exit_code": code, "timed_out": timed_out, "seconds": round(time.perf_counter() - started, 2),
            **counts, "tail": tail if code != 0 else ""}


def main():
    source, modules_file, out, timeout = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    for entry in json.loads(modules_file.read_text()):  # a name, or {"module": name, "tag": repeat-label}
        module, tag = (entry, None) if isinstance(entry, str) else (entry["module"], entry.get("tag"))
        result = run_module(source, module, out, timeout, tag)
        with (out / "results.jsonl").open("a") as handle:
            handle.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
