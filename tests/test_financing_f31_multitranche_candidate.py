"""WF-05A F3.1 multi-tranche candidate — acceptance matrix.

CANDIDATE-ONLY. Proves: package isolation (non-authoritative, import-narrow),
released-rule generalization to N >= 2, hand-computed 3-tranche schedules,
N=2 equivalence with the released engine (1e-9), source/use reconciliation,
and the fail-closed scenario combinations. No canonical output changes.

Acceptance markers:

  F31MT_CANDIDATE_ISOLATION          non-authoritative, import-narrow
  F31MT_VALIDATION_GENERALIZATION    released rules verbatim at N >= 2
  F31MT_SCHEDULES_HAND_COMPUTED      3-tranche ledgers match hand math
  F31MT_N2_EQUIVALENCE               candidate == released engine at N=2
  F31MT_BOUNDARY_TWO_SENIOR          released validator still exactly-2
  F31MT_RECONCILIATION               source/use rules fail closed
  F31MT_SCENARIO_COMBINATIONS        SHL/PIK/mezz/reserve/quarterly rejected
"""
from __future__ import annotations

import ast
import itertools
from datetime import date
from fractions import Fraction
from math import fsum
from pathlib import Path

import pytest

from app.model_v2 import financing_f31_multitranche_candidate as candidate
from finco_core.inputs.financing_instruments import (
    CommitmentAuthority,
    DrawdownEntry,
    FeeKind,
    FeeTerm,
    FinancingCollection,
    FinancingError,
    FinancingInstrument,
    InterestTerms,
    MaturityAuthority,
    RateMode,
    RepaymentMode,
    RepaymentTerms,
)
from finco_core.inputs.multisenior import validate_effective_collection

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "app" / "model_v2" / "financing_f31_multitranche_candidate"

M_A = date(2030, 12, 31)   # operating boundary O2
M_B = date(2031, 12, 31)   # operating boundary O4


def _instrument(instrument_id, commitment, rate, mode, *, grace=0,
                maturity=M_B, draws=None, pik=False, fees=None,
                instrument_type=None, rank=1, authority=None):
    return FinancingInstrument(
        instrument_id=instrument_id,
        instrument_type=instrument_type or __import__(
            "finco_core.inputs.financing_instruments",
            fromlist=["InstrumentType"]).InstrumentType.SENIOR_TERM_LOAN,
        name=f"Tranche {instrument_id}",
        commitment_keur=commitment,
        commitment_authority=CommitmentAuthority.EXPLICIT,
        drawdowns=draws or (DrawdownEntry(date(2029, 2, 1), commitment),),
        interest=InterestTerms(RateMode.FIXED, fixed_rate=rate, pik=pik),
        repayment=RepaymentTerms(mode, grace_months=grace,
                                 maturity_authority=MaturityAuthority.EXPLICIT_DATE,
                                 maturity_date=maturity),
        fees=fees or (FeeTerm(FeeKind.UPFRONT, 0.01),
                      FeeTerm(FeeKind.COMMITMENT, 0.005, "UNDRAWN")),
        seniority_rank=rank,
    )


def _three(mode_a=RepaymentMode.LEVEL_PRINCIPAL):
    return FinancingCollection((
        _instrument("senior-a", 300.0, 0.05, mode_a, maturity=M_A),
        _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET, grace=12,
                    draws=(DrawdownEntry(date(2029, 8, 15), 200.0),)),
        _instrument("senior-c", 100.0, 0.04, RepaymentMode.LEVEL_PRINCIPAL,
                    draws=(DrawdownEntry(date(2029, 3, 1), 60.0),
                           DrawdownEntry(date(2029, 10, 1), 40.0))),
    ))


# plain canonical-shape periods (semestrial halves; construction 2029)
CONSTRUCTION = ((date(2029, 1, 1), date(2029, 6, 30)),
                (date(2029, 7, 1), date(2029, 12, 31)))
OPERATING = (
    candidate.CandidatePeriod(2, date(2030, 1, 1), date(2030, 6, 30), True),
    candidate.CandidatePeriod(3, date(2030, 7, 1), date(2030, 12, 31), True),
    candidate.CandidatePeriod(4, date(2031, 1, 1), date(2031, 6, 30), True),
    candidate.CandidatePeriod(5, date(2031, 7, 1), date(2031, 12, 31), True),
)


# ---------------------------------------------------------------------------
# F31MT_CANDIDATE_ISOLATION
# ---------------------------------------------------------------------------


def test_candidate_isolation_pins():
    """F31MT_CANDIDATE_ISOLATION = PASS."""
    assert candidate.NON_AUTHORITATIVE is True
    assert candidate.F31_MULTITRANCHE_CANDIDATE_AUTHORITY == (
        "F31_MULTITRANCHE_CANDIDATE_V0")
    assert candidate.F31_MULTITRANCHE_CANDIDATE_AUTHORITY != (
        "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1")
    forbidden = ("financial_engine", "app.persistence", "fastapi",
                 "sqlite3", "app.services", "app.api", "app.v2")
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] + [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom) else [])
            for value in names:
                assert not any(value.startswith(f) or f in value
                               for f in forbidden), (path.name, value)
    # the only project-internal import is the canonical F3.1 schema
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] + [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom) else [])
            for value in names:
                if value.startswith("finco_core"):
                    assert "financing_instruments" in value, (path.name, value)
    assert "f31_multitranche" not in (ROOT / "main_web.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# F31MT_VALIDATION_GENERALIZATION
# ---------------------------------------------------------------------------


def test_validation_count_rule_and_three_tranche_acceptance():
    """F31MT_VALIDATION_GENERALIZATION = PASS (count + happy path)."""
    with pytest.raises(FinancingError, match="F3_MULTITRANCHE_COUNT_UNSUPPORTED"):
        candidate.validate_multitranche_collection(FinancingCollection((
            _instrument("senior-a", 300.0, 0.05, RepaymentMode.LEVEL_PRINCIPAL),)))
    candidate.validate_multitranche_collection(_three())  # N=3 accepted
    candidate.validate_multitranche_collection(FinancingCollection((
        _instrument("senior-a", 300.0, 0.05, RepaymentMode.LEVEL_PRINCIPAL),
        _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET, grace=12),
        _instrument("senior-c", 100.0, 0.04, RepaymentMode.LEVEL_PRINCIPAL),
        _instrument("senior-d", 50.0, 0.06, RepaymentMode.BULLET),
    )))  # N=4 accepted


