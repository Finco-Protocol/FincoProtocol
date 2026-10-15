"""Index-series PPA price authority tests (P0-2 supplemental audit follow-up).

Independent-oracle discipline: expected values are derived with Decimal
arithmetic inline and never by calling the authority under test beyond the
single assertion target.
"""
from decimal import Decimal

import pytest

from domain.revenue.revenue_config import PPAParams


def _params(**overrides) -> PPAParams:
    base = dict(
        ppa_enabled=True,
        ppa_base_price_eur_mwh=75.0,
        ppa_price_index=0.02,
        ppa_start_year=1,
        ppa_term_years=25,
        ppa_volume_share=1.0,
    )
    base.update(overrides)
    return PPAParams(**base)


def test_index_series_rescales_base_by_index_ratio():
    """price[y] = base * index[y] / index[1] — independent Decimal oracle."""
    p = _params(ppa_index_values=(100.0, 102.0, 103.5))
    expected = {
        1: Decimal("75") * Decimal("100") / Decimal("100"),
        2: Decimal("75") * Decimal("102") / Decimal("100"),
        3: Decimal("75") * Decimal("103.5") / Decimal("100"),
    }
    for year, want in expected.items():
        got = Decimal(repr(p.price_at_year(year)))
        assert abs(got - want) < Decimal("0.0000001"), (year, got, want)


def test_flat_index_behavior_unchanged_when_series_empty():
    """Regression: empty series keeps the flat annual-rate clock exactly."""
    p = _params()
    want = Decimal("75") * (Decimal("1.02") ** 4)
    got = Decimal(repr(p.price_at_year(5)))
    assert abs(got - want) < Decimal("0.0000001")


def test_year_beyond_series_fails_closed():
    """No silent fallback to the flat index on a mixed basis."""
    p = _params(ppa_index_values=(100.0, 102.0))
    with pytest.raises(ValueError, match="does not cover year"):
        p.price_at_year(3)


def test_non_positive_or_nan_index_entry_fails_closed():
    p = _params(ppa_index_values=(100.0, 0.0))
    with pytest.raises(ValueError, match="finite and positive"):
        p.price_at_year(2)
    p2 = _params(ppa_index_values=(100.0, float("nan")))
    with pytest.raises(ValueError, match="finite and positive"):
        p2.price_at_year(2)


def test_floor_and_cap_still_apply_with_series():
    capped = _params(ppa_index_values=(100.0, 150.0), ppa_price_cap=100.0)
    assert capped.price_at_year(2) == 100.0
    floored = _params(ppa_index_values=(100.0, 40.0), ppa_price_floor=40.0)
    assert floored.price_at_year(2) == 40.0


def test_year_zero_is_rejected():
    p = _params(ppa_index_values=(100.0,))
    with pytest.raises(ValueError, match="does not cover year"):
        p.price_at_year(0)
