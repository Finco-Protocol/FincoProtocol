"""RWA Integrity & Trust Intelligence V1 — representation profile +
underlying-level read model (Correction A).

Read-model authority: composes existing canonical facts only.
Identity binding uses COMPLETE representation identity:
canonical_asset_id + venue_id + instrument_id + representation_type.
No first-match-by-instrument shortcut. Dependency intelligence counts
only ACTIVE representations.
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

from finco_radar.venues.intelligence import build_tokenized_intelligence
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.store import VenueMarketStore

DEFAULT_ATTESTATION_STALE_DAYS = 180


class UnknownCanonicalUnderlying(KeyError):
    """The requested canonical underlying does not exist in the registry
    (typed, fail-closed — raised before any reference/provider/store read)."""


@dataclass(frozen=True)
class RepresentationIntegrityProfile:
    canonical_asset_id: str
    platform: str
    representation_symbol: str
    network: str | None
    chain_id: int | None
    contract_address: str | None
    instrument_type: str
    registry_status: str
    source_ref: str
    market_evidence_state: str
    market_source_timestamp: str | None
    reference_evidence_state: str
    basis_evidence_state: str
    basis_bps: str | None
    attestation: AttestationEvaluation
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def identity_verified(self) -> bool:
        return self.registry_status == "ACTIVE"


@dataclass(frozen=True)
class UnderlyingIntegrityView:
    canonical_asset_id: str
    generated_at: str
    representation_count: int
    active_representation_count: int
    quarantined_count: int
    conflict_count: int
    venue_count: int
    chain_count: int
    source_count: int
    market_evidence_coverage: str
    reference_evidence_state: str
    attestation_evidence_state: str
    dependency_flags: tuple[str, ...]
    integrity_flags: tuple[str, ...]
    representations: tuple[RepresentationIntegrityProfile, ...]
    cross_venue_divergence_state: str

def _expected_identity(entry) -> tuple[str, str, str]:
    venue_id = entry.network or entry.platform
    instrument_id = (entry.contract_address
                     or entry.representation_symbol.strip().upper())
    return venue_id, instrument_id, entry.instrument_type


def _identity_flags_for(registry_status: str, market_state: str,
                        basis_state: str,
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


def build_representation_integrity(
    resolved, *,
    registry: VenueRegistry,
    store: VenueMarketStore | None,
    intelligence: Any = None,
    attestations: list[BackingAttestationEvidence] | None = None,
    now: datetime | None = None,
    attestation_stale_days: int = DEFAULT_ATTESTATION_STALE_DAYS,
    registry_status: str | None = None,
    reference_evidence: dict[str, Any] | None = None,
) -> RepresentationIntegrityProfile:
    now = now or datetime.now(timezone.utc)
    entry = resolved.entry
    status = (RegistryStatus(registry_status) if registry_status
              else resolved.status)
    effective_status = (status.value if hasattr(status, "value")
                        else str(status))

    venue_id, instrument_id, rep_type = _expected_identity(entry)
    underlying_symbol = str(entry.underlying_symbol or "").strip().upper()

    market_state = "UNAVAILABLE"
    market_source_ts = None
    basis_state = "UNAVAILABLE"
    basis_bps = None
    if intelligence is not None:
        for history in intelligence.representations:
            if (history.venue_id != venue_id
                    or history.instrument_id != instrument_id
                    or history.representation_type != rep_type):
                continue
            market_state = history.current_state
            basis_bps = history.latest_basis_bps
            basis_state = "AVAILABLE" if basis_bps is not None else "UNAVAILABLE"
            break

    if market_state != "UNAVAILABLE" and store is not None:
        try:
            latest = store.get_latest_for_identity(
                underlying_symbol, venue_id, instrument_id, rep_type)
            if latest is not None:
                market_source_ts = latest.ts
        except Exception:
            pass

    if reference_evidence is not None and reference_evidence.get("price") is not None:
        reference_state = "AVAILABLE"
    else:
        reference_state = "UNAVAILABLE"

    if attestations is not None:
        records = [
            record if isinstance(record, BackingAttestationEvidence)
            else parse_attestation(record)
            for record in attestations
        ]
        attestation_eval = evaluate_attestations(
            records,
            canonical_asset_id=underlying_symbol,
            chain_id=entry.chain_id,
            contract_address=entry.contract_address,
            now=now, stale_after_days=attestation_stale_days,
        )
    else:
        attestation_eval = AttestationEvaluation(
            state=EvidenceState.UNAVAILABLE, reason="ATTESTATION_UNAVAILABLE")

    flags = _identity_flags_for(effective_status, market_state,
                                basis_state, attestation_eval)

    return RepresentationIntegrityProfile(
        canonical_asset_id=underlying_symbol,
        platform=entry.platform,
        representation_symbol=entry.representation_symbol,
        network=entry.network,
        chain_id=entry.chain_id,
        contract_address=entry.contract_address,
        instrument_type=entry.instrument_type,
        registry_status=effective_status,
        source_ref=entry.source_ref,
        market_evidence_state=market_state,
        market_source_timestamp=market_source_ts,
        reference_evidence_state=reference_state,
        basis_evidence_state=basis_state,
        basis_bps=basis_bps,
        attestation=attestation_eval,
        flags=tuple(flags),
    )


def _aggregate_attestation_state(profiles) -> str:
    active_attestations = [
        p.attestation for p in profiles
        if p.registry_status == "ACTIVE"
    ]
    if not active_attestations:
        return EvidenceState.UNAVAILABLE.value
    states = [a.state for a in active_attestations]
    if EvidenceState.CONFLICT in states:
        return EvidenceState.CONFLICT.value
    verified_count = sum(1 for s in states if s is EvidenceState.VERIFIED)
    stale_count = sum(1 for s in states if s is EvidenceState.STALE)
    if verified_count == len(states):
        return EvidenceState.VERIFIED.value
    if verified_count > 0:
        return EvidenceState.PARTIAL.value
    if stale_count > 0:
        return EvidenceState.STALE.value
    return EvidenceState.UNAVAILABLE.value


def build_underlying_integrity(
    canonical_asset_id: str, *,
    registry: VenueRegistry,
    store: VenueMarketStore | None = None,
    attestations: list[BackingAttestationEvidence] | None = None,
    now: datetime | None = None,
    attestation_stale_days: int = DEFAULT_ATTESTATION_STALE_DAYS,
    reference_evidence_reader: Callable[[str], dict[str, Any] | None] | None = None,
) -> UnderlyingIntegrityView:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    symbol = canonical_asset_id.strip().upper()

    underlying = registry.get_underlying(symbol)
    if underlying is None:
        raise UnknownCanonicalUnderlying(symbol)

    raw_entries = registry._by_underlying.get(symbol, [])
    resolved_all = [
        SimpleNamespace(entry=entry, status=registry.status_for(entry))
        for entry in raw_entries
    ]
    active_resolved = [r for r in resolved_all
                       if r.status is RegistryStatus.ACTIVE]

    intelligence = None
    try:
        if store is not None and active_resolved:
            intelligence = build_tokenized_intelligence(
                symbol, registry=registry, store=store, as_of=now,
                include_points=False)
    except Exception:
        intelligence = None

    reference_evidence = None
    if reference_evidence_reader is not None:
        try:
            reference_evidence = reference_evidence_reader(symbol)
        except Exception:
            reference_evidence = None

    profiles = []
    for resolved in resolved_all:
        profiles.append(build_representation_integrity(
            resolved, registry=registry, store=store,
            intelligence=intelligence, attestations=attestations,
            now=now, attestation_stale_days=attestation_stale_days,
            reference_evidence=reference_evidence))

    active_profiles = [p for p in profiles
                       if p.registry_status == RegistryStatus.ACTIVE.value]
    venues = {p.platform for p in active_profiles}
    chains = {(p.chain_id if p.chain_id is not None else p.network)
              for p in active_profiles
              if p.chain_id is not None or p.network is not None}
    sources = {p.source_ref.split("#")[0] for p in active_profiles
               if p.source_ref}

    dependency_flags: list[str] = []
    if len(active_profiles) == 1:
        dependency_flags.append(
            IdentityFlag.SINGLE_REPRESENTATION_DEPENDENCY.value)
    if len(venues) <= 1:
        dependency_flags.append(IdentityFlag.SINGLE_VENUE_DEPENDENCY.value)
    if len(chains) <= 1:
        dependency_flags.append(IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value)
    if len(sources) <= 1:
        dependency_flags.append(IdentityFlag.SINGLE_SOURCE_DEPENDENCY.value)

    priced_active = [p for p in active_profiles
                     if p.market_evidence_state == "AVAILABLE"]
    if active_profiles and len(priced_active) == len(active_profiles):
        market_coverage = "AVAILABLE"
    elif priced_active:
        market_coverage = "PARTIAL"
    else:
        market_coverage = "UNAVAILABLE"

    reference_state = ("AVAILABLE" if reference_evidence is not None
                       and reference_evidence.get("price") is not None
                       else "UNAVAILABLE")

    attestation_state = _aggregate_attestation_state(profiles)

    integrity_flags: list[str] = []
    for profile in profiles:
        integrity_flags.extend(profile.flags)
    integrity_flags.extend(dependency_flags)
    if attestation_state == "UNAVAILABLE":
        integrity_flags.append(IdentityFlag.ATTESTATION_UNAVAILABLE.value)
    elif attestation_state == "STALE":
        integrity_flags.append(IdentityFlag.ATTESTATION_STALE.value)
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
        active_representation_count=len(active_profiles),
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
