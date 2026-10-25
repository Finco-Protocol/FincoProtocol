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
from datetime import date
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
