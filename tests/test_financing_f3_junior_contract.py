"""Candidate opt-in contract and strict serialization boundaries."""
from dataclasses import replace
import json

import pytest

from finco_core.inputs import hash_inputs_for_cache, project_inputs_from_dict, project_inputs_to_dict
from finco_core.inputs.financing_instruments import FinancingCollection, FinancingError, InstrumentType
from finco_core.inputs.junior_debt import JuniorDebtPolicy, activate_collection
from finco_core.inputs.multisenior import deactivate_collection
from tests.test_financing_f3_multisenior import case as senior_case


def case(kind="solar", **policy_changes):
    old, periods = senior_case(kind)
    pi = deactivate_collection(old)
    senior, junior = old.financing_collection.instruments
    junior = replace(junior, instrument_type=InstrumentType.JUNIOR_DEBT, seniority_rank=2, name="Junior Debt", fees=(),
        repayment=replace(junior.repayment, grace_months=0))
    policy = JuniorDebtPolicy(junior_instrument_id=junior.instrument_id, day_count="act_360",
        idc_book_life_years=8, idc_tax_treatment=("BOOK_BASED_POLICY" if pi.tax.tax_dep_basis_source_owned
        else "EXCLUDED_BY_EXISTING_POLICY"), maximum_total_debt_gearing=.8)
    return activate_collection(pi, FinancingCollection((senior, junior)), replace(policy, **policy_changes)), periods


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_typed_roundtrip_and_identity(kind):
    pi, _ = case(kind)
    restored = project_inputs_from_dict(json.loads(json.dumps(project_inputs_to_dict(pi))))
    assert restored == pi
    assert hash_inputs_for_cache(restored) == hash_inputs_for_cache(pi)
    changed = replace(pi, junior_debt_policy=replace(pi.junior_debt_policy, idc_book_life_years=9))
    assert hash_inputs_for_cache(changed) != hash_inputs_for_cache(pi)


@pytest.mark.parametrize("field,value", [("day_count", "fixed_semiannual"), ("idc_book_life_years", True),
    ("idc_book_life_years", 0), ("maximum_total_debt_gearing", float("nan")),
    ("maximum_total_debt_gearing", 1.1), ("idc_tax_treatment", "ASSUMED_DEDUCTIBLE")])
def test_policy_invalid(field, value):
    with pytest.raises(FinancingError):
        case(**{field: value})


@pytest.mark.parametrize("change", ["rank", "binding", "fees", "draws", "kind", "authority"])
def test_invalid_activation_fails_closed(change):
    pi, _ = case()
    senior, junior = pi.financing_collection.instruments
    with pytest.raises(FinancingError):
        if change == "binding":
            replace(pi, junior_debt_policy=replace(pi.junior_debt_policy, junior_instrument_id="unbound"))
        elif change == "authority":
            replace(pi, financing_activation_authority="unknown")
        else:
            terms = {"rank": {"seniority_rank": 1}, "fees": {"fees": senior.fees},
                "draws": {"drawdowns": ()}, "kind": {"instrument_type": InstrumentType.SENIOR_TERM_LOAN}}[change]
            replace(pi, financing_collection=FinancingCollection((senior, replace(junior, **terms))))


def test_serialization_cannot_drop_policy():
    pi, _ = case()
    payload = project_inputs_to_dict(pi)
    del payload["financing_activation"]["junior_policy"]
    with pytest.raises(FinancingError):
        project_inputs_from_dict(payload)
