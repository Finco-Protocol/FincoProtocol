"""WF-04: the two contractual DSCR inputs — capture, per-Run immutability of the record, strict raw evaluation and honest display.

Pure unit tests (no engine, no database).  Thresholds in the covenant cases are generated RELATIVE to the inputs under test; no
canonical contractual number is invented.
"""
import math

import pytest

from app.run_integrity.contracts import TOL_KEUR
from app.workbook import dscr_contract_terms as t


def rows(*dscrs, service=100.0, start=1):
    """Evidence-shaped period rows: one applicable period per value (None = DSCR not persisted)."""
    evidence = []
    for i, d in enumerate(dscrs):
        evidence.append({"period_index": start + i, "debt_service": service, "principal": 60.0, "interest": 40.0,
                         "base_cfads": None if d is None else d * service, "bank_cfads": 0.9 * service * (d or 1.0),
                         "reported_dscr": d, "target_dscr": 1.2})
    return t.test_rows(evidence, {start + i: f"2031-{(i % 12) + 1:02d}-28" for i in range(len(dscrs))})


def terms(eod=None, covenant=None, recorded=True):
    def term(fid, v):
        return t.Term(fid, t.NOT_CONFIGURED) if v is None else t.Term(fid, t.CONFIGURED, float(v), repr(v))
    return t.RunTerms(recorded, "" if recorded else "NOT_RECORDED", term(t.EOD_FIELD_ID, eod), term(t.COVENANT_FIELD_ID, covenant))


# ── capture / read ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_capture_distinguishes_not_configured_from_zero_and_keeps_the_exact_text():
    blank = t.capture({})
    assert blank["eod_minimum_dscr"]["status"] == t.NOT_CONFIGURED and blank["eod_minimum_dscr"]["value"] is None
    assert t.capture({t.EOD_SNAPSHOT_KEY: "   "})["eod_minimum_dscr"]["status"] == t.NOT_CONFIGURED
    assert t.capture({t.EOD_SNAPSHOT_KEY: "0"})["eod_minimum_dscr"]["status"] == t.INVALID       # 0 is never "no floor"
    ok = t.capture({t.EOD_SNAPSHOT_KEY: "1.05", t.COVENANT_SNAPSHOT_KEY: "1.2000"})
    assert ok["eod_minimum_dscr"] == {"field_id": t.EOD_FIELD_ID, "status": t.CONFIGURED, "value": 1.05, "raw": "1.05", "unit": "x"}
    assert ok["contractual_dscr"]["raw"] == "1.2000" and ok["contractual_dscr"]["value"] == 1.2
    assert ok["schema"] == t.SCHEMA and ok["test_basis"]["authority"] == "FINCO_MODEL_CONVENTION_NOT_A_LEGAL_TEST"


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", "-inf", "-1", "0.001", "10.01", "1e309"])
def test_capture_never_raises_and_records_invalid_values_as_invalid(bad):
    block = t.capture({t.EOD_SNAPSHOT_KEY: bad})["eod_minimum_dscr"]
    assert block["status"] == t.INVALID and block["value"] is None and block["raw"] == bad


def test_capture_tolerates_a_non_mapping_snapshot():
    assert t.capture(None)["contractual_dscr"]["status"] == t.NOT_CONFIGURED


def test_read_roundtrip_and_historical_runs_are_not_recorded_never_defaulted():
    recorded = t.read_run_terms({t.IDENTITY_KEY: t.capture({t.EOD_SNAPSHOT_KEY: "1.05"})})
    assert recorded.recorded and recorded.eod.value == 1.05 and recorded.contractual.status == t.NOT_CONFIGURED
    for identity in (None, {}, {"composite_hash": "x"}):
        old = t.read_run_terms(identity)
        assert not old.recorded and old.reason.startswith("NOT_RECORDED")
        assert old.eod.status == t.NOT_CONFIGURED and old.eod.value is None
    for malformed in ({t.IDENTITY_KEY: "x"}, {t.IDENTITY_KEY: {"schema": "other"}},
                      {t.IDENTITY_KEY: {**t.capture({}), "eod_minimum_dscr": {"field_id": t.EOD_FIELD_ID, "status": t.CONFIGURED, "value": float("nan")}}},
                      {t.IDENTITY_KEY: {**t.capture({}), "contractual_dscr": {"field_id": "wrong.field", "status": t.NOT_CONFIGURED}}}):
        assert t.read_run_terms(malformed).reason.startswith("UNREADABLE")


def test_applicability_convention_equals_the_integrity_check_convention():
    assert t.DEBT_SERVICE_DUE_KEUR == TOL_KEUR


