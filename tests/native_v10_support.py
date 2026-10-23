"""Shared support for the V10 native-candidate tests (not a test module).

Native binaries are never committed and never compiled at runtime. Tests that must EXECUTE native code
use the session fixture ``native_artifacts``: it builds both kernels offline into a temporary directory
with the repository's own build scripts, requires the result to be the APPROVED build (every manifest
field except the informational ``built_with_python`` equals the committed manifest, so the binary
sha256 is byte-identical), and only then installs the two shared objects next to the package for the
duration of the session (removed afterwards; ``*.so`` is git-ignored).

* Unvalidated runtime / no compiler: native-executing tests SKIP with the reason (canonical fallback
  is covered by tests that need no binary).
* Same compiler identification but a different binary: FAIL (the build is not reproducible).
* Different compiler identification: SKIP (that toolchain is not the approved build; widening the
  approved toolchain needs new evidence, never a test default).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# config.py is pure Python (no ctypes, no loader); the native modules are imported lazily below so that
# importing this support module from conftest never imports native code into an unrelated test session.
from financial_engine.native_v10.config import NativeConfig, native_run

HERE = Path(__file__).resolve().parents[1] / "financial_engine" / "native_v10"
ARTIFACTS = {"fk_v10_manifest.json": "_fk_v10.so", "fk_v10_stage2_manifest.json": "_fk_v10_stage2.so"}
INFORMATIONAL_FIELDS = frozenset({"built_with_python"})

OFF = NativeConfig()
STAGE1 = NativeConfig(mode="candidate")
STAGE2 = NativeConfig(mode="candidate", stage2_experimental=True)
ARMS = {"off": OFF, "stage1": STAGE1, "stage2": STAGE2}


def committed_manifest(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def approved_fields(manifest: dict) -> dict:
    """Manifest identity: everything except informational fields; the recorded build command is compared
    with its output-directory token normalised (an out-of-tree build writes ``<out>``, the release
    build writes next to the sources, ``<native_v10>``); every flag and the build ID stay compared."""
    fields = {k: v for k, v in manifest.items() if k not in INFORMATIONAL_FIELDS}
    if "command" in fields:
        fields["command"] = [c.replace("<out>", "<native_v10>") for c in fields["command"]]
    return fields


def compiler_or_skip(cc: str = "gcc") -> str:
    from financial_engine.native_v10 import build
    if shutil.which(cc) is None:
        pytest.skip(f"native build: compiler {cc!r} not available")
    return build.compiler_id(cc)


def build_both(out_dir: Path) -> dict:
    """Offline build of both kernels into ``out_dir``; returns {manifest name: manifest}."""
    from financial_engine.native_v10 import build, build_stage2
    return {"fk_v10_manifest.json": build.build(out_dir), "fk_v10_stage2_manifest.json": build_stage2.build(out_dir)}


def reset_native_caches() -> None:
    from financial_engine.native_v10 import loader, stage2
    loader._reset_for_tests()
    stage2._reset_for_tests()


@pytest.fixture(scope="session")
def native_artifacts(tmp_path_factory):
    from financial_engine.native_v10 import eligibility, loader, stage2
    reason = eligibility.check_runtime()
    if reason:
        pytest.skip(f"native runtime not validated here: {reason}")
    compiler = compiler_or_skip()
    out = tmp_path_factory.mktemp("native_v10_build")
    built = build_both(out)
    for name, manifest in built.items():
        expected = committed_manifest(name)
        if manifest["compiler"] != expected["compiler"]:
            pytest.skip(f"toolchain {compiler!r} is not the approved build toolchain {expected['compiler']!r}")
        if approved_fields(manifest) != approved_fields(expected):
            pytest.fail(f"non-reproducible native build for {name}: "
                        f"{sorted(k for k in approved_fields(expected) if manifest.get(k) != expected.get(k))}")
    installed = []
    for name, so in ARTIFACTS.items():
        target = HERE / so
        data = (out / so).read_bytes()
        if target.exists():
            assert target.read_bytes() == data, f"a different {so} is already present next to the package"
        else:
            target.write_bytes(data)
            installed.append(target)
    reset_native_caches()
    lib, why = loader.get_native()
    lib2, why2 = stage2.get_stage2()
    assert lib is not None, why
    assert lib2 is not None, why2
    try:
        yield {"build_dir": out, "manifests": built}
    finally:
        for target in installed:
            target.unlink(missing_ok=True)
        reset_native_caches()


# ------------------------------------------------------------------ engine cases and evidence
def acceptance():
    from tools import v9p2a_odr_acceptance as acc
    return acc


def entries() -> dict:
    acc = acceptance()
    e = acc.cases()
    e.update(acc.supplementary_cases())
    return e


def evidence_of(result) -> dict:
    """Exact digests of every financial leaf, the whole result, Integrity and the final checks."""
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    acc = acceptance()
    integrity = run_integrity_checks(build_run_integrity_evidence(result)).to_dict()
    return {"financial_digest": acc.digest(acc.financial_leaves(result)), "full_digest": acc.digest(acc.flatten(result)),
            "integrity": integrity["overall"], "integrity_digest": acc.digest(acc.flatten(integrity)),
            "final_checks": acc.digest(acc.final_checks(result))}


def run_case(name: str, authority: str, config: NativeConfig, catalogue: dict | None = None) -> dict:
    """One production Run (run_clean_production) of an acceptance case under ``config``."""
    from app.services import production_financial_authority as pfa
    acc = acceptance()
    factory, vertical, base = (catalogue or entries())[name]
    pfa._POLICY_RUN_CACHE.clear()
    with native_run(config) as stats:
        try:
            result = pfa.run_clean_production(factory(), project_type=vertical,
                                              financing_policy=acc.policy_for(authority, base))
            out = {"verdict": "FEASIBLE", "error": None, "digests": evidence_of(result)}
        except Exception as exc:  # noqa: BLE001 - the verdict IS the exception
            out = {"verdict": "REJECTED", "error": f"{type(exc).__name__}: {exc}", "digests": None}
    pfa._POLICY_RUN_CACHE.clear()
    out["native"] = stats.as_dict()
    return out


def outcome_key(run: dict) -> tuple:
    return run["verdict"], run["error"], json.dumps(run["digests"], sort_keys=True)


def sleep_for(seconds: float) -> float:
    """A picklable long-running call (lifecycle tests run it inside a real candidate worker)."""
    import time
    time.sleep(seconds)
    return seconds


def crash_task() -> None:
    """Dereference NULL in the worker (a native fault Python cannot catch)."""
    import ctypes
    ctypes.string_at(0)


def allocate_task(gib: int) -> int:
    """Allocate beyond the worker's RLIMIT_AS."""
    return len(bytearray(gib * 1024 ** 3))


def touch_task(path: str) -> dict:
    """Leave a marker proving the task body executed."""
    Path(path).write_text("ran")
    return {"verdict": "OK", "digests": {}}


def _failing_limits_class():
    from dataclasses import dataclass

    from financial_engine.native_v10.isolation import WorkerLimits

    @dataclass(frozen=True)
    class FailingLimits(WorkerLimits):
        """setrlimit refused in the candidate worker (e.g. a hardened container)."""
        def apply(self) -> None:
            raise OSError("setrlimit refused (test)")

    return FailingLimits


def __getattr__(name):            # lazily defined so importing this module never imports native code
    if name == "FailingLimits":
        cls = _failing_limits_class()
        cls.__module__, cls.__qualname__ = __name__, "FailingLimits"
        globals()["FailingLimits"] = cls
        return cls
    raise AttributeError(name)


def git_tracked(path_glob: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", path_glob], capture_output=True, text=True,
                         cwd=str(HERE.parents[1]), check=True).stdout
    return [line for line in out.splitlines() if line.strip()]
