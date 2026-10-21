"""Actual ModelExecutor dispatch and result transfer, with private output evidence."""
from __future__ import annotations

import argparse
import concurrent.futures
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import threading
import time


def financial_return_digest(value):
    """Compare actual leaves, not pickle memo aliasing or pandas block layout."""
    import dataclasses
    from datetime import date, datetime
    from decimal import Decimal
    from enum import Enum
    import struct
    import numpy as np
    import pandas as pd
    def freeze(item):
        if isinstance(item, pd.DataFrame):
            return ("DataFrame", freeze(item.index), freeze(item.columns),
                    tuple(freeze(item.iloc[:, i].to_numpy()) for i in range(len(item.columns))),
                    tuple(str(dtype) for dtype in item.dtypes), freeze(item.attrs))
        if isinstance(item, pd.Series):
            return ("Series", freeze(item.index), freeze(item.name), freeze(item.to_numpy()), freeze(item.attrs))
        if isinstance(item, pd.Index):
            return (type(item).__qualname__, freeze(item.to_numpy()), freeze(item.names))
        if item is pd.NA:
            return ("pandas.NA",)
        if isinstance(item, np.ndarray):
            contents = tuple(freeze(v) for v in item.flat) if item.dtype.hasobject else item.tobytes(order="C").hex()
            return ("ndarray", str(item.dtype), item.shape, contents)
        if isinstance(item, np.generic):
            return ("numpy_scalar", str(item.dtype), item.tobytes().hex())
        if isinstance(item, Enum):
            return (type(item).__qualname__, item.name)
        if isinstance(item, float):
            return ("float64", struct.pack(">d", item).hex())
        if item is None or isinstance(item, (str, int, bool)):
            return (type(item).__name__, item)
        if isinstance(item, (date, datetime, Decimal)):
            return (type(item).__qualname__, str(item))
        if dataclasses.is_dataclass(item):
            return (type(item).__qualname__, tuple((f.name, freeze(getattr(item, f.name)))
                    for f in dataclasses.fields(item)))
        if isinstance(item, dict):
            return ("dict", tuple((freeze(k), freeze(v)) for k, v in item.items()))
        if isinstance(item, (list, tuple, set, frozenset)):
            values = sorted(item, key=repr) if isinstance(item, (set, frozenset)) else item
            return (type(item).__name__, tuple(freeze(v) for v in values))
        if hasattr(item, "__dict__"):
            return (type(item).__qualname__, freeze(vars(item)))
        raise TypeError(f"Unsupported runtime result evidence: {type(item)}")
    encoded = json.dumps(freeze(value), separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


@lru_cache(maxsize=1)
def _windows_api():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "working", "paged_peak", "paged",
                "nonpaged_peak", "nonpaged", "pagefile", "pagefile_peak")]
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(Entry)]
    query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    return kernel, Counters, Entry, query


def process_resources(pid):
    """OS process CPU and memory, including import and serialization costs."""
    if sys.platform != "win32":
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        status = Path(f"/proc/{pid}/status").read_text().splitlines()
        peak = next(int(row.split()[1]) * 1024 for row in status if row.startswith("VmHWM:"))
        rss = next(int(row.split()[1]) * 1024 for row in status if row.startswith("VmRSS:"))
        return {"cpu_s": cpu, "peak_bytes": peak, "rss_bytes": rss}
    import ctypes
    from ctypes import wintypes
    kernel, Counters, _entry, query = _windows_api()
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        cpu = sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in times[2:]) / 1e7
        value = Counters()
        value.cb = ctypes.sizeof(value)
        if not query(handle, ctypes.byref(value), value.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"cpu_s": cpu, "peak_bytes": int(value.peak), "rss_bytes": int(value.working)}
    finally:
        kernel.CloseHandle(handle)


def descendant_pids(root):
    if sys.platform != "win32":
        found, pending = {root}, [root]
        while pending:
            pid = pending.pop()
            try:
                children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            except OSError:
                continue
            for child in map(int, children):
                if child not in found:
                    found.add(child)
                    pending.append(child)
        return found
    import ctypes
    kernel, _counters, Entry, _query = _windows_api()
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        valid = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while valid:
            parents[int(entry.pid)] = int(entry.parent)
            valid = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    found = {root}
    while True:
        children = {pid for pid, parent in parents.items() if parent in found}
        if children.issubset(found):
            return found
        found.update(children)


