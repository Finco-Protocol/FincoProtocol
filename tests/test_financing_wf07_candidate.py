"""WF-07 financing & reserve integration candidate — acceptance tests.

Independent expectations are computed with ``fractions.Fraction`` inside this
file (never with the code under test) or taken from the RELEASED float
engines. Matrix:

 1 one senior + SHL (released-equivalent)       9 insufficient CFADS / shortfall
 2 two seniors + aggregate DSRA target         10 reserved cash is not distributed
 3 three seniors, different maturities         11 commitment exhaustion over periods
 4 DSRA top-up after higher debt service       12 double funding / duplicate claims
 5 cash-funded vs undrawn facility reserve     13 missing evidence fails closed
 6 DSRF shortfall and restoration              14 balance and source/use conservation
 7 SHL cash and PIK interest                   15 existing outputs unaffected
 8 subordination and waterfall ordering        +  release closure and isolation
"""
from __future__ import annotations

import ast
import random
import subprocess
import sys
from datetime import date
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path

import pytest

import app.model_v2.financing_wf07_candidate.contracts as contracts
from app.model_v2.financing_wf07_candidate import (
    SUPPORTED_POLICY, CANDIDATE, UNAVAILABLE, UNSUPPORTED, ConstructionUse, Decision, EquityPool,
    FacilityService, InterestMode, InterestTreatment, Layer, PeriodEvidence, Phase, ReserveContract,
    ReserveOpening, ReservePosition, ReserveTargetEvidence, ReserveType, SeniorDraw, ShlDraw,
    ShlPrincipal, ShlTerms, WaterfallPolicy, Wf07Error, Wf07Inputs, forward_requirement, identity, run,
)
from app.model_v2.financing_wf07_candidate.engine import RESERVE_FUNDING

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "app" / "model_v2" / "financing_wf07_candidate"


@pytest.fixture(autouse=True)
def released(monkeypatch):
    """Isolated acceptance fixture: open the candidate gate in memory only."""
    monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)


# ── builders ────────────────────────────────────────────────────────────────

Q = D("0.25")
ENDS = [date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30), date(2026, 12, 31),
        date(2027, 3, 31), date(2027, 6, 30), date(2027, 9, 30)]


def periods(n_construction, cash, n_operating=None):
    """Construction periods 0..n-1 then operating periods carrying the given CFADS values."""
    out = []
    for i in range(n_construction):
        out.append(PeriodEvidence(i, ENDS[i], Phase.CONSTRUCTION, Q))
    for k, c in enumerate(cash):
        i = n_construction + k
        out.append(PeriodEvidence(i, ENDS[i], Phase.OPERATING, Q,
                                  None if c is None else D(c), None if c is None else f"cfads-{i}"))
    return tuple(out)


def svc(first_op, table, layer=Layer.SENIOR, paid=None):
    """table: {facility: [service per operating period]} -> FacilityService rows."""
    rows = []
    for fac, vals in table.items():
        for k, v in enumerate(vals):
            p = None if paid is None else paid.get((fac, k))
            rows.append(FacilityService(first_op + k, fac, layer, None if v is None else D(v),
                                        f"ds-{fac}-{first_op + k}", None if p is None else D(p)))
    return tuple(rows)


def targets(first_op, reserve_id, values):
    return tuple(ReserveTargetEvidence(first_op + k, reserve_id, None if v is None else D(v),
                                       f"tgt-{reserve_id}-{first_op + k}") for k, v in enumerate(values))


def dsra(rid="DSRA"):
    return ReserveContract(rid, ReserveType.DSRA)


def dsrf(limit, rid="DSRF"):
    return ReserveContract(rid, ReserveType.DSRF, D(limit), f"limit-{rid}")


def inputs(**kw):
    base = dict(periods=periods(0, [300, 300, 300]), services=(), senior_draws=(), uses=(),
                equity_pools=(), shl=(), reserves=(), targets=(), openings=(), policy=SUPPORTED_POLICY)
    base.update(kw)
    return Wf07Inputs(**base)


def shl(sid="SHL-1", commitment=500, rate="0.08", cmode=InterestMode.PIK, omode=InterestMode.CASH,
        draws=((0, 400),), principal=()):
    return ShlTerms(sid, D(commitment), D(rate), cmode, omode,
                    tuple(ShlDraw(p, D(a), f"{sid}-draw-{p}") for p, a in draws),
                    tuple(ShlPrincipal(p, D(a)) for p, a in principal if a))


def op_row(res, index):
    return next(r for r in res.operating if r.period_index == index)


def dsra_row(res, index):
    return next(r for r in res.dsra_rows if r.period_index == index)


def dsrf_row(res, index):
    return next(r for r in res.dsrf_rows if r.period_index == index)


# ── 1. one senior + SHL: released-equivalence ───────────────────────────────


