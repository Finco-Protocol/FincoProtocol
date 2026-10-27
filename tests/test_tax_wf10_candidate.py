"""WF-10 — Advanced Tax & Jurisdiction Contracts candidate: acceptance battery.

RELEASE-CLOSED CANDIDATE TESTS (house convention). Covers the 17 mission
acceptance cases with independent hand-computed expectations (every
expected value is derived in the test from the supplied terms, never by
calling the code under test), exact Decimal currency (kEUR, 6-decimal
quantisation, ROUND_HALF_UP), and fail-closed behaviour for unsupported
jurisdictions and legal arrangements.

Canonical date semantics: depreciation period geometry is fed from the
RELEASED ``PeriodEngine`` (Jun 30 / Dec 31 rows, COD stubs, leap-year
denominators) — the candidate never redefines periodisation. Case 17
(existing canonical outputs unchanged) is proven by the reverse/forward
isolation scans here plus the exact-head CI digest suite.
"""
from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.model_v2.tax_wf10_candidate import (
    ACTIVATION_ENABLED,
    DepreciationAsset,
    IntercompanyFlow,
    InterestLimitationInputs,
    OpeningLossVintage,
    TaxCandidateBook,
    TaxEntityBook,
    TaxEntityIdentity,
    TaxLossCarryforwardConfig,
    TaxRateSchedule,
    TaxRateWindow,
    VatConfig,
    VatPeriodInput,
    WithholdingRule,
    require_release,
)
from app.model_v2.tax_wf10_candidate.pure import (
    DepreciationPeriod,
    WithholdingApplication,
    apply_withholding,
    attribute_intercompany_interest,
    build_depreciation_schedules,
    compute_vat_position,
    corporate_tax_for_tax_year,
    interest_limitation,
    tax_loss_schedule,
    taxable_income_reconciliation,
    withholding_ledger,
)

REPO = Path(__file__).resolve().parents[1]
D = Decimal


@pytest.fixture()
def released(monkeypatch):
    """Isolated acceptance fixture: enable the candidate gate in memory."""
    import app.model_v2.tax_wf10_candidate.contracts as contracts
    import app.model_v2.tax_wf10_candidate.pure as pure
    monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)
    monkeypatch.setattr(pure, "ACTIVATION_ENABLED", True)
    yield


@pytest.fixture(scope="module")
def canonical_axis():
    """A real released PeriodEngine: FC 2025-01-01, 6 construction months,
    COD 2025-07-01 — semiannual rows on Jun 30 / Dec 31 (with a leap-year
    row for Feb 2028 inside the 25-year horizon)."""
    from finco_core.engine.period_engine import PeriodEngine

    engine = PeriodEngine(
        financial_close=date(2025, 1, 1), construction_months=6,
        horizon_years=25, ppa_years=15, cod_date=date(2025, 7, 1))
    return engine.periods()


def _operating(canonical_axis):
    return [p for p in canonical_axis if p.is_operation]


# ── Release closure ──────────────────────────────────────────────────────────


class TestReleaseClosure:
    def test_flag_is_a_literal_false_at_import(self):
        assert ACTIVATION_ENABLED is False

    @pytest.mark.parametrize("call", [
        lambda: taxable_income_reconciliation(
            tax_year=1, ebitda_keur=1.0, tax_depreciation_keur=0.0,
            deductible_interest_keur=0.0),
        lambda: corporate_tax_for_tax_year(
            taxable_income_keur=D("1"),
            tax_rate_schedule=TaxRateSchedule(mode="FLAT", flat_rate=0.1),
            tax_year_start=date(2025, 1, 1), tax_year_end=date(2025, 12, 31)),
        lambda: tax_loss_schedule(
            taxable_income_after_limits_by_tax_year={1: D("1")},
            config=TaxLossCarryforwardConfig(utilisation_cap_pct=100.0,
                                             unlimited=True),
            first_tax_year=1),
        lambda: interest_limitation(InterestLimitationInputs(
            ebitda_keur=1.0, net_interest_keur=1.0, ebitda_limit_pct=30.0,
            de_minimis_keur=0.0)),
        lambda: build_depreciation_schedules(
            DepreciationAsset("a", "cat", 1.0, 5, 5, date(2025, 7, 1)),
            cod_date=date(2025, 7, 1),
            periods=(DepreciationPeriod(0, date(2025, 7, 1),
                                        date(2025, 12, 31), 0.5),)),
        lambda: compute_vat_position(
            VatConfig(rate=0.2, recovery_pct_construction=100.0,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="EXPENSE"),
            VatPeriodInput(phase="OPERATING", output_net_keur=1.0,
                           input_net_keur=1.0)),
        lambda: apply_withholding(WithholdingApplication(
            "f1", WithholdingRule("DIVIDEND", 0.05, "spv", "inv", "law"),
            1.0)),
        lambda: withholding_ledger(()),
        lambda: attribute_intercompany_interest(
            IntercompanyFlow("i1", "spv", "holdco", "INTEREST", 0, 1.0),
            book=TaxCandidateBook(entities=(
                TaxEntityBook(TaxEntityIdentity("spv", "XA", "SPV")),
                TaxEntityBook(TaxEntityIdentity("holdco", "XB", "HOLDCO"))))),
        lambda: require_release(),
    ])
    def test_every_calculation_entry_fails_closed(self, call):
        with pytest.raises(ValueError, match="TAX_WF10_RELEASE_CLOSED"):
            call()

    def test_no_environment_variable_can_enable_the_gate(self, monkeypatch):
        for env in ("FINCO_TAX_WF10_ENABLED", "FINCO_TAX_WF10_ACTIVATION",
                    "TAX_WF10_ACTIVATION_ENABLED"):
            monkeypatch.setenv(env, "1")
        import app.model_v2.tax_wf10_candidate.contracts as contracts
        assert contracts.ACTIVATION_ENABLED is False
        with pytest.raises(ValueError, match="TAX_WF10_RELEASE_CLOSED"):
            require_release()


# ── Case 1: single SPV tax reconciliation ────────────────────────────────────


