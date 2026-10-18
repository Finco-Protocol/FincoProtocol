"""WF-09 CAPEX spending-profile contract: exact allocation, rejection of invalid input, no silent normalisation."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from app.capex_profiles.contract import (
    ProfileError, ProfileShape as S, ProfileSpec, aggregate_by_group, allocate, build_weights, parse_percent, reject_duplicates,
)

MONTHS = (6, 12, 18, 24)


def spec(shape, **kw):
    return ProfileSpec("C.02.01", shape, **kw)


@pytest.mark.parametrize("n", MONTHS)
@pytest.mark.parametrize("shape", [S.UNIFORM, S.FRONT_LOADED, S.BACK_LOADED])
def test_preset_weights_sum_exactly_to_one_and_are_non_negative(n, shape):
    w = build_weights(spec(shape), n)
    assert len(w) == n and sum(w) == 1 and all(x >= 0 for x in w)


@pytest.mark.parametrize("n", MONTHS)
def test_front_is_monotone_decreasing_back_is_its_mirror_uniform_is_flat(n):
    f, b, u = (build_weights(spec(s), n) for s in (S.FRONT_LOADED, S.BACK_LOADED, S.UNIFORM))
    assert list(f) == sorted(f, reverse=True) and f == tuple(reversed(b)) and len(set(u)) == 1 and f[0] > u[0] > f[-1]


@pytest.mark.parametrize("n", MONTHS)
@pytest.mark.parametrize("amount", ["8250", "1234.567891", "0.000003", "1", "999999.999999"])
@pytest.mark.parametrize("shape", [S.UNIFORM, S.FRONT_LOADED, S.BACK_LOADED])
def test_monthly_uses_reconcile_exactly_to_the_owning_amount(n, amount, shape):
    r = allocate(spec(shape), amount, n)
    assert sum(m.amount_keur for m in r.months) == Decimal(amount).quantize(Decimal("0.000001")) == r.total_keur
    assert r.months[-1].cumulative_keur == r.total_keur and r.months[-1].remaining_keur == 0 and r.unallocated_keur == 0
    assert abs(r.rounding_residual_keur) <= Decimal("0.000001") * (n + 1)
    cum = Decimal(0)
    for m in r.months:                                   # cumulative / remaining are consistent every month
        cum += m.amount_keur
        assert m.cumulative_keur == cum and m.remaining_keur == r.total_keur - cum and m.amount_keur >= 0


def test_uniform_twelve_months_is_one_twelfth_each():
    r = allocate(spec(S.UNIFORM), "1200", 12)
    assert {m.amount_keur for m in r.months} == {Decimal("100.000000")}


def test_milestone_pays_everything_in_one_month():
    r = allocate(spec(S.MILESTONE, milestone_month=7), "500", 12)
    assert [m.amount_keur for m in r.months][6] == Decimal("500.000000") and sum(1 for m in r.months if m.amount_keur) == 1
    for bad in (0, 13, -1, None, True, 1.5):
        with pytest.raises(ProfileError) as exc:
            allocate(spec(S.MILESTONE, milestone_month=bad), "500", 12)
        assert exc.value.code == "CAPEX_PROFILE_MILESTONE_MONTH_INVALID"


def test_explicit_profile_exact_and_decimal_comma():
    pct = ["10", "20", "30", "40"] + ["0"] * 8
    r = allocate(spec(S.EXPLICIT, explicit_percent=tuple(pct)), "1000", 12)
    assert [m.amount_keur for m in r.months[:4]] == [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("400")]
    assert parse_percent("12,5") == Fraction(125, 1000) == parse_percent("12.5")


@pytest.mark.parametrize("pct,code", [
    (("50", "40") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_SUM_INVALID"),                 # 90 %: NOT normalised
    (("60", "50") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_SUM_INVALID"),                 # 110 %
    (("-10", "110") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_NEGATIVE"),
    (("nan", "100") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_NON_FINITE"),
    (("inf", "0") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_NON_FINITE"),
    (("-inf", "0") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_NON_FINITE"),
    (("abc", "100") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_INVALID"),
    (("", "100") + ("0",) * 10, "CAPEX_PROFILE_WEIGHT_INVALID"),
    (("100",) * 1, "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"),                              # too few months
    (("10",) * 13, "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"),                              # too many months
    (("0",) * 12, "CAPEX_PROFILE_WEIGHT_SUM_INVALID"),
])
def test_invalid_explicit_profiles_are_rejected_never_normalised(pct, code):
    with pytest.raises(ProfileError) as exc:
        allocate(spec(S.EXPLICIT, explicit_percent=pct), "1000", 12)
    assert exc.value.code == code


def test_sum_within_the_existing_tolerance_is_accepted_and_still_reconciles():
    pct = ["8.3333333333"] * 11 + ["8.3333333337"]                                     # 100.0000000000 % within 1e-9
    r = allocate(spec(S.EXPLICIT, explicit_percent=tuple(pct)), "1000", 12)
    assert r.allocated_keur == Decimal("1000.000000")
    pct = ["8.33"] * 12                                                                # 99.96 %: material -> rejected
    with pytest.raises(ProfileError):
        allocate(spec(S.EXPLICIT, explicit_percent=tuple(pct)), "1000", 12)


@pytest.mark.parametrize("shape", list(S))
def test_zero_amount_items_are_stable_and_allocate_zero(shape):
    kw = {"explicit_percent": ("50", "50") + ("0",) * 10} if shape is S.EXPLICIT else {"milestone_month": 3} if shape is S.MILESTONE else {}
    r = allocate(spec(shape, **kw), 0, 12)
    assert r.total_keur == 0 and all(m.amount_keur == 0 for m in r.months) and r.rounding_residual_keur == 0 and r.unallocated_keur == 0


@pytest.mark.parametrize("bad", [-1, "-5", float("nan"), float("inf"), "nan", None, True, "x"])
def test_invalid_amounts_are_rejected(bad):
    with pytest.raises(ProfileError) as exc:
        allocate(spec(S.UNIFORM), bad, 12)
    assert exc.value.code == "CAPEX_PROFILE_AMOUNT_INVALID"


@pytest.mark.parametrize("bad", [0, -3, 61, 1.5, "12", None, True])
def test_construction_duration_must_be_whole_months_in_range(bad):
    with pytest.raises(ProfileError) as exc:
        build_weights(spec(S.UNIFORM), bad)
    assert exc.value.code == "CAPEX_PROFILE_DURATION_INVALID"


def test_duplicate_item_identity_is_rejected():
    with pytest.raises(ProfileError) as exc:
        reject_duplicates([spec(S.UNIFORM), spec(S.FRONT_LOADED)])
    assert exc.value.code == "CAPEX_PROFILE_DUPLICATE_ITEM"
    reject_duplicates([spec(S.UNIFORM), ProfileSpec("C.02.02", S.UNIFORM)])


def test_aggregation_into_period_groups_conserves_the_total():
    r = allocate(spec(S.FRONT_LOADED), "8250", 14)
    groups = (0,) * 6 + (1,) * 6 + (2,) * 2
    agg = aggregate_by_group(r, groups, 3)
    assert sum(agg) == r.total_keur and agg[0] > agg[1] > agg[2]
    with pytest.raises(ProfileError):
        aggregate_by_group(r, groups[:-1], 3)


def test_contract_module_is_pure():
    from pathlib import Path
    src = Path("app/capex_profiles/contract.py").read_text()
    for needle in ("open(", "sqlite", "requests", "subprocess", "financial_engine", "finco_core", "random", "datetime.now"):
        assert needle not in src, needle