class ResourceSampler:
    """Sample simultaneous process-tree RSS; include sampler CPU in caller CPU."""
    def __init__(self, interval=.1):
        self.interval = interval
        self.rows = []
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.tree_lock = threading.Lock()
        self.pids = {os.getpid()}
        self.tree_scanned = 0.
        self.failure = None
        self.started = time.perf_counter()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def snapshot(self, *, force_tree=False):
        with self.tree_lock:
            if force_tree or time.perf_counter() - self.tree_scanned >= .5:
                self.pids = descendant_pids(os.getpid())
                self.tree_scanned = time.perf_counter()
            pids = set(self.pids)
        values = {}
        for pid in pids:
            try:
                values[pid] = process_resources(pid)
            except OSError:
                # Process may exit between enumeration and observation.
                continue
        return values

    def _run(self):
        while not self.stop.is_set():
            try:
                values = self.snapshot()
                row = {"seconds": time.perf_counter() - self.started,
                       "rss_bytes": sum(v["rss_bytes"] for v in values.values()),
                       "process_count": len(values)}
                with self.lock:
                    self.rows.append(row)
            except BaseException as error:
                self.failure = type(error).__name__
                return
            self.stop.wait(self.interval)

    def phase(self, index):
        assert self.failure is None, self.failure
        with self.lock:
            values = self.rows[index:]
        return {"sample_interval_s": self.interval, "pid_discovery_interval_s": .5, "samples": values,
                "sampled_peak_simultaneous_rss_bytes": max((r["rss_bytes"] for r in values), default=0),
                "sampled_peak_processes": max((r["process_count"] for r in values), default=0)}

    def close(self):
        self.stop.set()
        self.thread.join(5)
        assert not self.thread.is_alive()
        assert self.failure is None, self.failure


