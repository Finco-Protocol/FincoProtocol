"""Shared RWA Integrity read adapter for the Unified Crypto Terminal.

This module owns no market mathematics and performs no provider acquisition.
It composes the approved RWA Integrity read model with the same canonical
registry, persisted VenueMarketStore, and persisted reference-evidence reader
used by Tokenized Markets.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.rwa_integrity.read_model import build_underlying_integrity

_UNSET = object()


def _canonical_reference_reader(store, *, as_of: datetime):
    from app.radar_ui.tokenized_router import _persisted_reference_reader
    return _persisted_reference_reader(store, as_of=as_of)


def build_view(
    canonical_asset_id: str, *,
    now: datetime | None = None,
    registry=None,
    store: Any = _UNSET,
    reference_evidence_reader=None,
):
    """Build one acquisition-free Integrity profile.

    Browser composition may pass the already-resolved registry/store/reference
    reader so the exact #181 request context is reused.  API callers use the
    same canonical adapters through the defaults below.
    """
    now = now or datetime.now(timezone.utc)
    if registry is None:
        from app.crypto_terminal.tokenized_read import registry as load_registry
        registry = load_registry()
    if store is _UNSET:
        try:
            from app.crypto_terminal.tokenized_read import store as load_store
            store = load_store()
        except Exception:
            store = None
    if reference_evidence_reader is None:
        try:
            reference_evidence_reader = _canonical_reference_reader(
                store, as_of=now)
        except Exception:
            reference_evidence_reader = None
    return build_underlying_integrity(
        canonical_asset_id,
        registry=registry,
        store=store,
        attestations=None,  # no approved external attestation authority in V1
        now=now,
        reference_evidence_reader=reference_evidence_reader,
    )


def _identity_state(view) -> str:
    """Compact factual identity summary, not a score or recommendation."""
    if view.conflict_count:
        return "CONFLICT"
    if view.active_representation_count and view.quarantined_count:
        return "PARTIAL"
    if view.active_representation_count:
        return "AVAILABLE"
    if view.quarantined_count:
        return "QUARANTINED"
    return "UNAVAILABLE"


def as_data(view) -> dict[str, Any]:
    """JSON/template-safe factual envelope body; missing values stay null."""
    representations = []
    for rep in view.representations:
        attestation = rep.attestation
        representations.append({
            "canonical_asset_id": rep.canonical_asset_id,
            "platform": rep.platform,
            "representation_symbol": rep.representation_symbol,
            "network": rep.network,
            "chain_id": rep.chain_id,
            "contract_address": rep.contract_address,
            "instrument_type": rep.instrument_type,
            "registry_status": rep.registry_status,
            "market_evidence_state": rep.market_evidence_state,
            "market_source_timestamp": rep.market_source_timestamp,
            "reference_evidence_state": rep.reference_evidence_state,
            "basis_evidence_state": rep.basis_evidence_state,
            "basis_bps": rep.basis_bps,
            "attestation_state": attestation.state.value,
            "attestation_reason": attestation.reason,
            "flags": list(rep.flags),
        })
    return {
        "generated_at": view.generated_at,
        "identity_state": _identity_state(view),
        "representation_count": view.representation_count,
        "active_representation_count": view.active_representation_count,
        "quarantined_count": view.quarantined_count,
        "conflict_count": view.conflict_count,
        "venue_count": view.venue_count,
        "chain_count": view.chain_count,
        "source_count": view.source_count,
        "market_evidence_coverage": view.market_evidence_coverage,
        "reference_evidence_state": view.reference_evidence_state,
        "attestation_evidence_state": view.attestation_evidence_state,
        "dependency_flags": list(view.dependency_flags),
        "integrity_flags": list(view.integrity_flags),
        "cross_venue_divergence_state": view.cross_venue_divergence_state,
        "representations": representations,
    }


def detail_data(canonical_asset_id: str, **kwargs) -> dict[str, Any]:
    return as_data(build_view(canonical_asset_id, **kwargs))
