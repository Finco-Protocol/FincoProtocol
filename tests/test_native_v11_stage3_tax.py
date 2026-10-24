"""Stage 3a: the native full tax evaluation is calculate_tax, exactly.

Real (periods, TaxCalculationInput) pairs are captured from canonical Solar / Data Center Runs, then
perturbed deterministically across the admitted tax space: corporate rate, ATAD on/off with binding EBITDA
or de-minimis capacity, EBT-positive or taxable-income loss gate, loss carry-forward window, cash-tax lag
(including payments beyond the horizon -> terminal unpaid tax), MODEL_YEAR_PAYMENT_PERIOD timing, opening
loss vintages (expiring, partially and fully used), negative EBITDA years, senior / other / SHL interest
(including SHL non-deductible fractions), fiscal reintegration and admitted financing income.

For every case the native result, assembled by the canonical ``calculate_canonical_cfads`` /
``_assemble_tax_cfads_schedules`` consumers, must equal the canonical result object for object (pickle
bytes: every float bit, every TaxAnnualResult, every vintage ledger entry), every period field read by the
canonical consumers must be bit-identical, and when the canonical function raises the native path must
never return a value."""
from __future__ import annotations

import dataclasses
import pickle
import random
import types

import pytest

pytestmark = pytest.mark.usefixtures("stage3_artifacts")

PERIOD_FIELDS = ("period_index", "primary_tax_year", "deductible_interest_keur", "disallowed_interest_keur",
                 "other_fiscal_reintegration_keur", "taxable_income_before_lcf_share_keur", "cit_accrual_share_keur",
                 "cash_tax_keur", "shl_tax_eligible_interest_keur", "shl_non_deductible_interest_keur",
                 "capitalisation_ratio", "capitalisation_gate_active", "shl_absolute_limit_component_keur",
                 "shl_ebitda_limit_component_keur", "shl_additional_non_deductible_component_keur",
                 "financing_income_keur")


def _bits(v):
    return v.hex() if type(v) is float else (type(v).__name__, v)


@pytest.fixture(scope="module")
def captured():
    """Distinct canonical calculate_tax inputs of real Runs (V10 and Stage 3 off)."""
    import financial_engine.tax.engine as te
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    seen, out = set(), []
    real = te.calculate_tax

    def spy(periods, tax_input):
        key = (id(periods), pickle.dumps(tax_input))
        if key not in seen and len(out) < 12:
            seen.add(key)
            out.append((periods, tax_input))
        return real(periods, tax_input)

    te.calculate_tax = spy
    try:
        for project in ("Solar", "Generic Data Center Reference"):
            pfa._POLICY_RUN_CACHE.clear()
            run_project(project, "Base")
    finally:
        te.calculate_tax = real
        pfa._POLICY_RUN_CACHE.clear()
    assert len(out) >= 6
    return out


def _variant(rng, periods, tax_input):
    from financial_engine.inputs import (OpeningTaxLossVintageInput, PeriodFinancingIncomeInput, PeriodInterestInput,
                                         PeriodTaxAdjustmentInput)
    from financial_engine.policies.tax import CashTaxTiming, ShlInterestDeductibilityMode, TaxLossUtilisationGate
    pol = tax_input.policy
    atad = rng.random() < 0.5
    shl_mode = rng.choice([ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE, ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE,
                           ShlInterestDeductibilityMode.CUSTOM_DEDUCTIBLE_PERCENTAGE])
    pol = dataclasses.replace(
        pol, corporate_rate=rng.choice([0.0, 0.1, 0.18, 0.25, 0.333]),
        atad_enabled=atad, atad_ebitda_limit=rng.choice([0.3, 0.1, 0.05]),
        atad_de_minimis_threshold_keur_annual=rng.choice([0.0, 50.0, 3000.0, 1e6]),
        loss_carryforward_years=rng.choice([0, 1, 3, 5, 20]),
        cash_tax_payment_lag_periods=rng.choice([0, 0, 1, 2, 7]),
        cash_tax_timing=rng.choice([CashTaxTiming.TAX_YEAR_LAST_PERIOD, CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD]),
        loss_utilisation_gate=rng.choice([TaxLossUtilisationGate.TAXABLE_INCOME_POSITIVE,
                                          TaxLossUtilisationGate.EBT_POSITIVE]),
        shl_interest_tax_treatment_enabled=rng.random() < 0.5,
        shl_interest_deductibility=shl_mode,
        shl_interest_deductible_pct=(rng.choice([0.0, 0.25, 0.6, 1.0])
                                     if shl_mode == ShlInterestDeductibilityMode.CUSTOM_DEDUCTIBLE_PERCENTAGE else None))
    scale = rng.choice([1.0, 1.0, 0.3, -0.4])
    shift = rng.choice([0.0, -500.0, 250.0])
    periods = tuple(dataclasses.replace(p, ebitda_keur=p.ebitda_keur * scale + (shift if p.is_operation else 0.0))
                    for p in periods)
    idx = [p.period_index for p in periods]
    interest = []
    for i in idx:
        if rng.random() < 0.7:
            interest.append(PeriodInterestInput(
                period_index=i, senior_interest_keur=rng.choice([0.0, rng.uniform(0, 900), -rng.uniform(0, 5)]),
                shl_interest_keur=rng.choice([0.0, rng.uniform(0, 400)]),
                other_interest_keur=rng.choice([0.0, 0.0, rng.uniform(-10, 60)])))
    adjustments = tuple(PeriodTaxAdjustmentInput(period_index=i, other_fiscal_reintegration_keur=rng.uniform(-80, 120))
                        for i in idx if rng.random() < 0.2)
    income = tuple(PeriodFinancingIncomeInput(period_index=i, financing_income_keur=rng.uniform(0, 40),
                                              authority=rng.choice(["GENERIC_FINCO_POLICY", "SOURCE_PROVEN"]))
                   for i in idx if rng.random() < 0.3)
    first = periods[0].period_end.year - 1
    opening = tuple(OpeningTaxLossVintageInput(origin_tax_year=first - rng.randrange(0, 8),
                                               amount_keur=rng.uniform(0, 5000), source_label=rng.choice(["", f"v{k}"]))
                    for k in range(rng.choice([0, 0, 1, 3])))
    return periods, dataclasses.replace(tax_input, policy=pol, period_interest=tuple(interest),
                                        period_adjustments=adjustments, period_financing_income=income,
                                        opening_loss_vintages=opening)


