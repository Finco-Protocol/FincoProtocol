"""Focused, fully offline R4 reference-state tests.

Deterministic fixtures only; no network access. Synthetic market-session
evidence is clearly test-only and never represents real live authority.
Test numbering follows the R4 specification's mandatory coverage list.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    RegistryAssetStatus,
    RegistrySourceError,
)
from finco_radar.gap.contracts import GapComputationError
from finco_radar.gap.engine import build_bound_reference_price
from finco_radar.quotes.contracts import ExecutionQuote, QuoteSide, QuoteStatus, SettlementReference, SettlementReferenceState, AssetRef
from finco_radar.quotes.normalization import quote_size_impact_bps
from finco_radar.gap.engine import compute_directional_gap
from finco_radar.gap.contracts import GapComparisonPolicy
from finco_radar.reference_state.adapters.robinhood import RobinhoodCorporateActionAdapter
from finco_radar.reference_state.contracts import (
    BLOCKING_REASON_PRECEDENCE,
    CorporateActionEvidenceError,
    CorporateActionRow,
    FreshnessState,
    MarketSessionEvidence,
    MarketSessionState,
    ReferenceStateError,
    ReferenceStatePolicy,
    ReferenceStateReason,
    ReferenceStateStatus,
)
from finco_radar.reference_state.engine import (
    build_reference_state_snapshot,
    classify_multiplier,
    match_corporate_actions,
)

UID = "0x" + "11" * 32
TOKEN = "0x" + "aa" * 20
CHAIN = 4663
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

CASH_DIVIDEND = "CORPORATE_ACTION_TYPE_CASH_DIVIDEND"
UNKNOWN_TYPE = "CORPORATE_ACTION_TYPE_FUTURE_THING"
IN_PROGRESS = "CORPORATE_ACTION_STATUS_IN_PROGRESS"
COMPLETED = "CORPORATE_ACTION_STATUS_COMPLETED"


def policy(
    max_live: int = 120,
    session_age: int = 3600,
    skew: int = 5,
) -> ReferenceStatePolicy:
    return ReferenceStatePolicy(
        max_live_reference_age_seconds=max_live,
        max_session_evidence_age_seconds=session_age,
        max_clock_skew_seconds=skew,
    )


def asset(
    status: RegistryAssetStatus = RegistryAssetStatus.ACTIVE,
    *,
    multiplier: str = "1",
    pending: str | None = None,
    effective: datetime | None = None,
) -> CanonicalAssetRecord:
    return CanonicalAssetRecord(
        asset_uid=UID,
        token_symbol="AAA",
        token_name="AAA Token",
        deployments=(AssetKey(CHAIN, TOKEN),),
        current_multiplier=Decimal(multiplier),
        pending_multiplier=Decimal(pending) if pending is not None else None,
        pending_multiplier_effective_at=effective,
        status=status,
    )


def binding() -> ReferenceBinding:
    return ReferenceBinding(asset_uid=UID, asset_key=AssetKey(CHAIN, TOKEN), reference_symbol="AAA")


def price_row(*, generated_at: str = "2026-09-15T12:00:00Z", halt: bool = False) -> dict:
    return {
        "tokenSymbol": "AAA",
        "deployments": [{"chainId": CHAIN, "contractAddress": TOKEN}],
        "bid": "95",
        "ask": "105",
        "currency": "USD",
        "generatedAt": generated_at,
        "isTradingHalt": halt,
    }


def reference(generated_at: datetime = NOW, *, halt: bool = False):
    if generated_at.tzinfo is not None:
        stamp = generated_at.isoformat().replace("+00:00", "Z")
    else:
        # Deliberately produce a naive wire stamp for the boundary test.
        stamp = generated_at.isoformat()
    return build_bound_reference_price(asset(), binding(), price_row(generated_at=stamp, halt=halt))


def session(state: MarketSessionState, observed_at: datetime | None = None) -> MarketSessionEvidence:
    if observed_at is None and state is not MarketSessionState.UNRESOLVED:
        observed_at = NOW
    return MarketSessionEvidence(
        state=state,
        source="SYNTHETIC_TEST_SESSION_AUTHORITY" if state is not MarketSessionState.UNRESOLVED else "NO_SESSION_AUTHORITY_IN_TEST",
        observed_at=observed_at,
    )


def ca_row(
    *,
    uid: str = UID,
    action_type: str = CASH_DIVIDEND,
    status: str = IN_PROGRESS,
    symbol: str = "AAA",
    deployments: tuple[AssetKey, ...] = (AssetKey(CHAIN, TOKEN),),
    process_date: date | None = date(2026, 10, 14),
    details: dict | None = None,
) -> CorporateActionRow:
    if details is None:
        details = {"cashDividend": {"underlyingSymbol": symbol, "rate": "0.33"}}
    return CorporateActionRow(
        action_uid=uid,
        action_type=action_type,
        status=status,
        token_symbol=symbol,
        deployments=deployments,
        process_date=process_date,
        details=details,
        known_type=action_type in {
            "CORPORATE_ACTION_TYPE_FORWARD_SPLIT",
            "CORPORATE_ACTION_TYPE_REVERSE_SPLIT",
            CASH_DIVIDEND,
            "CORPORATE_ACTION_TYPE_STOCK_DIVIDEND",
        },
        known_status=status in {IN_PROGRESS, COMPLETED},
        raw_evidence={"id": uid, "type": action_type, "status": status},
    )


def matches(rows: list[CorporateActionRow], asset_record=None):
    asset_record = asset_record or asset()
    return match_corporate_actions(rows, asset=asset_record, asset_key=AssetKey(CHAIN, TOKEN))


def build(
    *,
    asset_record: CanonicalAssetRecord | None = None,
    ref=None,
    rows: list[CorporateActionRow] | None = None,
    session_evidence: MarketSessionEvidence | None = None,
    as_of: datetime = NOW + timedelta(seconds=60),
    pol: ReferenceStatePolicy | None = None,
):
    asset_record = asset_record or asset()
    ref = ref if ref is not None else reference()
    return build_reference_state_snapshot(
        asset=asset_record,
        reference=ref,
        corporate_actions=matches(rows or [], asset_record),
        session_evidence=session_evidence or session(MarketSessionState.UNRESOLVED),
        policy=pol or policy(),
        as_of=as_of,
        registry_observed_at=NOW,
        corporate_actions_observed_at=NOW,
    )


def expect_failure(**kwargs) -> ReferenceStateError:
    with pytest.raises(ReferenceStateError) as excinfo:
        build(**kwargs)
    return excinfo.value


# ---------------------------------------------------------------------------
# 1-3. Baseline lifecycle/halt/freshness classifications
# ---------------------------------------------------------------------------

def test_01_fresh_active_reference_is_current_and_usable() -> None:
    snap = build()
    assert snap.freshness_state is FreshnessState.CURRENT
    assert snap.reference_usable is True
    assert snap.blocking_reasons == ()
    assert snap.asset_lifecycle_state.value == "ACTIVE"
    assert snap.halt_state.value == "NOT_HALTED"
    assert snap.multiplier_state.value == "CURRENT"
    assert snap.corporate_action_state.value == "NONE"
    assert snap.status is ReferenceStateStatus.REFERENCE_STATE_OK


def test_02_active_trading_halt_is_halted_and_unusable() -> None:
    snap = build(ref=reference(halt=True))
    assert snap.halt_state.value == "TRADING_HALTED"
    assert snap.reference_usable is False
    assert ReferenceStateReason.TRADING_HALTED in snap.blocking_reasons


def test_03_inactive_r1_asset_is_inactive_and_unusable() -> None:
    snap = build(asset_record=asset(status=RegistryAssetStatus.INACTIVE))
    assert snap.asset_lifecycle_state.value == "INACTIVE"
    assert snap.reference_usable is False
    assert ReferenceStateReason.ASSET_INACTIVE in snap.blocking_reasons


# ---------------------------------------------------------------------------
# 4-6. Freshness vs market session
# ---------------------------------------------------------------------------

def test_04_old_reference_with_proven_open_session_is_stale_unexpected() -> None:
    snap = build(
        ref=reference(generated_at=NOW),
        session_evidence=session(MarketSessionState.OPEN, observed_at=NOW + timedelta(seconds=30)),
        as_of=NOW + timedelta(seconds=600),
    )
    assert snap.freshness_state is FreshnessState.STALE_UNEXPECTED
    assert snap.market_session_state is MarketSessionState.OPEN
    assert snap.reference_usable is False
    assert ReferenceStateReason.REFERENCE_STALE_UNEXPECTED in snap.blocking_reasons


def test_05_old_reference_with_closed_point_evidence_is_never_expected_static() -> None:
    # Correction A: a point-in-time CLOSED observation proves only that the
    # session is closed NOW — it cannot prove the reference was expected to
    # remain static across the whole interval in which it aged.
    snap = build(
        ref=reference(generated_at=NOW),
        session_evidence=session(MarketSessionState.CLOSED, observed_at=NOW + timedelta(seconds=30)),
        as_of=NOW + timedelta(seconds=600),
    )
    assert snap.freshness_state is FreshnessState.UNRESOLVED
    assert snap.freshness_state is not FreshnessState.EXPECTED_STATIC
    assert snap.market_session_state is MarketSessionState.CLOSED  # evidence recorded
    assert snap.reference_usable is False
    assert ReferenceStateReason.MARKET_SESSION_UNRESOLVED in snap.blocking_reasons


def test_06_old_reference_with_unresolved_session_is_never_expected_static() -> None:
    snap = build(
        ref=reference(generated_at=NOW),
        session_evidence=session(MarketSessionState.UNRESOLVED),
        as_of=NOW + timedelta(seconds=600),
    )
    assert snap.freshness_state is FreshnessState.UNRESOLVED
    assert snap.market_session_state is MarketSessionState.UNRESOLVED
    assert snap.freshness_state is not FreshnessState.EXPECTED_STATIC
    assert ReferenceStateReason.MARKET_SESSION_UNRESOLVED in snap.blocking_reasons
    assert snap.reference_usable is False


def test_06b_stale_open_session_evidence_downgrades_to_unresolved() -> None:
    stale_claim = NOW - timedelta(seconds=7200)
    snap = build(
        ref=reference(generated_at=NOW),
        session_evidence=session(MarketSessionState.CLOSED, observed_at=stale_claim),
        as_of=NOW + timedelta(seconds=600),
    )
    # The closed-session claim is older than the session-evidence window, so it
    # cannot explain the reference's age: freshness stays unresolved.
    assert snap.freshness_state is FreshnessState.UNRESOLVED
    assert snap.market_session_state is MarketSessionState.UNRESOLVED
    assert snap.session_evidence.state is MarketSessionState.CLOSED  # original preserved


def test_06b2_misaligned_closed_session_evidence_is_not_expected_static() -> None:
    # The closed-session claim predates the last generated reference: it may
    # describe an earlier closure. Point evidence never authorizes
    # EXPECTED_STATIC regardless of alignment (Correction A); the effective
    # CLOSED claim is still recorded while freshness fails closed.
    snap = build(
        ref=reference(generated_at=NOW),
        session_evidence=session(MarketSessionState.CLOSED, observed_at=NOW - timedelta(seconds=900)),
        as_of=NOW + timedelta(seconds=600),
    )
    assert snap.freshness_state is FreshnessState.UNRESOLVED
    assert snap.freshness_state is not FreshnessState.EXPECTED_STATIC
    assert snap.market_session_state is MarketSessionState.CLOSED
    assert snap.reference_usable is False
    assert ReferenceStateReason.MARKET_SESSION_UNRESOLVED in snap.blocking_reasons


def test_06c_adversarial_stale_during_open_timeline_is_never_expected_static() -> None:
    # Correction A (review counterexample): the reference was generated at
    # 12:00, stopped updating while the market was OPEN, and CLOSED evidence
    # only appeared at 18:01. The closed session cannot explain the hours in
    # which the reference silently aged.
    generated = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    closed_observed = datetime(2026, 9, 15, 18, 1, tzinfo=timezone.utc)
    as_of = datetime(2026, 9, 15, 18, 2, tzinfo=timezone.utc)
    snap = build(
        ref=reference(generated_at=generated),
        session_evidence=session(MarketSessionState.CLOSED, observed_at=closed_observed),
        as_of=as_of,
    )
    assert snap.freshness_state is FreshnessState.UNRESOLVED
    assert snap.freshness_state is not FreshnessState.EXPECTED_STATIC
    assert snap.reference_usable is False
    assert ReferenceStateReason.MARKET_SESSION_UNRESOLVED in snap.blocking_reasons


# ---------------------------------------------------------------------------
# 7-8. Timezone-awareness fail-closed
# ---------------------------------------------------------------------------

def test_07_timezone_naive_reference_timestamp_fails_closed() -> None:
    with pytest.raises(GapComputationError) as excinfo:
        reference(generated_at=NOW.replace(tzinfo=None))
    assert excinfo.value.status.value == "EVIDENCE_TIME_MISMATCH"


def test_08_timezone_naive_as_of_fails_closed() -> None:
    failure = expect_failure(as_of=(NOW + timedelta(seconds=60)).replace(tzinfo=None))
    assert failure.status is ReferenceStateStatus.EVIDENCE_TIME_MISMATCH


# ---------------------------------------------------------------------------
# 9-11. Multiplier transitions
# ---------------------------------------------------------------------------

def test_09_future_pending_multiplier_is_pending_future_and_usable() -> None:
    record = asset(pending="2", effective=NOW + timedelta(days=7))
    snap = build(asset_record=record)
    assert snap.multiplier_state.value == "PENDING_FUTURE"
    assert snap.reference_usable is True
    assert snap.pending_multiplier == Decimal("2")
    assert snap.pending_multiplier_effective_at == NOW + timedelta(days=7)
    assert snap.multiplier_evidence.current_multiplier == Decimal("1")


def test_10_overdue_pending_multiplier_is_transition_due_and_unusable() -> None:
    record = asset(pending="2", effective=NOW - timedelta(minutes=5))
    snap = build(asset_record=record)
    assert snap.multiplier_state.value == "TRANSITION_DUE_UNRESOLVED"
    assert snap.reference_usable is False
    assert ReferenceStateReason.MULTIPLIER_TRANSITION_UNRESOLVED in snap.blocking_reasons


def test_11_pending_multiplier_without_effective_time_cannot_bypass() -> None:
    # The frozen R1 parser/contract rejects the pair outright...
    with pytest.raises(RegistrySourceError):
        CanonicalAssetRecord(
            asset_uid=UID,
            token_symbol="AAA",
            token_name="AAA Token",
            deployments=(AssetKey(CHAIN, TOKEN),),
            current_multiplier=Decimal("1"),
            pending_multiplier=Decimal("2"),
            pending_multiplier_effective_at=None,
            status=RegistryAssetStatus.ACTIVE,
        )
    # ...and the R4 interpreter is defensively inconsistent without the pair.
    state, _, blockers = classify_multiplier(
        current_multiplier=Decimal("1"),
        pending_multiplier=Decimal("2"),
        pending_effective_at=None,
        as_of=NOW,
    )
    assert state.value == "INCONSISTENT"
    assert ReferenceStateReason.MULTIPLIER_STATE_INCONSISTENT in blockers


# ---------------------------------------------------------------------------
# 12-19. Corporate-action authority and matching
# ---------------------------------------------------------------------------

def test_12_matching_in_progress_action_preserved_and_not_blocking() -> None:
    row = ca_row(status=IN_PROGRESS)
    snap = build(rows=[row])
    assert snap.corporate_action_state.value == "IN_PROGRESS"
    assert snap.corporate_actions.rows == (row,)
    assert snap.corporate_actions.rows[0].process_date == date(2026, 10, 14)
    assert snap.reference_usable is True


def test_13_matching_completed_action_preserved() -> None:
    row = ca_row(status=COMPLETED, process_date=date(2026, 9, 1))
    snap = build(rows=[row])
    assert snap.corporate_action_state.value == "COMPLETED"
    assert snap.corporate_actions.rows == (row,)
    assert snap.reference_usable is True


def test_14_unsupported_in_progress_type_is_unresolved_never_none() -> None:
    row = ca_row(action_type=UNKNOWN_TYPE, details={"futureThing": {"x": "1"}})
    snap = build(rows=[row])
    assert snap.corporate_action_state.value == "UNRESOLVED"
    assert snap.corporate_action_state.value != "NONE"
    assert snap.reference_usable is False
    assert ReferenceStateReason.CORPORATE_ACTION_UNRESOLVED in snap.blocking_reasons
    # Evidence is preserved verbatim, never re-typed.
    assert snap.corporate_actions.rows[0].action_type == UNKNOWN_TYPE
    assert snap.corporate_actions.rows[0].known_type is False


def test_15_wrong_uid_action_is_ignored() -> None:
    stranger = ca_row(
        uid="0x" + "99" * 32,
        symbol="ZZZ",
        deployments=(AssetKey(CHAIN, "0x" + "99" * 20),),
    )
    snap = build(rows=[stranger])
    assert snap.corporate_actions.rows == ()
    assert snap.corporate_action_state.value == "NONE"
    assert snap.reference_usable is True


def test_16_matching_ticker_with_wrong_identity_is_rejected() -> None:
    conflict = ca_row(uid="0x" + "99" * 32, symbol="AAA")  # same ticker, foreign UID
    with pytest.raises(ReferenceStateError) as excinfo:
        matches([conflict])
    assert excinfo.value.status is ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH


def test_17_matching_deployment_with_conflicting_uid_is_rejected() -> None:
    conflict = ca_row(uid="0x" + "99" * 32, symbol="ZZZ")  # different ticker, our deployment
    with pytest.raises(ReferenceStateError) as excinfo:
        matches([conflict])
    assert excinfo.value.status is ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH


def test_18_multiple_historical_actions_retained_deterministically() -> None:
    first = ca_row(status=COMPLETED, process_date=date(2026, 3, 14))
    second = ca_row(status=COMPLETED, process_date=date(2026, 9, 1))
    snap = build(rows=[first, second])
    assert snap.corporate_actions.rows == (first, second)  # source order preserved
    assert snap.corporate_action_state.value == "COMPLETED"


def test_18b_deliberately_old_completed_action_is_never_labelled_recent() -> None:
    # Correction A: R4 has no recency authority, so a years-old completed
    # action must carry the neutral COMPLETED state — never a recency claim.
    ancient = ca_row(status=COMPLETED, process_date=date(2024, 2, 9))
    snap = build(rows=[ancient])
    assert snap.corporate_action_state.value == "COMPLETED"
    assert snap.corporate_actions.rows[0].process_date == date(2024, 2, 9)  # evidence kept


def test_19_ticker_never_repairs_canonical_identity() -> None:
    # A perfectly-formed row for a same-ticker foreign asset never matches.
    conflict = ca_row(uid="0x" + "99" * 32, symbol="AAA", status=COMPLETED)
    with pytest.raises(ReferenceStateError) as excinfo:
        matches([conflict])
    assert "ticker" in str(excinfo.value)
    # And a fully foreign row (foreign uid, ticker and deployment) is never
    # silently adopted.
    stranger = ca_row(
        uid="0x" + "99" * 32,
        symbol="ZZZ",
        deployments=(AssetKey(CHAIN, "0x" + "99" * 20),),
    )
    snap = build(rows=[stranger])
    assert snap.corporate_actions.rows == ()


# ---------------------------------------------------------------------------
# 20-22. Precedence and coexistence
# ---------------------------------------------------------------------------

def test_20_halt_with_fresh_timestamp_remains_blocked() -> None:
    snap = build(ref=reference(halt=True))
    assert snap.freshness_state is FreshnessState.CURRENT  # fresh...
    assert snap.halt_state.value == "TRADING_HALTED"  # ...but halted
    assert snap.reference_usable is False  # fresh + halted != normal current
    assert snap.blocking_reasons == (ReferenceStateReason.TRADING_HALTED,)


def test_21_inactive_with_fresh_timestamp_remains_blocked() -> None:
    snap = build(
        asset_record=asset(status=RegistryAssetStatus.INACTIVE),
        ref=reference(generated_at=NOW),
    )
    assert snap.freshness_state is FreshnessState.CURRENT
    assert snap.asset_lifecycle_state.value == "INACTIVE"
    assert snap.reference_usable is False
    assert snap.blocking_reasons == (ReferenceStateReason.ASSET_INACTIVE,)


def test_22_pending_future_material_coexists_with_usable_reference() -> None:
    record = asset(pending="2", effective=NOW + timedelta(days=7))
    row = ca_row(status=IN_PROGRESS, process_date=date(2026, 10, 14))
    snap = build(asset_record=record, rows=[row])
    assert snap.multiplier_state.value == "PENDING_FUTURE"
    assert snap.corporate_action_state.value == "IN_PROGRESS"
    assert snap.reference_usable is True  # policy permits; evidence preserved
    assert snap.blocking_reasons == ()


# ---------------------------------------------------------------------------
# 23. No score / signal / ranking fields
# ---------------------------------------------------------------------------

def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_23_no_score_signal_or_ranking_fields_exist() -> None:
    payload = build(
        asset_record=asset(pending="2", effective=NOW + timedelta(days=7)),
        rows=[ca_row(status=IN_PROGRESS)],
    ).to_evidence_dict()
    forbidden = ("score", "rank", "rating", "grade", "verdict", "opportunit", "recommend", "signal")
    assert not any(
        word in key.lower()
        for key in _walk_keys(payload)
        if key != "signalAuthority"  # boundary declaration, not a signal
        for word in forbidden
    )
    assert payload["boundaries"]["signalAuthority"] == "R5_NOT_YET_APPLIED"


# ---------------------------------------------------------------------------
# 24. R0-R3 production sources unchanged (behavioral canaries)
# ---------------------------------------------------------------------------

def test_24_r0_r1_r2_r3_sources_unchanged() -> None:
    # R0 canonical helper formula unchanged.
    settlement = SettlementReference(
        asset=AssetRef(CHAIN, "0x" + "cc" * 20, symbol="USDG", decimals=18),
        state=SettlementReferenceState.REFERENCE_CURRENT,
        usd_per_asset=Decimal("1"),
        source="TEST",
        observed_at=NOW,
    )
    def mk(side: QuoteSide, out: str) -> ExecutionQuote:
        token_ref = AssetRef(CHAIN, TOKEN, symbol="AAA", decimals=18)
        return ExecutionQuote(
            chain_id=CHAIN, token_address=TOKEN, side=side,
            input_asset=settlement.asset, output_asset=token_ref,
            requested_notional_usd=Decimal("100"),
            raw_amount_in=1, raw_amount_out=1,
            normalized_amount_in=Decimal("100"), normalized_amount_out=Decimal(out),
            input_decimals=18, output_decimals=18, source="T", quoted_at=NOW,
            settlement_reference=settlement, status=QuoteStatus.QUOTE_OK,
        )
    assert quote_size_impact_bps(mk(QuoteSide.BUY, "0.8"), mk(QuoteSide.BUY, "0.75")) == (
        ((Decimal("0.8") - Decimal("0.75")) / Decimal("0.8")) * Decimal("10000")
    )
    # R2 side binding unchanged: BUY compares against the official ASK.
    ref = build_bound_reference_price(asset(), binding(), price_row())
    gap_policy = GapComparisonPolicy(max_evidence_skew_seconds=300)
    obs = compute_directional_gap(ref, mk(QuoteSide.BUY, "0.8"), policy=gap_policy)
    assert obs.reference_price_usd_per_token == Decimal("105")
    # R1 canonical identity normalization unchanged.
    mixed_case = "0x" + TOKEN[2:].upper()
    assert AssetKey(CHAIN, mixed_case).canonical_id == f"{CHAIN}:{TOKEN}"


# ---------------------------------------------------------------------------
# Freshness/policy boundaries (adversarial additions)
# ---------------------------------------------------------------------------

def test_25_exact_live_age_boundary_is_current() -> None:
    snap = build(as_of=NOW + timedelta(seconds=120))
    assert snap.freshness_state is FreshnessState.CURRENT
    assert snap.reference_age_seconds == Decimal("120")


def test_26_negative_age_within_skew_tolerance_is_tolerated() -> None:
    snap = build(as_of=NOW - timedelta(seconds=3), pol=policy(skew=5))
    assert snap.freshness_state is FreshnessState.CURRENT
    assert snap.reference_age_seconds == Decimal("-3")


def test_27_negative_age_beyond_skew_tolerance_fails_closed() -> None:
    failure = expect_failure(as_of=NOW - timedelta(seconds=30), pol=policy(skew=5))
    assert failure.status is ReferenceStateStatus.EVIDENCE_TIME_MISMATCH


def test_28_policy_is_mandatory_without_defaults() -> None:
    with pytest.raises(TypeError):
        ReferenceStatePolicy()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        policy(max_live=0)
    with pytest.raises(ValueError):
        policy(session_age=-1)
    with pytest.raises(ValueError):
        policy(skew=-1)


def test_29_session_evidence_contract_is_fail_closed() -> None:
    with pytest.raises(ReferenceStateError):
        MarketSessionEvidence(state=MarketSessionState.OPEN, source="S", observed_at=None)
    with pytest.raises(ReferenceStateError):
        MarketSessionEvidence(state=MarketSessionState.UNRESOLVED, source="S", observed_at=NOW)
    with pytest.raises(ReferenceStateError) as naive:
        MarketSessionEvidence(
            state=MarketSessionState.CLOSED,
            source="S",
            observed_at=NOW.replace(tzinfo=None),
        )
    assert naive.value.status is ReferenceStateStatus.EVIDENCE_TIME_MISMATCH
    with pytest.raises(ReferenceStateError):
        MarketSessionEvidence(state=MarketSessionState.OPEN, source="  ", observed_at=NOW)


def test_30_blocking_reasons_follow_deterministic_precedence() -> None:
    snap = build(
        asset_record=asset(status=RegistryAssetStatus.INACTIVE),
        ref=reference(halt=True),
        session_evidence=session(MarketSessionState.UNRESOLVED),
        as_of=NOW + timedelta(seconds=600),
    )
    assert snap.blocking_reasons == tuple(
        r for r in BLOCKING_REASON_PRECEDENCE
        if r in set(snap.blocking_reasons)
    )
    assert snap.blocking_reasons[0] is ReferenceStateReason.ASSET_INACTIVE
    assert snap.blocking_reasons[1] is ReferenceStateReason.TRADING_HALTED
    assert snap.reference_usable is False


def test_31_serialization_carries_boundaries_and_reconstructible_evidence() -> None:
    row = ca_row(status=IN_PROGRESS)
    payload = build(rows=[row]).to_evidence_dict()
    assert payload["boundaries"] == {
        "referenceStateAuthority": "R4_APPLIED",
        "signalAuthority": "R5_NOT_YET_APPLIED",
        "terminalAuthority": "R6_NOT_YET_APPLIED",
    }
    assert payload["states"]["freshness"] == "CURRENT"
    assert payload["policy"]["maxLiveReferenceAgeSeconds"] == 120
    assert payload["corporateActionEvidence"]["rows"][0]["rawEvidence"]["type"] == CASH_DIVIDEND
    assert payload["referenceEvidence"]["rawBid"] == "95"


def test_32_identity_binding_failures_are_typed() -> None:
    from finco_radar.reference_state.contracts import CorporateActionMatches

    # Corporate-action matches bound to a foreign deployment are rejected by
    # the engine binding checks (typed, never silently re-bound).
    mismatched = CorporateActionMatches(
        asset_uid=UID,
        asset_key=AssetKey(CHAIN, "0x" + "bb" * 20),
        rows=(),
    )
    with pytest.raises(ReferenceStateError) as excinfo:
        build_reference_state_snapshot(
            asset=asset(),
            reference=reference(),
            corporate_actions=mismatched,
            session_evidence=session(MarketSessionState.UNRESOLVED),
            policy=policy(),
            as_of=NOW + timedelta(seconds=60),
        )
    assert excinfo.value.status is ReferenceStateStatus.REFERENCE_IDENTITY_MISMATCH


# ---------------------------------------------------------------------------
# Source-evidence tests: official /corporate-actions wire shapes (§22)
# ---------------------------------------------------------------------------

def valid_wire_row(**overrides: object) -> dict:
    """Official wire shape, verified live 2026-09-16 (cash dividend row)."""
    row: dict = {
        "id": UID,
        "type": CASH_DIVIDEND,
        "status": IN_PROGRESS,
        "processDate": {"year": 2026, "month": 10, "day": 14},
        "tokenSymbol": "AAA",
        "deployments": [
            {
                "contractAddress": TOKEN,
                "chainId": CHAIN,
                "networkName": "Robinhood Chain",
            }
        ],
        "details": {"cashDividend": {"underlyingSymbol": "AAA", "rate": "0.33"}},
    }
    row.update(overrides)
    return row


def test_s1_valid_wire_row_parses_with_raw_evidence() -> None:
    parsed = RobinhoodCorporateActionAdapter.parse_row(valid_wire_row())
    assert parsed.action_uid == UID
    assert parsed.known_type is True
    assert parsed.known_status is True
    assert parsed.is_in_progress is True and parsed.is_completed is False
    assert parsed.process_date == date(2026, 10, 14)
    assert parsed.details == {"cashDividend": {"underlyingSymbol": "AAA", "rate": "0.33"}}
    assert parsed.raw_evidence == valid_wire_row()


def test_s2_payload_wrapper_requires_corpactions_list() -> None:
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_rows({"nope": []})
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_rows("not-an-object")  # type: ignore[arg-type]
    rows = RobinhoodCorporateActionAdapter.parse_rows({"corpActions": [valid_wire_row()]})
    assert len(rows) == 1


def test_s3_malformed_uid_fails_closed() -> None:
    for bad in ("0x1234", "not-hex-at-all", "0x" + "gg" * 32, 12345):
        with pytest.raises(CorporateActionEvidenceError):
            RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(id=bad))


def test_s4_malformed_deployment_address_fails_closed() -> None:
    bad_row = valid_wire_row(
        deployments=[{"contractAddress": "0x1234", "chainId": CHAIN}]
    )
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(bad_row)


def test_s5_duplicate_deployment_identity_fails_closed() -> None:
    bad_row = valid_wire_row(
        deployments=[
            {"contractAddress": TOKEN, "chainId": CHAIN},
            {"contractAddress": TOKEN, "chainId": CHAIN},
        ]
    )
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(bad_row)


def test_s6_malformed_process_date_fails_closed() -> None:
    for bad in (
        {"year": 2026, "month": 13, "day": 1},
        {"year": 2026, "month": 1, "day": 32},
        {"year": 2026, "month": 1},
        "2026-10-14",
    ):
        with pytest.raises(CorporateActionEvidenceError):
            RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(processDate=bad))
    # processDate absent is tolerated and preserved as None.
    parsed = RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(processDate=None))
    assert parsed.process_date is None


def test_s7_missing_details_variant_fails_closed() -> None:
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(details={}))


def test_s8_conflicting_details_variant_fails_closed() -> None:
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(
            valid_wire_row(details={"forwardSplit": {"from": "1", "to": "4"}})
        )


def test_s9_malformed_status_fails_closed() -> None:
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(status=""))
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(status=None))


def test_s10_unknown_status_is_preserved_and_conservative() -> None:
    parsed = RobinhoodCorporateActionAdapter.parse_row(
        valid_wire_row(status="CORPORATE_ACTION_STATUS_FUTURE")
    )
    assert parsed.known_status is False
    snap = build(rows=[parsed])
    assert snap.corporate_action_state.value == "UNRESOLVED"
    assert snap.reference_usable is False


def test_s11_unknown_type_is_preserved_verbatim() -> None:
    parsed = RobinhoodCorporateActionAdapter.parse_row(
        valid_wire_row(
            type=UNKNOWN_TYPE,
            details={"futureVariant": {"anything": "goes"}},
        )
    )
    assert parsed.known_type is False
    assert parsed.action_type == UNKNOWN_TYPE
    assert parsed.details == {"futureVariant": {"anything": "goes"}}


def test_s12_missing_type_fails_closed() -> None:
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(type=None))
    with pytest.raises(CorporateActionEvidenceError):
        RobinhoodCorporateActionAdapter.parse_row(valid_wire_row(type=""))


# ---------------------------------------------------------------------------
# Correction A2 — R1 exception family must not escape the R4 boundary
# ---------------------------------------------------------------------------

def test_a2_01_malformed_token_symbol_raises_r4_typed_error() -> None:
    with pytest.raises(CorporateActionEvidenceError) as excinfo:
        RobinhoodCorporateActionAdapter.parse_row(
            valid_wire_row(tokenSymbol="bad symbol with spaces!")
        )
    assert excinfo.value.status is ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID
    # The raw frozen-R1 exception family must not escape the R4 boundary.
    from finco_radar.assets.contracts import RegistrySourceError

    assert not isinstance(excinfo.value, RegistrySourceError)


def test_a2_02_malformed_deployment_raises_r4_typed_error_not_r1_error() -> None:
    from finco_radar.assets.contracts import RegistrySourceError

    with pytest.raises(CorporateActionEvidenceError) as excinfo:
        RobinhoodCorporateActionAdapter.parse_row(
            valid_wire_row(deployments=[{"contractAddress": "0x1234", "chainId": CHAIN}])
        )
    assert excinfo.value.status is ReferenceStateStatus.CORPORATE_ACTION_EVIDENCE_INVALID
    assert not isinstance(excinfo.value, RegistrySourceError)


# ---------------------------------------------------------------------------
# Correction A — exact multiplier transition boundary
# ---------------------------------------------------------------------------

def test_ca_01_exact_multiplier_boundary_is_transition_due() -> None:
    # as_of == pending_multiplier_effective_at: the transition is due now and
    # the registry still reports it as pending — fail closed (>= semantics).
    record = asset(pending="2", effective=NOW)
    snap = build(asset_record=record)
    assert snap.multiplier_state.value == "TRANSITION_DUE_UNRESOLVED"
    assert snap.reference_usable is False
    assert ReferenceStateReason.MULTIPLIER_TRANSITION_UNRESOLVED in snap.blocking_reasons


def test_ca_02_expected_static_is_reserved_and_unreachable() -> None:
    # With the current point-in-time session evidence contract, no evidence
    # combination may produce EXPECTED_STATIC (Correction A1).
    for session_state, observed in (
        (MarketSessionState.CLOSED, NOW + timedelta(seconds=30)),
        (MarketSessionState.CLOSED, NOW - timedelta(seconds=900)),
        (MarketSessionState.OPEN, NOW + timedelta(seconds=30)),
        (MarketSessionState.UNRESOLVED, None),
    ):
        snap = build(
            ref=reference(generated_at=NOW),
            session_evidence=session(session_state, observed_at=observed),
            as_of=NOW + timedelta(seconds=600),
        )
        assert snap.freshness_state is not FreshnessState.EXPECTED_STATIC
