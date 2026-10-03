"""Canonical Tokenized Markets basis authority.

One rule is shared by current composition and historical intelligence:
basis exists only for AVAILABLE representation evidence against a FRESH /
AVAILABLE reference, with source timestamps on both sides no more than
300 seconds apart. Collection time never substitutes for source time.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

BASIS_SCALE = Decimal(10_000)
BASIS_MAX_CLOCK_SKEW_SECONDS = 300


def compute_basis_bps(representation_price: str, reference_price: str) -> Decimal:
    ratio = (Decimal(representation_price) / Decimal(reference_price)) - 1
    return (ratio * BASIS_SCALE).quantize(Decimal("1"))


def basis_for_evidence(
    *,
    representation_price: str | None,
    representation_state: str,
    representation_source_timestamp: str | None,
    reference_price: str | None,
    reference_state: str,
    reference_source_timestamp: str | None,
) -> tuple[str | None, str | None]:
    if representation_price is None:
        return None, "REPRESENTATION_PRICE_UNAVAILABLE"
    if representation_state != "AVAILABLE":
        return None, "REPRESENTATION_STALE"
    if reference_price is None or reference_state == "UNAVAILABLE":
        return None, "REFERENCE_UNAVAILABLE"
    if reference_state not in ("FRESH", "AVAILABLE"):
        return None, "REFERENCE_STALE"
    if not representation_source_timestamp or not reference_source_timestamp:
        return None, "EVIDENCE_TIMESTAMP_UNAVAILABLE"
    try:
        rep_stamp = datetime.fromisoformat(representation_source_timestamp)
        ref_stamp = datetime.fromisoformat(reference_source_timestamp)
    except (ValueError, TypeError):
        return None, "EVIDENCE_TIMESTAMP_UNAVAILABLE"
    if rep_stamp.tzinfo is None or ref_stamp.tzinfo is None:
        return None, "EVIDENCE_TIMESTAMP_UNAVAILABLE"
    if abs((rep_stamp - ref_stamp).total_seconds()) > BASIS_MAX_CLOCK_SKEW_SECONDS:
        return None, "EVIDENCE_SKEW_EXCEEDS_POLICY"
    try:
        basis = compute_basis_bps(representation_price, reference_price)
    except (InvalidOperation, ZeroDivisionError):
        return None, "BASIS_ARITHMETIC_INVALID"
    return str(basis), None
