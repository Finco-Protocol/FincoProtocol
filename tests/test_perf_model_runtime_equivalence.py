"""P0 model runtime performance: every optimisation must be semantics-preserving.

The Run was sped up by removing redundant work, never by changing a formula:

* a numeric-only cash-tax/CFADS path for the senior solver's inner loop,
* a record-free loss-ledger twin,
* cached period-axis geometry,
* an incremental SHL operating chain,
* reuse of an identical financing result inside the waterfall,
* a run-scoped exact-key memo.

Each fast path has a slower authoritative twin that is still in the code base. These tests
prove the fast path is bit-identical to its twin (``repr`` of every float, so ``-0.0`` and
``0.0`` differ) over randomised synthetic inputs that exercise every branch, that malformed
inputs fail exactly as before, and that a real Solar/Wind Run still reproduces the
pre-optimisation outputs. No wall-clock assertions except one very loose catastrophic ceiling.
"""
from __future__ import annotations

import math
import random
import time
from datetime import date

import pytest

from financial_engine.inputs import (
    OpeningTaxLossVintageInput,
    PeriodFinancingIncomeInput,
    PeriodInterestInput,
    PeriodTaxAdjustmentInput,
    TaxCalculationInput,
)
from financial_engine.policies.tax import (
    CashTaxTiming,
    ShlInterestDeductibilityMode,
    TaxBasisPeriodisation,
    TaxLossUtilisationGate,
    TaxPolicy,
)
from financial_engine.results import OperatingPeriodResult
from financial_engine.run_scope import current_run_scope, engine_run_scope, scoped_memo
from financial_engine.tax import engine as tax_engine
from financial_engine.tax.loss_ledger import (
    run_annual_fifo_ledger,
    taxable_income_after_lcf_series,
)


# ---------------------------------------------------------------------------
# Synthetic tax cases
# ---------------------------------------------------------------------------

def _boundaries(style: str, n: int) -> list[date]:
    """n + 1 period boundaries: 30 Jun / 31 Dec ("semiannual") or 1 Jan / 1 Jul ("calendar")."""
    if style == "semiannual":
        out = [date(2030, 12, 31)]
        while len(out) < n + 1:
            last = out[-1]
            out.append(date(last.year + 1, 6, 30) if last.month == 12 else date(last.year, 12, 31))
        return out
    out = [date(2031, 1, 1)]
    while len(out) < n + 1:
        last = out[-1]
        out.append(date(last.year, 7, 1) if last.month == 1 else date(last.year + 1, 1, 1))
    return out


def _periods(rng: random.Random, style: str) -> tuple[OperatingPeriodResult, ...]:
    n = rng.choice([8, 12, 20, 30])
    bounds = _boundaries("calendar" if style == "calendar" else "semiannual", n)
    if style == "irregular":
        # A period spanning three calendar years and a zero-length period, spliced into an
        # otherwise semi-annual axis.
        bounds = bounds[:4] + [
            date(2034, 12, 31), date(2034, 12, 31), date(2035, 6, 30), date(2035, 12, 31),
            date(2036, 6, 30),
        ]
        n = len(bounds) - 1
    out = []
    for i in range(n):
        start, end = bounds[i], bounds[i + 1]
        days = (end - start).days
        op = i >= 2
        ebitda = rng.choice([0.0, -0.0, rng.uniform(-300.0, 400.0)]) if not op else rng.choice(
            [rng.uniform(-800.0, 6000.0)] * 5 + [0.0, -0.0])
        out.append(OperatingPeriodResult(
            period_index=i, period_start=start, period_end=end, year_index=i / 2.0,
            period_in_year=float(1 + (i % 2)), is_construction=not op, is_operation=op,
            is_ppa_active=op, days_in_period=days, day_fraction=days / 365.0,
            production_mwh=0.0, revenue_keur=0.0, opex_keur=0.0, ebitda_keur=ebitda,
            book_depreciation_keur=0.0, tax_depreciation_keur=rng.uniform(0.0, 2500.0),
            ebit_keur=0.0,
        ))
    return tuple(out)