# ── the Owner's acceptance cases ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_owner_example_floor_105_achieved_103_triggers_with_period_and_terms():
    out = t.evaluate(terms(eod=1.05), rows(1.4, 1.03, 1.3))
    eod = out["eod"]
    assert eod["status"] == t.EOD_TRIGGERED and eod["threshold_x"] == 1.05 and eod["threshold_raw"] == "1.05"
    assert [p["period_index"] for p in eod["breaching_periods"]] == [2] and eod["breaching_periods"][0]["dscr"] == 1.03
    assert eod["worst"]["date"] and "not a legally declared default" in eod["note"]
    assert out["achieved_min_dscr"]["min"] == 1.03


def test_equality_is_not_a_trigger():
    assert t.evaluate(terms(eod=1.05), rows(1.05, 1.2))["eod"]["status"] == t.EOD_NOT_TRIGGERED


def test_raw_value_fractionally_below_the_floor_triggers_although_two_decimals_would_match():
    below = math.nextafter(1.05, 0.0)
    assert f"{below:.2f}" == "1.05"                                      # the display would hide it …
    out = t.evaluate(terms(eod=1.05), rows(below, 1.3))
    assert out["eod"]["status"] == t.EOD_TRIGGERED                       # … the verdict does not
    assert t.format_ratio(below, (1.05,)) != "1.05x"
    above = math.nextafter(1.05, 2.0)                                    # the opposite close case must NOT trigger
    assert t.evaluate(terms(eod=1.05), rows(above))["eod"]["status"] == t.EOD_NOT_TRIGGERED


def test_covenant_breach_without_eod_uses_input_relative_values():
    floor = 1.05
    covenant = 1.25
    actual = (floor + covenant) / 2                                      # below the covenant, above the EoD floor
    out = t.evaluate(terms(eod=floor, covenant=covenant), rows(1.5, actual, 1.5))
    assert out["covenant"]["status"] == t.COV_BREACHED and out["covenant"]["message"] == t.MESSAGE_COVENANT
    assert out["eod"]["status"] == t.EOD_NOT_TRIGGERED
    assert out["covenant"]["headroom"]["absolute_x"] == pytest.approx(actual - covenant)
    assert out["covenant"]["headroom"]["relative_pct"] == pytest.approx((actual / covenant - 1) * 100)


def test_eod_triggers_even_when_the_model_shows_debt_service_fully_paid_and_says_nothing_about_payment():
    out = t.evaluate(terms(eod=1.05), rows(1.01))
    assert out["eod"]["status"] == t.EOD_TRIGGERED and out["coverage"]["status"] == t.COVERAGE_NO_DEFICIENCY
    assert "payment" not in out["eod"]["note"].replace("missed payment", "")   # no payment-default claim


def test_coverage_below_one_is_independent_of_the_configured_terms_and_reports_cfads_service_and_shortfall():
    for configured in (terms(), terms(eod=0.5), terms(eod=1.05, covenant=1.2), terms(recorded=False)):
        out = t.evaluate(configured, rows(1.4, 0.7559018708368817, 0.9))
        cov = out["coverage"]
        assert cov["status"] == t.COVERAGE_DEFICIENCY and [p["period_index"] for p in cov["periods"]] == [2, 3]
        p = cov["periods"][0]
        assert p["base_cfads_keur"] == pytest.approx(75.59018708368817) and p["debt_service_keur"] == 100.0
        assert p["shortfall_keur"] == pytest.approx(24.40981291631183) and p["principal_keur"] == 60.0 and p["interest_keur"] == 40.0
        assert cov["total_shortfall_keur"] == pytest.approx(24.40981291631183 + 10.0)
        assert "below 1.00x" in cov["message"]


def test_a_floor_below_actual_dscr_below_one_is_not_an_eod_and_a_deficit_is_not_a_default():
    out = t.evaluate(terms(eod=0.5), rows(0.7559))
    assert out["coverage"]["status"] == t.COVERAGE_DEFICIENCY and out["eod"]["status"] == t.EOD_NOT_TRIGGERED


# ── never a false PASS ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_not_configured_unrecorded_invalid_and_unusable_inputs_are_never_a_pass():
    assert t.evaluate(terms(), rows(0.5))["eod"]["status"] == t.NOT_CONFIGURED
    assert t.evaluate(terms(), rows(0.5))["covenant"]["status"] == t.NOT_CONFIGURED
    old = t.evaluate(terms(recorded=False), rows(0.5))
    assert old["eod"]["status"] == t.UNAVAILABLE and old["eod"]["reason"].startswith("NOT_RECORDED") and old["covenant"]["status"] == t.UNAVAILABLE
    bad = t.RunTerms(True, "", t.Term(t.EOD_FIELD_ID, t.INVALID, None, "abc"), t.Term(t.COVENANT_FIELD_ID, t.NOT_CONFIGURED))
    assert t.evaluate(bad, rows(0.5))["eod"]["status"] == t.UNAVAILABLE
    # no scheduled service → NOT_APPLICABLE (never 0, never a breach); no DSCR persisted → UNAVAILABLE
    nothing = t.test_rows([{"period_index": 1, "debt_service": 0.0, "reported_dscr": None}], {})
    out = t.evaluate(terms(eod=1.05, covenant=1.2), nothing)
    assert out["eod"]["status"] == t.NOT_APPLICABLE and out["coverage"]["status"] == t.NOT_APPLICABLE and not out["achieved_min_dscr"]["available"]
    missing = t.evaluate(terms(eod=1.05), rows(None, None))
    assert missing["eod"]["status"] == t.UNAVAILABLE and missing["coverage"]["status"] == t.UNAVAILABLE


