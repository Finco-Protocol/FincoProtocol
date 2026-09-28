"""FINCO Verified Assets V1 — composition contracts.

Principle: NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION

This module defines the typed FINCO_VERIFIED_ASSET_V1 schema and the
VerifiedAssetStatus enumeration. All sections are composed from
existing authorities — no financial calculations here.

Authorities composed:
  model section   — WorkspaceStateRecord (last_runtime_summary, identity fields)
  verify section  — build_run_certificate() → FINCO_RUN_CERTIFICATE_V1
  market section  — exact model/run binding + canonical Radar AuthoritySnapshot
  protocol section — UTILITY_REGISTRY

Eligibility states:
  VERIFIED              — model + cert + market all coherent
  VERIFIED_MARKET_PARTIAL — model + cert + degraded market (execution unavailable)
  MODEL_ONLY            — model + cert exist; no tokenized-market identity mapping
  MARKET_ONLY           — market identity exists; no model binding
  STALE                 — model + cert exist but temporal coherence policy violated
  UNAVAILABLE           — certificate unavailable (fail-closed conditions met)
  IDENTITY_MISMATCH     — composite_hash bound in cert ≠ market evidence

Markers:
  FINCO_P5_VERIFIED_ASSETS_V1_SCHEMA_STABLE
  FINCO_P5_COMPOSED_NOT_CALCULATED
  FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
  FINCO_P5_ELIGIBILITY_DETERMINISTIC
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


VERIFIED_ASSET_SCHEMA = "FINCO_VERIFIED_ASSET_V1"


class VerifiedAssetStatus(str, Enum):
    """Eligibility state for a FINCO Verified Asset.

    FINCO_P5_ELIGIBILITY_DETERMINISTIC
    """
    VERIFIED = "VERIFIED"
    VERIFIED_MARKET_PARTIAL = "VERIFIED_MARKET_PARTIAL"
    MODEL_ONLY = "MODEL_ONLY"
    MARKET_ONLY = "MARKET_ONLY"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


# Status display metadata — used by templates and API consumers.
STATUS_DISPLAY: dict[str, dict[str, str]] = {
    VerifiedAssetStatus.VERIFIED: {
        "label": "Verified",
        "description": "Model, certificate, and market identity all coherent.",
        "css_class": "va-status--verified",
    },
    VerifiedAssetStatus.VERIFIED_MARKET_PARTIAL: {
        "label": "Verified (Market Partial)",
        "description": "Model and certificate coherent; market execution data partial.",
        "css_class": "va-status--partial",
    },
    VerifiedAssetStatus.MODEL_ONLY: {
        "label": "Model Only",
        "description": "Run certificate available. No tokenized-market identity mapping exists for this asset.",
        "css_class": "va-status--model-only",
    },
    VerifiedAssetStatus.MARKET_ONLY: {
        "label": "Market Only",
        "description": "Market identity exists. No model binding available.",
        "css_class": "va-status--market-only",
    },
    VerifiedAssetStatus.STALE: {
        "label": "Stale",
        "description": "Certificate exists but temporal coherence policy violated.",
        "css_class": "va-status--stale",
    },
    VerifiedAssetStatus.UNAVAILABLE: {
        "label": "Unavailable",
        "description": "Certificate unavailable — re-run the model to establish a certifiable Last Run.",
        "css_class": "va-status--unavailable",
    },
    VerifiedAssetStatus.IDENTITY_MISMATCH: {
        "label": "Identity Mismatch",
        "description": "Composite hash in certificate does not match market evidence.",
        "css_class": "va-status--mismatch",
    },
}


class VerifiedAssetDefinition:
    """Static definition of a P5 V1 asset entry.

    Each entry maps a human-readable asset_id to a template_source
    (the canonical reference project) plus display metadata.
    The model↔market binding is discovered at composition time;
    if no binding is available the status is MODEL_ONLY.

    FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
    """
    __slots__ = (
        "asset_id",
        "display_name",
        "asset_type",
        "template_source",
        "description",
    )

    def __init__(
        self,
        *,
        asset_id: str,
        display_name: str,
        asset_type: str,
        template_source: str,
        description: str,
    ) -> None:
        self.asset_id = asset_id
        self.display_name = display_name
        self.asset_type = asset_type
        self.template_source = template_source
        self.description = description