def _policy(rng: random.Random, **override) -> TaxPolicy:
    atad = rng.choice([True, False])
    mode = rng.choice(list(ShlInterestDeductibilityMode))
    if mode is ShlInterestDeductibilityMode.SUBJECT_TO_LIMITATIONS:
        atad = True
    kwargs = dict(
        policy_id="SYN", policy_version="1", corporate_rate=rng.choice([0.0, 0.1, 0.18, 0.25]),
        periods_per_tax_year=2, loss_carryforward_years=rng.choice([0, 1, 3, 5, 10]),
        atad_enabled=atad, atad_ebitda_limit=rng.choice([0.0, 0.3, 0.5]),
        atad_de_minimis_threshold_keur_annual=rng.choice([0.0, 500.0, 3000.0]),
        cash_tax_timing=rng.choice(list(CashTaxTiming)),
        cash_tax_payment_lag_periods=rng.choice([0, 0, 1, 2]),
        shl_interest_tax_treatment_enabled=rng.choice([True, False]),
        shl_interest_deductibility=mode,
        shl_interest_deductible_pct=(
            0.4 if mode is ShlInterestDeductibilityMode.CUSTOM_DEDUCTIBLE_PERCENTAGE else None
        ),
        loss_utilisation_gate=rng.choice(list(TaxLossUtilisationGate)),
    )
    kwargs.update(override)
    return TaxPolicy(**kwargs)


def _tax_input(rng: random.Random, periods, policy: TaxPolicy) -> TaxCalculationInput:
    def money(scale: float) -> float:
        return rng.choice([0.0, -0.0, rng.uniform(0.0, scale), rng.uniform(0.0, scale)])

    interest, adjustments, fin_income = [], [], []
    for p in periods:
        if rng.random() < 0.85:
            shl = money(900.0)
            interest.append(PeriodInterestInput(
                period_index=p.period_index, senior_interest_keur=money(1500.0),
                shl_interest_keur=shl, other_interest_keur=money(50.0),
                shl_deductible_interest_keur=(
                    rng.uniform(0.0, shl) if rng.random() < 0.2 and shl > 0 else None),
            ))
        if rng.random() < 0.15:
            adjustments.append(PeriodTaxAdjustmentInput(
                period_index=p.period_index, other_fiscal_reintegration_keur=money(200.0)))
        if rng.random() < 0.25:
            fin_income.append(PeriodFinancingIncomeInput(
                period_index=p.period_index, financing_income_keur=money(80.0),
                authority=rng.choice(["SOURCE_PROVEN", "GENERIC_FINCO_POLICY"])))
    vintages = tuple(
        OpeningTaxLossVintageInput(
            origin_tax_year=2026 + k, amount_keur=rng.uniform(0.0, 4000.0), source_label=f"v{k}")
        for k in range(rng.choice([0, 0, 1, 3]))
    )
    return TaxCalculationInput(
        policy=policy, opening_loss_vintages=vintages, period_interest=tuple(interest),
        period_adjustments=tuple(adjustments), period_financing_income=tuple(fin_income),
    )


def _outcome(fn, *args):
    """('ok', exact ordered maps) or ('err', type, message): the full observable behaviour."""
    try:
        cfads, tax = fn(*args)
    except Exception as exc:  # noqa: BLE001 - behaviour under test, incl. fail-closed errors
        return ("err", type(exc).__name__, str(exc))
    return ("ok", [(k, repr(v)) for k, v in cfads.items()], [(k, repr(v)) for k, v in tax.items()])


def _assert_lean_equals_full(periods, tax_input) -> None:
    expected = _outcome(tax_engine._cfads_and_cash_tax_via_full_tax, periods, tax_input)
    assert _outcome(tax_engine.calculate_cfads_and_cash_tax, periods, tax_input) == expected
    with engine_run_scope():
        # Twice in one scope: the second call reuses the cached period-axis plan.
        assert _outcome(tax_engine.calculate_cfads_and_cash_tax, periods, tax_input) == expected
        assert _outcome(tax_engine.calculate_cfads_and_cash_tax, periods, tax_input) == expected


