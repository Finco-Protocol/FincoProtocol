"""Financing F3 — candidate contract validation (NON-AUTHORITATIVE prototype).

These tests validate a *specification prototype* only.  They prove that the proposed contract
rejects invalid proposals deterministically.  They do not exercise, and do not imply, any
multi-tranche financial engine.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.model_v2.financing_f3_candidate.contracts import (
    CapitalProvider,
    CommitmentAuthority,
    DrawdownEntry,
    FeeKind,
    FeeTerm,
    FinancingCollection,
    FinancingError,
    FinancingInstrument,
    InstrumentType,
    InterestTerms,
    RateMode,
    RepaymentMode,
    RepaymentTerms,
    canonical_json,
    candidate_identity,
)


def _debt(iid="d1", **kw):
    base = dict(
        instrument_id=iid, instrument_type=InstrumentType.SENIOR_TERM_LOAN, name=iid,
        commitment_keur=1000.0,
        interest=InterestTerms(mode=RateMode.FIXED, fixed_rate=0.05),
        repayment=RepaymentTerms(mode=RepaymentMode.LEVEL_PRINCIPAL, maturity_date=date(2040, 1, 1)),
    )
    base.update(kw)
    return FinancingInstrument(**base)


def _expect(code, fn):
    with pytest.raises(FinancingError) as exc:
        fn()
    assert exc.value.code == code


class TestInstrumentValidation:
    def test_valid_debt_instrument(self):
        assert _debt().family.value == "DEBT"

    def test_duplicate_instrument_ids_rejected(self):
        _expect("F3_DUPLICATE_INSTRUMENT_ID", lambda: FinancingCollection((_debt("a"), _debt("a"))))

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), True, "10"])
    def test_negative_or_non_finite_commitment_rejected(self, bad):
        with pytest.raises(FinancingError):
            _debt(commitment_keur=bad)

    def test_invalid_dates_rejected(self):
        from datetime import datetime
        _expect("F3_INVALID_DATE", lambda: DrawdownEntry("2030-01-01", 1.0))
        _expect("F3_INVALID_DATE", lambda: DrawdownEntry(datetime(2030, 1, 1), 1.0))
        _expect("F3_DRAWDOWN_ORDER", lambda: _debt(drawdowns=(
            DrawdownEntry(date(2030, 6, 1), 1.0), DrawdownEntry(date(2030, 6, 1), 1.0))))

    def test_drawdown_cannot_exceed_commitment(self):
        _expect("F3_DRAWDOWN_EXCEEDS_COMMITMENT", lambda: _debt(
            commitment_keur=10.0, drawdowns=(DrawdownEntry(date(2030, 1, 1), 11.0),)))

    def test_missing_required_terms_rejected(self):
        _expect("F3_MISSING_TERM", lambda: _debt(interest=None))
        _expect("F3_MISSING_TERM", lambda: _debt(repayment=None))
        _expect("F3_MISSING_TERM", lambda: InterestTerms(mode=RateMode.FIXED))
        _expect("F3_MISSING_TERM", lambda: RepaymentTerms(mode=RepaymentMode.BULLET))
        _expect("F3_MISSING_TERM", lambda: _debt(instrument_type=InstrumentType.SHAREHOLDER_LOAN))

    def test_percent_style_rates_rejected(self):
        _expect("F3_RATE_NOT_A_FRACTION", lambda: InterestTerms(mode=RateMode.FIXED, fixed_rate=5.0))
        _expect("F3_RATE_NOT_A_FRACTION", lambda: FeeTerm(FeeKind.UPFRONT, 2.0))

    def test_invalid_type_combinations_rejected(self):
        eq = dict(instrument_type=InstrumentType.COMMON_EQUITY, interest=None)
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: _debt(
            instrument_type=InstrumentType.COMMON_EQUITY))                     # equity with interest
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: _debt(**eq))            # equity with repayment
        _expect("F3_INVALID_TYPE", lambda: _debt(instrument_type="SENIOR"))

    def test_preferred_equity_is_deferred_not_decorated(self):
        _expect("F3_PREFERRED_EQUITY_DEFERRED", lambda: FinancingInstrument(
            instrument_id="p", instrument_type=InstrumentType.PREFERRED_EQUITY, name="p", commitment_keur=1.0))

    def test_currency_and_seniority_validation(self):
        _expect("F3_CURRENCY_MISMATCH", lambda: _debt(currency="USD"))
        _expect("F3_INVALID_SENIORITY", lambda: _debt(seniority_rank=0))

    def test_derived_commitment_is_an_output_not_an_input(self):
        _expect("F3_DERIVED_COMMITMENT_HAS_AMOUNT", lambda: _debt(
            commitment_authority=CommitmentAuthority.CANONICAL_SIZING_DERIVED))
        d = _debt(commitment_keur=None, commitment_authority=CommitmentAuthority.CANONICAL_SIZING_DERIVED)
        assert d.commitment_keur is None
        _expect("F3_MISSING_TERM", lambda: _debt(commitment_keur=None))     # EXPLICIT needs an amount


class TestCollectionValidation:
    def test_unknown_funding_source_rejected(self):
        _expect("F3_UNKNOWN_FUNDING_SOURCE", lambda: FinancingCollection((_debt(funding_source_ref="nobody"),)))

    def test_ownership_cannot_exceed_100_percent(self):
        _expect("F3_OWNERSHIP_ABOVE_100", lambda: FinancingCollection((), providers=(
            CapitalProvider("a", "A", 0.7), CapitalProvider("b", "B", 0.5))))
        _expect("F3_DUPLICATE_PROVIDER_ID", lambda: FinancingCollection((), providers=(
            CapitalProvider("a", "A", 0.1), CapitalProvider("a", "A2", 0.1))))


class TestDeterminism:
    def _coll(self, order):
        items = {"a": _debt("a", seniority_rank=2), "b": _debt("b", seniority_rank=1), "c": _debt("c", seniority_rank=2)}
        return FinancingCollection(tuple(items[k] for k in order))

    def test_serialization_and_identity_ignore_insertion_order(self):
        x, y = self._coll("abc"), self._coll("cba")
        assert canonical_json(x) == canonical_json(y)
        assert candidate_identity(x) == candidate_identity(y)
        assert [i.instrument_id for i in x.ordered()] == ["b", "a", "c"]

    def test_identity_changes_with_economics_but_not_with_nothing(self):
        base = FinancingCollection((_debt("a"),))
        assert candidate_identity(base) == candidate_identity(FinancingCollection((_debt("a"),)))
        assert candidate_identity(base) != candidate_identity(FinancingCollection((_debt("a", commitment_keur=1001.0),)))

    def test_label_is_identity_not_economics_but_is_still_part_of_the_proposal_identity(self):
        a = _debt("a", classification_label="Club Deal")
        b = _debt("a", classification_label="DFI Loan")
        # same economics, different label: every economic field is identical
        econ = lambda i: (i.instrument_type, i.commitment_keur, i.interest, i.repayment, i.fees, i.seniority_rank)
        assert econ(a) == econ(b)


# ----------------------------------------------------------------------------------------------
# Correction A — strict validation
# ----------------------------------------------------------------------------------------------
from app.model_v2.financing_f3_candidate.contracts import MaturityAuthority, Provenance


class TestIdFormat:
    @pytest.mark.parametrize("bad", ["", "A", "Has Space", "-lead", "a_b", "x" * 65, None, 7, "añb"])
    def test_invalid_instrument_ids_rejected(self, bad):
        _expect("F3_INVALID_ID", lambda: _debt(bad))

    @pytest.mark.parametrize("bad", ["", "P1", "a b", None])
    def test_invalid_provider_ids_rejected(self, bad):
        _expect("F3_INVALID_ID", lambda: CapitalProvider(bad, "Name", 0.1))

    def test_boundary_valid_ids(self):
        assert _debt("a").instrument_id == "a" and _debt("a" * 64).instrument_id == "a" * 64
        _expect("F3_INVALID_ID", lambda: _debt("d1", funding_source_ref="Bad Ref"))


class TestMalformedValues:
    def test_enabled_must_be_a_strict_bool(self):
        for bad in ("yes", 1, 0, None):
            _expect("F3_INVALID_BOOL", lambda b=bad: _debt(enabled=b))
        assert _debt(enabled=False).enabled is False

    def test_enum_fields_must_be_enums_not_strings(self):
        _expect("F3_INVALID_ENUM", lambda: InterestTerms(mode="FIXED", fixed_rate=0.05))
        _expect("F3_INVALID_ENUM", lambda: RepaymentTerms(mode="BULLET", maturity_date=date(2040, 1, 1)))
        _expect("F3_INVALID_ENUM", lambda: FeeTerm("UPFRONT", 0.01))
        _expect("F3_INVALID_ENUM", lambda: _debt(commitment_authority="EXPLICIT"))
        _expect("F3_INVALID_ENUM", lambda: _debt(provenance="USER_INPUT"))
        _expect("F3_INVALID_ENUM", lambda: RepaymentTerms(mode=RepaymentMode.BULLET, maturity_date=date(2040, 1, 1),
                                                          maturity_authority="EXPLICIT_DATE"))

    @pytest.mark.parametrize("bad", [True, 1.5, -1, 10_001, float("nan"), "100"])
    def test_invalid_margins_rejected(self, bad):
        with pytest.raises(FinancingError):
            InterestTerms(mode=RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=bad)

    def test_stray_economic_fields_rejected(self):
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(mode=RateMode.FIXED, fixed_rate=0.05, margin_bps=100))
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(
            mode=RateMode.FLOATING_BASE_PLUS_MARGIN, margin_bps=100, fixed_rate=0.05))
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: InterestTerms(mode=RateMode.PERIOD_SCHEDULE, fixed_rate=0.05))
        _expect("F3_INVALID_BOOL", lambda: InterestTerms(mode=RateMode.PERIOD_SCHEDULE, pik="yes"))

    def test_fee_kind_basis_and_rate(self):
        _expect("F3_INVALID_FEE_BASIS", lambda: FeeTerm(FeeKind.UPFRONT, 0.01, basis="BOGUS"))
        _expect("F3_NEGATIVE_VALUE", lambda: FeeTerm(FeeKind.UPFRONT, -0.01))
        _expect("F3_NON_FINITE_VALUE", lambda: FeeTerm(FeeKind.UPFRONT, float("nan")))
        assert FeeTerm(FeeKind.COMMITMENT, 0.01, basis="UNDRAWN").basis == "UNDRAWN"

    def test_drawdown_and_fee_containers_are_typed_tuples(self):
        _expect("F3_INVALID_TERM", lambda: _debt(drawdowns=[DrawdownEntry(date(2030, 1, 1), 1.0)]))
        _expect("F3_INVALID_TERM", lambda: _debt(drawdowns=((date(2030, 1, 1), 1.0),)))
        _expect("F3_INVALID_TERM", lambda: _debt(fees=("UPFRONT",)))
        _expect("F3_INVALID_TERM", lambda: _debt(interest="fixed"))
        _expect("F3_INVALID_TERM", lambda: FinancingCollection([_debt()]))
        _expect("F3_INVALID_TERM", lambda: FinancingCollection((_debt(),), providers=["x"]))

    def test_numeric_terms_must_be_plain_non_negative_ints(self):
        for kw in ({"grace_months": True}, {"grace_months": -1}, {"grace_months": 1.5}):
            _expect("F3_INVALID_GRACE", lambda k=kw: RepaymentTerms(
                mode=RepaymentMode.BULLET, maturity_date=date(2040, 1, 1), **k))

    def test_unsupported_schema_version_fails_closed(self):
        _expect("F3_UNSUPPORTED_SCHEMA_VERSION", lambda: FinancingCollection((_debt(),), schema_version="f3-9.9"))


class TestMaturityAuthority:
    def test_explicit_date_requires_a_real_date(self):
        _expect("F3_MISSING_TERM", lambda: RepaymentTerms(mode=RepaymentMode.BULLET))
        from datetime import datetime
        _expect("F3_INVALID_DATE", lambda: RepaymentTerms(mode=RepaymentMode.BULLET, maturity_date=datetime(2040, 1, 1)))

    def test_period_axis_derived_maturity_is_an_output_and_carries_no_date(self):
        ok = RepaymentTerms(mode=RepaymentMode.DSCR_SCULPTED, maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED,
                            tenor_years=15)
        assert ok.maturity_date is None
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: RepaymentTerms(
            mode=RepaymentMode.BULLET, maturity_date=date(2040, 1, 1),
            maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED))
        _expect("F3_INVALID_TYPE_COMBINATION", lambda: RepaymentTerms(
            mode=RepaymentMode.BULLET, maturity_date=date(2040, 1, 1), tenor_years=5))
        _expect("F3_INVALID_TERM", lambda: RepaymentTerms(
            mode=RepaymentMode.BULLET, maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED, tenor_years=-1))


class TestDisabledSemantics:
    def test_disabled_is_retained_validated_identity_bearing_but_inactive(self):
        on, off = _debt("a"), _debt("a", enabled=False)
        coll_on, coll_off = FinancingCollection((on, _debt("b"))), FinancingCollection((off, _debt("b")))
        assert [i.instrument_id for i in coll_on.active()] == ["a", "b"]
        assert [i.instrument_id for i in coll_off.active()] == ["b"]
        assert len(coll_off.ordered()) == 2
        assert candidate_identity(coll_on) != candidate_identity(coll_off)

    def test_a_disabled_invalid_instrument_is_still_rejected(self):
        _expect("F3_NEGATIVE_VALUE", lambda: _debt(enabled=False, commitment_keur=-1.0))

    def test_all_disabled_collection_has_no_active_instruments(self):
        assert FinancingCollection((_debt("a", enabled=False),)).active() == ()
