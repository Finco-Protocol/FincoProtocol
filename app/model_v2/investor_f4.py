"""F4/P1 common-equity agreement and immutable downstream Run evidence.

No project funding, tax, debt or sponsor waterfall is calculated here. Residual
allocation and dated XIRR delegate to the existing reviewed core utilities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math

from app.model_v2.investor_f4_candidate.contracts import (
    CASH_TOLERANCE_KEUR, OWNERSHIP_TOLERANCE, Contribution, DistributionEvidence,
    Entitlements, InvestmentClass, Investor, InvestorAgreement, Priority,
)
from app.model_v2.investor_f4_candidate.adapter import (
    to_existing_inputs, validate_candidate_result,
)
from finco_core.sponsor.waterfall_runner import run_waterfall
from finco_core.sponsor.xirr import robust_xirr
from financial_engine.sponsor_returns.contracts import ReturnMetricStatus

FIELD_ID = "investor.agreement.common_equity"
SNAPSHOT_KEY = "investor_agreement_json"
EVIDENCE_KEY = "investor_waterfall_v1"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError("F4 agreement has missing or unsupported fields")


def _identity(value):
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ValueError("F4 requires explicit, nonblank identities")
    return value


def _amount(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("F4 cash must be finite, nonnegative kEUR")
    return float(value)


@dataclass(frozen=True)
class AgreementTerms:
    """Persisted definition using P0 investor/contribution contracts, not a registry.

    Owner/project/scenario authority comes from the authorized scalar/scenario
    store, and is captured explicitly in the atomic Run evidence binding.
    """
    agreement_id: str
    version: int
    investors: tuple[Investor, ...]
    contributions: tuple[Contribution, ...]

    def document(self):
        return {
            "schema_version": 1, "agreement_id": self.agreement_id,
            "version": self.version, "currency": "EUR", "unit": "kEUR",
            "policy": "RESIDUAL_ONLY",
            "investors": [asdict(i) for i in self.investors],
            "contributions": [dict(investor_id=c.investor_id,
                cash_date=c.cash_date.isoformat(), amount_keur=c.amount_keur)
                for c in self.contributions],
        }

    def to_json(self):
        return _json(self.document())

    def digest(self):
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def parse_terms(raw) -> AgreementTerms | None:
    if raw in (None, ""):
        return None

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("F4 duplicate JSON keys are not permitted")
            result[key] = value
        return result

    obj = json.loads(raw, object_pairs_hook=unique) if isinstance(raw, str) else raw
    _keys(obj, ("schema_version", "agreement_id", "version", "currency", "unit",
                "policy", "investors", "contributions"))
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise ValueError("Unsupported F4 agreement schema")
    if type(obj["version"]) is not int or obj["version"] < 1:
        raise ValueError("F4 agreement version must be a positive integer")
    if (obj["policy"], obj["currency"], obj["unit"]) != ("RESIDUAL_ONLY", "EUR", "kEUR"):
        raise ValueError("Only EUR/kEUR residual common equity is authorized; ROC/NAV/carry/SHL are unsupported")
    if not isinstance(obj["investors"], list) or not 1 <= len(obj["investors"]) <= 100:
        raise ValueError("F4 requires one to 100 explicitly identified investors")
    if not isinstance(obj["contributions"], list) or len(obj["contributions"]) > 2000:
        raise ValueError("Invalid F4 contribution collection")
    investors = []
    for row in obj["investors"]:
        _keys(row, ("investor_id", "investment_class", "ownership_fraction", "commitment_keur"))
        if row["investment_class"] != "COMMON_EQUITY":
            raise ValueError("Only common equity is supported; no SHL lender allocation")
        investors.append(Investor(row["investor_id"], InvestmentClass.COMMON_EQUITY,
                                  row["ownership_fraction"], row["commitment_keur"]))
    by_id = {i.investor_id: i for i in investors}
    if len(by_id) != len(investors):
        raise ValueError("Duplicate F4 investor identity")
    if abs(math.fsum(i.ownership_fraction for i in investors) - 1) > OWNERSHIP_TOLERANCE:
        raise ValueError("Legal equity ownership must sum to one")
    contributions = []
    for row in obj["contributions"]:
        _keys(row, ("investor_id", "cash_date", "amount_keur"))
        if not isinstance(row["cash_date"], str):
            raise ValueError("Contribution date must be explicit ISO date")
        c = Contribution(row["investor_id"], date.fromisoformat(row["cash_date"]), row["amount_keur"])
        if c.investor_id not in by_id:
            raise ValueError("Contribution investor is not in agreement")
        contributions.append(c)
    for i in investors:
        if math.fsum(c.amount_keur for c in contributions if c.investor_id == i.investor_id) > i.commitment_keur + CASH_TOLERANCE_KEUR:
            raise ValueError("Paid-in contributions exceed investor commitment")
    return AgreementTerms(_identity(obj["agreement_id"]), obj["version"],
        tuple(sorted(investors, key=lambda i: i.investor_id)),
        tuple(sorted(contributions, key=lambda c: (c.cash_date, c.investor_id, c.amount_keur))))


def extract_equity_receipts(g2c) -> dict:
    """Pass through actual G2C dated net dividend and legal contribution fields.

    This is requested only for an opted-in agreement. It never reconstructs net
    dividends from gross distributions or touches aggregate returns.
    """
    periods = []
    for p in g2c.waterfall_periods:
        if type(p.cashflow_date) is not date:
            raise ValueError("F4 canonical cash event has no exact date")
        contributions = math.fsum(_amount(getattr(p, key)) for key in (
            "share_capital_contribution_keur", "share_premium_contribution_keur",
            "other_committed_equity_contribution_keur", "additional_equity_contribution_keur"))
        gross = _amount(p.gross_dividend_paid_keur)
        net = _amount(p.net_dividend_received_keur)
        wht = _amount(p.dividend_wht_keur)
        if abs(gross - wht - net) > CASH_TOLERANCE_KEUR:
            raise ValueError("F4 canonical gross/WHT/net dividend reconciliation failed")
        periods.append(dict(date=p.cashflow_date.isoformat(), paid_in_keur=contributions,
                            net_equity_receipt_keur=net, gross_dividend_keur=gross, dividend_wht_keur=wht))
    if (abs(math.fsum(p["paid_in_keur"] for p in periods) - g2c.total_legal_equity_contributed_keur) > CASH_TOLERANCE_KEUR
            or abs(math.fsum(p["net_equity_receipt_keur"] for p in periods) - g2c.total_net_dividend_received_keur) > CASH_TOLERANCE_KEUR):
        raise ValueError("F4 canonical equity evidence totals mismatch")
    return {"schema_version": 1, "source": "CovenantGatedWaterfallResult.net_dividend_received_keur",
            "periods": periods, "return_status": g2c.return_summary.legal_equity.xirr_status.value}


def allocate_run(terms: AgreementTerms, receipt: dict, *, binding: dict) -> dict:
    """Allocate only canonical receipts, before the existing atomic Run CAS.

    The actual investor contributions must reconcile to canonical funding by
    exact date. A commitment is never used to manufacture a paid-in event.
    """
    _keys(binding, ("owner_id", "project_id", "scenario_id", "snapshot_id", "composite_hash"))
    for key in ("owner_id", "project_id", "snapshot_id", "composite_hash"):
        _identity(binding[key])
    if binding["scenario_id"] is not None:
        _identity(binding["scenario_id"])
    if receipt.get("schema_version") != 1 or receipt.get("source") != "CovenantGatedWaterfallResult.net_dividend_received_keur":
        raise ValueError("F4 requires canonical net-equity receipt evidence")
    source_status = ReturnMetricStatus(receipt["return_status"])
    upstream_blocked = source_status in (
        ReturnMetricStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY,
        ReturnMetricStatus.UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED,
    )
    rows = receipt["periods"]
    dates = tuple(date.fromisoformat(p["date"]) for p in rows)
    cash = tuple(_amount(p["net_equity_receipt_keur"]) for p in rows)
    agreement = InvestorAgreement(terms.agreement_id, terms.investors, terms.contributions,
        Entitlements((Priority.RESIDUAL,)), DistributionEvidence(binding["snapshot_id"], dates, cash))
    for p, d in zip(rows, dates):
        if abs(math.fsum(c.amount_keur for c in terms.contributions if c.cash_date == d) - _amount(p["paid_in_keur"])) > CASH_TOLERANCE_KEUR:
            raise ValueError(f"F4 paid-in capital does not reconcile to canonical funding on {d}; commitment is not paid-in cash")
        if abs(_amount(p["gross_dividend_keur"]) - _amount(p["dividend_wht_keur"]) - p["net_equity_receipt_keur"]) > CASH_TOLERANCE_KEUR:
            raise ValueError("F4 dividend/WHT receipt mismatch")
    result = run_waterfall(to_existing_inputs(agreement))
    validate_candidate_result(agreement, result)
    investor_rows = []
    for i in terms.investors:
        events = []
        paid = 0.0
        distributed = 0.0
        for d, p in zip(dates, result.period_results):
            contribution = math.fsum(c.amount_keur for c in terms.contributions
                                     if c.investor_id == i.investor_id and c.cash_date == d)
            distribution = p.tier_entries[0].allocation_for(i.investor_id)
            paid += contribution
            distributed += distribution
            events.append(dict(date=d.isoformat(), contribution_keur=contribution,
                returned_capital_keur=0.0, residual_distribution_keur=distribution,
                net_cashflow_keur=distribution - contribution, unreturned_paid_in_keur=paid))
        flows = [p["net_cashflow_keur"] for p in events]
        status = receipt["return_status"]
        rate = robust_xirr(flows, list(dates)) if status == "OK" else None
        if status == "OK":
            status = ("NO_NEGATIVE_CASHFLOW" if not any(v < 0 for v in flows)
                else "NO_POSITIVE_CASHFLOW" if not any(v > 0 for v in flows)
                else "NON_CONVERGENT" if rate is None or not math.isfinite(rate) else "OK")
        # No NAV/terminal valuation is supported: MOIC is realized cash only.
        multiple = distributed / paid if paid > 0 and not upstream_blocked else None
        investor_rows.append(dict(investor_id=i.investor_id, ownership_fraction=i.ownership_fraction,
            commitment_keur=i.commitment_keur, total_paid_in_keur=paid,
            uncalled_capital_keur=i.commitment_keur - paid, returned_capital_keur=0.0,
            residual_distributions_keur=distributed, cumulative_distributions_keur=distributed,
            unreturned_paid_in_keur=paid, dpi=multiple, realized_moic=multiple,
            xirr=rate, xirr_status=status, cash_events=events))
    output = dict(schema_version=1, binding=dict(binding), agreement=terms.document(),
        agreement_digest=terms.digest(), source=receipt["source"], currency="EUR", unit="kEUR",
        canonical_receipts=rows, investors=investor_rows, retained_cash_keur=0.0,
        roc_status="UNSUPPORTED_LEGAL_POLICY_NOT_APPROVED", nav_status="UNSUPPORTED")
    output["evidence_digest"] = hashlib.sha256(_json(output).encode("utf-8")).hexdigest()
    return output


def validate_evidence(evidence, *, owner_id, project_id, snapshot_id, composite_hash, scenario_id):
    """Read-side integrity/binding checks; no allocation or XIRR execution on GET/export."""
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("Investor evidence is unavailable for this Run")
    expected = dict(owner_id=owner_id, project_id=project_id, snapshot_id=snapshot_id,
                    composite_hash=composite_hash, scenario_id=scenario_id)
    if evidence.get("binding") != expected:
        raise ValueError("Investor Run/project/scenario identity mismatch")
    unsigned = {k: v for k, v in evidence.items() if k != "evidence_digest"}
    if hashlib.sha256(_json(unsigned).encode("utf-8")).hexdigest() != evidence.get("evidence_digest"):
        raise ValueError("Investor evidence digest mismatch")
    terms = parse_terms(evidence["agreement"])
    if terms.digest() != evidence.get("agreement_digest"):
        raise ValueError("Investor agreement digest mismatch")
    return evidence