@pytest.mark.parametrize("mutate,code", [
    (lambda i: replace_type(i), "F3_EFFECTIVE_INSTRUMENT_UNSUPPORTED"),
    (lambda i: _with(i, seniority_rank=2), "F3_PARI_PASSU_SENIOR_ONLY"),
    (lambda i: _interest(i, pik=True), "F3_FIXED_CASH_INTEREST_ONLY"),
    (lambda i: _repayment(i, RepaymentMode.DSCR_SCULPTED), "F3_REPAYMENT_UNSUPPORTED"),
    (lambda i: _repayment_derived(i), "F3_EXPLICIT_CALENDAR_MATURITY_REQUIRED"),
    (lambda i: _with(i, commitment_authority=CommitmentAuthority.CANONICAL_SIZING_DERIVED),
     "F3_DERIVED_COMMITMENT_HAS_AMOUNT"),
    (lambda i: _fees(i, (FeeTerm(FeeKind.AGENCY, 0.01),)), "F3_FEE_UNSUPPORTED"),
    (lambda i: _fees(i, (FeeTerm(FeeKind.UPFRONT, 0.01),
                         FeeTerm(FeeKind.UPFRONT, 0.02),)), "F3_DUPLICATE_EFFECTIVE_FEE"),
])
def test_validation_released_rules_fire_verbatim_at_n3(mutate, code):
    """Every released two-Senior rule fires with the SAME code at N=3."""
    instruments = [_instrument("senior-a", 300.0, 0.05, RepaymentMode.LEVEL_PRINCIPAL),
                   _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET, grace=12),
                   _instrument("senior-c", 100.0, 0.04, RepaymentMode.LEVEL_PRINCIPAL)]
    with pytest.raises(FinancingError, match=code):
        candidate.validate_multitranche_collection(
            FinancingCollection((instruments[0], instruments[1],
                                 mutate(instruments[2]))))


def test_validation_providers_and_partial_draws_fail_closed():
    providers = (__import__("finco_core.inputs.financing_instruments",
                            fromlist=["CapitalProvider"]).CapitalProvider(
        "dfi", "DFI", 0.0),)
    with pytest.raises(FinancingError, match="F3_PROVIDER_ECONOMICS_UNSUPPORTED"):
        candidate.validate_multitranche_collection(
            FinancingCollection((_three().instruments), providers=providers))
    partial = _instrument("senior-c", 100.0, 0.04, RepaymentMode.LEVEL_PRINCIPAL,
                          draws=(DrawdownEntry(date(2029, 3, 1), 60.0),))
    with pytest.raises(FinancingError, match="F3_FULL_EXPLICIT_DRAWS_REQUIRED"):
        candidate.validate_multitranche_collection(FinancingCollection((
            _instrument("senior-a", 300.0, 0.05, RepaymentMode.LEVEL_PRINCIPAL),
            _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET, grace=12),
            partial)))


# ---------------------------------------------------------------------------
# F31MT_SCHEDULES_HAND_COMPUTED
# ---------------------------------------------------------------------------


