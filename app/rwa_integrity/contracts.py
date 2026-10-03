"""RWA Integrity & Trust Intelligence V1 — typed contracts.

Evidence states and the backing/attestation evidence contract for the RWA
Integrity vertical.  Evidence vocabulary is factual, not evaluative:

  VERIFIED      — an approved source affirmatively proves the claim.
  PARTIAL       — some approved evidence exists but coverage is incomplete.
  UNAVAILABLE   — no approved evidence exists (unknown ≠ negative).
  STALE         — evidence exists but is past its freshness authority.
  CONFLICT      — approved sources disagree on the claim.
  QUARANTINED   — the subject representation is registry-quarantined.
  NOT_APPLICABLE— the claim does not apply to this representation shape.

Missing evidence is never mapped to FAILED/FALSE/ZERO: unavailable is
unknown, not negative.

Attestation timestamps follow the foundation clock authority: published_at
is the SOURCE evidence time; observed_at is FINCO's ingestion/verification
time; the two are never substituted.  Evidence without a usable source
timestamp is not presented as current.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    QUARANTINED = "QUARANTINED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class IdentityFlag(str, Enum):
    """Deterministic integrity flags — facts, not subjective language."""

    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    REPRESENTATION_QUARANTINED = "REPRESENTATION_QUARANTINED"
    MARKET_EVIDENCE_UNAVAILABLE = "MARKET_EVIDENCE_UNAVAILABLE"
    MARKET_EVIDENCE_STALE = "MARKET_EVIDENCE_STALE"
    REFERENCE_EVIDENCE_UNAVAILABLE = "REFERENCE_EVIDENCE_UNAVAILABLE"
    BASIS_EVIDENCE_UNAVAILABLE = "BASIS_EVIDENCE_UNAVAILABLE"
    SINGLE_VENUE_DEPENDENCY = "SINGLE_VENUE_DEPENDENCY"
    SINGLE_CHAIN_DEPENDENCY = "SINGLE_CHAIN_DEPENDENCY"
    SINGLE_SOURCE_DEPENDENCY = "SINGLE_SOURCE_DEPENDENCY"
    SINGLE_REPRESENTATION_DEPENDENCY = "SINGLE_REPRESENTATION_DEPENDENCY"
    ATTESTATION_UNAVAILABLE = "ATTESTATION_UNAVAILABLE"
    ATTESTATION_STALE = "ATTESTATION_STALE"
    ATTESTATION_SCOPE_MISMATCH = "ATTESTATION_SCOPE_MISMATCH"


@dataclass(frozen=True)
class BackingAttestationEvidence:
    """One independently sourced RWA backing/attestation evidence record.

    Scope binding is exact: the record applies to (canonical_asset_id,
    chain_id, contract_address) when present.  A generic issuer statement
    does NOT automatically prove backing for every representation by that
    entity, and cross-chain coverage is never inferred: an attestation that
    does not name this exact contract/chain does not bind to it.
    """

    canonical_asset_id: str            # exact canonical underlying symbol
    chain_id: int | None               # exact chain where applicable
    contract_address: str | None       # exact contract where applicable

    issuer_identity: str | None
    issuer_legal_entity: str | None
    custodian: str | None
    reserve_description: str | None
    attestation_provider: str | None
    attestation_report_id: str | None
    coverage_statement: str | None

    published_at: str | None           # SOURCE evidence time (provider)
    observed_at: str | None            # FINCO ingestion/verification time
    valid_through: str | None          # explicit expiry when source states it

    source_uri: str
    source_type: str                   # e.g. issuer-website / audit-firm / registry
    evidence_status: EvidenceState = EvidenceState.UNAVAILABLE
    scope_note: str | None = None      # source-native scope statement

    def covers(self, *, canonical_asset_id: str, chain_id: int | None,
               contract_address: str | None) -> bool:
        """Exact scope binding.  Every provided scope dimension must match;
        an attestation that is silent on a dimension the caller requires
        (contract/chain) does NOT bind."""
        if self.canonical_asset_id.upper() != canonical_asset_id.upper():
            return False
        if chain_id is not None and self.chain_id != chain_id:
            return False
        if (contract_address is not None
                and (self.contract_address or "").lower()
                != contract_address.lower()):
            return False
        return True


def parse_attestation(raw: dict[str, Any]) -> BackingAttestationEvidence:
    """Strictly validate one raw attestation record (fail-closed typing)."""
    asset = raw.get("canonical_asset_id")
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("attestation requires canonical_asset_id")
    provider = raw.get("attestation_provider")
    published = raw.get("published_at")
    if published is not None:
        try:
            parsed = datetime.fromisoformat(str(published))
            if parsed.tzinfo is None:
                state = EvidenceState.UNAVAILABLE  # naive → not presentable current
        except ValueError:
            state = EvidenceState.UNAVAILABLE  # unparseable → not presentable
    # No usable published_at → the record stays UNAVAILABLE (not current):
    # enforced by the freshness authority, not by dropping the record.
    state = EvidenceState(raw.get("evidence_status", EvidenceState.UNAVAILABLE))
    if not isinstance(provider, str) or not provider.strip() or not published:
        state = EvidenceState.UNAVAILABLE
    return BackingAttestationEvidence(
        canonical_asset_id=asset.strip().upper(),
        chain_id=raw.get("chain_id") if isinstance(raw.get("chain_id"), int) else None,
        contract_address=(
            str(raw["contract_address"]).lower()
            if isinstance(raw.get("contract_address"), str)
            and raw["contract_address"] else None),
        issuer_identity=raw.get("issuer_identity"),
        issuer_legal_entity=raw.get("issuer_legal_entity"),
        custodian=raw.get("custodian"),
        reserve_description=raw.get("reserve_description"),
        attestation_provider=provider if isinstance(provider, str) else None,
        attestation_report_id=(
            str(raw["attestation_report_id"])
            if raw.get("attestation_report_id") else None),
        coverage_statement=raw.get("coverage_statement"),
        published_at=str(published) if published else None,
        observed_at=str(raw["observed_at"]) if raw.get("observed_at") else None,
        valid_through=str(raw["valid_through"]) if raw.get("valid_through") else None,
        source_uri=str(raw.get("source_uri") or ""),
        source_type=str(raw.get("source_type") or "unknown"),
        evidence_status=state,
        scope_note=raw.get("scope_note"),
    )


@dataclass(frozen=True)
class AttestationEvaluation:
    """Typed freshness/scope evaluation of the best attestation for one
    exact representation.  ``state`` is the presented evidence state."""

    state: EvidenceState
    reason: str | None = None          # typed unavailability/stale reason
    record: BackingAttestationEvidence | None = None


def evaluate_attestations(
    records: list[BackingAttestationEvidence], *,
    canonical_asset_id: str, chain_id: int | None,
    contract_address: str | None,
    now: datetime, stale_after_days: int = 180,
) -> AttestationEvaluation:
    """Evaluate the best attestation for one exact representation.

    Fail-closed rules:
      - no in-scope record            → UNAVAILABLE (unknown, not negative);
      - scope mismatch                → the record does not bind;
      - no usable published_at        → UNAVAILABLE (never presented current);
      - published_at + stale_after    → STALE;
      - valid_through in the past     → STALE;
      - otherwise                     → VERIFIED (state per record).
    """
    parsed_records = []
    for record in records:
        if isinstance(record, BackingAttestationEvidence):
            parsed_records.append(record)
        else:
            try:
                parsed_records.append(parse_attestation(record))
            except (ValueError, TypeError):
                pass  # malformed records are skipped, not fatal
    in_scope = [
        record for record in parsed_records
        if record.covers(canonical_asset_id=canonical_asset_id,
                         chain_id=chain_id,
                         contract_address=contract_address)
    ]
    if not in_scope:
        return AttestationEvaluation(
            state=EvidenceState.UNAVAILABLE,
            reason="ATTESTATION_SCOPE_MISMATCH" if records
            else "ATTESTATION_UNAVAILABLE")

    best: BackingAttestationEvidence | None = None
    best_published: datetime | None = None
    for record in in_scope:
        if record.evidence_status is EvidenceState.UNAVAILABLE:
            continue
        if not record.published_at:
            continue
        try:
            published = datetime.fromisoformat(record.published_at)
        except ValueError:
            continue
        if published.tzinfo is None:
            continue  # naive evidence time is not presentable as current
        if best_published is None or published > best_published:
            best, best_published = record, published

    if best is None:
        return AttestationEvaluation(
            state=EvidenceState.UNAVAILABLE, reason="ATTESTATION_UNAVAILABLE")

    expiry = best.valid_through
    if expiry:
        try:
            if datetime.fromisoformat(expiry) < now:
                return AttestationEvaluation(
                    state=EvidenceState.STALE, reason="ATTESTATION_STALE",
                    record=best)
        except ValueError:
            pass  # unparseable expiry never fabricates currency
    if best_published is not None:
        age_days = (now - best_published).total_seconds() / 86400
        if age_days > stale_after_days:
            return AttestationEvaluation(
                state=EvidenceState.STALE, reason="ATTESTATION_STALE",
                record=best)
    return AttestationEvaluation(
        state=best.evidence_status if best.evidence_status is not None
        else EvidenceState.VERIFIED,
        record=best)