class TestSingleSeniorWithShl:
    def test_shl_schedule_equals_the_released_engine_and_an_exact_oracle(self):
        from financial_engine.shl.contracts import ShlInterestPaymentMode as M
        from financial_engine.shl.engine import compute_shl_period
        res = run(inputs(
            periods=periods(2, [300]), shl=(shl(),),
            uses=(ConstructionUse(0, "EPC", D(400), "use-0"),),
            services=svc(2, {"SENIOR-A": [100]})))
        assert res.status == CANDIDATE and res.complete
        rows = {r.period_index: r for r in res.shl_rows}
        released = []
        bal = 0.0
        for idx, mode, draw in ((0, M.PIK, 400.0), (1, M.PIK, 0.0), (2, M.CASH_PAID, 0.0)):
            r = compute_shl_period(bal, draw, 0.25, 0.08, mode, 0.0, idx)
            released.append(r)
            bal = r.closing_balance_keur
        for r in released:
            mine = rows[r.period_index]
            assert float(mine.opening) == pytest.approx(r.opening_balance_keur, abs=1e-9)
            assert float(mine.accrued_interest) == pytest.approx(r.gross_accrued_interest_keur, abs=1e-9)
            assert float(mine.cash_interest_paid) == pytest.approx(r.cash_interest_keur, abs=1e-9)
            assert float(mine.pik_interest) == pytest.approx(r.pik_interest_keur, abs=1e-9)
            assert float(mine.closing) == pytest.approx(r.closing_balance_keur, abs=1e-9)
        # exact oracle (Fractions): 400 -> 408 -> 416.16, operating cash interest 8.3232
        assert rows[1].closing == D("416.16") and rows[2].cash_interest_paid == D("8.3232")
        op = op_row(res, 2)
        assert op.senior_paid_from_cash == 100 and op.distribution_candidate == D("191.6768")


# ── 2/3. several seniors and aggregate DSRA targets ─────────────────────────


class TestAggregateReserveRequirements:
    def test_two_seniors_aggregate_forward_requirement_funds_one_dsra(self):
        services = svc(0, {"A": [60, 60, 60], "B": [40, 40, 40]})
        agg, truncated = forward_requirement(services, 0, 1)
        assert (agg, truncated) == (D(100), False)
        per_a, _ = forward_requirement(services, 0, 1, "A")
        assert per_a == D(60)
        res = run(inputs(periods=periods(0, [300, 300, 300]), services=services, reserves=(dsra(),),
                         targets=targets(0, "DSRA", [100, 100, 100]),
                         openings=(ReserveOpening("DSRA", D(0), "open-DSRA"),)))
        assert res.status == CANDIDATE
        r0 = dsra_row(res, 0)
        assert (r0.opening, r0.deposit, r0.closing) == (0, 100, 100)
        assert op_row(res, 0).senior_due == 100 and op_row(res, 0).distribution_candidate == 100
        assert op_row(res, 1).dsra_top_up == 0 and op_row(res, 1).distribution_candidate == 200

    def test_three_seniors_with_different_maturities_and_a_truncated_horizon(self):
        table = {"A": [50, 50, 50], "B": [30, 30, 0], "C": [20, 20, 20]}
        services = svc(0, table)
        assert forward_requirement(services, 0, 2) == (D(170), False)       # p1 100 + p2 70
        assert forward_requirement(services, 1, 2) == (D(70), True)
        assert forward_requirement(services, 2, 2) == (D(0), True)
        res = run(inputs(periods=periods(0, [300, 300, 300]), services=services))
        assert [op_row(res, i).senior_due for i in range(3)] == [D(100), D(100), D(70)]

    def test_missing_contractual_service_in_the_window_is_unavailable_not_zero(self):
        services = svc(0, {"A": [50, None, 50]})
        assert forward_requirement(services, 0, 2) == (None, False)


# ── 4. DSRA top-up after an increased obligation, release after decrease ────


class TestDsraLedger:
    def test_top_up_follows_a_higher_target_and_release_follows_a_lower_one(self):
        res = run(inputs(periods=periods(0, [300, 300, 300]), services=svc(0, {"A": [100, 100, 100]}),
                         reserves=(dsra(),), targets=targets(0, "DSRA", [100, 150, 120]),
                         openings=(ReserveOpening("DSRA", D(0), "o"),)))
        rows = [dsra_row(res, i) for i in range(3)]
        assert [(r.deposit, r.release, r.closing) for r in rows] == [(100, 0, 100), (50, 0, 150), (0, 30, 120)]
        assert op_row(res, 2).distribution_candidate == D(300 - 100 + 30)
        for r in rows:
            assert r.opening + r.deposit - r.draw - r.release == r.closing
        assert rows[1].opening == rows[0].closing

    def test_top_up_is_limited_by_cash_and_the_remainder_is_a_reported_shortfall(self):
        res = run(inputs(periods=periods(0, [140]), services=svc(0, {"A": [100]}), reserves=(dsra(),),
                         targets=targets(0, "DSRA", [100]), openings=(ReserveOpening("DSRA", D(0), "o"),)))
        r = dsra_row(res, 0)
        assert (r.deposit, r.closing, r.shortfall_to_target) == (40, 40, 60)
        assert op_row(res, 0).distribution_candidate == 0 and op_row(res, 0).retained_cash == 0

    def test_dsra_draw_covers_a_senior_shortfall(self):
        res = run(_dsra_draw_inputs())
        assert res.status == CANDIDATE
        r = dsra_row(res, 3)
        assert (r.opening, r.draw, r.closing, r.shortfall_to_target) == (100, 40, 60, 40)
        assert op_row(res, 3).senior_shortfall == 0


def _dsra_draw_inputs():
    return inputs(periods=periods(3, [60]), services=svc(3, {"A": [100]}), reserves=(dsra(),),
                  targets=targets(3, "DSRA", [100]),
                  openings=(ReserveOpening("DSRA", D(100), "o"),),
                  uses=(ConstructionUse(2, RESERVE_FUNDING, D(100), "u-res", "DSRA"),),
                  equity_pools=(EquityPool("EQ", D(100)),))


