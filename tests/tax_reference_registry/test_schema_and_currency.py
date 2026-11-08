"""Schema, value parsing and NO_IMPLICIT_FX currency-policy tests (synthetic)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from tax_reference_registry import (
    CurrencyPolicy,
    LawStatus,
    NoImplicitFxError,
    RateScheduleMode,
    VerificationStatus,
)
from tax_reference_registry.records import EffectiveWindow, ParsedValue, parse_value
from tax_reference_registry.currency import NO_IMPLICIT_FX, KnownCurrency


# ── value parsing: tier sets are represented, never evaluated ────────────────
def test_single_decimal():
    parsed = parse_value("21")
    assert parsed.single == Decimal("21")
    assert parsed.mode is RateScheduleMode.FLAT


def test_tier_set_represented_without_evaluation():
    parsed = parse_value("10 / 21 / 24")
    assert parsed.tiers == (Decimal("10"), Decimal("21"), Decimal("24"))
    assert parsed.is_tiered
    assert parsed.mode is RateScheduleMode.TIERED
    # No bracket logic exists: the "rate" for an income level is not computable.
    with pytest.raises((TypeError, AttributeError, IndexError)):
        parsed.tiers.bracket_for_income  # type: ignore[attr-defined]


def test_text_rate_is_not_parsed_into_a_number():
    assert parse_value("23% corporations / 27.5% other recipients") is None
    assert parse_value("exempt") is None


def test_empty_value_parses_to_none():
    assert parse_value(None) is None
    assert parse_value("  ") is None


# ── NO_IMPLICIT_FX: currency mixing is a hard stop ───────────────────────────
def test_pln_vs_eur_comparison_hard_stops():
    with pytest.raises(NoImplicitFxError):
        NO_IMPLICIT_FX.compare(Decimal("3000000"), "PLN", Decimal("3000000"), "EUR")


def test_chf_threshold_without_fx_policy_hard_stops():
    with pytest.raises(NoImplicitFxError):
        NO_IMPLICIT_FX.convert(Decimal("939810000"), "HUF", "CHF")


def test_explicit_pinned_table_allows_conversion():
    policy = CurrencyPolicy(fx_table={("PLN", "EUR"): Decimal("0.25")})
    assert policy.convert(Decimal("3000000"), "PLN", "EUR") == Decimal("750000.00")
    # same-currency comparison is allowed without any table
    assert NO_IMPLICIT_FX.compare(Decimal("3"), "EUR", Decimal("3"), "EUR") == 0


def test_same_currency_comparison_allowed():
    assert NO_IMPLICIT_FX.compare(Decimal("5"), "PLN", Decimal("4"), "PLN") == 1


def test_known_currency_vocabulary():
    assert KnownCurrency("PLN").value == "PLN"
    with pytest.raises(ValueError):
        KnownCurrency("XXX_INVALID")


# ── windows and effectiveness: DRAFT never operative ────────────────────────
def test_future_draft_window_not_operative():
    window = EffectiveWindow(
        effective_from=dt.date(2027, 1, 1),
        effective_to=dt.date(2027, 12, 31),
    )
    from tax_reference_registry.records import TaxRuleRecord
    from tax_reference_registry.enums import TaxCategory
    from tax_reference_registry.registry import TaxReferenceRegistry

    record = TaxRuleRecord(
        rule_id="ZZ-DRAFT-001",
        jurisdiction_code="ZZ",
        subnational_scope=None,
        industry_scope=None,
        entity_scope=None,
        tax_category=TaxCategory.CIT,
        subrule="standard rate",
        asset_class=None,
        recipient_country=None,
        income_type=None,
        value=ParsedValue(single=Decimal("22")),
        value_unit="pct",
        value_currency=None,
        threshold_min=None,
        threshold_max=None,
        condition_logic=None,
        formula_or_method=None,
        window=window,
        law_status=LawStatus.DRAFT,
        primary_legal_title=None,
        primary_section=None,
        primary_url=None,
        professional_source_url="https://example.test",
        professional_last_reviewed=None,
        professional_last_reviewed_raw="",
        accessed_at=dt.date(2026, 11, 7),
        source_status_raw="SECONDARY_ONLY",
        verification=VerificationStatus.SECONDARY_ONLY,
        review_due=None,
        confidence=None,
        advisor_required=True,
        finco_current_behavior=None,
        reference_workbook_behavior=None,
        parity_gap=None,
        implementation_dependency=None,
        evidence_id=None,
    )
    registry = TaxReferenceRegistry.from_records([record], as_of=dt.date(2026, 11, 7))
    assert registry.is_operative_on("ZZ-DRAFT-001", dt.date(2026, 11, 7)) is False
    assert registry.is_operative_on("ZZ-DRAFT-001", dt.date(2027, 6, 1)) is False