def test_three_tranche_schedules_match_hand_math():
    """F31MT_SCHEDULES_HAND_COMPUTED = PASS (ACT_365, hand-computed)."""
    schedules = candidate.build_candidate_facility_schedules(
        _three(), CONSTRUCTION, OPERATING, day_count="act_365")
    by_id = {s.instrument_id: s for s in schedules}
    a, b, c = by_id["senior-a"], by_id["senior-b"], by_id["senior-c"]

    # Tranche A: 300 @5%, level, maturity O2 (181d then 184d)
    assert a.opening_keur == (300.0, 150.0)
    assert a.interest_keur == pytest.approx(
        (300 * 0.05 * 180 / 365, 150 * 0.05 * 183 / 365), abs=1e-9)
    assert a.principal_keur == (150.0, 150.0)
    assert a.closing_keur == (150.0, 0.0)
    # construction: single draw 2029-02-01, 150 days to 2029-07-01
    assert a.construction_draws_keur == (300.0, 0.0)
    assert a.construction_idc_keur[0] == pytest.approx(300 * 0.05 * 150 / 365, abs=1e-9)
    assert a.construction_idc_keur[1] == pytest.approx(300 * 0.05 * 184 / 365, abs=1e-9)
    # undrawn integral C1: (300)*(181/365) - 300*(150/365)
    assert a.construction_commitment_fees_keur[0] == pytest.approx(
        0.005 * 300 * 31 / 365, abs=1e-9)
    assert a.construction_commitment_fees_keur[1] == 0.0
    assert a.upfront_fees_keur == (3.0, 0.0)

    # Tranche B: 200 @7%, bullet, grace 12m, maturity O4
    assert b.interest_keur == pytest.approx((
        200 * 0.07 * 180 / 365, 200 * 0.07 * 183 / 365,
        200 * 0.07 * 180 / 365, 200 * 0.07 * 183 / 365), abs=1e-9)
    assert b.principal_keur == (0.0, 0.0, 0.0, 200.0)
    assert b.debt_service_keur[3] == pytest.approx(200.0 + 200 * 0.07 * 183 / 365,
                                                   abs=1e-9)
    assert b.closing_keur[-1] == 0.0
    # construction: draw 2029-08-15 -> 138 days to 2030-01-01
    assert b.construction_draws_keur == (0.0, 200.0)
    assert b.construction_idc_keur[0] == 0.0
    assert b.construction_idc_keur[1] == pytest.approx(200 * 0.07 * 139 / 365, abs=1e-9)
    assert b.construction_commitment_fees_keur[0] == pytest.approx(
        0.005 * 200 * 181 / 365, abs=1e-9)
    assert b.construction_commitment_fees_keur[1] == pytest.approx(
        0.005 * 200 * 45 / 365, abs=1e-9)

    # Tranche C: 100 @4%, level, two dated draws (60 + 40)
    assert c.principal_keur == (25.0, 25.0, 25.0, 25.0)
    assert c.interest_keur == pytest.approx((
        100 * 0.04 * 180 / 365, 75 * 0.04 * 183 / 365,
        50 * 0.04 * 180 / 365, 25 * 0.04 * 183 / 365), abs=1e-9)
    assert c.closing_keur[-1] == 0.0
    assert c.construction_draws_keur == (60.0, 40.0)
    # C1 IDC: base 0 + draw 60 accruing 122 days; C2: base 60 over 184d + draw 40 over 92d
    assert c.construction_idc_keur[0] == pytest.approx(60 * 0.04 * 122 / 365, abs=1e-9)
    assert c.construction_idc_keur[1] == pytest.approx(
        60 * 0.04 * 184 / 365 + 40 * 0.04 * 92 / 365, abs=1e-9)
    assert c.construction_commitment_fees_keur[1] == pytest.approx(
        0.005 * 40 * 92 / 365, abs=1e-9)

    # aggregate invariant: per-period sums == tranche sums (released handshake)
    aggregate = candidate.build_candidate_aggregate(schedules)
    for field in ("interest", "principal", "debt_service", "closing"):
        for position, idx in enumerate(a.period_indices):
            assert aggregate[idx][field] == pytest.approx(fsum(
                getattr(f, f"{field}_keur")[position]
                for f in schedules if idx in f.period_indices), abs=1e-9)


def test_schedule_edge_cases_fail_closed():
    off_boundary = _instrument("senior-a", 300.0, 0.05, RepaymentMode.BULLET,
                               maturity=date(2030, 12, 30))
    with pytest.raises(FinancingError, match="F3_MATURITY_NOT_ON_OPERATING_BOUNDARY"):
        candidate.build_candidate_facility_schedules(
            FinancingCollection((off_boundary,
                                 _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET))),
            CONSTRUCTION, OPERATING, day_count="act_365")
    long_grace = _instrument("senior-c", 100.0, 0.04, RepaymentMode.LEVEL_PRINCIPAL,
                             grace=36, maturity=M_B)
    with pytest.raises(FinancingError, match="F3_GRACE_EXCEEDS_MATURITY"):
        candidate.build_candidate_facility_schedules(
            FinancingCollection((_instrument("senior-a", 300.0, 0.05, RepaymentMode.BULLET),
                                 long_grace)),
            CONSTRUCTION, OPERATING, day_count="act_365")
    outside = _instrument("senior-c", 100.0, 0.04, RepaymentMode.BULLET,
                          draws=(DrawdownEntry(date(2030, 3, 1), 100.0),))
    with pytest.raises(FinancingError, match="F3_DRAW_OUTSIDE_CONSTRUCTION"):
        candidate.build_candidate_facility_schedules(
            FinancingCollection((_instrument("senior-a", 300.0, 0.05, RepaymentMode.BULLET),
                                 outside)),
            CONSTRUCTION, OPERATING, day_count="act_365")
    with pytest.raises(FinancingError, match="F3_DAY_COUNT_UNSUPPORTED"):
        candidate.build_candidate_facility_schedules(
            _three(), CONSTRUCTION, OPERATING, day_count="fixed_semianual")


# ---------------------------------------------------------------------------
# F31MT_N2_EQUIVALENCE + F31MT_BOUNDARY_TWO_SENIOR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_n2_equivalence_with_released_engine(kind):
    """F31MT_N2_EQUIVALENCE = PASS — candidate == released engine at N=2."""
    from test_financing_f3_multisenior import case
    from financial_engine.financing.multisenior import build_facility_schedules
    from financial_engine.financing.generic_product_policy import (
        derive_construction_financing,
    )
    active, periods = case(kind)
    released = build_facility_schedules(active, periods)
    construction = derive_construction_financing(active)
    candidate_schedules = candidate.build_candidate_facility_schedules(
        active.financing_collection,
        [(p.start_date, p.end_date) for p in construction.periods],
        tuple(candidate.CandidatePeriod(p.period_index, p.period_start,
                                        p.period_end, p.is_operation)
              for p in periods),  # full canonical list; candidate filters
        day_count="act_360")
    assert len(candidate_schedules) == len(released)
    for got, want in zip(candidate_schedules, released):
        assert got.instrument_id == want.instrument_id
        for field in ("opening_keur", "interest_keur", "principal_keur",
                      "debt_service_keur", "closing_keur",
                      "construction_draws_keur", "construction_idc_keur",
                      "construction_commitment_fees_keur", "upfront_fees_keur"):
            assert getattr(got, field) == pytest.approx(
                getattr(want, field), abs=1e-9), (got.instrument_id, field)