class TestDsraDrawIsBoundedByTheBalance:
    def test_the_draw_never_exceeds_the_reserve_and_the_rest_is_a_recorded_shortfall(self):
        ins = inputs(periods=periods(3, [0]), services=svc(3, {"A": [130]}, paid={("A", 0): 100}),
                     reserves=(dsra(),), targets=targets(3, "DSRA", [100]),
                     openings=(ReserveOpening("DSRA", D(100), "o"),),
                     uses=(ConstructionUse(2, RESERVE_FUNDING, D(100), "u", "DSRA"),),
                     equity_pools=(EquityPool("EQ", D(100)),))
        res = run(ins)
        row, r = op_row(res, 3), dsra_row(res, 3)
        assert (row.dsra_draw, row.senior_shortfall, r.closing) == (100, 30, 0)
        assert row.conservation_residual() == 0 and res.reasons == ("WF07_DEFAULT_CURE_POLICY_OPEN",)


# ── 5. cash-funded vs facility-backed reserve ───────────────────────────────


class TestCashVersusFacilityBacked:
    def _scenario(self, reserve, opening=D(0)):
        return run(inputs(periods=periods(0, [300, 300]), services=svc(0, {"A": [100, 100]}),
                          reserves=(reserve,), targets=targets(0, reserve.reserve_id, [100, 100]),
                          openings=(ReserveOpening(reserve.reserve_id, opening, "o"),)))

    def test_an_undrawn_facility_backed_reserve_moves_no_project_cash(self):
        cash = self._scenario(dsra())
        fac = self._scenario(dsrf(150))
        assert op_row(cash, 0).distribution_candidate == 100 and op_row(cash, 0).dsra_top_up == 100
        assert op_row(fac, 0).distribution_candidate == 200
        r = dsrf_row(fac, 0)
        assert (r.draw, r.restoration, r.closing_drawn, r.available, r.coverage_shortfall) == (0, 0, 0, 150, 0)
        assert fac.dsra_rows == () and cash.dsrf_rows == ()

    def test_contract_types_are_never_confused(self):
        with pytest.raises(Wf07Error, match="WF07_DSRF_FACILITY_EVIDENCE_MISSING"):
            ReserveContract("R", ReserveType.DSRF)
        with pytest.raises(Wf07Error, match="WF07_DSRA_IS_CASH_NOT_A_FACILITY"):
            ReserveContract("R", ReserveType.DSRA, D(10), "limit")
        with pytest.raises(Wf07Error, match="WF07_DSRF_CASH_FUNDING_REJECTED"):
            inputs(reserves=(dsrf(100),), uses=(ConstructionUse(0, RESERVE_FUNDING, D(10), "u", "DSRF"),),
                   periods=periods(1, [100]))

    def test_dsrf_fee_policy_is_open(self):
        with pytest.raises(Wf07Error, match="WF07_DECISION_NOT_OPEN"):
            ReserveContract("R", ReserveType.DSRF, D(10), "l", fee_policy="PAID")


# ── 6. DSRF shortfall and restoration ───────────────────────────────────────


class TestDsrfShortfallAndRestoration:
    def test_draw_covers_the_shortfall_and_cash_restores_it_next_period(self):
        res = run(inputs(periods=periods(0, [60, 300]), services=svc(0, {"A": [100, 100]}),
                         reserves=(dsrf(150),), targets=targets(0, "DSRF", [100, 100]),
                         openings=(ReserveOpening("DSRF", D(0), "o"),)))
        assert res.status == CANDIDATE
        a, b = dsrf_row(res, 0), dsrf_row(res, 1)
        assert (a.draw, a.closing_drawn, a.available) == (40, 40, 110) and a.coverage_shortfall == 0
        assert (b.restoration, b.closing_drawn, b.available) == (40, 0, 150)
        assert op_row(res, 0).senior_shortfall == 0 and op_row(res, 0).distribution_candidate == 0
        assert op_row(res, 1).distribution_candidate == 160
        for r in (a, b):
            assert r.opening_drawn + r.draw - r.restoration == r.closing_drawn
            assert r.available == r.limit - r.closing_drawn

    def test_a_limit_below_the_target_is_a_coverage_shortfall_that_locks_distributions(self):
        res = run(inputs(periods=periods(0, [300]), services=svc(0, {"A": [100]}), reserves=(dsrf(80),),
                         targets=targets(0, "DSRF", [100]), openings=(ReserveOpening("DSRF", D(0), "o"),)))
        r = dsrf_row(res, 0)
        assert r.coverage_shortfall == 20
        assert op_row(res, 0).distribution_candidate == 0 and op_row(res, 0).retained_cash == 200

    def test_the_draw_cannot_exceed_the_remaining_facility_and_the_rest_is_a_shortfall(self):
        paid = {("A", 0): 80}
        res = run(inputs(periods=periods(0, [10]), services=svc(0, {"A": [100]}, paid=paid),
                         reserves=(dsrf(70),), targets=targets(0, "DSRF", [0]),
                         openings=(ReserveOpening("DSRF", D(0), "o"),)))
        row = op_row(res, 0)
        assert row.dsrf_draw == 70 and row.senior_shortfall == 20 and row.facility_paid == (("A", D(80)),)
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_DEFAULT_CURE_POLICY_OPEN",)

    def test_draws_not_permitted_by_policy_is_unsupported(self):
        policy = WaterfallPolicy(SUPPORTED_POLICY.ranking, SUPPORTED_POLICY.reserve_position,
                                 SUPPORTED_POLICY.draw_order, SUPPORTED_POLICY.restoration_order, False)
        res = run(inputs(policy=policy))
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_POLICY_COMBINATION_UNSUPPORTED",)


# ── 7. SHL cash interest and PIK ────────────────────────────────────────────


