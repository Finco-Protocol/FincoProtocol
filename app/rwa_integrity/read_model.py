"""RWA Integrity & Trust Intelligence V1 — representation profile +
underlying-level read model.

Read-model authority: composes existing canonical facts only:

  - identity/status   → finco_radar.venues.VenueRegistry (exact, Correction-B
                        quarantine/conflict semantics);
  - market evidence   → finco_radar.venues.intelligence.build_tokenized_intelligence
                        (freshness/basis/divergence NOT recomputed here);
  - attestation       → app.rwa_integrity.contracts evaluate_attestations.

No provider acquisition happens inside these functions; callers inject the
authorities.  One unavailable authority degrades its own evidence state —
it never crashes the profile and never fabricates a clean state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from app.rwa_integrity.contracts import (
    AttestationEvaluation,
    BackingAttestationEvidence,
    EvidenceState,
    IdentityFlag,
    evaluate_attestations,
    parse_attestation,
)

# Cross-venue divergence semantics are interpreted from the merged #179
# authority (finco_radar.venues.intelligence) — never recomputed here.
from finco_radar.venues.intelligence import build_tokenized_intelligence
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.store import VenueMarketStore

DEFAULT_ATTESTATION_STALE_DAYS = 180


@dataclass(frozen=True)
class RepresentationIntegrityProfile:
    """Integrity profile for ONE exact canonical representation."""

    canonical_asset_id: str
    platform: str
    representation_symbol: str
    network: str | None
    chain_id: int | None
    contract_address: str | None
    instrument_type: str
    registry_status: str
    source_ref: str
    market_evidence_state: str         # AVAILABLE / STALE / UNAVAILABLE
    market_source_timestamp: str | None
    reference_evidence_state: str      # AVAILABLE / UNAVAILABLE
    basis_evidence_state: str          # AVAILABLE / UNAVAILABLE / CONFLICT
    basis_bps: str | None
    attestation: AttestationEvaluation
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def identity_verified(self) -> bool:
        return self.registry_status == "ACTIVE"


@dataclass(frozen=True)
class UnderlyingIntegrityView:
    """Canonical underlying-level integrity read model."""

    canonical_asset_id: str
    generated_at: str
    representation_count: int
    active_representation_count: int
    quarantined_count: int
    conflict_count: int
    venue_count: int
    chain_count: int
    source_count: int
    market_evidence_coverage: str      # AVAILABLE / PARTIAL / UNAVAILABLE
    reference_evidence_state: str
    attestation_evidence_state: str
    dependency_flags: tuple[str, ...]
    integrity_flags: tuple[str, ...]
    representations: tuple[RepresentationIntegrityProfile, ...]
    cross_venue_divergence_state: str  # interpreted from #179 authority


def _identity_flags_for(entry: RepresentationEntryLike, registry_status: str,
                        market_state: str, basis_state: str,
                        attestation: AttestationEvaluation) -> list[str]:
    flags: list[str] = []
    if registry_status == "CONFLICT":
        flags.append(IdentityFlag.IDENTITY_CONFLICT.value)
    if registry_status == "QUARANTINED":
        flags.append(IdentityFlag.REPRESENTATION_QUARANTINED.value)
    if market_state == "UNAVAILABLE":
        flags.append(IdentityFlag.MARKET_EVIDENCE_UNAVAILABLE.value)
    elif market_state == "STALE":
        flags.append(IdentityFlag.MARKET_EVIDENCE_STALE.value)
    if basis_state != "AVAILABLE":
        flags.append(IdentityFlag.BASIS_EVIDENCE_UNAVAILABLE.value)
    if attestation.state is EvidenceState.UNAVAILABLE:
        flags.append(IdentityFlag.ATTESTATION_UNAVAILABLE.value)
    elif attestation.state is EvidenceState.STALE:
        flags.append(IdentityFlag.ATTESTATION_STALE.value)
    if attestation.reason == "ATTESTATION_SCOPE_MISMATCH":
        flags.append(IdentityFlag.ATTESTATION_SCOPE_MISMATCH.value)
    return flags


# Structural type alias to avoid importing the private registry entry class.
class RepresentationEntryLike:
    pass


def build_representation_integrity(
    resolved, *,
    registry: VenueRegistry,
    store: VenueMarketStore | None,
    intelligence: Any = None,
    attestations: list[BackingAttestationEvidence] | None = None,
    now: datetime | None = None,
    attestation_stale_days: int = DEFAULT_ATTESTATION_STALE_DAYS,
    registry_status: str | None = None,
) -> RepresentationIntegrityProfile:
    """Integrity profile for ONE exact registry representation.

    ``resolved`` is a ResolvedRepresentation from the canonical registry.
    ``intelligence`` is the pre-built TokenizedIntelligence for the
    underlying (built ONCE by the caller — never recomputed per row).
    Missing store → market_evidence_state UNAVAILABLE.
    """
    now = now or datetime.now(timezone.utc)
    entry = resolved.entry
    status = resolved.status if registry_status is None else RegistryStatus(
        registry_status)

    market_state = "UNAVAILABLE"
    market_ts = None
    basis_state = "UNAVAILABLE"
    basis_bps = None
    if intelligence is not None:
        for history in intelligence.representations:
            identity = getattr(history, "instrument_id", None)
            if identity in (entry.contract_address,
                            entry.representation_symbol.strip().upper()):
                market_state = getattr(history, "freshness_state",
                                       "UNAVAILABLE")
                observation = getattr(history, "latest", None)
                if observation is not None:
                    market_ts = observation.ts
                basis_bps = getattr(history, "basis_bps", None)
                basis_state = "AVAILABLE" if basis_bps is not None \
                    else "UNAVAILABLE"
                break

    if attestations is not None:
        # Accept raw dicts (fail-closed parse) or parsed records.
        records = [
            record if isinstance(record, BackingAttestationEvidence)
            else parse_attestation(record)
            for record in attestations
        ]
        attestation_eval = evaluate_attestations(
            records,
            canonical_asset_id=underlying_symbol_of(entry),
            chain_id=entry.chain_id,
            contract_address=entry.contract_address,
            now=now, stale_after_days=attestation_stale_days,
        )
    else:
        attestation_eval = AttestationEvaluation(
            state=EvidenceState.UNAVAILABLE, reason="ATTESTATION_UNAVAILABLE")

    effective_status = (status.value if hasattr(status, "value") else str(status))
    flags = _identity_flags_for(entry, effective_status, market_state,
                                basis_state, attestation_eval)

    return RepresentationIntegrityProfile(
        canonical_asset_id=underlying_symbol_of(entry),
        platform=entry.platform,
        representation_symbol=entry.representation_symbol,
        network=entry.network,
        chain_id=entry.chain_id,
        contract_address=entry.contract_address,
        instrument_type=entry.instrument_type,
        registry_status=effective_status,
        source_ref=entry.source_ref,
        market_evidence_state=market_state,
        market_source_timestamp=market_ts,
        reference_evidence_state=_reference_state(intelligence),
        basis_evidence_state=basis_state,
        basis_bps=basis_bps,
        attestation=attestation_eval,
        flags=tuple(flags),
    )


def underlying_symbol_of(entry) -> str:
    return str(entry.underlying_symbol or "").strip().upper()


def _reference_state(intelligence: Any) -> str:
    """Reference evidence availability interpreted from the merged #179
    authority (no recomputation): the cross-venue divergence structure
    reports reference availability when it was computable."""
    cross = getattr(intelligence, "cross_venue", None) if intelligence else None
    if cross is None:
        return "UNAVAILABLE"
    state = getattr(cross, "state", None)
    if state in ("AVAILABLE", "PARTIAL"):
        return "AVAILABLE"
    return "UNAVAILABLE"


def build_underlying_integrity(
    canonical_asset_id: str, *,
    registry: VenueRegistry,
    store: VenueMarketStore | None = None,
    attestations: list[BackingAttestationEvidence] | None = None,
    now: datetime | None = None,
    attestation_stale_days: int = DEFAULT_ATTESTATION_STALE_DAYS,
) -> UnderlyingIntegrityView:
    """Canonical underlying-level RWA integrity read model.

    Unknown canonical underlying → KeyError (fail-closed, no fabricated
    profile).  One unavailable authority (store/attestation) degrades only
    its own evidence state.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    symbol = canonical_asset_id.strip().upper()

    underlying = registry.get_underlying(symbol)
    if underlying is None:
        raise KeyError(symbol)

    # ALL representations for the underlying — including QUARANTINED and
    # CONFLICT rows, which must remain inspectable (never hidden).  Status
    # is derived per entry by the registry's own authority.
    raw_entries = registry._by_underlying.get(symbol, [])
    resolved_all = [
        SimpleNamespace(entry=entry, status=registry.status_for(entry))
        for entry in raw_entries
    ]
    active = [r for r in resolved_all
              if r.status is RegistryStatus.ACTIVE]

    # Market intelligence built ONCE via the merged #179 authority.
    intelligence = None
    store_unavailable = False
    try:
        if store is not None and active:
            intelligence = build_tokenized_intelligence(
                symbol, registry=registry, store=store, as_of=now,
                include_points=False)
    except Exception:  # noqa: BLE001 — market authority unavailable degrades
        store_unavailable = True

    profiles = []
    for resolved in resolved_all:
        profiles.append(build_representation_integrity(
            resolved, registry=registry, store=store,
            intelligence=intelligence, attestations=attestations,
            now=now, attestation_stale_days=attestation_stale_days,
            registry_status=resolved.status.value))

    venues = {p.platform for p in profiles}
    # Chain diversity uses network identity when chain_id is unavailable —
    # non-EVM chains (e.g. Solana) legitimately have no chain_id.
    chains = {p.chain_id if p.chain_id is not None else p.network
              for p in profiles
              if p.chain_id is not None or p.network is not None}
    sources = {p.source_ref.split("#")[0] for p in profiles if p.source_ref}

    dependency_flags: list[str] = []
    if len(profiles) == 1:
        dependency_flags.append(IdentityFlag.SINGLE_REPRESENTATION_DEPENDENCY.value)
    if len(venues) <= 1:
        dependency_flags.append(IdentityFlag.SINGLE_VENUE_DEPENDENCY.value)
    if len(chains) <= 1:
        dependency_flags.append(IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value)
    if len(sources) <= 1:
        dependency_flags.append(IdentityFlag.SINGLE_SOURCE_DEPENDENCY.value)

    priced_active = [p for p in profiles
                     if p.market_evidence_state == "AVAILABLE"
                     and p.registry_status == "ACTIVE"]
    if active and len(priced_active) == len(active):
        market_coverage = "AVAILABLE"
    elif priced_active:
        market_coverage = "PARTIAL"
    else:
        market_coverage = "UNAVAILABLE"

    reference_state = ("AVAILABLE" if any(
        p.reference_evidence_state == "AVAILABLE" for p in profiles)
        else "UNAVAILABLE")

    attestation_states = {p.attestation.state for p in profiles}
    if EvidenceState.VERIFIED in attestation_states:
        attestation_state = "VERIFIED"
    elif EvidenceState.STALE in attestation_states:
        attestation_state = "STALE"
    else:
        attestation_state = "UNAVAILABLE"

    integrity_flags: list[str] = []
    for profile in profiles:
        integrity_flags.extend(profile.flags)
    integrity_flags.extend(dependency_flags)
    if attestation_state == "UNAVAILABLE":
        integrity_flags.append(IdentityFlag.ATTESTATION_UNAVAILABLE.value)
    elif attestation_state == "STALE":
        integrity_flags.append(IdentityFlag.ATTESTATION_STALE.value)
    # dedupe, stable order
    integrity_flags = tuple(dict.fromkeys(integrity_flags))

    cross_state = "UNAVAILABLE"
    cross = getattr(intelligence, "cross_venue", None) if intelligence else None
    if cross is not None:
        cross_state = str(getattr(cross, "state", "UNAVAILABLE"))

    quarantined = sum(1 for p in profiles
                      if p.registry_status == RegistryStatus.QUARANTINED.value)
    conflicts = sum(1 for p in profiles
                    if p.registry_status == RegistryStatus.CONFLICT.value)

    return UnderlyingIntegrityView(
        canonical_asset_id=symbol,
        generated_at=now.isoformat(),
        representation_count=len(profiles),
        active_representation_count=len(active),
        quarantined_count=quarantined,
        conflict_count=conflicts,
        venue_count=len(venues),
        chain_count=len(chains),
        source_count=len(sources),
        market_evidence_coverage=market_coverage,
        reference_evidence_state=reference_state,
        attestation_evidence_state=attestation_state,
        dependency_flags=tuple(sorted(set(dependency_flags))),
        integrity_flags=integrity_flags,
        representations=tuple(profiles),
        cross_venue_divergence_state=cross_state,
    )


def list_integrity_profiles(
    registry: VenueRegistry, *, store: VenueMarketStore | None = None,
    attestations: list[BackingAttestationEvidence] | None = None,
    now: datetime | None = None, limit: int | None = None,
) -> list[UnderlyingIntegrityView]:
    """Canonical integrity profiles for every underlying with active
    representations (deterministic order).  No provider acquisition."""
    views = []
    for symbol in sorted(registry._underlyings):
        resolved = registry.representations_for_underlying(symbol)
        if not resolved:
            continue
        views.append(build_underlying_integrity(
            symbol, registry=registry, store=store, attestations=attestations,
            now=now))
        if limit is not None and len(views) >= limit:
            break
    return views
