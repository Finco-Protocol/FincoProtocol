"""WF-09B cost receipts & LCOE/LCOS reconciliation — acceptance tests.

Expectations are hand-calculated with ``fractions.Fraction`` inside this file
(never with the code under test). The WF-09A arithmetic is the only formula;
these tests prove the receipt layer feeds it correctly and reconciles.

 1 Solar unlevered              8 cash tax and refunds            15 net-spread-only LCOS
 2 Wind unlevered               9 missing component vs zero       16 zero delivered energy
 3 levered vs unlevered        10 missing discount convention     17 duplicate source identity
 4 kEUR -> EUR/MWh             11 discounted energy denominator   18 Run identity / alignment
 5 construction CAPEX timing   12 different period lengths        19 ambient precision
 6 DEVEX/CAPEX duplicate       13 leap-year / nonstandard         20 zero change to canonical output
 7 IDC / financing double      14 explicit BESS charging cost
"""
from __future__ import annotations

import ast
import subprocess
import sys
from datetime import date
from decimal import Decimal as D, ROUND_DOWN, ROUND_UP, Context, localcontext
from fractions import Fraction as F
from pathlib import Path

import pytest

import app.model_v2.costing_wf09b_candidate.contracts as contracts
from app.model_v2.costing_wf09b_candidate import (
    REFERENCE_PARITY, UNAVAILABLE, CANDIDATE, AugmentationEvidence, ChargingEvidence, Component,
    CostLine, CostReceipts, CostingRequest, DiscountReceipt, EnergyBoundary, EnergyLine, EnergyReceipts,
    Freshness, LineKind, Metric, Phase, PeriodAxis, PeriodSpec, PriceBasis, RunIdRef, RunReceipt,
    Treatment, Vertical, Wf09bError, evaluate,
)

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "app" / "model_v2" / "costing_wf09b_candidate"
RUN = RunReceipt("snap-1", "hash-1", "wb-1", "eng-1", "CANONICAL_G2C", Freshness.FRESH, True, "proj-1", "base")
REF = RUN.ref


@pytest.fixture(autouse=True)
def released(monkeypatch):
    """Isolated acceptance fixture: open the candidate gate in memory only."""
    monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)


# ── builders ────────────────────────────────────────────────────────────────

SOLAR_PERIODS = [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 12, 31)),
                 ("o1", Phase.OPERATING, date(2026, 12, 31), date(2027, 12, 31)),
                 ("o2", Phase.OPERATING, date(2027, 12, 31), date(2028, 12, 31))]       # 2028 is a leap year


def axis(periods=SOLAR_PERIODS, run=REF):
    return PeriodAxis(run, tuple(PeriodSpec(*p) for p in periods))


class Costs:
    """Collects cost lines; every (period, component) gets an explicit line (0 by default)."""

    def __init__(self, periods=("c0", "o1", "o2")):
        self.periods, self.lines, self.n = periods, [], 0

    def add(self, kind, period, amount, origin=None, treatment=Treatment.ATTRIBUTED, contains=()):
        self.n += 1
        self.lines.append(CostLine(f"L{self.n}", origin or f"O{self.n}", kind, period,
                                   None if amount is None else D(amount), treatment, f"src-{self.n}", contains))
        return self

    def zero_fill(self, kinds):
        have = {(ln.period_id, ln.kind) for ln in self.lines if ln.treatment is Treatment.ATTRIBUTED}
        for p in self.periods:
            for k in kinds:
                if (p, k) not in have and not any(ln.period_id == p and ln.component is ln_comp(k)
                                                  and ln.treatment is Treatment.ATTRIBUTED for ln in self.lines):
                    self.add(k, p, "0", origin=f"zero-{k.value}-{p}")
        return self

    def receipts(self, run=REF, basis=PriceBasis.NOMINAL):
        return CostReceipts(run, basis, tuple(self.lines))


def ln_comp(kind):
    from app.model_v2.costing_wf09b_candidate.contracts import KIND_COMPONENT
    return KIND_COMPONENT[kind]


UNLEV = (LineKind.DEVEX_COST, LineKind.CONSTRUCTION_CAPEX, LineKind.OPERATING_OPEX)
LEV = UNLEV + (LineKind.FINANCING_INTEREST, LineKind.CASH_TAX_PAID)


def energy(values, boundary=EnergyBoundary.DELIVERED_AC_EXPORT, run=REF, ids=("c0", "o1", "o2")):
    return EnergyReceipts(run, tuple(EnergyLine(f"E-{p}", p, boundary, None if v is None else D(v), f"meter-{p}")
                                     for p, v in zip(ids, values)))


def discount(factors, convention="synthetic supplied factors", rate_source="synthetic receipt",
             run=REF, basis=PriceBasis.NOMINAL, ids=("c0", "o1", "o2"), currency="EUR"):
    return DiscountReceipt(run, convention, rate_source, currency, basis, date(2026, 1, 1),
                           tuple((p, D(f)) for p, f in zip(ids, factors)), "disc-receipt")


def request(costs, en, disc, ax=None, vertical=Vertical.SOLAR, metric=Metric.UNLEVERED_PRE_FINANCING, **kw):
    return CostingRequest(vertical, metric, kw.pop("run", RUN), ax or axis(), costs, en, disc, **kw)


