"""Advanced Revenue V4 candidate — focused acceptance battery (WF-04A).

RELEASE-CLOSED CANDIDATE TESTS. Mirrors the house conventions
(``tests/test_revenue_v3_products.py``): the flag must be a literal False
at import, all public entry points fail closed by default, and only an
isolated monkeypatch fixture enables the gate for the pure-math checks.

Coverage:
  - release closure (flag, every entry point, no env enabling)
  - parse/validate fail-closed matrix (unknown keys/members, NaN/Inf,
    bool-as-number, negative where disallowed, wrong arities, identity)
  - negative-price policies: SETTLE_NORMALLY / NO_SETTLEMENT / CURTAIL,
    plant vs single-stream scope, scope/action cross-rules, no double
    policy, hourly classification, period-declared share
  - contracted volume: SHARE round-trip, FIXED_ANNUAL_MWH allocation
    (incl. zero-hour periods, residual assignment, crossing-COD zero
    periods), MONTHLY_MW_SHAPE conversion + period aggregation (missing
    month, double-claimed month)
  - price modes: FIXED / MARKET_FLOOR / MARKET_CAP / FLOOR_AND_CAP,
    REVENUE_SHARING unsupported (fail closed everywhere), missing market
    evidence -> None, malformed market evidence -> typed error
  - route-to-market: EUR/MWh vs percent, up-only escalation (negative
    rate fails closed), exact review-month counting, fee-exceeds-revenue
    fail closed
  - deterministic canonical_json
  - no double settlement (each month/energy unit claimed at most once)
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from app.revenue_v4_candidate import (
    ACTIVATION_ENABLED,
    AdvancedRevenueV4Candidate,
    ContractedVolume,
    NegativePriceHoursPolicy,
    PriceModeRule,
    RouteToMarketFee,
    StreamCandidate,
    aggregate_monthly_to_periods,
    apply_negative_price_policy,
    apply_route_to_market_fee,
    classify_hourly_prices,
    completed_annual_reviews,
    convert_monthly_mw,
    fixed_annual_mwh_to_periods,
    parse_candidate,
    parse_contracted_volume,
    parse_negative_price_hours,
    parse_price_mode,
    parse_route_to_market,
    parse_stream_candidate,
    period_negative_share,
    require_release,
    resolve_market_mode_price,
)


@pytest.fixture()
def released(monkeypatch):
    """Isolated acceptance fixture: enable the candidate gate in memory."""
    import app.revenue_v4_candidate.contracts as contracts
    import app.revenue_v4_candidate.pure as pure
    monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)
    monkeypatch.setattr(pure, "ACTIVATION_ENABLED", True)
    yield


#: Candidate book identity markers a hand-written payload must carry.
IDENT = {"_schema": "finco.revenue-v4-candidate", "schema_version": 1,
         "activation": "RELEASE_CLOSED"}


# ── Release closure ──────────────────────────────────────────────────────────


class TestReleaseClosure:
    def test_flag_is_a_literal_false_at_import(self):
        assert ACTIVATION_ENABLED is False

    @pytest.mark.parametrize("call", [
        lambda: parse_negative_price_hours({"scope": "PLANT", "action": "CURTAIL"}),
        lambda: parse_contracted_volume({"mode": "SHARE_OF_OUTPUT", "share": 0.5}),
        lambda: parse_price_mode({"mode": "FIXED", "fixed_price_eur_mwh": 50.0}),
        lambda: parse_route_to_market({"fee_basis": "EUR_PER_MWH", "fee_value": 1.0}),
        lambda: parse_stream_candidate({"stream_id": "s1", "contracted_volume": {"mode": "SHARE_OF_OUTPUT", "share": 0.5}}),
        lambda: parse_candidate({"streams": [{"stream_id": "s1", "price_mode": {"mode": "FIXED", "fixed_price_eur_mwh": 1.0}}]}),
    ])
    def test_every_parse_entry_fails_closed(self, call):
        with pytest.raises(ValueError, match="REVENUE_V4_RELEASE_CLOSED"):
            call()

    @pytest.mark.parametrize("call", [
        lambda: classify_hourly_prices([1.0, -1.0]),
        lambda: period_negative_share(100.0, 5.0),
        lambda: fixed_annual_mwh_to_periods(1000.0, [100.0]),
        lambda: convert_monthly_mw([1.0] * 12, [1.0] * 12),
        lambda: aggregate_monthly_to_periods({(2026, 1): 1.0}, [("p", ((2026, 1),))]),
        lambda: resolve_market_mode_price(PriceModeRule(mode="FIXED", fixed_price_eur_mwh=5.0), 4.0),
        lambda: completed_annual_reviews(date(2027, 1, 1), date(2026, 1, 1), 1),
        lambda: apply_route_to_market_fee(
            RouteToMarketFee(fee_basis="EUR_PER_MWH", fee_value=1.0),
            delivered_mwh=1.0, gross_revenue_eur=Decimal("100"),
            completed_reviews=0),
    ])
    def test_every_pure_entry_fails_closed(self, call):
        with pytest.raises(ValueError, match="REVENUE_V4_RELEASE_CLOSED"):
            call()

    def test_no_environment_variable_can_enable_the_gate(self, monkeypatch):
        for env in ("FINCO_REVENUE_V4_ENABLED", "FINCO_REVENUE_V4_ACTIVATION",
                    "REVENUE_V4_ACTIVATION_ENABLED"):
            monkeypatch.setenv(env, "1")
        import app.revenue_v4_candidate.contracts as contracts
        assert contracts.ACTIVATION_ENABLED is False
        with pytest.raises(ValueError, match="REVENUE_V4_RELEASE_CLOSED"):
            contracts.require_release()

    def test_candidate_gate_enabled_only_inside_fixture(self, released):
        parse_price_mode({"mode": "FIXED", "fixed_price_eur_mwh": 50.0})


# ── Parse / validate fail-closed matrix ──────────────────────────────────────


class TestFailClosedParsing:
    def test_unknown_top_level_key_rejected(self, released):
        with pytest.raises(ValueError, match="unsupported key"):
            parse_candidate({"streams": [{"stream_id": "s", "price_mode": {"mode": "FIXED", "fixed_price_eur_mwh": 1.0}}],
                             "price_interpolation": "linear"})

    def test_unknown_nph_action_rejected(self, released):
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            parse_negative_price_hours({"scope": "PLANT", "action": "OPTIMISE"})

    def test_single_stream_requires_stream_id(self, released):
        with pytest.raises(ValueError, match="SINGLE_STREAM"):
            parse_negative_price_hours({"scope": "SINGLE_STREAM", "action": "CURTAIL"})

    def test_plant_scope_must_not_carry_stream_id(self, released):
        with pytest.raises(ValueError, match="PLANT scope"):
            parse_negative_price_hours(
                {"scope": "PLANT", "action": "CURTAIL", "stream_id": "s1"})

    def test_volume_mode_requires_exactly_12_shape_values(self, released):
        with pytest.raises(ValueError, match="exactly"):
            parse_contracted_volume({"mode": "MONTHLY_MW_SHAPE",
                                     "monthly_mw": [1.0] * 11,
                                     "shape_timezone": "UTC"})

    def test_shape_timezone_must_be_utc(self, released):
        with pytest.raises(ValueError, match="UTC"):
            parse_contracted_volume({"mode": "MONTHLY_MW_SHAPE",
                                     "monthly_mw": [1.0] * 12,
                                     "shape_timezone": "Europe/Berlin"})

    def test_volume_mode_stray_fields_rejected(self, released):
        with pytest.raises(ValueError, match="must not carry"):
            parse_contracted_volume({"mode": "SHARE_OF_OUTPUT", "share": 0.5,
                                     "fixed_annual_mwh": 100.0})

    def test_share_bounds(self, released):
        with pytest.raises(ValueError, match="at most 1.0"):
            parse_contracted_volume({"mode": "SHARE_OF_OUTPUT", "share": 1.5})

    def test_fixed_annual_mwh_must_be_positive(self, released):
        with pytest.raises(ValueError, match="strictly positive"):
            parse_contracted_volume({"mode": "FIXED_ANNUAL_MWH",
                                     "fixed_annual_mwh": 0.0})

    def test_floor_above_cap_rejected(self, released):
        with pytest.raises(ValueError, match="floor exceeds cap"):
            parse_price_mode({"mode": "FLOOR_AND_CAP", "floor_eur_mwh": 90.0,
                              "cap_eur_mwh": 10.0})

    def test_negative_fixed_price_rejected(self, released):
        """The released authorities fail closed on negative prices; the
        candidate preserves that rule (the production NPH question is a
        separate owner decision, not a silent acceptance here)."""
        with pytest.raises(ValueError, match="at least 0.0"):
            parse_price_mode({"mode": "FIXED", "fixed_price_eur_mwh": -5.0})

    def test_revenue_sharing_is_unsupported_not_validated_as_a_mechanism(self, released):
        """Any REVENUE_SHARING payload fails closed as UNSUPPORTED, including
        otherwise well-formed ones; its bounds are never the question."""
        for raw in ({"mode": "REVENUE_SHARING", "project_share": 0.7},
                    {"mode": "REVENUE_SHARING", "project_share": 1.2},
                    {"mode": "REVENUE_SHARING"}):
            with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED.*D-10"):
                parse_price_mode(raw)

    def test_negative_escalation_rejected_up_only(self, released):
        with pytest.raises(ValueError, match="at least 0.0"):
            parse_route_to_market({"fee_basis": "EUR_PER_MWH", "fee_value": 1.0,
                                   "escalation_rate": -0.01,
                                   "escalation_timing": "ANNUAL_REVIEW",
                                   "review_month": 3})

    def test_annual_review_requires_review_month(self, released):
        with pytest.raises(ValueError, match="review_month"):
            parse_route_to_market({"fee_basis": "EUR_PER_MWH", "fee_value": 1.0,
                                   "escalation_rate": 0.02,
                                   "escalation_timing": "ANNUAL_REVIEW"})

    def test_review_month_bounds_and_bool_rejection(self, released):
        for bad in (0, 13, True, 1.5):
            with pytest.raises(ValueError, match="review_month"):
                parse_route_to_market({"fee_basis": "EUR_PER_MWH", "fee_value": 1.0,
                                       "escalation_rate": 0.02,
                                       "escalation_timing": "ANNUAL_REVIEW",
                                       "review_month": bad})

    def test_review_month_requires_annual_timing(self, released):
        with pytest.raises(ValueError, match="ANNUAL_REVIEW"):
            parse_route_to_market({"fee_basis": "EUR_PER_MWH", "fee_value": 1.0,
                                   "review_month": 3})

    def test_percent_fee_above_one_rejected(self, released):
        with pytest.raises(ValueError, match="fraction"):
            parse_route_to_market({"fee_basis": "PERCENT_OF_REVENUE",
                                   "fee_value": 1.5})

    def test_bool_as_number_rejected(self, released):
        with pytest.raises(ValueError, match="finite number"):
            parse_contracted_volume({"mode": "FIXED_ANNUAL_MWH",
                                     "fixed_annual_mwh": True})

    def test_nan_and_inf_rejected(self, released):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="finite"):
                parse_contracted_volume({"mode": "FIXED_ANNUAL_MWH",
                                         "fixed_annual_mwh": bad})

    def test_stream_requires_at_least_one_term(self, released):
        with pytest.raises(ValueError, match="at least one candidate term"):
            parse_stream_candidate({"stream_id": "s1"})

    def test_duplicate_stream_ids_rejected(self, released):
        raw = {**IDENT, "streams": [
            {"stream_id": "s1", "price_mode": {"mode": "FIXED", "fixed_price_eur_mwh": 1.0}},
            {"stream_id": "s1", "price_mode": {"mode": "FIXED", "fixed_price_eur_mwh": 2.0}},
        ]}
        with pytest.raises(ValueError, match="duplicate stream candidate"):
            parse_candidate(raw)

    def test_stream_level_nph_must_target_own_stream(self, released):
        raw = {**IDENT, "streams": [{"stream_id": "s1",
                            "negative_price_hours": {"scope": "SINGLE_STREAM",
                                                     "action": "CURTAIL",
                                                     "stream_id": "s2"}}]}
        with pytest.raises(ValueError, match="own stream_id"):
            parse_candidate(raw)

    def test_plant_and_stream_nph_policies_cannot_combine(self, released):
        raw = {**IDENT, "streams": [{"stream_id": "s1",
                            "negative_price_hours": {"scope": "SINGLE_STREAM",
                                                     "action": "CURTAIL",
                                                     "stream_id": "s1"}}],
               "plant_negative_price_hours": {"scope": "PLANT",
                                              "action": "NO_SETTLEMENT"}}
        with pytest.raises(ValueError, match="cannot be combined"):
            parse_candidate(raw)

    def test_empty_book_rejected(self, released):
        with pytest.raises(ValueError, match="non-empty"):
            parse_candidate({**IDENT, "streams": []})


# ── Negative price policies (math) ───────────────────────────────────────────


class TestNegativePricePolicies:
    def _policy(self, action, scope="PLANT", stream_id=None):
        return NegativePriceHoursPolicy(scope=scope, action=action,
                                        stream_id=stream_id)

    def test_settle_normally_keeps_the_negative_settlement(self, released):
        out = apply_negative_price_policy(
            self._policy("SETTLE_NORMALLY"),
            negative_mwh=100.0, negative_price_eur_mwh=-2.0,
            nonnegative_mwh=900.0, nonnegative_price_eur_mwh=40.0)
        assert out.delivered_mwh == 1000.0
        assert out.settled_revenue_eur == Decimal("-200.0") + Decimal("36000.0")
        assert out.settled_revenue_eur == Decimal("35800.0")

    def test_no_settlement_delivers_energy_but_waives_negative_revenue(self, released):
        out = apply_negative_price_policy(
            self._policy("NO_SETTLEMENT"),
            negative_mwh=100.0, negative_price_eur_mwh=-2.0,
            nonnegative_mwh=900.0, nonnegative_price_eur_mwh=40.0)
        # energy still delivered (physical MWh unchanged)
        assert out.delivered_mwh == 1000.0
        # commercial settlement of the negative bucket waived — not zeroed MWh
        assert out.settled_revenue_eur == Decimal("36000.0")

    def test_curtail_removes_the_physical_energy(self, released):
        out = apply_negative_price_policy(
            self._policy("CURTAIL"),
            negative_mwh=100.0, negative_price_eur_mwh=-2.0,
            nonnegative_mwh=900.0, nonnegative_price_eur_mwh=40.0)
        assert out.delivered_mwh == 900.0
        assert out.settled_revenue_eur == Decimal("36000.0")

    def test_all_negative_hours(self, released):
        out = apply_negative_price_policy(
            self._policy("NO_SETTLEMENT"),
            negative_mwh=500.0, negative_price_eur_mwh=-1.0,
            nonnegative_mwh=0.0, nonnegative_price_eur_mwh=0.0)
        assert out.delivered_mwh == 500.0
        assert out.settled_revenue_eur == Decimal("0")

    def test_empty_bucket_is_a_legitimate_zero(self, released):
        out = apply_negative_price_policy(
            self._policy("SETTLE_NORMALLY"),
            negative_mwh=0.0, negative_price_eur_mwh=0.0,
            nonnegative_mwh=100.0, nonnegative_price_eur_mwh=30.0)
        assert out.delivered_mwh == 100.0
        assert out.settled_revenue_eur == Decimal("3000.0")

    def test_positive_bucket_may_not_carry_a_negative_price(self, released):
        with pytest.raises(ValueError, match="negative_price_eur_mwh"):
            apply_negative_price_policy(
                self._policy("SETTLE_NORMALLY"),
                negative_mwh=0.0, negative_price_eur_mwh=0.0,
                nonnegative_mwh=100.0, nonnegative_price_eur_mwh=-5.0)

    def test_scope_and_action_ridden_through_for_audit(self, released):
        out = apply_negative_price_policy(
            self._policy("CURTAIL", scope="SINGLE_STREAM", stream_id="ppa"),
            negative_mwh=10.0, negative_price_eur_mwh=-1.0,
            nonnegative_mwh=0.0, nonnegative_price_eur_mwh=0.0)
        assert out.policy_scope == "SINGLE_STREAM"
        assert out.policy_action == "CURTAIL"

    def test_hourly_classification_is_deterministic(self, released):
        neg, pos = classify_hourly_prices([10.0, -0.1, 0.0, -5.0, 3.0])
        assert neg == (1, 3)
        assert pos == (0, 2, 4)
        with pytest.raises(ValueError, match="malformed evidence|finite"):
            classify_hourly_prices([1.0, float("nan")])

    def test_period_declared_share(self, released):
        assert period_negative_share(1000.0, 50.0) == pytest.approx(0.05)
        with pytest.raises(ValueError, match="exceeds the period energy"):
            period_negative_share(100.0, 150.0)
        with pytest.raises(ValueError, match="strictly positive"):
            period_negative_share(0.0, 0.0)

    def test_no_double_policy_across_scopes_enforced_at_book_level(self, released):
        book = AdvancedRevenueV4Candidate(
            streams=(StreamCandidate(
                stream_id="s1",
                negative_price_hours=NegativePriceHoursPolicy(
                    scope="SINGLE_STREAM", action="CURTAIL", stream_id="s1")),),
            plant_negative_price_hours=NegativePriceHoursPolicy(
                scope="PLANT", action="CURTAIL"))
        with pytest.raises(ValueError, match="cannot be combined"):
            book.validate()


# ── Contracted volume modes ──────────────────────────────────────────────────


class TestContractedVolumeModes:
    def test_fixed_annual_mwh_pro_rata_by_declared_hours(self, released):
        # two periods, 2:1 hours → 2:1 allocation
        out = fixed_annual_mwh_to_periods(1000.0, [4000.0, 2000.0])
        assert out[0] == pytest.approx(1000.0 * 2 / 3)
        assert out[1] == pytest.approx(1000.0 * 1 / 3)
        assert sum(out) == pytest.approx(1000.0)

    def test_fixed_annual_mwh_residual_lands_on_last_active_period(self, released):
        # 1/3 splits twice cannot be exact in binary floats; residual must
        # be assigned, never dropped
        out = fixed_annual_mwh_to_periods(100.0, [1000.0, 1000.0, 1000.0])
        assert sum(out) == pytest.approx(100.0, abs=0.0) or \
            sum(out) == 100.0
        assert all(v > 0 for v in out)

    def test_fixed_annual_mwh_zero_hour_periods_get_zero(self, released):
        out = fixed_annual_mwh_to_periods(1000.0, [0.0, 4000.0, 2000.0])
        assert out[0] == 0.0
        assert sum(out) == pytest.approx(1000.0)

    def test_fixed_annual_mwh_crossing_cod_zero_pre_cod_periods(self, released):
        # pre-COD periods are modeled as zero-hour periods by the caller
        out = fixed_annual_mwh_to_periods(8760.0, [0.0, 0.0, 4380.0, 4380.0])
        assert out[:2] == (0.0, 0.0)
        assert sum(out) == pytest.approx(8760.0)

    def test_fixed_annual_mwh_all_zero_hours_fail_closed(self, released):
        with pytest.raises(ValueError, match="cover no time"):
            fixed_annual_mwh_to_periods(1000.0, [0.0, 0.0])

    def test_convert_monthly_mw_units(self, released):
        # 10 MW × 730 h = 7300 MWh
        out = convert_monthly_mw([10.0] * 12, [730.0] * 12)
        assert out == (7300.0,) * 12
        with pytest.raises(ValueError, match="exactly 12"):
            convert_monthly_mw([1.0] * 12, [1.0] * 11)

    def test_aggregate_months_to_periods(self, released):
        monthly = {(2026, 1): 100.0, (2026, 2): 120.0, (2026, 3): 140.0,
                   (2026, 4): 160.0}
        out = aggregate_monthly_to_periods(
            monthly, [("H1", ((2026, 1), (2026, 2))),
                      ("H2", ((2026, 3), (2026, 4)))])
        assert out == (("H1", 220.0), ("H2", 300.0))

    def test_missing_month_is_never_interpolated(self, released):
        with pytest.raises(ValueError, match="never interpolated|no declared"):
            aggregate_monthly_to_periods(
                {(2026, 1): 100.0},
                [("H1", ((2026, 1), (2026, 2)))])

    def test_double_claimed_month_fails_no_double_settlement(self, released):
        with pytest.raises(ValueError, match="double settlement"):
            aggregate_monthly_to_periods(
                {(2026, 1): 100.0},
                [("A", ((2026, 1),)), ("B", ((2026, 1),))])

    def test_share_of_output_round_trip(self, released):
        vol = parse_contracted_volume({"mode": "SHARE_OF_OUTPUT", "share": 0.6})
        assert vol.share == 0.6
        assert vol.mode == "SHARE_OF_OUTPUT"


# ── Price modes ──────────────────────────────────────────────────────────────


class TestPriceModes:
    def test_fixed_ignores_market(self, released):
        rule = PriceModeRule(mode="FIXED", fixed_price_eur_mwh=42.0)
        assert resolve_market_mode_price(rule, 100.0) == Decimal("42.0")
        # FIXED needs no market evidence at all: a MISSING observation is fine
        assert resolve_market_mode_price(rule, None) == Decimal("42.0")

    def test_fixed_does_not_hide_malformed_market_evidence(self, released):
        rule = PriceModeRule(mode="FIXED", fixed_price_eur_mwh=42.0)
        for bad in (float("nan"), float("inf"), True, "banana"):
            with pytest.raises(ValueError, match="REVENUE_V4_VALUE"):
                resolve_market_mode_price(rule, bad)

    def test_market_floor_lifts_low_prices(self, released):
        rule = PriceModeRule(mode="MARKET_FLOOR", floor_eur_mwh=20.0)
        assert resolve_market_mode_price(rule, 15.0) == Decimal("20")
        assert resolve_market_mode_price(rule, 25.0) == Decimal("25")

    def test_market_floor_on_negative_market_is_non_negative(self, released):
        rule = PriceModeRule(mode="MARKET_FLOOR", floor_eur_mwh=0.0)
        assert resolve_market_mode_price(rule, -3.0) == Decimal("0")

    def test_market_caps_high_prices(self, released):
        rule = PriceModeRule(mode="MARKET_CAP", cap_eur_mwh=80.0)
        assert resolve_market_mode_price(rule, 95.0) == Decimal("80")
        assert resolve_market_mode_price(rule, 70.0) == Decimal("70")

    def test_floor_and_cap_clamps_both_sides(self, released):
        rule = PriceModeRule(mode="FLOOR_AND_CAP", floor_eur_mwh=20.0,
                             cap_eur_mwh=80.0)
        assert resolve_market_mode_price(rule, 5.0) == Decimal("20")
        assert resolve_market_mode_price(rule, 50.0) == Decimal("50")
        assert resolve_market_mode_price(rule, 120.0) == Decimal("80")

    def test_missing_market_evidence_is_none_never_zero(self, released):
        for mode, kw in (("MARKET_FLOOR", {"floor_eur_mwh": 20.0}),
                         ("MARKET_CAP", {"cap_eur_mwh": 80.0}),
                         ("FLOOR_AND_CAP", {"floor_eur_mwh": 20.0,
                                            "cap_eur_mwh": 80.0})):
            assert resolve_market_mode_price(PriceModeRule(mode=mode, **kw), None) is None

    def test_malformed_market_evidence_fails_closed_never_missing(self, released):
        rule = PriceModeRule(mode="MARKET_FLOOR", floor_eur_mwh=20.0)
        for bad in (float("nan"), float("inf"), float("-inf"), True, False,
                    "banana", "10", [10.0], Decimal("10")):
            with pytest.raises(ValueError, match="REVENUE_V4_VALUE"):
                resolve_market_mode_price(rule, bad)

    def test_cap_mode_passes_negative_market_through_typed(self, released):
        """MARKET_CAP without a floor does not invent a price floor; the
        negative-price settlement question stays with the NPH policy and
        owner decision D-05 (production still fails closed upstream)."""
        rule = PriceModeRule(mode="MARKET_CAP", cap_eur_mwh=80.0)
        assert resolve_market_mode_price(rule, -3.0) == Decimal("-3")


# ── Route-to-market fee ──────────────────────────────────────────────────────


class TestRouteToMarketFee:
    def test_eur_per_mwh_fee_without_escalation(self, released):
        fee = RouteToMarketFee(fee_basis="EUR_PER_MWH", fee_value=1.5)
        net = apply_route_to_market_fee(fee, delivered_mwh=1000.0,
                                        gross_revenue_eur=Decimal("40000"),
                                        completed_reviews=0)
        assert net == Decimal("40000") - Decimal("1500.0")

    def test_percent_of_revenue_fee(self, released):
        fee = RouteToMarketFee(fee_basis="PERCENT_OF_REVENUE", fee_value=0.05)
        net = apply_route_to_market_fee(fee, delivered_mwh=1000.0,
                                        gross_revenue_eur=Decimal("40000"),
                                        completed_reviews=0)
        assert net == Decimal("38000.000")

    def test_up_only_escalation_counts_completed_reviews(self, released):
        assert completed_annual_reviews(
            date(2026, 6, 30), date(2025, 3, 15), 1) == 1  # 2026-01-01 only
        assert completed_annual_reviews(
            date(2027, 6, 30), date(2025, 3, 15), 1) == 2
        assert completed_annual_reviews(
            date(2025, 12, 31), date(2025, 3, 15), 1) == 0  # not yet due
        # review exactly on period end counts
        assert completed_annual_reviews(
            date(2026, 1, 1), date(2025, 3, 15), 1) == 1
        # reviews before the contract start never count
        assert completed_annual_reviews(
            date(2026, 6, 30), date(2026, 3, 15), 1) == 0

    def test_review_month_first_of_month_boundary_semantics(self, released):
        # a December review month: review lands on Dec 1 each year
        assert completed_annual_reviews(
            date(2025, 11, 30), date(2025, 1, 15), 12) == 0
        assert completed_annual_reviews(
            date(2025, 12, 1), date(2025, 1, 15), 12) == 1
        # a January review month with a mid-January start: the 2025 review
        # (Jan 1) is NOT strictly after the start; 2026-01-01 is the first
        assert completed_annual_reviews(
            date(2025, 12, 31), date(2025, 1, 15), 1) == 0
        assert completed_annual_reviews(
            date(2026, 1, 1), date(2025, 1, 15), 1) == 1

    def test_escalated_fee_compounds_exactly(self, released):
        fee = RouteToMarketFee(fee_basis="EUR_PER_MWH", fee_value=1.0,
                               escalation_rate=0.10,
                               escalation_timing="ANNUAL_REVIEW",
                               review_month=1)
        net = apply_route_to_market_fee(fee, delivered_mwh=1000.0,
                                        gross_revenue_eur=Decimal("100000"),
                                        completed_reviews=2)
        # 1.0 × 1.1² = 1.21 EUR/MWh → 1210 EUR charge
        assert net == Decimal("100000") - Decimal("1210.000000")

    def test_fee_exceeding_revenue_fails_closed(self, released):
        fee = RouteToMarketFee(fee_basis="PERCENT_OF_REVENUE", fee_value=1.0,
                               escalation_rate=0.5,
                               escalation_timing="ANNUAL_REVIEW",
                               review_month=1)
        with pytest.raises(ValueError, match="exceeds gross revenue"):
            apply_route_to_market_fee(fee, delivered_mwh=10.0,
                                      gross_revenue_eur=Decimal("100"),
                                      completed_reviews=1)  # 150% charge

    def test_period_end_before_start_fails_closed(self, released):
        with pytest.raises(ValueError, match="precedes"):
            completed_annual_reviews(date(2025, 1, 1), date(2026, 1, 1), 1)


# ── Composition + deterministic serialization ────────────────────────────────


class TestCompositionAndSerialization:
    def _book(self):
        return AdvancedRevenueV4Candidate(
            streams=(
                StreamCandidate(
                    stream_id="ppa-2026",
                    source_ref="unit-test",
                    contracted_volume=ContractedVolume(
                        mode="FIXED_ANNUAL_MWH", fixed_annual_mwh=120000.0),
                    price_mode=PriceModeRule(mode="MARKET_FLOOR",
                                             floor_eur_mwh=18.0),
                    route_to_market=RouteToMarketFee(
                        fee_basis="EUR_PER_MWH", fee_value=0.8,
                        escalation_rate=0.02,
                        escalation_timing="ANNUAL_REVIEW", review_month=4),
                ),
                StreamCandidate(
                    stream_id="merchant",
                    negative_price_hours=NegativePriceHoursPolicy(
                        scope="SINGLE_STREAM", action="NO_SETTLEMENT",
                        stream_id="merchant"),
                ),
            ))

    def test_valid_book_round_trips_canonically(self, released):
        book = self._book()
        canonical = book.canonical_json()
        parsed = parse_candidate(book.to_payload())
        assert parsed.canonical_json() == canonical
        # inside the isolated acceptance fixture the marker is explicit
        assert '"activation":"ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"' in canonical

    def test_closed_gate_marks_the_payload_release_closed(self):
        assert '"activation":"RELEASE_CLOSED"' in self._book().canonical_json()

    def test_canonical_json_is_key_order_independent(self, released):
        import json
        book = self._book()
        canonical = book.canonical_json()
        payload = book.to_payload()
        reordered = json.loads(json.dumps(payload))
        reordered["streams"] = list(reversed(reordered["streams"]))
        assert parse_candidate(reordered).canonical_json() == canonical

    def test_unknown_candidate_schema_fails_closed(self, released):
        payload = self._book().to_payload()
        payload["_schema"] = "finco.revenue-v5-candidate"
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            parse_candidate(payload)

    def test_activation_marker_reflects_isolated_enablement(self, released, monkeypatch):
        import app.revenue_v4_candidate.contracts as contracts
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)
        marker = self._book().to_payload()["activation"]
        assert marker == "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"


# ── Correction D: sharing semantics, fail-closed parsing, identity, evidence ─


class TestRevenueSharingIsNotSilentlyAccepted:
    """The earlier ``market_price x project_share`` arithmetic is a market
    revenue participation; Harvest V4 describes sharing of the contractual-vs-
    market DIFFERENCE. No formula is approved, so no result may be produced."""

    SHARING = {"mode": "REVENUE_SHARING", "project_share": 0.7}

    def test_rule_validation_rejects_sharing(self, released):
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            PriceModeRule(mode="REVENUE_SHARING", project_share=0.7).validate()

    def test_resolution_never_returns_a_sharing_number(self, released):
        rule = PriceModeRule(mode="REVENUE_SHARING", project_share=0.7)
        for market in (100.0, -3.0, 0.0, None, float("nan")):
            with pytest.raises(ValueError):
                resolve_market_mode_price(rule, market)

    def test_stream_and_book_parsing_reject_sharing(self, released):
        stream = {"stream_id": "s1", "price_mode": self.SHARING}
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            parse_stream_candidate(stream)
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            parse_candidate({**IDENT, "streams": [stream]})

    def test_a_book_holding_a_sharing_rule_cannot_be_serialized(self, released):
        book = AdvancedRevenueV4Candidate(streams=(StreamCandidate(
            stream_id="s1",
            price_mode=PriceModeRule(mode="REVENUE_SHARING", project_share=0.7)),))
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            book.canonical_json()

    def test_project_share_is_rejected_in_every_supported_mode(self, released):
        for raw in ({"mode": "FIXED", "fixed_price_eur_mwh": 1.0},
                    {"mode": "MARKET_FLOOR", "floor_eur_mwh": 1.0},
                    {"mode": "MARKET_CAP", "cap_eur_mwh": 1.0},
                    {"mode": "FLOOR_AND_CAP", "floor_eur_mwh": 1.0, "cap_eur_mwh": 2.0}):
            with pytest.raises(ValueError, match="must not carry"):
                parse_price_mode({**raw, "project_share": 0.7})

    def test_the_decision_packet_records_the_open_sharing_formula(self):
        import pathlib
        packet = pathlib.Path("docs/model_v2/REVENUE_V4_CANDIDATE_OWNER_DECISION_PACKET.md").read_text(encoding="utf-8")
        assert "D-10" in packet and "REVENUE_SHARING" in packet


class TestParsingDoesNotRepairMalformedValues:
    BASE = {"fee_basis": "EUR_PER_MWH", "fee_value": 1.0}

    def test_absent_optional_fields_take_the_documented_defaults(self, released):
        fee = parse_route_to_market(dict(self.BASE))
        assert fee.escalation_rate == 0.0 and fee.escalation_timing == "NO_ESCALATION"

    def test_explicit_zero_escalation_rate_is_legitimate(self, released):
        assert parse_route_to_market({**self.BASE, "escalation_rate": 0}).escalation_rate == 0.0

    @pytest.mark.parametrize("bad", ["", False, True, None, "0.1", [], {}])
    def test_malformed_escalation_rate_is_rejected(self, released, bad):
        with pytest.raises(ValueError, match="REVENUE_V4_VALUE"):
            parse_route_to_market({**self.BASE, "escalation_rate": bad})

    @pytest.mark.parametrize("bad", ["", False, 0, None, "annual_review", ["ANNUAL_REVIEW"]])
    def test_malformed_escalation_timing_is_rejected(self, released, bad):
        with pytest.raises(ValueError, match="REVENUE_V4_UNSUPPORTED"):
            parse_route_to_market({**self.BASE, "escalation_timing": bad})

    def test_source_ref_default_only_when_absent(self, released):
        stream = {"stream_id": "s1", "price_mode": {"mode": "FIXED", "fixed_price_eur_mwh": 1.0}}
        assert parse_stream_candidate(dict(stream)).source_ref == ""
        assert parse_stream_candidate({**stream, "source_ref": ""}).source_ref == ""
        assert parse_stream_candidate({**stream, "source_ref": "doc-1"}).source_ref == "doc-1"

    @pytest.mark.parametrize("bad", [0, False, True, None, [], {}, 5])
    def test_malformed_source_ref_is_rejected_not_defaulted(self, released, bad):
        stream = {"stream_id": "s1", "source_ref": bad,
                  "price_mode": {"mode": "FIXED", "fixed_price_eur_mwh": 1.0}}
        with pytest.raises(ValueError, match="source_ref must be a string"):
            parse_stream_candidate(stream)


class TestCandidateSchemaIdentity:
    def _payload(self):
        return AdvancedRevenueV4Candidate(streams=(StreamCandidate(
            stream_id="s1", price_mode=PriceModeRule(
                mode="FIXED", fixed_price_eur_mwh=1.0)),)).to_payload()

    def test_valid_serialized_identity_is_accepted(self, released):
        assert parse_candidate(self._payload()).canonical_json()
        closed = {**self._payload(), "activation": "RELEASE_CLOSED"}
        assert parse_candidate(closed).canonical_json()

    @pytest.mark.parametrize("key", ["_schema", "schema_version", "activation"])
    def test_missing_identity_marker_is_rejected(self, released, key):
        payload = self._payload()
        del payload[key]
        with pytest.raises(ValueError, match="REVENUE_V4_(UNSUPPORTED|SCHEMA)"):
            parse_candidate(payload)

    @pytest.mark.parametrize("bad", [0, 2, -1, True, False, 1.0, "1", None, [1]])
    def test_unsupported_schema_version_is_rejected(self, released, bad):
        payload = {**self._payload(), "schema_version": bad}
        with pytest.raises(ValueError, match="schema_version"):
            parse_candidate(payload)

    @pytest.mark.parametrize("bad", ["ACTIVE", "ENABLED", "PRODUCTION", "released",
                                     "", None, True, 1, ["RELEASE_CLOSED"]])
    def test_misleading_activation_marker_is_rejected(self, released, bad):
        payload = {**self._payload(), "activation": bad}
        with pytest.raises(ValueError, match="activation marker"):
            parse_candidate(payload)

    def test_isolated_enablement_claim_requires_an_open_gate(self, released, monkeypatch):
        import app.revenue_v4_candidate.contracts as contracts
        payload = {**self._payload(), "activation": "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"}
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", False)
        with pytest.raises(ValueError, match="misleading activation marker"):
            contracts._require_candidate_identity(payload)

    def test_a_payload_marker_can_never_open_the_gate(self):
        """No fixture: the gate is closed and an ENABLED-claiming payload still
        cannot be parsed, so a marker is descriptive and never an activation."""
        payload = {**TestCandidateSchemaIdentity._payload(None),
                   "activation": "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"}
        with pytest.raises(ValueError, match="REVENUE_V4_RELEASE_CLOSED"):
            parse_candidate(payload)
        assert ACTIVATION_ENABLED is False


class TestMissingVersusMalformedEvidence:
    def test_bucket_inputs_reject_booleans_consistently(self, released):
        policy = NegativePriceHoursPolicy(scope="PLANT", action="NO_SETTLEMENT")
        good = dict(negative_mwh=10.0, negative_price_eur_mwh=-1.0,
                    nonnegative_mwh=90.0, nonnegative_price_eur_mwh=40.0)
        for field in good:
            for bad in (True, False, "1", None):
                with pytest.raises(ValueError, match="REVENUE_V4_VALUE"):
                    apply_negative_price_policy(policy, **{**good, field: bad})

    def test_bucket_negative_price_must_not_be_positive_or_non_finite(self, released):
        policy = NegativePriceHoursPolicy(scope="PLANT", action="CURTAIL")
        for bad in (1.0, float("nan"), float("-inf")):
            with pytest.raises(ValueError, match="REVENUE_V4_VALUE"):
                apply_negative_price_policy(
                    policy, negative_mwh=1.0, negative_price_eur_mwh=bad,
                    nonnegative_mwh=1.0, nonnegative_price_eur_mwh=1.0)

    def test_zero_is_valid_evidence_not_missing(self, released):
        rule = PriceModeRule(mode="MARKET_FLOOR", floor_eur_mwh=0.0)
        assert resolve_market_mode_price(rule, 0.0) == Decimal("0")
        assert resolve_market_mode_price(rule, 0) == Decimal("0")


# ── Isolation: the candidate is invisible to the production path ─────────────


class TestProductionIsolation:
    def test_no_production_module_imports_the_candidate(self, released):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import json, pathlib, sys\n"
             "roots = ['app', 'domain', 'financial_engine', 'finco_core', 'main_web.py']\n"
             "bad = []\n"
             "for root in roots:\n"
             "    p = pathlib.Path(root)\n"
             "    files = [p] if p.is_file() else sorted(p.rglob('*.py'))\n"
             "    for f in files:\n"
             "        try:\n"
             "            t = f.read_text(encoding='utf-8')\n"
             "        except Exception:\n"
             "            continue\n"
             "        if 'revenue_v4_candidate' in t:\n"
             "            bad.append(str(f))\n"
             "print(json.dumps(bad))"],
            cwd=".", capture_output=True, text=True)
        import json
        referers = json.loads(result.stdout.strip())
        own = {r for r in referers if r.startswith("app/revenue_v4_candidate") or r.startswith("app\\revenue_v4_candidate")}
        assert set(referers) == own, f"production files reference the candidate: {sorted(set(referers) - own)}"
