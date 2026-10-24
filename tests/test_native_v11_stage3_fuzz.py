"""Stage 3b: the native senior-debt model evaluation is run_senior_debt_model, exactly — or it declines.

Real ``SeniorDebtModelInput`` values (with and without a shareholder loan) are captured from canonical
Solar and EV Runs and perturbed deterministically: DSCR target, senior rate, gearing, sizing mode
(DSCR_SCULPTED / COMBINED_MINIMUM), damping, iteration caps (forcing non-convergence), tolerances,
terminal balloon permission, initial debt guess, eligible cost, corporate tax rate, ATAD, loss gate, loss
carry-forward window, cash-tax lag, SHL rate / repayment mode / iteration cap / tolerance, and the OD-R SHL
maturity context (none, PROVISIONAL with a fresh ledger, AUTHORITATIVE).

Each case runs canonically and through Stage 3 in separate engine Run scopes:
* Stage 3 returns a result  -> the canonical evaluation returned the pickle-identical result and wrote the
  identical maturity ledger;
* Stage 3 declines           -> it wrote nothing (the canonical replay then decides);
* Stage 3 raises             -> only after its commit point (PROVISIONAL ledger), with the identical
  canonical exception text and ledger;
* the canonical evaluation raises -> Stage 3 never returns a value.
"""
from __future__ import annotations

import collections
import dataclasses
import pickle
import random

import pytest

pytestmark = pytest.mark.usefixtures("stage3_artifacts")


@pytest.fixture(scope="module")
def captured():
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    import financial_engine.financing.project as proj
    real = proj._senior_debt_model
    out = {"shl": [], "plain": []}

    def spy(model_input, *, shl_maturity_context=None):
        bucket = out["shl" if model_input.shareholder_loan is not None else "plain"]
        if len(bucket) < 6:
            bucket.append(model_input)
        return real(model_input, shl_maturity_context=shl_maturity_context)

    proj._senior_debt_model = spy
    try:
        for project in ("Solar", "Generic EV Charging Reference"):
            pfa._POLICY_RUN_CACHE.clear()
            run_project(project, "Base")
    finally:
        proj._senior_debt_model = real
        pfa._POLICY_RUN_CACHE.clear()
    assert out["shl"] and out["plain"]
    return out["shl"] + out["plain"]


def _ledger(ctx):
    if ctx is None or ctx.ledger is None:
        return ()
    return tuple((s.closing_keur.hex(), s.period_index, s.tolerance_keur.hex()) for s in ctx.ledger.shortfalls)


def _context(kind):
    from financial_engine.shl.maturity_authority import ShlMaturityAuthority, ShlMaturityContext
    if kind == "provisional":
        return ShlMaturityContext.provisional_pass()
    if kind == "authoritative":
        return ShlMaturityContext(ShlMaturityAuthority.AUTHORITATIVE)
    return None


def _canonical(inputs, kind):
    from financial_engine.orchestrator import run_senior_debt_model
    from financial_engine.run_scope import engine_run_scope
    ctx = _context(kind)
    with engine_run_scope():
        try:
            r = run_senior_debt_model(inputs, shl_maturity_context=ctx)
        except Exception as exc:  # noqa: BLE001
            return "raise", f"{type(exc).__name__}: {exc}", _ledger(ctx)
    return "ok", pickle.dumps(r), _ledger(ctx)


def _stage3(inputs, kind):
    from financial_engine.native_v11 import stage3
    from financial_engine.native_v11.config import Stage3Config, stage3_run
    from financial_engine.run_scope import engine_run_scope
    ctx = _context(kind)
    with engine_run_scope(), stage3_run(Stage3Config(mode="candidate")) as st:
        try:
            r = stage3.run_senior_debt_model(inputs, shl_maturity_context=ctx)
        except Exception as exc:  # noqa: BLE001
            return "raise", f"{type(exc).__name__}: {exc}", _ledger(ctx), st.as_dict()
    if r is None:
        return "decline", None, _ledger(ctx), st.as_dict()
    return "ok", pickle.dumps(r), _ledger(ctx), st.as_dict()


def _maybe(rng, p=0.35):
    return rng.random() < p


