"""FINCO Verified Assets V1 — composition engine.

Principle: NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION

This module assembles FINCO_VERIFIED_ASSET_V1 records by composing
existing authorities. It NEVER calls financial-engine entry points or
duplicates any calculation formula.

Composition authority chain:
  1. model section   ← WorkspaceStateRecord (persisted Last Run fields)
  2. verify section  ← build_run_certificate() — FINCO_RUN_CERTIFICATE_V1
  3. market section  ← discover_model_evidence() + compute_tokenization_premium()
                       (absent in V1: MODEL_BINDING_UNAVAILABLE for all assets)
  4. protocol section ← UTILITY_REGISTRY

Fail-closed:
  - No committed run → UNAVAILABLE (propagates RunCertificateUnavailableError)
  - Legacy lineage  → UNAVAILABLE
  - Missing composite_hash / snapshot_id / timestamp → UNAVAILABLE
  - Market binding unavailable → MODEL_ONLY (truthful, not an error)
  - discover_model_evidence returns gap → MODEL_ONLY

Markers:
  FINCO_P5_COMPOSED_NOT_CALCULATED
  FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
  FINCO_P5_CERTIFICATE_AUTHORITY_REUSED
  FINCO_P5_ELIGIBILITY_DETERMINISTIC
"""
from __future__ import annotations

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
            "protocol": _protocol_section(asset_def),
            "error": cert_error,
        }

    # Attempt market binding discovery.
    # discover_model_evidence returns MODEL_BINDING_UNAVAILABLE for all assets
    # in V1 — this is truthful, not an error.
    # FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
    #
    # VERIFIED STATE GATE — all six authorities required, fail-closed:
    #   1. valid committed FINCO Last Run          (certificate above)
    #   2. valid P3 Run Certificate                (certificate above)
    #   3. canonical model ↔ market economic identity reconciliation
    #   4. no identity conflict/mismatch (ComplementIdentityStatus.MATCHED)
    #   5. canonical Radar reference evidence
    #   6. canonical P2 tokenization-premium observation (compute_tokenization_premium)
    #
    # A bare market-identity binding satisfies ONLY authority 3 (partial).
    # Authorities 4–6 require full Radar evidence + P2 premium computation,
    # which is not yet available for any V1 asset.
    # A discovered binding alone MUST NOT produce VERIFIED.
    # Until all six authorities are available: fail closed to MODEL_ONLY.
    #
    # VERIFIED_ASSET_BINDING_ALONE_NOT_VERIFIED
    # VERIFIED_ASSET_VERIFIED_REQUIRES_FULL_RECONCILIATION
    # VERIFIED_ASSET_PREMIUM_REQUIRED_FOR_VERIFIED
    market_section = None
    status = VerifiedAssetStatus.MODEL_ONLY

    try:
        from finco_radar.model_radar.bridge import discover_model_evidence
        # asset_uid would be needed for a real market binding;
        # in V1 no asset_uid → market identity mapping exists.
        # We do not fabricate one.
        discovered, gap = discover_model_evidence(None)
        if discovered is not None:
            # A market identity binding was discovered. This satisfies authority 3
            # only. Authorities 4–6 (identity reconciliation, Radar reference
            # evidence, P2 tokenization-premium) are still required for VERIFIED.
            # Without them, fail closed to MODEL_ONLY — never emit VERIFIED from
            # a binding alone. Do NOT fabricate tokenization premium, execution
            # midpoint, BUY/SELL quotes, or market freshness values here.
            #
            # VERIFIED_ASSET_BINDING_ALONE_NOT_VERIFIED
            # VERIFIED_ASSET_PREMIUM_REQUIRED_FOR_VERIFIED
            status = VerifiedAssetStatus.MODEL_ONLY
            market_section = None
        else:
            status = VerifiedAssetStatus.MODEL_ONLY
            market_section = None
    except Exception:
        # Any import or discovery error → stay MODEL_ONLY.
        status = VerifiedAssetStatus.MODEL_ONLY
        market_section = None

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
        "protocol": _protocol_section(asset_def),
        "error": None,
        # Embed full certificate for JSON consumers.
        "certificate": certificate,
    }
