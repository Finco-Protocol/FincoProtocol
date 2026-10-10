"""F3.1 proposal contracts: strict validation, immutable identity, no activation."""
import copy
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
import hashlib
import json

import pytest

from finco_core.inputs.financing_instruments import (
    SCHEMA_VERSION, CapitalProvider, CommitmentAuthority as CA, DrawdownEntry,
    FeeKind, FeeTerm, FinancingCollection, FinancingError, FinancingInstrument,
    InstrumentType as IT, InterestTerms, MaturityAuthority as MA, Provenance,
    RateMode, RepaymentMode as RM, RepaymentTerms, canonical_json, content_digest,
    family_of, from_dict, to_dict,
)


def loan(**kw):
    body = dict(instrument_id="loan", instrument_type=IT.SENIOR_TERM_LOAN,
                name="Term loan", commitment_keur=1000,
                interest=InterestTerms(RateMode.FIXED, fixed_rate=.05),
                repayment=RepaymentTerms(RM.LEVEL_PRINCIPAL, maturity_date=date(2040, 1, 1)))
    return FinancingInstrument(**(body | kw))


def collection():
    return FinancingCollection((loan(drawdowns=(DrawdownEntry(date(2030, 1, 1), 12.123456789012345),),
                                     fees=(FeeTerm(FeeKind.COMMITMENT, .001234567890123456, "UNDRAWN"),)),),
                               (CapitalProvider("owner", "Owner", 1),))


