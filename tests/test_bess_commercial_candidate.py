"""WF-08A BESS commercial and lender contract candidate — acceptance battery (release-closed).

All economic inputs are synthetic or come from the existing native BESS synthetic example
(``domain.bess.synthetic.example``); nothing here is Financial Owner policy approval. Coverage map:

  1 NET_SPREAD vs EXPLICIT_BUY_LEG            8 dispatch allocation without double claims
  2 no charging-cost double counting          9 capacity obligations vs throughput obligations
  3 grid import/export + receipt reconcile   10 augmentation threshold + unsupported posting
  4 zero vs missing evidence                 11 multi-period and partial-COD
  5 contracted / merchant classification     12 deterministic output + provenance identity
  6 unsecured as a separate category         13 release closure + production isolation
  7 tolling availability / penalty edges     14 bit-identical existing BESS outputs
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal as D, localcontext
from pathlib import Path

import pytest

import app.bess_commercial_candidate.contracts as contracts
from app.bess_commercial_candidate import (
    AugmentationCommercialPolicy, AugmentationTrigger, BessCommercialError, ChargingBasis, ChargingPeriod,
    Decision, Direction, EnergyClaim, LegKind, Party, PerformanceDeduction, ReceiptLeg, ReservationClaim,
    RevenueClass, RevenueLine, Service, TollingContract, TollingOpenDecisions, TollingPeriod, allocate,
    augmentation_financial_posting, build_lcos_receipts, canonical_json, charging_book, charging_statement,
    evaluate_trigger, identity, link_to_allocation, native_charging_period, native_event_alignment,
    native_net_spread_period, present_for_lender, reconcile_with_native_hours, reservation_for_tolling,
    stack_by_service, tolling_statement,
)
from domain.bess.contracts import parse_configuration
from domain.bess.dispatch import evaluate
from domain.bess.settlement import FinancialPeriodProposal
from domain.bess.synthetic import example

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


@pytest.fixture()
def released(monkeypatch):
    """Isolated acceptance fixture: open the candidate gate in memory only."""
    monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)
    yield


@pytest.fixture(scope="module")
def native():
    return evaluate(parse_configuration(json.dumps(example())))


def day(native, n):
    return native.hours[24 * n:24 * (n + 1)]


def total(hours, field):
    return sum((getattr(h, field) for h in hours), D(0))


def proposal(hours, index=1):
    return FinancialPeriodProposal(
        index, hours[-1].end.date().isoformat(), len(hours), 1,
        total(hours, "grid_import_mwh"), total(hours, "grid_export_mwh"), total(hours, "gross_sale_revenue_keur"),
        total(hours, "charging_purchase_cost_keur"), total(hours, "auxiliary_purchase_cost_keur"),
        total(hours, "grid_import_charge_keur"), total(hours, "grid_export_charge_keur"),
        total(hours, "net_merchant_contribution_keur"), D(0), D(0))


def explicit(hours, pid="P1", evid="ev-1"):
    return native_charging_period(proposal(hours), pid, evid)


def legs(**amounts):
    base = {k: D(1) for k in LegKind}
    base.update({LegKind[k]: v for k, v in amounts.items()})
    return tuple(ReceiptLeg(k, f"r-{k.value}", base[k]) for k in LegKind)


def spread(pid="P1", evid="ev-s", price=D(40), mwh=D("1.62")):
    return ChargingPeriod(pid, ChargingBasis.NET_SPREAD, evid, (), price, mwh)


# ── 1. NET_SPREAD vs EXPLICIT_BUY_LEG ───────────────────────────────────────


class TestChargingBases:
    def test_net_spread_never_invents_a_charging_cost(self, released, native):
        st = charging_statement(spread())
        assert st.status == "CANDIDATE" and st.net_contribution_keur == D("1.62") * 40 / 1000
        assert st.gross_charging_cost_keur is None and st.charging_cost_deductions == 0
        assert [l.kind for l in st.lines] == ["NET_SPREAD_CONTRIBUTION"]

    def test_explicit_buy_leg_uses_the_native_receipts_and_deducts_charging_once(self, released, native):
        hours = day(native, 0)
        st = charging_statement(explicit(hours))
        assert st.status == "CANDIDATE" and st.charging_cost_deductions == 1
        assert st.net_contribution_keur == total(hours, "net_merchant_contribution_keur")
        assert st.gross_charging_cost_keur == (total(hours, "charging_purchase_cost_keur")
                                               + total(hours, "auxiliary_purchase_cost_keur"))
        assert sorted(l.kind for l in st.lines) == sorted(k.value for k in LegKind)

    def test_the_two_bases_are_distinct_results_for_the_same_trade(self, released, native):
        hours = day(native, 0)
        explicit_net = charging_statement(explicit(hours)).net_contribution_keur
        spread_net = charging_statement(spread(mwh=total(hours, "ac_discharge_mwh"))).net_contribution_keur
        assert explicit_net != spread_net   # a spread price is not the explicit buy-leg economics

    def test_bases_cannot_be_mixed(self, released):
        with pytest.raises(BessCommercialError, match="MIXED_BASIS"):
            ChargingPeriod("P1", ChargingBasis.NET_SPREAD, "e", legs(), D(40), D(1))
        with pytest.raises(BessCommercialError, match="MIXED_BASIS"):
            ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", legs(), D(40), D(1),
                           D(1), D(1))
        with pytest.raises(BessCommercialError, match="MIXED_BASIS"):
            ChargingPeriod("P1", ChargingBasis.NET_SPREAD, "e", (), D(40), D(1), grid_import_mwh=D(1))

    def test_explicit_requires_exactly_one_leg_of_each_kind(self, released):
        for bad in (legs()[:-1], legs() + (ReceiptLeg(LegKind.GROSS_SALE, "extra", D(1)),)):
            with pytest.raises(BessCommercialError, match="exactly one leg"):
                ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", bad, None, None, D(1), D(1))

    def test_basis_must_be_a_typed_member(self, released):
        with pytest.raises(BessCommercialError, match="UNSUPPORTED"):
            ChargingPeriod("P1", "NET_SPREAD", "e", (), D(1), D(1))


# ── 2. No charging-cost double counting ─────────────────────────────────────


class TestNoDoubleCounting:
    def test_a_period_cannot_be_settled_under_two_bases(self, released, native):
        explicit_period = explicit(day(native, 0), pid="P1", evid="ev-a")
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*period_id"):
            charging_book((explicit_period, spread(pid="P1", evid="ev-b")))

    def test_a_receipt_or_evidence_identity_cannot_be_reused(self, released, native):
        a, b = explicit(day(native, 0), "P1", "ev-1"), explicit(day(native, 1), "P2", "ev-2")
        assert len(charging_book((a, b))) == 2
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*evidence_id"):
            charging_book((a, explicit(day(native, 1), "P2", "ev-1")))
        reused = ChargingPeriod("P2", ChargingBasis.EXPLICIT_BUY_LEG, "ev-9", a.legs, None, None, D(1), D(1))
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*receipt_id"):
            charging_book((a, reused))

    def test_duplicate_receipt_ids_within_a_period_are_rejected(self, released):
        dup = tuple(ReceiptLeg(k, "same", D(1)) for k in LegKind)
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT"):
            ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", dup, None, None, D(1), D(1))

    def test_native_proposal_with_inconsistent_net_is_rejected(self, released, native):
        good = proposal(day(native, 0))
        bad = FinancialPeriodProposal(*[
            (good.net_merchant_contribution_keur + D("0.001")) if name == "net_merchant_contribution_keur"
            else getattr(good, name) for name in good.__dataclass_fields__])
        with pytest.raises(BessCommercialError, match="RECONCILIATION"):
            native_charging_period(bad, "P1", "ev-1")

    def test_a_net_spread_period_gives_the_lcos_boundary_no_gross_charging_cost(self, released, native):
        hours = day(native, 0)
        st = charging_statement(spread(mwh=total(hours, "ac_discharge_mwh")))
        receipts = build_lcos_receipts(st, hours, operating_cost_keur=D(1), operating_cost_ref="opex-1",
                                       methodology_ref="m-1")
        assert receipts.status == "UNAVAILABLE" and receipts.gross_charging_purchase_keur is None
        assert any("not independently known" in r for r in receipts.reasons)


# ── 3. Grid import/export and revenue reconciliation ────────────────────────


class TestNativeReconciliation:
    def test_explicit_statement_reconciles_with_native_hours(self, released, native):
        hours = day(native, 0)
        st = charging_statement(explicit(hours))
        assert reconcile_with_native_hours(st, hours) is st
        assert st.grid_import_mwh == D("1.24") and st.grid_export_mwh == D("0.81")

    def test_tampered_grid_quantity_or_receipt_fails_closed(self, released, native):
        hours = day(native, 0)
        period = explicit(hours)
        tampered_q = ChargingPeriod(period.period_id, period.basis, period.evidence_id, period.legs, None, None,
                                    period.grid_import_mwh + D("0.001"), period.grid_export_mwh)
        with pytest.raises(BessCommercialError, match="grid_import_mwh differs"):
            reconcile_with_native_hours(charging_statement(tampered_q), hours)
        bumped = tuple(ReceiptLeg(l.kind, l.receipt_id, l.amount_keur + D("0.000001")
                                  if l.kind is LegKind.GROSS_SALE else l.amount_keur) for l in period.legs)
        tampered_r = ChargingPeriod(period.period_id, period.basis, period.evidence_id, bumped, None, None,
                                    period.grid_import_mwh, period.grid_export_mwh)
        with pytest.raises(BessCommercialError, match="GROSS_SALE differs"):
            reconcile_with_native_hours(charging_statement(tampered_r), hours)

    def test_reconciling_against_the_wrong_hours_fails(self, released, native):
        st = charging_statement(explicit(day(native, 0)))
        with pytest.raises(BessCommercialError, match="RECONCILIATION"):
            reconcile_with_native_hours(st, day(native, 0)[:12])

    def test_net_spread_delivered_mwh_reconciles_with_native_ac_discharge(self, released, native):
        hours = day(native, 0)
        ok = charging_statement(native_net_spread_period("P1", "ev-s", D(40), hours))
        assert reconcile_with_native_hours(ok, hours) is ok
        wrong = charging_statement(spread(mwh=D("1.00")))
        with pytest.raises(BessCommercialError, match="delivered MWh differs"):
            reconcile_with_native_hours(wrong, hours)

    def test_unavailable_statement_cannot_be_reconciled(self, released, native):
        with pytest.raises(BessCommercialError, match="only a CANDIDATE"):
            reconcile_with_native_hours(charging_statement(spread(price=None)), day(native, 0))


# ── 4. Zero vs missing evidence ─────────────────────────────────────────────


class TestZeroVersusMissing:
    def test_missing_spread_is_unavailable_but_zero_is_a_legitimate_candidate(self, released):
        missing = charging_statement(spread(price=None))
        zero = charging_statement(spread(price=D(0)))
        assert missing.status == "UNAVAILABLE" and missing.net_contribution_keur is None
        assert zero.status == "CANDIDATE" and zero.net_contribution_keur == 0

    def test_missing_delivered_energy_is_unavailable_but_zero_is_not(self, released):
        assert charging_statement(spread(mwh=None)).status == "UNAVAILABLE"
        assert charging_statement(spread(mwh=D(0))).net_contribution_keur == 0

    def test_a_missing_receipt_leg_is_unavailable_and_an_explicit_zero_is_a_zero(self, released):
        some_missing = tuple(ReceiptLeg(l.kind, l.receipt_id, None if l.kind is LegKind.GRID_IMPORT_CHARGE else l.amount_keur)
                             for l in legs())
        st = charging_statement(ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", some_missing, None, None, D(1), D(1)))
        assert st.status == "UNAVAILABLE" and "GRID_IMPORT_CHARGE" in st.reason
        zeros = tuple(ReceiptLeg(l.kind, l.receipt_id, D(0)) for l in legs())
        st0 = charging_statement(ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", zeros, None, None, D(0), D(0)))
        assert st0.status == "CANDIDATE" and st0.net_contribution_keur == 0

    def test_missing_grid_quantities_are_unavailable(self, released):
        st = charging_statement(ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", legs(), None, None, None, D(1)))
        assert st.status == "UNAVAILABLE" and "grid_import_mwh" in st.reason

    @pytest.mark.parametrize("bad", [1.5, 1, "1", True, D("NaN"), D("Infinity")])
    def test_only_finite_decimals_are_accepted(self, released, bad):
        with pytest.raises(BessCommercialError, match="finite Decimal"):
            spread(price=bad)

    def test_serialization_keeps_missing_distinct_from_zero(self, released):
        assert canonical_json(charging_statement(spread(price=None))) != canonical_json(charging_statement(spread(price=D(0))))
        assert '"net_contribution_keur":null' in canonical_json(charging_statement(spread(price=None)))


# ── 5./6. Contracted / merchant classification, unsecured as its own category ─


def rline(i, cls, amount, period="P1", service=Service.MERCHANT_ENERGY, ref="c-1"):
    contracted = cls is not RevenueClass.MERCHANT
    return RevenueLine(f"L{i}", period, service, cls, amount, f"claim-{i}", ref if contracted else None)


class TestRevenueClassification:
    def test_contract_reference_rules(self, released):
        with pytest.raises(BessCommercialError, match="requires a contract_ref"):
            RevenueLine("L1", "P1", Service.CAPACITY_RESERVATION, RevenueClass.CONTRACTED, D(1), "c1")
        with pytest.raises(BessCommercialError, match="requires a contract_ref"):
            RevenueLine("L1", "P1", Service.CAPACITY_RESERVATION, RevenueClass.CONTRACTED_UNSECURED, D(1), "c1")
        with pytest.raises(BessCommercialError, match="cannot carry a contract_ref"):
            RevenueLine("L1", "P1", Service.MERCHANT_ENERGY, RevenueClass.MERCHANT, D(1), "c1", "c-1")

    def test_classification_must_be_a_typed_member(self, released):
        with pytest.raises(BessCommercialError, match="UNSUPPORTED"):
            RevenueLine("L1", "P1", Service.MERCHANT_ENERGY, "MERCHANT", D(1), "c1")

    def test_the_three_classes_are_presented_separately_and_never_netted(self, released):
        lines = (rline(1, RevenueClass.CONTRACTED, D(10)), rline(2, RevenueClass.CONTRACTED_UNSECURED, D(4)),
                 rline(3, RevenueClass.MERCHANT, D(6)))
        view = present_for_lender(lines).periods[0]
        assert (view.contracted.amount_keur, view.contracted_unsecured.amount_keur, view.merchant.amount_keur) == (10, 4, 6)
        assert not any(hasattr(view, name) for name in ("total_keur", "combined_keur", "net_keur"))

    def test_lender_treatment_is_open_for_every_class(self, released):
        presentation = present_for_lender((rline(1, RevenueClass.MERCHANT, D(1)),))
        assert {t.classification for t in presentation.treatment} == set(RevenueClass)
        assert all(t.dscr_eligibility is Decision.OPEN and t.haircut is Decision.OPEN
                   and t.netted_with_other_classes is False for t in presentation.treatment)
        assert not (presentation.released_cfads_engine_modified or presentation.released_debt_sizing_modified
                    or presentation.released_dscr_engine_modified)

    def test_unsecured_stays_its_own_category_with_missing_vs_zero_distinct(self, released):
        lines = (rline(1, RevenueClass.CONTRACTED_UNSECURED, None), rline(2, RevenueClass.MERCHANT, D(0)),
                 rline(3, RevenueClass.CONTRACTED, D(5)))
        view = present_for_lender(lines).periods[0]
        assert view.contracted_unsecured.amount_keur is None and view.contracted_unsecured.unavailable_line_ids == ("L1",)
        assert view.merchant.amount_keur == 0 and view.merchant.line_count == 1     # reported zero
        assert view.contracted.amount_keur == 5
        none_declared = present_for_lender((rline(4, RevenueClass.MERCHANT, D(2)),)).periods[0]
        assert none_declared.contracted.line_count == 0                                # nothing declared

    def test_lines_and_claims_must_be_unique(self, released):
        a = rline(1, RevenueClass.MERCHANT, D(1))
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT"):
            present_for_lender((a, a))
        b = RevenueLine("L9", "P1", Service.MERCHANT_ENERGY, RevenueClass.MERCHANT, D(1), a.claim_id)
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*claim_id"):
            present_for_lender((a, b))

    def test_stacked_services_stay_separate(self, released):
        lines = (rline(1, RevenueClass.CONTRACTED, D(3), service=Service.CAPACITY_RESERVATION),
                 rline(2, RevenueClass.MERCHANT, D(2), service=Service.MERCHANT_ENERGY),
                 rline(3, RevenueClass.CONTRACTED, D(1), service=Service.CAPACITY_RESERVATION))
        stacked = stack_by_service(lines)
        assert stacked[("P1", "CAPACITY_RESERVATION", "CONTRACTED")] == 4
        assert stacked[("P1", "MERCHANT_ENERGY", "MERCHANT")] == 2 and len(stacked) == 2


# ── 7. Tolling availability / penalty edge cases ────────────────────────────


def toll(**kw):
    base = dict(contract_id="toll-1", contracted_capacity_mw=D(10), availability_fee_eur_mw_year=D(50000),
                start=date(2028, 1, 1), end=date(2029, 1, 1), guaranteed_availability=D("0.98"),
                energy_ownership=Party.OFFTAKER, dispatch_responsibility=Party.OFFTAKER, evidence_ref="doc-1")
    base.update(kw)
    return TollingContract(**base)


def period(start=date(2028, 4, 1), end=date(2028, 5, 1), avail=D("0.99"), deductions=(), pid="Q"):
    return TollingPeriod(pid, start, end, avail, deductions)


def close(a, b, tol="1e-20"):
    return abs(a - b) < D(tol)


class TestTolling:
    def test_scheduled_availability_fee_act_365(self, released):
        st = tolling_statement(toll(), period())     # 30 days
        assert st.status == "CANDIDATE" and st.in_term_days == 30
        assert close(st.scheduled_fee_keur, D(10 * 50000 * 30) / D(365000))
        assert st.availability_shortfall == 0 and st.net_fee_keur == st.scheduled_fee_keur

    def test_contract_starting_mid_period_is_prorated_by_overlap_days(self, released):
        st = tolling_statement(toll(start=date(2028, 3, 20)), period(date(2028, 3, 1), date(2028, 4, 1)))
        assert st.in_term_days == 12 and st.period_days == 31
        assert close(st.scheduled_fee_keur, D(10 * 50000 * 12) / D(365000))

    def test_contract_ending_mid_period_is_prorated(self, released):
        st = tolling_statement(toll(end=date(2028, 3, 15)), period(date(2028, 3, 1), date(2028, 4, 1)))
        assert st.in_term_days == 14

    def test_period_outside_the_term_is_not_applicable_not_zero(self, released):
        st = tolling_statement(toll(), period(date(2027, 1, 1), date(2027, 2, 1)))
        assert st.status == "NOT_APPLICABLE" and st.scheduled_fee_keur is None and st.net_fee_keur is None

    def test_missing_availability_is_unavailable_but_measured_zero_is_valid(self, released):
        assert tolling_statement(toll(), period(avail=None)).status == "UNAVAILABLE"
        zero = tolling_statement(toll(), period(avail=D(0)))
        assert zero.status == "CANDIDATE" and zero.availability_shortfall == D("0.98")

    def test_a_zero_fee_rate_is_a_legitimate_zero_fee(self, released):
        st = tolling_statement(toll(availability_fee_eur_mw_year=D(0)), period())
        assert st.status == "CANDIDATE" and st.scheduled_fee_keur == 0

    def test_declared_deduction_is_subtracted_without_any_penalty_formula(self, released):
        d = PerformanceDeduction("d1", "Q", D("5"), "ops-report-7")
        st = tolling_statement(toll(), period(avail=D("0.90"), deductions=(d,)))
        assert st.availability_shortfall == D("0.08") and st.declared_deductions_keur == 5
        assert close(st.net_fee_keur, st.scheduled_fee_keur - 5)     # test-side subtraction runs at default precision

    def test_deduction_edge_cases_fail_closed(self, released):
        d = lambda amount="1", pid="Q", did="d1": PerformanceDeduction(did, pid, D(amount), "ref")
        with pytest.raises(BessCommercialError, match="meets the guarantee"):
            tolling_statement(toll(), period(avail=D("0.99"), deductions=(d(),)))
        with pytest.raises(BessCommercialError, match="needs a declared guaranteed"):
            tolling_statement(toll(guaranteed_availability=None), period(avail=D("0.5"), deductions=(d(),)))
        with pytest.raises(BessCommercialError, match="exceed the scheduled fee"):
            tolling_statement(toll(), period(avail=D("0.5"), deductions=(d("100000"),)))
        with pytest.raises(BessCommercialError, match="another period"):
            tolling_statement(toll(), period(avail=D("0.5"), deductions=(d(pid="X"),)))
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT"):
            period(avail=D("0.5"), deductions=(d(), d()))
        with pytest.raises(BessCommercialError, match="outside the contract term"):
            tolling_statement(toll(), period(date(2027, 1, 1), date(2027, 2, 1), deductions=(d(),)))

    def test_contracted_capacity_cannot_exceed_rated_power(self, released):
        with pytest.raises(BessCommercialError, match="exceeds the rated"):
            tolling_statement(toll(contracted_capacity_mw=D(11)), period(), rated_discharge_mw=D(10))
        assert tolling_statement(toll(), period(), rated_discharge_mw=D(10)).status == "CANDIDATE"

    def test_unsupported_day_count_and_bad_dates_are_rejected(self, released):
        with pytest.raises(BessCommercialError, match="day_count"):
            toll(day_count="ACT_360")
        with pytest.raises(BessCommercialError, match="end must be after start"):
            toll(end=date(2028, 1, 1))
        with pytest.raises(BessCommercialError, match="availability"):
            toll(guaranteed_availability=D("1.01"))

    def test_ownership_and_responsibility_must_be_declared_parties(self, released):
        with pytest.raises(BessCommercialError, match="UNSUPPORTED"):
            toll(energy_ownership="OFFTAKER")
        c = toll(energy_ownership=Party.PROJECT, dispatch_responsibility=Party.OFFTAKER)
        assert c.energy_ownership is Party.PROJECT and c.dispatch_responsibility is Party.OFFTAKER

    def test_allocation_decisions_can_only_be_recorded_as_open(self, released):
        assert all(v is Decision.OPEN for v in vars(toll().open_decisions).values())
        for name in ("merchant_upside_allocation", "availability_penalty_formula", "charging_cost_bearer",
                     "degradation_risk_bearer"):
            for value in ("OPEN", "OFFTAKER", None, True):
                with pytest.raises(BessCommercialError, match="OWNER_DECISION"):
                    TollingOpenDecisions(**{name: value})

    def test_tolling_places_a_capacity_reservation_not_an_energy_claim(self, released):
        claim = reservation_for_tolling(toll(), "res-1", datetime(2028, 1, 1, tzinfo=UTC), datetime(2028, 1, 2, tzinfo=UTC))
        assert claim.service is Service.CAPACITY_RESERVATION and claim.reserved_mw == 10 and claim.obligation_ref == "toll-1"
        with pytest.raises(BessCommercialError, match="outside the tolling term"):
            reservation_for_tolling(toll(), "res-2", datetime(2027, 12, 31, tzinfo=UTC), datetime(2028, 1, 2, tzinfo=UTC))


# ── 8./9. Dispatch allocation, capacity vs throughput ───────────────────────

H20 = datetime(2028, 1, 1, 20, tzinfo=UTC)     # native: AC discharge 0.81 MWh
H02 = datetime(2028, 1, 1, 2, tzinfo=UTC)      # native: AC charge 1.0 MWh


def eclaim(i, mwh, hour=H20, service=Service.MERCHANT_ENERGY, direction=Direction.DISCHARGE_AC):
    return EnergyClaim(f"e{i}", service, hour, direction, D(mwh))


def run(native, energy=(), reservations=(), n=2, **kw):
    return allocate(tuple(energy), tuple(reservations), native.hours[:24 * n],
                    rated_discharge_mw=kw.get("rd", D(1)), rated_charge_mw=kw.get("rc", D(1)))


class TestDispatchAllocation:
    def test_partial_claims_reconcile_and_report_the_unallocated_remainder(self, released, native):
        result = run(native, [eclaim(1, "0.5")])
        assert result.claimed_mwh == D("0.5") and not result.fully_allocated
        assert result.unallocated_mwh == total(native.hours[:48], "ac_discharge_mwh") + total(native.hours[:48], "ac_charge_mwh") - D("0.5")

    def test_two_services_may_split_one_hour_but_never_exceed_it(self, released, native):
        split = run(native, [eclaim(1, "0.30", service=Service.ENERGY_THROUGHPUT), eclaim(2, "0.51")])
        row = next(r for r in split.rows if r.hour == H20)
        assert row.claimed_mwh == D("0.81") and row.unallocated_mwh == 0

    def test_the_same_mwh_claimed_twice_fails_closed(self, released, native):
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*same MWh is claimed twice"):
            run(native, [eclaim(1, "0.81"), eclaim(2, "0.01", service=Service.ENERGY_THROUGHPUT)])
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT"):
            run(native, [eclaim(1, "0.81"), eclaim(2, "0.81", service=Service.ENERGY_THROUGHPUT)])

    def test_claim_identities_must_be_unique(self, released, native):
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*claim_id"):
            run(native, [eclaim(1, "0.1"), eclaim(1, "0.1")])

    def test_claims_need_native_energy_in_that_hour_and_direction(self, released, native):
        with pytest.raises(BessCommercialError, match="none in the native evidence"):
            run(native, [eclaim(1, "0.1", hour=datetime(2028, 1, 1, 3, tzinfo=UTC))])
        with pytest.raises(BessCommercialError, match="none in the native evidence"):
            run(native, [eclaim(1, "0.1", hour=H02)])     # charge hour has no AC discharge
        with pytest.raises(BessCommercialError, match="outside the native dispatch evidence"):
            run(native, [eclaim(1, "0.1", hour=datetime(2030, 1, 1, 20, tzinfo=UTC))])

    def test_charge_energy_is_a_separate_direction(self, released, native):
        result = run(native, [eclaim(1, "1.0", hour=H02, direction=Direction.CHARGE_AC)])
        assert next(r for r in result.rows if r.hour == H02).unallocated_mwh == 0

    def test_native_evidence_is_required_and_unique(self, released, native):
        with pytest.raises(BessCommercialError, match="native hourly evidence required"):
            allocate((), (), (), rated_discharge_mw=D(1), rated_charge_mw=D(1))
        with pytest.raises(BessCommercialError, match="duplicate native hour"):
            allocate((), (), native.hours[:2] + native.hours[:1], rated_discharge_mw=D(1), rated_charge_mw=D(1))


class TestCapacityVersusThroughput:
    def res(self, i, start=H20, end=H20 + timedelta(hours=2), mw="0.4", service=Service.CAPACITY_RESERVATION,
            direction=Direction.DISCHARGE_AC):
        return ReservationClaim(f"r{i}", service, start, end, direction, D(mw))

    def test_a_capacity_reservation_consumes_no_physical_throughput(self, released, native):
        baseline = run(native, [eclaim(1, "0.5")])
        with_reservation = run(native, [eclaim(1, "0.5")], [self.res(1)])
        assert with_reservation.claimed_mwh == baseline.claimed_mwh
        assert with_reservation.unallocated_mwh == baseline.unallocated_mwh
        row = next(r for r in with_reservation.rows if r.hour == H20 and r.direction is Direction.DISCHARGE_AC)
        assert row.reserved_mw == D("0.4") and row.headroom_mw == D("0.6")

    def test_service_types_are_kept_apart(self, released):
        with pytest.raises(BessCommercialError, match="not an energy-consuming service"):
            eclaim(1, "0.1", service=Service.CAPACITY_RESERVATION)
        with pytest.raises(BessCommercialError, match="energy service"):
            self.res(1, service=Service.MERCHANT_ENERGY)
        with pytest.raises(BessCommercialError, match="energy service"):
            self.res(1, service=Service.ENERGY_THROUGHPUT)

    def test_reservations_cannot_exceed_rated_power(self, released, native):
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT.*rated"):
            run(native, reservations=[self.res(1, mw="0.6"), self.res(2, mw="0.6", service=Service.ANCILLARY_AVAILABILITY)])
        ok = run(native, reservations=[self.res(1, mw="0.6"), self.res(2, mw="0.4", service=Service.ANCILLARY_AVAILABILITY)])
        assert ok.status == "CANDIDATE"

    def test_reservation_must_lie_inside_native_evidence_and_available_hours(self, released):
        raw = example()
        raw["outages"] = [{"start": "2028-01-01T10:00:00Z", "end": "2028-01-01T12:00:00Z", "source_ref": "outage-1"}]
        with_outage = evaluate(parse_configuration(json.dumps(raw)))
        down = datetime(2028, 1, 1, 10, tzinfo=UTC)
        with pytest.raises(BessCommercialError, match="unavailable hour"):
            allocate((), (self.res(1, start=down, end=down + timedelta(hours=1)),), with_outage.hours,
                     rated_discharge_mw=D(1), rated_charge_mw=D(1))
        with pytest.raises(BessCommercialError, match="outside the native evidence"):
            allocate((), (self.res(1, start=H20, end=datetime(2030, 1, 1, tzinfo=UTC)),), with_outage.hours,
                     rated_discharge_mw=D(1), rated_charge_mw=D(1))

    def test_revenue_lines_link_one_to_one_to_claims_of_the_same_service(self, released):
        energy = eclaim(1, "0.5")
        reservation = self.res(2)
        good = (RevenueLine("L1", "P1", Service.MERCHANT_ENERGY, RevenueClass.MERCHANT, D(1), "e1"),
                RevenueLine("L2", "P1", Service.CAPACITY_RESERVATION, RevenueClass.CONTRACTED, D(2), "r2", "c-1"))
        link_to_allocation(good, (energy, reservation))
        wrong_service = RevenueLine("L3", "P1", Service.ENERGY_THROUGHPUT, RevenueClass.MERCHANT, D(1), "e1")
        with pytest.raises(BessCommercialError, match="service"):
            link_to_allocation((wrong_service,), (energy,))
        with pytest.raises(BessCommercialError, match="unknown claim"):
            link_to_allocation((good[0],), (reservation,))
        twice = (good[0], RevenueLine("L4", "P1", Service.MERCHANT_ENERGY, RevenueClass.MERCHANT, D(1), "e1"))
        with pytest.raises(BessCommercialError, match="DOUBLE_COUNT"):
            link_to_allocation(twice, (energy,))


# ── 10. Augmentation commercial policy ──────────────────────────────────────


def policy(trigger, **kw):
    return AugmentationCommercialPolicy("aug-1", trigger, **kw)


class TestAugmentation:
    def test_trigger_inputs_are_exclusive_to_their_trigger(self, released):
        with pytest.raises(BessCommercialError, match="requires soh_threshold"):
            policy(AugmentationTrigger.SOH_THRESHOLD)
        with pytest.raises(BessCommercialError, match="must not carry planned_at"):
            policy(AugmentationTrigger.SOH_THRESHOLD, soh_threshold=D("0.7"), planned_at=datetime(2028, 1, 2, tzinfo=UTC))
        with pytest.raises(BessCommercialError, match="requires warranty_ref"):
            policy(AugmentationTrigger.WARRANTY_TRIGGERED, warranty_soh_floor=D("0.7"))
        with pytest.raises(BessCommercialError, match="requires planned_at"):
            policy(AugmentationTrigger.PLANNED_EVENT)

    def test_soh_threshold_reads_native_state_of_health(self, released, native):
        target = native.hours[30].soh_closing
        found = evaluate_trigger(policy(AugmentationTrigger.SOH_THRESHOLD, soh_threshold=target), native.hours, D("0.6"))
        oracle = next(h for h in native.hours if h.soh_closing <= target)
        assert found.triggered is True and found.at == oracle.end and found.observed_soh == oracle.soh_closing
        none = evaluate_trigger(policy(AugmentationTrigger.SOH_THRESHOLD, soh_threshold=D("0.61")), native.hours, D("0.6"))
        assert none.triggered is False and none.at is None and none.minimum_observed_soh == native.hours[-1].soh_closing

    def test_a_threshold_at_or_below_the_native_minimum_is_rejected(self, released, native):
        for level in (D("0.6"), D("0.5")):
            with pytest.raises(BessCommercialError, match="native minimum SoH"):
                evaluate_trigger(policy(AugmentationTrigger.SOH_THRESHOLD, soh_threshold=level), native.hours, D("0.6"))

    def test_warranty_trigger_does_not_resolve_the_remedy(self, released, native):
        p = policy(AugmentationTrigger.WARRANTY_TRIGGERED, warranty_ref="w-1", warranty_soh_floor=native.hours[10].soh_closing)
        got = evaluate_trigger(p, native.hours, D("0.6"))
        assert got.triggered is True and "OPEN" in got.reason and p.warranty_remedy is Decision.OPEN

    def test_planned_event_inside_and_outside_the_native_horizon(self, released, native):
        inside = evaluate_trigger(policy(AugmentationTrigger.PLANNED_EVENT, planned_at=datetime(2028, 1, 2, 0, tzinfo=UTC)),
                                  native.hours, D("0.6"))
        assert inside.status == "CANDIDATE" and inside.triggered is True
        outside = evaluate_trigger(policy(AugmentationTrigger.PLANNED_EVENT, planned_at=datetime(2030, 1, 1, tzinfo=UTC)),
                                   native.hours, D("0.6"))
        assert outside.status == "UNAVAILABLE" and outside.triggered is None

    def test_replacement_capex_proposal_missing_vs_zero(self, released, native):
        base = dict(trigger=AugmentationTrigger.PLANNED_EVENT, planned_at=datetime(2028, 1, 2, tzinfo=UTC))
        missing = evaluate_trigger(policy(**base), native.hours, D("0.6"))
        zero = evaluate_trigger(policy(**base, replacement_capex_proposal_keur=D(0), proposal_ref="q-1"), native.hours, D("0.6"))
        assert missing.proposal_status == "UNAVAILABLE" and missing.replacement_capex_proposal_keur is None
        assert zero.proposal_status == "CANDIDATE" and zero.replacement_capex_proposal_keur == 0
        with pytest.raises(BessCommercialError, match="come together"):
            policy(**base, replacement_capex_proposal_keur=D(1))

    def test_funding_residual_and_capex_class_can_only_be_open(self, released):
        base = dict(trigger=AugmentationTrigger.PLANNED_EVENT, planned_at=datetime(2028, 1, 2, tzinfo=UTC))
        p = policy(**base)
        assert (p.funding_treatment, p.residual_value_treatment, p.capex_classification) == (Decision.OPEN,) * 3
        for name in ("funding_treatment", "residual_value_treatment", "capex_classification", "warranty_remedy"):
            with pytest.raises(BessCommercialError, match="OWNER_DECISION"):
                policy(**base, **{name: "CAPITALISED"})

    def test_financial_posting_is_closed_in_every_state(self, released, monkeypatch):
        base = dict(trigger=AugmentationTrigger.PLANNED_EVENT, planned_at=datetime(2028, 1, 2, tzinfo=UTC))
        with pytest.raises(BessCommercialError, match="POSTING_RELEASE_CLOSED"):
            policy(**base, financial_posting="POSTED")
        with pytest.raises(BessCommercialError, match="AUGMENTATION_POSTING_RELEASE_CLOSED"):
            augmentation_financial_posting(policy(**base))
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", False)
        with pytest.raises(BessCommercialError, match="AUGMENTATION_POSTING_RELEASE_CLOSED"):
            augmentation_financial_posting()

    def test_native_post_cod_posting_stays_release_closed(self):
        source = (ROOT / "financial_engine" / "bess.py").read_text(encoding="utf-8")
        assert "BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED" in source and "if config.events:" in source

    def test_alignment_with_native_configuration_events(self, released):
        raw = example()
        raw["events"] = [{"at": "2028-01-02T00:00:00Z", "kind": "AUGMENT", "installed_energy_mwh": 1, "usable_energy_mwh": .8,
                          "cost_keur": 150, "useful_life_years": 5, "source_ref": "native-event-1", "tax_book_policy": "UNRESOLVED"}]
        events = parse_configuration(json.dumps(raw)).events
        at = datetime(2028, 1, 2, tzinfo=UTC)
        match = policy(AugmentationTrigger.PLANNED_EVENT, planned_at=at, replacement_capex_proposal_keur=D(150), proposal_ref="q")
        assert native_event_alignment(match, events).aligned is True
        diff = policy(AugmentationTrigger.PLANNED_EVENT, planned_at=at, replacement_capex_proposal_keur=D(151), proposal_ref="q")
        assert native_event_alignment(diff, events).mismatches == ("proposal differs from the native event cost",)
        other = policy(AugmentationTrigger.PLANNED_EVENT, planned_at=at + timedelta(hours=5))
        assert native_event_alignment(other, events).aligned is False
        with pytest.raises(BessCommercialError, match="only a PLANNED_EVENT"):
            native_event_alignment(policy(AugmentationTrigger.SOH_THRESHOLD, soh_threshold=D("0.7")), events)


# ── LCOS receipt boundary (specification only) ──────────────────────────────


class TestLcosReceiptBoundary:
    def receipts(self, native, **kw):
        hours = day(native, 0)
        args = dict(operating_cost_keur=D("0.5"), operating_cost_ref="opex-1", methodology_ref="m-1")
        args.update(kw)
        return build_lcos_receipts(charging_statement(explicit(hours)), hours, **args)

    def test_complete_receipts_are_a_candidate_specification_without_lcos_arithmetic(self, released, native):
        r = self.receipts(native)
        assert r.status == "CANDIDATE" and r.reasons == () and r.lcos_arithmetic_performed is False
        hours = day(native, 0)
        assert r.delivered_ac_discharge_mwh == total(hours, "ac_discharge_mwh") == D("0.81")
        assert r.gross_charging_purchase_keur == total(hours, "charging_purchase_cost_keur")
        assert r.auxiliary_purchase_keur == total(hours, "auxiliary_purchase_cost_keur")
        assert r.grid_fee_receipts_keur == total(hours, "grid_import_charge_keur") + total(hours, "grid_export_charge_keur")
        assert r.augmentation_investment_keur is None and "opex-1" in r.evidence_ids

    @pytest.mark.parametrize("kw,fragment", [
        ({"operating_cost_keur": None, "operating_cost_ref": None}, "operating-cost receipt missing"),
        ({"methodology_ref": None}, "methodology"),
    ])
    def test_missing_receipt_or_methodology_is_unavailable(self, released, native, kw, fragment):
        r = self.receipts(native, **kw)
        assert r.status == "UNAVAILABLE" and any(fragment in reason for reason in r.reasons)

    def test_zero_operating_cost_is_a_reported_zero_and_augmentation_is_optional(self, released, native):
        r = self.receipts(native, operating_cost_keur=D(0), augmentation_investment_keur=D(150), augmentation_receipt_ref="aug-r")
        assert r.status == "CANDIDATE" and r.operating_cost_keur == 0 and r.augmentation_investment_keur == 150
        assert "aug-r" in r.evidence_ids

    def test_receipt_and_reference_must_come_together(self, released, native):
        with pytest.raises(BessCommercialError, match="come together"):
            self.receipts(native, operating_cost_ref=None)
        with pytest.raises(BessCommercialError, match="come together"):
            self.receipts(native, augmentation_investment_keur=D(1))

    def test_discharge_must_reconcile_with_the_statements_grid_export(self, released, native):
        with pytest.raises(BessCommercialError, match="RECONCILIATION"):
            build_lcos_receipts(charging_statement(explicit(day(native, 0))), day(native, 1)[:12],
                                operating_cost_keur=D(1), operating_cost_ref="o", methodology_ref="m")

    def test_wf09a_is_not_imported_or_duplicated(self):
        source = (ROOT / "app" / "bess_commercial_candidate" / "lcos.py").read_text(encoding="utf-8")
        assert "wf09a" not in source.replace("PR #362 (``research/wf09a``)", "").replace("research/wf09a", "")
        assert "import" not in [n for n in ast.parse(source).body if isinstance(n, ast.Import)] and not any(
            isinstance(n, (ast.Import, ast.ImportFrom)) and "research" in ast.dump(n) for n in ast.walk(ast.parse(source)))


# ── 11. Multi-period and partial-COD ────────────────────────────────────────


class TestMultiPeriodAndPartialCod:
    def test_daily_periods_sum_to_the_native_total_and_statements_stay_separate(self, released, native):
        periods = (explicit(day(native, 0), "D1", "ev-d1"), explicit(day(native, 1), "D2", "ev-d2"))
        statements = charging_book(periods)
        assert sum((s.net_contribution_keur for s in statements), D(0)) == native.net_merchant_contribution_keur
        for s, n in zip(statements, (0, 1)):
            reconcile_with_native_hours(s, day(native, n))

    def test_period_straddling_cod_covers_only_the_operating_hours(self, released, native):
        # operating starts mid-period: the first period holds only the post-COD hours (12 of 24)
        post_cod = day(native, 0)[12:]
        st = charging_statement(explicit(post_cod, "D1", "ev-cod"))
        reconcile_with_native_hours(st, post_cod)
        assert st.grid_export_mwh == D("0.81") and st.net_contribution_keur == total(post_cod, "net_merchant_contribution_keur")
        with pytest.raises(BessCommercialError, match="RECONCILIATION"):
            reconcile_with_native_hours(st, day(native, 0))      # the pre-COD hours are not part of this statement

    def test_tolling_across_a_partial_cod_period_and_a_full_period(self, released):
        c = toll(start=date(2028, 3, 20))
        first = tolling_statement(c, period(date(2028, 3, 1), date(2028, 4, 1), pid="Q1"))
        second = tolling_statement(c, period(date(2028, 4, 1), date(2028, 5, 1), pid="Q2"))
        assert (first.in_term_days, second.in_term_days) == (12, 30)
        assert first.scheduled_fee_keur < second.scheduled_fee_keur

    def test_lender_view_has_one_row_per_period_in_order(self, released):
        lines = (rline(1, RevenueClass.MERCHANT, D(1), period="P2"), rline(2, RevenueClass.MERCHANT, D(2), period="P1"))
        assert [p.period_id for p in present_for_lender(lines).periods] == ["P1", "P2"]


# ── 12. Deterministic output and provenance identity ────────────────────────


class TestDeterminismAndProvenance:
    def test_identical_inputs_serialize_and_identify_identically(self, released, native):
        a, b = charging_statement(explicit(day(native, 0))), charging_statement(explicit(day(native, 0)))
        assert canonical_json(a) == canonical_json(b) and identity(a) == identity(b)
        assert len(identity(a)) == 64

    def test_equal_decimals_with_different_scale_share_one_identity(self, released):
        assert identity(charging_statement(spread(price=D("40.0")))) == identity(charging_statement(spread(price=D("40"))))

    def test_changing_provenance_changes_identity(self, released):
        assert identity(charging_statement(spread(evid="ev-1"))) != identity(charging_statement(spread(evid="ev-2")))

    def test_results_do_not_depend_on_the_callers_decimal_context(self, released, native):
        c, p, ch = toll(), period(), explicit(day(native, 0))      # inputs are built at default precision
        with localcontext() as ctx:
            ctx.prec, ctx.rounding = 3, ROUND_UP
            low = (tolling_statement(c, p), charging_statement(ch))
        with localcontext() as ctx:
            ctx.prec = 60
            high = (tolling_statement(c, p), charging_statement(ch))
        assert low == high and identity(low[0]) == identity(high[0])

    def test_canonical_envelope_carries_schema_and_activation_marker(self, released):
        payload = json.loads(canonical_json(charging_statement(spread())))
        assert payload["_schema"] == "finco.bess-commercial-candidate" and payload["schema_version"] == 1
        assert payload["activation"] == "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"

    def test_closed_gate_marks_the_payload_release_closed(self, monkeypatch):
        assert json.loads(canonical_json(spread()))["activation"] == "RELEASE_CLOSED"

    def test_contracts_are_immutable(self, released):
        with pytest.raises(Exception):
            spread().period_id = "x"
        with pytest.raises(BessCommercialError, match="immutable tuple"):
            ChargingPeriod("P1", ChargingBasis.EXPLICIT_BUY_LEG, "e", list(legs()), None, None, D(1), D(1))


# ── 13. Release closure and production isolation ────────────────────────────


class TestReleaseClosureAndIsolation:
    def test_the_gate_is_a_literal_false_in_source(self):
        tree = ast.parse((ROOT / "app" / "bess_commercial_candidate" / "contracts.py").read_text(encoding="utf-8"))
        assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ACTIVATION_ENABLED" for t in n.targets)]
        assert len(assigns) == 1 and isinstance(assigns[0].value, ast.Constant) and assigns[0].value.value is False
        assert contracts.ACTIVATION_ENABLED is False

    def test_every_gated_entry_point_fails_closed_by_default(self, monkeypatch, native):
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)
        hours = day(native, 0)
        st = charging_statement(explicit(hours))
        res = ReservationClaim("r", Service.CAPACITY_RESERVATION, H20, H20 + timedelta(hours=1), Direction.DISCHARGE_AC, D(1))
        line = rline(1, RevenueClass.MERCHANT, D(1))
        p = policy(AugmentationTrigger.PLANNED_EVENT, planned_at=datetime(2028, 1, 2, tzinfo=UTC))
        calls = {
            "charging_statement": lambda: charging_statement(spread()),
            "charging_book": lambda: charging_book((spread(),)),
            "native_charging_period": lambda: native_charging_period(proposal(hours), "P", "e"),
            "native_net_spread_period": lambda: native_net_spread_period("P", "e", D(1), hours),
            "reconcile_with_native_hours": lambda: reconcile_with_native_hours(st, hours),
            "present_for_lender": lambda: present_for_lender((line,)),
            "stack_by_service": lambda: stack_by_service((line,)),
            "link_to_allocation": lambda: link_to_allocation((line,), (EnergyClaim("claim-1", Service.MERCHANT_ENERGY, H20,
                                                                                   Direction.DISCHARGE_AC, D("0.1")),)),
            "allocate": lambda: allocate((), (res,), hours, rated_discharge_mw=D(1), rated_charge_mw=D(1)),
            "tolling_statement": lambda: tolling_statement(toll(), period()),
            "reservation_for_tolling": lambda: reservation_for_tolling(toll(), "r", datetime(2028, 1, 1, tzinfo=UTC),
                                                                       datetime(2028, 1, 2, tzinfo=UTC)),
            "evaluate_trigger": lambda: evaluate_trigger(p, hours, D("0.6")),
            "native_event_alignment": lambda: native_event_alignment(p, ()),
            "build_lcos_receipts": lambda: build_lcos_receipts(st, hours, operating_cost_keur=None, operating_cost_ref=None,
                                                               methodology_ref=None),
        }
        for name, call in calls.items():
            call()      # works while the isolated fixture has opened the gate
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", False)
        for name, call in calls.items():
            with pytest.raises(BessCommercialError, match="BESS_COMMERCIAL_RELEASE_CLOSED"):
                call()

    def test_no_environment_variable_can_enable_the_package(self, monkeypatch):
        for name in ("ACTIVATION_ENABLED", "FINCO_BESS_COMMERCIAL", "BESS_COMMERCIAL_ENABLED", "FINCO_ACTIVATE_BESS_COMMERCIAL"):
            monkeypatch.setenv(name, "1")
        out = subprocess.run([sys.executable, "-c", "import app.bess_commercial_candidate.contracts as c;print(c.ACTIVATION_ENABLED)"],
                             cwd=ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == "False"

    def test_no_production_module_references_the_candidate(self):
        bad = []
        for root in ("app", "domain", "financial_engine", "finco_core", "finco_radar", "finco_protocol", "main_web.py",
                     "main_api.py", "main_mcp.py", "static", "tools", ".github", "deploy"):
            path = ROOT / root
            for f in ([path] if path.is_file() else sorted(path.rglob("*"))):
                if not f.is_file() or f.suffix not in (".py", ".html", ".js", ".json", ".yml", ".yaml", ".toml", ".css"):
                    continue
                if "app/bess_commercial_candidate" in f.as_posix():
                    continue
                try:
                    if "bess_commercial_candidate" in f.read_text(encoding="utf-8"):
                        bad.append(f.relative_to(ROOT).as_posix())
                except UnicodeDecodeError:
                    continue
        assert bad == []

    def test_importing_the_candidate_loads_no_financial_web_or_research_module(self):
        code = ("import sys, app.bess_commercial_candidate;"
                "print(sorted(m for m in sys.modules if m.split('.')[0] in "
                "('financial_engine','finco_core','research','domain','fastapi','flask','starlette','jinja2')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == "[]", out.stderr

    def test_the_candidate_adds_no_route_ui_or_default(self):
        for f in sorted((ROOT / "app" / "bess_commercial_candidate").glob("*.py")):
            names = {a.name.split(".")[0] for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
                     if isinstance(n, (ast.Import, ast.ImportFrom))
                     for a in (n.names if isinstance(n, ast.Import) else [ast.alias(name=n.module or "")])}
            assert not names & {"fastapi", "flask", "starlette", "jinja2", "requests", "httpx", "os", "financial_engine",
                                "finco_core", "research"}, (f.name, names)


# ── 14. Existing BESS / canonical outputs are bit-identical ─────────────────

PINNED_BLOBS = {
    "domain/bess/__init__.py": "1905167cfb38bebb69f5f8b24f4100adf2b71f3d",
    "domain/bess/contracts.py": "1143dced2b27e3b7ed16754ccd3a17f6982d9f98",
    "domain/bess/dispatch.py": "ff2a9d2be76c2b1be308c596c42e32fe4276a9bc",
    "domain/bess/settlement.py": "e10829563e359f1766c6d8f98542e43107dac0dd",
    "domain/bess/synthetic.py": "427ad4589f9726c07e7c3723c2ff7ceed68c38ae",
    "financial_engine/bess.py": "a07873816d97240ae02af106cd31b2135ee63316",
    "domain/revenue/bess.py": "2e793f4ee7f1a1afd0f8822f37095a220b055927",
    "finco_core/inputs/bess_native.py": "57ee798dbe4742c1b36acbfbc1412c90b172d3a2",
    "research/wf09a/costing.py": "9751bb4f0a85ecc19bd7245add1873169059b29d",
}


class TestExistingOutputsUnchanged:
    @pytest.mark.parametrize("path,blob", sorted(PINNED_BLOBS.items()))
    def test_existing_sources_are_byte_identical_to_main(self, path, blob):
        out = subprocess.run(["git", "hash-object", path], cwd=ROOT, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == blob

    def test_native_hourly_evaluation_is_bit_identical(self, native):
        import hashlib
        rows = [[str(getattr(h, f)) for f in ("start", "grid_import_mwh", "grid_export_mwh", "closing_energy_mwh", "soh_closing",
                                              "gross_sale_revenue_keur", "charging_purchase_cost_keur",
                                              "net_merchant_contribution_keur")] for h in native.hours]
        assert hashlib.sha256(json.dumps(rows).encode()).hexdigest() == \
            "7702e2e28bae7b546101f203c4cb9e3b1e8910a306470eb01b55c1de2174b7d1"
        assert native.input_fingerprint == "15a5d6df2fc0b777af95c9bcb9afe95a7cb1decf3260a7a36fef20162355efa8"
        assert (str(native.net_merchant_contribution_keur), str(native.total_dc_throughput_mwh)) == ("0.05622", "3.6")

    def test_candidate_use_does_not_change_native_evaluation(self, released, native):
        explicit(day(native, 0)); allocate((), (), native.hours[:24], rated_discharge_mw=D(1), rated_charge_mw=D(1))
        again = evaluate(parse_configuration(json.dumps(example())))
        assert again.input_fingerprint == native.input_fingerprint and again.hours == native.hours

    def test_legacy_net_spread_approximation_values_are_unchanged(self):
        from domain.revenue.bess import (BessParams, bess_ancillary_revenue_keur, bess_arbitrage_revenue_keur,
                                         bess_augmentation_cost_keur, bess_capacity_revenue_keur, bess_discharged_mwh)
        p = BessParams(power_mw=100, energy_mwh=200, cycles_per_year=350)
        assert (bess_discharged_mwh(p, 1), bess_discharged_mwh(p, 3, .5), bess_arbitrage_revenue_keur(p, 2),
                bess_capacity_revenue_keur(p), bess_ancillary_revenue_keur(p, .25),
                bess_augmentation_cost_keur(BessParams(100, 200, 350, augmentation_capex_keur=1000), 4)) == \
            (60368.0, 28988.713600000003, 2366.4256, 0.0, 625.0, 100.0)