def test_partial_evidence_cannot_prove_compliance_but_still_reports_a_proven_breach():
    partial = rows(1.4, None, 1.5)
    assert t.evaluate(terms(eod=1.05), partial)["eod"]["status"] == t.UNAVAILABLE
    assert t.evaluate(terms(eod=1.45), partial)["eod"]["status"] == t.EOD_TRIGGERED


def test_non_finite_and_negative_ratios_are_handled_without_error():
    out = t.evaluate(terms(eod=1.05), rows(float("nan"), -0.2, 1.3))
    assert out["eod"]["status"] == t.EOD_TRIGGERED and out["achieved_min_dscr"]["min"] == -0.2 and out["coverage"]["status"] == t.COVERAGE_DEFICIENCY


def test_period_without_service_is_excluded_from_the_tests_and_never_plotted_as_zero():
    evidence = [{"period_index": 1, "debt_service": 100.0, "base_cfads": 150.0, "reported_dscr": 1.5, "bank_cfads": 120.0},
                {"period_index": 2, "debt_service": 0.0, "base_cfads": 10.0, "reported_dscr": 0.0, "bank_cfads": 5.0}]
    built = t.test_rows(evidence, {})
    assert built[1]["applicable"] is False and built[1]["dscr"] is None and built[1]["bank_dscr"] is None
    assert t.evaluate(terms(eod=1.05), built)["eod"]["status"] == t.EOD_NOT_TRIGGERED


def test_bank_case_is_reported_separately_and_never_decides_the_verdicts():
    out = t.evaluate(terms(eod=1.05), rows(1.3))
    assert out["bank_case_min_dscr"]["available"] and out["bank_case_min_dscr"]["min"] == pytest.approx(0.9 * 1.3)
    assert out["eod"]["status"] == t.EOD_NOT_TRIGGERED            # bank-case 1.17 / actual 1.3 — verdict follows the base ratio only


# ── display ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value, refs, shown", [
    (0.9951, (1.0,), "0.995x"), (0.99999, (1.0,), "0.99999x"), (0.7559018708368817, (1.0,), "0.76x"), (1.2, (1.0,), "1.20x"),
    (1.0, (1.0,), "1.00x"), (1.004, (1.0,), "1.004x"), (1.05, (1.05,), "1.05x"), (0.5, (1.0, 1.05), "0.50x"),
])
def test_format_ratio_never_reads_equal_to_a_reference_unless_it_is(value, refs, shown):
    assert t.format_ratio(value, refs) == shown


@pytest.mark.parametrize("value, ref", [(0.9951, 1.0), (0.99999, 1.0), (1.049999999, 1.05), (1.0500001, 1.05), (1.004, 1.0)])
def test_format_ratio_close_to_threshold_is_distinguishable_from_the_threshold(value, ref):
    assert t.format_ratio(value, (ref,)) != t.format_ratio(ref, (ref,))
    assert (float(t.format_ratio(value, (ref,))[:-1]) < ref) == (value < ref)


def test_a_value_one_ulp_from_a_reference_prints_its_exact_text_never_a_trailing_zero_lookalike():
    below, above = math.nextafter(1.05, 0.0), math.nextafter(1.05, math.inf)
    assert t.format_ratio(below, (1.05,)) == "1.0499999999999998x" and t.format_ratio(above, (1.05,)) == "1.0500000000000003x"
    assert t.format_ratio(1.05, (1.05,)) == "1.05x"


def test_format_ratio_unavailable_values():
    for bad in (None, True, float("nan"), float("inf"), "1.0"):
        assert t.format_ratio(bad) == "—"
    assert t.headroom(None, 1.0) is None and t.headroom(1.2, None) is None and t.headroom(1.2, 0.0) is None


@pytest.mark.parametrize("delta, shown", [(0.15, "+0.15x"), (-0.0074885, "-0.0075x"), (-0.00001234, "-0.000012x"), (1.234, "+1.23x"), (0.0, "+0.00x"), (-0.10, "-0.10x")])
def test_format_delta_never_hides_or_exaggerates_a_small_difference(delta, shown):
    assert t.format_delta_x(delta) == shown


@pytest.mark.parametrize("pct, shown", [(-0.75, "-0.75%"), (-0.0012, "-0.0012%"), (12.5, "+12.50%"), (0.0, "+0.00%")])
def test_format_relative_pct(pct, shown):
    assert t.format_relative_pct(pct) == shown
    assert t.format_delta_x(None) == "—" and t.format_relative_pct(float("nan")) == "—"