class TestShlCashAndPik:
    def test_pik_capitalises_cash_pays_and_the_balance_identity_holds(self):
        t = shl(commitment=1000, omode=InterestMode.PIK, draws=((0, 1000),), principal=((3, 100),))
        res = run(inputs(periods=periods(1, [500, 500, 500]), shl=(t,),
                         uses=(ConstructionUse(0, "EPC", D(1000), "u"),)))
        assert res.status == CANDIDATE
        by = {r.period_index: r for r in res.shl_rows}
        bal = F(0)
        for idx in (0, 1, 2, 3):                       # exact Fraction oracle, PIK throughout
            draw = F(1000) if idx == 0 else F(0)
            acc = (bal + draw) * F(8, 100) * F(1, 4)
            prin = F(100) if idx == 3 else F(0)
            bal = bal + draw + acc - prin
            assert F(by[idx].accrued_interest) == acc and F(by[idx].closing) == bal
            r = by[idx]
            assert r.opening + r.draw + r.pik_interest - r.principal_paid == r.closing
        assert by[0].treatment is InterestTreatment.CAPITALIZED
        assert by[1].treatment is InterestTreatment.OPERATING_EXPENSE_CANDIDATE
        assert all(r.cash_interest_paid == 0 for r in res.shl_rows)
        assert by[3].principal_paid == 100 and op_row(res, 3).shl_principal_due == 100
        assert by[0].claim_class.value == "SPONSOR_DEBT"

    def test_cash_interest_is_paid_below_senior_and_is_not_a_distribution(self):
        res = run(inputs(periods=periods(1, [200]), shl=(shl(draws=((0, 500),), cmode=InterestMode.PIK),),
                         uses=(ConstructionUse(0, "EPC", D(500), "u"),), services=svc(1, {"A": [100]})))
        row = op_row(res, 1)
        # construction PIK 500*0.08*0.25 = 10 -> operating balance 510; cash interest 510*0.02 = 10.2
        assert row.shl_cash_interest_due == D("10.2") and row.shl_paid == D("10.2")
        assert row.distribution_candidate == D("89.8")
        assert row.conservation_residual() == 0

    def test_construction_cash_interest_is_a_use_funded_by_sources(self):
        t = shl(cmode=InterestMode.CASH, draws=((0, 400),))
        res = run(inputs(periods=periods(2, [100]), shl=(t,), uses=(ConstructionUse(0, "EPC", D(400), "u0"),),
                         equity_pools=(EquityPool("EQ", D(100)),)))
        c0, c1 = res.construction
        assert c0.shl_cash_interest_use == 8 and c0.uses_total == 408 and c0.equity_draws == (("EQ", D(8)),)
        assert c1.shl_cash_interest_use == 8 and c1.uses_total == 8 and c1.equity_draws == (("EQ", D(8)),)

    def test_tax_deductibility_is_open_and_shl_is_never_equity(self):
        with pytest.raises(Wf07Error, match="WF07_DECISION_NOT_OPEN"):
            ShlTerms("S", D(1), D(0), InterestMode.CASH, InterestMode.CASH, (), tax_deductibility="DEDUCTIBLE")
        from app.model_v2.financing_wf07_candidate import ClaimClass
        with pytest.raises(Wf07Error, match="WF07_SHL_CLAIM_CLASS"):
            ShlTerms("S", D(1), D(0), InterestMode.CASH, InterestMode.CASH, (), claim_class=ClaimClass.LEGAL_EQUITY)
        with pytest.raises(Wf07Error, match="WF07_EQUITY_CLAIM_CLASS"):
            EquityPool("E", D(1), ClaimClass.SPONSOR_DEBT)

    def test_principal_beyond_the_balance_or_in_construction_is_rejected(self):
        with pytest.raises(Wf07Error, match="WF07_SHL_PRINCIPAL_EXCEEDS_BALANCE"):
            run(inputs(periods=periods(1, [500]),
                       shl=(shl(draws=((0, 100),), principal=((1, 500),)),),
                       uses=(ConstructionUse(0, "EPC", D(100), "u"),)))
        with pytest.raises(Wf07Error, match="WF07_SHL_PRINCIPAL_IN_CONSTRUCTION"):
            run(inputs(periods=periods(2, [500]), shl=(shl(draws=((0, 100),), principal=((1, 5),)),),
                       uses=(ConstructionUse(0, "EPC", D(100), "u"),)))


# ── 8. subordination and waterfall ordering ─────────────────────────────────


def _layered(cash, junior=30, principal=20):
    return inputs(
        periods=periods(1, [cash]),
        services=svc(1, {"A": [100]}) + svc(1, {"J": [junior]}, Layer.JUNIOR),
        shl=(shl(draws=((0, 400),), cmode=InterestMode.CASH, omode=InterestMode.CASH, principal=((1, principal),)),),
        uses=(ConstructionUse(0, "EPC", D(400), "u"),),
        equity_pools=(EquityPool("EQ", D(100)),))


