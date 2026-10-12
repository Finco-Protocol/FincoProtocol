"""Agreement-bound candidate data, not an authorization or runtime input."""
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
import hashlib
import json
import math


# Match the existing sponsor tier/result contracts; no production tolerances change.
OWNERSHIP_TOLERANCE = 1e-8
CASH_TOLERANCE_KEUR = 1e-6


class InvestmentClass(str, Enum):
    COMMON_EQUITY = "COMMON_EQUITY"
    PREFERRED_EQUITY = "PREFERRED_EQUITY"
    SHAREHOLDER_LOAN = "SHAREHOLDER_LOAN"


class Priority(str, Enum):
    RETURN_OF_CAPITAL = "RETURN_OF_CAPITAL"
    PREFERRED_RETURN = "PREFERRED_RETURN"
    GP_CATCH_UP = "GP_CATCH_UP"
    PROMOTE = "PROMOTE"
    RESIDUAL = "RESIDUAL"


def _identity(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be an explicit nonblank identity without outer whitespace")


def _amount(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class Investor:
    investor_id: str
    investment_class: InvestmentClass
    ownership_fraction: float
    commitment_keur: float

    def __post_init__(self):
        _identity(self.investor_id, "investor_id")
        if not isinstance(self.investment_class, InvestmentClass):
            raise ValueError("investment_class must be explicitly typed")
        _amount(self.ownership_fraction, "ownership_fraction")
        _amount(self.commitment_keur, "commitment_keur")
        if self.ownership_fraction > 1:
            raise ValueError("ownership_fraction exceeds one")
        if self.investment_class == InvestmentClass.SHAREHOLDER_LOAN and self.ownership_fraction != 0:
            raise ValueError("SHL is not legal equity ownership")


@dataclass(frozen=True)
class Contribution:
    investor_id: str
    cash_date: date
    amount_keur: float

    def __post_init__(self):
        _identity(self.investor_id, "investor_id")
        if type(self.cash_date) is not date:
            raise ValueError("cash_date must be an explicit date")
        _amount(self.amount_keur, "amount_keur")


@dataclass(frozen=True)
class Entitlements:
    priorities: tuple[Priority, ...]
    preferred_rate_pa: float | None = None
    carry_fraction: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "priorities", tuple(self.priorities))
        if (not self.priorities or any(not isinstance(p, Priority) for p in self.priorities)
                or len(set(self.priorities)) != len(self.priorities)):
            raise ValueError("explicit, unique typed priorities are required")
        for name in ("preferred_rate_pa", "carry_fraction"):
            value = getattr(self, name)
            if value is not None:
                _amount(value, name)
                if value >= 1:
                    raise ValueError(f"{name} must be below one")
        if Priority.PREFERRED_RETURN in self.priorities and self.preferred_rate_pa is None:
            raise ValueError("preferred return requires an explicit contractual rate")
        if any(p in self.priorities for p in (Priority.GP_CATCH_UP, Priority.PROMOTE)) and self.carry_fraction is None:
            raise ValueError("carry tiers require an explicit contractual fraction")


@dataclass(frozen=True)
class DistributionEvidence:
    """Caller-supplied receipt, NOT proof of authorization or canonical provenance.

    Future integration must bind net equity receipts to an authorized immutable Run.
    Synthetic callers may supply synthetic references; this module cannot verify them.
    """
    evidence_reference: str
    period_dates: tuple[date, ...]
    net_equity_cash_keur: tuple[float, ...]

    def __post_init__(self):
        _identity(self.evidence_reference, "evidence_reference")
        object.__setattr__(self, "period_dates", tuple(self.period_dates))
        object.__setattr__(self, "net_equity_cash_keur", tuple(self.net_equity_cash_keur))
        if not self.period_dates or len(self.period_dates) != len(self.net_equity_cash_keur):
            raise ValueError("explicit dates and cash must have equal nonzero lengths")
        if any(type(d) is not date for d in self.period_dates):
            raise ValueError("period dates must be explicit dates")
        if tuple(sorted(set(self.period_dates))) != self.period_dates:
            raise ValueError("period dates must be strictly increasing")
        for amount in self.net_equity_cash_keur:
            _amount(amount, "net_equity_cash_keur")


@dataclass(frozen=True)
class InvestorAgreement:
    agreement_reference: str
    investors: tuple[Investor, ...]
    contributions: tuple[Contribution, ...]
    entitlements: Entitlements
    evidence: DistributionEvidence
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported candidate schema version")
        _identity(self.agreement_reference, "agreement_reference")
        if not isinstance(self.entitlements, Entitlements) or not isinstance(self.evidence, DistributionEvidence):
            raise ValueError("typed entitlements and evidence are required")
        investors = tuple(self.investors)
        contributions = tuple(self.contributions)
        if not investors or any(not isinstance(i, Investor) for i in investors):
            raise ValueError("at least one typed investor is required")
        if any(not isinstance(c, Contribution) for c in contributions):
            raise ValueError("typed contributions are required")
        by_id = {i.investor_id: i for i in investors}
        if len(by_id) != len(investors):
            raise ValueError("duplicate investor identities")
        equity = [i for i in investors if i.investment_class != InvestmentClass.SHAREHOLDER_LOAN]
        if abs(math.fsum(i.ownership_fraction for i in equity) - 1.0) > OWNERSHIP_TOLERANCE:
            raise ValueError("legal equity ownership must sum to one")
        if (any(i.investment_class == InvestmentClass.PREFERRED_EQUITY for i in investors)
                and self.entitlements.preferred_rate_pa is None):
            raise ValueError("preferred equity requires an explicit contractual rate")
        for c in contributions:
            if c.investor_id not in by_id:
                raise ValueError("contribution investor is not in agreement")
            if c.cash_date not in self.evidence.period_dates:
                raise ValueError("contribution date is not on the explicit candidate axis")
        for i in investors:
            called = math.fsum(c.amount_keur for c in contributions if c.investor_id == i.investor_id)
            if called > i.commitment_keur + CASH_TOLERANCE_KEUR:
                raise ValueError("contributions exceed commitment")
        object.__setattr__(self, "investors", tuple(sorted(investors, key=lambda i: i.investor_id)))
        object.__setattr__(self, "contributions", tuple(sorted(
            contributions, key=lambda c: (c.cash_date, c.investor_id, c.amount_keur))))

    def unsupported_reasons(self) -> tuple[str, ...]:
        reasons = []
        if any(i.investment_class != InvestmentClass.COMMON_EQUITY for i in self.investors):
            reasons.append("Only common legal equity has a proven equivalent candidate adapter")
        if self.entitlements.priorities != (Priority.RESIDUAL,):
            reasons.append("ROC, preference, catch-up and carry tiers require independent financial review")
        if self.entitlements.preferred_rate_pa is not None or self.entitlements.carry_fraction is not None:
            reasons.append("Explicit preference/carry terms are declared but not executable")
        return tuple(reasons)

    def to_json(self) -> str:
        def encode(value):
            if type(value) is date:
                return value.isoformat()
            raise TypeError(f"unsupported serialization type: {type(value).__name__}")
        return json.dumps(asdict(self), default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def content_digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
