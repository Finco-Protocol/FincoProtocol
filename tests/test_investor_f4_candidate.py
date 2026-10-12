"""Offline agreement validation and delegation, never production activation."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.model_v2.investor_f4_candidate.adapter import (
    evaluate_candidate, to_existing_inputs, validate_candidate_result,
)
from app.model_v2.investor_f4_candidate.contracts import (
    Contribution, DistributionEvidence, Entitlements, InvestmentClass, Investor, InvestorAgreement, Priority,
)
from finco_core.sponsor.waterfall_runner import run_waterfall

DATES = (date(2030, 1, 1), date(2030, 7, 1), date(2031, 1, 1))


def agreement(two=False):
    investors = ((Investor("alpha", InvestmentClass.COMMON_EQUITY, 0.7, 70),
                  Investor("beta", InvestmentClass.COMMON_EQUITY, 0.3, 30)) if two else
                 (Investor("alpha", InvestmentClass.COMMON_EQUITY, 1.0, 100),))
    return InvestorAgreement(
        "synthetic-agreement", investors,
        tuple(Contribution(i.investor_id, DATES[0], i.commitment_keur) for i in investors),
        Entitlements((Priority.RESIDUAL,)),
        DistributionEvidence("synthetic-cash-receipt", DATES, (0.0, 60.0, 100.0)),
    )


@pytest.mark.parametrize("two", [False, True])
def test_delegated_common_cash_exactly_equals_existing_runner(two):
    contract = agreement(two)
    before = contract.to_json()
    result = evaluate_candidate(contract)
    assert result == run_waterfall(to_existing_inputs(contract))
    assert contract.to_json() == before
    for p, cash in zip(result.period_results, contract.evidence.net_equity_cash_keur):
        assert sum(a for _, a in p.tier_entries[0].allocated_per_sponsor_keur) == pytest.approx(cash, abs=1e-6)
        assert p.total_remaining_cash_keur == 0
    if two:
        assert result.total_distributions_by_sponsor_keur == (("alpha", 112.0), ("beta", 48.0))
    else:
        assert result.total_distributions_by_sponsor_keur == (("alpha", 160.0),)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), True, "10"])
def test_invalid_contribution_amount_rejected(value):
    with pytest.raises(ValueError):
        Contribution("alpha", DATES[0], value)


@pytest.mark.parametrize("identity", ["", " ", " alpha ", None])
def test_missing_or_ambiguous_identity_rejected(identity):
    with pytest.raises(ValueError):
        Investor(identity, InvestmentClass.COMMON_EQUITY, 1, 100)


@pytest.mark.parametrize("share", [0.99, 0.5, 0.0])
def test_invalid_ownership_total_rejected(share):
    contract = agreement()
    with pytest.raises(ValueError, match="ownership"):
        replace(contract, investors=(replace(contract.investors[0], ownership_fraction=share),))


def test_duplicate_investor_identity_rejected():
    contract = agreement()
    with pytest.raises(ValueError, match="duplicate"):
        replace(contract, investors=contract.investors * 2)


@pytest.mark.parametrize("change", ["unknown", "off_axis", "over_commitment"])
def test_contribution_identity_axis_and_commitment(change):
    c = Contribution("unknown" if change == "unknown" else "alpha",
                     date(2030, 2, 1) if change == "off_axis" else DATES[0],
                     101 if change == "over_commitment" else 10)
    with pytest.raises(ValueError):
        replace(agreement(), contributions=(c,))


def test_dated_contributions_map_to_cumulative_not_new_allocation_logic():
    contract = replace(agreement(), contributions=(Contribution("alpha", DATES[1], 20),))
    assert to_existing_inputs(contract).cumulative_invested_by_period == (0, 20, 20)
    assert evaluate_candidate(contract).total_allocated_keur == 160


@pytest.mark.parametrize("priority", [Priority.PREFERRED_RETURN, Priority.GP_CATCH_UP, Priority.PROMOTE])
def test_rates_are_required_not_defaulted(priority):
    with pytest.raises(ValueError, match="explicit contractual"):
        Entitlements((priority, Priority.RESIDUAL))


@pytest.mark.parametrize("priority", list(Priority)[:-1])
def test_declared_but_unsupported_tiers_never_execute(priority):
    terms = Entitlements((priority, Priority.RESIDUAL),
                         preferred_rate_pa=0.06 if priority == Priority.PREFERRED_RETURN else None,
                         carry_fraction=0.15 if priority in (Priority.GP_CATCH_UP, Priority.PROMOTE) else None)
    contract = replace(agreement(), entitlements=terms)
    assert contract.unsupported_reasons()
    with pytest.raises(ValueError, match="Unsupported"):
        evaluate_candidate(contract)


def test_explicit_preference_class_does_not_silently_become_common():
    contract = agreement()
    investor = replace(contract.investors[0], investment_class=InvestmentClass.PREFERRED_EQUITY)
    with pytest.raises(ValueError, match="explicit contractual rate"):
        replace(contract, investors=(investor,))
    contract = replace(contract, investors=(investor,),
                       entitlements=Entitlements((Priority.RESIDUAL,), preferred_rate_pa=0.06))
    with pytest.raises(ValueError, match="Unsupported"):
        evaluate_candidate(contract)


def test_shl_is_not_legal_equity_and_never_redistributed():
    with pytest.raises(ValueError, match="not legal equity"):
        Investor("loan-holder", InvestmentClass.SHAREHOLDER_LOAN, 0.1, 100)
    contract = agreement()
    loan = Investor("loan-holder", InvestmentClass.SHAREHOLDER_LOAN, 0, 100)
    contract = replace(contract, investors=contract.investors + (loan,),
                       contributions=contract.contributions + (Contribution(loan.investor_id, DATES[0], 100),))
    with pytest.raises(ValueError, match="Unsupported"):
        evaluate_candidate(contract)


@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf"), True])
def test_invalid_distributable_cash_rejected(value):
    with pytest.raises(ValueError):
        DistributionEvidence("synthetic", DATES, (0, value, 10))


@pytest.mark.parametrize("dates", [DATES[::-1], (DATES[0],) * 3, ("2030-01-01",) * 3])
def test_date_axis_never_inferred(dates):
    with pytest.raises(ValueError):
        DistributionEvidence("synthetic", dates, (0, 0, 0))


def test_mutable_sequences_are_copied_and_serialization_is_deterministic():
    contract = agreement(True)
    investors = list(contract.investors[::-1])
    contributions = list(contract.contributions[::-1])
    other = replace(contract, investors=investors, contributions=contributions)
    investors.clear()
    contributions.clear()
    assert other.to_json() == contract.to_json()
    assert other.content_digest() == contract.content_digest()
    assert len(other.content_digest()) == 64
    with pytest.raises(FrozenInstanceError):
        other.schema_version = 2
    assert json.loads(other.to_json())["entitlements"]["preferred_rate_pa"] is None
    changed = replace(other, evidence=replace(other.evidence, net_equity_cash_keur=(0, 50, 100)))
    assert changed.content_digest() != other.content_digest()


@pytest.mark.parametrize("corruption", ["over", "retained", "nan", "unknown"])
def test_result_validation_rejects_invented_or_unauthorized_cash(corruption):
    contract = agreement()
    result = evaluate_candidate(contract)
    periods = list(result.period_results)
    p = periods[1]
    amount = {"over": 61, "retained": 59, "nan": float("nan"), "unknown": 60}[corruption]
    tier = SimpleNamespace(tier_type=p.tier_entries[0].tier_type, allocated_amount_keur=amount,
                           allocated_per_sponsor_keur=(("unknown" if corruption == "unknown" else "alpha", amount),))
    periods[1] = SimpleNamespace(period_index=1, available_cash_keur=60, tier_entries=(tier,),
                                total_allocated_keur=amount, total_remaining_cash_keur=0)
    with pytest.raises(ValueError):
        validate_candidate_result(contract, SimpleNamespace(period_results=periods))


def test_only_version_one_and_typed_priorities_supported():
    with pytest.raises(ValueError):
        replace(agreement(), schema_version=2)
    with pytest.raises(ValueError):
        Entitlements(("RESIDUAL",))
    with pytest.raises(ValueError):
        Entitlements((Priority.RESIDUAL, Priority.RESIDUAL))


def test_no_production_imports_or_activation_hook():
    root = Path(__file__).resolve().parents[1]
    candidate = root / "app/model_v2/investor_f4_candidate"
    for path in (root / "app").rglob("*.py"):
        if candidate in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            assert not any("investor_f4_candidate" in n for n in names), str(path)
    for path in candidate.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith(
            ("app.persistence", "app.services", "app.v2", "financial_engine")) for n in ast.walk(tree))


def test_real_canonical_cash_remains_unchanged_during_offline_delegation():
    from dataclasses import asdict
    from app.project_factories import create_generic_solar_reference
    from app.services.production_financial_authority import run_clean_production
    run = run_clean_production(create_generic_solar_reference())
    before = asdict(run)
    periods = run.g2c_result.waterfall_periods
    evidence = DistributionEvidence(
        "synthetic-local-canonical-run", tuple(p.cashflow_date for p in periods),
        tuple(p.net_dividend_received_keur for p in periods),
    )
    contract = replace(agreement(), evidence=evidence, contributions=())
    result = evaluate_candidate(contract)
    assert result.total_allocated_keur == pytest.approx(sum(evidence.net_equity_cash_keur), abs=1e-6)
    assert asdict(run) == before