def _variant(rng, inputs):
    from financial_engine.policies.tax import TaxLossUtilisationGate
    from financial_engine.senior_debt.policy import SeniorDebtSizingMode
    from financial_engine.shl.contracts import ShlRepaymentMode
    pol, sdi, tax = inputs.senior_debt_policy, inputs.senior_debt_inputs, inputs.tax
    changes = {}
    if _maybe(rng):
        changes["target_dscr"] = rng.choice([1.15, 1.3, 1.6, 2.5])
    if _maybe(rng) and pol.annual_fixed_rate is not None:
        changes["annual_fixed_rate"] = pol.annual_fixed_rate * rng.choice([0.5, 1.5, 2.5])
    if _maybe(rng):
        changes["maximum_gearing"] = rng.choice([0.5, 0.7, 0.9])
    if _maybe(rng, 0.25):
        changes["sizing_mode"] = rng.choice([SeniorDebtSizingMode.DSCR_SCULPTED, SeniorDebtSizingMode.COMBINED_MINIMUM])
    if _maybe(rng, 0.25):
        changes["damping_alpha"] = rng.choice([0.7, 0.4])
    if _maybe(rng, 0.15):
        changes["maximum_iterations"] = rng.choice([1, 3])
    if _maybe(rng, 0.25):
        changes["convergence_tolerance_keur"] = pol.convergence_tolerance_keur * rng.choice([1e-3, 1e3])
    if _maybe(rng, 0.2):
        changes["convergence_relative_tolerance"] = 0.0
    if _maybe(rng, 0.25):
        changes["permit_terminal_balloon"] = not pol.permit_terminal_balloon
    if _maybe(rng, 0.15):
        changes["maturity_period_index"] = pol.maturity_period_index - rng.choice([1, 4])
    pol = dataclasses.replace(pol, **changes)
    if _maybe(rng):
        sdi = dataclasses.replace(sdi, initial_debt_guess_keur=sdi.initial_debt_guess_keur * rng.choice([0.0, 0.1, 3.0]))
    if _maybe(rng):
        sdi = dataclasses.replace(sdi, eligible_project_cost_keur=sdi.eligible_project_cost_keur * rng.choice([0.5, 1.4]))
    tpol = tax.policy
    tchanges = {}
    if _maybe(rng):
        tchanges["corporate_rate"] = rng.choice([0.0, 0.1, 0.3])
    if _maybe(rng, 0.25):
        tchanges.update(atad_enabled=True, atad_ebitda_limit=0.3,
                        atad_de_minimis_threshold_keur_annual=rng.choice([0.0, 100.0, 3000.0]))
    if _maybe(rng, 0.25):
        tchanges["loss_utilisation_gate"] = TaxLossUtilisationGate.EBT_POSITIVE
    if _maybe(rng, 0.25):
        tchanges["loss_carryforward_years"] = rng.choice([0, 2, 10])
    if _maybe(rng, 0.25):
        tchanges["cash_tax_payment_lag_periods"] = rng.choice([1, 2])
    tax = dataclasses.replace(tax, policy=dataclasses.replace(tpol, **tchanges))
    shl = inputs.shareholder_loan
    if shl is not None:
        schanges = {}
        if _maybe(rng):
            schanges["annual_fixed_rate"] = shl.annual_fixed_rate * rng.choice([0.5, 2.0])
        if _maybe(rng, 0.3):
            schanges["repayment_mode"] = rng.choice([ShlRepaymentMode.BULLET, ShlRepaymentMode.CASH_SWEEP])
        if _maybe(rng, 0.15):
            schanges["maximum_iterations"] = rng.choice([2, 3])
        if _maybe(rng, 0.2):
            schanges["convergence_tolerance_keur"] = shl.convergence_tolerance_keur * rng.choice([1e-3, 1e3])
        shl = dataclasses.replace(shl, **schanges)
    return dataclasses.replace(inputs, senior_debt_policy=pol, senior_debt_inputs=sdi, tax=tax, shareholder_loan=shl)


@pytest.mark.parametrize("seed", range(5))
def test_perturbed_senior_debt_models_are_exact_or_declined(captured, seed):
    rng = random.Random(7000 + seed)
    tally = collections.Counter()
    for k in range(24):
        base = captured[(seed * 24 + k) % len(captured)]
        try:
            inputs = _variant(rng, base)
        except (TypeError, ValueError):
            tally["invalid-input"] += 1
            continue
        kind = rng.choice(["none", "none", "provisional", "authoritative"]) if inputs.shareholder_loan else "none"
        ref = _canonical(inputs, kind)
        got = _stage3(inputs, kind)
        if got[0] == "ok":
            assert ref[0] == "ok", (ref[1], got[3])
            assert got[1] == ref[1]
            assert got[2] == ref[2]
        elif got[0] == "decline":
            assert got[2] == (), "a declined evaluation must leave no effect"
        else:
            assert kind == "provisional", got
            assert ref[0] == "raise" and got[1] == ref[1] and got[2] == ref[2]
        tally[f"{ref[0]}->{got[0]}"] += 1
    assert tally["ok->ok"] >= 8, dict(tally)
