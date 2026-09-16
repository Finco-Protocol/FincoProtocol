"""Focused, fully offline R7 cross-market tests.

Deterministic synthetic fixtures only; synthetic evidence is marked synthetic
and never represents live authority. Test numbering follows the R7
specification's mandatory coverage list (§27).
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import AssetKey
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.cross_market.contracts import (
    TimingState,
    AttributionState,
    ComparabilityReason,
    ComparabilityState,
    CrossMarketError,
    CrossMarketPolicy,
    CrossMarketStatus,
    EconomicIdentityBinding,
    EventKind,
    FxObservation,
    LayerObservation,
    LayerObservationStatus,
    LayerType,
    SettlementContext,
    TokenRepresentation,
    VenueObservation,
    verify_serialized_evidence,
)
from finco_radar.cross_market.engine import (
    build_cross_market_snapshot,
    compare_cross_deployments,
    derive_events,
)

T = timezone.utc
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=T)
UID = "AAPL"
KEY = AssetKey(4663, "0x" + "aa" * 20)
KEY_B = AssetKey(137, "0x" + "bb" * 20)

THRESHOLD = Decimal("50")


def policy(threshold: str = "50", skew: str = "120", stale: str = "600") -> CrossMarketPolicy:
    return CrossMarketPolicy(
        comparison_currency="USD",
        material_dislocation_bps=Decimal(threshold),
        max_layer_skew_seconds=Decimal(skew),
        stale_layer_seconds=Decimal(stale),
    )


def binding(keys=(KEY,), uid: str = UID) -> EconomicIdentityBinding:
    return EconomicIdentityBinding(
        economic_asset_uid=uid, canonical_keys=tuple(keys), source="OFFICIAL_TEST_REGISTRY"
    )


def layer(
    layer_type: LayerType,
    price: str,
    *,
    at: datetime = NOW,
    currency: str = "USD",
    source: str = "SYNTHETIC_SOURCE",
    status: LayerObservationStatus = LayerObservationStatus.AVAILABLE,
    usable: bool | None = True,
    multiplier: str = "1",
    uid: str = UID,
    key: AssetKey = KEY,
    instrument: str | None = None,
) -> LayerObservation:
    return LayerObservation(
        layer=layer_type,
        status=status,
        source=source,
        price=Decimal(price) if status is LayerObservationStatus.AVAILABLE else None,
        currency=currency if status is LayerObservationStatus.AVAILABLE else None,
        observed_at=at if status is LayerObservationStatus.AVAILABLE else None,
        instrument=instrument,
        usable=usable,
        multiplier=Decimal(multiplier),
        asset_uid=uid,
        asset_key=key,
        raw_evidence={"synthetic": True},
    )


def token(
    *,
    price: str | None = None,
    multiplier: str = "1",
    usable: bool = True,
    at: datetime = NOW,
    key: AssetKey = KEY,
) -> TokenRepresentation:
    return TokenRepresentation(
        economic_asset_uid=UID,
        asset_key=key,
        symbol="AAA",
        multiplier=Decimal(multiplier),
        representation_status="ACTIVE",
        reference_usable=usable,
        observed_price=Decimal(price) if price is not None else None,
        currency="USD" if price is not None else None,
        observed_at=at if price is not None else None,
        raw_evidence={"synthetic": True},
    )


def venue(
    name: str,
    price: str,
    *,
    side: QuoteSide = QuoteSide.BUY,
    notional: str = "100",
    at: datetime = NOW,
    currency: str = "USD",
    key: AssetKey = KEY,
) -> VenueObservation:
    return VenueObservation(
        venue=name,
        side=side,
        notional_usd=Decimal(notional),
        price=Decimal(price),
        currency=currency,
        observed_at=at,
        source="SYNTHETIC_R0_EVIDENCE",
        asset_key=key,
        gap_bps=Decimal("12.5"),
        route_signature="SYNTH:ROUTE",
        raw_evidence={"synthetic": True},
    )


def build(**kwargs):
    kwargs.setdefault("binding", binding())
    kwargs.setdefault("policy", policy())
    kwargs.setdefault("as_of", NOW)
    kwargs.setdefault("synthetic", True)
    kwargs.setdefault("git_head", "r7-test-head")
    return build_cross_market_snapshot(**kwargs)


def oracle(price: str = "250", **kwargs):
    return layer(LayerType.ORACLE_REFERENCE, price, **kwargs)


def underlying(price: str = "250", **kwargs):
    return layer(LayerType.UNDERLYING, price, instrument="AAPL", **kwargs)


def settlement(resolved: bool = True) -> SettlementContext:
    return SettlementContext(
        settlement_asset_symbol="USDG",
        chain_id=4663,
        contract_address="0x" + "cc" * 20,
        settlement_currency="USD",
        transfer_required=False,
        authority_status="CONTEXT_ONLY_R8_PENDING",
        resolved=resolved,
        raw_evidence={"synthetic": True},
    )


# ---------------------------------------------------------------------------
# 1-8. Core attribution scenarios
# ---------------------------------------------------------------------------

def test_01_fully_aligned_stack_is_comparable_with_no_dislocation() -> None:
    snap = build(
        underlying=underlying("250"),
        oracle_reference=oracle("250"),
        token=token(price="250"),
        venues=[venue("DEX_A", "250")],
        settlement=settlement(),
    )
    assert snap.attribution_state is AttributionState.NO_MATERIAL_DISLOCATION
    assert snap.timing.state.value == "ALIGNED"
    # A single venue cannot answer the cross-venue comparison, so the honest
    # state is PARTIALLY_COMPARABLE with INSUFFICIENT_MEMBERS (never silent).
    assert snap.comparability_state is ComparabilityState.PARTIALLY_COMPARABLE
    assert snap.comparability_reasons == (ComparabilityReason.INSUFFICIENT_MEMBERS,)


def test_01b_complete_stack_with_two_venues_is_comparable() -> None:
    snap = build(
        underlying=underlying("250"),
        oracle_reference=oracle("250"),
        token=token(price="250"),
        venues=[venue("DEX_A", "250"), venue("DEX_B", "250")],
        settlement=settlement(),
    )
    assert snap.comparability_state is ComparabilityState.COMPARABLE
    assert snap.comparability_reasons == ()
    assert snap.attribution_state is AttributionState.NO_MATERIAL_DISLOCATION


def test_02_underlying_reference_divergence_is_attributed() -> None:
    snap = build(underlying=underlying("252"), oracle_reference=oracle("250"))
    material = [c for c in snap.dislocation_components if c.material]
    assert any(
        c.from_layer is LayerType.UNDERLYING and c.to_layer is LayerType.ORACLE_REFERENCE
        for c in material
    )
    assert snap.attribution_state is AttributionState.UNDERLYING_REFERENCE_DISLOCATION


def test_03_reference_token_divergence_is_attributed() -> None:
    snap = build(oracle_reference=oracle("250"), token=token(price="252"))
    material = [c for c in snap.dislocation_components if c.material]
    assert any(
        c.from_layer is LayerType.ORACLE_REFERENCE and c.to_layer is LayerType.TOKEN
        for c in material
    )
    assert snap.attribution_state is AttributionState.REFERENCE_TOKEN_DISLOCATION


def test_04_token_venue_divergence_is_attributed() -> None:
    snap = build(oracle_reference=oracle("250"), token=token(price="250"), venues=[venue("DEX_A", "252")])
    material = [c for c in snap.dislocation_components if c.material]
    assert any(
        c.from_layer is LayerType.TOKEN and c.to_layer is LayerType.VENUE for c in material
    )
    assert snap.attribution_state is AttributionState.TOKEN_VENUE_DISLOCATION


def test_05_cross_venue_divergence_is_attributed() -> None:
    # Symmetric divergence around the token price: each per-venue delta stays
    # below the threshold while the cross-venue dispersion crosses it.
    snap = build(
        oracle_reference=oracle("250"),
        token=token(price="250"),
        venues=[venue("DEX_A", "249.375"), venue("DEX_B", "250.625")],
    )
    dispersion = [
        c
        for c in snap.dislocation_components
        if c.from_layer is LayerType.VENUE and c.to_layer is LayerType.VENUE
    ]
    assert len(dispersion) == 1 and dispersion[0].material
    assert snap.attribution_state is AttributionState.CROSS_VENUE_DISLOCATION


def test_05b_cross_deployment_divergence_is_attributed() -> None:
    snap_a = build(
        binding=binding(keys=(KEY,)),
        oracle_reference=oracle("250", key=KEY),
    )
    snap_b = build(
        binding=binding(keys=(KEY_B,)),
        oracle_reference=oracle("252", key=KEY_B, uid=UID),
    )
    component = compare_cross_deployments(
        stack_a=snap_a, stack_b=snap_b, policy=policy()
    )
    assert component.material is True
    assert (component.from_layer, component.to_layer) == (LayerType.TOKEN, LayerType.TOKEN)
    assert component.delta_bps == ((Decimal("252") / Decimal("250")) - 1) * Decimal(10000)


def test_06_multiple_simultaneous_dislocations_are_multi_layer() -> None:
    snap = build(
        underlying=underlying("252"),
        oracle_reference=oracle("250"),
        token=token(price="252.5"),
        venues=[venue("DEX_A", "255")],
    )
    material = [c for c in snap.dislocation_components if c.material]
    assert len(material) >= 2
    assert snap.attribution_state is AttributionState.MULTI_LAYER_DISLOCATION
    # Component-level evidence is preserved, not collapsed.
    labels = {c.label for c in material}
    assert len(labels) == len(material)


def test_07_no_material_dislocation_when_all_layers_agree() -> None:
    snap = build(
        underlying=underlying("250"),
        oracle_reference=oracle("250"),
        token=token(price="250"),
        venues=[venue("DEX_A", "250.1")],  # 4 bps < 50 threshold
    )
    assert snap.attribution_state is AttributionState.NO_MATERIAL_DISLOCATION
    assert all(not c.material for c in snap.dislocation_components)


# ---------------------------------------------------------------------------
# 9-10. Threshold and rounding boundaries
# ---------------------------------------------------------------------------

def test_08_exact_threshold_boundary_is_material() -> None:
    snap = build(
        binding=binding(),
        policy=policy(threshold="100"),
        oracle_reference=oracle("100"),
        venues=[venue("DEX_A", "101")],  # exactly 100 bps
    )
    component = snap.dislocation_components[-1]
    assert component.delta_bps == Decimal("100")
    assert component.material is True
    assert snap.attribution_state is AttributionState.REFERENCE_TOKEN_DISLOCATION


def test_09_just_below_threshold_is_not_material() -> None:
    snap = build(
        binding=binding(),
        policy=policy(threshold="100"),
        oracle_reference=oracle("100000"),
        venues=[venue("DEX_A", "100099.999")],  # 99.9999 bps
    )
    component = snap.dislocation_components[-1]
    assert component.material is False
    assert snap.attribution_state is AttributionState.NO_MATERIAL_DISLOCATION


# ---------------------------------------------------------------------------
# 11-14. FX / currency normalization
# ---------------------------------------------------------------------------

def test_10_different_quote_currencies_without_fx_is_partial() -> None:
    snap = build(
        underlying=layer(LayerType.UNDERLYING, "230", currency="EUR"),
        oracle_reference=oracle("250"),
    )
    assert snap.comparability_state is ComparabilityState.PARTIALLY_COMPARABLE
    assert ComparabilityReason.FX_UNAVAILABLE in snap.comparability_reasons
    # No cross-currency component may be computed without FX authority.
    assert all(
        not (c.from_layer is LayerType.UNDERLYING and c.to_layer is LayerType.ORACLE_REFERENCE)
        for c in snap.dislocation_components
    )


def test_11_valid_fx_conversion_normalizes_and_explains_fx_layer() -> None:
    fx = FxObservation(
        source_currency="EUR",
        target_currency="USD",
        rate=Decimal("1.10"),
        source="SYNTHETIC_FX_AUTHORITY",
        observed_at=NOW,
        raw_evidence={"synthetic": True},
    )
    snap = build(
        underlying=layer(LayerType.UNDERLYING, "230", currency="EUR"),
        fx=fx,
        oracle_reference=oracle("250"),
    )
    fx_components = [
        c
        for c in snap.dislocation_components
        if c.from_layer is LayerType.UNDERLYING and c.to_layer is LayerType.UNDERLYING
    ]
    assert len(fx_components) == 1
    assert fx_components[0].fx_rate == Decimal("1.10")
    # 230 EUR → 253 USD at 1.10: the FX layer contributes +1000 bps.
    assert fx_components[0].delta_bps == ((Decimal("1.10") / Decimal("1")) - 1) * Decimal(10000)
    underlying_to_oracle = [
        c
        for c in snap.dislocation_components
        if c.from_layer is LayerType.UNDERLYING and c.to_layer is LayerType.ORACLE_REFERENCE
    ]
    assert underlying_to_oracle and underlying_to_oracle[0].from_price == Decimal("253")


def test_12_missing_fx_authority_blocks_required_conversion() -> None:
    snap = build(
        underlying=layer(LayerType.UNDERLYING, "230", currency="EUR"),
        oracle_reference=oracle("250"),
    )
    assert ComparabilityReason.FX_UNAVAILABLE in snap.comparability_reasons


def test_13_stale_fx_observation_is_treated_as_unavailable() -> None:
    stale_fx = FxObservation(
        source_currency="EUR",
        target_currency="USD",
        rate=Decimal("1.10"),
        source="SYNTHETIC_FX_AUTHORITY",
        observed_at=NOW - timedelta(seconds=3600),  # > stale window 600 s
        raw_evidence={"synthetic": True},
    )
    snap = build(
        underlying=layer(LayerType.UNDERLYING, "230", currency="EUR"),
        fx=stale_fx,
        oracle_reference=oracle("250"),
    )
    assert ComparabilityReason.FX_UNAVAILABLE in snap.comparability_reasons
    assert all(
        not (c.from_layer is LayerType.UNDERLYING and c.to_layer is LayerType.ORACLE_REFERENCE)
        for c in snap.dislocation_components
    )


# ---------------------------------------------------------------------------
# 15-17. Unavailable / stale layers
# ---------------------------------------------------------------------------

def test_14_reference_unavailable_makes_attribution_unavailable() -> None:
    snap = build(oracle_reference=None, venues=[venue("DEX_A", "250")])
    assert snap.attribution_state is AttributionState.ATTRIBUTION_UNAVAILABLE
    assert ComparabilityReason.REFERENCE_UNAVAILABLE in snap.comparability_reasons
    assert snap.comparability_state is ComparabilityState.PARTIALLY_COMPARABLE


def test_15_stale_underlying_marks_timing_stale() -> None:
    snap = build(
        underlying=layer(LayerType.UNDERLYING, "250", at=NOW - timedelta(seconds=3600)),
        oracle_reference=oracle("250"),
    )
    assert snap.timing.state is TimingState.STALE_LAYER
    assert "UNDERLYING" in snap.timing.stale_layers
    assert ComparabilityReason.STALE_LAYER in snap.comparability_reasons


def test_16_stale_venue_marks_timing_stale() -> None:
    snap = build(
        oracle_reference=oracle("250"),
        venues=[venue("DEX_A", "250", at=NOW - timedelta(seconds=3600))],
    )
    assert snap.timing.state is TimingState.STALE_LAYER
    assert any(label.startswith("VENUE[DEX_A") for label in snap.timing.stale_layers)


def test_16b_reference_suppressed_is_not_available() -> None:
    # A suppressed layer must never carry a price (no fake availability).
    with pytest.raises(CrossMarketError):
        LayerObservation(
            layer=LayerType.ORACLE_REFERENCE,
            status=LayerObservationStatus.SUPPRESSED_BY_AUTHORITY,
            source="SYNTHETIC_SOURCE",
            price=Decimal("250"),
            currency="USD",
            observed_at=NOW,
            usable=False,
        )
    suppressed = layer(
        LayerType.ORACLE_REFERENCE, "250", usable=False,
        status=LayerObservationStatus.SUPPRESSED_BY_AUTHORITY,
    )
    snap = build(oracle_reference=suppressed)
    assert snap.comparability_state is ComparabilityState.SUPPRESSED
    assert snap.attribution_state is AttributionState.ATTRIBUTION_UNAVAILABLE


# ---------------------------------------------------------------------------
# 18-19. Timing skew policy
# ---------------------------------------------------------------------------

def test_17_acceptable_timing_skew_is_aligned() -> None:
    snap = build(
        underlying=underlying("250", at=NOW - timedelta(seconds=60)),
        oracle_reference=oracle("250", at=NOW - timedelta(seconds=30)),
        venues=[venue("DEX_A", "250", at=NOW)],
    )
    assert snap.timing.state is TimingState.ALIGNED
    assert ComparabilityReason.TIMING_SKEW not in snap.comparability_reasons
    assert snap.timing.total_skew_seconds == Decimal("60")


def test_18_excessive_timing_skew_is_skewed() -> None:
    snap = build(
        underlying=underlying("250", at=NOW - timedelta(seconds=600)),
        oracle_reference=oracle("250", at=NOW),
        venues=[venue("DEX_A", "250")],
    )
    assert snap.timing.state is TimingState.SKEWED
    assert snap.timing.total_skew_seconds == Decimal("600")
    assert ComparabilityReason.TIMING_SKEW in snap.comparability_reasons
    assert snap.comparability_state in (
        ComparabilityState.PARTIALLY_COMPARABLE,
        ComparabilityState.COMPARABLE,
    )


# ---------------------------------------------------------------------------
# 20-25. Settlement, identity and lineage
# ---------------------------------------------------------------------------

def test_19_settlement_context_unresolved_is_recorded() -> None:
    snap = build(
        oracle_reference=oracle("250"),
        venues=[venue("DEX_A", "250")],
        settlement=settlement(resolved=False),
    )
    assert ComparabilityReason.SETTLEMENT_CONTEXT_UNRESOLVED in snap.comparability_reasons
    assert snap.comparability_state is ComparabilityState.PARTIALLY_COMPARABLE


def test_20_ticker_collision_without_identity_binding_is_rejected() -> None:
    # Same ticker text, but the venue row carries an unbound deployment:
    # membership is never proven by ticker.
    with pytest.raises(CrossMarketError) as excinfo:
        build(
            binding=binding(keys=(KEY,)),
            oracle_reference=oracle("250"),
            venues=[venue("DEX_A", "250", key=KEY_B)],
        )
    assert excinfo.value.status is CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH


def test_21_conflicting_economic_binding_is_rejected() -> None:
    with pytest.raises(CrossMarketError) as excinfo:
        build(token=TokenRepresentation(
            economic_asset_uid="MSFT",
            asset_key=KEY,
            symbol="AAA",
            multiplier=Decimal("1"),
            representation_status="ACTIVE",
            reference_usable=True,
        ))
    assert excinfo.value.status is CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH
    with pytest.raises(CrossMarketError) as uid_exc:
        EconomicIdentityBinding(
            economic_asset_uid=UID,
            canonical_keys=(KEY, KEY),
            source="S",
        )
    assert uid_exc.value.status is CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED


def test_22_multiplier_mismatch_is_suppressed() -> None:
    snap = build(
        oracle_reference=oracle("250", multiplier="2"),
        token=token(price="250", multiplier="1"),
        venues=[venue("DEX_A", "250")],
    )
    assert ComparabilityReason.MULTIPLIER_UNRESOLVED in snap.comparability_reasons
    assert snap.comparability_state is ComparabilityState.SUPPRESSED
    assert snap.attribution_state is AttributionState.ATTRIBUTION_UNAVAILABLE


def test_23_duplicate_canonical_member_is_rejected() -> None:
    with pytest.raises(CrossMarketError) as excinfo:
        build(
            oracle_reference=oracle("250"),
            venues=[venue("DEX_A", "250"), venue("DEX_A", "250")],
        )
    assert excinfo.value.status is CrossMarketStatus.CROSS_MARKET_INPUT_INVALID
    with pytest.raises(CrossMarketError) as bind_exc:
        binding(keys=(KEY, KEY))
    assert bind_exc.value.status is CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED


def test_24_upstream_evidence_mismatch_is_rejected() -> None:
    foreign_oracle = layer(LayerType.ORACLE_REFERENCE, "250", uid="MSFT")
    with pytest.raises(CrossMarketError) as excinfo:
        build(oracle_reference=foreign_oracle)
    assert excinfo.value.status is CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH
    foreign_token = TokenRepresentation(
        economic_asset_uid=UID,
        asset_key=KEY_B,
        symbol="AAA",
        multiplier=Decimal("1"),
        representation_status="ACTIVE",
        reference_usable=True,
    )
    with pytest.raises(CrossMarketError) as token_exc:
        build(token=foreign_token)
    assert token_exc.value.status is CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH


# ---------------------------------------------------------------------------
# 26-30. Determinism, immutability, digests
# ---------------------------------------------------------------------------

def _reference_stack(venues: list | None = None):
    return dict(
        underlying=underlying("250"),
        oracle_reference=oracle("250"),
        token=token(price="250"),
        venues=venues if venues is not None else [venue("DEX_A", "250")],
        settlement=settlement(),
    )


def test_25_member_order_invariance_produces_identical_digest() -> None:
    straight = build(**_reference_stack([venue("DEX_A", "250"), venue("DEX_B", "250.2")]))
    shuffled = build(**_reference_stack([venue("DEX_B", "250.2"), venue("DEX_A", "250")]))
    assert straight.r7_snapshot_digest == shuffled.r7_snapshot_digest
    assert straight.to_evidence_dict() == shuffled.to_evidence_dict()


def test_26_serialized_mutation_does_not_mutate_source() -> None:
    snap = build(**_reference_stack())
    payload = snap.to_evidence_dict()
    payload["layers"]["oracleReference"]["price"] = "999"
    payload["dislocationComponents"].clear()
    payload["boundaries"]["signalAuthority"] = "TAMPERED"
    fresh = snap.to_evidence_dict()
    assert fresh["layers"]["oracleReference"]["price"] == "250"
    assert fresh["dislocationComponents"]
    assert fresh["boundaries"]["signalAuthority"] == "R5_APPLIED"
    assert verify_serialized_evidence(fresh) is True


def test_27_internal_mutation_attempt_fails() -> None:
    snap = build(**_reference_stack())
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.attribution_state = AttributionState.ATTRIBUTION_UNAVAILABLE  # type: ignore[misc]
    component = snap.dislocation_components[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        component.delta_bps = Decimal("0")  # type: ignore[misc]


def test_28_digest_reconstruction_matches() -> None:
    snap = build(**_reference_stack())
    evidence = snap.to_evidence_dict()
    recorded = evidence["r7SnapshotDigest"]
    material = json.loads(json.dumps(evidence))
    material.pop("r7SnapshotDigest")
    import hashlib

    recomputed = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert recomputed == recorded


def test_29_tampered_serialized_evidence_is_rejected() -> None:
    snap = build(**_reference_stack())
    evidence = snap.to_evidence_dict()
    assert verify_serialized_evidence(evidence) is True
    for tampered in (
        {**evidence, "attributionState": "TAMPERED"},
        {**evidence, "dislocationComponents": []},
        {**evidence, "r7SnapshotDigest": "0" * 64},
    ):
        assert verify_serialized_evidence(tampered) is False


# ---------------------------------------------------------------------------
# 31-32. Suppression vs no-dislocation; authority vs price state
# ---------------------------------------------------------------------------

def test_30_suppression_is_distinct_from_no_dislocation() -> None:
    same_prices = dict(
        underlying=underlying("250"),
        venues=[venue("DEX_A", "250")],
    )
    clean = build(**same_prices, oracle_reference=oracle("250"))
    suppressed = build(**same_prices, oracle_reference=layer(
        LayerType.ORACLE_REFERENCE, "250", usable=False,
        status=LayerObservationStatus.SUPPRESSED_BY_AUTHORITY,
    ))
    assert clean.attribution_state is AttributionState.NO_MATERIAL_DISLOCATION
    assert suppressed.attribution_state is AttributionState.ATTRIBUTION_UNAVAILABLE
    # Prices are identical; only the authority state differs, and it must show.
    assert clean.comparability_state is ComparabilityState.PARTIALLY_COMPARABLE
    assert suppressed.comparability_state is ComparabilityState.SUPPRESSED
    assert clean.comparability_state is not suppressed.comparability_state


def test_31_authority_state_change_is_distinct_from_market_price_change() -> None:
    # Identical market prices in both snapshots; only the reference authority
    # state (usable → halted/unusable) changes, and comparability must follow
    # the authority state, not the (unchanged) price.
    prices = dict(
        underlying=underlying("250"),
        venues=[venue("DEX_A", "250")],
    )
    usable_snapshot = build(**prices, oracle_reference=oracle("250", usable=True))
    halted_snapshot = build(**prices, oracle_reference=oracle("250", usable=False))
    assert usable_snapshot.comparability_state is ComparabilityState.PARTIALLY_COMPARABLE
    assert halted_snapshot.comparability_state is ComparabilityState.SUPPRESSED
    assert (
        usable_snapshot.attribution_state is AttributionState.NO_MATERIAL_DISLOCATION
        and halted_snapshot.attribution_state is AttributionState.ATTRIBUTION_UNAVAILABLE
    )


# ---------------------------------------------------------------------------
# Events (deterministic descriptive diff)
# ---------------------------------------------------------------------------

def test_32_events_derive_deterministically_from_two_snapshots() -> None:
    first = build(oracle_reference=oracle("250"))
    second = build(oracle_reference=oracle("260"), venues=[venue("DEX_A", "262")])
    events = derive_events(first, second)
    kinds = [e.kind for e in events]
    assert EventKind.DISLOCATION_APPEARED in kinds
    assert EventKind.ATTRIBUTION_CHANGED in kinds
    assert all(e.kind not in (EventKind.DISLOCATION_CLEARED,) for e in events)
    # Determinism: same inputs, same events.
    assert events == derive_events(first, second)
    widened = derive_events(second, build(oracle_reference=oracle("270"), venues=[venue("DEX_A", "275")]))
    assert EventKind.DISLOCATION_WIDENED in [e.kind for e in widened]
    cleared = derive_events(second, first)
    assert EventKind.DISLOCATION_CLEARED in [e.kind for e in cleared]


def test_32b_snapshot_without_previous_has_no_events() -> None:
    snap = build(**_reference_stack())
    assert snap.events == ()


# ---------------------------------------------------------------------------
# Policy contract
# ---------------------------------------------------------------------------

def test_33_policy_is_mandatory_and_validated() -> None:
    with pytest.raises(CrossMarketError):
        CrossMarketPolicy(comparison_currency=" ", material_dislocation_bps=Decimal("1"),
                          max_layer_skew_seconds=Decimal("1"), stale_layer_seconds=Decimal("1"))
    with pytest.raises(CrossMarketError):
        policy(threshold="0")
    with pytest.raises(CrossMarketError):
        CrossMarketPolicy(
            comparison_currency="USD",
            material_dislocation_bps=0.5,  # float is not a Decimal
            max_layer_skew_seconds=Decimal("1"),
            stale_layer_seconds=Decimal("1"),
        )


def test_34_timezone_naive_evidence_fails_closed() -> None:
    with pytest.raises(CrossMarketError) as excinfo:
        build(
            oracle_reference=oracle("250"),
            venues=[venue("DEX_A", "250", at=NOW.replace(tzinfo=None))],
            as_of=NOW,
        )
    assert excinfo.value.status is CrossMarketStatus.CROSS_MARKET_TIME_MISMATCH
    with pytest.raises(CrossMarketError) as as_of_exc:
        build(as_of=NOW.replace(tzinfo=None))
    assert as_of_exc.value.status is CrossMarketStatus.CROSS_MARKET_TIME_MISMATCH