class TestSubordinationAndOrdering:
    def test_senior_then_junior_then_shl_then_distribution(self):
        # SHL operating: 400 * 0.08 * 0.25 = 8 cash interest + 20 principal = 28
        res = run(_layered(200))
        row = op_row(res, 1)
        assert (row.senior_due, row.junior_paid, row.shl_paid) == (100, 30, 28)
        assert row.distribution_candidate == 42 and row.conservation_residual() == 0
        assert [r for r in res.shl_rows if r.period_index == 1][0].closing == 380

    def test_a_junior_shortfall_stops_everything_below_it(self):
        res = run(_layered(125))
        row = op_row(res, 1)
        assert row.junior_paid == 25 and row.shl_paid == 0 and row.distribution_candidate == 0
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_JUNIOR_SHORTFALL_POLICY_OPEN",)
        assert not [r for r in res.shl_rows if r.period_index == 1]

    def test_an_shl_shortfall_never_defers_or_capitalises_and_blocks_distribution(self):
        res = run(_layered(150))
        row = op_row(res, 1)
        assert (row.junior_paid, row.shl_paid, row.shl_shortfall, row.distribution_candidate) == (30, 20, 8, 0)
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_SHL_SHORTFALL_POLICY_OPEN",)

    def test_other_rankings_and_reserve_positions_are_unsupported(self):
        for policy in (
                WaterfallPolicy((Layer.SENIOR, Layer.SHAREHOLDER_LOAN, Layer.JUNIOR), ReservePosition.AFTER_SENIOR,
                                SUPPORTED_POLICY.draw_order, SUPPORTED_POLICY.restoration_order, True),
                WaterfallPolicy(SUPPORTED_POLICY.ranking, ReservePosition.AFTER_JUNIOR,
                                SUPPORTED_POLICY.draw_order, SUPPORTED_POLICY.restoration_order, True),
                WaterfallPolicy(SUPPORTED_POLICY.ranking, ReservePosition.AFTER_SENIOR,
                                (ReserveType.DSRF, ReserveType.DSRA), SUPPORTED_POLICY.restoration_order, True)):
            assert run(inputs(policy=policy)).status == UNSUPPORTED

    def test_a_policy_object_is_mandatory(self):
        with pytest.raises(Wf07Error, match="WF07_POLICY_REQUIRED"):
            inputs(policy=None)

    def test_a_release_and_a_shortfall_in_one_period_is_not_resolved_by_inference(self):
        res = run(inputs(periods=periods(3, [60]), services=svc(3, {"A": [100]}), reserves=(dsra(),),
                         targets=targets(3, "DSRA", [20]), openings=(ReserveOpening("DSRA", D(100), "o"),),
                         uses=(ConstructionUse(2, RESERVE_FUNDING, D(100), "u", "DSRA"),),
                         equity_pools=(EquityPool("EQ", D(100)),)))
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_RELEASE_AND_SHORTFALL_OPEN",)


# ── 9. insufficient CFADS ───────────────────────────────────────────────────


class TestInsufficientCfads:
    def test_no_implicit_pro_rata_allocation_of_a_shortfall(self):
        res = run(inputs(periods=periods(0, [70]), services=svc(0, {"A": [60], "B": [40]})))
        assert res.status == UNAVAILABLE and res.reasons == ("WF07_SHORTFALL_ALLOCATION_POLICY_OPEN",)

    def test_a_supplied_allocation_is_recorded_and_the_default_mechanism_is_open(self):
        res = run(inputs(periods=periods(0, [70]),
                         services=svc(0, {"A": [60], "B": [40]}, paid={("A", 0): 42, ("B", 0): 28})))
        row = op_row(res, 0)
        assert row.senior_shortfall == 30 and row.distribution_candidate == 0
        assert row.facility_paid == (("A", D(42)), ("B", D(28)))
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_DEFAULT_CURE_POLICY_OPEN",)
        assert row.conservation_residual() == 0

    def test_paid_evidence_that_does_not_add_up_is_rejected(self):
        with pytest.raises(Wf07Error, match="WF07_PAID_EVIDENCE_MISMATCH"):
            run(inputs(periods=periods(0, [70]),
                       services=svc(0, {"A": [60], "B": [40]}, paid={("A", 0): 42, ("B", 0): 30})))
        with pytest.raises(Wf07Error, match="WF07_PAID_EVIDENCE_MISMATCH"):
            run(inputs(periods=periods(0, [300]), services=svc(0, {"A": [60]}, paid={("A", 0): 50})))


# ── 10. reserved cash is not distributed ────────────────────────────────────


class TestReservedCashIsNotDistributed:
    def test_all_cash_up_to_the_target_goes_to_the_reserve_first(self):
        res = run(inputs(periods=periods(0, [150]), services=svc(0, {"A": [100]}), reserves=(dsra(),),
                         targets=targets(0, "DSRA", [100]), openings=(ReserveOpening("DSRA", D(0), "o"),)))
        row = op_row(res, 0)
        assert row.dsra_top_up == 50 and row.distribution_candidate == 0

    def test_distributions_equal_only_the_surplus_after_every_obligation(self):
        res = run(inputs(periods=periods(0, [400]), services=svc(0, {"A": [100]}), reserves=(dsra(),),
                         targets=targets(0, "DSRA", [100]), openings=(ReserveOpening("DSRA", D(0), "o"),)))
        assert op_row(res, 0).distribution_candidate == 200


# ── 11. commitment exhaustion across construction periods ───────────────────


def _construction(pools, uses=(100, 100, 100)):
    return inputs(
        periods=periods(3, [100]), services=svc(3, {"A": [10]}),
        uses=tuple(ConstructionUse(i, "EPC", D(u), f"u{i}") for i, u in enumerate(uses)),
        senior_draws=tuple(SeniorDraw(i, "A", D(40), f"sd{i}") for i in range(3)),
        shl=(ShlTerms("SHL-1", D(50), D(0), InterestMode.PIK, InterestMode.CASH, (ShlDraw(0, D(20), "shl-d0"),)),),
        equity_pools=pools)


