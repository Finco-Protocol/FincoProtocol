"""V10-08 / V10-09 / provenance seal: the loader never raises and declines every artifact, manifest, seal,
runtime or source deviation before any native call; an unvalidated runtime keeps a functioning canonical
Run (Python 3.10/3.11, other platforms, free-threaded builds)."""
from __future__ import annotations

import json
import shutil
import sys

import pytest

from financial_engine.native_v10 import eligibility, loader, provenance, stage2
from tests.native_v10_support import ARTIFACTS, HERE, OFF, STAGE1, STAGE2, outcome_key, run_case

APPROVED = {("Linux", "x86_64", "cpython", (3, 12)), ("Linux", "x86_64", "cpython", (3, 13))}


def _copy_release(dst, *, with_binaries=True):
    for name in ("fk_v10_manifest.json", "fk_v10_stage2_manifest.json", "approved_canonical_blobs.json",
                 "approved_canonical_blobs_stage2.json"):
        shutil.copy(HERE / name, dst / name)
    if with_binaries:
        for so in ARTIFACTS.values():
            shutil.copy(HERE / so, dst / so)
    return dst


def test_validated_targets_are_exactly_linux_x86_64_cpython_312_and_313():
    assert set(eligibility.VALIDATED_TARGETS) == APPROVED


@pytest.mark.parametrize("key,reason", [
    (("Linux", "x86_64", "cpython", (3, 10)), "RUNTIME_NOT_VALIDATED"),
    (("Linux", "x86_64", "cpython", (3, 11)), "RUNTIME_NOT_VALIDATED"),
    (("Linux", "aarch64", "cpython", (3, 13)), "RUNTIME_NOT_VALIDATED"),
    (("Windows", "AMD64", "cpython", (3, 12)), "RUNTIME_NOT_VALIDATED"),
    (("Darwin", "arm64", "cpython", (3, 13)), "RUNTIME_NOT_VALIDATED"),
    (("Linux", "x86_64", "pypy", (3, 12)), "RUNTIME_NOT_VALIDATED"),
])
def test_unvalidated_runtimes_decline(monkeypatch, key, reason):
    monkeypatch.setattr(eligibility, "runtime_key", lambda: key)
    assert eligibility.check_runtime().startswith(reason)


def test_free_threaded_build_declines(monkeypatch):
    if eligibility.runtime_key() not in APPROVED:
        pytest.skip("validated runtime required to reach the free-threading check")
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False, raising=False)
    assert eligibility.check_runtime() == "RUNTIME_FREE_THREADED_NOT_VALIDATED"


def test_missing_artifacts_decline_without_raising(tmp_path):
    _copy_release(tmp_path, with_binaries=False)
    lib, reason = loader._verify(tmp_path, "fk_v10_manifest.json")
    assert lib is None
    assert reason.startswith(("LOADER_ARTIFACT_UNAVAILABLE", "RUNTIME_"))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert loader.get_native(empty)[0] is None                     # cached, never raises


def _release_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return _copy_release(d)


def test_tampered_artifacts_manifests_and_seal_decline(tmp_path, native_artifacts):
    def verify(directory):
        loader._reset_for_tests()
        return loader._verify(directory, "fk_v10_manifest.json")

    assert verify(_release_dir(tmp_path, "ok"))[1] is None          # the untouched copy is accepted

    corrupt = _release_dir(tmp_path, "corrupt")
    data = bytearray((corrupt / "_fk_v10.so").read_bytes())
    data[2000] ^= 0xFF
    (corrupt / "_fk_v10.so").write_bytes(bytes(data))
    assert verify(corrupt) == (None, "LOADER_ARTIFACT_SHA256_MISMATCH")

    unsealed = _release_dir(tmp_path, "unsealed")
    approved = json.loads((unsealed / "approved_canonical_blobs.json").read_text())
    approved["blobs"]["financial_engine/tax/engine.py"] = "0" * 40
    (unsealed / "approved_canonical_blobs.json").write_text(json.dumps(approved))
    assert verify(unsealed) == (None, "LOADER_APPROVED_MANIFEST_NOT_SEALED")

    for field, value, reason in (("abi_version", 1, "LOADER_ABI_VERSION_MANIFEST"),
                                 ("build_id", "0" * 64, "LOADER_BUILD_ID")):
        d = _release_dir(tmp_path, field)
        manifest = json.loads((d / "fk_v10_manifest.json").read_text())
        manifest[field] = value
        (d / "fk_v10_manifest.json").write_text(json.dumps(manifest))
        assert verify(d) == (None, reason)


def test_admission_layer_and_stage2_blob_tamper_fail_authentication(tmp_path):
    # source authentication runs only after the runtime gate admitted the interpreter (loader order)
    reason = eligibility.check_runtime()
    if reason:
        pytest.skip(f"source authentication is reached only on validated runtimes: {reason}")
    m = json.loads(provenance.APPROVED_MANIFEST.read_text())
    m["blobs"]["financial_engine/native_v10/dispatch.py"] = "0" * 40
    (tmp_path / "m.json").write_text(json.dumps(m))
    auth, reason = provenance.authenticate(tmp_path / "m.json")
    assert auth is None and reason.startswith("PROVENANCE_BLOB_MISMATCH:financial_engine/native_v10/dispatch.py")

    m2 = json.loads(provenance.STAGE2_APPROVED_MANIFEST.read_text())
    m2["blobs"]["financial_engine/native_v10/stage2.py"] = "0" * 40
    (tmp_path / "m2.json").write_text(json.dumps(m2))
    auth2, reason2 = provenance.authenticate(tmp_path / "m2.json", functions=provenance.STAGE2_REGION_FUNCTIONS,
                                             attributes=provenance.STAGE2_REGION_ATTRIBUTES,
                                             aliases=provenance.STAGE2_ALIASES,
                                             extra_sources=provenance.STAGE2_EXTRA_SOURCES)
    assert auth2 is None and reason2.startswith("PROVENANCE_BLOB_MISMATCH:financial_engine/native_v10/stage2.py")


def test_committed_approved_manifests_match_the_working_tree():
    """The sealed approved-source manifests are exactly the current canonical sources (no stale seal)."""
    assert json.loads(provenance.APPROVED_MANIFEST.read_text()) == provenance.build_manifest()
    assert json.loads(provenance.STAGE2_APPROVED_MANIFEST.read_text()) == provenance.build_manifest(
        provenance.STAGE2_REGION_FUNCTIONS, provenance.STAGE2_EXTRA_SOURCES)


@pytest.mark.parametrize("key", [("Linux", "x86_64", "cpython", (3, 10)), ("Windows", "AMD64", "cpython", (3, 12))])
def test_unvalidated_runtime_candidate_run_is_canonical(monkeypatch, key):
    """A candidate Run on an unvalidated runtime declines at the loader and returns the canonical result."""
    off = run_case("reference-solar", "canonical", OFF)
    monkeypatch.setattr(eligibility, "runtime_key", lambda: key)
    loader._reset_for_tests()
    stage2._reset_for_tests()
    try:
        for cfg in (STAGE1, STAGE2):
            cand = run_case("reference-solar", "canonical", cfg)
            assert outcome_key(cand) == outcome_key(off)
            assert cand["native"]["native_solves"] == 0 and cand["native"]["stage2_native_calls"] == 0
            assert cand["native"]["loader_reason"].startswith("RUNTIME_NOT_VALIDATED")
    finally:
        loader._reset_for_tests()
        stage2._reset_for_tests()
