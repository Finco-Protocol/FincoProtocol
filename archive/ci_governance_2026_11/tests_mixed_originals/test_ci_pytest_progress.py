"""CI progress recorder + supervisor stall/timeout evidence (synthetic suites only)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.ci_pytest_runner import _progress_line, read_progress

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


def test_records_every_test_with_phase_durations_outcomes_and_summary(tmp_path):
    (tmp_path / "test_synthetic.py").write_text(SYNTHETIC, encoding="utf-8")
    progress = tmp_path / "progress"
    result = _pytest(["-p", "tools.ci_pytest_progress", f"--ci-progress={progress}"], tmp_path)
    assert result.returncode == 1
    records = {r["n"]: r for r in _lines(progress / "tests.jsonl")}
    assert len(records) == 5
    assert records["test_synthetic.py::test_a_pass"]["o"] == "passed"
    assert records["test_synthetic.py::test_c_fail"]["o"] == "failed"
    assert records["test_synthetic.py::test_d_skip"]["o"] == "skipped"
    assert records["test_synthetic.py::test_b_slow_setup"]["s"] >= 0.1
    assert records["test_synthetic.py::test_e_call_sleep"]["c"] >= 0.15
    assert all({"s", "t", "u"} <= set(r) for r in records.values())
    active = read_progress(progress)
    assert active["phase"] == "session-finished" and active["completed"] == 5 and active["selected"] == 5
    summary = json.loads((progress / "summary.json").read_text(encoding="utf-8"))
    assert summary["tests_recorded"] == 5
    assert summary["slowest_tests"][0][0] in {"test_synthetic.py::test_e_call_sleep", "test_synthetic.py::test_b_slow_setup"}
    assert summary["slowest_modules"][0][0] == "test_synthetic.py"


@pytest.mark.parametrize("content", [None, "", "{not json", "[]", '"x"'])
def test_missing_torn_or_non_object_progress_is_reported_not_trusted(tmp_path, content):
    if content is not None:
        (tmp_path / "active.json").write_text(content, encoding="utf-8")
    assert read_progress(tmp_path) is None
    assert "no progress evidence" in _progress_line(tmp_path)
    assert read_progress(None) is None


def test_progress_line_names_active_node_phase_and_last_completed(tmp_path):
    (tmp_path / "active.json").write_text(json.dumps({
        "node": "tests/test_x.py::test_slow", "phase": "call", "phase_started_epoch": 1000.0,
        "completed": 7, "selected": 10, "last_completed": "tests/test_x.py::test_fast"}), encoding="utf-8")
    line = _progress_line(tmp_path, now=1042.0)
    assert "tests/test_x.py::test_slow" in line and "'call' for 42s" in line
    assert "completed=7/10" in line and "tests/test_x.py::test_fast" in line


def _supervised(tmp_path, budget, stall):
    (tmp_path / "test_hang.py").write_text(HANGING, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), FINCO_CI_PYTEST_BUDGET_S=str(budget), FINCO_CI_EXIT_GRACE_S="30",
               FINCO_CI_DIAG_PATH=str(tmp_path / "diag.txt"), FINCO_CI_PROGRESS_DIR=str(tmp_path / "progress"),
               FINCO_CI_STALL_S=str(stall))
    return subprocess.run([sys.executable, str(RUNNER), "-q", "-p", "no:cacheprovider", "--confcutdir", str(tmp_path),
                           "-p", "tools.ci_pytest_progress", f"--ci-progress={tmp_path / 'progress'}",
                           str(tmp_path / "test_hang.py")],
                          capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)


def test_supervisor_timeout_exits_124_and_keeps_active_node_evidence(tmp_path):
    result = _supervised(tmp_path, budget=8, stall=3600)
    assert result.returncode == 124, result.stdout + result.stderr
    assert "FINCO_CI_SUPERVISOR TIMEOUT" in result.stdout
    assert "ACTIVE AT TIMEOUT" in result.stdout and "test_b_hangs_forever" in result.stdout
    assert "PYTHON_PROCESS_EXITED" not in result.stdout
    diag = (tmp_path / "diag.txt").read_text(encoding="utf-8")
    assert "test_b_hangs_forever" in diag and "'call'" in diag and "native threads:" in diag
    active = read_progress(tmp_path / "progress")
    assert active["node"].endswith("::test_b_hangs_forever") and active["phase"] == "call"
    assert active["last_completed"].endswith("::test_a_done") and active["completed"] == 1
    finished = [r["n"] for r in _lines(tmp_path / "progress" / "tests.jsonl")]
    assert len(finished) == 1 and finished[0].endswith("test_hang.py::test_a_done")
    assert not (tmp_path / "progress" / "summary.json").exists()   # partial evidence, never a fake complete run


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


def test_report_renders_partial_evidence_and_skips_a_line_torn_by_the_kill(tmp_path):
    from tools.ci_pytest_progress import report
    (tmp_path / "active.json").write_text(json.dumps({
        "node": "tests/test_b.py::test_hangs", "phase": "call", "phase_started_utc": "2026-10-11T00:00:00.000Z",
        "completed": 2, "selected": 9, "last_completed": "tests/test_a.py::test_two"}), encoding="utf-8")
    (tmp_path / "tests.jsonl").write_text(
        json.dumps({"n": "tests/test_a.py::test_one", "s": 0.1, "c": 4.0, "t": 0.0, "o": "passed"}) + "\n"
        + json.dumps({"n": "tests/test_a.py::test_two", "s": 0.0, "c": 1.5, "t": 0.0, "o": "passed"}) + "\n"
        + '{"n": "tests/test_b.py::test_torn", "c": 9', encoding="utf-8")          # no newline: killed mid-write
    text = report(tmp_path)
    assert "active='tests/test_b.py::test_hangs' phase='call'" in text and "completed=2/9" in text
    assert "tests_recorded=2" in text and "test_torn" not in text
    assert text.index("test_one") < text.index("test_two") or "4.1s" in text


def test_report_never_raises_without_any_evidence(tmp_path):
    from tools.ci_pytest_progress import report
    text = report(tmp_path / "missing")
    assert "no active.json" in text and "no tests.jsonl" in text


def test_public_job_wires_progress_evidence_and_keeps_a_finite_budget_inside_the_job_timeout():
    import re
    text = (ROOT / ".github/workflows/ci_public_job.yml").read_text(encoding="utf-8")
    assert "-p tools.ci_pytest_inventory -p tools.ci_pytest_progress" in text
    assert "--ci-progress=artifacts/progress" in text and "FINCO_CI_PROGRESS_DIR: artifacts/progress" in text
    assert "python -m tools.ci_pytest_progress artifacts/progress" in text
    budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", text).group(1))
    grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", text).group(1))
    timeout = int(re.search(r"timeout-minutes: (\d+)", text).group(1))
    # setup/install/scan/compile (measured <= ~4 min) + budget + exit grace/kill + diagnosis + upload must fit.
    assert 0 < budget and budget + grace + 15 * 60 <= timeout * 60
    assert "tools/ci_pytest_runner.py" in text and "continue-on-error" not in text
