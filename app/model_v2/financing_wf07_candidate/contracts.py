"""WF-07 financing & reserve integration contracts — RELEASE-CLOSED CANDIDATE.

Nothing here is financial authority. Every calculation entry point is gated
behind :data:`ACTIVATION_ENABLED`, a module-level literal ``False``; only
isolated acceptance fixtures may enable it in memory. No environment variable,
payload or product surface can, and no production module imports this package.

The candidate consumes IMMUTABLE, EXPLICITLY SUPPLIED evidence (period,
facility, contractual and paid debt service, available cash, reserve target,
opening reserve balance, source identity, evidence status). It never resizes
debt, never changes a contractual payment and never reads another candidate.

Conventions:

- Numbers are exact ``Decimal`` (never ``float``/``bool``/``str``).
- ``None`` is MISSING evidence and yields a typed UNAVAILABLE result; an
  explicit ``Decimal(0)`` is a legitimate zero. They are never conflated.
- Unresolved Financial Owner choices are :class:`Decision` members whose only
  value is ``OPEN``; combinations without an explicit policy are UNSUPPORTED.
- Source identities are bounded explicit strings, unique wherever an amount
  could otherwise be counted twice.
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

WF07_CANDIDATE_AUTHORITY = "WF07_FINANCING_RESERVES_CANDIDATE_V0"
NON_AUTHORITATIVE = True

#: Reconciles two exact-Decimal computations made at the 40-digit context.
TOLERANCE = Decimal("1e-25")

CANDIDATE = "CANDIDATE"
UNAVAILABLE = "UNAVAILABLE"
UNSUPPORTED = "UNSUPPORTED"


class Wf07Error(ValueError):
    """Typed fail-closed error; the message starts with a stable code."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def exact_arithmetic(func):
    """Run in a 40-digit Decimal context so results never depend on the caller's."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            return func(*args, **kwargs)

    return wrapper


def require_release() -> None:
    if not ACTIVATION_ENABLED:
        raise Wf07Error(
            "WF07_RELEASE_CLOSED",
            "independent financial release approval required")


def activation_marker() -> str:
    return "RELEASE_CLOSED" if not ACTIVATION_ENABLED else "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"


# ── Closed vocabularies ─────────────────────────────────────────────────────


class Phase(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    OPERATING = "OPERATING"


class Layer(str, Enum):
    """Creditor layers. SENIOR is N pari-passu facilities; ranking is explicit."""

    SENIOR = "SENIOR"
    JUNIOR = "JUNIOR"
    SHAREHOLDER_LOAN = "SHAREHOLDER_LOAN"


class ClaimClass(str, Enum):
    """What a cash flow legally IS. SHL principal/interest is sponsor debt,
    never equity and never a distribution."""

    LEGAL_EQUITY = "LEGAL_EQUITY"
    SPONSOR_DEBT = "SPONSOR_DEBT"
    EXTERNAL_DEBT = "EXTERNAL_DEBT"
    DISTRIBUTION = "DISTRIBUTION"


class InterestMode(str, Enum):
    CASH = "CASH"
    PIK = "PIK"


class InterestTreatment(str, Enum):
    """Accounting classification only; tax deductibility is never decided here."""

    CAPITALIZED = "CAPITALIZED"
    OPERATING_EXPENSE_CANDIDATE = "OPERATING_EXPENSE_CANDIDATE"


class ReserveType(str, Enum):
    """DSRA is cash-funded; DSRF is a facility-backed standby. Never mixed."""

    DSRA = "DSRA"
    DSRF = "DSRF"


class Decision(str, Enum):
    """The only representable state of a Financial Owner decision is OPEN."""

    OPEN = "OPEN"


class EvidenceStatus(str, Enum):
    EVIDENCED = "EVIDENCED"
    MISSING = "MISSING"


# ── Strict validators ───────────────────────────────────────────────────────


def dec(value, label: str, *, nonnegative: bool = False, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise Wf07Error("WF07_VALUE", f"{label} must be a finite Decimal")
    if positive and value <= 0:
        raise Wf07Error("WF07_VALUE", f"{label} must be strictly positive")
    if nonnegative and value < 0:
        raise Wf07Error("WF07_VALUE", f"{label} must be non-negative")
    return value


def opt_dec(value, label: str, **kw) -> Optional[Decimal]:
    """``None`` is MISSING and stays ``None``; anything else must be valid."""
    return None if value is None else dec(value, label, **kw)


def ident(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128 \
            or not value.isprintable() or value != value.strip():
        raise Wf07Error("WF07_IDENTITY", f"{label} must be a bounded, non-empty printable string")
    return value


def index(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Wf07Error("WF07_VALUE", f"{label} must be a non-negative integer")
    return value


def enum(value, kind, label: str):
    if not isinstance(value, kind):
        raise Wf07Error("WF07_VALUE", f"{label} must be a {kind.__name__}")
    return value


def calendar(value, label: str) -> date:
    if not isinstance(value, date) or hasattr(value, "hour"):
        raise Wf07Error("WF07_VALUE", f"{label} must be a calendar date")
    return value


def unique(values, label: str) -> None:
    seen = set()
    for v in values:
        if v in seen:
            raise Wf07Error("WF07_DUPLICATE", f"{label} {v!r} is used more than once")
        seen.add(v)


# ── Canonical provenance identity ───────────────────────────────────────────


def _canon(value):
    if isinstance(value, Decimal):
        sign, digits, exp = value.as_tuple()
        # context-free text from the digit tuple (never str(Decimal) under a context)
        text = "".join(map(str, digits)) or "0"
        return {"d": ("-" if sign and any(digits) else "") + text, "e": exp if any(digits) else 0}
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
