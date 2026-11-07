"""Registry compare/explain/export + activation fail-closed + repo isolation."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from tax_reference_registry import (
    ActivationBlockedError,
    LawStatus,
    RateScheduleMode,
    TaxReferenceRegistry,
    VerificationStatus,
    activate_country,
    get_effective_run_profile,
    load_records,
)


def test_compare_added_changed_verification_no_overwrite(zz_pair):
    old_path, new_path = zz_pair
    old = load_records(old_path, source_path="old")
    new = load_records(new_path, source_path="new")
    old_reg = TaxReferenceRegistry.from_records(old.records, as_of=dt.date(2026, 11, 7))
    new_reg = TaxReferenceRegistry.from_records(new.records, as_of=dt.date(2026, 11, 7))
    diff = new_reg.compare(old_reg, reference_day=dt.date(2026, 11, 7))
    assert diff["added"] == ["ZZ-CIT-002"]
    assert diff["removed"] == []
    changed_ids = {c["rule_id"] for c in diff["changed"]}
    assert changed_ids == {"ZZ-CIT-001"}
    verification_changes = {v["rule_id"]: (v["from"], v["to"]) for v in diff["verification_changes"]}
    assert verification_changes["ZZ-CIT-001"] == ("SECONDARY_ONLY", "PRIMARY_CONFIRMED")
    # Original registry objects are untouched (no destructive overwrite):
    assert old_reg.get("ZZ-CIT-001").value.single == Decimal("21")


def test_expired_detection(zz_pair):
    old_path, new_path = zz_pair
    new = load_records(new_path, source_path="new")
    reg = TaxReferenceRegistry.from_records(new.records, as_of=dt.date(2026, 11, 7))
    diff = reg.compare(reg, reference_day=dt.date(2028, 6, 1))
    # ZZ-CIT-001's window ends 2027-12-31 -> expired as of 2028-06-01
    assert "ZZ-CIT-001" in diff["expired"]


def test_explain_citations_and_no_computed_rate(zz_single):
    reg = TaxReferenceRegistry.from_records(
        load_records(zz_single).records, as_of=dt.date(2026, 11, 7)
    )
    result = reg.explain("ZZ", "ZZ-CIT-001")
    payload = result.as_dict()
    assert payload["primary_citation"] is None
    assert payload["professional_source"] == "https://example.test/zz-cit"
    assert payload["value"] == "21"
    assert payload["verification"] == "SECONDARY_ONLY"
    assert "computed" not in str(payload["value"])  # reference value, not a computed tax rate
    with pytest.raises(KeyError):
        reg.explain("ZZ", "ZZ-NOL-404")


def test_rate_schedule_mode_classification(zz_pair):
    old_path, new_path = zz_pair
    reg = TaxReferenceRegistry.from_records(
        load_records(new_path).records, as_of=dt.date(2026, 11, 7)
    )
    # ZZ-CIT-001 (2024..2027) + ZZ-CIT-002 (2028..2029) share a scope key with
    # disjoint dated windows -> DATED_SERIES; no rate is chosen or computed.
    assert reg.rate_schedule_mode("ZZ-CIT-001") is RateScheduleMode.DATED_SERIES
    assert reg.rate_schedule_mode("ZZ-CIT-002") is RateScheduleMode.DATED_SERIES


def test_tiered_classification(tmp_path):
    from tests.tax_reference_registry.conftest import base_row, rows_to_csv

    path = tmp_path / "tiered.csv"
    path.write_text(
        rows_to_csv(
            [
                base_row(
                    rule_id="SK-CIT-001",
                    jurisdiction_code="SK",
                    value="10 / 21 / 24",
                )
            ]
        ),
        encoding="utf-8",
    )
    reg = TaxReferenceRegistry.from_records(
        load_records(path).records, as_of=dt.date(2026, 11, 7)
    )
    assert reg.rate_schedule_mode("SK-CIT-001") is RateScheduleMode.TIERED


def test_export_candidates_tagged_and_scrubbed(zz_single):
    reg = TaxReferenceRegistry.from_records(
        load_records(zz_single).records, as_of=dt.date(2026, 11, 7)
    )
    report = reg.export_candidates()
    assert report["tag"] == "NON_ACTIVATABLE_REFERENCE_ONLY"
    row = report["candidates"][0]
    # Whitelist-only export: behavior/free-text columns are excluded.
    for forbidden in (
        "condition_logic",
        "finco_current_behavior",
        "reference_workbook_behavior",
        "primary_section",
    ):
        assert forbidden not in row


# ── activation fails CLOSED ──────────────────────────────────────────────────
def test_activate_country_always_fails():
    with pytest.raises(ActivationBlockedError):
        activate_country("ZZ")
    with pytest.raises(ActivationBlockedError):
        activate_country()


def test_get_effective_run_profile_always_fails():
    with pytest.raises(ActivationBlockedError):
        get_effective_run_profile("ZZ", "2026-11-07")
    with pytest.raises(ActivationBlockedError):
        get_effective_run_profile()


def test_no_automatic_country_fallback():
    from tax_reference_registry.records import TaxRuleRecord
    from tax_reference_registry.enums import TaxCategory
    from tax_reference_registry.records import ParsedValue, EffectiveWindow

    record = TaxRuleRecord(
        rule_id="ZZ-CIT-001",
        jurisdiction_code="ZZ",
        subnational_scope=None,
        industry_scope=None,
        entity_scope=None,
        tax_category=TaxCategory.CIT,
        subrule="standard rate",
        asset_class=None,
        recipient_country=None,
        income_type=None,
        value=ParsedValue(single=Decimal("21")),
        value_unit="pct",
        value_currency=None,
        threshold_min=None,
        threshold_max=None,
        condition_logic=None,
        formula_or_method=None,
        window=EffectiveWindow(effective_from=dt.date(2024, 1, 1), effective_to=None),
        law_status=LawStatus.IN_FORCE,
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
    reg = TaxReferenceRegistry.from_records([record], as_of=dt.date(2026, 11, 7))
    # Asking for an unknown country yields no records and no fallback rate:
    assert reg.for_country("QQ") == ()
    with pytest.raises(KeyError):
        reg.get("QQ-CIT-001")


# ── repo isolation: no production module imports this package ────────────────
def test_no_production_import_of_registry():
    repo_root = dt.__file__  # placeholder to keep import local
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tax_reference_registry/", "tests/tax_reference_registry/")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "tax_reference_registry" in text:
            offenders.append(rel)
    assert offenders == [], f"production files reference the registry: {offenders}"
