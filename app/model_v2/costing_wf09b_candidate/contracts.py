"""WF-09B cost-receipt and LCOE/LCOS reconciliation contracts — RELEASE-CLOSED CANDIDATE.

A read-only layer that prepares explicitly supplied, canonical-shaped
project-finance evidence for the already implemented WF-09A arithmetic
(``research.wf09a.costing.calculate``). It introduces NO second LCOE formula,
no discount-rate or convention default, no energy reconstruction and no
engine/Run/persistence/route/flag. Nothing imports it.

Conventions:

- Numbers are exact ``Decimal`` (never ``float``/``bool``/``str``).
- ``None`` is MISSING evidence and yields a typed UNAVAILABLE result; an
  explicit ``Decimal(0)`` is a legitimate zero. They are never conflated.
- Every cost component carries a unique, traceable source identity.
- A cash movement is not a cost: principal, drawdowns, equity, reserve funding,
  depreciation, accounting tax, distributions and net arbitrage spread are
  recordable only as EXCLUDED movements.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import Enum
from typing import Optional

#: Release-closure flag (house convention for release-closed candidates).
ACTIVATION_ENABLED = False

WF09B_CANDIDATE_AUTHORITY = "WF09B_COST_RECEIPTS_CANDIDATE_V0"
NON_AUTHORITATIVE = True

#: Reference parity is NOT assessed: the canonical Solar/Wind Run results do not
#: expose the line-level evidence this layer needs (see the design document).
REFERENCE_PARITY = "NOT_ASSESSED_MISSING_LINE_LEVEL_EVIDENCE"

CANDIDATE = "CANDIDATE"
UNAVAILABLE = "UNAVAILABLE"

#: Tolerance for the sum of the five component quotients vs the total quotient.
#: WF09A divides at a fixed 50 significant digits; each quotient is rounded to
#: half an ulp, i.e. at most 5e-41 for values below 1e9 EUR/MWh, five components
#: give < 3e-40. 1e-30 is a deliberately generous, still-negligible bound.
COMPONENT_SUM_TOLERANCE = Decimal("1e-30")


class Wf09bError(ValueError):
    """Typed fail-closed error; the message starts with a stable code."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def exact_arithmetic(func):
    """Run in a fixed 50-digit Decimal context so results never depend on the caller's."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            return func(*args, **kwargs)

    return wrapper


def require_release() -> None:
    if not ACTIVATION_ENABLED:
        raise Wf09bError("WF09B_RELEASE_CLOSED", "independent financial release approval required")


def activation_marker() -> str:
    return "RELEASE_CLOSED" if not ACTIVATION_ENABLED else "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"


# ── Closed vocabularies ─────────────────────────────────────────────────────


class Vertical(str, Enum):
    SOLAR = "SOLAR"
    WIND = "WIND"
    BESS = "BESS"
    DATA_CENTER = "DATA_CENTER"
    EV_CHARGING = "EV_CHARGING"


class Metric(str, Enum):
    UNLEVERED_PRE_FINANCING = "unlevered_pre_financing"
    LEVERED_AFTER_TAX = "levered_after_tax"
    LCOS = "lcos"


class Component(str, Enum):
    """Order matches ``research.wf09a.costing.COMPONENTS``."""

    DEVEX = "devex"
    CAPEX = "capex"
    OPEX = "opex"
    FINANCE = "finance"
    TAX = "tax"


class Phase(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    OPERATING = "OPERATING"


class LineKind(str, Enum):
    # cost kinds
    DEVEX_COST = "DEVEX_COST"
    CONSTRUCTION_CAPEX = "CONSTRUCTION_CAPEX"
    OPERATING_OPEX = "OPERATING_OPEX"
    CHARGING_ELECTRICITY_PAID = "CHARGING_ELECTRICITY_PAID"
    GRID_IMPORT_CHARGE = "GRID_IMPORT_CHARGE"
    AUXILIARY_ELECTRICITY_PAID = "AUXILIARY_ELECTRICITY_PAID"
    FINANCING_INTEREST = "FINANCING_INTEREST"
    FINANCING_FEE = "FINANCING_FEE"
    IDC = "IDC"
    CASH_TAX_PAID = "CASH_TAX_PAID"
    CASH_TAX_REFUND = "CASH_TAX_REFUND"
    # lifecycle CAPEX: recognised but UNAVAILABLE until approved evidence exists
    AUGMENTATION_CAPEX = "AUGMENTATION_CAPEX"
    REPLACEMENT_CAPEX = "REPLACEMENT_CAPEX"
    # cash movements / non-cash items that are NEVER a cost
    PRINCIPAL_REPAYMENT = "PRINCIPAL_REPAYMENT"
    DEBT_DRAWDOWN = "DEBT_DRAWDOWN"
    EQUITY_FUNDING = "EQUITY_FUNDING"
    RESERVE_FUNDING = "RESERVE_FUNDING"
    DEPRECIATION = "DEPRECIATION"
    ACCOUNTING_TAX_EXPENSE = "ACCOUNTING_TAX_EXPENSE"
    NET_ARBITRAGE_SPREAD = "NET_ARBITRAGE_SPREAD"
    DISTRIBUTION = "DISTRIBUTION"


KIND_COMPONENT = {
    LineKind.DEVEX_COST: Component.DEVEX,
    LineKind.CONSTRUCTION_CAPEX: Component.CAPEX,
    LineKind.AUGMENTATION_CAPEX: Component.CAPEX,
    LineKind.REPLACEMENT_CAPEX: Component.CAPEX,
    LineKind.OPERATING_OPEX: Component.OPEX,
    LineKind.CHARGING_ELECTRICITY_PAID: Component.OPEX,
    LineKind.GRID_IMPORT_CHARGE: Component.OPEX,
    LineKind.AUXILIARY_ELECTRICITY_PAID: Component.OPEX,
    LineKind.FINANCING_INTEREST: Component.FINANCE,
    LineKind.FINANCING_FEE: Component.FINANCE,
    LineKind.IDC: Component.FINANCE,
    LineKind.CASH_TAX_PAID: Component.TAX,
    LineKind.CASH_TAX_REFUND: Component.TAX,
}
NON_COST_KINDS = frozenset(k for k in LineKind if k not in KIND_COMPONENT)
LIFECYCLE_KINDS = frozenset({LineKind.AUGMENTATION_CAPEX, LineKind.REPLACEMENT_CAPEX})
BESS_ONLY_KINDS = frozenset({LineKind.CHARGING_ELECTRICITY_PAID, LineKind.GRID_IMPORT_CHARGE,
                             LineKind.AUXILIARY_ELECTRICITY_PAID})


class Treatment(str, Enum):
    ATTRIBUTED = "ATTRIBUTED"
    EXCLUDED_MOVEMENT = "EXCLUDED_MOVEMENT"


class EnergyBoundary(str, Enum):
    DELIVERED_AC_EXPORT = "DELIVERED_AC_EXPORT"
    DELIVERED_AC_DISCHARGE = "DELIVERED_AC_DISCHARGE"


class PriceBasis(str, Enum):
    REAL = "REAL"
    NOMINAL = "NOMINAL"


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


class ChargingEvidence(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXPLICIT_BUY = "EXPLICIT_BUY"
    NET_SPREAD = "NET_SPREAD"


class AugmentationEvidence(str, Enum):
    """Whether lifecycle replacement / augmentation CAPEX is evidenced as absent."""

    NOT_APPLICABLE_EVIDENCED = "NOT_APPLICABLE_EVIDENCED"
    UNKNOWN = "UNKNOWN"


class Decision(str, Enum):
    """The only representable state of a Financial Owner decision is OPEN."""

    OPEN = "OPEN"


# ── Strict validators ───────────────────────────────────────────────────────


def dec(value, label: str, *, nonnegative: bool = False, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise Wf09bError("WF09B_VALUE", f"{label} must be a finite Decimal")
    if positive and value <= 0:
        raise Wf09bError("WF09B_VALUE", f"{label} must be strictly positive")
    if nonnegative and value < 0:
        raise Wf09bError("WF09B_VALUE", f"{label} must be non-negative")
    return value


def opt_dec(value, label: str, **kw) -> Optional[Decimal]:
    return None if value is None else dec(value, label, **kw)


def ident(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160 \
            or not value.isprintable() or value != value.strip():
        raise Wf09bError("WF09B_IDENTITY", f"{label} must be a bounded, non-empty printable string")
    return value


def opt_ident(value, label: str) -> Optional[str]:
    return None if value is None else ident(value, label)


def enum(value, kind, label: str):
    if not isinstance(value, kind):
        raise Wf09bError("WF09B_VALUE", f"{label} must be a {kind.__name__}")
    return value


def calendar(value, label: str) -> date:
    if not isinstance(value, date) or hasattr(value, "hour"):
        raise Wf09bError("WF09B_VALUE", f"{label} must be a calendar date")
    return value


def unique(values, label: str) -> None:
    seen = set()
    for v in values:
        if v in seen:
            raise Wf09bError("WF09B_DUPLICATE", f"{label} {v!r} is used more than once")
        seen.add(v)


# ── Canonical provenance identity (context-free) ────────────────────────────


def _canon(value):
    if isinstance(value, Decimal):
        sign, digits, exp = value.as_tuple()
        text = "".join(map(str, digits)) or "0"
        zero = not any(digits)
        return {"d": ("-" if sign and not zero else "") + text, "e": 0 if zero else exp}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _canon(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return [_canon(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    return value


def canonical_json(value) -> str:
    return json.dumps(_canon(value), sort_keys=True, separators=(",", ":"))


def identity(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
