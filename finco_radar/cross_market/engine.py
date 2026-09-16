"""Deterministic cross-market dislocation engine (R7 authority).

Consumes frozen R0–R6 evidence plus new R7 underlying/FX/oracle observations
and produces a typed, digested cross-market snapshot: timing diagnostics,
price-path decomposition, dislocation components, attribution and comparability.

R7 measures observed differences only. It never computes executable edge,
fees, gas, bridge costs or recommendations (R8 boundary), and never builds a
general asset graph (R9 boundary).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from finco_radar.quotes.contracts import QuoteSide

from .contracts import (
    AttributionState,
    ComparabilityReason,
    ComparabilityState,
    CrossMarketError,
    CrossMarketEvent,
    CrossMarketPolicy,
    CrossMarketSnapshot,
    CrossMarketStatus,
    DislocationComponent,
    EconomicIdentityBinding,
    EventKind,
    FxObservation,
    LayerObservation,
    LayerObservationStatus,
    LayerType,
    SettlementContext,
    StackTiming,
    TimingState,
    TokenRepresentation,
    VenueObservation,
    compute_snapshot_digest,
)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise CrossMarketError(
            f"{name} must be timezone-aware",
            CrossMarketStatus.CROSS_MARKET_TIME_MISMATCH,
        )


def _decimal_seconds(delta_seconds: float) -> Decimal:
    return Decimal(str(delta_seconds))


def _canonical_venue_order(venues: Sequence[VenueObservation]) -> tuple[VenueObservation, ...]:
    return tuple(
        sorted(
            venues,
            key=lambda v: (v.venue, v.side.value, str(v.notional_usd), str(v.price)),
        )
    )


def _is_available(observation: LayerObservation | None) -> bool:
    return (
        observation is not None
        and observation.status is LayerObservationStatus.AVAILABLE
        and observation.price is not None
    )


def _fx_rate_for(
    fx: FxObservation | None,
    source_currency: str,
    target_currency: str,
    *,
    as_of: datetime,
    policy: CrossMarketPolicy,
) -> Decimal | None:
    """Fresh FX rate for one pair, or None when unavailable/stale.

    The FX observation must be no older than the policy stale-layer window;
    a stale rate is treated as unavailable, never silently applied.
    """
    if fx is None:
        return None
    if fx.pair != (source_currency.strip().upper(), target_currency.strip().upper()):
        return None
    age = _decimal_seconds((as_of - fx.observed_at).total_seconds())
    if age < 0 or age > policy.stale_layer_seconds:
        return None
    return fx.rate


def _component(
    *,
    from_layer: LayerType,
    to_layer: LayerType,
    label: str,
    from_price: Decimal,
    to_price: Decimal,
    policy: CrossMarketPolicy,
    from_observed_at: datetime,
    to_observed_at: datetime,
    from_source: str,
    to_source: str,
    fx: tuple[str, str, Decimal] | None = None,
) -> DislocationComponent:
    delta = to_price - from_price
    delta_bps = (to_price / from_price - Decimal(1)) * Decimal(10000)
    material = abs(delta_bps) >= policy.material_dislocation_bps
    return DislocationComponent(
        from_layer=from_layer,
        to_layer=to_layer,
        label=label,
        from_price=from_price,
        to_price=to_price,
        delta=delta,
        delta_bps=delta_bps,
        threshold_bps=policy.material_dislocation_bps,
        material=material,
        fx_source_currency=fx[0] if fx else None,
        fx_target_currency=fx[1] if fx else None,
        fx_rate=fx[2] if fx else None,
        from_observed_at=from_observed_at,
        to_observed_at=to_observed_at,
        timing_skew_seconds=_decimal_seconds(
            abs((to_observed_at - from_observed_at).total_seconds())
        ),
        from_source=from_source,
        to_source=to_source,
    )


_COMPONENT_ATTRIBUTION = {
    (LayerType.UNDERLYING, LayerType.UNDERLYING): AttributionState.FX_NORMALIZATION_DISLOCATION,
    (LayerType.UNDERLYING, LayerType.ORACLE_REFERENCE): (
        AttributionState.UNDERLYING_REFERENCE_DISLOCATION
    ),
    (LayerType.ORACLE_REFERENCE, LayerType.TOKEN): AttributionState.REFERENCE_TOKEN_DISLOCATION,
    (LayerType.TOKEN, LayerType.VENUE): AttributionState.TOKEN_VENUE_DISLOCATION,
    (LayerType.ORACLE_REFERENCE, LayerType.VENUE): AttributionState.REFERENCE_TOKEN_DISLOCATION,
    (LayerType.VENUE, LayerType.VENUE): AttributionState.CROSS_VENUE_DISLOCATION,
    (LayerType.TOKEN, LayerType.TOKEN): AttributionState.CROSS_DEPLOYMENT_DISLOCATION,
}


def derive_events(
    previous: CrossMarketSnapshot,
    current: CrossMarketSnapshot,
) -> tuple[CrossMarketEvent, ...]:
    """Deterministic descriptive events from two snapshots. Never advice."""
    events: list[CrossMarketEvent] = []
    previous_material = {c.label: c for c in previous.dislocation_components if c.material}
    current_material = {c.label: c for c in current.dislocation_components if c.material}
    for label, component in sorted(current_material.items()):
        was = previous_material.get(label)
        if was is None:
            events.append(
                CrossMarketEvent(
                    kind=EventKind.DISLOCATION_APPEARED,
                    label=label,
                    detail=f"material dislocation appeared at {component.delta_bps} bps",
                )
            )
            if component.from_layer is LayerType.ORACLE_REFERENCE:
                events.append(
                    CrossMarketEvent(
                        kind=EventKind.REFERENCE_DIVERGENCE,
                        label=label,
                        detail="reference/venue divergence component became material",
                    )
                )
            elif component.from_layer is LayerType.VENUE and component.to_layer is LayerType.VENUE:
                events.append(
                    CrossMarketEvent(
                        kind=EventKind.VENUE_DIVERGENCE,
                        label=label,
                        detail="cross-venue divergence component became material",
                    )
                )
        else:
            if component.delta_bps > was.delta_bps:
                events.append(
                    CrossMarketEvent(
                        kind=EventKind.DISLOCATION_WIDENED,
                        label=label,
                        detail=f"{was.delta_bps} -> {component.delta_bps} bps",
                    )
                )
            elif component.delta_bps < was.delta_bps:
                events.append(
                    CrossMarketEvent(
                        kind=EventKind.DISLOCATION_NARROWED,
                        label=label,
                        detail=f"{was.delta_bps} -> {component.delta_bps} bps",
                    )
                )
    for label, was in sorted(previous_material.items()):
        if label not in current_material:
            events.append(
                CrossMarketEvent(
                    kind=EventKind.DISLOCATION_CLEARED,
                    label=label,
                    detail=f"material dislocation cleared (was {was.delta_bps} bps)",
                )
            )
    if previous.attribution_state is not current.attribution_state:
        events.append(
            CrossMarketEvent(
                kind=EventKind.ATTRIBUTION_CHANGED,
                label="attribution",
                detail=f"{previous.attribution_state.value} -> {current.attribution_state.value}",
            )
        )
    previous_aligned = previous.timing.state is TimingState.ALIGNED
    current_aligned = current.timing.state is TimingState.ALIGNED
    if previous_aligned and not current_aligned:
        events.append(
            CrossMarketEvent(
                kind=EventKind.TIMING_ALIGNMENT_LOST, label="timing",
                detail=f"timing state {previous.timing.state.value} -> {current.timing.state.value}",
            )
        )
    if not previous_aligned and current_aligned:
        events.append(
            CrossMarketEvent(
                kind=EventKind.TIMING_ALIGNMENT_RESTORED, label="timing",
                detail=f"timing state {previous.timing.state.value} -> {current.timing.state.value}",
            )
        )
    return tuple(events)


def compare_cross_deployments(
    *,
    stack_a: CrossMarketSnapshot,
    stack_b: CrossMarketSnapshot,
    policy: CrossMarketPolicy,
) -> DislocationComponent:
    """Deterministic cross-deployment component for one economic asset.

    Both stacks must bind the SAME economic asset to DIFFERENT canonical
    deployments; membership is proven by the explicit identity bindings, never
    by ticker. The comparison uses each stack's canonical oracle/reference
    price (multiplier-adjusted) — observed dislocation only, never edge.
    """
    if stack_a.economic_asset_uid != stack_b.economic_asset_uid:
        raise CrossMarketError(
            "cross-deployment comparison requires the same economic asset UID",
            CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED,
        )
    keys_a = {k.canonical_id for k in stack_a.binding.canonical_keys}
    keys_b = {k.canonical_id for k in stack_b.binding.canonical_keys}
    if keys_a & keys_b:
        raise CrossMarketError(
            "cross-deployment comparison requires disjoint canonical deployments",
            CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
        )
    oracle_a, oracle_b = stack_a.oracle_reference, stack_b.oracle_reference
    if not _is_available(oracle_a) or not _is_available(oracle_b):
        raise CrossMarketError(
            "cross-deployment comparison requires available oracle/reference layers",
            CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
        )
    assert oracle_a is not None and oracle_b is not None
    if oracle_a.currency != oracle_b.currency:
        raise CrossMarketError(
            "cross-deployment comparison requires matching quote currencies; "
            "FX normalization for cross-deployment stacks is not authorized yet",
            CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
        )
    return _component(
        from_layer=LayerType.TOKEN,
        to_layer=LayerType.TOKEN,
        label=(
            f"TOKEN→TOKEN[cross-deployment:{oracle_a.asset_key.canonical_id}|"
            f"{oracle_b.asset_key.canonical_id}]"
        ),
        from_price=oracle_a.price,
        to_price=oracle_b.price,
        policy=policy,
        from_observed_at=oracle_a.observed_at,
        to_observed_at=oracle_b.observed_at,
        from_source=oracle_a.source,
        to_source=oracle_b.source,
    )


def build_cross_market_snapshot(
    *,
    binding: EconomicIdentityBinding,
    policy: CrossMarketPolicy,
    as_of: datetime,
    token: TokenRepresentation | None = None,
    underlying: LayerObservation | None = None,
    fx: FxObservation | None = None,
    oracle_reference: LayerObservation | None = None,
    external_oracle: LayerObservation | None = None,
    venues: Sequence[VenueObservation] = (),
    settlement: SettlementContext | None = None,
    upstream_evidence: dict | None = None,
    source_digests: dict | None = None,
    live_disclosures: dict | None = None,
    synthetic: bool = False,
    generated_at: datetime | None = None,
    git_head: str = "UNKNOWN",
    previous: CrossMarketSnapshot | None = None,
) -> CrossMarketSnapshot:
    """Build the deterministic cross-market snapshot, or raise typed errors."""
    _require_aware(as_of, "as_of")
    if generated_at is not None:
        _require_aware(generated_at, "generated_at")

    comparison_currency = policy.comparison_currency.strip().upper()

    # ---- identity and lineage validation (fail closed) --------------------
    if token is not None:
        if token.economic_asset_uid != binding.economic_asset_uid:
            raise CrossMarketError(
                "token representation binds a different economic asset UID",
                CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH,
            )
        if token.asset_key not in binding.canonical_keys:
            raise CrossMarketError(
                "token representation key is not bound to this economic asset",
                CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH,
            )
    if oracle_reference is not None:
        if oracle_reference.asset_uid is not None and (
            oracle_reference.asset_uid != binding.economic_asset_uid
        ):
            raise CrossMarketError(
                "oracle/reference observation binds a different economic asset UID",
                CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH,
            )
        if (
            oracle_reference.asset_key is not None
            and oracle_reference.asset_key not in binding.canonical_keys
        ):
            raise CrossMarketError(
                "oracle/reference observation key is not bound to this economic asset",
                CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH,
            )
    venues_canonical = _canonical_venue_order(venues)
    if len(venues_canonical) != len(venues):
        raise CrossMarketError(
            "duplicate venue observation members are not permitted",
            CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
        )
    seen_members: set[tuple[str, str, str]] = set()
    for venue in venues_canonical:
        if venue.asset_key not in binding.canonical_keys:
            raise CrossMarketError(
                f"venue {venue.venue} observation key is not bound to this economic "
                "asset; ticker equality never proves membership",
                CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH,
            )
        if venue.member_key in seen_members:
            raise CrossMarketError(
                f"duplicate venue observation member {venue.member_key}",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        seen_members.add(venue.member_key)

    multiplier_mismatch = (
        token is not None
        and oracle_reference is not None
        and oracle_reference.multiplier is not None
        and token.multiplier != oracle_reference.multiplier
    )

    # ---- currency normalization into the comparison currency --------------
    def normalize(
        price: Decimal, currency: str
    ) -> tuple[Decimal, tuple[str, str, Decimal] | None, bool]:
        """Return (converted price, fx applied, conversion unavailable)."""
        currency = currency.strip().upper()
        if currency == comparison_currency:
            return price, None, False
        rate = _fx_rate_for(fx, currency, comparison_currency, as_of=as_of, policy=policy)
        if rate is None:
            return price, None, True
        return price * rate, (currency, comparison_currency, rate), False

    # ---- timing diagnostics ----------------------------------------------
    stamps: list[tuple[str, datetime]] = []
    for label, observation in (
        ("UNDERLYING", underlying),
        ("ORACLE_REFERENCE", oracle_reference),
        ("EXTERNAL_ORACLE", external_oracle),
    ):
        if _is_available(observation) and observation.observed_at is not None:
            stamps.append((label, observation.observed_at))
    for venue in venues_canonical:
        stamps.append((f"VENUE[{venue.venue}:{venue.side.value}:{venue.notional_usd}]", venue.observed_at))
    stale_layers: list[str] = []
    for label, stamp in stamps:
        age = _decimal_seconds((as_of - stamp).total_seconds())
        if age < 0 or age > policy.stale_layer_seconds:
            stale_layers.append(label)
    if len(stamps) >= 2:
        ordered = sorted(stamps, key=lambda x: x[1])
        oldest, newest = ordered[0][1], ordered[-1][1]
        total_skew = _decimal_seconds((newest - oldest).total_seconds())
        if stale_layers:
            timing_state = TimingState.STALE_LAYER
        elif total_skew > policy.max_layer_skew_seconds:
            timing_state = TimingState.SKEWED
        else:
            timing_state = TimingState.ALIGNED
    else:
        oldest = newest = None
        total_skew = None
        timing_state = TimingState.TIMING_UNRESOLVED
    timing = StackTiming(
        state=timing_state,
        oldest=oldest,
        newest=newest,
        total_skew_seconds=total_skew,
        policy_max_layer_skew_seconds=policy.max_layer_skew_seconds,
        policy_stale_layer_seconds=policy.stale_layer_seconds,
        stale_layers=tuple(sorted(stale_layers)),
    )

    # ---- price-path components -------------------------------------------
    components: list[DislocationComponent] = []
    reasons: list[ComparabilityReason] = []

    underlying_available = _is_available(underlying)
    oracle_available = _is_available(oracle_reference)
    oracle_suppressed = (
        oracle_reference is not None
        and oracle_reference.status is LayerObservationStatus.SUPPRESSED_BY_AUTHORITY
    ) or (oracle_reference is not None and oracle_reference.usable is False)

    fx_applied: tuple[str, str, Decimal] | None = None
    underlying_normalized: Decimal | None = None
    if underlying_available:
        assert underlying is not None
        converted, applied, unavailable = normalize(underlying.price, underlying.currency)
        if unavailable:
            reasons.append(ComparabilityReason.FX_UNAVAILABLE)
        else:
            underlying_normalized = converted
            fx_applied = applied

    # FX normalization component: the FX layer's own contribution.
    if underlying_normalized is not None and fx_applied is not None:
        assert underlying is not None
        components.append(
            _component(
                from_layer=LayerType.UNDERLYING,
                to_layer=LayerType.UNDERLYING,
                label=f"UNDERLYING→UNDERLYING[fx:{fx_applied[0]}→{fx_applied[1]}]",
                from_price=underlying.price,
                to_price=underlying_normalized,
                policy=policy,
                from_observed_at=underlying.observed_at,
                to_observed_at=underlying.observed_at,
                from_source=underlying.source,
                to_source=fx.source if fx else "FX",
                fx=fx_applied,
            )
        )

    # UNDERLYING → ORACLE_REFERENCE. Suppressed reference authority (R4 says
    # the reference is not usable) suppresses every oracle-anchored component.
    if underlying_normalized is not None and oracle_available and not oracle_suppressed:
        assert underlying is not None and oracle_reference is not None
        oracle_price, oracle_fx, oracle_fx_unavailable = normalize(
            oracle_reference.price, oracle_reference.currency
        )
        if oracle_fx_unavailable:
            reasons.append(ComparabilityReason.FX_UNAVAILABLE)
        else:
            components.append(
                _component(
                    from_layer=LayerType.UNDERLYING,
                    to_layer=LayerType.ORACLE_REFERENCE,
                    label="UNDERLYING→ORACLE_REFERENCE",
                    from_price=underlying_normalized,
                    to_price=oracle_price,
                    policy=policy,
                    from_observed_at=underlying.observed_at,
                    to_observed_at=oracle_reference.observed_at,
                    from_source=underlying.source,
                    to_source=oracle_reference.source,
                    fx=oracle_fx,
                )
            )

    # ORACLE_REFERENCE → TOKEN → VENUE (or ORACLE_REFERENCE → VENUE directly
    # when the token layer carries no independent price observation).
    token_price_available = (
        token is not None
        and token.observed_price is not None
        and token.observed_at is not None
        and token.currency is not None
    )
    if oracle_available and not oracle_suppressed:
        assert oracle_reference is not None
        oracle_price, _, oracle_fx_unavailable = normalize(
            oracle_reference.price, oracle_reference.currency
        )
        if oracle_fx_unavailable:
            reasons.append(ComparabilityReason.FX_UNAVAILABLE)
        else:
            token_normalized: Decimal | None = None
            if token_price_available:
                assert token is not None
                token_price, token_fx, token_fx_unavailable = normalize(
                    token.observed_price, token.currency
                )
                if token_fx_unavailable:
                    reasons.append(ComparabilityReason.FX_UNAVAILABLE)
                else:
                    token_normalized = token_price
                    components.append(
                        _component(
                            from_layer=LayerType.ORACLE_REFERENCE,
                            to_layer=LayerType.TOKEN,
                            label="ORACLE_REFERENCE→TOKEN",
                            from_price=oracle_price,
                            to_price=token_price,
                            policy=policy,
                            from_observed_at=oracle_reference.observed_at,
                            to_observed_at=token.observed_at,
                            from_source=oracle_reference.source,
                            to_source=f"TOKEN_REPRESENTATION[{token.symbol}]",
                            fx=token_fx,
                        )
                    )
            anchor_price = token_normalized if token_normalized is not None else oracle_price
            anchor_layer = LayerType.TOKEN if token_normalized is not None else LayerType.ORACLE_REFERENCE
            anchor_time = (
                token.observed_at if token_normalized is not None else oracle_reference.observed_at
            )
            anchor_source = (
                f"TOKEN_REPRESENTATION[{token.symbol}]"
                if token_normalized is not None
                else oracle_reference.source
            )
            for venue in venues_canonical:
                venue_price, venue_fx, venue_fx_unavailable = normalize(
                    venue.price, venue.currency
                )
                if venue_fx_unavailable:
                    reasons.append(ComparabilityReason.FX_UNAVAILABLE)
                    continue
                components.append(
                    _component(
                        from_layer=anchor_layer,
                        to_layer=LayerType.VENUE,
                        label=f"{anchor_layer.value}→VENUE[{venue.venue}:{venue.side.value}:{venue.notional_usd}]",
                        from_price=anchor_price,
                        to_price=venue_price,
                        policy=policy,
                        from_observed_at=anchor_time,
                        to_observed_at=venue.observed_at,
                        from_source=anchor_source,
                        to_source=venue.source,
                        fx=venue_fx,
                    )
                )

    # VENUE → VENUE dispersion per (side, notional) across distinct venues.
    by_side_notional: dict[tuple[str, str], list[VenueObservation]] = {}
    for venue in venues_canonical:
        by_side_notional.setdefault((venue.side.value, str(venue.notional_usd)), []).append(venue)
    for (side, notional), members in sorted(by_side_notional.items()):
        distinct_venues = {m.venue for m in members}
        if len(distinct_venues) < 2:
            reasons.append(ComparabilityReason.INSUFFICIENT_MEMBERS)
            continue
        prices = sorted(m.price for m in members)
        low, high = prices[0], prices[-1]
        components.append(
            _component(
                from_layer=LayerType.VENUE,
                to_layer=LayerType.VENUE,
                label=f"VENUE→VENUE[dispersion:{side}:{notional}]",
                from_price=low,
                to_price=high,
                policy=policy,
                from_observed_at=members[0].observed_at,
                to_observed_at=members[-1].observed_at,
                from_source=members[0].source,
                to_source=members[-1].source,
            )
        )

    # ---- comparability -----------------------------------------------------
    if oracle_reference is not None and oracle_suppressed:
        reasons.append(ComparabilityReason.REFERENCE_UNAVAILABLE)
    if oracle_reference is None or not oracle_available:
        reasons.append(ComparabilityReason.REFERENCE_UNAVAILABLE)
    if underlying is None or not underlying_available:
        reasons.append(ComparabilityReason.UNDERLYING_SOURCE_UNAVAILABLE)
    if timing_state is TimingState.SKEWED:
        reasons.append(ComparabilityReason.TIMING_SKEW)
    if timing_state is TimingState.STALE_LAYER:
        reasons.append(ComparabilityReason.STALE_LAYER)
    if multiplier_mismatch:
        reasons.append(ComparabilityReason.MULTIPLIER_UNRESOLVED)
    if settlement is not None and not settlement.resolved:
        reasons.append(ComparabilityReason.SETTLEMENT_CONTEXT_UNRESOLVED)

    if token is None or oracle_reference is None:
        reasons.append(ComparabilityReason.INSUFFICIENT_MEMBERS)

    if not components and oracle_suppressed:
        comparability = ComparabilityState.SUPPRESSED
        if not reasons:
            reasons.append(ComparabilityReason.REFERENCE_UNAVAILABLE)
    elif multiplier_mismatch:
        comparability = ComparabilityState.SUPPRESSED
    elif not underlying_available and not oracle_available and not venues_canonical:
        comparability = ComparabilityState.UNAVAILABLE
        if not reasons:
            reasons.append(ComparabilityReason.INSUFFICIENT_MEMBERS)
    elif reasons:
        comparability = ComparabilityState.PARTIALLY_COMPARABLE
    else:
        comparability = ComparabilityState.COMPARABLE

    ordered_reasons = tuple(
        reason
        for reason in ComparabilityReason
        if reason in set(reasons)
    )

    # ---- attribution -------------------------------------------------------
    if comparability in (ComparabilityState.UNAVAILABLE, ComparabilityState.SUPPRESSED):
        attribution = AttributionState.ATTRIBUTION_UNAVAILABLE
    elif oracle_reference is None or not oracle_available:
        # Reference unavailable: cross-layer attribution cannot be established.
        attribution = AttributionState.ATTRIBUTION_UNAVAILABLE
    else:
        material = [c for c in components if c.material]
        if not material:
            attribution = AttributionState.NO_MATERIAL_DISLOCATION
        elif len(material) == 1:
            attribution = _COMPONENT_ATTRIBUTION[
                (material[0].from_layer, material[0].to_layer)
            ]
        else:
            attribution = AttributionState.MULTI_LAYER_DISLOCATION

    # ---- events -------------------------------------------------------------
    # Events require the current snapshot's own components/attribution/timing,
    # so the snapshot is built first and re-built with derived events when a
    # previous snapshot was supplied. The digest is computed last.
    snapshot = CrossMarketSnapshot(
        status=CrossMarketStatus.CROSS_MARKET_OK,
        economic_asset_uid=binding.economic_asset_uid,
        binding=binding,
        underlying=underlying,
        fx=fx,
        oracle_reference=oracle_reference,
        external_oracle=external_oracle,
        token=token,
        venues=venues_canonical,
        settlement=settlement,
        timing=timing,
        comparability_state=comparability,
        comparability_reasons=ordered_reasons,
        price_path=tuple(components),
        dislocation_components=tuple(components),
        attribution_state=attribution,
        events=(),
        upstream_evidence=upstream_evidence or {},
        source_digests=source_digests or {},
        live_disclosures=live_disclosures or {},
        synthetic=synthetic,
        generated_at=generated_at or as_of,
        git_head=git_head,
        comparison_currency=comparison_currency,
        r7_snapshot_digest="",
    )
    if previous is not None:
        from dataclasses import replace

        snapshot = replace(
            snapshot, events=derive_events(previous, snapshot)
        )
    digest = compute_snapshot_digest(snapshot)
    from dataclasses import replace

    snapshot = replace(snapshot, r7_snapshot_digest=digest)
    return snapshot
