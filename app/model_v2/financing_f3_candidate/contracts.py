"""Candidate typed contracts for multi-instrument financing (non-authoritative, pure)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from . import SCHEMA_VERSION

CANDIDATE_CURRENCY = "EUR"          # single model currency today; FX is out of scope for F3
_TOL = 1e-9
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FEE_BASES = frozenset({"COMMITMENT", "UNDRAWN", "DRAWN"})
_MAX_MARGIN_BPS = 10_000


def _check_id(kind: str, value: object) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise FinancingError("F3_INVALID_ID", f"{kind} id {value!r} must match [a-z0-9][a-z0-9-]{{0,63}}")
    return value


def _check_enum(name: str, value: object, kind: type) -> None:
    if not isinstance(value, kind):
        raise FinancingError("F3_INVALID_ENUM", f"{name}={value!r} is not a {kind.__name__}")


def _check_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinancingError("F3_MISSING_TERM", f"{name} must be non-empty text")
    return value


class FinancingError(ValueError):
    """Typed validation failure; ``code`` is stable and test-pinned."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Family(str, Enum):
    DEBT = "DEBT"
    EQUITY = "EQUITY"
    OTHER = "OTHER"


class InstrumentType(str, Enum):
    # DEBT
    SENIOR_TERM_LOAN = "SENIOR_TERM_LOAN"
    CONSTRUCTION_FACILITY = "CONSTRUCTION_FACILITY"
    JUNIOR_DEBT = "JUNIOR_DEBT"
    MEZZANINE_DEBT = "MEZZANINE_DEBT"
    SHAREHOLDER_LOAN = "SHAREHOLDER_LOAN"
    BOND = "BOND"
    # EQUITY
    COMMON_EQUITY = "COMMON_EQUITY"
    SHARE_PREMIUM = "SHARE_PREMIUM"
    ADDITIONAL_EQUITY = "ADDITIONAL_EQUITY"
    PREFERRED_EQUITY = "PREFERRED_EQUITY"
    # OTHER
    GRANT = "GRANT"
    DEFERRED_PAYMENT = "DEFERRED_PAYMENT"
    DEVELOPER_REIMBURSEMENT = "DEVELOPER_REIMBURSEMENT"


_FAMILY_OF = {
    **{t: Family.DEBT for t in (InstrumentType.SENIOR_TERM_LOAN, InstrumentType.CONSTRUCTION_FACILITY,
                                InstrumentType.JUNIOR_DEBT, InstrumentType.MEZZANINE_DEBT,
                                InstrumentType.SHAREHOLDER_LOAN, InstrumentType.BOND)},
    **{t: Family.EQUITY for t in (InstrumentType.COMMON_EQUITY, InstrumentType.SHARE_PREMIUM,
                                  InstrumentType.ADDITIONAL_EQUITY, InstrumentType.PREFERRED_EQUITY)},
    **{t: Family.OTHER for t in (InstrumentType.GRANT, InstrumentType.DEFERRED_PAYMENT,
                                 InstrumentType.DEVELOPER_REIMBURSEMENT)},
}
_INTEREST_BEARING_DEBT = frozenset({
    InstrumentType.SENIOR_TERM_LOAN, InstrumentType.CONSTRUCTION_FACILITY, InstrumentType.JUNIOR_DEBT,
    InstrumentType.MEZZANINE_DEBT, InstrumentType.SHAREHOLDER_LOAN, InstrumentType.BOND,
})


def family_of(instrument_type: InstrumentType) -> Family:
    return _FAMILY_OF[instrument_type]


class CommitmentAuthority(str, Enum):
    EXPLICIT = "EXPLICIT"                        # amount is a user/contract input
    CANONICAL_SIZING_DERIVED = "CANONICAL_SIZING_DERIVED"   # amount is an OUTPUT of the existing sizing
    RESIDUAL_DERIVED = "RESIDUAL_DERIVED"        # amount is the S&U residual (e.g. SHL / additional equity)