class TestCase01SingleSpvReconciliation:
    def test_explicit_line_items_reconcile_exactly(self, released):
        rec = taxable_income_reconciliation(
            tax_year=1, ebitda_keur=1000.0, financing_income_keur=10.0,
            tax_depreciation_keur=200.0, non_deductible_addbacks_keur=50.0,
            deductible_interest_keur=300.0, loss_used_keur=60.0)
        # hand-computed: 1000 + 10 − 200 + 50 − 300 = 560; 560 − 60 = 500
        assert rec.taxable_before_losses_keur == D("560.000000")
        assert rec.taxable_after_losses_keur == D("500.000000")
        assert rec.loss_generated_keur == D("0.000000")
        identity = (rec.ebitda_keur + rec.financing_income_keur
                    - rec.tax_depreciation_keur
                    + rec.non_deductible_addbacks_keur
                    - rec.deductible_interest_keur)
        assert rec.taxable_before_losses_keur == identity

    def test_reconciliation_feeds_dated_cit_exactly(self, released):
        rec = taxable_income_reconciliation(
            tax_year=1, ebitda_keur=1000.0, tax_depreciation_keur=200.0,
            deductible_interest_keur=300.0)
        schedule = TaxRateSchedule(mode="FLAT", flat_rate=0.20)
        tax = corporate_tax_for_tax_year(
            taxable_income_keur=rec.taxable_after_losses_keur,
            tax_rate_schedule=schedule, tax_year_start=date(2025, 1, 1),
            tax_year_end=date(2025, 12, 31))
        assert tax == D("100.000000")  # 500 × 20%


# ── Case 2: dated tax-rate change ────────────────────────────────────────────


