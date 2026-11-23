"""Small actual pytest subprocess controls; no FINCO regression suite execution."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from tools.ci_v3_observed_verify import verify_observed
from tools.ci_v3_real_contract import actual_execution_records, producer_identity
from tools.ci_v3_schema import ContractError, read_json
from tools.ci_v3_shadow_local import run_shadow
from tools.ci_v3_synthetic_project import EXPECTED_NODES, create_project


@pytest.fixture(scope="module")
def actual_bundle(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ci-v3-real-positive")
    inventory, policy, weights = create_project(directory / "project")
    result = run_shadow(directory / "project", inventory, policy, weights, directory / "execution")
    assert result["proof"]["coverage_valid"], result["proof"]
    root = Path(result["output"])
    return {"root": root, "anchor": result["observations_sha256"], "trust": read_json(root / "trust.json"),
            "producer": producer_identity(), "result": result}


def test_real_pytest_collection_phases_identity_and_normal_exit(actual_bundle):
    data = actual_bundle; root = data["root"]
    proof = verify_observed(root, data["anchor"], data["trust"], data["producer"])
    assert proof["observation_mode"] == "real-local-OS-observed"
    assert proof["authoritative_acceptance"] is False
    assert proof["phase1_proof"]["executions"] == 6
    assert proof["phase1_proof"]["unique_nodes"] == 6
    assert proof["phase1_proof"]["collection_skips_per_worker"] == 1
    all_nodes = []
    for directory in sorted((root / "workers").iterdir()):
        report = read_json(directory / "adapter.json")
        assert report["collection"]["nodes"] == EXPECTED_NODES
        assert len(report["collection"]["skips"]) == 1
        assert not report["unauthorized_deselection"]
        assert set(report["selected"]) | set(report["deselected"]) == set(EXPECTED_NODES)
        assert set(report["selected"]).isdisjoint(report["deselected"])
        all_nodes += report["selected"]
        assert len(report["phases"]) == 3 * len(report["selected"])
        returned = read_json(directory / "pytest-return.json")
        assert returned["code"] == 0 and not any(returned["leaks"].values())
        assert returned["pytest_import_ms"] >= 0
        assert read_json(directory / "interpreter-exit.json")["finalizing"]
        assert (directory / "native.xml").is_file()
    assert sorted(all_nodes) == EXPECTED_NODES
    assert any("literal::id" in n for n in all_nodes)


def test_actual_session_fixtures_database_temp_isolation_and_cleanup(actual_bundle):
    paths = []
    for directory in sorted((actual_bundle["root"] / "workers").iterdir()):
        record = read_json(directory / "tmp/fixture-proof.json")
        assert record["closed"] and record["owner"] == directory.name
        database = Path(record["database"])
        # Windows extended-length prefixes can differ for the same real directory.
        assert database.parent.samefile(directory / "tmp")
        db = sqlite3.connect(database, timeout=1)
        try:
            assert db.execute("select owner from owners").fetchall() == [(directory.name,)]
        finally:
            db.close()
        paths.append(database.resolve())
    assert len(set(paths)) == 3


@pytest.mark.parametrize("variant", [
    "failure", "abrupt", "forged_success", "silent_zero", "timeout", "shutdown_hang",
    "collection_only", "deselection", "wrong_xfail", "xpass", "wrong_collection_skip",
    "teardown_failure", "duplicate_execution", "contamination", "new_node", "collection_error",
    "wrong_skip", "missing_exit", "grandchild_timeout",
])
def test_real_adversarial_subprocesses_cannot_make_aggregate_pass(tmp_path, variant):
    inventory, policy, weights = create_project(tmp_path / "project", variant)
    timeout = 4 if variant in ("timeout", "shutdown_hang", "grandchild_timeout") else 20
    result = run_shadow(tmp_path / "project", inventory, policy, weights, tmp_path / "execution", timeout)
    assert result["proof"]["coverage_valid"] is False, variant
    assert result["proof"]["authoritative_acceptance"] is False
    receipt = read_json(tmp_path / "execution/observations.json")
    if variant in ("new_node", "collection_error", "deselection", "wrong_collection_skip"):
        assert not receipt["workers"]
        assert receipt["controller_error"]
    if variant in ("timeout", "shutdown_hang", "grandchild_timeout"):
        assert any(o["timed_out"] for o in receipt["workers"].values())
    if variant == "forged_success":
        assert any(o["os_exit_code"] == 1 for o in receipt["workers"].values())
    if variant == "silent_zero":
        assert any(o["os_exit_code"] == 0 and o["pytest_return"] is None for o in receipt["workers"].values())
    if variant == "missing_exit":
        assert any(o["os_exit_code"] == 0 and o["interpreter_exit"] is None for o in receipt["workers"].values())
    if variant == "grandchild_timeout":
        pid_file = tmp_path / "execution/workers/worker-2/tmp/grandchild.pid"
        assert pid_file.is_file(), "grandchild really started before the timeout"
        pid = int(pid_file.read_text())
        import os
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                code = wintypes.DWORD()
                try:
                    assert kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259
                finally:
                    kernel.CloseHandle(handle)
        else:
            proc = Path("/proc") / str(pid) / "stat"
            assert not proc.exists() or proc.read_text().split()[2] == "Z"


def test_phase_counter_rejects_duplicate_or_missing_actual_execution(actual_bundle):
    report = read_json(actual_bundle["root"] / "workers/worker-0/adapter.json")
    duplicated = deepcopy(report); duplicated["phases"].append(deepcopy(duplicated["phases"][0]))
    with pytest.raises(ContractError, match="duplicate"):
        actual_execution_records(duplicated)
    missing = deepcopy(report); missing["phases"] = []
    with pytest.raises(ContractError, match="missing actual"):
        actual_execution_records(missing)


def test_full_product_and_unmarked_project_are_refused(tmp_path):
    from tools.ci_v3_shadow_local import validate_synthetic_project
    with pytest.raises(ContractError, match="FINCO"):
        validate_synthetic_project(Path(__file__).resolve().parents[1], tmp_path / "out")
    project = tmp_path / "unmarked"; project.mkdir()
    with pytest.raises(ContractError, match="synthetic-project"):
        validate_synthetic_project(project, tmp_path / "out")