@pytest.mark.parametrize("style", ["semiannual", "calendar", "irregular"])
def test_lean_cash_tax_is_bit_identical_to_calculate_tax(style):
    outcomes = {"ok": 0, "err": 0}
    for seed in range(120):
        rng = random.Random(f"{style}-{seed}")
        periods = _periods(rng, style)
        policy = _policy(rng)
        tax_input = _tax_input(rng, periods, policy)
        _assert_lean_equals_full(periods, tax_input)
        outcomes[_outcome(tax_engine._cfads_and_cash_tax_via_full_tax, periods, tax_input)[0]] += 1
    assert outcomes["ok"] > 60, outcomes   # the cases must mostly exercise the real arithmetic


def test_lean_path_delegates_unusual_inputs_and_fails_identically():
    rng = random.Random("fallback")
    periods = _periods(rng, "semiannual")

    # MODEL_YEAR_PAIRING is not the lean path's basis: delegated, identical behaviour.
    pairing = _policy(
        rng, tax_basis_periodisation=TaxBasisPeriodisation.MODEL_YEAR_PAIRING,
        cash_tax_timing=CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD,
        loss_utilisation_gate=TaxLossUtilisationGate.EBT_POSITIVE,
        shl_interest_tax_treatment_enabled=False,
    )
    _assert_lean_equals_full(periods, _tax_input(rng, periods, pairing))

    # Duplicate period indices fail closed with the same error as before.
    dup = periods[:3] + (periods[2],) + periods[3:]
    policy = _policy(rng)
    _assert_lean_equals_full(dup, _tax_input(rng, dup, policy))
    assert _outcome(tax_engine.calculate_cfads_and_cash_tax, dup, _tax_input(rng, dup, policy))[0] == "err"

    # An UNRESOLVED financing-income authority with a non-zero value fails closed.
    bad = TaxCalculationInput(
        policy=policy, opening_loss_vintages=(), period_interest=(),
        period_financing_income=(PeriodFinancingIncomeInput(2, 5.0, "UNRESOLVED"),),
    )
    out = _outcome(tax_engine.calculate_cfads_and_cash_tax, periods, bad)
    assert out[0] == "err" and "UNRESOLVED" in out[2]
    assert out == _outcome(tax_engine._cfads_and_cash_tax_via_full_tax, periods, bad)

    # A period that ends before it starts is a malformed axis: the full path reports it.
    broken = list(periods)
    broken[4] = OperatingPeriodResult(**{**broken[4].__dict__, "period_end": date(2000, 1, 1)})
    _assert_lean_equals_full(tuple(broken), _tax_input(rng, tuple(broken), policy))

    # No periods at all.
    _assert_lean_equals_full((), _tax_input(rng, (), policy))


def test_period_axis_plan_is_built_once_per_run_scope(monkeypatch):
    rng = random.Random("plan")
    periods = _periods(rng, "semiannual")
    tax_input = _tax_input(rng, periods, _policy(rng, tax_basis_periodisation=TaxBasisPeriodisation.CALENDAR_YEAR))
    builds = []
    real = tax_engine._build_tax_plan
    monkeypatch.setattr(tax_engine, "_build_tax_plan", lambda p: builds.append(1) or real(p))

    tax_engine.calculate_cfads_and_cash_tax(periods, tax_input)
    tax_engine.calculate_cfads_and_cash_tax(periods, tax_input)
    assert len(builds) == 2                      # no scope open: nothing is retained

    builds.clear()
    with engine_run_scope():
        tax_engine.calculate_cfads_and_cash_tax(periods, tax_input)
        tax_engine.calculate_cfads_and_cash_tax(periods, tax_input)
    assert len(builds) == 1                      # one plan for the whole scope
    assert current_run_scope() is None           # and nothing outlives it


# ---------------------------------------------------------------------------
# Loss ledger twin
# ---------------------------------------------------------------------------

def _ledger_outcome(fn, **kw):
    try:
        res = fn(**kw)
    except Exception as exc:  # noqa: BLE001
        return ("err", type(exc).__name__, str(exc))
    return ("ok", [repr(float(x if not hasattr(x, "taxable_income_after_lcf_keur")
                              else x.taxable_income_after_lcf_keur)) for x in res])


