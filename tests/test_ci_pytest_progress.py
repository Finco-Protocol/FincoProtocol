"""CI progress recorder + supervisor stall/timeout evidence (synthetic suites only)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "ci_pytest_runner.py"

SYNTHETIC = '''
import time
import pytest

@pytest.fixture
def slow_setup():
    time.sleep(0.15)
    yield

def test_a_pass(): pass
def test_b_slow_setup(slow_setup): pass
def test_c_fail(): assert False, "synthetic failure"
@pytest.mark.skip(reason="synthetic skip")
def test_d_skip(): pass
def test_e_call_sleep(): time.sleep(0.2)
'''

HANGING = '''
import time

def test_a_done(): pass
def test_b_hangs_forever(): time.sleep(600)
def test_c_never_reached(): pass
'''


def _pytest(args, cwd, **extra):
    env = dict(os.environ, PYTHONPATH=str(ROOT), **extra)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--confcutdir", str(cwd), *args],
                          capture_output=True, text=True, cwd=cwd, env=env, timeout=120)


def _lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_recorder_does_not_change_collection_selection_or_outcomes(tmp_path):
    (tmp_path / "test_synthetic.py").write_text(SYNTHETIC, encoding="utf-8")
    plain = _pytest(["--collect-only"], tmp_path)
    with_plugin = _pytest(["--collect-only", "-p", "tools.ci_pytest_progress",
                           f"--ci-progress={tmp_path / 'progress'}"], tmp_path)
    assert plain.returncode == with_plugin.returncode == 0
    nodes = lambda text: [line for line in text.splitlines() if "::" in line]
    assert nodes(plain.stdout) == nodes(with_plugin.stdout) and len(nodes(plain.stdout)) == 5
    base = _pytest(["-p", "tools.ci_pytest_inventory", f"--ci-inventory={tmp_path / 'a.json'}"], tmp_path)
    inst = _pytest(["-p", "tools.ci_pytest_inventory", f"--ci-inventory={tmp_path / 'b.json'}",
                    "-p", "tools.ci_pytest_progress", f"--ci-progress={tmp_path / 'progress'}"], tmp_path)
    assert base.returncode == inst.returncode == 1          # the synthetic failure is preserved
    first, second = (json.loads((tmp_path / name).read_text(encoding="utf-8")) for name in ("a.json", "b.json"))
    for key in ("collected", "selected", "deselected", "outcomes", "collection_skips", "pytest_exit"):
        assert first[key] == second[key], key


def test_recorder_is_inert_without_its_option(tmp_path):
    (tmp_path / "test_synthetic.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    result = _pytest(["-p", "tools.ci_pytest_progress"], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(tmp_path.glob("**/active.json")) and not list(tmp_path.glob("**/tests.jsonl"))


def _supervised(tmp_path, budget, stall):
    (tmp_path / "test_hang.py").write_text(HANGING, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), FINCO_CI_PYTEST_BUDGET_S=str(budget), FINCO_CI_EXIT_GRACE_S="30",
               FINCO_CI_DIAG_PATH=str(tmp_path / "diag.txt"), FINCO_CI_PROGRESS_DIR=str(tmp_path / "progress"),
               FINCO_CI_STALL_S=str(stall))
    return subprocess.run([sys.executable, str(RUNNER), "-q", "-p", "no:cacheprovider", "--confcutdir", str(tmp_path),
                           "-p", "tools.ci_pytest_progress", f"--ci-progress={tmp_path / 'progress'}",
                           str(tmp_path / "test_hang.py")],
                          capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)


def test_supervisor_records_one_bounded_stall_snapshot_per_phase(tmp_path):
    result = _supervised(tmp_path, budget=12, stall=3)
    assert result.returncode == 124
    stalls = [line for line in result.stdout.splitlines() if "FINCO_CI_SUPERVISOR STALL" in line]
    assert len(stalls) == 1 and "test_b_hangs_forever" in stalls[0]
    diag = (tmp_path / "diag.txt").read_text(encoding="utf-8")
    assert diag.count("(stall > 3s)") == 1 and diag.count("(budget 12s exceeded") == 1


def test_supervisor_still_propagates_normal_pytest_exit_unchanged(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), FINCO_CI_DIAG_PATH=str(tmp_path / "diag.txt"),
               FINCO_CI_PROGRESS_DIR=str(tmp_path / "progress"))
    result = subprocess.run([sys.executable, str(RUNNER), "-q", "-p", "no:cacheprovider", "--confcutdir", str(tmp_path),
                             "-p", "tools.ci_pytest_progress", f"--ci-progress={tmp_path / 'progress'}",
                             str(tmp_path / "test_ok.py")],
                            capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PYTEST_MAIN_RETURNED FINCO_CI_MARKER after pytest.main rc=0" in result.stdout
    assert "PYTHON_PROCESS_EXITED FINCO_CI_SUPERVISOR child exit code 0" in result.stdout
    assert "TIMEOUT" not in result.stdout and not (tmp_path / "diag.txt").exists()