class RepaymentMode(str, Enum):
    BULLET = "BULLET"
    LEVEL_PRINCIPAL = "LEVEL_PRINCIPAL"
    DSCR_SCULPTED = "DSCR_SCULPTED"
    EXPLICIT_SCHEDULE = "EXPLICIT_SCHEDULE"
    CASH_SWEEP = "CASH_SWEEP"
    NONE = "NONE"


class RateMode(str, Enum):
    FIXED = "FIXED"
    PERIOD_SCHEDULE = "PERIOD_SCHEDULE"
    FLOATING_BASE_PLUS_MARGIN = "FLOATING_BASE_PLUS_MARGIN"


class MaturityAuthority(str, Enum):
    EXPLICIT_DATE = "EXPLICIT_DATE"              # a calendar date supplied as an input
    PERIOD_AXIS_DERIVED = "PERIOD_AXIS_DERIVED"  # an OUTPUT of the canonical operating period axis (never FC + n years)


class Provenance(str, Enum):
    USER_INPUT = "USER_INPUT"
    LEGACY_FINANCING_PARAMS = "LEGACY_FINANCING_PARAMS"
    PRESET = "PRESET"


def _finite(name: str, value: float, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FinancingError("F3_NON_FINITE_VALUE", f"{name}={value!r}")
    if value < minimum - _TOL:
        raise FinancingError("F3_NEGATIVE_VALUE", f"{name}={value!r}")
    return float(value)


@dataclass(frozen=True)
class DrawdownEntry:
    draw_date: date
    amount_keur: float

    def __post_init__(self) -> None:
        if not isinstance(self.draw_date, date) or hasattr(self.draw_date, "hour"):
            raise FinancingError("F3_INVALID_DATE", f"draw_date={self.draw_date!r}")
        object.__setattr__(self, "amount_keur", _finite("drawdown.amount_keur", self.amount_keur))


@dataclass(frozen=True)
class InterestTerms:
    mode: RateMode
    fixed_rate: Optional[float] = None            # fraction (0.05 = 5%)
    margin_bps: Optional[int] = None
    pik: bool = False

    def __post_init__(self) -> None:
        _check_enum("interest.mode", self.mode, RateMode)
        if not isinstance(self.pik, bool):
            raise FinancingError("F3_INVALID_BOOL", f"pik={self.pik!r}")
        if self.mode is RateMode.FIXED:
            if self.fixed_rate is None:
                raise FinancingError("F3_MISSING_TERM", "FIXED interest needs fixed_rate")
            if self.margin_bps is not None:
                raise FinancingError("F3_INVALID_TYPE_COMBINATION", "FIXED interest cannot carry margin_bps")
            object.__setattr__(self, "fixed_rate", _finite("fixed_rate", self.fixed_rate))
            if self.fixed_rate > 1.0:
                raise FinancingError("F3_RATE_NOT_A_FRACTION", f"fixed_rate={self.fixed_rate!r}")
        elif self.fixed_rate is not None:
            raise FinancingError("F3_INVALID_TYPE_COMBINATION", f"{self.mode.value} cannot carry fixed_rate")
        if self.mode is RateMode.FLOATING_BASE_PLUS_MARGIN:
            if self.margin_bps is None:
                raise FinancingError("F3_MISSING_TERM", "FLOATING needs margin_bps")
            if isinstance(self.margin_bps, bool) or not isinstance(self.margin_bps, int):
                raise FinancingError("F3_INVALID_MARGIN", f"margin_bps={self.margin_bps!r} must be an int")
            if not 0 <= self.margin_bps <= _MAX_MARGIN_BPS:
                raise FinancingError("F3_INVALID_MARGIN", f"margin_bps={self.margin_bps!r} outside 0..{_MAX_MARGIN_BPS}")
        elif self.margin_bps is not None:
            raise FinancingError("F3_INVALID_TYPE_COMBINATION", f"{self.mode.value} cannot carry margin_bps")


@dataclass(frozen=True)
class RepaymentTerms:
    mode: RepaymentMode
    grace_months: int = 0
    maturity_date: Optional[date] = None
    maturity_authority: MaturityAuthority = MaturityAuthority.EXPLICIT_DATE
    tenor_years: Optional[int] = None             # informational for PERIOD_AXIS_DERIVED
    maturity_period_index: Optional[int] = None   # informational canonical period index, if one is configured

    def __post_init__(self) -> None:
        _check_enum("repayment.mode", self.mode, RepaymentMode)
        _check_enum("maturity_authority", self.maturity_authority, MaturityAuthority)
        if isinstance(self.grace_months, bool) or not isinstance(self.grace_months, int) or self.grace_months < 0:
            raise FinancingError("F3_INVALID_GRACE", f"grace_months={self.grace_months!r}")
        for name in ("tenor_years", "maturity_period_index"):
            v = getattr(self, name)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                raise FinancingError("F3_INVALID_TERM", f"{name}={v!r}")
        if self.maturity_date is not None and (
                not isinstance(self.maturity_date, date) or hasattr(self.maturity_date, "hour")):
            raise FinancingError("F3_INVALID_DATE", f"maturity_date={self.maturity_date!r}")
        if self.maturity_authority is MaturityAuthority.EXPLICIT_DATE:
            if self.mode is not RepaymentMode.NONE and self.maturity_date is None:
                raise FinancingError("F3_MISSING_TERM", f"{self.mode.value} repayment needs maturity_date")
            if self.tenor_years is not None or self.maturity_period_index is not None:
                raise FinancingError("F3_INVALID_TYPE_COMBINATION",
                                     "tenor/period-index belong to PERIOD_AXIS_DERIVED maturity")
        else:
            if self.maturity_date is not None:
                raise FinancingError("F3_INVALID_TYPE_COMBINATION",
                                     "a period-axis-derived maturity is an output and must not carry a date")
            if self.mode is RepaymentMode.NONE:
                raise FinancingError("F3_INVALID_TYPE_COMBINATION", "NONE repayment has no maturity authority")


class FeeKind(str, Enum):
    UPFRONT = "UPFRONT"
    COMMITMENT = "COMMITMENT"
    AGENCY = "AGENCY"


@dataclass(frozen=True)
class FeeTerm:
    kind: FeeKind
    rate: float                      # fraction of the stated basis
    basis: str = "COMMITMENT"        # COMMITMENT | UNDRAWN | DRAWN — documentary until an authority consumes it

    def __post_init__(self) -> None:
        _check_enum("fee.kind", self.kind, FeeKind)
        if self.basis not in _FEE_BASES:
            raise FinancingError("F3_INVALID_FEE_BASIS", f"basis={self.basis!r}; allowed {sorted(_FEE_BASES)}")
        object.__setattr__(self, "rate", _finite("fee.rate", self.rate))
        if self.rate > 1.0:
            raise FinancingError("F3_RATE_NOT_A_FRACTION", f"fee.rate={self.rate!r}")


@dataclass(frozen=True)
class CapitalProvider:
    provider_id: str
    name: str
    ownership_share: float           # fraction of legal equity; 0 for pure lenders

    def __post_init__(self) -> None:
        _check_id("provider", self.provider_id)
        _check_text("provider.name", self.name)
        object.__setattr__(self, "ownership_share", _finite("ownership_share", self.ownership_share))
        if self.ownership_share > 1.0 + _TOL:
            raise FinancingError("F3_OWNERSHIP_ABOVE_100", f"{self.provider_id}={self.ownership_share!r}")


@dataclass(frozen=True)
class FinancingInstrument:
    instrument_id: str
    instrument_type: InstrumentType
    name: str
    commitment_keur: Optional[float]
    commitment_authority: CommitmentAuthority = CommitmentAuthority.EXPLICIT
    currency: str = CANDIDATE_CURRENCY
    enabled: bool = True
    funding_source_ref: Optional[str] = None      # CapitalProvider.provider_id
    seniority_rank: int = 1                       # 1 = most senior; ties allowed (pari passu)
    drawdowns: tuple[DrawdownEntry, ...] = ()
    interest: Optional[InterestTerms] = None
    repayment: Optional[RepaymentTerms] = None
    fees: tuple[FeeTerm, ...] = ()
    provenance: Provenance = Provenance.USER_INPUT
    classification_label: str = ""                # "Club Deal", "DFI Loan": identity/label ONLY, never economics

    @property
    def family(self) -> Family:
        return family_of(self.instrument_type)

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_type, InstrumentType):
            raise FinancingError("F3_INVALID_TYPE", f"{self.instrument_type!r}")
        _check_id("instrument", self.instrument_id)
        _check_text("instrument.name", self.name)
        _check_enum("commitment_authority", self.commitment_authority, CommitmentAuthority)
        _check_enum("provenance", self.provenance, Provenance)
        if not isinstance(self.enabled, bool):
            raise FinancingError("F3_INVALID_BOOL", f"enabled={self.enabled!r} must be a strict bool")
        if not isinstance(self.classification_label, str):
            raise FinancingError("F3_INVALID_TERM", "classification_label must be text")
        if self.funding_source_ref is not None:
            _check_id("funding_source_ref", self.funding_source_ref)
        for name, kind in (("drawdowns", DrawdownEntry), ("fees", FeeTerm)):
            seq = getattr(self, name)
            if not isinstance(seq, tuple) or not all(isinstance(x, kind) for x in seq):
                raise FinancingError("F3_INVALID_TERM", f"{name} must be a tuple of {kind.__name__}")
        if self.interest is not None and not isinstance(self.interest, InterestTerms):
            raise FinancingError("F3_INVALID_TERM", "interest must be InterestTerms")
        if self.repayment is not None and not isinstance(self.repayment, RepaymentTerms):
            raise FinancingError("F3_INVALID_TERM", "repayment must be RepaymentTerms")
        if self.currency != CANDIDATE_CURRENCY:
            raise FinancingError("F3_CURRENCY_MISMATCH", f"{self.instrument_id}: {self.currency!r}")
        if isinstance(self.seniority_rank, bool) or not isinstance(self.seniority_rank, int) or self.seniority_rank < 1:
            raise FinancingError("F3_INVALID_SENIORITY", f"{self.instrument_id}: {self.seniority_rank!r}")
        if self.commitment_authority is CommitmentAuthority.EXPLICIT:
            if self.commitment_keur is None:
                raise FinancingError("F3_MISSING_TERM", f"{self.instrument_id}: EXPLICIT commitment needs an amount")
            object.__setattr__(self, "commitment_keur", _finite("commitment_keur", self.commitment_keur))
        elif self.commitment_keur is not None:
            raise FinancingError("F3_DERIVED_COMMITMENT_HAS_AMOUNT",
                                 f"{self.instrument_id}: a derived commitment is an output, not an input")
        dates = [d.draw_date for d in self.drawdowns]
        if any(b <= a for a, b in zip(dates, dates[1:])):
            raise FinancingError("F3_DRAWDOWN_ORDER", f"{self.instrument_id}: dates must strictly increase")
        if self.commitment_keur is not None and sum(d.amount_keur for d in self.drawdowns) > self.commitment_keur + _TOL:
            raise FinancingError("F3_DRAWDOWN_EXCEEDS_COMMITMENT", self.instrument_id)
        if self.instrument_type in _INTEREST_BEARING_DEBT:
            if self.interest is None or self.repayment is None:
                raise FinancingError("F3_MISSING_TERM", f"{self.instrument_id}: debt needs interest and repayment terms")
        elif self.interest is not None:
            raise FinancingError("F3_INVALID_TYPE_COMBINATION",
                                 f"{self.instrument_id}: {self.instrument_type.value} cannot carry interest terms")
        if self.family is Family.EQUITY and self.repayment is not None and self.repayment.mode is not RepaymentMode.NONE:
            raise FinancingError("F3_INVALID_TYPE_COMBINATION",
                                 f"{self.instrument_id}: equity has no repayment schedule (redemption is F4)")
        if self.instrument_type is InstrumentType.PREFERRED_EQUITY:
            raise FinancingError("F3_PREFERRED_EQUITY_DEFERRED",
                                 f"{self.instrument_id}: preferred economics need the F4 investor waterfall")
        if self.instrument_type is InstrumentType.SHAREHOLDER_LOAN and not self.funding_source_ref:
            raise FinancingError("F3_MISSING_TERM", f"{self.instrument_id}: SHL needs a capital provider")


