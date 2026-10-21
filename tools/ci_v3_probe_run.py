"""Run standalone-module probes in N concurrent private containers and write attempt evidence with an identity file.

Kinds: `first` (full-suite pass), `uncontended` (re-run alone), `target` (equivalent target concurrency: three
worker-sized containers at once, each module repeated). Cleanup is explicit: every container is removed and its
absence verified, even on interruption."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from tools.ci_v3_container import image_ref
from tools.ci_v3_schema import require, write_json

KINDS = ("first", "uncontended", "target")


def lanes(entries, count, weights):
    """Longest-processing-time assignment of (module, tag) entries to lanes; deterministic."""
    result, load = [[] for _ in range(count)], [0] * count
    for entry in sorted(entries, key=lambda e: (-weights.get(e["module"], 1), e["module"], e["tag"] or "")):
        index = load.index(min(load)); result[index].append(entry); load[index] += weights.get(entry["module"], 1) + 10
    return result


def run(args):
    require(args.kind in KINDS and args.lanes >= 1 and args.repeat >= 1, "bad probe parameters")
    image_ref(args.image)
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    modules = json.loads(Path(args.modules).read_text())
    weights = json.loads(Path(args.weights).read_text())["modules_ms"] if args.weights else {}
    entries = [{"module": m, "tag": f"r{r}" if args.repeat > 1 else None} for r in range(args.repeat) for m in modules]
    assignment = lanes(entries, args.lanes, weights)
    write_json(out / "meta.json", {"kind": args.kind, "label": args.label, "image": args.image, "image_id": args.image_id,
        "tree": args.tree, "head": args.head, "concurrency": args.lanes, "cpus_per_container": args.cpus, "memory": args.memory,
        "repeat": args.repeat, "timeout_s": args.timeout, "boot_files_sha256": args.boot_sha})
    names, procs, started = [], [], time.perf_counter()
    def cleanup(*_):
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
    def terminate(signum, frame):
        raise KeyboardInterrupt("probe cancelled")
    signal.signal(signal.SIGTERM, terminate)
    try:
        for index, lane in enumerate(assignment):
            lane_dir = out / f"lane-{index}"; lane_dir.mkdir(); lane_dir.chmod(0o777)
            write_json(lane_dir / "lane.json", lane); (lane_dir / "lane.json").chmod(0o644)
            name = "ci-v3-probe-" + uuid.uuid4().hex; names.append(name)
            command = ["docker", "run", "--name", name, "--init", "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=512", f"--memory={args.memory}", f"--cpus={args.cpus}", "--user", "1001:1001",
                "--tmpfs", "/tmp:rw,nosuid,nodev,exec,size=3g", "-e", "HOME=/tmp/home", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "CI=true",
                "-e", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "-e", "OMP_NUM_THREADS=1", "-e", "MKL_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1",
                "-e", "NUMEXPR_NUM_THREADS=1",
                "--mount", f"type=bind,source={Path(args.source).resolve()},target=/src,readonly",
                "--mount", f"type=bind,source={Path(args.boot).resolve()},target=/boot,readonly",
                "--mount", f"type=bind,source={lane_dir / 'lane.json'},target=/lane.json,readonly",
                "--mount", f"type=bind,source={lane_dir},target=/out", args.image,
                "python", "-I", "/boot/ci_v3_solo_probe.py", "/src", "/lane.json", "/out", str(args.timeout)]
            procs.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
        codes = [p.wait() for p in procs]
    finally:
        cleanup()
        gone = all(subprocess.run(["docker", "container", "inspect", n], capture_output=True).returncode != 0 for n in names)
    write_json(out / "run.json", {"container_exit_codes": codes, "containers_removed": gone, "wall_s": round(time.perf_counter() - started, 1)})
    require(gone, "probe containers were not removed")
    return codes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "image-id", "tree", "head", "source", "boot", "modules", "output", "label", "boot-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--kind", required=True, choices=KINDS); parser.add_argument("--weights")
    parser.add_argument("--lanes", type=int, default=4); parser.add_argument("--cpus", default="1"); parser.add_argument("--memory", default="3500m")
    parser.add_argument("--repeat", type=int, default=1); parser.add_argument("--timeout", type=int, default=1500)
    args = parser.parse_args(argv)
    return 0 if not any(run(args)) else 1


if __name__ == "__main__":
    sys.exit(main())