class TestCase02DatedRateChange:
    def _schedule(self):
        return TaxRateSchedule(mode="DATED_SERIES", windows=(
            TaxRateWindow(date(2025, 1, 1), 0.20),
            TaxRateWindow(date(2027, 1, 1), 0.25),
        ))

    def test_each_tax_year_gets_its_evidence_supplied_rate(self, released):
        schedule = self._schedule()
        tax_2025 = corporate_tax_for_tax_year(
            taxable_income_keur=D("400"), tax_rate_schedule=schedule,
            tax_year_start=date(2025, 1, 1), tax_year_end=date(2025, 12, 31))
        tax_2027 = corporate_tax_for_tax_year(
            taxable_income_keur=D("400"), tax_rate_schedule=schedule,
            tax_year_start=date(2027, 1, 1), tax_year_end=date(2027, 12, 31))
        assert tax_2025 == D("80.000000")
        assert tax_2027 == D("100.000000")

    def test_rate_change_inside_one_tax_year_fails_closed(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_TAX_YEAR_RATE_SPLIT"):
            corporate_tax_for_tax_year(
                taxable_income_keur=D("400"),
                tax_rate_schedule=self._schedule(),
                tax_year_start=date(2026, 7, 1),
                tax_year_end=date(2027, 6, 30))

    def test_uncovered_date_is_unavailable_never_a_default(self, released):
        assert corporate_tax_for_tax_year(
            taxable_income_keur=D("400"),
            tax_rate_schedule=self._schedule(),
            tax_year_start=date(2024, 1, 1),
            tax_year_end=date(2024, 12, 31)) is None

    def test_overlapping_rate_windows_fail_closed(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_OVERLAP"):
            TaxRateSchedule(mode="DATED_SERIES", windows=(
                TaxRateWindow(date(2025, 1, 1), 0.20),
                TaxRateWindow(date(2025, 1, 1), 0.25),
            )).validate()


# ── Case 3: tax-loss carryforward use and expiration ─────────────────────────


class TestCase03LossCarryforward:
    def test_fifo_use_with_opening_vintage(self, released):
        ledger = tax_loss_schedule(
            taxable_income_after_limits_by_tax_year={2: D("200")},
            config=TaxLossCarryforwardConfig(utilisation_cap_pct=100.0,
                                             carryforward_years=5),
            opening_vintages=(OpeningLossVintage(origin_tax_year=1,
                                                 amount_keur=300.0),),
            first_tax_year=2)
        row = ledger.rows[0]
        assert row.opening_by_vintage == ((1, D("300.000000")),)
        assert row.used_keur == D("200.000000")
        assert row.closing_by_vintage == ((1, D("100.000000")),)
        assert ledger.closing_total_keur == D("100.000000")

    def test_expiration_before_use_after_the_supplied_window(self, released):
        ledger = tax_loss_schedule(
            taxable_income_after_limits_by_tax_year={
                1: D("-500"), 2: D("200"), 4: D("100"), 8: D("100")},
            config=TaxLossCarryforwardConfig(utilisation_cap_pct=100.0,
                                             carryforward_years=5),
            opening_vintages=(), first_tax_year=1)
        assert ledger.rows[0].generated_keur == D("500.000000")
        assert ledger.rows[1].used_keur == D("200.000000")
        assert ledger.rows[2].used_keur == D("100.000000")
        # year 8 > origin 1 + 5 → the remaining 200 expire BEFORE use
        assert ledger.rows[3].used_keur == D("0.000000")
        assert ledger.rows[3].expired_keur == D("200.000000")
        assert ledger.closing_total_keur == D("0.000000")
        # exact per-year identity
        for row in ledger.rows:
            opening = sum(v for _, v in row.opening_by_vintage)
            closing = sum(v for _, v in row.closing_by_vintage)
            assert closing == opening + row.generated_keur \
                - row.used_keur - row.expired_keur

    def test_utilisation_cap_is_explicit_evidence(self, released):
        ledger = tax_loss_schedule(
            taxable_income_after_limits_by_tax_year={
                1: D("-500"), 2: D("200")},
            config=TaxLossCarryforwardConfig(utilisation_cap_pct=50.0,
                                             unlimited=True),
            opening_vintages=(), first_tax_year=1)
        assert ledger.rows[1].used_keur == D("100.000000")  # 50% × 200

    def test_unlimited_requires_omitted_years(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_SCHEMA"):
            TaxLossCarryforwardConfig(utilisation_cap_pct=100.0,
                                      unlimited=True,
                                      carryforward_years=5).validate()
        with pytest.raises(ValueError, match="TAX_WF10_SCHEMA"):
            TaxLossCarryforwardConfig(utilisation_cap_pct=100.0).validate()

    def test_future_dated_opening_vintage_fails_closed(self, released):
        with pytest.raises(ValueError, match="future-dated"):
            tax_loss_schedule(
                taxable_income_after_limits_by_tax_year={3: D("100")},
                config=TaxLossCarryforwardConfig(utilisation_cap_pct=100.0,
                                                 unlimited=True),
                opening_vintages=(OpeningLossVintage(origin_tax_year=3,
                                                     amount_keur=100.0),),
                first_tax_year=3)


# ── Case 4: interest limitation with deductible/disallowed outputs ──────────


class TestCase04InterestLimitation:
    def test_ebitda_pct_binding(self, released):
        outcome = interest_limitation(InterestLimitationInputs(
            ebitda_keur=1000.0, net_interest_keur=500.0,
            ebitda_limit_pct=30.0, de_minimis_keur=100.0))
        assert outcome.capacity_keur == D("300.000000")
        assert outcome.deductible_interest_keur == D("300.000000")
        assert outcome.disallowed_interest_keur == D("200.000000")
        assert outcome.binding_rule == "EBITDA_PCT"
        # exact identity
        assert (outcome.deductible_interest_keur
                + outcome.disallowed_interest_keur
                == D("500.000000"))

    def test_de_minimis_binding(self, released):
        outcome = interest_limitation(InterestLimitationInputs(
            ebitda_keur=100.0, net_interest_keur=500.0,
            ebitda_limit_pct=30.0, de_minimis_keur=100.0))
        assert outcome.capacity_keur == D("100.000000")
        assert outcome.binding_rule == "DE_MINIMIS"
        assert outcome.disallowed_interest_keur == D("400.000000")

    def test_explicitly_disabled_deducts_everything(self, released):
        outcome = interest_limitation(InterestLimitationInputs(
            ebitda_keur=100.0, net_interest_keur=500.0,
            ebitda_limit_pct=30.0, de_minimis_keur=100.0, enabled=False))
        assert outcome.deductible_interest_keur == D("500.000000")
        assert outcome.disallowed_interest_keur == D("0.000000")
        assert outcome.binding_rule == "DISABLED"

    def test_nonpositive_ebitda_leaves_de_minimis_only(self, released):
        outcome = interest_limitation(InterestLimitationInputs(
            ebitda_keur=-500.0, net_interest_keur=500.0,
            ebitda_limit_pct=30.0, de_minimis_keur=100.0))
        assert outcome.capacity_keur == D("100.000000")

    def test_disallowed_carryforward_is_not_representable(self, released):
        """The released production engine also refuses interest-limitation
        carryforward; the candidate types the same absence (no field)."""
        assert all("carryforward" not in f.name
                   for f in InterestLimitationInputs.__dataclass_fields__.values())


# ── Case 5: accounting versus tax depreciation ───────────────────────────────


class TestCase05BookVsTaxDepreciation:
    def test_different_lives_create_exact_temporary_differences(self, released):
        asset = DepreciationAsset(
            asset_id="pv-1", category="solar_panels", gross_basis_keur=1000.0,
            book_useful_life_years=10, tax_useful_life_years=5,
            in_service_date=date(2025, 1, 1))
        periods = [DepreciationPeriod(i, date(2024+i, 1, 1), date(2024+i, 12, 31),
                                      1.0) for i in range(1, 6)]
        schedules = build_depreciation_schedules(
            asset, cod_date=date(2025, 1, 1), periods=periods)
        assert schedules.rows[0].book_keur == D("100.000000")
        assert schedules.rows[0].tax_keur == D("200.000000")
        assert schedules.rows[0].difference_keur == D("100.000000")
        assert schedules.rows[0].cumulative_difference_keur == D("100.000000")
        assert schedules.rows[2].cumulative_difference_keur == D("300.000000")
        # annual amounts hand-computed: 1000/10 = 100 book, 1000/5 = 200 tax
        # over five full years: 500 book, 1000 tax, 500 temporary difference
        assert schedules.total_book_keur == D("500.000000")
        assert schedules.total_tax_keur == D("1000.000000")
        assert schedules.total_temporary_difference_keur == D("500.000000")

    def test_periods_before_in_service_contribute_zero(self, released):
        asset = DepreciationAsset(
            asset_id="pv-1", category="solar_panels", gross_basis_keur=1000.0,
            book_useful_life_years=10, tax_useful_life_years=5,
            in_service_date=date(2025, 7, 1))
        periods = (DepreciationPeriod(1, date(2025, 1, 1), date(2025, 6, 30),
                                      0.5),
                   DepreciationPeriod(2, date(2025, 7, 1), date(2025, 12, 31),
                                      0.5))
        schedules = build_depreciation_schedules(
            asset, cod_date=date(2025, 7, 1), periods=periods)
        assert schedules.rows[0].book_keur == D("0.000000")
        assert schedules.rows[0].tax_keur == D("0.000000")
        assert schedules.rows[1].book_keur == D("50.000000")  # 100 × 0.5

    def test_non_straight_line_fails_closed_no_invented_acceleration(
            self, released):
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            DepreciationAsset(
                asset_id="pv-1", category="solar_panels",
                gross_basis_keur=1000.0, book_useful_life_years=10,
                tax_useful_life_years=5, in_service_date=date(2025, 7, 1),
                method="DECLINING_BALANCE").validate(cod_date=date(2025, 7, 1))

    def test_construction_period_in_service_fails_closed(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            DepreciationAsset(
                asset_id="pv-1", category="solar_panels",
                gross_basis_keur=1000.0, book_useful_life_years=10,
                tax_useful_life_years=5, in_service_date=date(2025, 3, 1),
            ).validate(cod_date=date(2025, 7, 1))


# ── Cases 6-8: VAT ───────────────────────────────────────────────────────────


class TestCase06ConstructionInputVatRecovery:
    def test_full_recovery_is_a_refund_position(self, released):
        config = VatConfig(rate=0.20, recovery_pct_construction=100.0,
                           recovery_pct_operating=100.0,
                           nonrecoverable_treatment="CAPITALISE")
        position = compute_vat_position(
            config, VatPeriodInput(phase="CONSTRUCTION", output_net_keur=0.0,
                                   input_net_keur=1000.0))
        assert position.input_vat_keur == D("200.000000")
        assert position.recoverable_input_vat_keur == D("200.000000")
        assert position.nonrecoverable_input_vat_keur == D("0.000000")
        # no output VAT in construction → net refundable 200 (negative)
        assert position.net_vat_cash_keur == D("-200.000000")


class TestCase07NonrecoverableVatPolicy:
    def test_capitalise_policy_adds_to_the_asset_basis_ledger(self, released):
        position = compute_vat_position(
            VatConfig(rate=0.20, recovery_pct_construction=0.0,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="CAPITALISE"),
            VatPeriodInput(phase="CONSTRUCTION", output_net_keur=0.0,
                           input_net_keur=1000.0))
        assert position.capitalised_keur == D("200.000000")
        assert position.pnl_expense_keur == D("0.000000")

    def test_expense_policy_hits_the_pnl_ledger(self, released):
        position = compute_vat_position(
            VatConfig(rate=0.20, recovery_pct_construction=0.0,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="EXPENSE"),
            VatPeriodInput(phase="CONSTRUCTION", output_net_keur=0.0,
                           input_net_keur=1000.0))
        assert position.pnl_expense_keur == D("200.000000")
        assert position.capitalised_keur == D("0.000000")

    def test_policy_is_explicit_only(self):
        """The treatment field has NO default: a config without the policy
        is unconstructible (missing recovery assumptions cannot slip)."""
        with pytest.raises(TypeError):
            VatConfig(rate=0.20, recovery_pct_construction=100.0,
                      recovery_pct_operating=100.0)
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            VatConfig(rate=0.20, recovery_pct_construction=100.0,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="NEUTRALISE").validate()


class TestCase08VatTimingAndLiquidity:
    def test_operating_net_position_and_ledger_separation(self, released):
        config = VatConfig(rate=0.20, recovery_pct_construction=100.0,
                           recovery_pct_operating=50.0,
                           nonrecoverable_treatment="EXPENSE")
        position = compute_vat_position(
            config, VatPeriodInput(phase="OPERATING", output_net_keur=1000.0,
                                   input_net_keur=400.0))
        # output VAT 200; input VAT 80; recoverable 40; non-recoverable 40
        assert position.output_vat_keur == D("200.000000")
        assert position.input_vat_keur == D("80.000000")
        assert position.recoverable_input_vat_keur == D("40.000000")
        assert position.nonrecoverable_input_vat_keur == D("40.000000")
        # cash ledger: 200 payable − 40 recoverable = 160 payable
        assert position.net_vat_cash_keur == D("160.000000")
        # P&L ledger: the non-recoverable 40 is expensed, NOT a cash VAT item
        assert position.pnl_expense_keur == D("40.000000")
        assert position.net_vat_cash_keur != position.pnl_expense_keur

    def test_refund_months_are_negative_cash_not_zero(self, released):
        position = compute_vat_position(
            VatConfig(rate=0.20, recovery_pct_construction=100.0,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="CAPITALISE"),
            VatPeriodInput(phase="CONSTRUCTION", output_net_keur=0.0,
                           input_net_keur=500.0))
        assert position.net_vat_cash_keur == D("-100.000000")


# ── Cases 9-10: withholding (dividends, SHL, senior/junior) ──────────────────


class TestCase09DividendWithholding:
    def test_gross_net_conservation_exact(self, released):
        outcome = apply_withholding(WithholdingApplication(
            "div-1", WithholdingRule("DIVIDEND", 0.05, "spv-1", "investor",
                                     "national-law-xa-2026"),
            1000.0, period_index=3))
        assert outcome.gross_keur == D("1000.000000")
        assert outcome.withheld_keur == D("50.000000")
        assert outcome.net_keur == D("950.000000")
        assert outcome.withheld_keur + outcome.net_keur == outcome.gross_keur

    def test_zero_rate_is_explicit_zero_not_missing(self, released):
        outcome = apply_withholding(WithholdingApplication(
            "div-2", WithholdingRule("DIVIDEND", 0.0, "spv-1", "investor",
                                     "national-law-xa-2026"),
            1000.0))
        assert outcome.withheld_keur == D("0.000000")
        assert outcome.net_keur == D("1000.000000")


class TestCase10ShlAndSeniorJuniorWithholding:
    def test_shl_interest_withholding(self, released):
        outcome = apply_withholding(WithholdingApplication(
            "shl-int-1", WithholdingRule("SHL_INTEREST", 0.02, "spv-1",
                                         "holdco-1", "national-law-xa-2026"),
            250.0))
        assert outcome.withheld_keur == D("5.000000")
        assert outcome.net_keur == D("245.000000")

    def test_senior_interest_requires_a_supported_legal_basis(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            WithholdingRule("SENIOR_INTEREST", 0.10, "spv-1", "bank",
                            "x").validate()
        outcome = apply_withholding(WithholdingApplication(
            "sen-int-1", WithholdingRule("SENIOR_INTEREST", 0.10, "spv-1",
                                         "bank", "treaty-xa-bank-art-11"),
            100.0))
        assert outcome.withheld_keur == D("10.000000")

    def test_junior_interest_requires_a_supported_legal_basis(self, released):
        # an EMPTY basis fails the identity check first (still fail-closed)…
        with pytest.raises(ValueError, match="TAX_WF10_SCHEMA"):
            WithholdingRule("JUNIOR_INTEREST", 0.10, "spv-1", "junior",
                            "").validate()
        # …and a too-short basis hits the dedicated unsupported code
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            WithholdingRule("JUNIOR_INTEREST", 0.10, "spv-1", "junior",
                            "x").validate()


# ── Case 11: SPV versus HoldCo separate tax entities ─────────────────────────


class TestCase11SeparateTaxEntities:
    def _book(self):
        return TaxCandidateBook(entities=(
            TaxEntityBook(
                identity=TaxEntityIdentity("spv-1", "XA", "SPV"),
                rate_schedule=TaxRateSchedule(mode="FLAT", flat_rate=0.20),
            ),
            TaxEntityBook(
                identity=TaxEntityIdentity("holdco-1", "XB", "HOLDCO"),
                rate_schedule=TaxRateSchedule(mode="FLAT", flat_rate=0.25),
            ),
        ))

    def test_each_entity_taxed_on_its_own_evidence_only(self, released):
        book = self._book()
        spv = book.entity("spv-1")
        holdco = book.entity("holdco-1")
        spv_tax = corporate_tax_for_tax_year(
            taxable_income_keur=D("500"),
            tax_rate_schedule=spv.rate_schedule,
            tax_year_start=date(2026, 1, 1), tax_year_end=date(2026, 12, 31))
        holdco_tax = corporate_tax_for_tax_year(
            taxable_income_keur=D("500"),
            tax_rate_schedule=holdco.rate_schedule,
            tax_year_start=date(2026, 1, 1), tax_year_end=date(2026, 12, 31))
        assert spv_tax == D("100.000000")
        assert holdco_tax == D("125.000000")

    def test_no_consolidation_exists_in_the_candidate(self):
        """Structural: no consolidation routine exists anywhere in the
        package (mission: no automatic consolidated tax assumption)."""
        package = REPO / "app" / "model_v2" / "tax_wf10_candidate"
        for py in sorted(package.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            names = [node.name for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef))]
            assert not [n for n in names if "consolidat" in n.lower()], py

    def test_duplicate_entity_ids_fail_closed(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_IDENTITY"):
            TaxCandidateBook(entities=(
                TaxEntityBook(TaxEntityIdentity("spv-1", "XA", "SPV")),
                TaxEntityBook(TaxEntityIdentity("spv-1", "XA", "SPV")),
            )).validate()


# ── Case 12: missing assumptions and unsupported arrangements ────────────────


class TestCase12MissingAssumptions:
    def test_jurisdiction_alone_never_selects_a_rate(self, released):
        book = TaxCandidateBook(entities=(
            TaxEntityBook(identity=TaxEntityIdentity("spv-1", "XA", "SPV")),
        ))
        book.validate()
        entity = book.entity("spv-1")
        # the jurisdiction is carried as an opaque label...
        assert entity.identity.jurisdiction_code == "XA"
        # ...and NO rate exists to apply: the evidence is simply absent
        assert entity.rate_schedule is None

    def test_missing_rate_schedule_is_unavailable_not_defaulted(self, released):
        schedule = TaxRateSchedule(mode="DATED_SERIES", windows=(
            TaxRateWindow(date(2027, 1, 1), 0.20),
        ))
        assert corporate_tax_for_tax_year(
            taxable_income_keur=D("100"), tax_rate_schedule=schedule,
            tax_year_start=date(2025, 1, 1),
            tax_year_end=date(2025, 12, 31)) is None

    def test_vat_recovery_percentages_are_required_evidence(self, released):
        with pytest.raises(TypeError):
            VatConfig(rate=0.20, recovery_pct_construction=100.0,
                      nonrecoverable_treatment="EXPENSE")
        with pytest.raises(ValueError, match="TAX_WF10_VALUE"):
            VatConfig(rate=0.20, recovery_pct_construction=None,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="EXPENSE").validate()

    def test_unknown_arrangements_fail_closed(self, released):
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            TaxEntityIdentity("e1", "XA", "PARTNERSHIP").validate()
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            VatConfig(rate=0.2, recovery_pct_construction=100.0,
                      recovery_pct_operating=100.0,
                      nonrecoverable_treatment="CREDIT").validate()
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            WithholdingRule("ROYALTY", 0.1, "spv", "licensor",
                            "law").validate()

    def test_malformed_numbers_fail_closed(self, released):
        for bad in (float("nan"), float("inf"), True, "0.2"):
            with pytest.raises(ValueError, match="TAX_WF10_VALUE"):
                VatConfig(rate=bad, recovery_pct_construction=100.0,
                          recovery_pct_operating=100.0,
                          nonrecoverable_treatment="EXPENSE").validate()


# ── Case 13: leap years, COD stubs and period boundaries ─────────────────────


class TestCase13CanonicalBoundaries:
    def test_cod_stub_period_uses_the_released_day_fraction(
            self, released, canonical_axis):
        operating = _operating(canonical_axis)
        stub = operating[0]
        assert stub.start_date == date(2025, 7, 1)
        assert stub.day_fraction == pytest.approx(184 / 365)
        asset = DepreciationAsset(
            asset_id="pv-1", category="solar_panels", gross_basis_keur=1000.0,
            book_useful_life_years=10, tax_useful_life_years=10,
            in_service_date=date(2025, 7, 1))
        schedules = build_depreciation_schedules(
            asset, cod_date=date(2025, 7, 1),
            periods=(DepreciationPeriod(
                stub.index, stub.start_date, stub.end_date,
                stub.day_fraction),))
        expected = (D("100") * D(str(stub.day_fraction))).quantize(
            Decimal("0.000001"))
        assert schedules.rows[0].book_keur == expected
        assert schedules.rows[0].tax_keur == expected

    def test_leap_year_row_uses_the_released_denominator(
            self, released, canonical_axis):
        leap_row = next(p for p in _operating(canonical_axis)
                        if p.is_leap_year and p.start_date <= date(2028, 2, 29)
                        <= p.end_date)
        assert leap_row.is_leap_year is True
        # the released denominator: days / 366 in leap years
        assert leap_row.day_fraction == pytest.approx(
            leap_row.days_in_period / 366)
        asset = DepreciationAsset(
            asset_id="pv-1", category="solar_panels", gross_basis_keur=1000.0,
            book_useful_life_years=10, tax_useful_life_years=10,
            in_service_date=date(2025, 7, 1))
        schedules = build_depreciation_schedules(
            asset, cod_date=date(2025, 7, 1),
            periods=(DepreciationPeriod(
                leap_row.index, leap_row.start_date, leap_row.end_date,
                leap_row.day_fraction),))
        expected = (D("100") * D(str(leap_row.day_fraction))).quantize(
            Decimal("0.000001"))
        assert schedules.rows[0].book_keur == expected

    def test_loss_ledger_is_tax_year_keyed_not_day_keyed(self, released):
        """Leap years and stubs affect day-proportional surfaces only; the
        loss ledger is keyed by the caller's canonical tax years."""
        ledger = tax_loss_schedule(
            taxable_income_after_limits_by_tax_year={1: D("-100"),
                                                     2: D("50")},
            config=TaxLossCarryforwardConfig(utilisation_cap_pct=100.0,
                                             unlimited=True),
            opening_vintages=(), first_tax_year=1)
        assert ledger.rows[1].used_keur == D("50.000000")


# ── Case 14: negative taxable income ─────────────────────────────────────────


class TestCase14NegativeTaxableIncome:
    def test_negative_income_generates_a_loss_and_never_negative_tax(
            self, released):
        rec = taxable_income_reconciliation(
            tax_year=2, ebitda_keur=-300.0, tax_depreciation_keur=200.0,
            deductible_interest_keur=100.0)
        assert rec.taxable_before_losses_keur == D("-600.000000")
        assert rec.taxable_after_losses_keur == D("0.000000")
        assert rec.loss_generated_keur == D("600.000000")
        tax = corporate_tax_for_tax_year(
            taxable_income_keur=rec.taxable_after_losses_keur,
            tax_rate_schedule=TaxRateSchedule(mode="FLAT", flat_rate=0.20),
            tax_year_start=date(2026, 1, 1), tax_year_end=date(2026, 12, 31))
        assert tax == D("0.000000")

    def test_corporate_tax_never_returns_negative(self, released):
        tax = corporate_tax_for_tax_year(
            taxable_income_keur=D("-500"),
            tax_rate_schedule=TaxRateSchedule(mode="FLAT", flat_rate=0.20),
            tax_year_start=date(2026, 1, 1), tax_year_end=date(2026, 12, 31))
        assert tax == D("0.000000")


# ── Case 15: double-taxation / double-withholding prevention ─────────────────


class TestCase15DoubleWithholdingPrevention:
    def test_same_flow_id_twice_fails_closed(self, released):
        rule = WithholdingRule("DIVIDEND", 0.05, "spv-1", "investor",
                               "national-law-xa-2026")
        with pytest.raises(ValueError, match="TAX_WF10_DOUBLE_WITHHOLDING"):
            withholding_ledger((
                WithholdingApplication("div-1", rule, 1000.0),
                WithholdingApplication("div-1", rule, 1000.0),
            ))

    def test_distinct_flows_apply_independently(self, released):
        rule = WithholdingRule("DIVIDEND", 0.05, "spv-1", "investor",
                               "national-law-xa-2026")
        outcomes = withholding_ledger((
            WithholdingApplication("div-1", rule, 1000.0, period_index=1),
            WithholdingApplication("div-2", rule, 500.0, period_index=2),
        ))
        assert [o.withheld_keur for o in outcomes] == \
            [D("50.000000"), D("25.000000")]

    def test_duplicate_intercompany_flow_ids_fail_closed(self, released):
        book = TaxCandidateBook(entities=(
            TaxEntityBook(TaxEntityIdentity("spv-1", "XA", "SPV")),
            TaxEntityBook(TaxEntityIdentity("holdco-1", "XB", "HOLDCO")),
        ))
        with pytest.raises(ValueError, match="TAX_WF10_IDENTITY"):
            TaxCandidateBook(
                entities=book.entities,
                intercompany_flows=(
                    IntercompanyFlow("i1", "spv-1", "holdco-1", "INTEREST",
                                     0, 250.0),
                    IntercompanyFlow("i1", "spv-1", "holdco-1", "INTEREST",
                                     1, 250.0),
                )).validate()


# ── Case 16: zero cross-entity leakage ───────────────────────────────────────


class TestCase16ZeroCrossEntityLeakage:
    def test_intercompany_interest_identity_is_exact(self, released):
        book = TaxCandidateBook(entities=(
            TaxEntityBook(TaxEntityIdentity("spv-1", "XA", "SPV")),
            TaxEntityBook(TaxEntityIdentity("holdco-1", "XB", "HOLDCO")),
        ))
        attribution = attribute_intercompany_interest(
            IntercompanyFlow("i1", "spv-1", "holdco-1", "INTEREST", 0,
                             250.0),
            book=book)
        assert attribution.payer_deduction_keur == D("250.000000")
        assert attribution.payee_taxable_income_keur == D("250.000000")
        assert attribution.payer_deduction_keur \
            == attribution.payee_taxable_income_keur

    def test_shl_principal_is_never_taxable_income(self, released):
        """Mirrors the released HoldCo authority: principal repayment is a
        balance-sheet movement, never taxable income."""
        book = TaxCandidateBook(entities=(
            TaxEntityBook(TaxEntityIdentity("spv-1", "XA", "SPV")),
            TaxEntityBook(TaxEntityIdentity("holdco-1", "XB", "HOLDCO")),
        ))
        with pytest.raises(ValueError, match="TAX_WF10_UNSUPPORTED"):
            attribute_intercompany_interest(
                IntercompanyFlow("p1", "spv-1", "holdco-1", "PRINCIPAL", 0,
                                 250.0),
                book=book)

    def test_flows_reference_known_entities_only(self, released):
        book = TaxCandidateBook(entities=(
            TaxEntityBook(TaxEntityIdentity("spv-1", "XA", "SPV")),
        ))
        with pytest.raises(ValueError, match="TAX_WF10_IDENTITY"):
            TaxCandidateBook(
                entities=book.entities,
                intercompany_flows=(IntercompanyFlow(
                    "i1", "spv-1", "ghost", "INTEREST", 0, 250.0),)).validate()
        with pytest.raises(ValueError, match="TAX_WF10_IDENTITY"):
            TaxCandidateBook(
                entities=book.entities,
                withholding_rules=(WithholdingRule(
                    "DIVIDEND", 0.05, "spv-1", "ghost", "law"),)).validate()
        with pytest.raises(ValueError, match="TAX_WF10_VALUE"):
            IntercompanyFlow("i1", "spv-1", "spv-1", "INTEREST", 0,
                             250.0).validate()


# ── Case 17: existing canonical financial outputs unchanged ─────────────────


class TestCase17CanonicalOutputsUnchanged:
    def test_candidate_imports_nothing_from_production(self):
        package = REPO / "app" / "model_v2" / "tax_wf10_candidate"
        forbidden = ("financial_engine", "finco_core", "domain.tax",
                     "domain.revenue", "app.persistence", "app.services",
                     "app.api", "app.v2", "fastapi", "sqlite3",
                     "financing_instruments")
        for py in sorted(package.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for token in forbidden:
                            assert token not in alias.name, (py, alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for token in forbidden:
                        assert token not in module, (py, module)

    def test_no_production_module_references_the_candidate(self):
        import json
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import json, pathlib, sys\n"
             "roots = ['app', 'domain', 'financial_engine', 'finco_core', 'tools', 'static', 'deploy', '.github', 'main_web.py', 'main_api.py', 'main_mcp.py']\n"
             "exts = {'.py', '.yml', '.yaml', '.json', '.html', '.js', '.toml'}\n"
             "bad = []\n"
             "for root in roots:\n"
             "    p = pathlib.Path(root)\n"
             "    files = [p] if p.is_file() else [f for f in sorted(p.rglob('*')) if f.suffix in exts]\n"
             "    for f in files:\n"
             "        try:\n"
             "            t = f.read_text(encoding='utf-8')\n"
             "        except Exception:\n"
             "            continue\n"
             "        if 'tax_wf10_candidate' in t:\n"
             "            bad.append(str(f))\n"
             "print(json.dumps(bad))"],
            cwd=str(REPO), capture_output=True, text=True)
        referers = set(json.loads(result.stdout.strip()))
        own = {r for r in referers
               if r.replace("\\", "/").startswith("app/model_v2/tax_wf10_candidate")}
        assert referers == own, \
            f"production files reference the candidate: {sorted(referers - own)}"

    def test_released_tax_files_are_untouched_on_this_branch(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--",
             "domain/tax/", "financial_engine/", "finco_core/",
             "app/revenue_v4_candidate/", "app/generation_v2_candidate/",
             "app/model_v2/canonical_analytics.py"],
            cwd=str(REPO), capture_output=True, text=True)
        assert result.returncode == 0
        # A reviewed FIN-V2 source cohort does not alter or activate this tax candidate. Admit only its complete exact committed
        # cohort; every other released-engine change fails.
        from tests.fin_v2_cohorts import matches
        unreviewed = [path for path in result.stdout.splitlines()
                      if not matches(path, repo=REPO, ref="HEAD")]
        assert unreviewed == [], unreviewed


# Correction A: independent precision and date-boundary regressions.
@pytest.mark.parametrize('money',[D('9007199254740993.123456'),D('12345678901234567890123456789012345678901234567890.123456')])
def test_correction_a_decimal_money_never_round_trips_float(released,money):
    from app.model_v2.tax_wf10_candidate.pure import _dec
    assert _dec(money,'synthetic') is money
    result=corporate_tax_for_tax_year(taxable_income_keur=money,tax_rate_schedule=TaxRateSchedule('FLAT',1),tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))
    assert result==money
    rec=taxable_income_reconciliation(tax_year=2025,ebitda_keur=money,tax_depreciation_keur=0,deductible_interest_keur=0)
    assert rec.taxable_before_losses_keur==money


@pytest.mark.parametrize('income,rate,expected',[('0.000005','.1','0.000001'),('0.0000049','.1','0.000000'),('0.0000005','.5','0.000000'),('1.2345675','1','1.234568')])
def test_correction_a_cit_boundary_rounding(released,income,rate,expected):
    result=corporate_tax_for_tax_year(taxable_income_keur=D(income),tax_rate_schedule=TaxRateSchedule('FLAT',D(rate)),tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))
    assert result==D(expected)


@pytest.mark.parametrize('bad',[D('NaN'),D('Infinity'),D('-Infinity'),float('nan'),float('inf'),True])
def test_correction_a_nonfinite_money_rejected(released,bad):
    with pytest.raises(ValueError,match='TAX_WF10_VALUE'):
        corporate_tax_for_tax_year(taxable_income_keur=bad,tax_rate_schedule=TaxRateSchedule('FLAT',.1),tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))
    with pytest.raises(ValueError,match='TAX_WF10_VALUE'):
        VatPeriodInput('OPERATING',bad,0).validate()


def test_correction_a_float_evidence_uses_its_decimal_spelling():
    from app.model_v2.tax_wf10_candidate.pure import _dec
    value=0.1+0.2
    assert _dec(value,'binary evidence')==D(str(value))
    assert _dec(9007199254740993,'integer evidence')==D(9007199254740993)


@pytest.mark.parametrize('rates',[(.1,.2,.1),(.1,.2,.3),(.1,.1,.2,.1)])
def test_correction_a_all_intrayear_rate_transitions_detected(released,rates):
    windows=tuple(TaxRateWindow(date(2025,i+1,1),r) for i,r in enumerate(rates))
    with pytest.raises(ValueError,match='TAX_WF10_TAX_YEAR_RATE_SPLIT'):
        corporate_tax_for_tax_year(taxable_income_keur=D(100),tax_rate_schedule=TaxRateSchedule('DATED_SERIES',windows=windows),tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))


