"""Calibration verdicts are derived from the fixed test sleeps and fail closed on slow hosts."""
from tools.ci_v3_calibrate import COLD_START_CEILING_S, cpu_loop_s, verdict


def test_ceiling_is_below_the_disconnect_test_budget():
    # tests/test_p0a_model_execution.py: cancel at 0.4 s, assert after 1.8 s more, calculation 1.5 s => cold start <= 0.7 s
    assert COLD_START_CEILING_S < 2.2 - 1.5


def test_verdict_fails_closed_above_the_ceiling():
    assert verdict(0.3)["meets_test_assumption"] is True
    assert verdict(COLD_START_CEILING_S)["meets_test_assumption"] is True
    assert verdict(1.4)["meets_test_assumption"] is False      # measured on the slow validation VM


def test_cpu_loop_reports_positive_seconds_even_on_a_fast_host():
    # The hosted runner finishes 10k iterations in under 0.5 ms; three-decimal rounding made that 0.0 and failed CI.
    value = cpu_loop_s(200_000)
    assert isinstance(value, float) and value > 0
    assert cpu_loop_s(10_000) >= 0
