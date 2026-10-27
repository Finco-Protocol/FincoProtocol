"""Correction F: the production calibration contract separates the one-time cache-cold first start from steady-state start-up speed.

Every raw sample is retained. The 0.6 s maximum is unchanged and applies to the samples after the first; the first sample has its own explicit
ceiling. Materially slower executor start-up, malformed receipts and unapproved contracts still fail closed."""
import json, math, shutil, subprocess, sys
from pathlib import Path

import pytest

from tools import ci_v3_calibrate as cal
from tools.ci_v3_calibrate import (FIRST_START_CEILING_S, LEGACY_CONTRACT, STEADY_STATE_CONTRACT, approved_contract, evaluate,
                                   worker_cold_start_s)

ROOT = Path(__file__).resolve().parent.parent

# The raw first/second/third samples of the hosted refusals recorded in run 40522709690 (workers 1, 3) and run 40534725665 (worker 0).
HOSTED_CACHE_COLD_REFUSALS = [
    [0.610031006, 0.217968788, 0.222495816],
    [0.801908379, 0.255256116, 0.251828227],
    [0.704152905, 0.243172698, 0.242377088],
]


def ok(samples, contract=STEADY_STATE_CONTRACT):
    return evaluate(samples, contract)["meets_test_assumption"]


def test_threshold_statistic_and_sample_count_are_unchanged():
    assert LEGACY_CONTRACT == {"ceiling_s": 0.6, "statistic": "maximum", "samples": 3}
    assert STEADY_STATE_CONTRACT["ceiling_s"] == 0.6 and STEADY_STATE_CONTRACT["statistic"] == "maximum" and STEADY_STATE_CONTRACT["samples"] == 3
    assert cal.COLD_START_CEILING_S == 0.6 and FIRST_START_CEILING_S == 1.8


@pytest.mark.parametrize("samples", HOSTED_CACHE_COLD_REFUSALS)
def test_the_recorded_hosted_cache_cold_first_samples_are_accepted_but_stay_visible(samples):
    record = evaluate(samples, STEADY_STATE_CONTRACT)
    assert record["meets_test_assumption"] is True
    assert record["first_start_s"] == samples[0] and record["steady_state_max_s"] == max(samples[1:]) and record["cold_start_s"] == max(samples)
    assert not ok(samples, LEGACY_CONTRACT)                    # the legacy contract would still have refused them: nothing is hidden


@pytest.mark.parametrize("samples", [
    [0.3, 0.7, 0.3], [0.3, 0.3, 0.7], [0.3, 0.601, 0.3], [0.9, 0.9, 0.9], [1.4, 1.4, 1.4],   # slower steady-state start-up (the slow validation VM)
    [1.801, 0.3, 0.3], [2.5, 0.3, 0.3], [1.9, 1.9, 1.9],                                      # gross first start
])
def test_materially_slower_startup_still_fails(samples):
    assert not ok(samples)


@pytest.mark.parametrize("samples", [[0.3, 0.6, 0.6], [1.8, 0.6, 0.6], [0.2, 0.2, 0.2], [0.61, 0.22, 0.22]])
def test_boundaries_are_inclusive_and_exact(samples):
    assert ok(samples)


@pytest.mark.parametrize("samples", [[], [0.3], [0.3, 0.3], [0.3, 0.3, 0.3, 0.3], None, "0.3", 0.3,
                                     [True, 0.3, 0.3], [0.3, False, 0.3], [0, 0.3, 0.3], [-1, 0.3, 0.3], [math.nan, 0.3, 0.3],
                                     [0.3, math.inf, 0.3], ["0.3", 0.3, 0.3], [0.3, None, 0.3]])
def test_incomplete_or_malformed_samples_never_pass(samples):
    assert ok(samples) is False
    assert ok(samples, LEGACY_CONTRACT) is False


def test_the_legacy_contract_is_unchanged_and_stricter():
    assert ok([0.2, 0.2, 0.6], LEGACY_CONTRACT) and not ok([0.2, 0.2, 0.601], LEGACY_CONTRACT) and not ok([0.61, 0.2, 0.2], LEGACY_CONTRACT)
    assert cal.verdict(0.6)["meets_test_assumption"] and not cal.verdict(0.601)["meets_test_assumption"]