def test_correction_a_unsorted_schedule_fails_closed():
    schedule=TaxRateSchedule('DATED_SERIES',windows=(TaxRateWindow(date(2026,1,1),.2),TaxRateWindow(date(2025,1,1),.1)))
    with pytest.raises(ValueError,match='TAX_WF10_RATE_ORDER'):schedule.validate()
    with pytest.raises(ValueError,match='TAX_WF10_RATE_ORDER'):schedule.rate_on(date(2026,6,1))


def test_correction_a_cit_boundary_dates_stable_and_uncovered(released):
    schedule=TaxRateSchedule('DATED_SERIES',windows=(TaxRateWindow(date(2025,1,1),.1),TaxRateWindow(date(2026,1,1),.2)))
    def cit(start,end):return corporate_tax_for_tax_year(taxable_income_keur=D(100),tax_rate_schedule=schedule,tax_year_start=start,tax_year_end=end)
    assert cit(date(2025,1,1),date(2025,12,31))==10
    assert cit(date(2026,1,1),date(2026,12,31))==20
    assert cit(date(2024,12,31),date(2025,12,31)) is None
    with pytest.raises(ValueError,match='RATE_SPLIT'):cit(date(2025,1,1),date(2026,1,1))
    with pytest.raises(ValueError,match='TAX_WF10_VALUE'):cit(date(2026,1,1),date(2025,1,1))
    identical=TaxRateSchedule('DATED_SERIES',windows=(TaxRateWindow(date(2025,1,1),.1),TaxRateWindow(date(2025,6,1),.1)))
    assert corporate_tax_for_tax_year(taxable_income_keur=D(100),tax_rate_schedule=identical,tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))==10


