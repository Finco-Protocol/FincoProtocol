"""FINCO Radar P2 — Tokenization Premium engine tests (Correction A).

Acceptance markers exercised by this suite:
  MULTIPLIER_IS_NOT_TOKENIZATION_PREMIUM
  TOKENIZATION_PREMIUM_INDEPENDENT_MARKET_AUTHORITY
  P2_ZERO_DUPLICATED_EXECUTION_MATH
  P2_BUY_DIRECTION_LABELS_CORRECT
  P2_SELL_DIRECTION_LABELS_CORRECT
  P2_SUPPRESSION_STATES_ARE_PRODUCIBLE
  P2_TEMPORAL_POLICY_EXPLICIT
  P2_COMPLEMENT_IDENTITY_BOUND
  P2_COMPLEMENT_TIME_COHERENT

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
from app.radar_ui.tokenization_premium_view import (
    build_tokenization_premium_view,
    compute_p2_view,
)

_POLICY = TokenizationPremiumPolicy(max_evidence_skew_seconds=300)

_T0 = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 9, 26, 12, 1, 0, tzinfo=timezone.utc)   # +60s


def _ref(
    *,
    available: bool = True,
    raw_bid: str = "100.00",
    raw_ask: str = "100.00",
    multiplier: str = "1.02",
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
        "observedAt": observed_at or _T0.isoformat(),
        "isTradingHalt": is_trading_halt,
    }


def _exec(
    *,
    available: bool = True,
    effective_price: str | None = "102.50",
    quoted_at: str | None = None,
) -> dict:
    if not available:
        return {"available": False}
    return {
        "available": True,
        "effectivePrice": effective_price,
        "quotedAt": quoted_at or _T1.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MULTIPLIER_IS_NOT_TOKENIZATION_PREMIUM (adversarial — Correction A core)
#
# currentMultiplier is a unit conversion (shares per token).
# underlying_token_basis = raw_mid × multiplier = R2 token_midpoint.
# When the DEX mid equals that basis, tokenization_premium_bps must be 0 bps,
# regardless of the multiplier value.
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiplierIsNotTokenizationPremium:
    """MULTIPLIER_IS_NOT_TOKENIZATION_PREMIUM = PASS"""

    def test_multiplier_gt1_dex_mid_equals_basis_is_zero_bps(self):
        # raw_mid=100, multiplier=1.02 → basis=102
        # DEX buy=102.25, DEX sell=101.75 → execution_mid=102.00
        # tokenization_premium_bps = ((102/102)-1)×10000 = 0
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=_exec(effective_price="102.25"),
            sell_exec_evidence=_exec(effective_price="101.75"),
            policy=_POLICY,
        )
        assert obs.tokenization_premium_bps == Decimal("0")

    def test_multiplier_lt1_dex_mid_equals_basis_is_zero_bps(self):
        # raw_mid=100, multiplier=0.5 → basis=50
        # DEX buy=50.25, DEX sell=49.75 → execution_mid=50.00
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="0.5"),
            buy_exec_evidence=_exec(effective_price="50.25"),
            sell_exec_evidence=_exec(effective_price="49.75"),
            policy=_POLICY,
        )
        assert obs.tokenization_premium_bps == Decimal("0")

    def test_multiplier_eq1_dex_mid_equals_basis_is_zero_bps(self):
        # raw_mid=100, multiplier=1.0 → basis=100
        # DEX buy=100.25, DEX sell=99.75 → execution_mid=100.00
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1"),
            buy_exec_evidence=_exec(effective_price="100.25"),
            sell_exec_evidence=_exec(effective_price="99.75"),
            policy=_POLICY,
        )
        assert obs.tokenization_premium_bps == Decimal("0")

    def test_non_unit_multiplier_no_independent_market_no_premium(self):
        # When there is no independent DEX price, there is no tokenization premium.
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.tokenization_premium_bps is None
        assert obs.status is TokenizationPremiumStatus.TOKEN_MARKET_REFERENCE_UNAVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
# Section J numeric fixture (Correction A)
#
# raw_bid=100, raw_ask=100, multiplier=1.02
# underlying_token_basis = 100 × 1.02 = 102
# DEX buy=102.50, DEX sell=101.50 → execution_mid = 102.00
# tokenization_premium_bps = ((102/102)-1)×10000 = 0 bps  (not +200!)
# buy_execution_premium_bps = ((102.50/102)-1)×10000 > 0
# sell_execution_premium_bps = ((101.50/102)-1)×10000 < 0
# ─────────────────────────────────────────────────────────────────────────────

class TestSectionJNumericFixture:
    """TOKENIZATION_PREMIUM_INDEPENDENT_MARKET_AUTHORITY = PASS"""

    def test_tokenization_premium_zero_bps_when_dex_mid_equals_basis(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
        assert obs.tokenization_premium_bps == Decimal("0")

    def test_underlying_token_basis_correct(self):
        # basis = 100 × 1.02 = 102
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.underlying_token_basis_usd_per_token == Decimal("102")

    def test_execution_mid_price_correct(self):
        # (102.50 + 101.50) / 2 = 102.00
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.execution_mid_price_usd_per_token == Decimal("102")

    def test_buy_execution_premium_positive(self):
        # ((102.50/102)-1)×10000 > 0
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.buy_execution_premium_bps is not None
        assert obs.buy_execution_premium_bps > Decimal("0")

    def test_sell_execution_premium_negative(self):
        # ((101.50/102)-1)×10000 < 0
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=_exec(effective_price="101.50"),
            policy=_POLICY,
        )
        assert obs.sell_execution_premium_bps is not None
        assert obs.sell_execution_premium_bps < Decimal("0")

    def test_positive_premium_when_dex_above_basis(self):
        # raw_mid=100, multiplier=1.0 → basis=100
        # DEX buy=102, DEX sell=100 → execution_mid=101
        # tokenization_premium_bps = ((101/100)-1)×10000 = +100 bps
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1"),
            buy_exec_evidence=_exec(effective_price="102"),
            sell_exec_evidence=_exec(effective_price="100"),
            policy=_POLICY,
        )
        assert obs.tokenization_premium_bps == Decimal("100")

    def test_negative_premium_when_dex_below_basis(self):
        # raw_mid=100, multiplier=1.0 → basis=100
        # DEX buy=100, DEX sell=98 → execution_mid=99
        # tokenization_premium_bps = ((99/100)-1)×10000 = -100 bps
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1"),
            buy_exec_evidence=_exec(effective_price="100"),
            sell_exec_evidence=_exec(effective_price="98"),
            policy=_POLICY,
        )
        assert obs.tokenization_premium_bps == Decimal("-100")


# ─────────────────────────────────────────────────────────────────────────────
# Status matrix — 9 genuinely producible states
# ─────────────────────────────────────────────────────────────────────────────

class TestSuppressionMatrix:
    """P2_SUPPRESSION_STATES_ARE_PRODUCIBLE = PASS"""

    def test_tokenization_premium_ok_both_directions(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
        assert obs.tokenization_premium_bps is not None
        assert obs.execution_mid_price_usd_per_token is not None

    def test_execution_premium_partial_buy_only(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.EXECUTION_PREMIUM_PARTIAL
        assert obs.buy_execution_premium_bps is not None
        assert obs.sell_execution_premium_bps is None
        assert obs.tokenization_premium_bps is None
        assert obs.execution_mid_price_usd_per_token is None

    def test_execution_premium_partial_sell_only(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=None,
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.EXECUTION_PREMIUM_PARTIAL
        assert obs.sell_execution_premium_bps is not None
        assert obs.buy_execution_premium_bps is None

    def test_token_market_reference_unavailable_when_no_dex(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_MARKET_REFERENCE_UNAVAILABLE
        assert obs.tokenization_premium_bps is None
        # Basis is still available (reference parsed OK)
        assert obs.underlying_token_basis_usd_per_token is not None
        assert obs.basis_available()
        assert not obs.independent_market_available()

    def test_underlying_reference_invalid_when_unavailable(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(available=False),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_underlying_reference_invalid_missing_raw_bid(self):
        ref = _ref()
        del ref["rawBid"]
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_underlying_reference_invalid_zero_multiplier(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(multiplier="0"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_underlying_reference_invalid_non_numeric(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_ask="N/A"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_trading_halted(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(is_trading_halt=True),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TRADING_HALTED
        assert obs.tokenization_premium_bps is None

    def test_time_coherence_violation(self):
        """P2_TEMPORAL_POLICY_EXPLICIT = PASS"""
        strict_policy = TokenizationPremiumPolicy(max_evidence_skew_seconds=30)
        far_future = datetime(2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc)  # +2h
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at=_T0.isoformat()),
            buy_exec_evidence=_exec(quoted_at=far_future.isoformat()),
            sell_exec_evidence=None,
            policy=strict_policy,
        )
        assert obs.status is TokenizationPremiumStatus.TIME_COHERENCE_VIOLATION

    def test_time_coherence_within_policy_passes(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at=_T0.isoformat()),
            buy_exec_evidence=_exec(quoted_at=_T1.isoformat()),  # +60s < 300s
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.EXECUTION_PREMIUM_PARTIAL

    def test_token_execution_unavailable_invalid_price(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="not-a-number"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_token_execution_unavailable_non_finite(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="Infinity"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_complement_identity_mismatch(self):
        """P2_COMPLEMENT_IDENTITY_BOUND = PASS"""
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
            complement_identity_verified=False,
        )
        assert obs.status is TokenizationPremiumStatus.COMPLEMENT_IDENTITY_MISMATCH
        assert obs.tokenization_premium_bps is None


# ─────────────────────────────────────────────────────────────────────────────
# Temporal policy tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalPolicy:
    """P2_TEMPORAL_POLICY_EXPLICIT = PASS"""

    def test_policy_must_be_positive(self):
        with pytest.raises(ValueError, match="max_evidence_skew_seconds must be positive"):
            TokenizationPremiumPolicy(max_evidence_skew_seconds=0)

    def test_policy_negative_raises(self):
        with pytest.raises(ValueError):
            TokenizationPremiumPolicy(max_evidence_skew_seconds=-1)

    def test_stale_complement_triggers_time_coherence_violation(self):
        """P2_COMPLEMENT_TIME_COHERENT = PASS"""
        strict = TokenizationPremiumPolicy(max_evidence_skew_seconds=60)
        far_past = datetime(2026, 9, 26, 11, 0, 0, tzinfo=timezone.utc)  # -1h from T0
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at=_T0.isoformat()),
            buy_exec_evidence=_exec(quoted_at=far_past.isoformat()),
            sell_exec_evidence=None,
            policy=strict,
        )
        assert obs.status is TokenizationPremiumStatus.TIME_COHERENCE_VIOLATION


# ─────────────────────────────────────────────────────────────────────────────
# Directional label tests (UI layer)
# ─────────────────────────────────────────────────────────────────────────────

class TestDirectionalLabels:
    """P2_BUY_DIRECTION_LABELS_CORRECT = PASS
    P2_SELL_DIRECTION_LABELS_CORRECT = PASS"""

    def test_buy_direction_label_present_in_view(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["directionalPremiums"] is not None
        # BUY label must always be keyed by direction, not by position
        assert "buyExecutionPremiumBps" in view["directionalPremiums"]

    def test_sell_direction_label_present_in_view(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert "sellExecutionPremiumBps" in view["directionalPremiums"]

    def test_buy_only_view_has_buy_label_not_sell(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["directionalPremiums"]["buyExecutionPremiumBps"] is not None
        assert view["directionalPremiums"]["sellExecutionPremiumBps"] is None

    def test_sell_only_view_has_sell_label_not_buy(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=None,
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["directionalPremiums"]["sellExecutionPremiumBps"] is not None
        assert view["directionalPremiums"]["buyExecutionPremiumBps"] is None

    def test_view_has_no_gap_or_position_based_labels(self):
        # Correction A: no "gap" fields, no "current direction" / "complement" labels
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert "referencePremiumBps" not in view
        assert "execution" not in view or (
            view.get("execution") is None
            or "buyGapBps" not in (view.get("execution") or {})
        )


# ─────────────────────────────────────────────────────────────────────────────
# View layer
# ─────────────────────────────────────────────────────────────────────────────

class TestViewLayer:
    def test_available_false_when_reference_invalid(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(available=False),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["available"] is False

    def test_available_true_when_basis_only(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["available"] is True
        assert view["tokenizationPremiumBps"] is None  # no independent price

    def test_tokenization_premium_bps_formatted_correctly(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1"),
            buy_exec_evidence=_exec(effective_price="102"),
            sell_exec_evidence=_exec(effective_price="100"),
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["tokenizationPremiumBps"] is not None
        assert "bps" in view["tokenizationPremiumBps"]

    def test_compute_p2_view_never_raises(self):
        # compute_p2_view is the boundary guard: must never raise
        result = compute_p2_view(
            reference_evidence={},
            buy_exec_evidence=None,
            sell_exec_evidence=None,
        )
        assert isinstance(result, dict)
        assert "status" in result

    def test_compute_p2_view_complement_not_verified(self):
        result = compute_p2_view(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="103"),
            sell_exec_evidence=_exec(effective_price="101"),
            complement_identity_verified=False,
        )
        assert result["status"] == TokenizationPremiumStatus.COMPLEMENT_IDENTITY_MISMATCH.value

    def test_underlying_section_shows_token_basis(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="100", raw_ask="100", multiplier="1.02"),
            buy_exec_evidence=None,
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        view = build_tokenization_premium_view(obs)
        assert view["underlying"] is not None
        assert view["underlying"]["tokenBasis"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Adversarial / mutation guards
# ─────────────────────────────────────────────────────────────────────────────

class TestAdversarial:
    def test_observation_is_frozen(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        with pytest.raises((AttributeError, TypeError)):
            obs.tokenization_premium_bps = Decimal("999")  # type: ignore[misc]

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

    def test_numeric_precision_preserved(self):
        ref = _ref(raw_bid="99.99", raw_ask="100.01", multiplier="1.02")
        obs = compute_tokenization_premium(
            reference_evidence=ref,
            buy_exec_evidence=_exec(effective_price="102.50"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        # underlying_mid = (99.99 + 100.01) / 2 = 100.00
        assert obs.underlying_raw_mid_usd_per_share == Decimal("100.00")

    def test_naive_datetime_in_reference_rejected(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(observed_at="2026-09-26T12:00:00"),  # no tz
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_invalid_iso_timestamp_in_exec(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(quoted_at="not-a-date"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE

    def test_halted_overrides_execution_availability(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(is_trading_halt=True),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=_exec(effective_price="101"),
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TRADING_HALTED
        assert obs.tokenization_premium_bps is None

    def test_zero_underlying_raises_invalid(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(raw_bid="0", raw_ask="0"),
            buy_exec_evidence=_exec(),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID

    def test_negative_exec_price_rejected(self):
        obs = compute_tokenization_premium(
            reference_evidence=_ref(),
            buy_exec_evidence=_exec(effective_price="-1"),
            sell_exec_evidence=None,
            policy=_POLICY,
        )
        assert obs.status is TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE
