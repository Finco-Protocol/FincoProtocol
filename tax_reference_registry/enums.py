"""Typed enums and canonical mappings for the tax reference registry.

The harvest vocabulary (T01-B/T01-C 35-column CSV contract) is richer than the
canonical registry vocabulary. The mapping below is the *documented contract*:
raw values are always preserved verbatim alongside the canonical form, and the
mapping never upgrades evidence confidence.

Law status ``IN_FORCE`` must never imply verified — effectiveness and
verification are independent dimensions.
"""
from __future__ import annotations

import enum


class LawStatus(enum.Enum):
    IN_FORCE = "IN_FORCE"
    DRAFT = "DRAFT"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(enum.Enum):
    PRIMARY_CONFIRMED = "PRIMARY_CONFIRMED"
    SECONDARY_ONLY = "SECONDARY_ONLY"
    CONFLICT = "CONFLICT"
    NOT_TESTED = "NOT_TESTED"
    STALE = "STALE"


class TaxCategory(enum.Enum):
    CIT = "CIT"
    TAX_DEPRECIATION = "TAX_DEPRECIATION"
    NOL = "NOL"
    INTEREST_LIMITATION = "INTEREST_LIMITATION"
    WHT = "WHT"
    VAT = "VAT"
    INCENTIVE = "INCENTIVE"
    PILLAR2 = "PILLAR2"
    CASH_TAX_CALENDAR = "CASH_TAX_CALENDAR"


class RateScheduleMode(enum.Enum):
    """Reference-schema classification of CIT records. Never used to compute."""

    FLAT = "FLAT"
    TIERED = "TIERED"
    DATED_SERIES = "DATED_SERIES"
    UNKNOWN = "UNKNOWN"


class AssetClass(enum.Enum):
    GENERAL = "GENERAL"
    PV_PANELS = "PV_PANELS"
    WIND_TURBINES = "WIND_TURBINES"
    BESS_CELLS = "BESS_CELLS"
    BESS_POWER_ELECTRONICS = "BESS_POWER_ELECTRONICS"
    GRID_CONNECTION = "GRID_CONNECTION"
    BUILDINGS_CIVIL = "BUILDINGS_CIVIL"
    LAND_RIGHTS = "LAND_RIGHTS"


#: Canonical mapping from the harvest vocabulary to the registry vocabulary.
#: Values: (VerificationStatus, LawStatus override or None).
#: ``CORROBORATED`` maps DOWN to SECONDARY_ONLY: corroboration without fetched
#: primary normative text is not primary confirmation (T01-C provenance policy).
SOURCE_STATUS_CANONICAL: dict[str, tuple[VerificationStatus, LawStatus | None]] = {
    "PRIMARY_CONFIRMED": (VerificationStatus.PRIMARY_CONFIRMED, None),
    "CORROBORATED": (VerificationStatus.SECONDARY_ONLY, None),
    "SECONDARY_ONLY": (VerificationStatus.SECONDARY_ONLY, None),
    "CONFLICT": (VerificationStatus.CONFLICT, None),
    "NOT_TESTED": (VerificationStatus.NOT_TESTED, None),
    "STALE": (VerificationStatus.STALE, None),
    "SOURCE_ACCESS_UNAVAILABLE": (VerificationStatus.NOT_TESTED, None),
    "NO_SOURCE": (VerificationStatus.NOT_TESTED, None),
    "NOT_APPLICABLE": (VerificationStatus.NOT_TESTED, None),
    "PROPOSED_NOT_LAW": (VerificationStatus.NOT_TESTED, LawStatus.DRAFT),
}

#: Confidence vocabulary as captured.
CONFIDENCE_VALUES = {"HIGH", "MEDIUM", "LOW"}

#: Law-status vocabulary as captured (only IN_FORCE occurs in T01-B/T01-C).
LAW_STATUS_VALUES = {"IN_FORCE", "DRAFT", "EXPIRED", "UNKNOWN"}

REQUIRED_COLUMNS: tuple[str, ...] = (
    "rule_id",
    "jurisdiction_code",
    "subnational_scope",
    "industry_scope",
    "entity_scope",
    "tax_category",
    "subrule",
    "asset_class",
    "recipient_country",
    "income_type",
    "value",
    "value_unit",
    "value_currency",
    "threshold_min",
    "threshold_max",
    "condition_logic",
    "formula_or_method",
    "law_effective_from",
    "law_effective_to",
    "law_status",
    "primary_legal_title",
    "primary_section",
    "primary_url",
    "professional_source_url",
    "professional_last_reviewed",
    "accessed_at",
    "source_status",
    "review_due",
    "confidence",
    "advisor_required",
    "finco_current_behavior",
    "reference_workbook_behavior",
    "parity_gap",
    "implementation_dependency",
    "evidence_id",
)

XK_INTERNAL_CODE_NOTE = (
    "XK is the project's governed internal identifier for Kosovo and is not an "
    "official ISO 3166-1 alpha-2 assignment; it is admitted as an explicit "
    "exception and must never be presented as an ISO code."
)
#: Explicit, documented country-code exception set.
COUNTRY_CODE_EXCEPTIONS = {"XK"}
