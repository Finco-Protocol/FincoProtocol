"""Independent bounded Decimal identity checks, NEVER production price/debt/tax models.

Caller supplies every quantity, rate, period, convention and tolerance. Output is a
residual and an independently justified tolerance verdict, not fitted inputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Sequence

from .reconcile import ReconciliationInputError, _decimal, _str


@dataclass(frozen=True)
class OracleResult:
    name: str
    observed: str
    expected: str
    residual: str
    tolerance: str
    status: str


def check(name: str, observed, expected, *, tolerance) -> OracleResult:
    o = _decimal(observed, name + ".observed")
    e = _decimal(expected, name + ".expected")
    t = _decimal(tolerance, name + ".tolerance", nonnegative=True)
    residue = o - e
    return OracleResult(name, _str(o), _str(e), _str(residue), _str(t),
                        "PASS" if abs(residue) <= t else "FAIL")


def revenue(quantity_mwh, price_per_mwh, revenue_keur, *, tolerance_keur) -> OracleResult:
    q = _decimal(quantity_mwh, "quantity_mwh", nonnegative=True)
    p = _decimal(price_per_mwh, "price_per_mwh", nonnegative=True)
    return check("revenue_keur", revenue_keur, q * p / Decimal(1000), tolerance=tolerance_keur)


def allocation(shares: Sequence, *, expected=1, tolerance) -> OracleResult:
    if not shares:
        raise ReconciliationInputError("allocation: shares required")
    decimals = [_decimal(x, "volume_share", nonnegative=True) for x in shares]
    if any(x > 1 for x in decimals):
        raise ReconciliationInputError("allocation: a physical share exceeds one")
    return check("allocation_conservation", sum(decimals), expected, tolerance=tolerance)


def debt_rollforward(opening, drawdowns, principal_repaid, closing, *, tolerance) -> OracleResult:
    return check("debt_rollforward", closing,
                 _decimal(opening, "opening") + _decimal(drawdowns, "drawdowns") -
                 _decimal(principal_repaid, "principal_repaid"), tolerance=tolerance)


def interest(opening_principal, annual_rate, days, basis_days, reported_interest, *, tolerance) -> OracleResult:
    """Simple annual rate accrual on supplied opening principal; no compounding inference."""
    days_d = _decimal(days, "days", nonnegative=True)
    basis_d = _decimal(basis_days, "basis_days", nonnegative=True)
    if basis_d == 0:
        raise ReconciliationInputError("basis_days: positive basis required")
    return check("interest_accrual", reported_interest,
                 _decimal(opening_principal, "opening_principal") *
                 _decimal(annual_rate, "annual_rate", nonnegative=True) *
                 days_d / basis_d, tolerance=tolerance)


def sources_uses(sources, uses, *, tolerance) -> OracleResult:
    return check("sources_minus_uses", _decimal(sources, "sources") - _decimal(uses, "uses"),
                 0, tolerance=tolerance)


def cash_conservation(opening, inflows, outflows, closing, *, tolerance) -> OracleResult:
    return check("cash_conservation", closing, _decimal(opening, "opening") +
                 _decimal(inflows, "inflows") - _decimal(outflows, "outflows"), tolerance=tolerance)


def balance_sheet(assets, liabilities, equity, *, tolerance) -> OracleResult:
    return check("balance_sheet", _decimal(assets, "assets"),
                 _decimal(liabilities, "liabilities") + _decimal(equity, "equity"), tolerance=tolerance)


def discounted_cashflows(cashflows, period_discount_factors, npv, *, tolerance) -> OracleResult:
    """Factors supplied and independently approved; no calendar/daycount conventions inferred."""
    if not cashflows or len(cashflows) != len(period_discount_factors):
        raise ReconciliationInputError("discounted_cashflows: aligned nonempty vectors required")
    expected = sum(
        (_decimal(flow, "cashflow") * _decimal(factor, "discount_factor", nonnegative=True)
         for flow, factor in zip(cashflows, period_discount_factors)),
        Decimal(0),
    )
    return check("discounted_cashflows", npv, expected, tolerance=tolerance)
