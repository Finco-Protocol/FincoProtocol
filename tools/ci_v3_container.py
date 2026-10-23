"""Trusted Linux host observer. Test containers never receive Actions credentials."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid

from tools.ci_v3_schema import read_json, require, write_json


def image_ref(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9./_-]+@sha256:[0-9a-f]{64}", value), "image must be an immutable registry digest")
    return value


def subject_bytes(root, names):
    """Read data only after subject execution; never execute subject-modified Git config."""
    root = Path(root).resolve()
    result = {}
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            return None
        result[name] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o111)
    return result


def passwd_file(path, uid, gid):
    """Read-only /etc/passwd with the numeric host user (OpenSSH and other tools refuse a uid that has no entry,
    which the hosted control runner always has). Contains no credentials."""
    entries = ["root:x:0:0:root:/root:/usr/sbin/nologin"]
    if uid != 0:
        entries.append(f"ci:x:{int(uid)}:{int(gid)}:ci:/tmp/home:/usr/sbin/nologin")
    Path(path).write_text("\n".join(entries) + "\n", encoding="ascii")
    return Path(path)


def docker_command(image, name, project, bootstrap, evidence, worker, context=None, passwd=None, local_review=False, built_image=False):
    if local_review or built_image:
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", image or ""), "local review requires immutable image config ID")
    else:
        image_ref(image)
    require(re.fullmatch(r"ci-v3-[0-9a-f]{32}", name), "unsafe container identity")
    require(sys.platform != 'linux' or os.getuid() != 0, "test containers require a non-root host identity")
    args = ["docker", "run", "--rm", "--name", name, "--init", "--network=none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=512", "--memory=6g",
        "--user", f"{os.getuid()}:{os.getgid()}" if sys.platform == "linux" else "1001:1001",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=2g", "--workdir", "/subject"]
    mounts = [(project, "/subject", False), (bootstrap, "/bootstrap", True), (evidence, "/evidence", False)]
    if passwd is not None:
        mounts.append((passwd, "/etc/passwd", True))
    for source, target, readonly in mounts:
        require("," not in str(source), "unsupported mount path")
        args += ["--mount", f"type=bind,source={Path(source).resolve()},target={target}" + (",readonly" if readonly else "")]
    env = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp/home",
        "TMPDIR": "/evidence/tmp", "TMP": "/evidence/tmp", "TEMP": "/evidence/tmp",
        "CI_V3_WORKER_TMPDIR": "/evidence/tmp", "CI_V3_WORKER_ID": worker or "discover",
        "GIT_CONFIG_NOSYSTEM": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
    if context is not None:
        env.update(CI="true", GITHUB_ACTIONS="true", GITHUB_EVENT_NAME="workflow_dispatch",
            GITHUB_RUN_ID=str(context["run_id"]), GITHUB_RUN_ATTEMPT=str(context["attempt"]),
            GITHUB_REPOSITORY=context["repository"], GITHUB_SHA=context["source"]["head"], GITHUB_WORKSPACE="/subject",
            FINCO_CI_TESTED_SHA=context["source"]["head"], FINCO_CI_TESTED_TREE=context["source"]["tree"])
    for key, value in env.items():
        args += ["--env", key + "=" + value]
    entry = 'ci_v3_built_image_child.py' if built_image else 'ci_v3_real_child.py'
    return args + (["--pull=never"] if local_review or built_image else []) + [image, "python", "-I", "/bootstrap/tools/" + entry, "/evidence/request.json"]


def copy_tracked_source(project, sandbox):
    """Fresh tracked bytes/history; never copy ignored host databases or credentials."""
    sandbox = Path(sandbox); sandbox.mkdir()
    archive = subprocess.check_output(["git", "-C", str(project), "archive", "--format=tar", "HEAD"])
    import io
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tracked = []
        for member in tar:
            require(member.isdir() or member.isfile(), "non-regular source archive member")
            require(not Path(member.name).is_absolute() and ".." not in Path(member.name).parts, "unsafe source archive")
            if member.isfile():
                tracked.append(member.name)
        tar.extractall(sandbox, filter="data")
    gitdir = Path(subprocess.check_output(["git", "-C", str(project), "rev-parse", "--absolute-git-dir"], text=True).strip())
    require((gitdir / "objects").is_dir() and not (gitdir / "commondir").exists(), "hosted source must be standalone checkout")
    shutil.copytree(gitdir, sandbox / ".git")
    # No host credentials or custom Git helper/config is made available to tests.
    (sandbox / ".git/config").write_text('[core]\nrepositoryformatversion = 0\nbare = false\nfilemode = true\n', encoding="ascii")
    identities = [".git/HEAD", ".git/packed-refs"]
    head = (sandbox / ".git/HEAD").read_text().strip()
    if head.startswith("ref: "):
        identities.append(".git/" + head[5:])
    identities = [p for p in identities if (sandbox / p).is_file()]
    return tracked + identities


def observe_container(request, directory, project, image, timeout_s, local_review=False, built_image=False):
    require(sys.platform == "linux", "hosted test execution requires Linux; no insecure fallback")
    require(type(timeout_s) is int and 1 <= timeout_s <= (12600 if request.get("worker") == "control" else 5400), "hosted timeout out of bounds")
    require(not (local_review and built_image), 'choose local review or run-built artifact image')
    if built_image:
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', image or ''), 'run-built image config identity missing')
        require(str(request['context']['run_id']).isdecimal() and int(request['context']['run_id']) > 0,
                'run-built image requires real run binding')
        actual = subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()
        require(actual == image, 'run-built immutable image differs')
    if local_review:
        require(request["context"].get("run_id") == "0", "local image review cannot use a hosted run")
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", image or ""), "local review requires image config ID")
        actual = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
        require(actual == image, "local immutable image identity mismatch")
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    evidence = directory / "child"; evidence.mkdir(); (evidence / "tmp").mkdir()
    bootstrap = directory / "bootstrap"; bootstrap.mkdir()
    shutil.copytree(Path(__file__).resolve().parent, bootstrap / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    sandbox = directory / "source"
    tracked = copy_tracked_source(project, sandbox)
    before_bytes = subject_bytes(sandbox, tracked)
    require(before_bytes is not None, "invalid private source copy")
    before_python = {p.relative_to(sandbox).as_posix() for p in sandbox.rglob("*.py")}
    child_request = {**request, "project": "/subject", "hosted": True}
    if built_image:
        child_request['finalize_owned_multiprocessing'] = True
    write_json(evidence / "request.json", child_request)
    (evidence / "release").write_text("host container isolation established\n", encoding="ascii")
    name = "ci-v3-" + uuid.uuid4().hex
    uid, gid = (os.getuid(), os.getgid()) if sys.platform == "linux" else (1001, 1001)
    command = docker_command(image, name, sandbox, bootstrap, evidence, request.get("worker"), request["context"],
                             passwd_file(directory / "passwd", uid, gid), local_review=local_review, built_image=built_image)
    timed_out = False; cancelled = False; started = time.perf_counter()
    process = None; cleanup_ok = False
    try:
        with (evidence / "process.log").open("wb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
    except BaseException:
        cancelled = True
        raise
    finally:
        # Docker CLI process-group death alone does not terminate its container.
        cleanup_error = None
        try:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            cleanup_error = type(exc).__name__
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
        try:
            inspect = subprocess.run(["docker", "container", "inspect", name], capture_output=True, timeout=30)
            cleanup_ok = inspect.returncode != 0 and any(term in inspect.stderr.lower() for term in
                                                        (b"no such object", b"no such container"))
        except (OSError, subprocess.SubprocessError) as exc:
            cleanup_error = type(exc).__name__
        try:
            source_unchanged = subject_bytes(sandbox, tracked) == before_bytes
            source_unchanged = source_unchanged and {p.relative_to(sandbox).as_posix() for p in sandbox.rglob("*.py")} == before_python
        except OSError:
            source_unchanged = False
        write_json(directory / "host-finalization.json", {"container": name, "image": image,
            "cancelled": cancelled, "timed_out": timed_out, "container_removed": cleanup_ok,
            "source_bytes_unchanged": source_unchanged,
            "cleanup_error": cleanup_error, "os_exit_code": process.returncode if process else None})
    elapsed = round((time.perf_counter() - started) * 1000)
    returned = read_json(evidence / "pytest-return.json") if (evidence / "pytest-return.json").exists() else None
    final = read_json(evidence / "interpreter-exit.json") if (evidence / "interpreter-exit.json").exists() else None
    normal = (process.returncode == 0 and not timed_out and not cancelled and cleanup_ok and source_unchanged and returned is not None
              and returned["code"] == 0 and not any(returned["leaks"].values()) and final is not None and final.get("finalizing") is True)
    descendant = read_json(evidence/'descendant-cleanup.json') if (evidence/'descendant-cleanup.json').exists() else None
    if built_image:
        normal = normal and descendant is not None and descendant.get('cleanup_verified') is True
    return evidence, {"worker": request.get("worker"), "os_exit_code": process.returncode, "timed_out": timed_out,
        "normal_successful_exit": normal, "elapsed_ms": elapsed, "pytest_return": returned, "interpreter_exit": final,
        "temporary_directory": str(evidence / "tmp"), "startup_ms": None, "shutdown_ms": None,
        "containment": "docker-private-linux-posix-group-v1", "container_removed": cleanup_ok, "image": image,
        "source_bytes_unchanged": source_unchanged,
        "cancelled": cancelled, "local_image_review": local_review,
        "built_image": built_image, "descendant_cleanup": descendant,
        "registry_digest": None if local_review or built_image else image.rsplit("@", 1)[1]}
