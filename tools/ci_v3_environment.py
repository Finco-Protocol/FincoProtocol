"""Source-controlled comparison of the sequential control environment with the shadow image.

Inputs are the control's own recorded install log / job log (downloaded from the Actions run) and the image's baked
manifests. Every item is `equal`, `different` or `unproven`; `fully_equivalent` is true only if nothing is different or
unproven that the owners have not explicitly accepted. This tool never changes a workflow or the image."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from tools.ci_v3_schema import seal

IGNORED = {"pip", "setuptools", "wheel"}


def norm(name):
    return name.lower().replace("_", "-")


def control_packages(install_log):
    result = {}
    for line in re.findall(r"Successfully installed (.*)", install_log):
        for token in line.split():
            name, _, version = token.rpartition("-")
            result[norm(name)] = version
    return result


def image_packages(freeze):
    return {norm(n): v for n, v in (l.strip().split("==", 1) for l in freeze.splitlines() if "==" in l)}


def item(name, control, shadow, status, note=""):
    return {"item": name, "control": control, "shadow": shadow, "status": status, "note": note}


def compare(install_log, job_log, freeze, system_list, python_version, tool_versions, os_release, accepted=()):
    ctl, img = control_packages(install_log), image_packages(freeze)
    diffs = {k: [ctl.get(k), img.get(k)] for k in sorted(set(ctl) | set(img)) if k not in IGNORED and ctl.get(k) != img.get(k)}
    ctl_python = (re.search(r"/Python/(\d+\.\d+\.\d+)/", install_log) or [None, None])[1]
    lines = [re.sub(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z\s*", "", line).strip() for line in job_log.splitlines()]   # strip Actions timestamps
    runner = (None, None, None)
    for index, line in enumerate(lines):
        match = re.fullmatch(r"Image:\s*(\S+)", line)
        if match and index + 1 < len(lines) and (version := re.fullmatch(r"Version:\s*(\S+)", lines[index + 1])):
            runner = (None, match.group(1), version.group(1)); break
    found = re.search(r"Python (\d+\.\d+\.\d+)", python_version)
    img_python = found.group(1) if found else None
    libc = next((l.split("=", 1)[1] for l in system_list.splitlines() if l.startswith("libc6=")), None)
    pretty = re.search(r'PRETTY_NAME="([^"]+)"', os_release)
    items = [
        item("python-version", ctl_python, img_python, "equal" if ctl_python == img_python else "different"),
        item("python-packages-direct-and-transitive", f"{len(ctl)} installed", f"{len(img)} frozen", "equal" if not diffs else "different",
             json.dumps(diffs) if diffs else "identical versions for this snapshot; constraints.txt pins only direct requirements, so transitive drift remains possible"),
        item("native-numerical-libraries", "numpy/scipy/pandas wheels (bundled BLAS) by version above", "same wheels by version above",
             "equal" if not any(k in diffs for k in ("numpy", "scipy", "pandas")) else "different", "bundled OpenBLAS inside wheels; not separately hashed"),
        item("native-thread-variables", "unset (workflow defines none)", "OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS=1", "different",
             "owners must reconcile; the mandatory workflow is deliberately not edited"),
        item("operating-system", f"{runner[1]} {runner[2]}" if runner[1] else None, pretty.group(1) if pretty else None, "different",
             "hosted Ubuntu 24.04 runner vs Debian-based image"),
        item("libc", "Ubuntu 24.04 glibc (not recorded in artifacts)", libc, "unproven"),
        item("optional-tools-node-ssh", "preinstalled on runner image (versions not recorded in artifacts)", tool_versions.strip().replace("\n", "; "), "unproven",
             "presence matters (tests skip without them); versions unproven"),
        item("pytest-plugin-config", "autoload on; -p tools.ci_pytest_inventory -p tools.ci_pytest_progress via tools/ci_pytest_runner.py",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; -p pytest_asyncio.plugin via the CI V3 adapter", "different",
             "different by design; equivalence of node ids and outcomes is checked by the coverage/nonpass comparison, not assumed"),
        item("cpu-and-start-up-speed", "hosted 4 vCPU runner (unmeasured here)", "see calibration evidence", "unproven",
             "tests/test_p0a_model_execution.py needs worker cold start <= 0.7 s; tools/ci_v3_calibrate.py gates this"),
    ]
    for entry in items:
        entry["accepted_by_owner"] = entry["item"] in accepted
    blocking = [e["item"] for e in items if e["status"] != "equal" and not e["accepted_by_owner"]]
    return seal({"schema": 1, "kind": "ci-v3-environment-equivalence", "items": items, "fully_equivalent": not blocking,
                 "admission_condition": "open" if not blocking else "closed", "unaccepted_differences": blocking})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("control-install-log", "control-job-log", "resolved-python", "resolved-system", "python-version", "tool-versions", "os-release", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--accept", nargs="*", default=[])
    args = parser.parse_args(argv)
    read = lambda p: Path(p).read_text(encoding="utf-8", errors="replace")
    result = compare(read(args.control_install_log), read(args.control_job_log), read(args.resolved_python), read(args.resolved_system),
                     read(args.python_version), read(args.tool_versions), read(args.os_release), tuple(args.accept))
    Path(args.output).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"fully_equivalent": result["fully_equivalent"], "unaccepted_differences": result["unaccepted_differences"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
