"""M6 candidate acquisition underwriting. NOT approved canonical financial authority.

Pure, opt-in, testable candidate math. Never called by project Run / canonical KPIs.
Uses existing reviewed dated XIRR and XNPV primitives.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

from finco_core.sponsor.xirr import robust_xirr
from finco_core.sponsor.xnpv import xnpv

ACTIVATION_ENABLED = False
STATUS = "CANDIDATE_NOT_AUTHORIZED"
TRANSACTION = "FULL_COMMON_SHARE_CASH_NO_REFINANCING"
SHL_POLICY = "SHL_RIGHTS_EXCLUDED"
_EPS = 1e-8


class AcquisitionPolicyError(ValueError):
    pass


def _finite(value, name, *, nonnegative=True):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise AcquisitionPolicyError(name + "_INVALID")
    if nonnegative and value < 0:
        raise AcquisitionPolicyError(name + "_NEGATIVE")
    return float(value)


def _rate(value, name):
    v = _finite(value, name, nonnegative=False)
    if v <= -1 or v > 10:
        raise AcquisitionPolicyError(name + "_OUT_OF_BOUNDS")
    return v


@dataclass(frozen=True)
class AcquisitionTerms:
    closing_date: date
    purchase_price_keur: float
    transaction_costs_keur: float
    buyer_discount_rate: float
    target_buyer_irr: float
    bid_lower_bound_keur: float
    bid_upper_bound_keur: float
    ownership_fraction: float = 1.0
    transaction_type: str = TRANSACTION
    shl_policy: str = SHL_POLICY
    future_funding_policy: str = "SOURCE_PROVEN_EQUITY_CALLS"
    closing_adjustment_keur: float = 0.0
    exit_date: date | None = None
    exit_proceeds_keur: float | None = None

    def check(self):
        if type(self.closing_date) is not date:
            raise AcquisitionPolicyError("CLOSING_DATE_INVALID")
        if self.transaction_type != TRANSACTION or self.shl_policy != SHL_POLICY:
            raise AcquisitionPolicyError("TRANSACTION_STRUCTURE_UNSUPPORTED")
        if self.future_funding_policy != "SOURCE_PROVEN_EQUITY_CALLS":
            raise AcquisitionPolicyError("FUNDING_POLICY_UNSUPPORTED")
        if type(self.ownership_fraction) not in (int, float) or self.ownership_fraction != 1:
            raise AcquisitionPolicyError("OWNERSHIP_NOT_100_PERCENT")
        for name in ("purchase_price_keur", "transaction_costs_keur",
                     "bid_lower_bound_keur", "bid_upper_bound_keur"):
            _finite(getattr(self, name), name)
        _finite(self.closing_adjustment_keur, "closing_adjustment_keur", nonnegative=False)
        _rate(self.buyer_discount_rate, "buyer_discount_rate")
        _rate(self.target_buyer_irr, "target_buyer_irr")
        if not (self.bid_lower_bound_keur < self.bid_upper_bound_keur):
            raise AcquisitionPolicyError("BID_BOUNDS_INVALID")
        if (self.exit_date is None) != (self.exit_proceeds_keur is None):
            raise AcquisitionPolicyError("EXIT_FIELDS_INCOMPLETE")
        if self.exit_date is not None:
            if type(self.exit_date) is not date or self.exit_date <= self.closing_date:
                raise AcquisitionPolicyError("EXIT_DATE_INVALID")
            _finite(self.exit_proceeds_keur, "exit_proceeds_keur")
        if self.purchase_price_keur + self.transaction_costs_keur + self.closing_adjustment_keur < 0:
            raise AcquisitionPolicyError("INITIAL_BUYER_INVESTMENT_NEGATIVE")


def _validated_rows(evidence):
    # Always call evidence.validate() with exact identity before reaching this function.
    if evidence.get("currency") != "EUR" or evidence.get("unit") != "kEUR":
        raise AcquisitionPolicyError("CURRENCY_UNIT_MISMATCH")
    if evidence.get("authority") != "COVENANT_GATED_G2C_AND_C1_PROJECT_RETURN":
        raise AcquisitionPolicyError("SOURCE_AUTHORITY_MISSING")
    return evidence["equity_periods"]


def buyer_cashflows(evidence, terms: AcquisitionTerms, *, price_override=None):
    terms.check()
    rows = _validated_rows(evidence)
    if not rows:
        raise AcquisitionPolicyError("BUYER_SOURCE_PERIODS_MISSING")
    latest = date.fromisoformat(rows[-1]["date"])
    if terms.closing_date >= latest:
        raise AcquisitionPolicyError("CLOSING_NOT_WITHIN_SOURCE_HORIZON")
    if terms.exit_date is not None and terms.exit_date > latest:
        raise AcquisitionPolicyError("EXIT_BEYOND_SOURCE_HORIZON")
    for row in rows:
        if date.fromisoformat(row["date"]) == terms.closing_date and (
            abs(row["net_legal_dividend_keur"]) > _EPS
            or abs(row["legal_equity_contribution_keur"]) > _EPS
        ):
            raise AcquisitionPolicyError("CLOSING_DATE_ENTITLEMENT_ORDER_AMBIGUOUS")
    price = terms.purchase_price_keur if price_override is None else _finite(price_override, "bid_price")
    flows = [(terms.closing_date, -(price + terms.transaction_costs_keur
                                     + terms.closing_adjustment_keur),
              "PURCHASE_FEES_AND_EXPLICIT_CLOSING_ADJUSTMENT")]
    for row in rows:
        day = date.fromisoformat(row["date"])
        if day <= terms.closing_date:
            continue
        if terms.exit_date is not None and day > terms.exit_date:
            continue
        # Ordinary shareholder distributions only. SHL lender rights are NOT acquired.
        receipts = float(row["net_legal_dividend_keur"])
        equity_call = float(row["legal_equity_contribution_keur"])
        flows.append((day, receipts, "NET_LEGAL_DIVIDEND"))
        flows.append((day, -equity_call, "SOURCE_PROVEN_EQUITY_CALL"))
    if terms.exit_date is not None:
        flows.append((terms.exit_date, float(terms.exit_proceeds_keur), "EXPLICIT_EQUITY_EXIT"))
    # Fold equal dates (end-of-period + exit) without silently changing the time axis.
    amounts = {}
    components = {}
    for day, amount, origin in flows:
        amounts[day] = amounts.get(day, 0.0) + amount
        components.setdefault(day, []).append({"component": origin, "amount_keur": amount})
    return tuple({"date": day.isoformat(), "amount_keur": amounts[day],
                  "components": tuple(components[day])} for day in sorted(amounts))


def enterprise_equity_bridge(*, enterprise_value_keur, senior_debt_keur,
                             unrestricted_cash_keur, shl_balance_keur,
                             restricted_cash_keur, debt_like_keur=0,
                             working_capital_adjustment_keur=0,
                             transaction_adjustment_keur=0):
    """Explicit closing-date balance facts or labelled underwriting assumptions only.

    DSRA/restricted cash is displayed, never automatically added to equity value.
    """
    vals = {k: _finite(v, k, nonnegative=k not in (
        "working_capital_adjustment_keur", "transaction_adjustment_keur"))
        for k, v in locals().items()}
    eq = (vals["enterprise_value_keur"] - vals["senior_debt_keur"]
          - vals["shl_balance_keur"] - vals["debt_like_keur"]
          + vals["unrestricted_cash_keur"] + vals["working_capital_adjustment_keur"]
          + vals["transaction_adjustment_keur"])
    if not math.isfinite(eq):
        raise AcquisitionPolicyError("BRIDGE_NON_FINITE")
    return {"status": STATUS, "enterprise_value_keur": vals["enterprise_value_keur"],
            "senior_debt_keur": vals["senior_debt_keur"],
            "unrestricted_cash_keur": vals["unrestricted_cash_keur"],
            "restricted_cash_excluded_keur": vals["restricted_cash_keur"],
            "shl_balance_keur": vals["shl_balance_keur"], "debt_like_keur": vals["debt_like_keur"],
            "working_capital_adjustment_keur": vals["working_capital_adjustment_keur"],
            "transaction_adjustment_keur": vals["transaction_adjustment_keur"],
            "equity_value_keur": eq}


def evaluate(evidence, terms: AcquisitionTerms):
    """Unapproved candidate. Service/UI must not publish metrics while gate is closed."""
    rows = buyer_cashflows(evidence, terms)
    dates = [date.fromisoformat(x["date"]) for x in rows]
    amounts = [x["amount_keur"] for x in rows]
    signs = [1 if v > _EPS else -1 for v in amounts if abs(v) > _EPS]
    transitions = sum(a != b for a, b in zip(signs, signs[1:]))
    ambiguous = transitions > 1
    irr = (robust_xirr(amounts, dates) if transitions == 1
           and any(v < 0 for v in amounts) and any(v > 0 for v in amounts) else None)
    if irr is not None and not math.isfinite(irr):
        irr = None
    # MOIC counts actual receipts and capital calls separately even on the SAME date.
    components = [c["amount_keur"] for row in rows for c in row["components"]]
    invest = -math.fsum(v for v in components if v < 0)
    received = math.fsum(v for v in components if v > 0)
    moic = received / invest if invest > 0 else None
    npv = xnpv(terms.buyer_discount_rate, amounts, dates)
    if not math.isfinite(npv):
        raise AcquisitionPolicyError("BUYER_NPV_NON_FINITE")

    def at_price(price):
        proposal = buyer_cashflows(evidence, terms, price_override=price)
        return xnpv(terms.target_buyer_irr,
                    [x["amount_keur"] for x in proposal],
                    [date.fromisoformat(x["date"]) for x in proposal])

    lo, hi = terms.bid_lower_bound_keur, terms.bid_upper_bound_keur
    f_lo, f_hi = at_price(lo), at_price(hi)
    ceiling, ceiling_status = None, "NO_ROOT_IN_BOUNDS"
    if math.isfinite(f_lo) and math.isfinite(f_hi) and f_lo >= -_EPS and f_hi <= _EPS:
        for _ in range(100):
            mid = (lo + hi) / 2
            if at_price(mid) >= 0:
                lo = mid
            else:
                hi = mid
        ceiling, ceiling_status = (lo + hi) / 2, "ROOT_FOUND"
    return {"status": STATUS, "methodology_version": "M6_ACQUISITION_CANDIDATE_V1",
            "buyer_cashflows": rows, "buyer_irr": irr,
            "buyer_irr_status": "AMBIGUOUS_XIRR_UNSUPPORTED" if ambiguous else ("AVAILABLE" if irr is not None else "NO_VALID_XIRR"),
            "buyer_moic": moic, "buyer_npv_keur": npv,
            "target_irr": terms.target_buyer_irr,
            "bid_ceiling_keur": ceiling, "bid_ceiling_status": ceiling_status,
            "proposed_price_keur": terms.purchase_price_keur}