def test_released_validator_still_exactly_two():
    """F31MT_BOUNDARY_TWO_SENIOR = PASS — released authority unchanged."""
    with pytest.raises(FinancingError, match="F3_EXACTLY_TWO_SENIORS_REQUIRED"):
        validate_effective_collection(_three())
    validate_effective_collection(FinancingCollection(
        (_instrument("senior-a", 300.0, 0.05, RepaymentMode.LEVEL_PRINCIPAL),
         _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET, grace=12))))


# ---------------------------------------------------------------------------
# F31MT_RECONCILIATION
# ---------------------------------------------------------------------------


def _reconcile(**overrides):
    facilities = candidate.build_candidate_facility_schedules(
        _three(), CONSTRUCTION, OPERATING, day_count="act_365")
    kwargs = dict(
        total_project_uses_keur=800.0,
        period_uses_keur=(360.0, 440.0),
        gearing_ratio=0.75,
        share_capital_keur=100.0,
        share_premium_keur=0.0,
        other_equity_keur=0.0,
        additional_equity_keur=100.0,
        # CFADS evidence is REQUIRED (Correction A); generous unless a test overrides it
        cfads_by_period={i: 1e6 for f in facilities for i in f.period_indices},
    )
    kwargs.update(overrides)
    return facilities, candidate.reconcile_multitranche_sources_uses(
        facilities, **kwargs)


def test_reconciliation_three_tranches_balances():
    """F31MT_RECONCILIATION = PASS — draws first, equity fills the residual."""
    facilities, result = _reconcile()
    assert result.aggregate_senior_commitment_keur == 600.0
    assert result.gearing_capacity_keur == 600.0  # constraint binds, never resizes
    draws = tuple(row.senior_draw_keur for row in result.per_period)
    assert draws == (360.0, 240.0)  # 300+60, 200+40
    first, second = result.per_period
    assert first.residual_keur == 0.0
    assert (second.share_capital_draw_keur, second.additional_equity_draw_keur) == (
        100.0, 100.0)
    assert result.sources_uses_residual_keur == 0.0


def test_reconciliation_fail_closed_matrix():
    with pytest.raises(FinancingError, match="F3_AGGREGATE_GEARING_CAP_EXCEEDED"):
        _reconcile(gearing_ratio=0.7)
    with pytest.raises(FinancingError, match="F3_PERIOD_OVERFUNDING"):
        _reconcile(period_uses_keur=(350.0, 450.0))
    with pytest.raises(FinancingError, match="F3_CONSTRUCTION_USES_DO_NOT_RECONCILE"):
        _reconcile(total_project_uses_keur=800.5)
    with pytest.raises(FinancingError,
                       match="F3_MULTITRANCHE_ADDITIONAL_EQUITY_REQUIRED"):
        _reconcile(additional_equity_keur=None)
    facilities, result = _reconcile()
    all_indices = sorted({i for f in facilities for i in f.period_indices})
    shortfall = {idx: 0.0 for idx in all_indices}
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
        candidate.reconcile_multitranche_sources_uses(
            facilities, total_project_uses_keur=800.0,
            period_uses_keur=(360.0, 440.0), gearing_ratio=0.75,
            share_capital_keur=100.0, share_premium_keur=0.0,
            other_equity_keur=0.0, additional_equity_keur=100.0,
            cfads_by_period=shortfall)
    generous = {idx: 1e6 for idx in all_indices}
    ok = candidate.reconcile_multitranche_sources_uses(
        facilities, total_project_uses_keur=800.0,
        period_uses_keur=(360.0, 440.0), gearing_ratio=0.75,
        share_capital_keur=100.0, share_premium_keur=0.0,
        other_equity_keur=0.0, additional_equity_keur=100.0,
        cfads_by_period=generous)
    assert ok.sources_uses_residual_keur == 0.0


# ---------------------------------------------------------------------------
# Correction A — equity commitments deplete across ALL construction periods
# ---------------------------------------------------------------------------


def _sched(instrument_id, commitment, draws, service=None):
    """A hand-built tranche ledger: dated construction draws + contractual service by operating period."""
    service = dict(service or {})
    indices = tuple(sorted(service))
    zero_ops = tuple(0.0 for _ in indices)
    zero_con = tuple(0.0 for _ in draws)
    return candidate.CandidateFacilitySchedule(
        instrument_id=instrument_id, commitment_keur=float(commitment),
        maturity_period_index=max(indices) if indices else 0, period_indices=indices,
        opening_keur=zero_ops, interest_keur=zero_ops, principal_keur=zero_ops,
        debt_service_keur=tuple(float(service[i]) for i in indices), closing_keur=zero_ops,
        construction_draws_keur=tuple(float(d) for d in draws), construction_idc_keur=zero_con,
        construction_commitment_fees_keur=zero_con, upfront_fees_keur=zero_con)


def _recon(facilities, uses, *, sc=0.0, sp=0.0, oe=0.0, ae=0.0, gearing=1.0, cfads=None, total=None):
    return candidate.reconcile_multitranche_sources_uses(
        tuple(facilities), total_project_uses_keur=fsum(uses) if total is None else total,
        period_uses_keur=tuple(uses), gearing_ratio=gearing, share_capital_keur=sc, share_premium_keur=sp,
        other_equity_keur=oe, additional_equity_keur=ae, cfads_by_period={} if cfads is None else cfads)


def _no_senior(periods):
    return [_sched("none", 0.0, (0.0,) * periods)]


