"""FINCO Radar P2 — Tokenization Premium + Execution Gap engine tests.

Covers:
- Section T suppression matrix (12 typed states)
- Section J numeric fixture (underlying=100, token_ref=102, buy=102.50, sell=101.50)
- Section U: reference premium survives when execution unavailable
- Mutation/adversarial guards

This is NOT a trading system.  No BUY/SELL/ARBITRAGE/OPPORTUNITY labels.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from finco_radar.tokenization_premium.contracts import (
    TokenizationPremiumObservation,
    TokenizationPremiumPolicy,
    TokenizationPremiumStatus,
)
from finco_radar.tokenization_premium.engine import compute_tokenization_premium

_POLICY = TokenizationPremiumPolicy(max_evidence_skew_seconds=300)

_T0 = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 9, 26, 12, 1, 0, tzinfo=timezone.utc)  # +60s
_T_STALE = datetime(2026, 9, 26, 11, 54, 0, tzinfo=timezone.utc)  # -6 min from T0


def _ref(
    *,
    available: bool = True,
    raw_bid: str = "100.00",
    raw_ask: str = "100.00",
    multiplier: str = "1.02",
    bid: str = "102.00",
    ask: str = "102.00",
    price: str = "102.00",
    observed_at: str | None = None,
    is_trading_halt: bool = False,
    unavailable_reason: str | None = None,
) -> dict:
    if not available:
        return {"available": False, "unavailableReason": unavailable_reason or "UNAVAILABLE"}
    return {
        "available": True,
        "rawBid": raw_bid,
        "rawAsk": raw_ask,
        "currentMultiplier": multiplier,
        "bid": bid,
        "ask": ask,
        "price": price,
        "observedAt": observed_at or _T0.isoformat(),
        "isTradingHalt": is_trading_halt,
    }


def _exec(
    *,
    available: bool = True,
    effective_price: str | None = "102.50",
    quoted_at: str | None = None,
    status: str = "QUOTE_OK",
) -> dict:
    if not available:
        return {"available": False, "status": status}
    return {
        "available": True,
        "effectivePrice": effective_price,
        "quotedAt": quoted_at or _T1.isoformat(),
        "status": status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section J numeric fixture
# underlying=100, token_ref=102, buy_exec=102.50, sell_exec=101.50
# reference_premium = ((102/100) - 1) × 10000 = +200 bps
# buy_exec_premium  = ((102.50/100) - 1) × 10000 = +250 bps
# sell_exec_premium = ((101.50/100) - 1) × 10000 = +150 bps
# buy_exec_gap  = 250 - 200 = +50 bps
# sell_exec_gap = 150 - 200 = -50 bps
# ─────────────────────────────────────────────────────────────────────────────

class TestSectionJNumericFixture:
    def test_reference_premium_200bps(self):
        ref = _ref(raw_bid="100", raw_ask="100", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
        assert obs.reference_premium_bps == Decimal("200")

    def test_buy_execution_gap_plus_50bps(self):
        ref = _ref(raw_bid="100", raw_ask="100", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.buy_execution_gap_bps == Decimal("50")

    def test_sell_execution_gap_minus_50bps(self):
        ref = _ref(raw_bid="100", raw_ask="100", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.sell_execution_gap_bps == Decimal("-50")

    def test_buy_execution_premium_250bps(self):
        ref = _ref(raw_bid="100", raw_ask="100", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.buy_execution_premium_bps == Decimal("250")

    def test_sell_execution_premium_150bps(self):
        ref = _ref(raw_bid="100", raw_ask="100", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.sell_execution_premium_bps == Decimal("150")

    def test_underlying_mid_preserved(self):
        ref = _ref(raw_bid="99", raw_ask="101", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.underlying_raw_mid_usd_per_share == Decimal("100")


# ─────────────────────────────────────────────────────────────────────────────
# Section T suppression matrix — 12 typed states
# ─────────────────────────────────────────────────────────────────────────────

class TestSuppressionMatrix:

    # 1. TOKENIZATION_PREMIUM_OK
    def test_state_1_premium_ok(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
        assert obs.suppression_reason is None

    # 2. REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE
    def test_state_2_ref_ok_exec_unavailable(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE
        assert obs.reference_premium_bps is not None
        assert obs.buy_execution_gap_bps is None
        assert obs.sell_execution_gap_bps is None

    def test_state_2_via_unavailable_exec_dicts(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(available=False),
            sell_exec_evidence=_exec(available=False),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE

    # 3. UNDERLYING_REFERENCE_INVALID — reference not available
    def test_state_3_reference_unavailable(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(available=False),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_state_3_missing_raw_bid(self):
        ref = _ref()
        del ref["rawBid"]
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_state_3_negative_raw_bid(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="-1"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_state_3_ask_less_than_bid(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="105", raw_ask="100"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_state_3_non_numeric_raw_ask(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_ask="N/A"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_state_3_empty_reference(self):
        obs = compute_tokenization_premium(
            reference_evidence={},
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    # 4. UNDERLYING_REFERENCE_STALE — handled via TIME_COHERENCE_VIOLATION
    # (the engine uses TIME_COHERENCE_VIOLATION for timestamp skew; UNDERLYING_REFERENCE_STALE
    # is available for use by callers who detect reference-specific staleness before calling)

    # 5. TOKEN_EXECUTION_UNAVAILABLE — execution dict available but effectivePrice invalid
    def test_state_5_invalid_effective_price(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="not-a-number"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_state_5_none_effective_price_treated_as_unavailable(self):
        # effectivePrice=None with available=True → treated as not available
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price=None),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        # Both directions unavailable → REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE
        assert obs.status is TokenizationPremiumStatus.REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE

    # 6. CORPORATE_ACTION_UNMIRRORED — not raised by engine directly;
    #    contract status exists for callers to set; engine produces reference result.

    # 7. TRADING_HALTED
    def test_state_7_trading_halt(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(is_trading_halt=True),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TRADING_HALTED
        assert obs.reference_premium_bps is None

    # 8. CURRENCY_MISMATCH — not raised by engine (raw reference fields are pre-parsed);
    #    contract status exists for callers.

    # 9. MULTIPLIER_TRANSITION_UNRESOLVED — not raised by engine directly;
    #    contract status exists for callers.

    # 10. TIME_COHERENCE_VIOLATION
    def test_state_10_time_coherence_violation(self):
        strict_policy = TokenizationPremiumPolicy(max_evidence_skew_seconds=30)
        far_future = datetime(2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc)  # +2h
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at=_T0.isoformat()),
            buy_exec_evidence=_exec(quoted_at=far_future.isoformat()),
            sell_exec_evidence=None,
            policy=strict_policy,
        )
        assert obs.status is TokenizationPremiumStatus.TIME_COHERENCE_VIOLATION

    def test_state_10_within_policy_passes(self):
        tight_policy = TokenizationPremiumPolicy(max_evidence_skew_seconds=300)
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at=_T0.isoformat()),
            buy_exec_evidence=_exec(quoted_at=_T1.isoformat()),  # +60s
            sell_exec_evidence=None,
            policy=tight_policy,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK

    # 11. IDENTITY_BINDING_MISSING — not raised by engine directly;
    #     contract status exists for callers.

    # 12. EXECUTION_QUOTE_STALE — TIME_COHERENCE_VIOLATION covers this numerically.
    def test_state_12_execution_quote_stale_via_time_coherence(self):
        strict_policy = TokenizationPremiumPolicy(max_evidence_skew_seconds=60)
        far_past_exec = datetime(2026, 9, 26, 11, 0, 0, tzinfo=timezone.utc)  # -1h
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at=_T0.isoformat()),
            buy_exec_evidence=_exec(quoted_at=far_past_exec.isoformat()),
            sell_exec_evidence=None,
            policy=strict_policy,
        )
        assert obs.status is TokenizationPremiumStatus.TIME_COHERENCE_VIOLATION


# ─────────────────────────────────────────────────────────────────────────────
# Section U: Reference premium survives if execution unavailable
# ─────────────────────────────────────────────────────────────────────────────

class TestSectionU:
    def test_reference_premium_available_when_buy_exec_only(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100",
                                    multiplier="1.02", bid="102", ask="102", price="102"),
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
        assert obs.reference_premium_bps == Decimal("200")
        assert obs.buy_execution_gap_bps == Decimal("50")
        assert obs.sell_execution_gap_bps is None

    def test_reference_premium_available_when_sell_exec_only(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100",
                                    multiplier="1.02", bid="102", ask="102", price="102"),
            buy_exec_evidence=None,
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
        assert obs.reference_premium_bps == Decimal("200")
        assert obs.buy_execution_gap_bps is None
        assert obs.sell_execution_gap_bps == Decimal("-50")

    def test_reference_premium_when_both_exec_unavailable(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100",
                                    multiplier="1.02", bid="102", ask="102", price="102"),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE
        assert obs.reference_premium_bps == Decimal("200")
        assert obs.reference_premium_available()

    def test_is_ok_false_when_execution_unavailable(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert not obs.is_ok()
        assert obs.reference_premium_available()


# ─────────────────────────────────────────────────────────────────────────────
# Adversarial / mutation tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAdversarial:
    def test_policy_must_be_positive(self):
        with pytest.raises(ValueError, match="max_evidence_skew_seconds must be positive"):
            TokenizationPremiumPolicy(max_evidence_skew_seconds=0)

    def test_policy_negative_raises(self):
        with pytest.raises(ValueError):
            TokenizationPremiumPolicy(max_evidence_skew_seconds=-1)

    def test_zero_underlying_raises_underlying_invalid(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="0", raw_ask="0"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_non_finite_exec_price(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="Infinity"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_negative_exec_price(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="-1"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_naive_datetime_in_reference_raises(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at="2026-09-26T12:00:00"),  # no tz
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_observation_is_frozen(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        with pytest.raises((AttributeError, TypeError)):
            obs.reference_premium_bps = Decimal("999")  # type: ignore[misc]

    def test_numeric_precision_preserved(self):
        # No rounding in engine — exact arithmetic
        ref = _ref(raw_bid="99.99", raw_ask="100.01", multiplier="1.02",
                   bid="102", ask="102", price="102")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        # underlying_mid = (99.99 + 100.01) / 2 = 100.00
        assert obs.underlying_raw_mid_usd_per_share == Decimal("100.00")

    def test_reference_evidence_dict_not_mutated(self):
        ref = _ref()
        original_keys = set(ref.keys())
        compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert set(ref.keys()) == original_keys

    def test_invalid_iso_timestamp_in_exec(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(quoted_at="not-a-date"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_halted_overrides_execution_availability(self):
        # Even if execution is present, TRADING_HALTED wins
        obs = compute_tokenization_premium(
            reference_evidence=_ref(is_trading_halt=True),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TRADING_HALTED
        assert obs.buy_execution_gap_bps is None
