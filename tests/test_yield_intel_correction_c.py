"""PR #178 final correction regressions: Treasury LKG + generic APY components."""

from decimal import Decimal
import time

from finco_yield.schema import ComponentState, ScenarioState, YieldObservation
from finco_yield.underwriting import decompose, run_scenario
import finco_yield.treasury as treasury


def _available():
    return treasury.TreasuryObservation(
        "AVAILABLE",
        treasury.TREASURY_SOURCE,
        Decimal("4.28"),
        "2026-10-02",
        "2026-10-03T08:00:00+00:00",
        None,
    )


def _unavailable(reason="SOURCE_UNAVAILABLE"):
    return treasury.TreasuryObservation(
        "UNAVAILABLE", treasury.TREASURY_SOURCE, None, None, None, reason
    )


def _clock(monkeypatch):
    state = {"value": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: state["value"])
    return state


def test_typed_unavailable_refresh_with_prior_lkg_returns_stale(monkeypatch):
    treasury.reset_treasury_cache()
    clock = _clock(monkeypatch)
    sequence = iter([_available(), _unavailable()])
    monkeypatch.setattr(treasury, "FredEconomyProvider", lambda: object())
    monkeypatch.setattr(treasury, "_read_treasury", lambda provider: next(sequence))

    first = treasury.latest_treasury()
    assert first.usable
    clock["value"] = treasury._TREASURY_TTL_OK_SECONDS + 1
    stale = treasury.latest_treasury()

    assert stale.state == "STALE"
    assert stale.reason == "TREASURY_LAST_KNOWN_GOOD_EXPIRED"
    assert stale.yield_percent == Decimal("4.28")
    assert stale.period == "2026-10-02"
    assert stale.retrieved_at == "2026-10-03T08:00:00+00:00"
    assert stale.source == treasury.TREASURY_SOURCE
    assert stale.usable is False


def test_lkg_survives_typed_failure_then_thrown_refresh(monkeypatch):
    treasury.reset_treasury_cache()
    clock = _clock(monkeypatch)
    calls = {"n": 0}

    def read(_provider):
        calls["n"] += 1
        if calls["n"] == 1:
            return _available()
        if calls["n"] == 2:
            return _unavailable()
        raise RuntimeError("network down")

    monkeypatch.setattr(treasury, "FredEconomyProvider", lambda: object())
    monkeypatch.setattr(treasury, "_read_treasury", read)

    assert treasury.latest_treasury().usable
    clock["value"] = treasury._TREASURY_TTL_OK_SECONDS + 1
    assert treasury.latest_treasury().state == "STALE"
    clock["value"] += treasury._TREASURY_TTL_UNAVAILABLE_SECONDS + 1
    stale_again = treasury.latest_treasury()

    assert stale_again.state == "STALE"
    assert stale_again.reason == "TREASURY_LAST_KNOWN_GOOD_EXPIRED"
    assert stale_again.yield_percent == Decimal("4.28")
    assert stale_again.period == "2026-10-02"
    assert stale_again.retrieved_at == "2026-10-03T08:00:00+00:00"


def test_no_prior_lkg_failed_refresh_stays_unavailable(monkeypatch):
    treasury.reset_treasury_cache()
    _clock(monkeypatch)
    monkeypatch.setattr(treasury, "FredEconomyProvider", lambda: object())
    monkeypatch.setattr(treasury, "_read_treasury", lambda provider: _unavailable())

    result = treasury.latest_treasury()
    assert result.state == "UNAVAILABLE"
    assert result.yield_percent is None
    assert result.usable is False


def test_thrown_refresh_with_lkg_returns_stale(monkeypatch):
    treasury.reset_treasury_cache()
    clock = _clock(monkeypatch)
    calls = {"n": 0}

    def read(_provider):
        calls["n"] += 1
        if calls["n"] == 1:
            return _available()
        raise RuntimeError("network down")

    monkeypatch.setattr(treasury, "FredEconomyProvider", lambda: object())
    monkeypatch.setattr(treasury, "_read_treasury", read)

    treasury.latest_treasury()
    clock["value"] = treasury._TREASURY_TTL_OK_SECONDS + 1
    result = treasury.latest_treasury()
    assert result.state == "STALE"
    assert result.reason == "TREASURY_LAST_KNOWN_GOOD_EXPIRED"
    assert result.yield_percent == Decimal("4.28")


def test_generic_explicit_rewards_still_support_component_math_and_scenarios():
    # Original Y0 positional contract: tvl, total, base, rewards, intrinsic,
    # annualized costs.  Intelligence fields must not displace these slots.
    observation = YieldObservation(
        Decimal("100"),
        Decimal(".08"),
        Decimal(".05"),
        Decimal(".02"),
        Decimal(".01"),
        Decimal(".005"),
    )
    result = decompose(observation)
    assert result.state == ComponentState.AVAILABLE
    assert result.organic_share == Decimal(".75")
    assert result.reward_dependency == Decimal(".25")
    assert result.reward_off_apy == Decimal(".055")
    assert run_scenario("REWARDS_OFF", observation).apy == Decimal(".06")
    assert run_scenario("REWARDS_MINUS_50", observation).apy == Decimal(".07")


def test_missing_rewards_are_not_inferred_from_total_minus_base():
    observation = YieldObservation(
        tvl_usd=Decimal("100"),
        apy_total=Decimal(".08"),
        apy_base=Decimal(".05"),
        apy_rewards=None,
        apy_intrinsic=Decimal(".01"),
    )
    assert decompose(observation).state == ComponentState.COMPONENTS_UNAVAILABLE
    scenario = run_scenario("REWARDS_OFF", observation)
    assert scenario.state == ScenarioState.NOT_MODELLED
    assert scenario.apy is None
