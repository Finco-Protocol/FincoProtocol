"""FINCO Verified Assets V1 — composition engine.

Principle: NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION

This module assembles FINCO_VERIFIED_ASSET_V1 records by composing
existing authorities. It NEVER calls financial-engine entry points or
duplicates any calculation formula.

Composition authority chain:
  1. model section   ← WorkspaceStateRecord (persisted Last Run fields)
  2. verify section  ← build_run_certificate() — FINCO_RUN_CERTIFICATE_V1
  3. market section  ← exact run binding + canonical Radar identity/authority
                       (absent in production: MODEL_BINDING_UNAVAILABLE)
  4. protocol section ← UTILITY_REGISTRY

Fail-closed:
  - No committed run → UNAVAILABLE (propagates RunCertificateUnavailableError)
  - Legacy lineage  → UNAVAILABLE
  - Missing composite_hash / snapshot_id / timestamp → UNAVAILABLE
  - Market binding unavailable → MODEL_ONLY (truthful, not an error)
  - no approved run-bound market attestation → MODEL_ONLY

Markers:
  FINCO_P5_COMPOSED_NOT_CALCULATED
  FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
  FINCO_P5_CERTIFICATE_AUTHORITY_REUSED
  FINCO_P5_ELIGIBILITY_DETERMINISTIC
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.persistence.records import WorkspaceStateRecord, ProjectRecord

from app.verified.contracts import (
    VERIFIED_ASSET_SCHEMA,
    VerifiedAssetStatus,
    VerifiedAssetDefinition,
    STATUS_DISPLAY,
)


def _model_section(ws: "WorkspaceStateRecord") -> dict[str, Any]:
    """Compose the model section from persisted Last Run fields only."""
    summary = ws.last_runtime_summary or {}
    headline = {
        k: summary.get(k)
        for k in (
            "project_irr",
            "equity_irr",
            "sponsor_irr",
            "min_dscr",
            "senior_debt_keur",
            "total_capex_keur",
        )
    }
    return {
        "any_run_committed": ws.any_run_committed,
        "headline_outputs": headline,
        "last_runtime_at": (
            ws.last_runtime_at.isoformat() if ws.last_runtime_at else None
        ),
        "last_runtime_origin": ws.last_runtime_origin,
    }


def _verify_section(certificate: dict[str, Any]) -> dict[str, Any]:
    """Compose the verify section from an already-built Run Certificate."""
    return {
        "certificate_id": certificate.get("certificate_id"),
        "certificate_digest_sha256": certificate.get("certificate_digest_sha256"),
        "committed_at": certificate.get("run", {}).get("committed_at"),
        "snapshot_id": certificate.get("run", {}).get("snapshot_id"),
        "engine_version": certificate.get("model", {}).get("engine_version"),
        "composite_hash": certificate.get("identity", {}).get("composite_hash"),
        "assumptions_sha256": certificate.get("identity", {}).get("assumptions_sha256"),
        "outputs_sha256": certificate.get("identity", {}).get("outputs_sha256"),
    }


def _protocol_section(asset_def: VerifiedAssetDefinition) -> dict[str, Any]:
    """Compose the protocol section from UTILITY_REGISTRY identifiers."""
    from app.protocol.utility_registry import (
        FINCO_COMPUTE,
        FINCO_VERIFY_PUBLISH,
        FINCO_INTELLIGENCE,
        UTILITY_REGISTRY,
    )
    return {
        "utilities": {
            FINCO_COMPUTE: UTILITY_REGISTRY[FINCO_COMPUTE].display_name,
            FINCO_VERIFY_PUBLISH: UTILITY_REGISTRY[FINCO_VERIFY_PUBLISH].display_name,
            FINCO_INTELLIGENCE: UTILITY_REGISTRY[FINCO_INTELLIGENCE].display_name,
        },
        "asset_type": asset_def.asset_type,
        "template_source": asset_def.template_source,
    }


def build_verified_asset(
    asset_def: VerifiedAssetDefinition,
    project_record: "ProjectRecord",
    ws: "WorkspaceStateRecord",
    *,
    authority_bundle: "VerifiedAuthorityBundle | None" = None,
    as_of: datetime | None = None,
    verification_policy: "VerificationPolicy | None" = None,
) -> dict[str, Any]:
    """Assemble a FINCO_VERIFIED_ASSET_V1 record.

    Returns the full composed record.

    FINCO_P5_COMPOSED_NOT_CALCULATED
    FINCO_P5_CERTIFICATE_AUTHORITY_REUSED
    """
    from app.verify.run_certificate import (
        RunCertificateUnavailableError,
        build_run_certificate,
    )
    from app.verified.authority import (
        VerifiedAuthorityBundle, VerificationPolicy, evaluate_authorities,
    )

    # Attempt certificate build — fail-closed on any error.
    try:
        certificate = build_run_certificate(ws, project_record)
        cert_error = None
    except RunCertificateUnavailableError as exc:
        certificate = None
        cert_error = {"code": exc.code, "reason": exc.reason}
    except Exception as exc:
        certificate = None
        cert_error = {"code": "INTERNAL_ERROR", "reason": str(exc)}

    if certificate is None:
        # UNAVAILABLE — certificate not producible.
        return {
            "schema": VERIFIED_ASSET_SCHEMA,
            "asset_id": asset_def.asset_id,
            "display_name": asset_def.display_name,
            "asset_type": asset_def.asset_type,
            "description": asset_def.description,
            "status": VerifiedAssetStatus.UNAVAILABLE,
            "status_display": STATUS_DISPLAY[VerifiedAssetStatus.UNAVAILABLE],
            "model": _model_section(ws),
            "verify": None,
            "market": None,
            "market_observation": None,
            "identity": None,
            "evidence": None,
            "verification": {"status": VerifiedAssetStatus.UNAVAILABLE.value,
                             "reason": cert_error["code"]},
            "protocol": _protocol_section(asset_def),
            "error": cert_error,
        }

    # Production has no approved model-market binding for either reference
    # asset. This is truthful MODEL_ONLY, not an error or a market identity.
    # FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
    #
    # VERIFIED STATE GATE — all six authorities required, fail-closed:
    #   1. valid committed FINCO Last Run          (certificate above)
    #   2. valid P3 Run Certificate                (certificate above)
    #   3. canonical model ↔ market economic identity reconciliation
    #   4. no identity conflict/mismatch (exact Robinhood AssetKey)
    #   5. canonical Radar underlying and independent token references
    #   6. canonical B1.0/B1.3 AuthoritySnapshot.premium AVAILABLE
    #
    # A bare market-identity binding satisfies ONLY authority 3 (partial).
    # Authorities 4–6 require full Radar evidence and bound canonical premium,
    # which is not yet available for any V1 asset.
    # A discovered binding alone MUST NOT produce VERIFIED.
    # Until all six authorities are available: fail closed to MODEL_ONLY.
    #
    # VERIFIED_ASSET_BINDING_ALONE_NOT_VERIFIED
    # VERIFIED_ASSET_VERIFIED_REQUIRES_FULL_RECONCILIATION
    # VERIFIED_ASSET_PREMIUM_REQUIRED_FOR_VERIFIED
    if authority_bundle is not None and as_of is None:
        raise ValueError("explicit as_of required for market freshness evaluation")
    status_value, reason = evaluate_authorities(
        asset_id=asset_def.asset_id,
        project_code=project_record.project_code,
        certificate=certificate,
        bundle=authority_bundle,
        as_of=as_of or ws.last_runtime_at,
        policy=verification_policy or VerificationPolicy(),
    )
    status = VerifiedAssetStatus(status_value)
    eligible = status is VerifiedAssetStatus.VERIFIED
    market_section = None
    evidence_section = None
    identity_section = None
    canonical_authority_section = None
    if eligible:
        binding = authority_bundle.binding
        observed = authority_bundle.market
        market_section = {
            "state": observed.state.value,
            "provider": observed.source,
            "provider_id": observed.provider_id,
            "scope": observed.market_scope,
            "observed_at": observed.observed_at.isoformat(),
            "price_usd": str(observed.price_usd) if observed.price_usd is not None else None,
            "execution": "UNAVAILABLE",
        }
        evidence_section = {
            "evidence_id": binding.evidence_id,
            "source": binding.source,
            "observed_at": binding.observed_at.isoformat(),
            "run_certificate_digest_sha256": binding.certificate_digest_sha256,
        }
        identity_section = {
            "economic_asset_uid": binding.economic_asset_uid,
            "chain_id": binding.deployment.chain_id,
            "contract_address": binding.deployment.contract_address,
            "authority_source": authority_bundle.identity.authority_source,
            "observed_at": authority_bundle.identity.observed_at.isoformat(),
        }
        radar = authority_bundle.radar
        canonical_authority_section = {
            "registry_source": radar.registry_source,
            "registry_observed_at": radar.registry_observed_at.isoformat(),
            "underlying_reference": {
                "state": radar.underlying.state.value,
                "source": radar.underlying.source,
                "observed_at": radar.underlying.observed_at.isoformat(),
                "price_usd_per_token": str(radar.underlying.price_usd_per_token),
            },
            "independent_token_reference": {
                "state": radar.token.state.value,
                "source": radar.token.source,
                "observed_at": radar.token.observed_at.isoformat(),
                "price_usd_per_token": str(radar.token.price_usd_per_token),
            },
            "premium": {
                "state": radar.premium.state.value,
                "value_bps": str(radar.premium.value_bps),
                "sources": list(radar.premium.sources),
                "observed_at": [stamp.isoformat() for stamp in radar.premium.observed_at],
            },
        }

    return {
        "schema": VERIFIED_ASSET_SCHEMA,
        "asset_id": asset_def.asset_id,
        "display_name": asset_def.display_name,
        "asset_type": asset_def.asset_type,
        "description": asset_def.description,
        "status": status,
        "status_display": STATUS_DISPLAY[status],
        "model": _model_section(ws),
        "verify": _verify_section(certificate),
        "market": market_section,
        "market_observation": market_section,
        "identity": identity_section,
        "evidence": evidence_section,
        "canonical_authority": canonical_authority_section,
        "verification": {"status": status.value, "reason": reason},
        "protocol": _protocol_section(asset_def),
        "error": None,
        # Full certificate is returned only by the entitled dossier route.
        "certificate": certificate,
    }