def runtime_call(project_type, pi):
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    pfa._POLICY_RUN_CACHE.clear()
    try:
        from financial_engine.financing import speculative as sp
        before = sp._POOL.metrics["submitted"] if sp._POOL is not None else 0
    except ImportError:
        sp, before = None, 0
    result = run_project(project_type, "Base", "Semiannual", pi)
    if sp is None:
        stats, helpers, actual, broken = None, [], 0, False
    else:
        stats = sp._POOL.metrics if sp._POOL is not None else None
        helpers = list(sp._POOL.executor._processes or {}) if sp._POOL is not None else []
        actual, broken = sp.configured_workers(), sp._POOL.broken if sp._POOL is not None else False
    return {"result": result, "worker_pid": os.getpid(), "helper_pids": helpers,
            "helper_metrics": stats, "configured_helpers": actual, "broken_pool": broken,
            "financial_helper_submissions_this_run": (stats["submitted"] if stats else 0) - before,
            "prewarm_evidence": getattr(sp, "_PREWARM_EVIDENCE", None) if sp else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=["S50", "S16", "W25", "DC", "reference-ev_charging"])
    parser.add_argument("--workers", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--users", type=int, choices=(1, 2), default=1)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--second-case")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    os.environ.update(FINCO_G2A_WORKERS=str(args.workers), FINCO_WEB_WORKERS="1",
                      FINCO_MODEL_EXECUTION_CONCURRENCY=str(args.users))
    import importlib.util
    spec = importlib.util.spec_from_file_location("v9_inventory", args.inventory)
    inv = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = inv
    spec.loader.exec_module(inv)
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig
    executor = ModelExecutor(ModelExecutionConfig(args.users, "process", 180))
    report = {"requested_helpers": args.workers, "users": args.users,
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=args.repo)),
              "platform": sys.platform, "python": sys.version,
              "boundary": "existing ModelExecutor, actual run_project, complete result transfer; not HTTP/DB commit",
              "memory": "per-process peaks; sum is an upper bound, not simultaneous peak RSS",
              "rows": []}
    report["protected_git_blobs"] = {
        path: subprocess.check_output(["git", "hash-object", "--path=" + path, path],
            cwd=args.repo, text=True).strip() if (args.repo / path).is_file() else None
        for path in ("financial_engine/financing/project.py", "financial_engine/financing/speculative.py")}
    report["application_git_blobs"] = {"app/runtime/model_execution.py": subprocess.check_output(
        ["git", "hash-object", "--path=app/runtime/model_execution.py", "app/runtime/model_execution.py"],
        cwd=args.repo, text=True).strip()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    sampler = ResourceSampler()
    sampler.thread.start()
    try:
        startup_before = sampler.snapshot()
        startup_index = len(sampler.rows)
        started = time.perf_counter()
        report["standard_outer_prewarm"] = executor.warm_up()
        report["standard_outer_prewarm_s"] = time.perf_counter() - started
        startup_after = sampler.snapshot(force_tree=True)
        report["startup_resources"] = sampler.phase(startup_index)
        report["startup_resources"]["aggregate_cpu_s"] = sum(v["cpu_s"] - startup_before.get(pid, {}).get(
            "cpu_s", 0.) for pid, v in startup_after.items())
        known_pids = {os.getpid(), *executor._process_pool._processes}
        for name in args.cases:
            factory, vertical, policy = inv.cases()[name]
            assert policy is None
            pi = factory()
            jobs = [(name, vertical, pi) for _ in range(args.users)]
            if args.second_case:
                assert args.users == 2
                other, other_vertical, other_policy = inv.cases()[args.second_case]
                assert other_policy is None
                jobs[1] = (args.second_case, other_vertical, other())
            for repeat in range(args.repetitions):
                before_cpu = {pid: value["cpu_s"] for pid, value in sampler.snapshot(force_tree=True).items()}
                sample_index = len(sampler.rows)
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as callers:
                    futures = [callers.submit(executor.run_process_sync, runtime_call, job[1], job[2])
                               for job in jobs]
                    returned = [future.result() for future in futures]
                elapsed = time.perf_counter() - started
                for value in returned:
                    known_pids.add(value["worker_pid"])
                    known_pids.update(value["helper_pids"])
                with sampler.tree_lock:
                    sampler.pids.update(known_pids)
                resources = sampler.snapshot(force_tree=True)
                cpu = sum(value["cpu_s"] - before_cpu.get(pid, 0.) for pid, value in resources.items())
                digests, byte_counts, financial_digests = [], [], []
                for value in returned:
                    output = value.pop("result")
                    blob = pickle.dumps(output, protocol=5)
                    financial_digests.append(financial_return_digest(output))
                    digests.append(hashlib.sha256(blob).hexdigest())
                    byte_counts.append(len(blob))
                row = {"case": name, "user_cases": [job[0] for job in jobs], "repeat": repeat,
                       "input_digests": [inv.digest(inv.flatten(job[2])) for job in jobs],
                       "roundtrip_batch_wall_s": elapsed,
                       "aggregate_cpu_s": cpu, "processes": resources, "process_count": len(resources),
                       "complete_return_pickle_sha256": digests, "returned_bytes": byte_counts,
                       "complete_financial_return_sha256": financial_digests,
                       "worker_evidence": returned, "simultaneous_resources": sampler.phase(sample_index)}
                if len({job[0] for job in jobs}) == 1:
                    assert len(set(financial_digests)) == 1, (name, "CONCURRENT_RESULT_DIFFERENCE")
                report["rows"].append(row)
                save()
                print(name, repeat, round(elapsed, 4), "CPU", round(cpu, 4), digests[0], flush=True)
        report["executor_stats"] = executor.stats()
    finally:
        # The normal Run worker owns its helper finalizers; no test-only helper
        # shutdown call is injected into the production task.
        try:
            shutdown_started = time.perf_counter()
            report["forced_shutdown_stragglers"] = executor.shutdown_and_join(timeout=30)
            report["shutdown_wall_s"] = time.perf_counter() - shutdown_started
            save()
            assert report["forced_shutdown_stragglers"] == []
        finally:
            sampler.close()


if __name__ == "__main__":
    main()
