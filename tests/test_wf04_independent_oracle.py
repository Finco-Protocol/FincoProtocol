"""WF-04: the stdlib-only oracle (tools/wf04_independent_dscr_oracle.py) against the product, over REAL committed Runs and a grid of thresholds.

The oracle imports nothing from the FINCO code base, so agreement is an independent confirmation of the threshold rules, not a self-check.
"""
import ast
import math
import pathlib

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture used by cenv)
from tests.test_wf04_credit_debt_metrics import EOD, COV, cenv, credit, history, raw_min, run, update, view_of, weak_wind  # noqa: F401
from tools import wf04_independent_dscr_oracle as oracle

SOURCE = pathlib.Path(oracle.__file__)


def test_the_oracle_is_standard_library_only():
    imports = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(SOURCE.read_text())) if isinstance(n, ast.Import)}
    imports |= {n.module.split(".")[0] for n in ast.walk(ast.parse(SOURCE.read_text())) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"decimal", "math"}


def _text(value):
    return None if value is None else repr(value)


def test_oracle_and_product_agree_on_every_threshold_including_the_exact_boundary(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    low = raw_min(history(record)[0])
    above, below = math.nextafter(low, math.inf), math.nextafter(low, 0.0)
    grid = [(None, None), ("1.05", "1.2"), (_text(low), _text(low)), (_text(above), _text(above)), (_text(below), _text(below)),
            ("0.5", "0.9"), ("9.5", "10")]
    checked = 0
    for eod, cov in grid:
        update(cenv, record, EOD, "" if eod is None else eod)             # blank = not configured
        update(cenv, record, COV, "" if cov is None else cov)
        run(cenv, record)
        entry = history(record)[0]
        expected = oracle.verdicts(entry.integrity_evidence, eod, cov)
        evaluation = view_of(credit(cenv, record))["evaluation"]
        assert evaluation["achieved_min_dscr"]["min"] == expected["achieved_min"]
        assert evaluation["achieved_min_dscr"]["period"]["period_index"] == expected["achieved_min_period"]
        for key in ("eod", "covenant"):
            assert evaluation[key]["status"] == expected[key]["status"], (key, eod, cov, expected[key])
            assert [p["period_index"] for p in evaluation[key]["breaching_periods"]] == expected[key].get("periods", []), (key, eod, cov)
        assert evaluation["coverage"]["status"] == expected["coverage"]["status"]
        assert [p["period_index"] for p in evaluation["coverage"]["periods"]] == expected["coverage"].get("periods", [])
        assert expected["recompute_max_deviation"] < 1e-9                # the stored ratio really is base CFADS / debt service
        checked += 1
    assert checked == 7
    entry = history(record)[0]
    # the boundary itself: equality is no trigger, one ulp above the measured minimum is (strict <)
    assert oracle.verdicts(entry.integrity_evidence, _text(low), None)["eod"]["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
    assert oracle.verdicts(entry.integrity_evidence, _text(above), None)["eod"]["status"] == "TRIGGERED"
    assert oracle.verdicts(entry.integrity_evidence, _text(below), None)["eod"]["status"] == "NOT_TRIGGERED_UNDER_THIS_FLOOR"


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_oracle_and_product_agree_for_every_technology(cenv, kind):
    record = cenv.create(kind)
    update(cenv, record, EOD, "1.35")
    update(cenv, record, COV, "1.45")
    run(cenv, record)
    entry = history(record)[0]
    expected = oracle.verdicts(entry.integrity_evidence, "1.35", "1.45")
    evaluation = view_of(credit(cenv, record))["evaluation"]
    for key in ("eod", "covenant"):
        assert evaluation[key]["status"] == expected[key]["status"]
        assert [p["period_index"] for p in evaluation[key]["breaching_periods"]] == expected[key].get("periods", [])
    assert evaluation["coverage"]["status"] == expected["coverage"]["status"]
    assert evaluation["achieved_min_dscr"]["min"] == expected["achieved_min"]
