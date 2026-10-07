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

import hashlib
import math
import random
import sys
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
from financial_engine.tax import engine as tax_engine
from financial_engine.tax.loss_ledger import run_annual_fifo_ledger


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
    from financial_engine.run_scope import engine_run_scope

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
    from financial_engine.run_scope import current_run_scope, engine_run_scope

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
# The reported (full) tax path and the SHL schedule vs the unmodified engine
# ---------------------------------------------------------------------------

def full_tax_digests(count: int = 60) -> dict[str, str]:
    """sha256 of ``repr(calculate_tax(...))`` (or of the error) for seeded synthetic cases."""
    out = {}
    for seed in range(count):
        style = ("semiannual", "calendar", "irregular")[seed % 3]
        rng = random.Random(f"digest-{style}-{seed}")
        periods = _periods(rng, style)
        tax_input = _tax_input(rng, periods, _policy(rng))
        try:
            payload = repr(tax_engine.calculate_tax(periods, tax_input))
        except Exception as exc:  # noqa: BLE001 - the error is part of the behaviour
            payload = f"ERR {type(exc).__name__}: {exc}"
        out[f"{style}-{seed}"] = hashlib.sha256(payload.encode()).hexdigest()
    return out


def shl_schedule_digests() -> dict[str, str]:
    from financial_engine.shl.production import compute_shl_schedule

    out = {}
    for n, (construction, policy, ops) in enumerate(_shl_cases()):
        out[f"shl-{n}"] = hashlib.sha256(
            repr(compute_shl_schedule(construction, ops, policy)).encode()).hexdigest()
    return out


# Recorded from the unmodified engine (base 1951e26): first 80 bits of sha256 over ``repr`` of the
# full result (or of the raised error). Python 3.12 changed float ``sum()`` to compensated
# summation, so the tax digests are recorded per interpreter family; the SHL schedule has no
# summation and is version independent.
_FULL_TAX_DIGESTS_PY311 = {
    "calendar-1": "a225330bd13dbba99702",
    "calendar-4": "a220662c05ca90aecae3",
    "calendar-7": "89ba24b4f6589c155cbd",
    "calendar-10": "ba123a98bfc3696113d5",
    "calendar-13": "4da069f755ee607d91a8",
    "calendar-16": "9259a29e7c15d89d5e11",
    "calendar-19": "47cc5adb60ea58963a7c",
    "calendar-22": "0f25fed0bca654f23dcc",
    "calendar-25": "0910dcfeb378558416b6",
    "calendar-28": "6300b18567beebb67643",
    "calendar-31": "3948474c9377eadfbba7",
    "calendar-34": "7cc4f78d309302cf6723",
    "calendar-37": "e0b8b7e6453479dac743",
    "calendar-40": "dc230e91faa053b07377",
    "calendar-43": "a386320eba90ac978dad",
    "calendar-46": "f08dff0fc75268615749",
    "calendar-49": "096d4d0f0e4034ce9d5b",
    "calendar-52": "c332371db5d3f66f59e7",
    "calendar-55": "7a25956a3dede0ebdb27",
    "calendar-58": "603619ff317bd107f17c",
    "irregular-2": "1c661a60b493e0d7876b",
    "irregular-5": "90b1fbbf9e0bd39aa6c0",
    "irregular-8": "4d8244dbb06e5aeef634",
    "irregular-11": "4b871b608ca815547a17",
    "irregular-14": "6e8811213c30bfe46419",
    "irregular-17": "07c7c3f9278b03b2f858",
    "irregular-20": "6d340d98346c3d85d238",
    "irregular-23": "afe0ef10b51c60200a75",
    "irregular-26": "da2db216c5065a43e406",
    "irregular-29": "a8282bd44d59d925bbee",
    "irregular-32": "ff24e8eefb6a44005a0c",
    "irregular-35": "6aa3d9ef08491327492a",
    "irregular-38": "cb92e55e2a5b751a33ee",
    "irregular-41": "3edebd4ab19f3a07f686",
    "irregular-44": "a4f980558b98e35369e1",
    "irregular-47": "5ed5cc552cfec3ae1aa6",
    "irregular-50": "c75b406e9bab1f0b79e4",
    "irregular-53": "c848b825b2dcab492d1e",
    "irregular-56": "324246a9f6b2e68de377",
    "irregular-59": "fb7326586c9623655122",
    "semiannual-0": "9d6089e28b89989b1971",
    "semiannual-3": "eba0a36d0d15cb9cb466",
    "semiannual-6": "93809301fe4096b60ea1",
    "semiannual-9": "cbab8ac8389f70d13d4f",
    "semiannual-12": "dd9adb16de78b8b0ca2d",
    "semiannual-15": "33d1cca8a09c29e73292",
    "semiannual-18": "92e7024552b2cb4fba78",
    "semiannual-21": "ee32d9d36f2137ff8b09",
    "semiannual-24": "f169a0367902c256259f",
    "semiannual-27": "b1f13b05fd22bf0c26b2",
    "semiannual-30": "1e7081b590671be84b9d",
    "semiannual-33": "1c21c34205f8d9e0ec29",
    "semiannual-36": "aee5060b3b8c8ac4d41b",
    "semiannual-39": "0720af03911673525372",
    "semiannual-42": "9e2a4333aba502ac040b",
    "semiannual-45": "84eb0ab04e0b61f517b4",
    "semiannual-48": "4e27e5c8891175f07ded",
    "semiannual-51": "8af71d1bdf518f1b8c22",
    "semiannual-54": "7397e4c3481f5d5c13df",
    "semiannual-57": "405f49841530516c019e",
}