@dataclass(frozen=True)
class FinancingCollection:
    instruments: tuple[FinancingInstrument, ...]
    providers: tuple[CapitalProvider, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.instruments, tuple) or not all(isinstance(i, FinancingInstrument) for i in self.instruments):
            raise FinancingError("F3_INVALID_TERM", "instruments must be a tuple of FinancingInstrument")
        if not isinstance(self.providers, tuple) or not all(isinstance(p, CapitalProvider) for p in self.providers):
            raise FinancingError("F3_INVALID_TERM", "providers must be a tuple of CapitalProvider")
        if self.schema_version != SCHEMA_VERSION:
            raise FinancingError("F3_UNSUPPORTED_SCHEMA_VERSION", repr(self.schema_version))
        ids = [i.instrument_id for i in self.instruments]
        if len(set(ids)) != len(ids):
            raise FinancingError("F3_DUPLICATE_INSTRUMENT_ID", ",".join(sorted(x for x in ids if ids.count(x) > 1)))
        pids = [p.provider_id for p in self.providers]
        if len(set(pids)) != len(pids):
            raise FinancingError("F3_DUPLICATE_PROVIDER_ID", ",".join(pids))
        known = set(pids)
        for inst in self.instruments:
            if inst.funding_source_ref is not None and inst.funding_source_ref not in known:
                raise FinancingError("F3_UNKNOWN_FUNDING_SOURCE", f"{inst.instrument_id} -> {inst.funding_source_ref}")
        if sum(p.ownership_share for p in self.providers) > 1.0 + _TOL:
            raise FinancingError("F3_OWNERSHIP_ABOVE_100", "sum of provider shares")

    def active(self) -> tuple[FinancingInstrument, ...]:
        """Enabled instruments in canonical order.  A disabled instrument is retained (and still
        validated and identity-bearing) for audit but has zero economic effect."""
        return tuple(i for i in self.ordered() if i.enabled)

    def ordered(self) -> tuple[FinancingInstrument, ...]:
        """Deterministic order: seniority rank, then instrument_id (never insertion order)."""
        return tuple(sorted(self.instruments, key=lambda i: (i.seniority_rank, i.instrument_id)))


def _plain(obj):
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, tuple):
        return [_plain(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _plain(getattr(obj, k)) for k in sorted(obj.__dataclass_fields__)}
    return obj


def to_canonical_dict(collection: FinancingCollection) -> dict:
    body = _plain(collection)
    body["instruments"] = [_plain(i) for i in collection.ordered()]
    body["providers"] = sorted(body["providers"], key=lambda p: p["provider_id"])
    return body


def canonical_json(collection: FinancingCollection) -> str:
    return json.dumps(to_canonical_dict(collection), sort_keys=True, separators=(",", ":"))


def candidate_identity(collection: FinancingCollection) -> str:
    """Deterministic identity of a *proposal*.  Not a Run fingerprint and never part of one."""
    return hashlib.sha256(canonical_json(collection).encode("utf-8")).hexdigest()