def solar_costs(levered=False):
    c = Costs()
    c.add(LineKind.DEVEX_COST, "c0", "100").add(LineKind.CONSTRUCTION_CAPEX, "c0", "1000")
    c.add(LineKind.OPERATING_OPEX, "o1", "50").add(LineKind.OPERATING_OPEX, "o2", "50")
    if levered:
        c.add(LineKind.FINANCING_INTEREST, "o1", "40").add(LineKind.FINANCING_INTEREST, "o2", "30")
        c.add(LineKind.CASH_TAX_PAID, "o1", "20").add(LineKind.CASH_TAX_REFUND, "o2", "-5")
    return c.zero_fill(LEV if levered else UNLEV)


def eur_mwh(numerator_keur, pv_energy):
    return F(numerator_keur) * 1000 / F(pv_energy)


def close(value, fraction):
    return abs(F(value) - fraction) < F(1, 10 ** 40)


# ── 1/2. Solar and Wind unlevered LCOE ──────────────────────────────────────


class TestUnleveredLcoe:
    def test_solar_hand_calculated(self):
        # PV costs: devex 100 + capex 1000 + opex 50*0.9 + 50*0.8 = 85 -> 1185 ; PV energy 2000*0.9 + 2000*0.8 = 3400
        r = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        assert r.status == CANDIDATE
        assert r.numerator_keur == 1185 and r.pv_energy_mwh == 3400
        assert close(r.total_eur_mwh, eur_mwh(1185, 3400))             # 348.5294117647...
        assert r.pv_components_keur == (D(100), D(1000), D(85), D(0), D(0))
        assert close(r.components_eur_mwh[0], eur_mwh(100, 3400))

    def test_wind_hand_calculated_with_a_stub_operating_period(self):
        periods = [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 12, 31)),
                   ("o1", Phase.OPERATING, date(2026, 12, 31), date(2027, 12, 31)),
                   ("o2", Phase.OPERATING, date(2027, 12, 31), date(2028, 12, 31)),
                   ("o3", Phase.OPERATING, date(2028, 12, 31), date(2029, 7, 1))]       # stub
        ids = ("c0", "o1", "o2", "o3")
        c = Costs(ids)
        c.add(LineKind.DEVEX_COST, "c0", "200").add(LineKind.CONSTRUCTION_CAPEX, "c0", "3000")
        for p, a in (("o1", "120"), ("o2", "120"), ("o3", "60")):
            c.add(LineKind.OPERATING_OPEX, p, a)
        c.zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["0", "6000", "5800", "2900"], ids=ids),
                             discount(["1", "0.95", "0.90", "0.85"], ids=ids), ax=axis(periods),
                             vertical=Vertical.WIND))
        # costs 3200 + 114 + 108 + 51 = 3473 ; energy 5700 + 5220 + 2465 = 13385
        assert r.numerator_keur == 3473 and r.pv_energy_mwh == 13385
        assert close(r.total_eur_mwh, eur_mwh(3473, 13385))

    def test_exact_keur_to_eur_per_mwh_conversion(self):
        p = [("o1", Phase.OPERATING, date(2027, 1, 1), date(2027, 12, 31))]
        c = Costs(("o1",)).add(LineKind.OPERATING_OPEX, "o1", "1").zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["1"], ids=("o1",)), discount(["1"], ids=("o1",)), ax=axis(p)))
        assert r.total_eur_mwh == 1000                              # 1 kEUR / 1 MWh = 1000 EUR/MWh exactly
        c = Costs(("o1",)).add(LineKind.OPERATING_OPEX, "o1", "2.5").zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["4"], ids=("o1",)), discount(["1"], ids=("o1",)), ax=axis(p)))
        assert r.total_eur_mwh == 625


# ── 3. levered vs unlevered attribution ─────────────────────────────────────