@pytest.mark.parametrize('income,used',[('100','101'),('100','100.0000001'),('0','1'),('-50','1'),('100','-1')])
def test_correction_a_loss_overutilisation_rejected(released,income,used):
    with pytest.raises(ValueError,match='TAX_WF10_LOSS_UTILISATION'):
        taxable_income_reconciliation(tax_year=2025,ebitda_keur=D(income),tax_depreciation_keur=0,deductible_interest_keur=0,loss_used_keur=D(used))


def test_correction_a_legitimate_loss_and_exact_posted_identities(released):
    positive=taxable_income_reconciliation(tax_year=2025,ebitda_keur=D('100.123456'),tax_depreciation_keur=0,deductible_interest_keur=0,loss_used_keur=D('100.123456'))
    assert positive.taxable_after_losses_keur==positive.loss_generated_keur==0
    negative=taxable_income_reconciliation(tax_year=2025,ebitda_keur=D('-50.123456'),tax_depreciation_keur=0,deductible_interest_keur=0)
    assert negative.loss_generated_keur==D('50.123456') and negative.taxable_after_losses_keur==0
    rec=taxable_income_reconciliation(tax_year=2025,ebitda_keur=D('1.0000005'),financing_income_keur=D('1.0000005'),tax_depreciation_keur=0,deductible_interest_keur=0)
    assert rec.taxable_before_losses_keur==rec.ebitda_keur+rec.financing_income_keur-rec.tax_depreciation_keur+rec.non_deductible_addbacks_keur-rec.deductible_interest_keur+rec.rounding_adjustment_keur