def _oracle(uses, senior_draws, sc, sp, oe, ae):
    """Independent exact-rational waterfall: share capital -> premium -> other -> additional, depleting pools."""
    pools = [Fraction(sc), Fraction(sp), Fraction(oe), Fraction(ae)]
    out = []
    for use, draw in zip(uses, senior_draws):
        need = Fraction(use) - Fraction(draw)
        taken = []
        for i, pool in enumerate(pools):
            take = min(pool, max(need, Fraction(0)))
            pools[i] -= take
            need -= take
            taken.append(take)
        out.append((tuple(taken), need))
    return out


def _equity_row(row):
    return (row.share_capital_draw_keur, row.share_premium_draw_keur,
            row.other_committed_equity_draw_keur, row.additional_equity_draw_keur)


def test_a_commitment_drawn_in_one_period_is_not_available_again():
    """The defect: each period re-offered the FULL share-capital commitment (drawn 200 against a commitment of 100)."""
    facilities = [_sched("a", 300, (200, 100)), _sched("b", 300, (160, 140))]
    result = _recon(facilities, (460, 540), sc=100, ae=300, gearing=0.6)
    first, second = result.per_period
    assert (first.senior_draw_keur, *_equity_row(first)) == (360, 100, 0, 0, 0)
    assert (second.senior_draw_keur, *_equity_row(second)) == (240, 0, 0, 0, 300)
    assert result.total_share_capital_drawn_keur == 100 and result.total_additional_equity_drawn_keur == 300
    assert result.total_senior_drawn_keur == 600 and result.sources_uses_residual_keur == 0.0


def test_an_exhausted_commitment_is_never_reused_over_many_periods():
    result = _recon(_no_senior(5), (100,) * 5, sc=150, ae=350)
    assert [r.share_capital_draw_keur for r in result.per_period] == [100, 50, 0, 0, 0]
    assert [r.additional_equity_draw_keur for r in result.per_period] == [0, 50, 100, 100, 100]
    assert result.total_share_capital_drawn_keur == 150 and result.total_additional_equity_drawn_keur == 350


def test_all_four_sources_deplete_in_the_released_waterfall_order():
    result = _recon(_no_senior(4), (80, 120, 100, 200), sc=50, sp=70, oe=30, ae=350)
    assert [_equity_row(r) for r in result.per_period] == [
        (50, 30, 0, 0), (0, 40, 30, 50), (0, 0, 0, 100), (0, 0, 0, 200)]
    assert (result.total_share_capital_drawn_keur, result.total_share_premium_drawn_keur,
            result.total_other_committed_equity_drawn_keur, result.total_additional_equity_drawn_keur) == (50, 70, 30, 350)


USES_GRID = [(100, 100, 100), (50, 150, 250), (10, 0, 490), (500, 0, 0)]
COMMITMENT_GRID = [(0, 0, 0, 500), (100, 0, 0, 400), (30, 60, 90, 320), (500, 0, 0, 0), (200, 200, 100, 0),
                   (600, 0, 0, 0), (0, 70, 0, 430)]


@pytest.mark.parametrize("uses", USES_GRID)
@pytest.mark.parametrize("commitments", COMMITMENT_GRID)
def test_equity_pools_match_an_independent_exact_oracle_and_never_exceed_any_commitment(uses, commitments):
    sc, sp, oe, ae = commitments
    result = _recon(_no_senior(len(uses)), uses, sc=sc, sp=sp, oe=oe, ae=ae)
    for row, (taken, leftover) in zip(result.per_period, _oracle(uses, (0,) * len(uses), sc, sp, oe, ae)):
        assert _equity_row(row) == tuple(float(t) for t in taken) and row.residual_keur == 0.0
    drawn = (result.total_share_capital_drawn_keur, result.total_share_premium_drawn_keur,
             result.total_other_committed_equity_drawn_keur, result.total_additional_equity_drawn_keur)
    assert all(d <= c for d, c in zip(drawn, commitments))
    assert fsum(drawn) + result.total_senior_drawn_keur == fsum(uses)     # aggregate sources == total uses


@pytest.mark.parametrize("senior", [(0, 0, 0), (40, 60, 0), (100, 0, 50)])
def test_three_tranche_independent_cases_reconcile_aggregate_sources_to_uses(senior):
    """N=3 hand-built ledgers: draws split over three tranches, equity fills the residual from depleting pools."""
    uses = (200, 300, 100)
    a = tuple(d * 0.5 for d in senior)        # binary-exact splits: 1/2, 1/4, 1/4
    b = tuple(d * 0.25 for d in senior)
    c = tuple(d * 0.25 for d in senior)
    facilities = [_sched("a", fsum(a), a), _sched("b", fsum(b), b), _sched("c", fsum(c), c)]
    total_senior = fsum(senior)
    residual = fsum(uses) - total_senior
    result = _recon(facilities, uses, sc=120, sp=30, oe=50, ae=residual - 200)
    assert result.total_senior_drawn_keur == total_senior
    equity = (result.total_share_capital_drawn_keur + result.total_share_premium_drawn_keur
              + result.total_other_committed_equity_drawn_keur + result.total_additional_equity_drawn_keur)
    assert equity == residual and result.sources_uses_residual_keur == 0.0
    for row, (taken, _) in zip(result.per_period, _oracle(uses, senior, 120, 30, 50, residual - 200)):
        assert _equity_row(row) == tuple(float(t) for t in taken)


def test_unused_committed_equity_is_not_forced_into_the_project():
    result = _recon(_no_senior(2), (100, 200), sc=1000)
    assert result.total_share_capital_drawn_keur == 300 and result.sources_uses_residual_keur == 0.0