class TestLeveredAttribution:
    def test_levered_adds_financing_and_cash_tax_to_the_same_denominator(self):
        # finance 40*0.9 + 30*0.8 = 60 ; tax 20*0.9 + (-5)*0.8 = 14 ; numerator 1185 + 60 + 14 = 1259
        r = evaluate(request(solar_costs(True).receipts(), energy(["0", "2000", "2000"]),
                             discount(["1", "0.9", "0.8"]), metric=Metric.LEVERED_AFTER_TAX))
        assert r.status == CANDIDATE and r.numerator_keur == 1259 and r.pv_energy_mwh == 3400
        assert r.pv_components_keur == (D(100), D(1000), D(85), D(60), D(14))
        assert close(r.total_eur_mwh, eur_mwh(1259, 3400))
        assert close(sum(F(x) for x in r.components_eur_mwh), eur_mwh(1259, 3400))
        assert r.reconciliation.numerator_equals_attributed_discounted_lines

    def test_the_unlevered_metric_refuses_attributed_finance_or_tax(self):
        with pytest.raises(Wf09bError, match="WF09B_UNLEVERED_EXCLUDES_FINANCE_TAX"):
            evaluate(request(solar_costs(True).receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))

    def test_finance_and_tax_can_be_recorded_as_excluded_memo_lines_for_the_unlevered_metric(self):
        c = solar_costs()
        c.add(LineKind.FINANCING_INTEREST, "o1", "40", treatment=Treatment.EXCLUDED_MOVEMENT)
        r = evaluate(request(c.receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        assert r.numerator_keur == 1185 and len(r.reconciliation.excluded_movement_line_ids) == 1


# ── 5/12/13. timing, period lengths, leap years ─────────────────────────────


class TestTimingAndPeriodAxis:
    def test_construction_capex_is_discounted_where_it_is_spent_not_collapsed_to_year_zero(self):
        periods = [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 7, 1)),
                   ("c1", Phase.CONSTRUCTION, date(2026, 7, 1), date(2027, 4, 1)),
                   ("o1", Phase.OPERATING, date(2027, 4, 1), date(2028, 4, 1))]
        ids = ("c0", "c1", "o1")
        c = Costs(ids).add(LineKind.CONSTRUCTION_CAPEX, "c0", "600").add(LineKind.CONSTRUCTION_CAPEX, "c1", "400")
        c.add(LineKind.OPERATING_OPEX, "o1", "10").zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["0", "0", "1000"], ids=ids),
                             discount(["1", "0.95", "0.9"], ids=ids), ax=axis(periods)))
        assert r.pv_components_keur[1] == D(980)                      # 600 + 400*0.95, not 1000
        assert r.numerator_keur == D(989) and close(r.total_eur_mwh, eur_mwh(989, 900))

    def test_different_construction_and_operating_period_lengths_do_not_change_supplied_amounts(self):
        short = [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 7, 2)),        # 182 days
                 ("c1", Phase.CONSTRUCTION, date(2026, 7, 2), date(2027, 4, 1)),        # 273 days
                 ("o1", Phase.OPERATING, date(2027, 4, 1), date(2027, 6, 30)),          # 90 days
                 ("o2", Phase.OPERATING, date(2027, 6, 30), date(2028, 6, 30))]         # 366 days
        ids = ("c0", "c1", "o1", "o2")
        c = Costs(ids).add(LineKind.CONSTRUCTION_CAPEX, "c0", "500").add(LineKind.CONSTRUCTION_CAPEX, "c1", "500")
        c.add(LineKind.OPERATING_OPEX, "o1", "5").add(LineKind.OPERATING_OPEX, "o2", "20").zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["0", "0", "100", "400"], ids=ids),
                             discount(["1", "0.97", "0.95", "0.9"], ids=ids), ax=axis(short)))
        # capex 500 + 485 = 985 ; opex 4.75 + 18 = 22.75 -> 1007.75 ; energy 95 + 360 = 455
        assert r.numerator_keur == D("1007.75") and r.pv_energy_mwh == 455
        assert close(r.total_eur_mwh, eur_mwh(D("1007.75"), 455))

    def test_leap_day_and_nonstandard_boundaries_are_accepted_when_contiguous(self):
        p = [("c0", Phase.CONSTRUCTION, date(2027, 12, 31), date(2028, 2, 29)),
             ("o1", Phase.OPERATING, date(2028, 2, 29), date(2028, 3, 1)),               # 1-day stub across the leap day
             ("o2", Phase.OPERATING, date(2028, 3, 1), date(2029, 2, 28))]
        ids = ("c0", "o1", "o2")
        c = Costs(ids).add(LineKind.CONSTRUCTION_CAPEX, "c0", "10").add(LineKind.OPERATING_OPEX, "o1", "1")
        c.add(LineKind.OPERATING_OPEX, "o2", "2").zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["0", "10", "30"], ids=ids), discount(["1", "1", "1"], ids=ids), ax=axis(p)))
        assert r.numerator_keur == 13 and r.pv_energy_mwh == 40

    @pytest.mark.parametrize("bad", [
        [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 12, 31)), ("o1", Phase.OPERATING, date(2027, 1, 1), date(2027, 12, 31))],  # gap
        [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 12, 31)), ("o1", Phase.OPERATING, date(2026, 12, 30), date(2027, 12, 31))],  # overlap
        [("o1", Phase.OPERATING, date(2026, 1, 1), date(2026, 12, 31)), ("c0", Phase.CONSTRUCTION, date(2026, 12, 31), date(2027, 6, 1))],   # order
        [("c0", Phase.CONSTRUCTION, date(2026, 12, 31), date(2026, 1, 1))],                                                                   # negative
    ])
    def test_misaligned_period_axes_are_rejected(self, bad):
        with pytest.raises(Wf09bError, match="WF09B_PERIOD_ALIGNMENT"):
            axis(bad)

    def test_receipts_must_name_periods_on_the_axis(self):
        c = solar_costs().add(LineKind.OPERATING_OPEX, "ghost", "1")
        with pytest.raises(Wf09bError, match="WF09B_PERIOD_ALIGNMENT"):
            evaluate(request(c.receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        with pytest.raises(Wf09bError, match="WF09B_PERIOD_ALIGNMENT"):
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]),
                             discount(["1", "0.9", "0.8", "0.7"], ids=("c0", "o1", "o2", "zz"))))


# ── 6/7/8. duplicate origins, IDC / financing, tax ──────────────────────────


