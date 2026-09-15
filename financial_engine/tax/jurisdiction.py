"""Typed tax-profile registry for synthetic public reference markets.

The public repository ships only illustrative, non-jurisdictional profiles.
XA/XB/XC are user-assigned ISO-style codes used solely for synthetic examples.
No profile in this module is legal or tax advice.
"""
from __future__ import annotations

from dataclasses import dataclass

PROVENANCE_SOURCE_PROVEN = "SOURCE_PROVEN"
PROVENANCE_GENERIC_MVP_POLICY = "GENERIC_MVP_POLICY"
PROVENANCE_TAX_JURISDICTION_SOURCE_UNRESOLVED = "TAX_JURISDICTION_SOURCE_UNRESOLVED"


@dataclass(frozen=True)
class TaxJurisdictionProfile:
    profile_id: str
    country_iso: str
    subnational_jurisdiction_code: str | None
    profile_version: str
    effective_from: str | None
    effective_to: str | None
    source_references: tuple[str, ...]
    provenance: str

    def __post_init__(self) -> None:
        valid = {
            PROVENANCE_SOURCE_PROVEN,
            PROVENANCE_GENERIC_MVP_POLICY,
            PROVENANCE_TAX_JURISDICTION_SOURCE_UNRESOLVED,
        }
        if self.provenance not in valid:
            raise ValueError(f"Unknown provenance: {self.provenance!r}")
        if not self.profile_id or not self.country_iso or not self.profile_version:
            raise ValueError("profile_id, country_iso and profile_version are required")


MARKET_A_GENERIC_MVP_V1 = TaxJurisdictionProfile(
    profile_id="XA-generic-mvp-v1",
    country_iso="XA",
    subnational_jurisdiction_code=None,
    profile_version="1.0.0",
    effective_from=None,
    effective_to=None,
    source_references=(),
    provenance=PROVENANCE_GENERIC_MVP_POLICY,
)
MARKET_B_GENERIC_MVP_V1 = TaxJurisdictionProfile(
    profile_id="XB-generic-mvp-v1",
    country_iso="XB",
    subnational_jurisdiction_code=None,
    profile_version="1.0.0",
    effective_from=None,
    effective_to=None,
    source_references=(),
    provenance=PROVENANCE_GENERIC_MVP_POLICY,
)
MARKET_C_GENERIC_MVP_V1 = TaxJurisdictionProfile(
    profile_id="XC-generic-mvp-v1",
    country_iso="XC",
    subnational_jurisdiction_code=None,
    profile_version="1.0.0",
    effective_from=None,
    effective_to=None,
    source_references=(),
    provenance=PROVENANCE_GENERIC_MVP_POLICY,
)

_PROFILE_REGISTRY = {
    p.profile_id: p
    for p in (
        MARKET_A_GENERIC_MVP_V1,
        MARKET_B_GENERIC_MVP_V1,
        MARKET_C_GENERIC_MVP_V1,
    )
}


@dataclass(frozen=True)
class TaxJurisdictionDefaults:
    corporate_tax_rate: float | None = None


_DEFAULTS_REGISTRY: dict[str, TaxJurisdictionDefaults] = {}


@dataclass(frozen=True)
class ProjectTaxOverrides:
    corporate_tax_rate_override: float | None = None
    withholding_tax_rate_dividends_override: float | None = None
    withholding_tax_rate_interest_override: float | None = None


@dataclass(frozen=True)
class ResolvedTaxAssumptions:
    corporate_tax_rate: float | None
    corporate_tax_rate_source: str
    withholding_tax_rate_dividends: float | None
    withholding_tax_rate_dividends_source: str
    withholding_tax_rate_interest: float | None
    withholding_tax_rate_interest_source: str
    jurisdiction_profile: TaxJurisdictionProfile


def resolve_tax_assumptions(
    profile: TaxJurisdictionProfile,
    defaults: TaxJurisdictionDefaults,
    overrides: ProjectTaxOverrides,
) -> ResolvedTaxAssumptions:
    def _resolve(override, default):
        if override is not None:
            return override, "project_override"
        if default is not None:
            return default, profile.provenance
        return None, "NOT_RESOLVED"

    corp, corp_src = _resolve(overrides.corporate_tax_rate_override, defaults.corporate_tax_rate)
    div, div_src = _resolve(overrides.withholding_tax_rate_dividends_override, None)
    intr, intr_src = _resolve(overrides.withholding_tax_rate_interest_override, None)
    return ResolvedTaxAssumptions(
        corporate_tax_rate=corp,
        corporate_tax_rate_source=corp_src,
        withholding_tax_rate_dividends=div,
        withholding_tax_rate_dividends_source=div_src,
        withholding_tax_rate_interest=intr,
        withholding_tax_rate_interest_source=intr_src,
        jurisdiction_profile=profile,
    )


def get_profile(profile_id: str) -> TaxJurisdictionProfile:
    try:
        return _PROFILE_REGISTRY[profile_id]
    except KeyError:
        raise KeyError(
            f"TaxJurisdictionProfile {profile_id!r} not found. "
            f"Registered profiles: {sorted(_PROFILE_REGISTRY)!r}"
        ) from None


def list_profiles() -> tuple[TaxJurisdictionProfile, ...]:
    return tuple(_PROFILE_REGISTRY.values())


def get_tax_jurisdiction_defaults(profile_id: str) -> TaxJurisdictionDefaults:
    if profile_id not in _PROFILE_REGISTRY:
        get_profile(profile_id)
    return _DEFAULTS_REGISTRY.get(profile_id, TaxJurisdictionDefaults())