def test_an_underfunded_stack_fails_closed_even_when_early_periods_look_funded():
    with pytest.raises(FinancingError, match="F3_SOURCES_USES_UNRECONCILED"):
        _recon(_no_senior(2), (100, 200), sc=100, ae=0)     # period 2 can no longer reuse the share capital


def test_an_exhausted_additional_equity_commitment_cannot_fund_a_later_period():
    with pytest.raises(FinancingError, match="F3_SOURCES_USES_UNRECONCILED"):
        _recon(_no_senior(2), (100, 100), ae=100)           # the 100 of additional equity is spent in period 1


def test_the_aggregate_commitment_guard_catches_a_stateless_allocator(monkeypatch):
    """Defence in depth: even if the per-period fill regressed to offering the FULL commitments every period
    (the original defect), the aggregate draws per source are checked against their commitments."""
    from app.model_v2.financing_f31_multitranche_candidate import reconciliation as rec
    facilities = [_sched("a", 300, (200, 100)), _sched("b", 300, (160, 140))]
    full = dict(share_capital=100.0, share_premium=0.0, other_equity=0.0, additional_equity=300.0)
    original = rec._equity_fill
    monkeypatch.setattr(rec, "_equity_fill", lambda residual, **_ignored: original(residual, **full))
    with pytest.raises(FinancingError, match="F3_EQUITY_COMMITMENT_EXCEEDED.*share_capital"):
        _recon(facilities, (460, 540), sc=100, ae=300, gearing=0.6)


def test_facility_draw_and_input_integrity_fail_closed():
    with pytest.raises(FinancingError, match="F3_DRAWDOWN_EXCEEDS_COMMITMENT"):
        _recon([_sched("a", 100, (60, 90))], (60, 90), ae=0, gearing=1.0)
    with pytest.raises(FinancingError, match="F3_CONSTRUCTION_USES_DO_NOT_RECONCILE"):
        _recon([_sched("a", 100, (100,))], (60, 90), ae=50)
    for label, bad in itertools.product(
            ("share_capital_keur", "share_premium_keur", "other_equity_keur", "total_project_uses_keur"),
            (float("nan"), float("inf"), -1.0, True, "5")):
        kwargs = dict(total_project_uses_keur=100.0, period_uses_keur=(100.0,), gearing_ratio=1.0,
                      share_capital_keur=100.0, share_premium_keur=0.0, other_equity_keur=0.0,
                      additional_equity_keur=0.0, cfads_by_period={})
        kwargs[label] = bad
        with pytest.raises(FinancingError, match="F3_MULTITRANCHE_INPUT_INVALID"):
            candidate.reconcile_multitranche_sources_uses(_no_senior(1), **kwargs)
    with pytest.raises(FinancingError, match="F3_MULTITRANCHE_INPUT_INVALID"):
        _recon(_no_senior(2), (100, float("nan")), sc=100, total=100.0)


def test_n2_equity_allocation_equals_the_released_allocator_over_multiple_periods():
    from finco_core.construction.allocator import allocate_construction_sources_per_period as released
    cases = [((100., 200., 150., 50.), (60., 0., 40., 0.), 120., 80., 40.),
             ((300., 300.), (0., 0.), 100., 0., 0.),
             ((10., 490., 0., 500.), (10., 200., 0., 100.), 300., 0., 90.)]
    for uses, draws, sc, sp, oe in cases:
        a = tuple(d * 0.4 for d in draws)
        b = tuple(d * 0.6 for d in draws)
        residual = tuple(u - d for u, d in zip(uses, draws))
        ae = max(0.0, fsum(residual) - sc - sp - oe)
        want = released(period_uses=residual, share_capital_keur=sc, share_premium_keur=sp,
                        other_committed_equity_keur=oe, additional_equity_keur=ae, shl_cash_keur=0.,
                        junior_keur=0., senior_commitment_keur=0.)
        got = _recon([_sched("a", fsum(a), a), _sched("b", fsum(b), b)], uses, sc=sc, sp=sp, oe=oe, ae=ae)
        for row, w in zip(got.per_period, want):
            assert _equity_row(row) == pytest.approx((w.share_capital_draw_keur, w.share_premium_draw_keur,
                                                      w.other_committed_equity_draw_keur,
                                                      w.additional_equity_draw_keur), abs=1e-9)
            assert row.residual_keur == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Correction A — contractual CFADS coverage is on the AGGREGATE service
# ---------------------------------------------------------------------------


def _service_facilities():
    """Three tranches, 40 each in operating period 5 -> aggregate 120; A/B offset into 6 and 7."""
    return [_sched("a", 0, (0.0,), {5: 40.0, 6: 60.0}), _sched("b", 0, (0.0,), {5: 40.0, 6: 50.0, 7: 50.0}),
            _sched("c", 0, (0.0,), {5: 40.0})]


def test_each_tranche_passing_does_not_prove_the_aggregate_service_is_covered():
    """The defect: every tranche was compared with the FULL CFADS, so 40 + 40 + 40 passed against CFADS 100."""
    facilities = _service_facilities()
    cfads = {5: 100.0, 6: 1000.0, 7: 1000.0}
    assert all(max(s) <= 100.0 for f in facilities for s in [f.debt_service_keur])   # each tranche is below the CFADS
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL.*120"):
        _recon(facilities, (0.0,), cfads=cfads)


def test_service_is_aggregated_per_operating_period_across_offset_tranche_calendars():
    facilities = _service_facilities()
    ok = _recon(facilities, (0.0,), cfads={5: 120.0, 6: 110.0, 7: 50.0})
    assert ok.aggregate_service_by_period == ((5, 120.0), (6, 110.0), (7, 50.0))
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL.*6"):
        _recon(facilities, (0.0,), cfads={5: 500.0, 6: 100.0, 7: 500.0})        # 60 and 50 are each <= 100; 110 is not
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL.*7"):
        _recon(facilities, (0.0,), cfads={5: 500.0, 6: 500.0, 7: 49.0})