class TestNoDoubleCounting:
    def test_devex_capitalised_into_capex_counts_once(self):
        c = Costs()
        c.add(LineKind.DEVEX_COST, "c0", "100", origin="devex-permits", treatment=Treatment.EXCLUDED_MOVEMENT)
        c.add(LineKind.CONSTRUCTION_CAPEX, "c0", "1100", origin="capex-total", contains=("devex-permits",))
        c.add(LineKind.DEVEX_COST, "c0", "0", origin="devex-zero")
        c.add(LineKind.OPERATING_OPEX, "o1", "50").add(LineKind.OPERATING_OPEX, "o2", "50").zero_fill(UNLEV)
        r = evaluate(request(c.receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        assert r.numerator_keur == 1185                        # identical to the un-capitalised case, not 1285

    def test_the_same_devex_origin_attributed_in_devex_and_capex_is_rejected(self):
        c = Costs().add(LineKind.DEVEX_COST, "c0", "100", origin="devex-permits")
        with pytest.raises(Wf09bError, match="WF09B_DOUBLE_COUNT"):
            c.add(LineKind.CONSTRUCTION_CAPEX, "c0", "1100", origin="capex-total", contains=("devex-permits",)).receipts()
        c2 = Costs().add(LineKind.DEVEX_COST, "c0", "100", origin="same")
        c2.add(LineKind.CONSTRUCTION_CAPEX, "c0", "1000", origin="same")
        with pytest.raises(Wf09bError, match="WF09B_DUPLICATE"):
            c2.receipts()

    def test_idc_capitalised_into_capex_and_attributed_as_financing_is_rejected(self):
        c = Costs().add(LineKind.IDC, "c0", "80", origin="idc-2026")
        with pytest.raises(Wf09bError, match="WF09B_DOUBLE_COUNT"):
            c.add(LineKind.CONSTRUCTION_CAPEX, "c0", "1080", origin="capex-with-idc", contains=("idc-2026",)).receipts()

    def test_a_cost_cannot_be_contained_by_two_lines(self):
        c = Costs().add(LineKind.CONSTRUCTION_CAPEX, "c0", "10", origin="a", contains=("x",))
        with pytest.raises(Wf09bError, match="WF09B_DUPLICATE"):
            c.add(LineKind.CONSTRUCTION_CAPEX, "c0", "10", origin="b", contains=("x",)).receipts()

    @pytest.mark.parametrize("kind", [LineKind.PRINCIPAL_REPAYMENT, LineKind.DEBT_DRAWDOWN, LineKind.EQUITY_FUNDING,
                                      LineKind.RESERVE_FUNDING, LineKind.DEPRECIATION, LineKind.ACCOUNTING_TAX_EXPENSE,
                                      LineKind.NET_ARBITRAGE_SPREAD, LineKind.DISTRIBUTION])
    def test_a_cash_movement_or_non_cash_item_never_becomes_a_cost(self, kind):
        with pytest.raises(Wf09bError, match="WF09B_CASH_MOVEMENT_NOT_COST"):
            CostLine("L", "O", kind, "o1", D(10), Treatment.ATTRIBUTED, "src")
        CostLine("L", "O", kind, "o1", D(10), Treatment.EXCLUDED_MOVEMENT, "src")        # recordable as a memo only

    def test_principal_and_reserve_funding_memos_leave_the_numerator_unchanged(self):
        c = solar_costs(True)
        c.add(LineKind.PRINCIPAL_REPAYMENT, "o1", "300", treatment=Treatment.EXCLUDED_MOVEMENT)
        c.add(LineKind.RESERVE_FUNDING, "c0", "90", treatment=Treatment.EXCLUDED_MOVEMENT)
        c.add(LineKind.DEPRECIATION, "o1", "70", treatment=Treatment.EXCLUDED_MOVEMENT)
        r = evaluate(request(c.receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                             metric=Metric.LEVERED_AFTER_TAX))
        assert r.numerator_keur == 1259 and len(r.reconciliation.excluded_movement_line_ids) == 3

    def test_cash_tax_paid_and_refund_are_signed_and_accounting_tax_is_not_a_cash_cost(self):
        with pytest.raises(Wf09bError, match="WF09B_TAX_REFUND_SIGN"):
            CostLine("L", "O", LineKind.CASH_TAX_REFUND, "o1", D(5), Treatment.ATTRIBUTED, "s")
        with pytest.raises(Wf09bError, match="WF09B_NEGATIVE_COST"):
            CostLine("L", "O", LineKind.OPERATING_OPEX, "o1", D(-5), Treatment.ATTRIBUTED, "s")
        base = evaluate(request(solar_costs(True).receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                                metric=Metric.LEVERED_AFTER_TAX))
        assert base.pv_components_keur[4] == D(14)                       # 20*0.9 - 5*0.8: the refund reduces PV tax


# ── 9/10/16. missing evidence vs explicit zero ──────────────────────────────


class TestMissingEvidence:
    def _eval(self, costs, en=None, disc=None, **kw):
        return evaluate(request(costs.receipts(), en or energy(["0", "2000", "2000"]), disc or discount(["1", "0.9", "0.8"]), **kw))

    def test_a_missing_amount_is_unavailable_and_an_explicit_zero_is_a_zero(self):
        c = solar_costs()
        c.lines[3] = CostLine("Lx", "Ox", LineKind.OPERATING_OPEX, "o1", None, Treatment.ATTRIBUTED, "s")
        c.lines[3] = CostLine(c.lines[3].line_id, c.lines[3].origin_id, LineKind.OPERATING_OPEX, "o1", None, Treatment.ATTRIBUTED, "s")
        r = self._eval(c)
        assert r.status == UNAVAILABLE and "WF09B_COST_AMOUNT_MISSING" in r.reasons and r.total_eur_mwh is None
        z = Costs().add(LineKind.OPERATING_OPEX, "o1", "0").add(LineKind.OPERATING_OPEX, "o2", "0").zero_fill(UNLEV)
        r = self._eval(z)
        assert r.status == CANDIDATE and r.total_eur_mwh == 0           # a legitimate zero, not UNAVAILABLE

    def test_an_absent_component_is_unavailable_not_zero(self):
        c = Costs().add(LineKind.CONSTRUCTION_CAPEX, "c0", "1000").add(LineKind.OPERATING_OPEX, "o1", "50")
        r = self._eval(c)       # no DEVEX at all and no OPEX line for o2
        assert r.status == UNAVAILABLE and r.reasons == ("WF09B_COMPONENT_EVIDENCE_MISSING",)

    def test_levered_requires_finance_and_tax_evidence_every_period(self):
        r = self._eval(solar_costs(), metric=Metric.LEVERED_AFTER_TAX)
        assert r.status == UNAVAILABLE and r.reasons == ("WF09B_COMPONENT_EVIDENCE_MISSING",)

    @pytest.mark.parametrize("change,reason", [({"convention": None}, "WF09B_DISCOUNT_CONVENTION_MISSING"),
                                               ({"rate_source": None}, "WF09B_DISCOUNT_RATE_SOURCE_MISSING")])
    def test_missing_discount_convention_or_rate_source(self, change, reason):
        r = self._eval(solar_costs(), disc=discount(["1", "0.9", "0.8"], **change))
        assert r.status == UNAVAILABLE and r.reasons == (reason,)

    def test_a_missing_discount_factor_is_unavailable_and_never_defaulted_to_one(self):
        r = self._eval(solar_costs(), disc=discount(["1", "0.9"], ids=("c0", "o1")))
        assert r.status == UNAVAILABLE and r.reasons == ("WF09B_DISCOUNT_FACTOR_MISSING",)

    def test_missing_or_absent_energy_is_unavailable_but_explicit_zero_energy_is_allowed_in_construction(self):
        assert self._eval(solar_costs(), en=energy(["0", None, "2000"])).reasons == ("WF09B_ENERGY_EVIDENCE_MISSING",)
        partial = EnergyReceipts(REF, energy(["0", "2000", "2000"]).lines[:2])
        assert self._eval(solar_costs(), en=partial).reasons == ("WF09B_ENERGY_EVIDENCE_MISSING",)
        assert self._eval(solar_costs()).status == CANDIDATE              # construction energy 0 is evidenced

    def test_zero_delivered_energy_is_unavailable_never_an_infinite_or_zero_price(self):
        r = self._eval(solar_costs(), en=energy(["0", "0", "0"]))
        assert r.status == UNAVAILABLE and r.total_eur_mwh is None
        assert any("no positive discounted delivered energy" in x for x in r.reasons)

    def test_run_freshness_and_completeness_gate_the_result(self):
        stale = RunReceipt("snap-1", "hash-1", "wb-1", "eng-1", "CANONICAL_G2C", Freshness.STALE, True)
        incomplete = RunReceipt("snap-1", "hash-1", "wb-1", "eng-1", "CANONICAL_G2C", Freshness.FRESH, False)
        assert self._eval(solar_costs(), run=stale).reasons == ("WF09B_RUN_NOT_FRESH",)
        assert self._eval(solar_costs(), run=incomplete).reasons == ("WF09B_RUN_EVIDENCE_INCOMPLETE",)


# ── 11. discounted energy denominator ───────────────────────────────────────


class TestDiscountedEnergyDenominator:
    def test_energy_is_discounted_with_the_same_factors_as_costs(self):
        r = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        assert r.pv_energy_mwh == 3400 != 4000
        undiscounted = eur_mwh(1185, 4000)
        assert abs(F(r.total_eur_mwh) - undiscounted) > 1          # the undiscounted-energy formula is a different number
        assert r.reconciliation.discounted_energy_equals_receipts


# ── 14/15. BESS LCOS ────────────────────────────────────────────────────────


BESS_IDS = ("c0", "o1")
BESS_AXIS = [("c0", Phase.CONSTRUCTION, date(2026, 1, 1), date(2026, 12, 31)),
             ("o1", Phase.OPERATING, date(2026, 12, 31), date(2027, 12, 31))]


def bess_costs(charging=True):
    c = Costs(BESS_IDS).add(LineKind.DEVEX_COST, "c0", "20").add(LineKind.CONSTRUCTION_CAPEX, "c0", "500")
    c.add(LineKind.OPERATING_OPEX, "o1", "15").add(LineKind.GRID_IMPORT_CHARGE, "o1", "5")
    if charging:
        c.add(LineKind.CHARGING_ELECTRICITY_PAID, "o1", "80")
    return c.zero_fill((LineKind.FINANCING_INTEREST, LineKind.CASH_TAX_PAID, LineKind.DEVEX_COST,
                        LineKind.CONSTRUCTION_CAPEX, LineKind.OPERATING_OPEX))


def bess_request(costs, **kw):
    kw.setdefault("charging", ChargingEvidence.EXPLICIT_BUY)
    kw.setdefault("augmentation", AugmentationEvidence.NOT_APPLICABLE_EVIDENCED)
    return request(costs.receipts(), energy(["0", "600"], EnergyBoundary.DELIVERED_AC_DISCHARGE, ids=BESS_IDS),
                   discount(["1", "0.9"], ids=BESS_IDS), ax=axis(BESS_AXIS), vertical=Vertical.BESS,
                   metric=Metric.LCOS, **kw)


class TestBessLcos:
    def test_explicit_paid_charging_cost_is_counted_once_in_opex(self):
        # costs 20 + 500 + (15 + 5 + 80)*0.9 = 90 -> 610 ; discharged energy 600*0.9 = 540
        r = evaluate(bess_request(bess_costs()))
        assert r.status == CANDIDATE and r.numerator_keur == 610 and r.pv_energy_mwh == 540
        assert close(r.total_eur_mwh, eur_mwh(610, 540))
        assert r.pv_components_keur[2] == D(90)

    def test_net_spread_only_evidence_is_rejected(self):
        r = evaluate(bess_request(bess_costs(charging=False), charging=ChargingEvidence.NET_SPREAD))
        assert r.status == UNAVAILABLE and r.reasons == ("WF09B_LCOS_NET_SPREAD_ONLY",)
        c = bess_costs(charging=False).add(LineKind.NET_ARBITRAGE_SPREAD, "o1", "30", treatment=Treatment.EXCLUDED_MOVEMENT)
        r = evaluate(bess_request(c))
        assert r.status == UNAVAILABLE and r.reasons == ("WF09B_LCOS_NET_SPREAD_ONLY",)

    def test_a_net_spread_memo_next_to_an_explicit_buy_does_not_change_the_cost(self):
        c = bess_costs().add(LineKind.NET_ARBITRAGE_SPREAD, "o1", "30", treatment=Treatment.EXCLUDED_MOVEMENT)
        assert evaluate(bess_request(c)).numerator_keur == 610
        with pytest.raises(Wf09bError, match="WF09B_CASH_MOVEMENT_NOT_COST"):
            CostLine("L", "O", LineKind.NET_ARBITRAGE_SPREAD, "o1", D(30), Treatment.ATTRIBUTED, "s")

    def test_no_charging_evidence_at_all_is_unavailable(self):
        r = evaluate(bess_request(bess_costs(charging=False), charging=ChargingEvidence.EXPLICIT_BUY))
        assert r.reasons == ("WF09B_LCOS_CHARGING_COST_MISSING",)
        r = evaluate(bess_request(bess_costs(), charging=ChargingEvidence.NOT_APPLICABLE))
        assert r.reasons == ("WF09B_LCOS_CHARGING_COST_MISSING",)

    def test_rte_or_loss_haircuts_cannot_be_applied_on_top_of_measured_discharge(self):
        with pytest.raises(Wf09bError, match="WF09B_SYNTHETIC_ENERGY_ADJUSTMENT"):
            EnergyLine("E", "o1", EnergyBoundary.DELIVERED_AC_DISCHARGE, D(600), "meter", generic_adjustment_factor=D("0.85"))

    def test_the_delivered_energy_boundary_must_match_the_vertical(self):
        with pytest.raises(Wf09bError, match="WF09B_ENERGY_BOUNDARY_MISMATCH"):
            evaluate(request(bess_costs().receipts(), energy(["0", "600"], EnergyBoundary.DELIVERED_AC_EXPORT, ids=BESS_IDS),
                             discount(["1", "0.9"], ids=BESS_IDS), ax=axis(BESS_AXIS), vertical=Vertical.BESS,
                             metric=Metric.LCOS, charging=ChargingEvidence.EXPLICIT_BUY,
                             augmentation=AugmentationEvidence.NOT_APPLICABLE_EVIDENCED))

    def test_augmentation_and_lifecycle_replacement_capex_stay_unavailable(self):
        assert evaluate(bess_request(bess_costs(), augmentation=AugmentationEvidence.UNKNOWN)).reasons \
            == ("WF09B_AUGMENTATION_UNAPPROVED",)
        for kind in (LineKind.AUGMENTATION_CAPEX, LineKind.REPLACEMENT_CAPEX):
            c = bess_costs().add(kind, "o1", "100")
            assert evaluate(bess_request(c)).reasons == ("WF09B_AUGMENTATION_UNAPPROVED",)

    def test_charging_kinds_do_not_apply_outside_bess_and_lcos_belongs_to_bess(self):
        c = solar_costs().add(LineKind.CHARGING_ELECTRICITY_PAID, "o1", "5")
        with pytest.raises(Wf09bError, match="WF09B_KIND_NOT_APPLICABLE"):
            evaluate(request(c.receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        r = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                             metric=Metric.LCOS))
        assert r.reasons == ("WF09B_METRIC_NOT_SUPPORTED_FOR_VERTICAL",)
        with pytest.raises(Wf09bError, match="WF09B_CHARGING_BELONGS_TO_LCOS"):
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                             charging=ChargingEvidence.EXPLICIT_BUY))

    @pytest.mark.parametrize("vertical", [Vertical.DATA_CENTER, Vertical.EV_CHARGING])
    def test_verticals_without_an_approved_physical_denominator_are_unavailable(self, vertical):
        r = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                             vertical=vertical))
        assert r.status == UNAVAILABLE and r.reasons == ("WF09B_VERTICAL_DENOMINATOR_NOT_APPROVED",)