INVALID_CASES = [
    ("F3_DUPLICATE_INSTRUMENT_ID", lambda: FinancingCollection((loan(), loan(enabled=False)))),
    ("F3_DUPLICATE_PROVIDER_ID", lambda: FinancingCollection((), (CapitalProvider("a", "A", 0),) * 2)),
    ("F3_NON_FINITE_VALUE", lambda: loan(commitment_keur=float("nan"))),
    ("F3_NON_FINITE_VALUE", lambda: loan(commitment_keur=10 ** 1000)),
    ("F3_NON_FINITE_VALUE", lambda: loan(commitment_keur="1000")),
    ("F3_NON_FINITE_VALUE", lambda: loan(commitment_keur=True)),
    ("F3_NEGATIVE_VALUE", lambda: loan(commitment_keur=-1e-12)),
    ("F3_NEGATIVE_VALUE", lambda: loan(enabled=False, commitment_keur=-1)),
    ("F3_INVALID_DATE", lambda: DrawdownEntry(datetime(2030, 1, 1), 1)),
    ("F3_INVALID_DATE", lambda: DrawdownEntry("2030-01-01", 1)),
    ("F3_DRAWDOWN_ORDER", lambda: loan(drawdowns=(DrawdownEntry(date(2030, 1, 1), 1),) * 2)),
    ("F3_DRAWDOWN_ORDER", lambda: loan(drawdowns=(DrawdownEntry(date(2031, 1, 1), 1), DrawdownEntry(date(2030, 1, 1), 1)))),
    ("F3_DRAWDOWN_EXCEEDS_COMMITMENT", lambda: loan(drawdowns=(DrawdownEntry(date(2030, 1, 1), 1000.0000000001),))),
    ("F3_NON_FINITE_VALUE", lambda: loan(commitment_keur=1e308, drawdowns=(DrawdownEntry(date(2030, 1, 1), 1e308),
                                                                                      DrawdownEntry(date(2031, 1, 1), 1e308)))),
    ("F3_MISSING_TERM", lambda: loan(interest=None)),
    ("F3_MISSING_TERM", lambda: loan(repayment=None)),
    ("F3_MISSING_TERM", lambda: loan(commitment_keur=None)),
    ("F3_MISSING_TERM", lambda: loan(name=" ")),
    ("F3_MISSING_TERM", lambda: loan(instrument_type=IT.SHAREHOLDER_LOAN)),
    ("F3_MISSING_TERM", lambda: InterestTerms(RateMode.FIXED)),
    ("F3_MISSING_TERM", lambda: InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN)),
    ("F3_MISSING_TERM", lambda: RepaymentTerms(RM.BULLET)),
    ("F3_MISSING_TERM", lambda: RepaymentTerms(RM.BULLET, maturity_authority=MA.PERIOD_AXIS_DERIVED)),
    ("F3_INVALID_TYPE", lambda: loan(instrument_type="SENIOR_TERM_LOAN")),
    ("F3_INVALID_TYPE", lambda: family_of("DEBT")),
    ("F3_INVALID_TYPE_COMBINATION", lambda: loan(instrument_type=IT.COMMON_EQUITY)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: loan(instrument_type=IT.COMMON_EQUITY, interest=None)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(RateMode.FIXED, .05, 100)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(RateMode.PERIOD_SCHEDULE, .05)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(RateMode.PERIOD_SCHEDULE, margin_bps=100)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, .05, 100)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: RepaymentTerms(RM.NONE, maturity_date=date(2040, 1, 1))),
    ("F3_INVALID_TYPE_COMBINATION", lambda: loan(repayment=RepaymentTerms(RM.NONE))),
    ("F3_INVALID_TYPE_COMBINATION", lambda: RepaymentTerms(RM.BULLET, maturity_authority=MA.PERIOD_AXIS_DERIVED,
                                                        maturity_date=date(2040, 1, 1), tenor_years=10)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: RepaymentTerms(RM.BULLET, maturity_date=date(2040, 1, 1), tenor_years=10)),
    ("F3_CURRENCY_MISMATCH", lambda: loan(currency="USD")),
    ("F3_INVALID_SENIORITY", lambda: loan(seniority_rank=True)),
    ("F3_INVALID_SENIORITY", lambda: loan(seniority_rank=0)),
    ("F3_INVALID_GRACE", lambda: RepaymentTerms(RM.BULLET, grace_months=True)),
    ("F3_INVALID_GRACE", lambda: RepaymentTerms(RM.BULLET, grace_months=-1)),
    ("F3_INVALID_GRACE", lambda: RepaymentTerms(RM.BULLET, grace_months=25, tenor_years=2,
                                             maturity_authority=MA.PERIOD_AXIS_DERIVED)),
    ("F3_RATE_NOT_A_FRACTION", lambda: InterestTerms(RateMode.FIXED, 5)),
    ("F3_RATE_NOT_A_FRACTION", lambda: FeeTerm(FeeKind.UPFRONT, 2)),
    ("F3_DERIVED_COMMITMENT_HAS_AMOUNT", lambda: loan(commitment_authority=CA.CANONICAL_SIZING_DERIVED)),
    ("F3_DERIVED_COMMITMENT_HAS_AMOUNT", lambda: loan(commitment_authority=CA.RESIDUAL_DERIVED)),
    ("F3_INVALID_TYPE_COMBINATION", lambda: loan(commitment_keur=None, commitment_authority=CA.CANONICAL_SIZING_DERIVED,
                                                drawdowns=(DrawdownEntry(date(2030, 1, 1), 1),))),
    ("F3_UNKNOWN_FUNDING_SOURCE", lambda: FinancingCollection((loan(funding_source_ref="missing"),))),
    ("F3_OWNERSHIP_ABOVE_100", lambda: CapitalProvider("a", "A", 1.0000000001)),
    ("F3_OWNERSHIP_ABOVE_100", lambda: FinancingCollection((), (CapitalProvider("a", "A", .6), CapitalProvider("b", "B", .5)))),
    ("F3_PREFERRED_EQUITY_DEFERRED", lambda: FinancingInstrument("p", IT.PREFERRED_EQUITY, "Preferred", 1)),
    ("F3_INVALID_ID", lambda: loan(instrument_id="id\n")),
    ("F3_INVALID_ID", lambda: CapitalProvider("A", "A", 0)),
    ("F3_INVALID_ID", lambda: loan(funding_source_ref="bad id")),
    ("F3_INVALID_ENUM", lambda: loan(commitment_authority="EXPLICIT")),
    ("F3_INVALID_ENUM", lambda: loan(provenance="USER_INPUT")),
    ("F3_INVALID_ENUM", lambda: InterestTerms("FIXED", .05)),
    ("F3_INVALID_ENUM", lambda: RepaymentTerms("BULLET", maturity_date=date(2040, 1, 1))),
    ("F3_INVALID_ENUM", lambda: FeeTerm("UPFRONT", .01)),
    ("F3_INVALID_ENUM", lambda: RepaymentTerms(RM.BULLET, maturity_authority="EXPLICIT_DATE")),
    ("F3_INVALID_BOOL", lambda: loan(enabled=1)),
    ("F3_INVALID_BOOL", lambda: InterestTerms(RateMode.PERIOD_SCHEDULE, pik="false")),
    ("F3_INVALID_MARGIN", lambda: InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=True)),
    ("F3_INVALID_MARGIN", lambda: InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=1.5)),
    ("F3_INVALID_MARGIN", lambda: InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=-1)),
    ("F3_INVALID_MARGIN", lambda: InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=10001)),
    ("F3_INVALID_FEE_BASIS", lambda: FeeTerm(FeeKind.AGENCY, .01, [])),
    ("F3_INVALID_FEE_BASIS", lambda: FeeTerm(FeeKind.AGENCY, .01, "USES")),
    ("F3_INVALID_TERM", lambda: loan(drawdowns=[])),
    ("F3_INVALID_TERM", lambda: loan(fees=("fee",))),
    ("F3_INVALID_TERM", lambda: loan(interest={})),
    ("F3_INVALID_TERM", lambda: FinancingCollection([loan()])),
    ("F3_INVALID_TERM", lambda: FinancingCollection((), providers=[CapitalProvider("a", "A", 0)])),
    ("F3_INVALID_TERM", lambda: RepaymentTerms(RM.BULLET, tenor_years=0, maturity_authority=MA.PERIOD_AXIS_DERIVED)),
    ("F3_INVALID_TERM", lambda: loan(drawdowns=(DrawdownEntry(date(2041, 1, 1), 1),))),
    ("F3_UNSUPPORTED_SCHEMA_VERSION", lambda: FinancingCollection((), schema_version="f3-candidate-0.1")),
]


