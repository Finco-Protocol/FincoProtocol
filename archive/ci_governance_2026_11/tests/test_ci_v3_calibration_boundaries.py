"""Reject incomplete and misleading calibration inputs without relaxing 0.6s."""
import math
import pytest
from tools.ci_v3_calibrate import main, verdict, worker_cold_start_s

@pytest.mark.parametrize('value', [True, False, -1, 0, math.inf, math.nan, '0.1'])
def test_invalid_samples_do_not_pass(value):
    assert verdict(value)['meets_test_assumption'] is False

def test_project_is_required(tmp_path):
    with pytest.raises(SystemExit) as exc: main(['--output', str(tmp_path/'result.json')])
    assert exc.value.code == 2

@pytest.mark.parametrize('repeats', [0, 1, 2, 31, True])
def test_inadequate_sample_count_rejected(repeats):
    with pytest.raises(ValueError): worker_cold_start_s('.', repeats=repeats)

def test_tail_failure_is_not_hidden_by_median(tmp_path, monkeypatch):
    from tools import ci_v3_calibrate as module
    monkeypatch.setattr(module, 'worker_cold_start_s', lambda project: (.2, [.2,.2,.601]))
    assert module.main(['--project','.', '--output',str(tmp_path/'result.json')]) == 3
    import json
    record = json.loads((tmp_path/'result.json').read_text())
    assert record['worker_cold_start_median_s'] == .2
    assert record['cold_start_s'] == .601
    assert not record['target_runner_authorized']