# ── 17/18. duplicate identity, Run identity, alignment ──────────────────────


class TestIdentityAndAlignment:
    def test_duplicate_source_line_identities_are_rejected(self):
        c = Costs().add(LineKind.OPERATING_OPEX, "o1", "1", origin="a")
        c.lines.append(CostLine("L1", "b", LineKind.OPERATING_OPEX, "o2", D(1), Treatment.ATTRIBUTED, "s"))   # reuses line id L1
        with pytest.raises(Wf09bError, match="WF09B_DUPLICATE"):
            c.receipts()
        with pytest.raises(Wf09bError, match="WF09B_DUPLICATE"):
            EnergyReceipts(REF, (EnergyLine("E", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(1), "s"),
                                 EnergyLine("E", "o2", EnergyBoundary.DELIVERED_AC_EXPORT, D(1), "s")))
        with pytest.raises(Wf09bError, match="WF09B_DUPLICATE"):
            EnergyReceipts(REF, (EnergyLine("E1", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(1), "s"),
                                 EnergyLine("E2", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(1), "s")))
        with pytest.raises(Wf09bError, match="WF09B_DUPLICATE"):
            DiscountReceipt(REF, "c", "r", "EUR", PriceBasis.NOMINAL, None, (("o1", D(1)), ("o1", D(1))), "s")

    @pytest.mark.parametrize("which", ["axis", "costs", "energy", "discount"])
    def test_every_receipt_must_belong_to_the_same_run(self, which):
        other = RunIdRef("snap-2", "hash-1")
        parts = dict(ax=axis(), costs=solar_costs().receipts(), en=energy(["0", "2000", "2000"]),
                     disc=discount(["1", "0.9", "0.8"]))
        parts[{"axis": "ax", "costs": "costs", "energy": "en", "discount": "disc"}[which]] = {
            "axis": axis(run=other), "costs": solar_costs().receipts(run=other),
            "energy": energy(["0", "2000", "2000"], run=other), "discount": discount(["1", "0.9", "0.8"], run=other)}[which]
        with pytest.raises(Wf09bError, match="WF09B_RUN_IDENTITY_MISMATCH"):
            evaluate(request(parts["costs"], parts["en"], parts["disc"], ax=parts["ax"]))
        with pytest.raises(Wf09bError, match="WF09B_RUN_IDENTITY_MISMATCH"):      # a different composite hash is also a mismatch
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                             run=RunReceipt("snap-1", "hash-X", "wb-1", "eng-1", "CANONICAL_G2C", Freshness.FRESH, True)))

    def test_currency_and_price_basis_must_be_consistent(self):
        with pytest.raises(Wf09bError, match="WF09B_CURRENCY"):
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"], currency="USD")))
        with pytest.raises(Wf09bError, match="WF09B_BASIS_MISMATCH"):
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]),
                             discount(["1", "0.9", "0.8"], basis=PriceBasis.REAL)))

    def test_receipt_types_are_strict(self):
        for bad in (1.5, "1", True):
            with pytest.raises(Wf09bError, match="WF09B_VALUE"):
                CostLine("L", "O", LineKind.OPERATING_OPEX, "o1", bad, Treatment.ATTRIBUTED, "s")
        with pytest.raises(Wf09bError, match="WF09B_VALUE"):
            DiscountReceipt(REF, "c", "r", "EUR", PriceBasis.NOMINAL, None, (("o1", D(0)),), "s")
        with pytest.raises(Wf09bError, match="WF09B_IDENTITY"):
            RunReceipt(" ", "h", "w", "e", "a", Freshness.FRESH, True)

    def test_energy_breakdown_is_only_accepted_from_actual_reconciling_evidence(self):
        ok = EnergyLine("E", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(90), "m", D(100), D(4), D(5), D(1))
        assert ok.delivered_mwh == 90
        with pytest.raises(Wf09bError, match="WF09B_ENERGY_BREAKDOWN_MISMATCH"):
            EnergyLine("E", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(91), "m", D(100), D(4), D(5), D(1))
        with pytest.raises(Wf09bError, match="WF09B_ENERGY_BREAKDOWN_INCOMPLETE"):
            EnergyLine("E", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(90), "m", D(100), D(4))
        with pytest.raises(Wf09bError, match="WF09B_ENERGY_BREAKDOWN_INCOMPLETE"):
            EnergyLine("E", "o1", EnergyBoundary.DELIVERED_AC_EXPORT, D(90), "m", None, D(4), D(5), D(1))