@pytest.mark.parametrize("code,build", INVALID_CASES)
def test_validation_catalogue(code, build):
    with pytest.raises(FinancingError) as exc:
        build()
    assert exc.value.code == code


@pytest.mark.parametrize("kind", [IT.SENIOR_TERM_LOAN, IT.CONSTRUCTION_FACILITY, IT.JUNIOR_DEBT,
                                 IT.MEZZANINE_DEBT, IT.SHAREHOLDER_LOAN, IT.BOND])
def test_all_approved_debt_types_are_proposals_not_engines(kind):
    item = loan(instrument_type=kind, funding_source_ref="owner")
    result = FinancingCollection((item,), (CapitalProvider("owner", "Provider", 0),))
    assert from_dict(to_dict(result)) == result
    assert item.family.value == "DEBT"
    assert not hasattr(item, "calculate")


@pytest.mark.parametrize("kind", [IT.COMMON_EQUITY, IT.SHARE_PREMIUM, IT.ADDITIONAL_EQUITY])
def test_approved_equity_types(kind):
    item = FinancingInstrument("equity", kind, "Equity", 12.345678901234567, funding_source_ref="owner")
    value = FinancingCollection((item,), (CapitalProvider("owner", "Provider", 1),))
    assert value == FinancingCollection.from_dict(json.loads(value.canonical_json()))


@pytest.mark.parametrize("terms", [InterestTerms(RateMode.FIXED, 0), InterestTerms(RateMode.FIXED, 1),
    InterestTerms(RateMode.PERIOD_SCHEDULE), InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=0),
    InterestTerms(RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=10000, pik=True)])
def test_valid_rate_modes_round_trip_without_an_invented_curve(terms):
    value = FinancingCollection((loan(interest=terms),))
    assert from_dict(value.to_dict()) == value


@pytest.mark.parametrize("mode", [RM.BULLET, RM.LEVEL_PRINCIPAL, RM.DSCR_SCULPTED, RM.EXPLICIT_SCHEDULE, RM.CASH_SWEEP])
def test_repayment_vocab_is_documentary_until_activation(mode):
    item = loan(repayment=RepaymentTerms(mode, maturity_authority=MA.PERIOD_AXIS_DERIVED, maturity_period_index=32))
    assert from_dict(FinancingCollection((item,)).to_dict()).instruments[0].repayment == item.repayment


def test_full_precision_canonical_order_and_frozen_nested_values():
    value = collection()
    reverse = FinancingCollection((replace(loan(), instrument_id="z", seniority_rank=2), value.instruments[0]),
                                  (CapitalProvider("z", "Z", 0), value.providers[0]))
    reordered = FinancingCollection(tuple(reversed(reverse.instruments)), tuple(reversed(reverse.providers)))
    assert reverse == reordered
    assert reverse.to_dict() == reordered.to_dict()
    assert reverse.canonical_json() == reordered.canonical_json()
    assert reverse.content_digest() == hashlib.sha256(reverse.canonical_json().encode()).hexdigest()
    assert from_dict(json.loads(canonical_json(reverse))) == reverse
    assert reverse.instruments[0].drawdowns[0].amount_keur == 12.123456789012345
    for obj, attr, new in ((value, "instruments", ()), (value.instruments[0], "instrument_id", "new"),
                          (value.instruments[0].interest, "fixed_rate", .7), (value.providers[0], "name", "Changed")):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attr, new)
    wire = value.to_dict()
    wire["instruments"][0]["name"] = "Changed"
    assert value.instruments[0].name != "Changed"


