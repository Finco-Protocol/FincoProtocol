"""FIN-V2-D01 — the shared Senior rate-shock authority (pure inputs, no persistence, no engine for most cases).

A requested interest shock must change the rate the clean Senior engine consumes (the typed explicit all-in vector) or be
refused with a typed code.  It must never move the auxiliary ``financing.base_rate`` and call that a result.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from app import project_factories as factories
from app.input_adapter import senior_rate_authority
from app.services import rate_shock as rs

KINDS = ("solar", "wind", "data_center", "ev_charging")
# Reference Senior all-in rates (human percent): 5.5 % Solar/Wind, 6.0 % Data Center/EV Charging.
BASE_PERCENT = {"solar": 5.5, "wind": 5.5, "data_center": 6.0, "ev_charging": 6.0}


def _ref(kind):
    return getattr(factories, f"create_generic_{kind}_reference")()


def _vector(pi):
    return pi.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates


def _with_vector(pi, vector):
    cfg = pi.financing.senior_debt_interest_config
    schedule = replace(cfg.rate_schedule, explicit_all_in_rates=tuple(vector))
    return replace(pi, financing=replace(pi.financing, senior_debt_interest_config=replace(cfg, rate_schedule=schedule)))


@pytest.mark.parametrize("kind", KINDS)
def test_reference_effective_rate_is_the_typed_vector_not_base_rate(kind):
    pi = _ref(kind)
    assert rs.effective_senior_rate_percent(pi) == pytest.approx(BASE_PERCENT[kind], abs=1e-12)
    # the auxiliary field the old shock moved is unrelated to the engine-consumed rate
    assert pi.financing.base_rate != pytest.approx(BASE_PERCENT[kind] / 100.0)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bps", [-200.0, -100.0, -25.0, 25.0, 100.0, 200.0])
def test_flat_schedule_shifts_every_period_by_the_requested_bps(kind, bps):
    pi = _ref(kind)
    shocked = rs.apply_rate_shock_bps(pi, bps)
    expected = (BASE_PERCENT[kind] + bps * 0.01) / 100.0
    old, new = _vector(pi), _vector(shocked)
    assert len(new) == len(old) and len(new) > 0
    assert all(r == pytest.approx(expected, abs=1e-12) for r in new)
    assert senior_rate_authority(shocked)[0] == "FLAT"
    assert shocked.financing.base_rate == pi.financing.base_rate            # auxiliary state is not the lever
    assert rs.effective_senior_rate_percent(shocked) == pytest.approx(BASE_PERCENT[kind] + bps * 0.01, abs=1e-10)


@pytest.mark.parametrize("kind", ("solar", "wind"))
def test_plus_100_bps_takes_5_5_percent_to_6_5_and_minus_100_to_4_5(kind):
    pi = _ref(kind)
    assert rs.effective_senior_rate_percent(pi) == pytest.approx(5.5)
    assert all(r == pytest.approx(0.065, abs=1e-12) for r in _vector(rs.apply_rate_shock_bps(pi, 100.0)))
    assert all(r == pytest.approx(0.045, abs=1e-12) for r in _vector(rs.apply_rate_shock_bps(pi, -100.0)))
    evidence = rs.rate_shock_evidence(pi, rs.apply_rate_shock_bps(pi, 100.0), 100.0)
    assert evidence == {"contract": rs.RATE_SHOCK_CONTRACT, "bps": 100.0, "before_pct": pytest.approx(5.5),
                        "after_pct": pytest.approx(6.5)}


def test_zero_shock_is_the_identity_and_never_refuses():
    pi = _ref("solar")
    assert rs.apply_rate_shock_bps(pi, 0) is pi
    assert rs.apply_rate_shock_bps(pi, 0.0) is pi
    calibrated = _with_vector(pi, (0.05, 0.06) * 15)
    assert rs.apply_rate_shock_bps(calibrated, 0.0) is calibrated         # identity request is not a shock


def test_input_object_is_never_mutated():
    pi = _ref("solar")
    before = (_vector(pi), pi.financing.margin_bps, pi.financing.base_rate)
    rs.apply_rate_shock_bps(pi, 100.0)
    assert (_vector(pi), pi.financing.margin_bps, pi.financing.base_rate) == before


@pytest.mark.parametrize("bad", [True, False, None, "100", float("nan"), float("inf"), float("-inf"), [100.0]])
def test_invalid_levels_are_refused(bad):
    with pytest.raises(rs.RateShockRefusal) as exc:
        rs.apply_rate_shock_bps(_ref("solar"), bad)
    assert exc.value.code == "RATE_SHOCK_LEVEL_INVALID"


@pytest.mark.parametrize("bps", [1500.0, 2000.0, -600.0, -1000.0])
def test_results_outside_the_human_percent_contract_are_refused(bps):
    with pytest.raises(rs.RateShockRefusal) as exc:
        rs.apply_rate_shock_bps(_ref("solar"), bps)      # 5.5 % +15 pp > 20 %, 5.5 % -5.5 pp = 0 is allowed, -6 pp < 0
    assert exc.value.code == "RATE_SHOCK_OUT_OF_RANGE"


def test_boundaries_zero_and_twenty_percent_are_representable():
    pi = _ref("solar")
    assert rs.effective_senior_rate_percent(rs.apply_rate_shock_bps(pi, -550.0)) == pytest.approx(0.0, abs=1e-9)
    assert rs.effective_senior_rate_percent(rs.apply_rate_shock_bps(pi, 1450.0)) == pytest.approx(20.0, abs=1e-9)


@pytest.mark.parametrize("vector", [(0.05, 0.06) * 15, (0.055,) * 14 + (0.056,), ()])
def test_calibrated_or_absent_schedule_is_refused_not_invented(vector):
    pi = _with_vector(_ref("solar"), vector)
    with pytest.raises(rs.RateShockRefusal) as exc:
        rs.apply_rate_shock_bps(pi, 100.0)
    assert exc.value.code == "RATE_SHOCK_CALIBRATED_SCHEDULE"
    assert _vector(pi) == tuple(vector)                                 # nothing was rewritten


def test_disabled_senior_pricing_is_refused():
    pi = _ref("solar")
    cfg = pi.financing.senior_debt_interest_config
    pi = replace(pi, financing=replace(pi.financing, senior_debt_interest_config=replace(cfg, enabled=False)))
    with pytest.raises(rs.RateShockRefusal) as exc:
        rs.apply_rate_shock_bps(pi, 100.0)
    assert exc.value.code == "RATE_SHOCK_SENIOR_PRICING_DISABLED"


def test_bankability_owned_rates_are_refused_when_the_owning_snapshot_is_known():
    from app.workbook.bankability_config import SNAPSHOT_KEY

    pi = _ref("solar")
    owned = {SNAPSHOT_KEY: json.dumps({"version": 1, "rates_pct": [5.5] * 30})}
    with pytest.raises(rs.RateShockRefusal) as exc:
        rs.apply_rate_shock_bps(pi, 100.0, snapshot=owned)
    assert exc.value.code == "RATE_SHOCK_BANKABILITY_OWNED"
    # a bankability document that does NOT own the rate vector does not block the shock
    unowned = {SNAPSHOT_KEY: json.dumps({"version": 1, "target_scalar": 1.3, "targets": []})}
    assert rs.apply_rate_shock_bps(pi, 100.0, snapshot=unowned) is not pi
    assert rs.apply_rate_shock_bps(pi, 100.0, snapshot={}) is not pi
    unreadable = {SNAPSHOT_KEY: "{not json"}
    with pytest.raises(rs.RateShockRefusal) as exc2:
        rs.apply_rate_shock_bps(pi, 100.0, snapshot=unreadable)
    assert exc2.value.code == "RATE_SHOCK_OWNER_UNREADABLE"          # an unreadable owner is never "not owned"


def test_a_shock_that_does_not_change_the_vector_is_refused(monkeypatch):
    import app.input_adapter as adapter

    monkeypatch.setattr(adapter, "_set_financing_interest_rate", lambda proj, value: proj)
    with pytest.raises(rs.RateShockRefusal) as exc:
        rs.apply_rate_shock_bps(_ref("solar"), 100.0)
    assert exc.value.code == "RATE_SHOCK_NOT_APPLIED"


def test_shocked_rate_arithmetic_matches_the_two_driver_matrix_expression():
    """The matrix computes ``original_percent + level * field_scale`` with ``field_scale = 0.01`` for bps."""
    from app.v2.sensitivity_matrix_projection import DRIVERS

    spec = DRIVERS["interest_rate"]
    assert spec.field_scale == 0.01 and spec.unit_label == "bps"
    for original in (5.5, 6.0, 9.0, 12.34):
        for level in (-200.0, -100.0, 100.0, 200.0):
            assert rs.shocked_rate_percent(original, level) == original + level * spec.field_scale


def test_unit_boundary_has_no_second_percent_to_ratio_conversion():
    """Only the F01 setter divides by 100; this module multiplies a RATIO by 100 for display and scales bps by 0.01."""
    source = (Path(rs.__file__)).read_text(encoding="utf-8")
    body = "\n".join(line for line in source.splitlines() if not line.strip().startswith(("#", '"', "*")))
    assert "/ 100" not in body and "/100" not in body and "/ 10_000" not in body and "/ 10000" not in body
    assert "_set_financing_interest_rate" in source


def test_financing_dependent_and_unlevered_kpi_sets_are_disjoint_and_exclude_project_irr_from_the_dependents():
    assert "project_irr" in rs.UNLEVERED_KPIS and "project_irr" not in rs.FINANCING_DEPENDENT_KPIS
    assert not (rs.UNLEVERED_KPIS & rs.FINANCING_DEPENDENT_KPIS)
    assert math.isfinite(rs.MIN_RATE_PERCENT) and rs.MAX_RATE_PERCENT == 20.0
