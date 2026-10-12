"""Process-lifecycle acceptance for the Public Safety supervisor (synthetic suites only).

What these pin: a complete pytest run is accepted ONLY when pytest.main returned rc=0 AND the interpreter exited
normally; a run whose tests all passed but whose suite-lifecycle guard set rc=1 is rejected; an interpreter that does
not shut down is rejected (124); nothing here forces an exit code, kills leaked resources or relaxes the verifier.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys

import pytest

from tools.ci_acceptance import run_command

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "ci_pytest_runner.py"
HEAD, TREE = "a" * 40, "b" * 40


def _supervised(tmp_path, tests: str, conftest: str = "", grace: int = 4, budget: int = 120):
    (tmp_path / "test_synthetic.py").write_text(tests, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(conftest, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), FINCO_CI_PYTEST_BUDGET_S=str(budget), FINCO_CI_EXIT_GRACE_S=str(grace),
               FINCO_CI_DIAG_PATH=str(tmp_path / "diag.txt"), FINCO_CI_PROGRESS_DIR=str(tmp_path / "progress"))
    return [sys.executable, str(RUNNER), "-q", "-p", "no:cacheprovider", "--confcutdir", str(tmp_path),
            "--junitxml", str(tmp_path / "results.xml"), "--rootdir", str(tmp_path), str(tmp_path / "test_synthetic.py")], env


def _record(tmp_path, monkeypatch, command, env, label="control"):
    monkeypatch.setattr("tools.ci_acceptance.attest", lambda value: {"head": HEAD, "tree": TREE})
    monkeypatch.setattr("tools.ci_acceptance.environment_digest", lambda: "environment")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    output = tmp_path / "process.json"
    code = run_command(argparse.Namespace(expected=HEAD, label=label, output=output,
                                          junit=str(tmp_path / "results.xml"), command=command))
    return code, json.loads(output.read_text(encoding="utf-8"))


PASSING = "def test_a(): pass\ndef test_b(): pass\n"
GUARD_RC1 = '''
import pytest

@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    # the same shape as tests/conftest.py's suite lifecycle guard: all tests passed, a leak is reported
    if session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
'''
NON_DAEMON_THREAD = '''
import threading, time

def test_leaks_a_non_daemon_thread():
    threading.Thread(target=time.sleep, args=(600,), daemon=False, name="leaked-non-daemon").start()
'''


def test_clean_run_is_accepted_with_rc0_and_a_normal_interpreter_exit(tmp_path, monkeypatch):
    command, env = _supervised(tmp_path, PASSING)
    code, record = _record(tmp_path, monkeypatch, command, env)
    assert code == 0 and record["normal_exit"] is True and record["exit_code"] == 0
    assert record["process_markers"]["pytest_return_code"] == 0 and record["process_markers"]["child_exit_code"] == 0
    assert record["junit_failures"] == 0 and record["junit_sha256"]
    assert not (tmp_path / "diag.txt").exists()


def test_pytest_rc1_with_every_test_passed_is_rejected(tmp_path, monkeypatch):
    command, env = _supervised(tmp_path, PASSING, GUARD_RC1)
    result = subprocess.run(command, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert "2 passed" in result.stdout, "the reported test outcomes are all passes"
    assert "PYTEST_MAIN_RETURNED FINCO_CI_MARKER after pytest.main rc=1" in result.stdout
    assert result.returncode == 1 and "child exit code 1" in result.stdout
    code, record = _record(tmp_path, monkeypatch, command, env)
    assert code != 0 and record["normal_exit"] is False
    assert record["process_markers"]["pytest_return_code"] == 1


def test_interpreter_shutdown_hang_is_rejected_and_never_reported_as_success(tmp_path, monkeypatch):
    command, env = _supervised(tmp_path, NON_DAEMON_THREAD, grace=4)
    result = subprocess.run(command, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert "PYTEST_MAIN_RETURNED FINCO_CI_MARKER after pytest.main rc=0" in result.stdout, "pytest itself finished"
    assert "shutdown hang" in result.stdout and result.returncode == 124
    assert "PYTHON_PROCESS_EXITED" not in result.stdout, "there was no normal interpreter exit"
    assert "did not exit within" in (tmp_path / "diag.txt").read_text(encoding="utf-8")   # diagnostics were captured
    code, record = _record(tmp_path, monkeypatch, command, env)
    assert code != 0 and record["normal_exit"] is False and record["exit_code"] == 124


@pytest.mark.parametrize("missing", ["pytest_return_code", "child_exit_code"])
def test_missing_lifecycle_markers_are_not_a_normal_exit(tmp_path, monkeypatch, missing):
    monkeypatch.setattr("tools.ci_acceptance.attest", lambda value: {"head": HEAD, "tree": TREE})
    monkeypatch.setattr("tools.ci_acceptance.environment_digest", lambda: "environment")
    lines = {"pytest_return_code": "print('PYTEST_MAIN_RETURNED FINCO_CI_MARKER after pytest.main rc=0')",
             "child_exit_code": "print('PYTHON_PROCESS_EXITED FINCO_CI_SUPERVISOR child exit code 0')"}
    lines.pop(missing)
    code_text = "# ci_pytest_runner.py\n" + "\n".join(lines.values()) + "\n"
    output = tmp_path / "process.json"
    code = run_command(argparse.Namespace(expected=HEAD, label="control", output=output, junit=None,
                                          command=[sys.executable, "-c", code_text]))
    assert code != 0 and json.loads(output.read_text())["normal_exit"] is False


def test_the_prewarm_failure_probe_is_picklable_so_no_discarded_pool_can_leak_workers():
    """Regression for the intermittent leaked SpawnProcess workers (suite lifecycle violation, rc=1, then a hang).

    A spawned pool worker can only run a probe that pickles by reference.  A local closure cannot, which made the
    submit fail in the pool's feeder thread and left the discarded pool's workers and manager thread alive.
    """
    from tests import test_perf_model_runtime_v2 as perf

    assert pickle.loads(pickle.dumps(perf._exploding_probe)) is perf._exploding_probe

    def closure():  # pragma: no cover - only pickled, never run
        raise RuntimeError

    with pytest.raises((pickle.PicklingError, AttributeError, TypeError)):
        pickle.dumps(closure)
    source = (ROOT / "tests" / "test_perf_model_runtime_v2.py").read_text(encoding="utf-8")
    assert 'monkeypatch.setattr(me, "_worker_warmup_probe", _exploding_probe)' in source
    assert "def broken_probe" not in source