class TestCommitmentExhaustion:
    def test_pools_deplete_in_order_and_are_never_reused(self):
        res = run(_construction((EquityPool("EQ-A", D(100)), EquityPool("EQ-B", D(100)))))
        assert res.status == CANDIDATE
        taken = [dict(r.equity_draws) for r in res.construction]
        assert taken == [{"EQ-A": D(40)}, {"EQ-A": D(60)}, {"EQ-B": D(60)}]
        drawn_a = sum(d.get("EQ-A", 0) for d in taken)
        assert drawn_a == 100                                   # exactly the commitment
        for r in res.construction:
            sources = r.senior_draws + r.shl_draws + sum(a for _, a in r.equity_draws) + r.funding_gap
            assert sources == r.uses_total

    def test_a_residual_gap_is_typed_never_filled_and_never_hidden(self):
        res = run(_construction((EquityPool("EQ-A", D(100)), EquityPool("EQ-B", D(50)))))
        assert res.status == UNAVAILABLE and res.reasons == ("WF07_FUNDING_GAP",) and not res.complete
        assert res.construction[-1].funding_gap == 10

    def test_explicit_draws_beyond_the_uses_are_not_silently_distributed(self):
        res = run(inputs(periods=periods(1, [100]), uses=(ConstructionUse(0, "EPC", D(10), "u"),),
                         senior_draws=(SeniorDraw(0, "A", D(30), "d"),), services=svc(1, {"A": [10]})))
        assert res.status == UNSUPPORTED and res.reasons == ("WF07_SOURCES_EXCEED_USES",)

    def test_a_commitment_cannot_be_drawn_beyond_its_size(self):
        with pytest.raises(Wf07Error, match="WF07_SHL_COMMITMENT_EXCEEDED"):
            ShlTerms("S", D(50), D(0), InterestMode.PIK, InterestMode.CASH,
                     (ShlDraw(0, D(30), "a"), ShlDraw(1, D(30), "b")))


# ── 12. double funding and duplicated reserve claims ────────────────────────


class TestDuplicateClaimsRejected:
    def test_the_same_funding_or_use_evidence_cannot_be_counted_twice(self):
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(periods=periods(2, [100]), uses=(ConstructionUse(0, "EPC", D(10), "same"),
                                                    ConstructionUse(1, "EPC", D(10), "same")))
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            ShlTerms("S", D(100), D(0), InterestMode.PIK, InterestMode.CASH,
                     (ShlDraw(0, D(10), "e"), ShlDraw(1, D(10), "e")))
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(equity_pools=(EquityPool("X", D(1)),), shl=(shl(sid="X"),))

    def test_senior_draw_evidence_cannot_be_reused_across_periods_or_categories(self):
        draws = (SeniorDraw(0, "A", D(10), "sd"), SeniorDraw(1, "A", D(10), "sd"))
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(periods=periods(2, [100]), senior_draws=draws, services=svc(2, {"A": [10]}))
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(periods=periods(2, [100]), senior_draws=draws[:1], services=svc(2, {"A": [10]}),
                   uses=(ConstructionUse(1, "EPC", D(10), "sd"),))

    def test_one_reserve_evidence_item_cannot_back_two_claims(self):
        a = ReserveTargetEvidence(0, "DSRA", D(10), "shared")
        b = ReserveTargetEvidence(0, "DSRF", D(10), "shared")
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(periods=periods(0, [100]), reserves=(dsra(), dsrf(50)), targets=(a, b))
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(reserves=(dsra(), dsra()))

    def test_more_than_one_reserve_of_a_type_is_unsupported(self):
        with pytest.raises(Wf07Error, match="WF07_MULTIPLE_RESERVES_OF_TYPE_UNSUPPORTED"):
            inputs(reserves=(dsra("R1"), dsra("R2")))

    def test_reserve_funding_is_counted_once_as_a_use_and_must_equal_the_opening(self):
        res = run(_dsra_draw_inputs())
        c = res.construction[2]
        assert c.uses_total == 100 and sum(a for _, a in c.equity_draws) == 100      # funded by sources, once
        with pytest.raises(Wf07Error, match="WF07_RESERVE_FUNDING_MISMATCH"):
            run(inputs(periods=periods(3, [300]), services=svc(3, {"A": [100]}), reserves=(dsra(),),
                       targets=targets(3, "DSRA", [100]), openings=(ReserveOpening("DSRA", D(100), "o"),)))
        with pytest.raises(Wf07Error, match="WF07_RESERVE_FUNDING_MISMATCH"):
            run(inputs(periods=periods(3, [300]), services=svc(3, {"A": [100]}), reserves=(dsra(),),
                       targets=targets(3, "DSRA", [100]), openings=(ReserveOpening("DSRA", D(150), "o"),),
                       uses=(ConstructionUse(2, RESERVE_FUNDING, D(100), "u", "DSRA"),),
                       equity_pools=(EquityPool("EQ", D(100)),)))

    def test_a_facility_cannot_serve_two_layers_and_service_rows_are_unique(self):
        with pytest.raises(Wf07Error, match="WF07_FACILITY_LAYER"):
            inputs(periods=periods(0, [1, 1]), services=svc(0, {"A": [1]}) + svc(1, {"A": [1]}, Layer.JUNIOR))
        with pytest.raises(Wf07Error, match="WF07_DUPLICATE"):
            inputs(periods=periods(0, [1]), services=svc(0, {"A": [1]}) + svc(0, {"A": [1]}))


# ── 13. missing evidence fails closed ───────────────────────────────────────