def test_correction_a_partial_asset_requires_explicit_active_fraction(released):
    asset=DepreciationAsset('synthetic','asset',D(1000),10,5,date(2025,7,1))
    period=DepreciationPeriod(1,date(2025,1,1),date(2025,12,31),D(1))
    with pytest.raises(ValueError,match='TAX_WF10_DEPRECIATION_PRORATION_REQUIRED'):
        build_depreciation_schedules(asset,cod_date=date(2025,1,1),periods=(period,))
    from dataclasses import replace
    supplied=replace(period,active_day_fraction=D('.5'),active_fraction_source='synthetic independent active-year fraction')
    r=build_depreciation_schedules(asset,cod_date=date(2025,1,1),periods=(supplied,))
    assert r.rows[0].book_keur==50 and r.rows[0].tax_keur==100
    with pytest.raises(ValueError):build_depreciation_schedules(asset,cod_date=date(2025,1,1),periods=(replace(supplied,active_day_fraction=D('1.1')),))
    at_end=replace(asset,in_service_date=date(2025,12,31))
    with pytest.raises(ValueError,match='PRORATION_REQUIRED'):build_depreciation_schedules(at_end,cod_date=date(2025,1,1),periods=(period,))


def test_correction_a_all_money_paths_independent_of_ambient_context(released):
    from decimal import localcontext, ROUND_DOWN, ROUND_UP, Inexact
    value=D('9007199254740993.123456')
    def evaluate():
        return (
            corporate_tax_for_tax_year(taxable_income_keur=value,tax_rate_schedule=TaxRateSchedule('FLAT',D('.2')),tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31)),
            tax_loss_schedule(taxable_income_after_limits_by_tax_year={2025:value},config=TaxLossCarryforwardConfig(100,unlimited=True),opening_vintages=(OpeningLossVintage(2024,value),),first_tax_year=2025),
            apply_withholding(WithholdingApplication('synthetic',WithholdingRule('DIVIDEND',D('.2'),'payer','payee','synthetic supplied rule'),value)),
            compute_vat_position(VatConfig(D('.2'),100,100,'EXPENSE'),VatPeriodInput('OPERATING',value,value)),
            build_depreciation_schedules(DepreciationAsset('synthetic','asset',value,2,4,date(2025,1,1)),cod_date=date(2025,1,1),periods=(DepreciationPeriod(1,date(2025,1,1),date(2025,12,31),D(1)),)),
        )
    with localcontext() as ctx:
        ctx.prec=4;ctx.rounding=ROUND_DOWN;ctx.traps[Inexact]=True
        low=evaluate()
    with localcontext() as ctx:
        ctx.prec=90;ctx.rounding=ROUND_UP
        high=evaluate()
    assert low==high
    assert low[1].total_used_keur==value
    assert low[2].gross_keur==value and low[2].gross_keur==low[2].withheld_keur+low[2].net_keur