def test_after_loss_series_is_bit_identical_to_the_fifo_ledger():
    checked = 0
    for seed in range(400):
        rng = random.Random(f"ledger-{seed}")
        n = rng.randint(1, 25)
        first = 2030
        years = tuple(first + i for i in range(n))
        taxable = tuple(
            rng.choice([0.0, -0.0, rng.uniform(-3000.0, 3000.0), rng.uniform(-50.0, 50.0), 1e-13, -1e-13])
            for _ in range(n))
        vintages = tuple(
            OpeningTaxLossVintageInput(
                origin_tax_year=rng.choice([2024, 2026, 2029, 2030, 2031]),
                amount_keur=rng.uniform(0.0, 5000.0), source_label=rng.choice(["", "a", "b"]))
            for _ in range(rng.choice([0, 0, 1, 2, 4])))
        gate = tuple(rng.random() < 0.7 for _ in range(n)) if rng.random() < 0.5 else None
        kw = dict(
            taxable_income_before_lcf=taxable, tax_year_indices=years,
            opening_inputs=vintages, loss_carryforward_years=rng.choice([0, 1, 3, 5, 20]),
            loss_use_allowed=gate)
        assert _ledger_outcome(taxable_income_after_lcf_series, **kw) == _ledger_outcome(
            run_annual_fifo_ledger, **kw), seed
        checked += 1
    assert checked == 400

    # Gate length mismatch fails with the same message.
    bad = dict(taxable_income_before_lcf=(1.0,), tax_year_indices=(2030,), opening_inputs=(),
               loss_carryforward_years=5, loss_use_allowed=(True, False))
    assert _ledger_outcome(taxable_income_after_lcf_series, **bad) == _ledger_outcome(
        run_annual_fifo_ledger, **bad)
    assert _ledger_outcome(taxable_income_after_lcf_series, **bad)[0] == "err"


# ---------------------------------------------------------------------------
# Incremental SHL operating chain
# ---------------------------------------------------------------------------

def _shl_cases():
    from financial_engine.shl.contracts import (
        ShlDayCountConvention, ShlRepaymentMode, ShlWaterfallPolicy,
    )
    from financial_engine.shl.production import ShlConstructionInput, ShlOperatingPeriodInput
    from finco_core.inputs._models import ShlConstructionInterestMethod

    for seed in range(150):
        rng = random.Random(f"shl-{seed}")
        rate = rng.choice([0.0, 0.05, 0.08, 0.12])
        method = rng.choice(list(ShlConstructionInterestMethod))
        dcf_choices = [0.0, 0.5, 1.0] if method is ShlConstructionInterestMethod.COMPOUND_PERIODIC else [0.5, 1.0]
        construction = ShlConstructionInput(
            draw_keur=rng.uniform(100.0, 9000.0), annual_rate=rate, dcf=rng.choice(dcf_choices),
            period_index=1, construction_interest_method=method)
        policy = ShlWaterfallPolicy(
            annual_rate=rate, day_count_convention=rng.choice(list(ShlDayCountConvention)))
        bounds = _boundaries("semiannual", rng.randint(2, 30))
        mode = rng.choice([ShlRepaymentMode.BULLET, ShlRepaymentMode.CASH_SWEEP])
        n = len(bounds) - 1
        ops = tuple(
            ShlOperatingPeriodInput(
                period_index=2 + i, period_start=bounds[i], period_end=bounds[i + 1],
                cash_available_for_shl_keur=rng.choice([0.0, rng.uniform(0.0, 700.0)]),
                day_count_fraction=rng.choice([None, 0.5]), repayment_mode=mode,
                is_maturity_period=(i == n - 1))
            for i in range(n))
        yield construction, policy, ops