def test_coverage_boundary_follows_the_released_tolerance():
    facilities = _service_facilities()
    base = {6: 1000.0, 7: 1000.0}
    _recon(facilities, (0.0,), cfads={5: 120.0, **base})                  # exactly covered
    _recon(facilities, (0.0,), cfads={5: 120.0 - 1e-8, **base})           # inside the 1e-7 tolerance
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
        _recon(facilities, (0.0,), cfads={5: 120.0 - 1e-6, **base})


def test_missing_cfads_evidence_fails_closed_with_its_own_code():
    facilities = _service_facilities()
    with pytest.raises(FinancingError, match="F3_CFADS_EVIDENCE_MISSING.*period 6"):
        _recon(facilities, (0.0,), cfads={5: 1000.0, 7: 1000.0})          # period 6 has service but no CFADS
    with pytest.raises(FinancingError, match="F3_CFADS_EVIDENCE_MISSING"):
        candidate.reconcile_multitranche_sources_uses(
            tuple(facilities), total_project_uses_keur=0.0, period_uses_keur=(0.0,), gearing_ratio=1.0,
            share_capital_keur=0.0, share_premium_keur=0.0, other_equity_keur=0.0, additional_equity_keur=0.0)
    with pytest.raises(FinancingError, match="F3_CFADS_EVIDENCE_MISSING"):
        candidate.reconcile_multitranche_sources_uses(
            tuple(facilities), total_project_uses_keur=0.0, period_uses_keur=(0.0,), gearing_ratio=1.0,
            share_capital_keur=0.0, share_premium_keur=0.0, other_equity_keur=0.0, additional_equity_keur=0.0,
            cfads_by_period=None)


def test_a_period_without_contractual_service_needs_no_cfads_and_extra_keys_are_ignored():
    quiet = [_sched("a", 0, (0.0,), {5: 0.0, 6: 10.0})]
    assert _recon(quiet, (0.0,), cfads={6: 10.0, 99: 1.0}).aggregate_service_by_period == ((5, 0.0), (6, 10.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, False, "100", None, [100.0]])
def test_invalid_cfads_values_are_rejected_not_treated_as_zero_or_a_pass(bad):
    with pytest.raises(FinancingError, match="F3_CFADS_EVIDENCE_INVALID"):
        _recon([_sched("a", 0, (0.0,), {5: 40.0})], (0.0,), cfads={5: bad})


def test_zero_and_negative_cfads_are_real_evidence_and_fail_a_positive_service():
    for value in (0.0, -50.0):
        with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
            _recon([_sched("a", 0, (0.0,), {5: 40.0})], (0.0,), cfads={5: value})


def test_three_tranche_schedule_ledgers_fail_when_cfads_sits_between_the_largest_tranche_and_the_aggregate():
    facilities, ok = _reconcile()
    indices = sorted({i for f in facilities for i in f.period_indices})
    aggregate = dict(ok.aggregate_service_by_period)
    largest = {i: max(dict(zip(f.period_indices, f.debt_service_keur)).get(i, 0.0) for f in facilities) for i in indices}
    between = {i: (aggregate[i] + largest[i]) / 2 for i in indices}
    assert all(largest[i] < between[i] < aggregate[i] for i in indices if aggregate[i] > 0)
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
        _reconcile(cfads_by_period=between)
    _reconcile(cfads_by_period={i: aggregate[i] for i in indices})        # exactly the aggregate: covered


# ---------------------------------------------------------------------------
# Correction A — N=2 equivalence with the released engine (Solar and Wind)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_n2_reconciliation_and_service_equal_the_released_engine(kind):
    from test_financing_f3_multisenior import case
    from financial_engine.financing.generic_product_policy import derive_construction_financing
    from financial_engine.financing.multisenior import run_multisenior_financing
    active, periods = case(kind)
    released = run_multisenior_financing(active)
    construction = derive_construction_financing(active)
    schedules = candidate.build_candidate_facility_schedules(
        active.financing_collection, [(p.start_date, p.end_date) for p in construction.periods],
        tuple(candidate.CandidatePeriod(p.period_index, p.period_start, p.period_end, p.is_operation) for p in periods),
        day_count="act_360")
    model = released.project_model_result
    cfads = dict(zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.cfads_keur))
    fin = released.construction_financing
    kwargs = dict(
        total_project_uses_keur=released.project_uses.total_project_uses_keur,
        period_uses_keur=fin.total_period_uses_keur, gearing_ratio=released.gearing_ratio,
        share_capital_keur=released.share_capital_keur, share_premium_keur=released.share_premium_keur,
        other_equity_keur=released.other_equity_funding_before_shl_keur,
        additional_equity_keur=released.additional_equity_keur)
    got = candidate.reconcile_multitranche_sources_uses(schedules, cfads_by_period=cfads, **kwargs)
    for field, want in (("share_capital_draw_keur", fin.share_capital_draws_keur),
                        ("share_premium_draw_keur", fin.share_premium_draws_keur),
                        ("other_committed_equity_draw_keur", fin.other_committed_equity_draws_keur),
                        ("additional_equity_draw_keur", fin.additional_equity_draws_keur),
                        ("senior_draw_keur", fin.senior_draws_keur)):
        assert [getattr(r, field) for r in got.per_period] == pytest.approx(list(want), abs=1e-9), field
    senior = model.senior_debt
    candidate_service = dict(got.aggregate_service_by_period)
    for index, service in zip(senior.period_indices, senior.senior_debt_service_keur):
        assert candidate_service.get(index, 0.0) == pytest.approx(service, abs=1e-9), index
    first = next(i for i, v in zip(senior.period_indices, senior.senior_debt_service_keur) if v > 1.0)
    squeezed = dict(cfads)
    squeezed[first] = candidate_service[first] * (1 - 1e-3)
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
        candidate.reconcile_multitranche_sources_uses(schedules, cfads_by_period=squeezed, **kwargs)