def test_disabled_remains_validated_and_identity_bearing():
    original = FinancingCollection((loan(),))
    disabled = FinancingCollection((loan(enabled=False),))
    assert disabled.active() == () and disabled.ordered()
    assert original.content_digest() != disabled.content_digest()
    assert FinancingCollection.from_dict(disabled.to_dict()) == disabled
    assert FinancingCollection(()).active() == ()  # empty proposal, never an activation grant


def test_derived_commitments_never_infer_amounts():
    for authority in (CA.CANONICAL_SIZING_DERIVED, CA.RESIDUAL_DERIVED):
        value = FinancingCollection((loan(commitment_keur=None, commitment_authority=authority),))
        assert from_dict(value.to_dict()).instruments[0].commitment_keur is None


@pytest.mark.parametrize("path", [(), ("instruments", 0), ("providers", 0),
    ("instruments", 0, "interest"), ("instruments", 0, "repayment"),
    ("instruments", 0, "drawdowns", 0), ("instruments", 0, "fees", 0)])
@pytest.mark.parametrize("operation", ["unknown", "missing"])
def test_unknown_and_missing_keys_at_every_level_fail_closed(path, operation):
    body = collection().to_dict()
    target = body
    for key in path:
        target = target[key]
    if operation == "unknown":
        target["unapproved"] = 1
    else:
        target.pop(next(iter(target)))
    with pytest.raises(FinancingError) as exc:
        from_dict(body)
    assert exc.value.code == "F3_INVALID_TERM"


@pytest.mark.parametrize("field,bad,code", [
    ("commitment_keur", "1", "F3_NON_FINITE_VALUE"), ("commitment_keur", True, "F3_NON_FINITE_VALUE"),
    ("enabled", "false", "F3_INVALID_BOOL"), ("enabled", 0, "F3_INVALID_BOOL"),
    ("instrument_type", "unknown", "F3_INVALID_ENUM"), ("provenance", {}, "F3_INVALID_ENUM"),
    ("drawdowns", {}, "F3_INVALID_TERM"), ("fees", None, "F3_INVALID_TERM"),
])
def test_wire_numeric_enum_and_container_coercion_is_forbidden(field, bad, code):
    wire = collection().to_dict()
    wire["instruments"][0][field] = bad
    before = copy.deepcopy(wire)
    with pytest.raises(FinancingError) as exc:
        from_dict(wire)
    assert exc.value.code == code
    assert wire == before


@pytest.mark.parametrize("bad", [None, True, 1, "f3-candidate-0.1", "f3-9.0"])
def test_strict_wire_version(bad):
    wire = collection().to_dict() | {"schema_version": bad}
    with pytest.raises(FinancingError, match="F3_UNSUPPORTED_SCHEMA_VERSION"):
        from_dict(wire)


@pytest.mark.parametrize("bad", ["20300101", "2030-W01-2", "2030-01-01T00:00:00", "2030-02-30", 1, None])
def test_strict_iso_wire_dates(bad):
    wire = collection().to_dict()
    wire["instruments"][0]["drawdowns"][0]["draw_date"] = bad
    with pytest.raises(FinancingError, match="F3_INVALID_DATE"):
        from_dict(wire)


def test_valid_candidate_shape_promotes_explicitly_not_as_a_schema_alias():
    from app.model_v2.financing_f3_candidate.contracts import to_canonical_dict as candidate_dict
    from tests.test_financing_f3_contract_candidate import _debt as candidate_debt
    from app.model_v2.financing_f3_candidate.contracts import FinancingCollection as Candidate
    old = candidate_dict(Candidate((candidate_debt("a"),)))
    with pytest.raises(FinancingError, match="F3_UNSUPPORTED_SCHEMA_VERSION"):
        from_dict(old)
    wire = old | {"schema_version": SCHEMA_VERSION}
    assert from_dict(wire).to_dict() == wire
    assert content_digest(from_dict(wire)) != hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
