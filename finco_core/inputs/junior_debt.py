"""Candidate F3.5-A activation; no legacy payload or accounting-policy defaults."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
from math import fsum, isfinite

from finco_core.inputs._models import AssetClass, CapexItem, CapexStructure, ProjectInputs
from finco_core.inputs.financing_instruments import (
    CommitmentAuthority, FinancingCollection, FinancingError, InstrumentType,
    MaturityAuthority, RateMode, RepaymentMode,
)

AUTHORITY = "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1"


@dataclass(frozen=True, kw_only=True)
class JuniorDebtPolicy:
    junior_instrument_id: str
    day_count: str
    idc_book_life_years: int
    idc_tax_treatment: str
    maximum_total_debt_gearing: float

    def __post_init__(self):
        if not isinstance(self.junior_instrument_id, str) or not self.junior_instrument_id:
            raise FinancingError("F35_JUNIOR_ID_REQUIRED")
        if self.day_count not in ("act_360", "act_365"):
            raise FinancingError("F35_DAY_COUNT_UNSUPPORTED")
        if type(self.idc_book_life_years) is not int or not 1 <= self.idc_book_life_years <= 100:
            raise FinancingError("F35_EXPLICIT_BOOK_LIFE_REQUIRED")
        if self.idc_tax_treatment not in ("EXCLUDED_BY_EXISTING_POLICY", "BOOK_BASED_POLICY"):
            raise FinancingError("F35_IDC_TAX_TREATMENT_UNSUPPORTED")
        value = self.maximum_total_debt_gearing
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 < value <= 1:
            raise FinancingError("F35_TOTAL_DEBT_GEARING_INVALID")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
            raise FinancingError("F35_POLICY_PAYLOAD_INVALID")
        return cls(**value)

    def content_digest(self):
        return sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_collection(collection, policy):
    if not isinstance(collection, FinancingCollection) or not isinstance(policy, JuniorDebtPolicy):
        raise FinancingError("F35_TYPED_COLLECTION_AND_POLICY_REQUIRED")
    if len(collection.instruments) != 2 or len(collection.active()) != 2 or collection.providers:
        raise FinancingError("F35_ONE_SENIOR_ONE_JUNIOR_REQUIRED")
    kinds = [i.instrument_type for i in collection.instruments]
    if kinds.count(InstrumentType.SENIOR_TERM_LOAN) != 1 or kinds.count(InstrumentType.JUNIOR_DEBT) != 1:
        raise FinancingError("F35_ONE_SENIOR_ONE_JUNIOR_REQUIRED")
    for instrument in collection.instruments:
        junior = instrument.instrument_type is InstrumentType.JUNIOR_DEBT
        if instrument.seniority_rank != (2 if junior else 1) or instrument.funding_source_ref is not None:
            raise FinancingError("F35_SENIORITY_CONFLICT")
        if junior and instrument.instrument_id != policy.junior_instrument_id:
            raise FinancingError("F35_POLICY_INSTRUMENT_BINDING_INVALID")
        if instrument.commitment_authority is not CommitmentAuthority.EXPLICIT or instrument.commitment_keur <= 0:
            raise FinancingError("F35_EXPLICIT_POSITIVE_COMMITMENT_REQUIRED")
        if instrument.interest.mode is not RateMode.FIXED or instrument.interest.pik:
            raise FinancingError("F35_FIXED_CASH_INTEREST_ONLY")
        if instrument.repayment.mode not in (RepaymentMode.LEVEL_PRINCIPAL, RepaymentMode.BULLET):
            raise FinancingError("F35_REPAYMENT_UNSUPPORTED")
        if junior and instrument.repayment.mode is RepaymentMode.BULLET and instrument.repayment.grace_months:
            raise FinancingError("F35_BULLET_GRACE_CONFLICT")
        if instrument.repayment.maturity_authority is not MaturityAuthority.EXPLICIT_DATE:
            raise FinancingError("F35_EXPLICIT_MATURITY_REQUIRED")
        if not instrument.drawdowns or abs(fsum(d.amount_keur for d in instrument.drawdowns) - instrument.commitment_keur) > 1e-9:
            raise FinancingError("F35_FULL_CONSTRUCTION_DRAWS_REQUIRED")
        if junior and instrument.fees:
            raise FinancingError("F35_JUNIOR_FEES_NOT_RELEASED")
        kinds = set()
        for fee in instrument.fees:
            if (fee.kind, fee.basis) not in (("UPFRONT", "COMMITMENT"), ("COMMITMENT", "UNDRAWN")) or fee.kind in kinds:
                raise FinancingError("F35_SENIOR_FEE_UNSUPPORTED")
            kinds.add(fee.kind)


@dataclass(frozen=True, kw_only=True)
class JuniorProjectInputs(ProjectInputs):
    financing_collection: FinancingCollection
    junior_debt_policy: JuniorDebtPolicy
    financing_activation_authority: str = AUTHORITY

    def __post_init__(self):
        super().__post_init__()
        if self.financing_activation_authority != AUTHORITY:
            raise FinancingError("F35_ACTIVATION_AUTHORITY_INVALID")
        validate_collection(self.financing_collection, self.junior_debt_policy)


def activate_collection(pi, collection, policy):
    return JuniorProjectInputs(**{f.name: getattr(pi, f.name) for f in fields(ProjectInputs)},
        financing_collection=collection, junior_debt_policy=policy)


@dataclass(frozen=True, kw_only=True)
class JuniorCapitalizedCashInterest:
    """Derived, funded cash cost, bound to the effective facility and dated ledger."""
    instrument_id: str
    collection_digest: str
    capitalized_cash_by_period_keur: tuple[float, ...]
    book_life_years: int
    evidence_digest: str

    def validate(self):
        if (not isinstance(self.capitalized_cash_by_period_keur, tuple)
                or not self.capitalized_cash_by_period_keur
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) or v < 0
                       for v in self.capitalized_cash_by_period_keur)
                or type(self.book_life_years) is not int or not 1 <= self.book_life_years <= 100
                or not self.instrument_id or len(self.collection_digest) != 64):
            raise FinancingError("F35_JUNIOR_IDC_EVIDENCE_INVALID")
        payload = (self.instrument_id, self.collection_digest, self.capitalized_cash_by_period_keur, self.book_life_years)
        if self.evidence_digest != sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest():
            raise FinancingError("F35_JUNIOR_IDC_EVIDENCE_TAMPERED")

    @property
    def amount_keur(self):
        self.validate()
        return fsum(self.capitalized_cash_by_period_keur)

    @classmethod
    def from_funded_ledger(cls, instrument_id, collection_digest, amounts, book_life_years):
        payload = (instrument_id, collection_digest, tuple(amounts), book_life_years)
        result = cls(instrument_id=instrument_id, collection_digest=collection_digest,
            capitalized_cash_by_period_keur=tuple(amounts), book_life_years=book_life_years,
            evidence_digest=sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest())
        result.validate()
        return result


@dataclass(frozen=True, kw_only=True)
class JuniorFundedCapex(CapexStructure):
    junior_cash_idc: JuniorCapitalizedCashInterest

    def book_depreciable_capex_items(self):
        return super().book_depreciable_capex_items() + (CapexItem(
            name="Junior Cash IDC", amount_keur=self.junior_cash_idc.amount_keur,
            asset_class=AssetClass.FINANCIAL_COSTS, useful_life_override=self.junior_cash_idc.book_life_years),)

    @property
    def total_capex(self):
        return super().total_capex + self.junior_cash_idc.amount_keur

    @property
    def sculpt_capex_keur(self):
        return super().sculpt_capex_keur + self.junior_cash_idc.amount_keur