_FULL_TAX_DIGESTS_PY312 = {
    "calendar-1": "a225330bd13dbba99702",
    "calendar-4": "a220662c05ca90aecae3",
    "calendar-7": "89ba24b4f6589c155cbd",
    "calendar-10": "ba123a98bfc3696113d5",
    "calendar-13": "4da069f755ee607d91a8",
    "calendar-16": "9259a29e7c15d89d5e11",
    "calendar-19": "dd97530b63eef3078f7e",
    "calendar-22": "0f25fed0bca654f23dcc",
    "calendar-25": "0910dcfeb378558416b6",
    "calendar-28": "6300b18567beebb67643",
    "calendar-31": "3948474c9377eadfbba7",
    "calendar-34": "7cc4f78d309302cf6723",
    "calendar-37": "e0b8b7e6453479dac743",
    "calendar-40": "dc230e91faa053b07377",
    "calendar-43": "a386320eba90ac978dad",
    "calendar-46": "f08dff0fc75268615749",
    "calendar-49": "096d4d0f0e4034ce9d5b",
    "calendar-52": "c332371db5d3f66f59e7",
    "calendar-55": "7a25956a3dede0ebdb27",
    "calendar-58": "f126d3a091895941eaad",
    "irregular-2": "1c661a60b493e0d7876b",
    "irregular-5": "b90a6521c04e93d54aa2",
    "irregular-8": "4d8244dbb06e5aeef634",
    "irregular-11": "79bd988dd0ed688ee836",
    "irregular-14": "eb129fd6de3266a6690a",
    "irregular-17": "7e5a703674504f9d02f3",
    "irregular-20": "39aed48d67a3304d8339",
    "irregular-23": "afe0ef10b51c60200a75",
    "irregular-26": "b46206520ce68c1aebfc",
    "irregular-29": "51b1e1abb9d5d43703df",
    "irregular-32": "8e72f3e053d2b58b94ca",
    "irregular-35": "871476cca428422d3c66",
    "irregular-38": "cb92e55e2a5b751a33ee",
    "irregular-41": "77df7ecdda4cb6ff5254",
    "irregular-44": "d330ddd88e21d6c0e39d",
    "irregular-47": "5ed5cc552cfec3ae1aa6",
    "irregular-50": "ec74b779d64e5e0bfb47",
    "irregular-53": "58da1a5d3a8f97fdcac1",
    "irregular-56": "fcc845d1237b9bad2b96",
    "irregular-59": "53a35ddd6da9bea284e9",
    "semiannual-0": "e8c569f801f580b671e1",
    "semiannual-3": "df7102340f7ac34e43a7",
    "semiannual-6": "f2fb7d5b9914f6e5ced9",
    "semiannual-9": "c36e9c2e1ed7cb2e9341",
    "semiannual-12": "2f8930efcc8c5094e613",
    "semiannual-15": "953a7d9a1b1aa86a09b5",
    "semiannual-18": "d8ae34fdc1be8c0a562d",
    "semiannual-21": "e34cddc836ffaee1ec39",
    "semiannual-24": "0ffe8c262e7240092b90",
    "semiannual-27": "c6a4b78b03de032ac11f",
    "semiannual-30": "cfa485abd253840e5864",
    "semiannual-33": "c7f67a364aff8007ce6f",
    "semiannual-36": "6fc47ebe614b3985d36d",
    "semiannual-39": "e5488f2a96e65f178573",
    "semiannual-42": "be3fedbe5d1e5904e197",
    "semiannual-45": "8519da1740b830efb938",
    "semiannual-48": "200a7e543c62f7c3bb18",
    "semiannual-51": "b5ba89724036c28bdb21",
    "semiannual-54": "a9bccc3303fa01b8f3ef",
    "semiannual-57": "a901cad72211fbee1e4d",
}

