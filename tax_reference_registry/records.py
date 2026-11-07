"""Typed reference records: immutable, versioned, evidence-carrying.

A TaxRuleRecord is a *reference* record. It never carries a computed project
tax result, and nothing in this package derives one.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import decimal
from decimal import Decimal
from typing import Optional

from tax_reference_registry.enums import (
    AssetClass,
    LawStatus,
    RateScheduleMode,
    TaxCategory,
    VerificationStatus,
)
from tax_reference_registry.currency import CurrencyPolicy

ISO_DATE = "%Y-%m-%d"


def parse_date(raw: str | None) -> tuple[Optional[_dt.date], bool]:
    """Return (date, was_unparsed). Empty -> (None, False). Non-ISO strings are
    preserved verbatim on the record but flagged (warning, not rejection)."""
    if raw is None:
        return None, False
    text = raw.strip()
    if not text:
        return None, False
    try:
        return _dt.datetime.strptime(text, ISO_DATE).date(), False
    except ValueError:
        return None, True


@dataclasses.dataclass(frozen=True)
class EffectiveWindow:
    effective_from: Optional[_dt.date]
    effective_to: Optional[_dt.date]
    effective_from_raw: str = ""
    effective_to_raw: str = ""
    from_unparsed: bool = False
    to_unparsed: bool = False

    def contains(self, day: _dt.date) -> bool:
        if self.effective_from is not None and day < self.effective_from:
            return False
        if self.effective_to is not None and day > self.effective_to:
            return False
        # Unparsed bounds are preserved but never treated as satisfied bounds.
        if self.from_unparsed or self.to_unparsed:
            return True if (self.effective_from is None and self.effective_to is None) else False
        return True

    def overlaps(self, other: "EffectiveWindow") -> bool:
        a_from = self.effective_from or _dt.date.min
        a_to = self.effective_to or _dt.date.max
        b_from = other.effective_from or _dt.date.min
        b_to = other.effective_to or _dt.date.max
        return a_from <= b_to and b_from <= a_to


@dataclasses.dataclass(frozen=True)
class ParsedValue:
    """Exact numeric value: single Decimal or an ordered tier set.

    Tier sets (e.g. Slovakia's "10 / 21 / 24") are represented without being
    evaluated: there is no bracket logic here, only the ordered components.
    Text rates ("23% corporations / 27.5% other recipients") are NEVER parsed
    into numbers — the loader rejects them as VALUE_UNPARSED instead of
    converting ambiguity into a default.
    """

    single: Optional[Decimal] = None
    tiers: tuple[Decimal, ...] = ()

    @property
    def is_tiered(self) -> bool:
        return len(self.tiers) > 1

    @property
    def mode(self) -> RateScheduleMode:
        if self.is_tiered:
            return RateScheduleMode.TIERED
        if self.single is not None:
            return RateScheduleMode.FLAT
        return RateScheduleMode.UNKNOWN


def parse_value(raw: str | None) -> Optional[ParsedValue]:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return ParsedValue(single=Decimal(text))
    except decimal.InvalidOperation:
        pass
    parts = [p.strip() for p in text.split("/")]
    if len(parts) > 1:
        try:
            tiers = tuple(Decimal(p) for p in parts)
            return ParsedValue(tiers=tiers)
        except decimal.InvalidOperation:
            return None
    return None


@dataclasses.dataclass(frozen=True)
class TaxRuleRecord:
    """One 35-column reference record, canonically typed."""

    rule_id: str
    jurisdiction_code: str
    subnational_scope: Optional[str]
    industry_scope: Optional[str]
    entity_scope: Optional[str]
    tax_category: TaxCategory
    subrule: Optional[str]
    asset_class: Optional[AssetClass]
    recipient_country: Optional[str]
    income_type: Optional[str]
    value: ParsedValue
    value_unit: Optional[str]
    value_currency: Optional[str]
    threshold_min: Optional[Decimal]
    threshold_max: Optional[Decimal]
    condition_logic: Optional[str]
    formula_or_method: Optional[str]
    window: EffectiveWindow
    law_status: LawStatus
    primary_legal_title: Optional[str]
    primary_section: Optional[str]
    primary_url: Optional[str]
    professional_source_url: Optional[str]
    professional_last_reviewed: Optional[_dt.date]
    professional_last_reviewed_raw: str
    accessed_at: _dt.date
    source_status_raw: str
    verification: VerificationStatus
    review_due: Optional[_dt.date]
    confidence: Optional[str]
    advisor_required: bool
    finco_current_behavior: Optional[str]
    reference_workbook_behavior: Optional[str]
    parity_gap: Optional[str]
    implementation_dependency: Optional[str]
    evidence_id: Optional[str]

    @property
    def is_verified(self) -> bool:
        """Only PRIMARY_CONFIRMED counts as verified. IN_FORCE never implies
        verified: this property reads the verification dimension exclusively."""
        return self.verification is VerificationStatus.PRIMARY_CONFIRMED

    def is_operative_on(self, day: _dt.date) -> bool:
        """Legal effectiveness only — independent of verification and of
        activation. DRAFT records are never operative."""
        if self.law_status is not LawStatus.IN_FORCE:
            return False
        return self.window.contains(day)

    def scope_key(self) -> tuple[str, str, str, str]:
        """Identity used for duplicate/overlap detection."""
        return (
            self.jurisdiction_code,
            self.subnational_scope or "",
            self.tax_category.value,
            self.subrule or "",
        )

    def compare_to(self, other: "TaxRuleRecord") -> dict:
        """Field-level difference summary for registry.compare()."""
        changed = []
        for field in (
            "value_unit",
            "value_currency",
            "condition_logic",
            "formula_or_method",
            "law_status",
            "verification",
            "source_status_raw",
            "subrule",
            "parity_gap",
        ):
            a = getattr(self, field)
            b = getattr(other, field)
            a = a.value if hasattr(a, "value") else a
            b = b.value if hasattr(b, "value") else b
            if a != b:
                changed.append(field)
        if self.value.single != other.value.single or self.value.tiers != other.value.tiers:
            changed.append("value")
        if self.window.effective_from != other.window.effective_from:
            changed.append("law_effective_from")
        if self.window.effective_to != other.window.effective_to:
            changed.append("law_effective_to")
        if self.verification is not other.verification:
            if "verification" not in changed:
                changed.append("verification_change")
        return {"rule_id": self.rule_id, "changed_fields": sorted(set(changed))}


def window_for(record: TaxRuleRecord, day: _dt.date, policy: CurrencyPolicy | None = None) -> bool:
    """Free-function form of is_operative_on (kept for API symmetry)."""
    return record.is_operative_on(day)
