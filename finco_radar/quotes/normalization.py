"""Deterministic quote normalization and size-impact metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from .contracts import ExecutionQuote, QuoteStatus


def to_raw_amount(amount: Decimal, decimals: int) -> int:
    if decimals < 0:
        raise ValueError("decimals must be non-negative")
    if amount < 0:
        raise ValueError("amount must be non-negative")
    scale = Decimal(10) ** decimals
    return int((amount * scale).to_integral_value(rounding=ROUND_DOWN))


def from_raw_amount(raw_amount: int, decimals: int) -> Decimal:
    if raw_amount < 0:
        raise ValueError("raw_amount must be non-negative")
    if decimals < 0:
        raise ValueError("decimals must be non-negative")
    return Decimal(raw_amount) / (Decimal(10) ** decimals)


def quote_size_impact_bps(small: ExecutionQuote, large: ExecutionQuote) -> Decimal:
    """Return positive bps when the larger exact-input quote has a worse rate."""
    if small.status is not QuoteStatus.QUOTE_OK or large.status is not QuoteStatus.QUOTE_OK:
        raise ValueError("size impact requires two QUOTE_OK observations")
    if small.side is not large.side:
        raise ValueError("quotes must have the same side")
    if small.input_asset != large.input_asset or small.output_asset != large.output_asset:
        raise ValueError("quotes must have the same input/output assets")
    small_rate = small.effective_output_per_input
    large_rate = large.effective_output_per_input
    if small_rate is None or large_rate is None or small_rate <= 0:
        raise ValueError("quotes must have positive normalized amounts")
    return ((small_rate - large_rate) / small_rate) * Decimal(10_000)


def enforce_freshness(
    quote: ExecutionQuote,
    *,
    now: datetime | None = None,
    max_age_seconds: int,
) -> ExecutionQuote:
    if quote.status is not QuoteStatus.QUOTE_OK:
        return quote
    current = now or datetime.now(timezone.utc)
    age = (current - quote.quoted_at).total_seconds()
    if age < 0 or age > max_age_seconds:
        return quote.with_status(
            QuoteStatus.STALE_QUOTE,
            f"quote age {age:.3f}s exceeds allowed window {max_age_seconds}s",
        )
    return quote