class TestReconciliationIsEnforced:
    """The layer re-derives every figure from the receipts; a tampered WF-09A result must fail closed."""

    @pytest.mark.parametrize("field,delta", [("numerator_keur", D("1e-9")), ("pv_energy_mwh", D("1e-9")),
                                             ("pv_components_keur", None), ("total_eur_mwh", D("1e-6"))])
    def test_a_result_that_does_not_reconcile_with_the_receipts_is_rejected(self, monkeypatch, field, delta):
        from dataclasses import replace
        import app.model_v2.costing_wf09b_candidate.engine as eng
        real = eng.wf09a.calculate

        def tampered(rows, basis):
            res = real(rows, basis)
            if field == "pv_components_keur":
                comps = list(res.pv_components_keur)
                comps[0] += D("1e-9")
                return replace(res, pv_components_keur=tuple(comps))
            return replace(res, **{field: getattr(res, field) + delta})

        monkeypatch.setattr(eng.wf09a, "calculate", tampered)
        with pytest.raises(Wf09bError, match="WF09B_RECONCILIATION_FAILED"):
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))

    def test_an_honest_result_reports_every_reconciliation_flag_true(self):
        r = evaluate(request(solar_costs(True).receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                             metric=Metric.LEVERED_AFTER_TAX))
        rec = r.reconciliation
        assert (rec.numerator_equals_attributed_discounted_lines, rec.components_equal_attributed_discounted_lines,
                rec.discounted_energy_equals_receipts, rec.component_quotients_sum_to_total) == (True,) * 4
        assert rec.max_component_sum_difference <= contracts.COMPONENT_SUM_TOLERANCE
        assert len(rec.attributed_line_ids) == len(set(rec.attributed_line_ids))     # every source line identity unique


