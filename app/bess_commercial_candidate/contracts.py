"""BESS commercial and lender-facing contracts (WF-08A) — RELEASE-CLOSED CANDIDATE.

Nothing here is financial authority. Every calculation, reconciliation and
parse entry point is gated behind :data:`ACTIVATION_ENABLED`, a module-level
literal ``False``. Only isolated acceptance fixtures may enable the gate in
memory; no environment variable, payload or product surface can, and no
production code path imports this package.

The candidate CONSUMES native BESS evidence (``domain.bess.dispatch`` hourly
evidence and ``domain.bess.settlement`` period proposals) in their existing
units (MWh, MW, EUR/MWh, kEUR). It never recalculates battery physics and
never substitutes the legacy ``domain/revenue/bess.py`` approximation.

Conventions pinned for every contract in this package:

- Numeric inputs are exact ``Decimal`` (never ``float``/``bool``/``str``).
- ``None`` is MISSING evidence and yields a typed UNAVAILABLE result; an
  explicit ``Decimal(0)`` is a legitimate zero. They are never conflated.
- Economic choices that the Financial Owner has not decided are typed
  :class:`Decision` members whose ONLY value is ``OPEN``; a contract cannot
  encode a resolved policy until a later, separately approved version.
- Provenance identities are bounded explicit strings and must be unique
  wherever a source amount could otherwise be counted twice.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import Enum
from typing import Optional

#: Release-closure flag (house convention for release-closed candidates).
ACTIVATION_ENABLED = False

SCHEMA = "finco.bess-commercial-candidate"
SCHEMA_VERSION = 1

#: Tolerance for reconciling two exact-Decimal computations made at the native
#: 40-digit context (energy in MWh, money in kEUR). Not a financial rounding.
RECONCILIATION_TOLERANCE = Decimal("1e-25")

CANDIDATE = "CANDIDATE"
UNAVAILABLE = "UNAVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"


class BessCommercialError(ValueError):
    """Typed fail-closed error; the message starts with a stable code."""


def exact_arithmetic(func):
    """Run a public function in the native 40-digit Decimal context (cf. ``domain.bess.dispatch.evaluate``),
    so results never depend on the caller's ambient precision or rounding."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            return func(*args, **kwargs)

    return wrapper


def require_release() -> None:
    if not ACTIVATION_ENABLED:
        raise BessCommercialError(
            "BESS_COMMERCIAL_RELEASE_CLOSED: independent financial release "
            "approval required")


def activation_marker() -> str:
    return "RELEASE_CLOSED" if not ACTIVATION_ENABLED else "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY"


# ── Typed vocabularies (closed sets) ─────────────────────────────────────────


class ChargingBasis(str, Enum):
    NET_SPREAD = "NET_SPREAD"
    EXPLICIT_BUY_LEG = "EXPLICIT_BUY_LEG"


class RevenueClass(str, Enum):
    CONTRACTED = "CONTRACTED"
    CONTRACTED_UNSECURED = "CONTRACTED_UNSECURED"
    MERCHANT = "MERCHANT"


class Service(str, Enum):
    ENERGY_THROUGHPUT = "ENERGY_THROUGHPUT"
    CAPACITY_RESERVATION = "CAPACITY_RESERVATION"
    ANCILLARY_AVAILABILITY = "ANCILLARY_AVAILABILITY"
    MERCHANT_ENERGY = "MERCHANT_ENERGY"


class Direction(str, Enum):
    DISCHARGE_AC = "DISCHARGE_AC"
    CHARGE_AC = "CHARGE_AC"


class Party(str, Enum):
    OFFTAKER = "OFFTAKER"
    PROJECT = "PROJECT"


class AugmentationTrigger(str, Enum):
    SOH_THRESHOLD = "SOH_THRESHOLD"
    PLANNED_EVENT = "PLANNED_EVENT"
    WARRANTY_TRIGGERED = "WARRANTY_TRIGGERED"


class Decision(str, Enum):
    """The only representable state of a Financial Owner decision is OPEN."""

    OPEN = "OPEN"


# ── Strict validators ────────────────────────────────────────────────────────


