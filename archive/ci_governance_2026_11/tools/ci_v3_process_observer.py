"""Finite, process-tree-contained local subprocess observation. No marker implies success."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from tools.ci_v3_schema import read_json, require, write_json


def posix_group_members(group):
    """Linux kernel observations, including subprocess.Popen children (not just multiprocessing)."""
    members = []
    for entry in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = entry.read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group and fields[0] != 'Z' and int(entry.parent.name) != group:
                members.append(int(entry.parent.name))
        except (OSError, ValueError, IndexError):
            continue
    return sorted(members)


class WindowsJob:
    """Anonymous kill-on-close job. Child waits for a parent release before imports."""
    def __init__(self, process):
        class Basic(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64), ("Flags", wintypes.DWORD),
                        ("MinWorking", ctypes.c_size_t), ("MaxWorking", ctypes.c_size_t),
                        ("ActiveLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [("x%d" % i, ctypes.c_uint64) for i in range(6)]
        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", IO), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t), ("PeakJob", ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        require(bool(self.handle), "cannot create bounded Windows job")
        info = Extended(); info.Basic.Flags = 0x2000
        if not (self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                and self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle)))):
            self.close()
            raise OSError("cannot contain synthetic worker in Windows job")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def observe(request, directory, timeout_s):
    require(isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool)
            and 0 < timeout_s <= 120, "local synthetic timeout must be finite and <=120 seconds")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "tmp").mkdir()
    write_json(directory / "request.json", request)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
               TMP=str(directory / "tmp"), TEMP=str(directory / "tmp"), TMPDIR=str(directory / "tmp"),
               CI_V3_WORKER_TMPDIR=str(directory / "tmp"), CI_V3_WORKER_ID=request.get("worker") or "discover")
    child = Path(__file__).with_name("ci_v3_real_child.py")
    started = time.perf_counter()
    timed_out = False
    job = None
    survivors = []
    cleanup_complete = True
    with (directory / "process.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-I", str(child), str(directory / "request.json")],
            cwd=request["project"], env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        try:
            if os.name == "nt":
                job = WindowsJob(process)
            (directory / "release").write_text("parent containment established\n", encoding="ascii")
            try:
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                if job:
                    job.close()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        except BaseException:
            if job:
                job.close()
            elif os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()  # child never received its release; no subject code ran
            process.wait(timeout=10)
            raise
        finally:
            if job:
                job.close()
            elif os.name != "nt":
                survivors = posix_group_members(process.pid)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 3
                while posix_group_members(process.pid) and time.monotonic() < deadline:
                    time.sleep(0.02)
                cleanup_complete = not posix_group_members(process.pid)
    elapsed = round((time.perf_counter() - started) * 1000)
    returned = read_json(directory / "pytest-return.json") if (directory / "pytest-return.json").exists() else None
    final = read_json(directory / "interpreter-exit.json") if (directory / "interpreter-exit.json").exists() else None
    bootstrap = read_json(directory / "bootstrap-start.json") if (directory / "bootstrap-start.json").exists() else None
    startup = round(bootstrap["perf_ns"] / 1_000_000 - started * 1000) if bootstrap else None
    normal = (process.returncode == 0 and not timed_out and returned is not None and returned["code"] == 0
              and not any(returned["leaks"].values()) and final is not None and final.get("finalizing") is True
              and not survivors and cleanup_complete)
    return {"worker": request.get("worker"), "os_exit_code": process.returncode, "timed_out": timed_out,
            "normal_successful_exit": normal, "elapsed_ms": elapsed, "pytest_return": returned,
            "interpreter_exit": final, "temporary_directory": str(directory / "tmp"),
            "startup_ms": startup,
            "surviving_descendants_at_parent_exit": survivors, "descendant_cleanup_complete": cleanup_complete,
            "shutdown_ms": max(0, elapsed - startup - returned["pytest_returned_ms"]) if returned and startup is not None else None,
            "containment": "windows-job-kill-on-close" if os.name == "nt" else "posix-process-group"}