def test_shl_chain_matches_recomputing_the_whole_prefix():
    from financial_engine.shl.production import _ShlOperatingChain, compute_shl_schedule
    from financial_engine.shl.waterfall import compute_shl_waterfall_period

    compared = 0
    for construction, policy, ops in _shl_cases():
        chain = _ShlOperatingChain(construction, policy)
        opening = chain.construction_result.closing_balance_keur
        for k, op in enumerate(ops):
            peek = chain.evaluate(op)
            assert chain.opening == opening                  # evaluate never advances
            via_chain = chain.advance(op)
            assert repr(via_chain) == repr(peek)
            # The previous behaviour: derive the entire schedule prefix, keep the last period.
            via_prefix = compute_shl_schedule(construction, ops[: k + 1], policy).operating[-1]
            assert repr(via_chain) == repr(via_prefix)
            # And the primitive, rolled by hand from the previous closing balance.
            from financial_engine.shl.day_count import compute_shl_dcf
            dcf = (op.day_count_fraction if op.day_count_fraction is not None else
                   compute_shl_dcf(op.period_start, op.period_end, policy.day_count_convention))
            by_hand = compute_shl_waterfall_period(
                opening_balance_keur=opening, annual_rate=policy.annual_rate,
                day_count_fraction=dcf, cash_available_for_shl_keur=op.cash_available_for_shl_keur,
                period_index=op.period_index, repayment_mode=op.repayment_mode,
                is_maturity_period=op.is_maturity_period)
            assert repr(via_chain) == repr(by_hand)
            opening = via_chain.closing_balance_keur
            compared += 1
    assert compared > 500


def test_shl_chain_fails_closed_exactly_as_the_schedule_does():
    from financial_engine.shl.contracts import ShlDayCountConvention, ShlWaterfallPolicy
    from financial_engine.shl.production import (
        ShlConstructionInput, ShlOperatingPeriodInput, _ShlOperatingChain, compute_shl_schedule,
    )
    construction = ShlConstructionInput(draw_keur=1000.0, annual_rate=0.08, dcf=1.0, period_index=1)
    policy = ShlWaterfallPolicy(annual_rate=0.08, day_count_convention=list(ShlDayCountConvention)[0])
    ok = ShlOperatingPeriodInput(2, date(2031, 6, 30), date(2031, 12, 31), 10.0)
    for bad in (
        ShlOperatingPeriodInput(3, date(2032, 1, 1), date(2032, 6, 30), -1.0),
        ShlOperatingPeriodInput(3, date(2032, 1, 1), date(2032, 6, 30), math.nan),
        ShlOperatingPeriodInput(3, date(2032, 1, 1), date(2032, 6, 30), 1.0, drawdown_keur=5.0),
    ):
        with pytest.raises(ValueError) as via_schedule:
            compute_shl_schedule(construction, (ok, bad), policy)
        chain = _ShlOperatingChain(construction, policy)
        chain.advance(ok)
        with pytest.raises(ValueError) as via_chain:
            chain.advance(bad)
        assert str(via_chain.value) == str(via_schedule.value)

    with pytest.raises(ValueError, match="annual_rate"):
        _ShlOperatingChain(construction, ShlWaterfallPolicy(
            annual_rate=0.09, day_count_convention=policy.day_count_convention))


# ---------------------------------------------------------------------------
# Run-scoped memo
# ---------------------------------------------------------------------------

def test_scoped_memo_is_inert_outside_a_run_scope_and_exact_inside_one():
    calls = []

    @scoped_memo(maxsize=16)
    def f(x, *, k=1):
        calls.append((x, k))
        return (x, k)

    f(1.0)
    f(1.0)
    assert len(calls) == 2                       # no scope: never cached

    with engine_run_scope():
        a = f(1.0)
        assert f(1.0) is a and len(calls) == 3   # cached inside the scope
        assert f(1, k=1) is not a                # 1 vs 1.0: equal by == but not identical
        assert f(0.0) is not f(-0.0)             # sign of zero is part of the key
        assert f(1.0, k=2) is not a              # keyword arguments are part of the key
        with engine_run_scope():                 # nested scope joins the enclosing one
            assert f(1.0) is a
    with engine_run_scope():
        assert f(1.0) is not a                   # a new run never sees an old run's results


def test_scoped_memo_never_caches_errors_or_unpicklable_arguments():
    n = {"calls": 0}

    @scoped_memo(maxsize=4)
    def boom(x):
        n["calls"] += 1
        raise ValueError("fails closed")

    with engine_run_scope():
        for _ in range(2):
            with pytest.raises(ValueError):
                boom(1)
    assert n["calls"] == 2

    seen = []

    @scoped_memo(maxsize=4)
    def ident(fn):
        seen.append(1)
        return fn

    with engine_run_scope():
        ident(lambda: None)                      # lambdas cannot be pickled: computed, not cached
        ident(lambda: None)
    assert len(seen) == 2


