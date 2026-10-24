"""Shared support for the V11 Stage 3 native-candidate tests (not a test module).

Same rule as ``native_v10_support``: the Stage 3 binary is never committed and never compiled at runtime.
Tests that EXECUTE it use the session fixture ``stage3_artifacts``: it builds ``kernel_v11_stage3.c``
offline into a temporary directory with the repository's own ``build_stage3.py``, requires the result to
be the APPROVED build (every manifest field except the informational ``built_with_python`` equals the
committed ``fk_v11_stage3_manifest.json``, so the binary sha256 is byte-identical), and only then installs
``_fk_v11_stage3.so`` next to the package for the session (removed afterwards; ``*.so`` is git-ignored).
The fixture also installs the V10 artifacts (``native_artifacts``) because the Stage 3 identity is
proven against the canonical engine, against V10 Stage 1+2 and against Stage 3 on top of Stage 1+2.

* Unvalidated runtime / no compiler: native-executing tests SKIP with the reason.
* Same compiler identification but a different binary: FAIL (the build is not reproducible).
* Different compiler identification: SKIP (that toolchain is not the approved build).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

# config modules are pure Python (no ctypes, no loader)
from financial_engine.native_v10.config import NativeConfig, native_run
from financial_engine.native_v11.config import Stage3Config, stage3_run

HERE = Path(__file__).resolve().parents[1] / "financial_engine" / "native_v11"
MANIFEST = "fk_v11_stage3_manifest.json"
ARTIFACT = "_fk_v11_stage3.so"
INFORMATIONAL_FIELDS = frozenset({"built_with_python"})

OFF10 = NativeConfig()
S12 = NativeConfig(mode="candidate", stage2_experimental=True)
OFF3 = Stage3Config()
S3 = Stage3Config(mode="candidate")
# arm -> (V10 configuration, Stage 3 configuration)
ARMS = {"off": (OFF10, OFF3), "v10_s12": (S12, OFF3), "s3": (OFF10, S3), "s12_s3": (S12, S3)}


def committed_manifest() -> dict:
    return json.loads((HERE / MANIFEST).read_text(encoding="utf-8"))


def approved_fields(manifest: dict) -> dict:
    fields = {k: v for k, v in manifest.items() if k not in INFORMATIONAL_FIELDS}
    if "command" in fields:
        fields["command"] = [c.replace("<out>", "<native_v11>") for c in fields["command"]]
    return fields


def reset_stage3_caches() -> None:
    from financial_engine.native_v11 import stage3
    stage3._reset_for_tests()


@pytest.fixture(scope="session")
def stage3_artifacts(tmp_path_factory, native_artifacts):
    from financial_engine.native_v10 import eligibility
    from financial_engine.native_v11 import build_stage3, stage3
    from tests.native_v10_support import compiler_or_skip
    reason = eligibility.check_runtime()
    if reason:
        pytest.skip(f"native runtime not validated here: {reason}")
    compiler = compiler_or_skip()
    out = tmp_path_factory.mktemp("native_v11_build")
    manifest = build_stage3.build(out)
    expected = committed_manifest()
    if manifest["compiler"] != expected["compiler"]:
        pytest.skip(f"toolchain {compiler!r} is not the approved build toolchain {expected['compiler']!r}")
    if approved_fields(manifest) != approved_fields(expected):
        pytest.fail("non-reproducible Stage 3 build: "
                    f"{sorted(k for k in approved_fields(expected) if manifest.get(k) != expected.get(k))}")
    target = HERE / ARTIFACT
    data = (out / ARTIFACT).read_bytes()
    installed = False
    if target.exists():
        assert target.read_bytes() == data, f"a different {ARTIFACT} is already present next to the package"
    else:
        target.write_bytes(data)
        installed = True
    reset_stage3_caches()
    lib, why = stage3.get_stage3()
    assert lib is not None, why
    try:
        yield {"build_dir": out, "manifest": manifest}
    finally:
        if installed:
            target.unlink(missing_ok=True)
        reset_stage3_caches()


def run_case(name: str, authority: str, arm: str, catalogue: dict | None = None) -> dict:
    """One production Run (run_clean_production) of an acceptance case under ``arm``."""
    from app.services import production_financial_authority as pfa
    from tests.native_v10_support import acceptance, entries, evidence_of
    acc = acceptance()
    factory, vertical, base = (catalogue or entries())[name]
    c10, c3 = ARMS[arm]
    pfa._POLICY_RUN_CACHE.clear()
    t0 = time.perf_counter()
    with native_run(c10) as st10, stage3_run(c3) as st3:
        try:
            result = pfa.run_clean_production(factory(), project_type=vertical,
                                              financing_policy=acc.policy_for(authority, base))
            out = {"verdict": "FEASIBLE", "error": None, "digests": evidence_of(result)}
        except Exception as exc:  # noqa: BLE001 - the verdict IS the exception
            out = {"verdict": "REJECTED", "error": f"{type(exc).__name__}: {exc}", "digests": None}
    pfa._POLICY_RUN_CACHE.clear()
    out["seconds"] = time.perf_counter() - t0
    out["v10"] = st10.as_dict()
    out["s3"] = st3.as_dict()
    return out


def outcome_key(run: dict) -> tuple:
    return run["verdict"], run["error"], json.dumps(run["digests"], sort_keys=True)