# ---------------------------------------------------------------------------
# Correction A — the candidate stays unreachable from production
# ---------------------------------------------------------------------------


def test_no_other_module_imports_the_candidate_package():
    """Reverse direction of the import-ownership allow-list: the allow-list lets the candidate import the F3
    financing contract, so nothing outside the package may import the candidate (no transitive path)."""
    needle = "financing_f31_multitranche_candidate"
    offenders = []
    for name in ("app", "domain", "financial_engine", "finco_core", "tools", "static", "deploy", ".github",
                 "main_web.py", "main_api.py", "main_mcp.py"):
        root = ROOT / name
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in files:
            if PACKAGE in path.parents or path.suffix not in (".py", ".yml", ".yaml", ".json", ".html", ".js", ".toml"):
                continue
            try:
                if needle in path.read_text(encoding="utf-8"):
                    offenders.append(path.relative_to(ROOT).as_posix())
            except UnicodeDecodeError:
                continue
    assert offenders == []


def test_the_package_init_does_not_import_the_financing_contract_directly():
    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    values = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    values += [(n.module or "") + "." + a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    assert not any("financing_instruments" in v for v in values)


# ---------------------------------------------------------------------------
# F31MT_SCENARIO_COMBINATIONS (workflow item 5)
# ---------------------------------------------------------------------------


def test_scenario_combinations_fail_closed():
    """F31MT_SCENARIO_COMBINATIONS = PASS."""
    # SHL / mezzanine / construction-facility instruments are not senior term
    # loans: the candidate rejects them per the released rule.
    module = __import__("finco_core.inputs.financing_instruments",
                        fromlist=["InstrumentType"])
    # Per type: the code that fires first. Non-SHL debt types pass the schema
    # and are rejected by the candidate's released rule; SHAREHOLDER_LOAN is
    # rejected by the schema itself (no capital provider on the fixture).
    expected = {"SHAREHOLDER_LOAN": "F3_MISSING_TERM",
                "MEZZANINE_DEBT": "F3_EFFECTIVE_INSTRUMENT_UNSUPPORTED",
                "CONSTRUCTION_FACILITY": "F3_EFFECTIVE_INSTRUMENT_UNSUPPORTED",
                "BOND": "F3_EFFECTIVE_INSTRUMENT_UNSUPPORTED"}
    for instrument_type, code in expected.items():
        with pytest.raises(FinancingError, match=code):
            candidate.validate_multitranche_collection(FinancingCollection((
                _instrument("senior-a", 300.0, 0.05, RepaymentMode.LEVEL_PRINCIPAL),
                _instrument("senior-b", 200.0, 0.07, RepaymentMode.BULLET, grace=12),
                _instrument("senior-c", 100.0, 0.04, RepaymentMode.LEVEL_PRINCIPAL,
                            instrument_type=getattr(module.InstrumentType,
                                                    instrument_type)))))
    # released engine boundary still guards reserves + quarterly for any F3 run
    from dataclasses import replace as dc_replace
    from app.project_factories import create_generic_solar_reference
    from financial_engine.financing.multisenior import validate_project_boundary
    from finco_core.inputs import (
        DebtServiceReserveSupportMode, PeriodFrequency, SponsorFundingMode,
    )
    base = create_generic_solar_reference()
    # Boundary order (released): period frequency -> sponsor mode -> ... ->
    # reserves. Neutralize the sponsor mode first so the later rules are the
    # ones under test, exactly as the released two-Senior fixture does.
    equity_only = dc_replace(base, financing=dc_replace(
        base.financing,
        sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
        dsra_support_mode=DebtServiceReserveSupportMode.NONE,
        dsra_months=0, debt_service_reserve_requirement_keur=0.0))
    with pytest.raises(FinancingError, match="F3_RESERVE_INTEGRATION_NOT_RELEASED"):
        validate_project_boundary(dc_replace(
            equity_only, financing=dc_replace(
                equity_only.financing,
                dsra_support_mode=DebtServiceReserveSupportMode.CASH_DSRA)))
    with pytest.raises(FinancingError, match="F3_PERIOD_FREQUENCY_UNSUPPORTED"):
        validate_project_boundary(dc_replace(
            equity_only, info=dc_replace(
                equity_only.info, period_frequency=PeriodFrequency.QUARTERLY)))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _with(instrument, **overrides):
    from dataclasses import replace
    return replace(instrument, **overrides)


def _interest(instrument, *, pik):
    from dataclasses import replace
    return replace(instrument, interest=replace(instrument.interest, pik=pik))


def _repayment(instrument, mode):
    from dataclasses import replace
    return replace(instrument, repayment=replace(
        instrument.repayment, mode=mode))


def _repayment_derived(instrument):
    from dataclasses import replace
    return replace(instrument, repayment=replace(
        instrument.repayment, maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED,
        maturity_date=None, tenor_years=10))


def _fees(instrument, fees):
    from dataclasses import replace
    return replace(instrument, fees=fees)


def replace_type(instrument):
    module = __import__("finco_core.inputs.financing_instruments",
                        fromlist=["InstrumentType"])
    from dataclasses import replace
    return replace(instrument, instrument_type=module.InstrumentType.CONSTRUCTION_FACILITY)