# ── 19. ambient precision independence and determinism ──────────────────────


class TestPrecisionAndDeterminism:
    def test_results_do_not_depend_on_the_callers_decimal_context(self):
        req = request(solar_costs(True).receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"]),
                      metric=Metric.LEVERED_AFTER_TAX)
        with localcontext(Context(prec=3, rounding=ROUND_UP)):
            low = evaluate(req)
        with localcontext(Context(prec=80, rounding=ROUND_DOWN)):
            high = evaluate(req)
        assert low == high and low.provenance == high.provenance and len(low.provenance) == 64

    def test_different_evidence_changes_the_provenance(self):
        a = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        b = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2001"]), discount(["1", "0.9", "0.8"])))
        assert a.provenance != b.provenance

    def test_decimal_representation_does_not_leak_into_the_identity(self):
        from app.model_v2.costing_wf09b_candidate import identity
        with localcontext(Context(prec=2)):
            assert identity(D("12345.678")) == identity(D("12345.678"))
        assert identity(D("0")) == identity(D("0.000"))


# ── 20. release closure, isolation, zero change to canonical outputs ────────


PINS = {
    "research/wf09a/costing.py": None,       # filled from main below
    "domain/analytics/lcoe.py": None,
    "app/model_v2/canonical_analytics.py": None,
    "financial_engine/orchestrator.py": None,
    "financial_engine/tax/engine.py": None,
    "financial_engine/bess.py": None,
}


