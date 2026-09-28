"""B2.1 evidence gate for an exact model/run-to-market relationship.

No production binding source is approved by default. A caller must supply
source-attested evidence; names, symbols and CoinGecko never establish identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.radar_rwa.bnb_contracts import BnbRwaMarketObservation
from finco_radar.assets.contracts import AssetKey, normalize_asset_uid
from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState
from finco_radar.authority.cross_chain import CrossChainIdentityBinding
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.tokenization_premium.contracts import (
    TokenizationPremiumObservation, TokenizationPremiumStatus,
)


@dataclass(frozen=True)
class ModelMarketRunBinding:
    """Explicit attestation of one immutable FINCO Last Run and market asset."""

    asset_id: str
    project_code: str
    certificate_digest_sha256: str
    composite_hash: str
    economic_asset_uid: str
    deployment: AssetKey
    evidence_id: str
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not all((self.asset_id, self.project_code, self.certificate_digest_sha256,
                    self.composite_hash, self.evidence_id, self.source)):
            raise ValueError("run binding fields are required")
        object.__setattr__(self, "economic_asset_uid", normalize_asset_uid(self.economic_asset_uid))
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("evidence observation time must be timezone-aware")


@dataclass(frozen=True)
class VerifiedAuthorityBundle:
    binding: ModelMarketRunBinding
    identity: CrossChainIdentityBinding
    market: BnbRwaMarketObservation
    radar: AuthoritySnapshot
    premium: TokenizationPremiumObservation


@dataclass(frozen=True)
class VerificationPolicy:
    approved_binding_sources: frozenset[str] = frozenset()
    max_evidence_age_seconds: int = 86400
    max_identity_age_seconds: int = 86400
    max_market_age_seconds: int = 3600
    max_reference_age_seconds: int = 3600

    def __post_init__(self) -> None:
        if min(self.max_evidence_age_seconds, self.max_identity_age_seconds,
               self.max_market_age_seconds, self.max_reference_age_seconds) <= 0:
            raise ValueError("positive freshness limits required")


def evaluate_authorities(
    *, asset_id: str, project_code: str, certificate: dict,
    bundle: VerifiedAuthorityBundle | None, as_of: datetime,
    policy: VerificationPolicy = VerificationPolicy(),
) -> tuple[str, str | None]:
    """Return existing VerifiedAssetStatus value and machine-readable gap."""
    if bundle is None:
        return "MODEL_ONLY", "MODEL_MARKET_BINDING_UNAVAILABLE"
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("aware evaluation time required")
    binding, identity, market, radar, premium = (
        bundle.binding, bundle.identity, bundle.market, bundle.radar, bundle.premium,
    )
    if binding.source not in policy.approved_binding_sources:
        return "MODEL_ONLY", "BINDING_SOURCE_NOT_APPROVED"
    if (binding.asset_id != asset_id or binding.project_code != project_code
            or binding.certificate_digest_sha256 != certificate.get("certificate_digest_sha256")
            or binding.composite_hash != certificate.get("identity", {}).get("composite_hash")):
        return "IDENTITY_MISMATCH", "MODEL_RUN_BINDING_MISMATCH"
    if identity.state is not AuthorityState.AVAILABLE:
        return "MODEL_ONLY", identity.reason or "ECONOMIC_IDENTITY_UNAVAILABLE"
    if not (identity.authority_source or "").startswith(RobinhoodAssetRegistryAdapter.source_name + ":"):
        return "MODEL_ONLY", "CANONICAL_IDENTITY_SOURCE_UNAVAILABLE"
    if (identity.economic_asset_uid != binding.economic_asset_uid
            or identity.external_asset_key != binding.deployment
            or binding.deployment not in identity.canonical_deployments):
        return "IDENTITY_MISMATCH", "ECONOMIC_IDENTITY_OR_DEPLOYMENT_MISMATCH"
    if market.asset_key != binding.deployment:
        return "IDENTITY_MISMATCH", "MARKET_DEPLOYMENT_MISMATCH"
    if (market.state is not AuthorityState.AVAILABLE or market.observed_at is None
            or market.price_usd is None or not market.price_usd.is_finite()
            or market.price_usd <= 0):
        return "MODEL_ONLY", "MARKET_OBSERVATION_UNAVAILABLE"
    if (radar.economic_asset_uid != binding.economic_asset_uid
            or radar.canonical_token != binding.deployment):
        return "IDENTITY_MISMATCH", "RADAR_IDENTITY_MISMATCH"
    if (radar.underlying.state is not AuthorityState.AVAILABLE
            or radar.token.state is not AuthorityState.AVAILABLE
            or radar.premium.state is not AuthorityState.AVAILABLE
            or premium.status is not TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK):
        return "MODEL_ONLY", "RADAR_REFERENCE_OR_PREMIUM_UNAVAILABLE"
    if radar.underlying.asset_key != binding.deployment or radar.token.asset_key != binding.deployment:
        return "IDENTITY_MISMATCH", "RADAR_REFERENCE_DEPLOYMENT_MISMATCH"
    for name, observed, maximum in (
        ("EVIDENCE", binding.observed_at, policy.max_evidence_age_seconds),
        ("IDENTITY", identity.observed_at, policy.max_identity_age_seconds),
        ("MARKET", market.observed_at, policy.max_market_age_seconds),
        ("UNDERLYING_REFERENCE", radar.underlying.observed_at, policy.max_reference_age_seconds),
        ("TOKEN_REFERENCE", radar.token.observed_at, policy.max_reference_age_seconds),
    ):
        if observed is None or not 0 <= (as_of - observed).total_seconds() <= maximum:
            return "STALE", f"{name}_STALE"
    return "VERIFIED", None
