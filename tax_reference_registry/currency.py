"""Currency policy: explicit NO_IMPLICIT_FX.

The registry stores thresholds and values in their native currency (EUR, PLN,
CZK, SEK, NOK, DKK, CHF, GBP, CLP, UYU, DOP, HUF, RSD, BAM, MKD, ALL, ...).
Comparing or combining amounts in different currencies is a hard error unless
a caller supplies an explicit, pinned conversion table. There is no default FX
rate anywhere in this package.
"""
from __future__ import annotations

import enum


class KnownCurrency(enum.Enum):
    """Currencies observed in the T01-B/T01-C reference vocabulary (ISO-4217)."""

    EUR = "EUR"
    PLN = "PLN"
    CZK = "CZK"
    SEK = "SEK"
    NOK = "NOK"
    DKK = "DKK"
    CHF = "CHF"
    GBP = "GBP"
    CLP = "CLP"
    UYU = "UYU"
    DOP = "DOP"
    HUF = "HUF"
    RSD = "RSD"
    BAM = "BAM"
    MKD = "MKD"
    ALL = "ALL"
    USD = "USD"


class NoImplicitFxError(TypeError):
    """Raised when amounts in different currencies are combined without an
    explicit pinned FX table. Never raised with a default rate attached."""


class CurrencyPolicy:
    """Comparison gate for cross-currency reference values.

    ``fx_table`` maps (from_code, to_code) -> Decimal rate and must be supplied
    explicitly by the caller (owner decision; see NEXT_INTEGRATION_CONTRACT).
    Without it, every cross-currency comparison raises NoImplicitFxError.
    """

    def __init__(self, fx_table: dict[tuple[str, str], "Decimal"] | None = None) -> None:
        self._fx = dict(fx_table or {})

    def compare(
        self,
        left_value,
        left_currency: str | None,
        right_value,
        right_currency: str | None,
    ) -> int:
        from decimal import Decimal

        if left_currency != right_currency:
            raise NoImplicitFxError(
                "NO_IMPLICIT_FX: refusing to compare "
                f"{left_value!r} {left_currency or '<none>'} with "
                f"{right_value!r} {right_currency or '<none>'} without an "
                "explicit pinned FX table."
            )
        lv = Decimal(str(left_value))
        rv = Decimal(str(right_value))
        return (lv > rv) - (lv < rv)

    def convert(self, value, from_code: str, to_code: str):
        from decimal import Decimal

        if from_code == to_code:
            return Decimal(str(value))
        key = (from_code, to_code)
        if key not in self._fx:
            raise NoImplicitFxError(
                f"NO_IMPLICIT_FX: no pinned rate for {from_code}->{to_code}; "
                "supply CurrencyPolicy(fx_table=...) explicitly."
            )
        return Decimal(str(value)) * Decimal(str(self._fx[key]))


#: Module-level policy with no FX table: every cross-currency operation fails.
NO_IMPLICIT_FX = CurrencyPolicy(fx_table=None)