def dec(value, label: str, *, nonnegative: bool = False, positive: bool = False,
        minimum: Optional[Decimal] = None, maximum: Optional[Decimal] = None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: {label} must be a finite Decimal")
    if positive and value <= 0:
        raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: {label} must be strictly positive")
    if nonnegative and value < 0:
        raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: {label} must be non-negative")
    if minimum is not None and value < minimum:
        raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: {label} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: {label} must be at most {maximum}")
    return value


def opt_dec(value, label: str, **kw) -> Optional[Decimal]:
    """``None`` = MISSING (kept as None); anything else must be a valid Decimal."""
    return None if value is None else dec(value, label, **kw)


def ident(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 200:
        raise BessCommercialError(f"BESS_COMMERCIAL_IDENTITY: bounded explicit {label} required")
    return value


def opt_ident(value, label: str) -> Optional[str]:
    return None if value is None else ident(value, label)


def utc_hour(value, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise BessCommercialError(f"BESS_COMMERCIAL_TIME: {label} must be a timezone-aware UTC datetime")
    if value.minute or value.second or value.microsecond:
        raise BessCommercialError(f"BESS_COMMERCIAL_TIME: {label} must be an exact UTC hour")
    return value


def calendar_date(value, label: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise BessCommercialError(f"BESS_COMMERCIAL_TIME: {label} must be a calendar date")
    return value


def enum_member(value, enum_type, label: str):
    if not isinstance(value, enum_type):
        raise BessCommercialError(f"BESS_COMMERCIAL_UNSUPPORTED: {label} {value!r} is not a supported member")
    return value


def open_decision(value, label: str) -> Decision:
    if value is not Decision.OPEN:
        raise BessCommercialError(
            f"BESS_COMMERCIAL_OWNER_DECISION: {label} is a Financial Owner decision and can only be "
            "recorded as OPEN in this candidate")
    return value


def unique(ids, label: str) -> None:
    seen = set()
    for item in ids:
        if item in seen:
            raise BessCommercialError(f"BESS_COMMERCIAL_DOUBLE_COUNT: duplicate {label} {item!r}")
        seen.add(item)


def tuple_of(value, label: str) -> tuple:
    if not isinstance(value, tuple):
        raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: {label} must be an immutable tuple")
    return value


def reconciles(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= RECONCILIATION_TOLERANCE


# ── Canonical serialization and provenance identity ──────────────────────────


#: Serialization bound: a finite Decimal beyond this many digits / this decimal exponent is rejected rather than
#: expanded (a plain-notation string of ``1E+999999999`` would otherwise be a memory hazard).
_MAX_DECIMAL_DIGITS = 1000
_MAX_DECIMAL_EXPONENT = 1000


def decimal_text(value: Decimal) -> str:
    """Exact, canonical plain-notation text of a finite Decimal, independent of the ambient Decimal context.

    Built from the value's digit tuple, so no operation can round it: ``Decimal.normalize()``, ``quantize()``
    and arithmetic all round to the CALLER's precision and rounding mode, which would make canonical JSON and
    the SHA-256 identity depend on the caller. Equal values share one text regardless of scale (``1.0`` /
    ``1.000`` / ``1E+0`` -> ``"1"``); every zero, including negative zero, is ``"0"``.
    """
    if not isinstance(value, Decimal) or not value.is_finite():
        raise BessCommercialError("BESS_COMMERCIAL_VALUE: non-finite Decimal cannot be serialized")
    sign, digit_tuple, exponent = value.as_tuple()
    digits = list(digit_tuple)
    if not any(digits):
        return "0"
    if len(digits) > _MAX_DECIMAL_DIGITS or abs(value.adjusted()) > _MAX_DECIMAL_EXPONENT:
        raise BessCommercialError("BESS_COMMERCIAL_VALUE: Decimal outside the bounded serialization domain")
    while digits[-1] == 0:                 # strip trailing zeros: scale-independent identity
        digits.pop()
        exponent += 1
    body = "".join(map(str, digits))
    if exponent >= 0:
        text = body + "0" * exponent
    else:
        point = len(body) + exponent       # digits before the decimal point
        text = body[:point] + "." + body[point:] if point > 0 else "0." + "0" * -point + body
    return "-" + text if sign else text


def _encode(value):
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {"_type": type(value).__name__}
        for field in dataclasses.fields(value):
            out[field.name] = _encode(getattr(value, field.name))
        return out
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise BessCommercialError(f"BESS_COMMERCIAL_VALUE: cannot serialize {type(value).__name__}")


def canonical_json(value) -> str:
    """Deterministic JSON of any contract/result: sorted keys, exact Decimal text,
    explicit nulls (MISSING stays distinguishable from zero)."""
    envelope = {"_schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                "activation": activation_marker(), "payload": _encode(value)}
    return json.dumps(envelope, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def identity(value) -> str:
    """SHA-256 provenance identity of the canonical serialization."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
