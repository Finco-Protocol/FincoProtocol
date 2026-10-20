"""Actual ModelExecutor dispatch and result transfer, with private output evidence."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
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


def process_resources(pid):
    """OS process CPU and memory, including import and serialization costs."""
    if sys.platform != "win32":
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        status = Path(f"/proc/{pid}/status").read_text().splitlines()
        peak = next(int(row.split()[1]) * 1024 for row in status if row.startswith("VmHWM:"))
        return {"cpu_s": cpu, "peak_bytes": peak}
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        cpu = sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in times[2:]) / 1e7
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("peak", "working", "paged_peak", "paged",
                    "nonpaged_peak", "nonpaged", "pagefile", "pagefile_peak")]
        value = Counters()
        value.cb = ctypes.sizeof(value)
        query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not query(handle, ctypes.byref(value), value.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"cpu_s": cpu, "peak_bytes": int(value.peak)}
    finally:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)


def runtime_call(project_type, pi):
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    pfa._POLICY_RUN_CACHE.clear()
    result = run_project(project_type, "Base", "Semiannual", pi)
    try:
        from financial_engine.financing import speculative as sp
    except ImportError:
        stats, helpers, actual, broken = None, [], 0, False
    else:
        stats = sp._POOL.metrics if sp._POOL is not None else None
        helpers = list(sp._POOL.executor._processes or {}) if sp._POOL is not None else []
        actual, broken = sp.configured_workers(), sp._POOL.broken if sp._POOL is not None else False
    return {"result": result, "worker_pid": os.getpid(), "helper_pids": helpers,
            "helper_metrics": stats, "configured_helpers": actual, "broken_pool": broken}


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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        started = time.perf_counter()
        report["standard_outer_prewarm"] = executor.warm_up()
        report["standard_outer_prewarm_s"] = time.perf_counter() - started
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
                before_cpu = {pid: process_resources(pid)["cpu_s"] for pid in known_pids}
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as callers:
                    futures = [callers.submit(executor.run_process_sync, runtime_call, job[1], job[2])
                               for job in jobs]
                    returned = [future.result() for future in futures]
                elapsed = time.perf_counter() - started
                for value in returned:
                    known_pids.add(value["worker_pid"])
                    known_pids.update(value["helper_pids"])
                resources = {pid: process_resources(pid) for pid in known_pids}
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
                       "worker_evidence": returned}
                if len({job[0] for job in jobs}) == 1:
                    assert len(set(financial_digests)) == 1, (name, "CONCURRENT_RESULT_DIFFERENCE")
                report["rows"].append(row)
                save()
                print(name, repeat, round(elapsed, 4), "CPU", round(cpu, 4), digests[0], flush=True)
        report["executor_stats"] = executor.stats()
    finally:
        # The normal Run worker owns its helper finalizers; no test-only helper
        # shutdown call is injected into the production task.
        report["forced_shutdown_stragglers"] = executor.shutdown_and_join(timeout=30)
        save()
        assert report["forced_shutdown_stragglers"] == []


if __name__ == "__main__":
    main()