def test_correction_a_micro_loss_and_withholding_postings_reconcile(released):
    ledger=tax_loss_schedule(taxable_income_after_limits_by_tax_year={2025:D('-.0000005'),2026:D('.000001')},config=TaxLossCarryforwardConfig(100,unlimited=True),first_tax_year=2025)
    assert ledger.rows[0].generated_keur==D('.000001') and ledger.rows[1].used_keur==D('.000001')
    assert ledger.closing_total_keur==0
    w=apply_withholding(WithholdingApplication('micro',WithholdingRule('DIVIDEND',D('.5'),'payer','payee','synthetic'),D('.000001')))
    assert w.gross_keur==w.withheld_keur+w.net_keur and w.net_keur==0



def test_correction_a_positive_exact_income_never_creates_rounding_loss(released):
    result=taxable_income_reconciliation(tax_year=2025,ebitda_keur=D('.00000049'),financing_income_keur=D('.00000049'),tax_depreciation_keur=D('.00000051'),deductible_interest_keur=0)
    assert result.taxable_before_losses_keur==0 and result.loss_generated_keur==0
    assert result.rounding_adjustment_keur==D('.000001')



def test_correction_a_equal_decimal_and_binary_rate_evidence_is_stable(released):
    schedule=TaxRateSchedule('DATED_SERIES',windows=(TaxRateWindow(date(2025,1,1),.1),TaxRateWindow(date(2025,6,1),D('.1'))))
    assert corporate_tax_for_tax_year(taxable_income_keur=D(100),tax_rate_schedule=schedule,tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))==D(10)



def test_correction_a_missing_rate_does_not_mask_nonfinite_money(released):
    schedule=TaxRateSchedule('DATED_SERIES',windows=(TaxRateWindow(date(2030,1,1),.1),))
    with pytest.raises(ValueError,match='TAX_WF10_VALUE'):
        corporate_tax_for_tax_year(taxable_income_keur=D('NaN'),tax_rate_schedule=schedule,tax_year_start=date(2025,1,1),tax_year_end=date(2025,12,31))



@pytest.mark.parametrize('income',[D(0),D(100)])
def test_correction_a_empty_loss_ledger_stays_zero(released,income):
    r=tax_loss_schedule(taxable_income_after_limits_by_tax_year={2025:income},config=TaxLossCarryforwardConfig(100,unlimited=True),first_tax_year=2025)
    assert r.closing_total_keur==r.total_used_keur==r.total_expired_keur==0
    assert r.rows[0].opening_by_vintage==r.rows[0].closing_by_vintage==()