@pytest.mark.parametrize("contract", [
    {**STEADY_STATE_CONTRACT, "ceiling_s": 0.7}, {**STEADY_STATE_CONTRACT, "first_start_ceiling_s": 5.0},
    {**STEADY_STATE_CONTRACT, "statistic": "median"}, {**STEADY_STATE_CONTRACT, "samples": 5}, {**STEADY_STATE_CONTRACT, "scope": "all-samples"},
    {**STEADY_STATE_CONTRACT, "extra": 1}, {"ceiling_s": 0.6, "statistic": "maximum"}, {"ceiling_s": 0.6, "statistic": "maximum", "samples": 2},
    {}, None, [], "legacy",
])
def test_unapproved_contracts_are_rejected(contract):
    assert approved_contract(contract) is False
    with pytest.raises(ValueError):
        evaluate([0.2, 0.2, 0.2], contract)


def test_exactly_the_two_reviewed_contracts_are_approved():
    assert approved_contract(dict(LEGACY_CONTRACT)) and approved_contract(dict(STEADY_STATE_CONTRACT))


def test_the_production_request_uses_the_steady_state_contract():
    text = (ROOT / "tools/ci_v3_production.py").read_text(encoding="utf-8")
    assert "'target_calibration':dict(STEADY_STATE_CONTRACT)" in text and "'ceiling_s':.6" not in text


def test_the_child_receipt_keeps_every_raw_sample_and_both_verdict_inputs():
    child = (ROOT / "tools/ci_v3_real_child.py").read_text(encoding="utf-8")
    assert '"samples_s": samples' in child and "**evaluate(samples, contract)" in child and "return 124" in child
    assert "not approved_contract(contract)" in child


def _project(tmp_path, delay_s):
    """A project whose pool-initializer import (``app.api.project_runner``, the only thing ``_worker_init`` imports) takes ``delay_s`` seconds:
    a real, controlled executor start-up slowdown paid by every fresh worker process, cold or warm."""
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "app" / "api").mkdir(parents=True)
    shutil.copytree(ROOT / "app" / "runtime", project / "app" / "runtime")
    shutil.copy(ROOT / "app" / "__init__.py", project / "app" / "__init__.py")
    (project / "app" / "api" / "__init__.py").write_text("", encoding="utf-8")
    (project / "app" / "api" / "project_runner.py").write_text("import time\ntime.sleep(%r)\n" % delay_s, encoding="utf-8")
    shutil.copy(ROOT / "tests" / "p0_exec_helpers.py", project / "tests" / "p0_exec_helpers.py")
    return project


@pytest.mark.parametrize("delay_s, expected", [(0.9, False), (2.2, False)])
def test_a_really_slower_executor_startup_is_refused_by_a_real_measurement(tmp_path, delay_s, expected):
    _, samples = worker_cold_start_s(_project(tmp_path, delay_s), repeats=3)
    record = evaluate(samples, STEADY_STATE_CONTRACT)
    assert min(samples) >= delay_s                              # every fresh process pays the injected start-up cost, cold or warm
    assert record["meets_test_assumption"] is expected
    assert record["steady_state_max_s"] > 0.6                  # caught by the steady-state gate, not only by the first-start guard


def test_a_real_measurement_has_the_expected_receipt_shape(tmp_path):
    _, samples = worker_cold_start_s(_project(tmp_path, 0), repeats=3)
    record = evaluate(samples, STEADY_STATE_CONTRACT)
    assert len(samples) == 3 and record["first_start_s"] == samples[0] and record["steady_state_max_s"] == max(samples[1:])
    assert isinstance(record["meets_test_assumption"], bool) and record["contract"] == STEADY_STATE_CONTRACT


# ── survivor diagnostics: the check stays strict, and a survivor is now attributable ─────────────────────────────

def test_describe_group_members_reports_a_live_process_and_a_vanished_one():
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        live, gone = cal.describe_group_members([sleeper.pid, 2 ** 22 + 7])
    finally:
        sleeper.kill()
        sleeper.wait()
    assert live["pid"] == sleeper.pid and live["state"] in {"S", "R", "D"} and "time.sleep" in live["cmdline"] and live["ppid"] > 0
    assert gone == {"pid": 2 ** 22 + 7, "gone_before_inspection": True}


def test_a_surviving_descendant_still_fails_the_calibration_and_is_named(monkeypatch, tmp_path):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        from tools import ci_v3_process_observer as observer
        monkeypatch.setattr(observer, "posix_group_members", lambda group: [sleeper.pid])
        with pytest.raises(RuntimeError, match="calibration left surviving descendants") as failure:
            worker_cold_start_s(_project(tmp_path, 0), repeats=3)
    finally:
        sleeper.kill()
        sleeper.wait()
    detail = json.loads(str(failure.value).split("descendants: ", 1)[1])
    assert detail["observed_at_probe_exit"][0]["pid"] == sleeper.pid and "time.sleep" in detail["observed_at_probe_exit"][0]["cmdline"]
    assert detail["remaining_after_kill"][0]["pid"] == sleeper.pid
