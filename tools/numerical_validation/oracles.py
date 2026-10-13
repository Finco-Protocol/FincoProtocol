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


# ── F3.9 additions: further bounded identities, still independent of every production module ──────────

def debt_service(interest, principal, reported_debt_service, *, tolerance) -> OracleResult:
    return check("debt_service", reported_debt_service,
                 _decimal(interest, "interest") + _decimal(principal, "principal"), tolerance=tolerance)


def ebitda(revenue, opex, reported_ebitda, *, tolerance) -> OracleResult:
    return check("ebitda", reported_ebitda, _decimal(revenue, "revenue") - _decimal(opex, "opex"), tolerance=tolerance)


def ebit(revenue, opex, depreciation, reported_ebit, *, tolerance) -> OracleResult:
    return check("ebit", reported_ebit, _decimal(revenue, "revenue") - _decimal(opex, "opex") -
                 _decimal(depreciation, "depreciation"), tolerance=tolerance)


def dscr(cfads, service, reported_dscr, *, tolerance) -> OracleResult:
    service_d = _decimal(service, "service")
    if service_d <= 0:
        raise ReconciliationInputError("dscr: positive debt service required")
    return check("dscr", reported_dscr, _decimal(cfads, "cfads") / service_d, tolerance=tolerance)


def cash_after_service(cfads, service, reported_cash, *, tolerance) -> OracleResult:
    return check("cash_after_senior_service", reported_cash,
                 _decimal(cfads, "cfads") - _decimal(service, "service"), tolerance=tolerance)


def sum_of_periods(values: Sequence, reported_total, *, tolerance, name: str = "total_equals_period_sum") -> OracleResult:
    """Independent total versus the sum of its own periods; a missing period is an input error, never zero."""
    if not values:
        raise ReconciliationInputError(name + ": at least one period required")
    return check(name, reported_total, sum((_decimal(v, name + ".period") for v in values), Decimal(0)),
                 tolerance=tolerance)


def cfd_settlement(quantity_mwh, strike_eur_mwh, reference_eur_mwh, settlement_keur, *, tolerance) -> OracleResult:
    """Two-way contract for difference, SIGNED: positive when the reference price is below the strike."""
    q = _decimal(quantity_mwh, "quantity_mwh", nonnegative=True)
    return check("cfd_settlement_keur", settlement_keur,
                 q * (_decimal(strike_eur_mwh, "strike") - _decimal(reference_eur_mwh, "reference")) / Decimal(1000),
                 tolerance=tolerance)


def energy_revenue(streams: Sequence[tuple], reported_keur, *, tolerance) -> OracleResult:
    """Sum of quantity x price / 1,000 over supplied (quantity_mwh, price_eur_mwh) pairs."""
    total = Decimal(0)
    for i, (quantity, price) in enumerate(streams):
        total += _decimal(quantity, f"stream[{i}].quantity", nonnegative=True) * \
            _decimal(price, f"stream[{i}].price", nonnegative=True) / Decimal(1000)
    return check("energy_revenue_keur", reported_keur, total, tolerance=tolerance)


def xirr(cashflows: Sequence, dates: Sequence, *, precision: int = 60) -> Decimal | None:
    """Independent Decimal XIRR: ACT/365 from the first date, bisection to ~1e-30.  None when no root exists.

    Deliberately NOT ``finco_core.sponsor.xirr`` (Newton in binary floating point).  The day-count basis is the
    Excel-compatible one the product documents; it is an explicit convention, not a fitted parameter.
    """
    from datetime import date as _date
    from decimal import localcontext

    if len(cashflows) != len(dates) or len(cashflows) < 2:
        return None
    flows = [_decimal(v, "cashflow") for v in cashflows]
    if not (any(v > 0 for v in flows) and any(v < 0 for v in flows)):
        return None
    parsed = [d if isinstance(d, _date) else _date.fromisoformat(str(d)) for d in dates]
    if any(b < a for a, b in zip(parsed, parsed[1:])):
        raise ReconciliationInputError("xirr: dates must be chronological")
    with localcontext() as ctx:
        ctx.prec = precision
        years = [Decimal((d - parsed[0]).days) / Decimal(365) for d in parsed]

        def npv(rate: Decimal) -> Decimal:
            base = Decimal(1) + rate
            return sum((f / (base ** t) for f, t in zip(flows, years)), Decimal(0))

        low, high = Decimal("-0.999999"), Decimal(10)
        f_low, f_high = npv(low), npv(high)
        if f_low == 0:
            return low
        if f_high == 0:
            return high
        if (f_low > 0) == (f_high > 0):
            return None
        for _ in range(220):
            mid = (low + high) / 2
            f_mid = npv(mid)
            if f_mid == 0:
                return mid
            if (f_mid > 0) == (f_low > 0):
                low, f_low = mid, f_mid
            else:
                high = mid
        return (low + high) / 2