def _main_blob(path):
    out = subprocess.run(["git", "rev-parse", f"origin/main:{path}"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("origin/main is not available in this checkout")
    return out.stdout.strip()


class TestReleaseClosureAndZeroRegression:
    def test_the_gate_is_a_literal_false_and_fails_closed(self, monkeypatch):
        tree = ast.parse((PKG / "contracts.py").read_text(encoding="utf-8"))
        assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ACTIVATION_ENABLED" for t in n.targets)]
        assert len(assigns) == 1 and isinstance(assigns[0].value, ast.Constant) and assigns[0].value.value is False
        monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", False)
        with pytest.raises(Wf09bError, match="WF09B_RELEASE_CLOSED"):
            evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))

    def test_no_environment_variable_can_enable_the_package(self, monkeypatch):
        for name in ("ACTIVATION_ENABLED", "FINCO_WF09B", "WF09B_ENABLED"):
            monkeypatch.setenv(name, "1")
        out = subprocess.run([sys.executable, "-c",
                              "import app.model_v2.costing_wf09b_candidate.contracts as c;print(c.ACTIVATION_ENABLED)"],
                             cwd=ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == "False"

    def test_the_result_is_non_authoritative_and_reference_parity_is_not_claimed(self):
        r = evaluate(request(solar_costs().receipts(), energy(["0", "2000", "2000"]), discount(["1", "0.9", "0.8"])))
        assert r.non_authoritative is True and r.authority == "WF09B_COST_RECEIPTS_CANDIDATE_V0"
        assert REFERENCE_PARITY == "NOT_ASSESSED_MISSING_LINE_LEVEL_EVIDENCE"

    def test_the_only_formula_is_the_wf09a_arithmetic(self):
        src = (PKG / "engine.py").read_text(encoding="utf-8")
        assert "wf09a.calculate(" in src and "* 1000" not in src and "/ 1000" not in src
        tree = ast.parse(src)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "wf09a" not in {a.id for a in ast.walk(tree) if isinstance(a, ast.Name) and isinstance(a.ctx, ast.Store)}

    def test_nothing_outside_the_package_references_it(self):
        bad = []
        for root in ("app", "domain", "financial_engine", "finco_core", "finco_radar", "finco_protocol", "main_web.py",
                     "main_api.py", "main_mcp.py", "static", "frontend/src", "tools", ".github", "deploy", "research"):
            path = ROOT / root
            for f in ([path] if path.is_file() else sorted(path.rglob("*"))):
                if not f.is_file() or f.suffix not in (".py", ".html", ".js", ".ts", ".tsx", ".json", ".yml", ".yaml"):
                    continue
                if "costing_wf09b_candidate" in f.as_posix():
                    continue
                try:
                    if "costing_wf09b_candidate" in f.read_text(encoding="utf-8"):
                        bad.append(f.relative_to(ROOT).as_posix())
                except UnicodeDecodeError:
                    continue
        assert bad == []

    def test_only_the_standard_library_and_wf09a_are_imported_and_no_sibling_candidate(self):
        stdlib = set(sys.stdlib_module_names)
        for f in sorted(PKG.glob("*.py")):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                        else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
                for m in mods:
                    top = m.split(".")[0]
                    assert (top in stdlib or top == "__future__" or m.startswith("app.model_v2.costing_wf09b_candidate")
                            or m.startswith("research.wf09a")), (f.name, m)

    def test_importing_the_candidate_adds_no_engine_web_or_sibling_candidate_module(self):
        code = ("import sys, app.model_v2; before = set(sys.modules); import app.model_v2.costing_wf09b_candidate;"
                "print(sorted(m for m in set(sys.modules) - before if not m.startswith("
                "('app.model_v2.costing_wf09b_candidate','research'))))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        assert out.stdout.strip() == "[]", out.stdout + out.stderr

    @pytest.mark.parametrize("path", sorted(PINS))
    def test_protected_canonical_sources_are_byte_identical_to_main(self, path):
        out = subprocess.run(["git", "hash-object", path], cwd=ROOT, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == _main_blob(path), path

    def test_canonical_analytics_keeps_reporting_lcoe_as_having_no_authority(self):
        import app.model_v2.canonical_analytics as ca
        assert ("lcoe", "UNIT_ECONOMICS", "EUR/MWh") in ca._FUTURE_METRICS
        metric = ca._future_metric("lcoe", "UNIT_ECONOMICS", "EUR/MWh", ca._LCOE_AUTHORITY_NOTE)
        assert metric.status.value == "AUTHORITY_MISSING" and metric.value is None and metric.source_authority is None
        src = (ROOT / "app" / "model_v2" / "canonical_analytics.py").read_text(encoding="utf-8")
        assert 'entries.append(_future_metric("lcoe"' in src
        assert "costing_wf09b" not in src and "wf09a" not in src       # the production layer does not call this candidate