class TestMissingEvidenceFailsClosed:
    def test_each_missing_item_is_unavailable_and_halts(self):
        base = dict(periods=periods(0, [300]), services=svc(0, {"A": [100]}), reserves=(dsra(),),
                    targets=targets(0, "DSRA", [100]), openings=(ReserveOpening("DSRA", D(0), "o"),))
        assert run(inputs(**base)).status == CANDIDATE
        cases = {
            "WF07_CASH_EVIDENCE_MISSING": dict(periods=periods(0, [None])),
            "WF07_CONTRACTUAL_SERVICE_EVIDENCE_MISSING": dict(services=svc(0, {"A": [None]})),
            "WF07_RESERVE_TARGET_EVIDENCE_MISSING": dict(targets=targets(0, "DSRA", [None])),
            "WF07_RESERVE_OPENING_MISSING": dict(openings=()),
        }
        for reason, change in cases.items():
            res = run(inputs(**{**base, **change}))
            assert res.status == UNAVAILABLE and res.reasons == (reason,) and not res.complete, reason

    def test_a_known_facility_without_a_row_for_a_period_is_unavailable_not_assumed_matured(self):
        res = run(inputs(periods=periods(0, [100, 100]), services=svc(0, {"A": [10, 10]})[:1]
                         + svc(0, {"B": [10, 10]})))
        assert res.status == UNAVAILABLE

    def test_an_absent_target_row_is_unavailable_and_an_explicit_zero_is_a_zero_target(self):
        missing = run(inputs(periods=periods(0, [300]), services=svc(0, {"A": [100]}), reserves=(dsra(),),
                             openings=(ReserveOpening("DSRA", D(0), "o"),)))
        assert missing.status == UNAVAILABLE
        zero = run(inputs(periods=periods(0, [300]), services=svc(0, {"A": [100]}), reserves=(dsra(),),
                          targets=targets(0, "DSRA", [0]), openings=(ReserveOpening("DSRA", D(0), "o"),)))
        assert zero.status == CANDIDATE and op_row(zero, 0).distribution_candidate == 200

    def test_invalid_types_are_rejected_at_the_boundary(self):
        for bad in (1, 1.5, "1", True, D("NaN"), D("Infinity")):
            with pytest.raises(Wf07Error, match="WF07_VALUE"):
                ConstructionUse(0, "EPC", bad, "e")
        with pytest.raises(Wf07Error, match="WF07_VALUE"):
            ConstructionUse(0, "EPC", D(-1), "e")
        with pytest.raises(Wf07Error, match="WF07_IDENTITY"):
            ConstructionUse(0, "EPC", D(1), " ")
        with pytest.raises(Wf07Error, match="WF07_DECISION_NOT_OPEN|WF07_VALUE"):
            ReserveContract("R", ReserveType.DSRA, fee_policy=None)

    def test_inputs_are_validated_structurally(self):
        with pytest.raises(Wf07Error, match="WF07_PERIODS"):
            inputs(periods=tuple(reversed(periods(0, [1, 1]))))
        with pytest.raises(Wf07Error, match="WF07_SERVICE_PERIOD"):
            inputs(periods=periods(1, [1]), services=svc(0, {"A": [1]}))
        with pytest.raises(Wf07Error, match="WF07_DRAW_FACILITY"):
            inputs(periods=periods(1, [1]), senior_draws=(SeniorDraw(0, "ghost", D(1), "d"),))


# ── 14. conservation, against an independent Fraction oracle ────────────────


def _oracle(cash, due, target, opening, junior, shl_due):
    """Independent single-DSRA waterfall: senior -> release/top-up -> junior -> SHL -> remainder."""
    cash, due, target, opening, junior, shl_due = (F(x) for x in (cash, due, target, opening, junior, shl_due))
    paid = min(cash, due)
    left = cash - paid
    if due - paid > 0:
        return None
    release = max(F(0), opening - target)
    left += release
    top = min(left, max(F(0), target - opening))
    left -= top
    j = min(left, junior)
    left -= j
    s = min(left, shl_due)
    left -= s
    if j < junior or s < shl_due:
        return None
    closing = opening - release + top
    return closing, (left if closing >= target else F(0)), (left if closing < target else F(0))


class TestConservationAndOracle:
    def test_randomised_scenarios_match_an_independent_oracle_and_conserve_cash(self):
        rng = random.Random(7)
        checked = 0
        for _ in range(300):
            cash = rng.randrange(0, 400)
            due, junior, principal = rng.randrange(0, 150), rng.randrange(0, 60), rng.randrange(0, 30)
            target, fund = rng.randrange(0, 160), rng.choice([0, 0, 50, 120])
            ins = inputs(
                periods=periods(1, [cash]),
                services=svc(1, {"A": [due]}) + svc(1, {"J": [junior]}, Layer.JUNIOR),
                shl=(shl(draws=((0, 300),), cmode=InterestMode.PIK, omode=InterestMode.CASH,
                         principal=((1, principal),)),),
                uses=(ConstructionUse(0, "EPC", D(300), "u"),) + (
                    (ConstructionUse(0, RESERVE_FUNDING, D(fund), "uf", "DSRA"),) if fund else ()),
                equity_pools=(EquityPool("EQ", D(1000)),),
                reserves=(dsra(),), targets=targets(1, "DSRA", [target]),
                openings=(ReserveOpening("DSRA", D(fund), "o"),))
            res = run(ins)
            bal = F(300) * (1 + F(8, 100) * F(1, 4))                  # PIK in construction: 306
            shl_op = bal * F(8, 100) * F(1, 4) + principal            # cash interest + scheduled principal
            want = _oracle(cash, due, target, fund, junior, shl_op)
            row = res.operating[-1] if res.operating else None
            if want is None:
                assert res.status != CANDIDATE
                if row:
                    assert row.distribution_candidate == 0
                continue
            closing, dist, retained = want
            assert res.status == CANDIDATE, (cash, due, target, fund, junior, principal)
            assert F(dsra_row(res, 1).closing) == closing
            assert F(row.distribution_candidate) == dist and F(row.retained_cash) == retained
            assert row.conservation_residual() == 0
            r = dsra_row(res, 1)
            assert r.opening + r.deposit - r.draw - r.release == r.closing
            for c in res.construction:
                assert c.senior_draws + c.shl_draws + sum(a for _, a in c.equity_draws) + c.funding_gap == c.uses_total
            checked += 1
        assert checked > 100

    def test_determinism_and_context_free_provenance(self):
        from decimal import Context, localcontext, ROUND_DOWN
        ins = _layered(200)
        a = run(ins)
        with localcontext(Context(prec=5, rounding=ROUND_DOWN)):
            b = run(ins)
        assert a == b and a.provenance == b.provenance and len(a.provenance) == 64
        assert run(_layered(201)).provenance != a.provenance