_SHL_SCHEDULE_DIGESTS = {
    "shl-0": "a9c6efbbf57f543c1da6",
    "shl-1": "30fbe580faa08c66b230",
    "shl-2": "433c2f050db0558cf1af",
    "shl-3": "274d72523f41561feec4",
    "shl-4": "bd5e9f6f59ebda92f618",
    "shl-5": "f7ff11ecac1fc9a69d6c",
    "shl-6": "d0dea4d6975db328ab7f",
    "shl-7": "e37d3be61ac31638eaaf",
    "shl-8": "a3a1ec92d19a063ad727",
    "shl-9": "338d183d1bf4b35879ae",
    "shl-10": "8a398a72e099707324d7",
    "shl-11": "c9bb9f00f3a06077e600",
    "shl-12": "3c0c2636610e96b0954d",
    "shl-13": "eeda46df34beb19c10eb",
    "shl-14": "49335b2814610d6638d9",
    "shl-15": "799725741a9d17c04864",
    "shl-16": "1ba10fc3857cf935abcf",
    "shl-17": "5a78f8c0614ff5ab0e1e",
    "shl-18": "f171d0a1904be9a45c92",
    "shl-19": "ed3c25842f0396e1ffd7",
    "shl-20": "93bf1e8e1bc40f2b834c",
    "shl-21": "e048e0006ee61ea51b55",
    "shl-22": "5c6a2d09b057442da8f1",
    "shl-23": "f2bdb8fc047e2fc60a11",
    "shl-24": "678e860939ba336ef5bd",
    "shl-25": "0a9297f917323c55bc6e",
    "shl-26": "12816789ebf25db79796",
    "shl-27": "0f63189ffa28eb8f6b47",
    "shl-28": "decb7ece221fca3b8dd6",
    "shl-29": "92a84f547a3f239c9934",
    "shl-30": "66ad4d9cf17ca6a557fe",
    "shl-31": "f8a11a5e397f27261092",
    "shl-32": "91408d3f609f06043ac8",
    "shl-33": "2fed1efc75db6880fdc4",
    "shl-34": "c3ed709bd70344cb9e03",
    "shl-35": "ee0e9d76397e974b7c2c",
    "shl-36": "11925c3014a53f7c5021",
    "shl-37": "24237e9b716e53d3d5b3",
    "shl-38": "77d17970da6e1bb008d7",
    "shl-39": "3e89294fecc55acb7d21",
    "shl-40": "c0d543bd54ed779b2105",
    "shl-41": "ba0b888793eaa6f4caf6",
    "shl-42": "0b777366ada91c51d87f",
    "shl-43": "69104ede1d5a355f155b",
    "shl-44": "c0d9e0b0e534dc0e887b",
    "shl-45": "19c35a54fc30b729185a",
    "shl-46": "2f71f9daeae93497fa8e",
    "shl-47": "ca615eafdd2d0306d415",
    "shl-48": "b5b4c93f63f7494e0f8b",
    "shl-49": "f1e45106eadf06fcb0d4",
    "shl-50": "33d945bf31c5dba44782",
    "shl-51": "cdac422ed9cf46870fc7",
    "shl-52": "e431b190d4c704075831",
    "shl-53": "776ba7aea4221d7c18c0",
    "shl-54": "491ce39e407707292c3f",
    "shl-55": "640a618239a86d4f452a",
    "shl-56": "ee98690217f24be501e6",
    "shl-57": "219be87d6d90b8feeb48",
    "shl-58": "b0e059e7acaba763a780",
    "shl-59": "06780192dc0ada1a5ffe",
    "shl-60": "19e570eca6f880179bf3",
    "shl-61": "827bcbaf17116bbfa445",
    "shl-62": "63698336114578a05a24",
    "shl-63": "8181d72f98f4dd74c419",
    "shl-64": "f1e279b2a7f122329dba",
    "shl-65": "77b5fa8aa516e85162de",
    "shl-66": "012bceef413109a95025",
    "shl-67": "08a652b5f3547ae60149",
    "shl-68": "e980d52718195826ffae",
    "shl-69": "63927a221bdb34e0ceef",
    "shl-70": "3af4df695fd1594383bd",
    "shl-71": "6f1a692edfa59a6a4448",
    "shl-72": "dbc23cb586908ed8ff3f",
    "shl-73": "b58c16f75e75f51c5774",
    "shl-74": "bfe3b4f9389db9f2b619",
    "shl-75": "6a4c93bab38b1f0338bc",
    "shl-76": "cdba4691f610797cee3b",
    "shl-77": "46744d3680d7354c6c26",
    "shl-78": "586cd91cf30f937c1f8d",
    "shl-79": "2db12fadee0e28b606ca",
    "shl-80": "31dfcf4c1ba238f549be",
    "shl-81": "917156e8a9c4f730902d",
    "shl-82": "5843cbfd9c8f66c6361f",
    "shl-83": "a31c27b2541e8f076af9",
    "shl-84": "2919dbd79aebe1edb0dd",
    "shl-85": "a8e09f846b4e55a7b149",
    "shl-86": "9c7c826ccf2ba95fb9e7",
    "shl-87": "35960dd670d05ba87f67",
    "shl-88": "0694d9d19ed98af75dce",
    "shl-89": "bba3d5556edcf29dc448",
    "shl-90": "d9aeb9a48017edf26bc0",
    "shl-91": "52837b40ea3907c7b6f1",
    "shl-92": "6dd931a2ce3c9f4c6679",
    "shl-93": "7cfaa01129f6c234f19a",
    "shl-94": "56b7cff0750c9c345567",
    "shl-95": "fe8a021aa43104de1cb0",
    "shl-96": "5a57862a25ce8356b976",
    "shl-97": "f43aac66a62bcc824308",
    "shl-98": "4643997eda6692f09d2c",
    "shl-99": "bea503cf33c2ec95cbb1",
    "shl-100": "88156b245daeb5c6309b",
    "shl-101": "63571374b607169d5f37",
    "shl-102": "96ef20552ec0655126d3",
    "shl-103": "a6ffac6b82afbf5932be",
    "shl-104": "4d166b5eb98454b353e1",
    "shl-105": "2481aff3ff5268bd71ab",
    "shl-106": "c865397ff38fdda68999",
    "shl-107": "2874c667126b0640f194",
    "shl-108": "9333ecc5e8eb1f7760f3",
    "shl-109": "433739bac70f56aaa0af",
    "shl-110": "99a6aa8108e60358a5ad",
    "shl-111": "265ff36986b7fa9e79ec",
    "shl-112": "7e274580c07ca10ff115",
    "shl-113": "95adfc2d3ad83b6997ee",
    "shl-114": "90799facf216d5c53f64",
    "shl-115": "3d81c79f7165361aba6f",
    "shl-116": "5c15578db19a86195269",
    "shl-117": "2f737eb70eb3543b1d83",
    "shl-118": "df46ef04666592d2656c",
    "shl-119": "bc41db072256ab6ed3aa",
    "shl-120": "62c6435b9433945a50e9",
    "shl-121": "3db5e3ecd3fcdecac2a9",
    "shl-122": "48f94458cacea4869145",
    "shl-123": "a3607c8dca2aa5499fd6",
    "shl-124": "97e25210288e36ab3f68",
    "shl-125": "ad163f933243f4634218",
    "shl-126": "40983ad7ec6d87651aab",
    "shl-127": "3f89dd91c6048b46d533",
    "shl-128": "3eb69af6237325e15ed6",
    "shl-129": "7111bb26becbdac8e855",
    "shl-130": "7fcb8a9931010adc3908",
    "shl-131": "afc25c0b71697046d0a7",
    "shl-132": "c231184fb8ac7ead8e30",
    "shl-133": "c85597e60fab63caa30f",
    "shl-134": "4fc75acab47aa94cb9f6",
    "shl-135": "d74ba00c206c3878c893",
    "shl-136": "b9d9dbd5558a08c4c388",
    "shl-137": "5f8811cf685f3f780045",
    "shl-138": "d5be64ceb9c97d5302f7",
    "shl-139": "72adb6364686010f22e7",
    "shl-140": "8e8c51acc37237bf0859",
    "shl-141": "a7576e1e053a86e28960",
    "shl-142": "01291a908d0d729bcd04",
    "shl-143": "04a8a2b416b0165b52f9",
    "shl-144": "2c61c07743db3f2d9014",
    "shl-145": "e97a95af72d05f4c63a6",
    "shl-146": "1044156ec47d318af540",
    "shl-147": "8ef9da80c89458ad7f1b",
    "shl-148": "ae0a9f10f5ff8f609400",
    "shl-149": "60781762c4990c436fe5",
}


def test_reported_tax_path_matches_the_unmodified_engine():
    """calculate_tax feeds every reported tax figure; its refactor must change no bit."""
    expected = _FULL_TAX_DIGESTS_PY312 if sys.version_info >= (3, 12) else _FULL_TAX_DIGESTS_PY311
    got = {k: v[:20] for k, v in full_tax_digests().items()}
    assert got == expected


def test_shl_schedule_matches_the_unmodified_engine():
    got = {k: v[:20] for k, v in shl_schedule_digests().items()}
    assert got == _SHL_SCHEDULE_DIGESTS


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
    from financial_engine.tax.loss_ledger import taxable_income_after_lcf_series

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
    from financial_engine.run_scope import engine_run_scope, scoped_memo

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
    from financial_engine.run_scope import engine_run_scope, scoped_memo

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
    from financial_engine.run_scope import engine_run_scope, scoped_memo

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