def _canonical(periods, tax_input):
    from financial_engine.cfads import calculate_canonical_cfads
    from financial_engine.orchestrator import _assemble_tax_cfads_schedules
    from financial_engine.tax.engine import calculate_tax
    tr = calculate_tax(periods, tax_input)
    cf = calculate_canonical_cfads(periods, tr.period_results)
    return tr, cf, _assemble_tax_cfads_schedules(types.SimpleNamespace(periods=periods), tr, tr.period_results, cf)


def _native(periods, tax_input, annual=True):
    from financial_engine.native_v11 import stage3
    from financial_engine.orchestrator import _assemble_tax_cfads_schedules
    native, why = stage3.get_stage3()
    assert native is not None, why
    tr, cf = stage3._full_tax(native, periods, tax_input, annual=annual, stats=None)
    sched = (_assemble_tax_cfads_schedules(types.SimpleNamespace(periods=periods), tr, tr.period_results, cf)
             if annual else None)
    return tr, cf, sched


def _compare(periods, tax_input):
    try:
        ref = _canonical(periods, tax_input)
    except Exception as exc:  # noqa: BLE001 - the canonical verdict is the exception
        with pytest.raises(Exception):
            _native(periods, tax_input)
        return "raised:" + type(exc).__name__
    tr, cf, sched = _native(periods, tax_input)
    rtr, rcf, rsched = ref
    assert pickle.dumps(sched) == pickle.dumps(rsched)                 # incl. every TaxAnnualResult and ledger
    assert tr.annual_results == rtr.annual_results
    assert _bits(tr.terminal_unpaid_tax_keur) == _bits(rtr.terminal_unpaid_tax_keur)
    for mine, theirs in zip(tr.period_results, rtr.period_results, strict=True):
        for name in PERIOD_FIELDS:
            assert _bits(getattr(mine, name)) == _bits(getattr(theirs, name)), name
        assert [(a.tax_year, a.allocation_fraction.hex()) for a in mine.tax_year_allocations] == \
               [(a.tax_year, a.allocation_fraction.hex()) for a in theirs.tax_year_allocations]
    for mine, theirs in zip(cf, rcf, strict=True):
        assert (mine.period_index, mine.ebitda_keur.hex(), mine.cash_tax_keur.hex(), mine.cfads_keur.hex(),
                mine.financing_income_keur.hex()) == (theirs.period_index, theirs.ebitda_keur.hex(),
                                                      theirs.cash_tax_keur.hex(), theirs.cfads_keur.hex(),
                                                      theirs.financing_income_keur.hex())
    btr, bcf, _ = _native(periods, tax_input, annual=False)            # Bank debt-sizing form
    assert [(r.period_index, r.cash_tax_keur.hex()) for r in btr.period_results] == \
           [(r.period_index, r.cash_tax_keur.hex()) for r in rtr.period_results]
    assert [c.cfads_keur.hex() for c in bcf] == [c.cfads_keur.hex() for c in rcf]
    return "exact"


def test_captured_inputs_are_exact(captured):
    assert {_compare(p, t) for p, t in captured} == {"exact"}


@pytest.mark.parametrize("seed", range(6))
def test_perturbed_tax_space_is_exact(captured, seed):
    rng = random.Random(1000 + seed)
    outcomes = []
    for k in range(40):
        periods, tax_input = captured[(seed * 40 + k) % len(captured)]
        try:
            periods, tax_input = _variant(rng, periods, tax_input)
        except (TypeError, ValueError, NotImplementedError):
            continue                                                    # invalid policy combination: not a tax input
        outcomes.append(_compare(periods, tax_input))
    assert outcomes.count("exact") >= 25, outcomes
