"""Retained earnings helpers for offline statement assembly."""

from __future__ import annotations


def compute_retained_earnings_schedule(
    net_income_schedule_keur: tuple[float, ...],
    dividends_paid_schedule_keur: tuple[float, ...],
    opening_retained_earnings_keur: float = 0.0,
) -> tuple[float, ...]:
    """Return retained earnings balances using movement = net income - dividends."""

    if len(net_income_schedule_keur) != len(dividends_paid_schedule_keur):
        raise ValueError("Net income and dividends schedules must have the same length.")

    retained_earnings = opening_retained_earnings_keur
    balances: list[float] = []
    for net_income, dividends_paid in zip(net_income_schedule_keur, dividends_paid_schedule_keur):
        retained_earnings += net_income - dividends_paid
        balances.append(retained_earnings)
    return tuple(balances)