# ── 15. release closure and isolation; released authority unaffected ────────


PINS = {
    "financial_engine/shl/engine.py": "48c3956739fcd972dd7347f167a959f8b65ce53a",
    "financial_engine/dsra/model.py": "68da8e9b715c71372c006460a3db9396d00e3168",
    "financial_engine/financing/dsrf.py": "f4b6f2905e90c71659a0d369036a7199b3959278",
    "financial_engine/financing/multisenior.py": "7fbe0a7b6d0bcd351f019c6a1e85988238a28d3c",
    "financial_engine/financing/junior_debt.py": "2205cfbcca33889975c964a5748797c82af5792f",
    "financial_engine/shareholder_waterfall/model.py": "9520b09b135c7fe39d3d4fac6a0c2462b7c1c4ca",
    "finco_core/construction/allocator.py": "6430b9ffbd44690a0f9a4accb68173a72d1cf1d3",
    "finco_core/inputs/financing_instruments.py": "e1d06441763d2316af45d14ddab1716abbe4f3ca",
    "app/model_v2/financing_f31_multitranche_candidate/reconciliation.py": "28891daf84982d9b4380255ac7daaf99c111744a",
}


class TestReleaseClosureAndIsolation:
    def test_the_gate_is_a_literal_false_in_source_and_fails_closed(self, monkeypatch):
        tree = ast.parse((PKG / "contracts.py").read_text(encoding="utf-8"))
        assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ACTIVATION_ENABLED" for t in n.targets)]
        assert len(assigns) == 1 and isinstance(assigns[0].value, ast.Constant) and assigns[0].value.value is False
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", False)
        with pytest.raises(Wf07Error, match="WF07_RELEASE_CLOSED"):
            run(inputs())

    def test_no_environment_variable_can_enable_the_package(self, monkeypatch):
        for name in ("ACTIVATION_ENABLED", "FINCO_WF07", "WF07_ENABLED"):
            monkeypatch.setenv(name, "1")
        out = subprocess.run([sys.executable, "-c",
                              "import app.model_v2.financing_wf07_candidate.contracts as c;print(c.ACTIVATION_ENABLED)"],
                             cwd=ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == "False"

    def test_the_candidate_is_non_authoritative_and_distinct_from_released_authority(self):
        res = run(inputs())
        assert res.non_authoritative is True
        assert res.authority == "WF07_FINANCING_RESERVES_CANDIDATE_V0"
        assert res.authority != "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"

    def test_nothing_outside_the_package_references_it(self):
        bad = []
        for root in ("app", "domain", "financial_engine", "finco_core", "finco_radar", "finco_protocol", "main_web.py",
                     "main_api.py", "main_mcp.py", "static", "frontend/src", "tools", ".github", "deploy"):
            path = ROOT / root
            for f in ([path] if path.is_file() else sorted(path.rglob("*"))):
                if not f.is_file() or f.suffix not in (".py", ".html", ".js", ".ts", ".tsx", ".json", ".yml", ".yaml"):
                    continue
                if "financing_wf07_candidate" in f.as_posix():
                    continue
                try:
                    if "financing_wf07_candidate" in f.read_text(encoding="utf-8"):
                        bad.append(f.relative_to(ROOT).as_posix())
                except UnicodeDecodeError:
                    continue
        assert bad == []

    def test_importing_the_candidate_adds_no_financial_web_or_sibling_candidate_module(self):
        # `app.model_v2` (the parent package) has its own imports; only the DELTA is the candidate's.
        code = ("import sys, app.model_v2; before = set(sys.modules); import app.model_v2.financing_wf07_candidate;"
                "print(sorted(m for m in set(sys.modules) - before if not m.startswith("
                "'app.model_v2.financing_wf07_candidate')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == "[]", out.stdout + out.stderr

    def test_the_package_imports_only_the_standard_library_and_itself(self):
        stdlib = set(sys.stdlib_module_names)
        for f in sorted(PKG.glob("*.py")):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                        else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
                for m in mods:
                    top = m.split(".")[0]
                    assert top in stdlib or m.startswith("app.model_v2.financing_wf07_candidate") or top == "__future__", (f.name, m)

    def test_released_financing_and_reserve_sources_are_byte_identical_to_their_pins(self):
        for path, blob in PINS.items():
            out = subprocess.run(["git", "hash-object", path], cwd=ROOT, capture_output=True, text=True, check=True)
            assert out.stdout.strip() == blob, path

    def test_the_candidate_never_resizes_debt_or_changes_a_contractual_payment(self):
        ins = inputs(periods=periods(0, [500, 500]), services=svc(0, {"A": [100, 80], "B": [40, 0]}))
        res = run(ins)
        assert [op_row(res, i).senior_due for i in range(2)] == [D(140), D(80)]
        assert [r.contractual_service for r in ins.services] == [D(100), D(80), D(40), D(0)]
