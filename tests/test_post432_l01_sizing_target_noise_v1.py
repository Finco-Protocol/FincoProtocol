"""Post-#432 live acceptance L01: the Senior sizing-target row is compared with a bounded floating-point tolerance.

Presentation only.  Wind showed ``required >= 1.20x / actual 1.1999999999999997x / headroom -0.000000000000x`` classified BELOW TARGET: binary noise,
not a shortfall.  The contractual verdicts (Event of Default, covenant, coverage) keep their strict raw comparison and never read this tolerance."""
from __future__ import annotations

import math

import pytest

from app.v2 import debt_metrics_projection as D
from app.workbook import dscr_contract_terms as T


def _sizing_row(bank, target):
    rows = [{"applicable": True, "bank_dscr": bank, "sizing_target_dscr": target, "period_index": 3, "date": "2030-06-30", "dscr": bank}]
    terms = T.RunTerms(False, "NOT_RECORDED")
    ev = D._unavailable_evaluation(terms, "unit test")
    table = D._covenant_table(ev, rows, {}, {})
    return {r["id"]: r for r in table}["SIZING_TARGET"]


ORACLE = [
    # (actual, target, expected status)
    (1.1999999999999997, 1.2, "AT_OR_ABOVE_TARGET"),     # the live Wind value
    (1.2, 1.2, "AT_OR_ABOVE_TARGET"),
    (1.2000000000000002, 1.2, "AT_OR_ABOVE_TARGET"),
    (math.nextafter(1.2, 0.0), 1.2, "AT_OR_ABOVE_TARGET"),
    (1.1999, 1.2, "BELOW_TARGET"),                       # a real (tiny) shortfall stays below
    (1.19, 1.2, "BELOW_TARGET"),
    (1.2 - 1e-9, 1.2, "BELOW_TARGET"),
    (1.25, 1.2, "AT_OR_ABOVE_TARGET"),
    (0.95, 1.0, "BELOW_TARGET"),                         # below 1.00x is classified, never blocked
    (0.9999999999999999, 1.0, "AT_OR_ABOVE_TARGET"),
    (1.0, 1.0, "AT_OR_ABOVE_TARGET"),
    (1.35 - 1e-9, 1.35, "BELOW_TARGET"),                 # a custom target
    (1.3499999999999999, 1.35, "AT_OR_ABOVE_TARGET"),
]


@pytest.mark.parametrize("actual,target,expected", ORACLE)
def test_boundary_oracle(actual, target, expected):
    row = _sizing_row(actual, target)
    assert row["status"] == expected
    assert row["status_label"] == ("AT OR ABOVE TARGET" if expected == "AT_OR_ABOVE_TARGET" else "BELOW TARGET")
    assert row["severity"] == ("OK" if expected == "AT_OR_ABOVE_TARGET" else "WARNING")
    assert row["actual"]["v"] == actual                  # the persisted ratio is never altered


def test_noise_is_displayed_as_the_target_with_zero_headroom_never_negative_zero():
    row = _sizing_row(1.1999999999999997, 1.2)
    assert row["required"]["d"] == "1.20x" and row["actual"]["d"] == "1.20x"
    assert row["headroom"]["absolute"]["d"] == "+0.00x" and row["headroom"]["relative"]["d"] == "+0.00%"
    for text in (row["actual"]["d"], row["headroom"]["absolute"]["d"], row["headroom"]["relative"]["d"]):
        assert "-0.0" not in text and "1.1999999999999997" not in text


def test_a_real_shortfall_keeps_a_visible_negative_headroom():
    row = _sizing_row(1.1999, 1.2)
    assert row["actual"]["d"] == "1.1999x" and row["headroom"]["absolute"]["d"].startswith("-")


def test_the_tolerance_is_bounded_and_only_the_sizing_row_uses_it():
    assert D.RATIO_NOISE_TOL == 1e-12
    row = D._status_row(row_id="X", label="x", role="r", description="d", basis="b", required=1.2, operator="≥", actual=1.1999999999999997,
                        status="s", status_label="l", severity="o")                       # snap_noise defaults to False: strict contractual rows
    assert row["actual"]["d"] == "1.1999999999999997x"
    assert D._noise_equal(None, 1.2) is False and D._noise_equal(1.2, None) is False


def test_contractual_verdicts_stay_strict():
    assert T.format_ratio(1.1999999999999997, (1.2,)) == "1.1999999999999997x"          # the exact-ulp display of the contractual rows is unchanged