def test_scoped_memo_evicts_oldest_beyond_maxsize():
    calls = []

    @scoped_memo(maxsize=2)
    def f(x):
        calls.append(x)
        return object()

    with engine_run_scope():
        a = f(1)
        f(2)
        f(3)                                     # evicts 1
        assert f(1) is not a
        assert calls == [1, 2, 3, 1]


# ---------------------------------------------------------------------------
# A real Run still reproduces the pre-optimisation outputs
# ---------------------------------------------------------------------------

# Recorded from the unmodified engine (base 1951e26, Python 3.12) on the generic Solar and Wind
# factories.
# Tolerance is a few ulps only because the recording and CI may use different libm builds;
# bit-for-bit identity versus the previous code is established by the twins above and by the
# full-result fingerprint comparison recorded in the pull request.
_GOLDEN = {
    "Solar": {
        "pure_equity_xirr": 0.28644843541096987,
        "pure_equity_moic": 38.348665154297656,
        "total_sponsor_xirr": 0.11486411444433564,
        "total_sponsor_moic": 4.345774008784585,
        "total_sponsor_receipts_keur": 38783.89386919953,
        "total_gross_dividend_paid_keur": 19174.332577148827,
        "total_shl_cash_contributed_keur": 8424.507761057394,
        "total_shl_cash_interest_received_keur": 10940.956438343463,
        "total_shl_principal_received_keur": 8668.604853707242,
    },
    "Wind": {
        "pure_equity_xirr": 0.5509342400404167,
        "pure_equity_moic": 182.12576759786344,
        "total_sponsor_xirr": 0.16020267886567827,
        "total_sponsor_moic": 9.806743846368859,
        "total_sponsor_receipts_keur": 117452.3662192766,
        "total_gross_dividend_paid_keur": 91062.88379893173,
        "total_shl_cash_contributed_keur": 11476.693595679637,
        "total_shl_cash_interest_received_keur": 14912.788824665246,
        "total_shl_principal_received_keur": 11476.693595679637,
    },
}


def _run(project_type):
    from app import project_factories as pf
    from app.services import production_financial_authority as pfa

    factory = {"Solar": pf.create_default_solar_project, "Wind": pf.create_default_wind_project}
    pfa._POLICY_RUN_CACHE.clear()      # a memo hit would hide the work these tests measure
    return pfa.run_clean_production(factory[project_type](), project_type=project_type)


@pytest.mark.parametrize("project_type", sorted(_GOLDEN))
def test_real_run_reproduces_pre_optimisation_outputs(project_type):
    g2c = _run(project_type).g2c_result
    for name, expected in _GOLDEN[project_type].items():
        assert getattr(g2c, name) == pytest.approx(expected, rel=1e-12, abs=0.0), name


def test_one_run_computes_each_financing_model_once_per_engine_evaluation(monkeypatch):
    """The waterfall must not recompute an identical financing result (it did, 2x per evaluation)."""
    import financial_engine.shareholder_waterfall as wf_pkg
    import financial_engine.shareholder_waterfall.model as wf

    real_fin = wf.run_project_financing_model
    real_wf = wf_pkg.run_project_shareholder_waterfall_model
    fin_calls, wf_calls = [], []

    def count_fin(*args, **kwargs):
        fin_calls.append(1)
        return real_fin(*args, **kwargs)

    def count_wf(*args, **kwargs):
        wf_calls.append(1)
        return real_wf(*args, **kwargs)

    monkeypatch.setattr(wf, "run_project_financing_model", count_fin)
    monkeypatch.setattr(wf_pkg, "run_project_shareholder_waterfall_model", count_wf)
    _run("Solar")
    assert len(wf_calls) >= 2                    # seed + at least one DSRA fixed-point evaluation
    assert len(fin_calls) == len(wf_calls)       # one financing model per evaluation, not two


def test_a_run_finishes_far_inside_a_catastrophic_ceiling():
    """Deliberately loose: guards a regression back to the pre-optimisation order of
    magnitude without depending on runner hardware. Real timings: tools/bench_model_runtime.py."""
    started = time.perf_counter()
    _run("Solar")
    assert time.perf_counter() - started < 120.0
