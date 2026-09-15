"""Canonical EBITDA authority shared by legacy and clean runtime paths."""
from __future__ import annotations


def calculate_ebitda_keur(revenue_keur: float, opex_keur: float) -> float:
    """Return signed EBITDA in kEUR.

    OPEX uses the engine's positive-expense convention. Negative EBITDA is a
    valid operating result and must remain available to tax, CFADS, and debt
    sizing rather than being silently floored.
    """
    return revenue_keur - opex_keur


__all__ = ["calculate_ebitda_keur"]
