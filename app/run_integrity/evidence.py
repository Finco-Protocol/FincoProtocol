"""Run Integrity evidence: full-precision facts recorded when a run is committed.

This module only RECORDS what the run used and produced (inputs such as declared rates,
day fractions and DSCR targets, and outputs such as balances, flows and reported ratios).
It performs no integrity judgement; the checks in ``checks.py`` recompute every identity
independently from this evidence, so the Last Run can be checked later without re-running
the model.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.run_integrity.contracts import EVIDENCE_SCHEMA


def _num(value: Any) -> float | None:
    """Full-precision JSON-safe number; non-finite or non-numeric becomes None (never 0)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def evidence_digest(evidence: dict[str, Any]) -> str:
    """sha256 over the evidence body (everything except the digest field itself)."""
    body = {k: v for k, v in evidence.items() if k != "digest"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _sources_uses(financing) -> dict[str, Any]:
    from dataclasses import asdict

    from financial_engine.financing.generic_product_policy import build_sources_and_uses

    su = {k: _num(v) for k, v in asdict(build_sources_and_uses(financing)).items()}
    funding = financing.construction_funding
    return {
        "summary": su,
        "construction_periods": [
            {
                "period": int(p.period_index),
                "uses": _num(p.project_cash_uses_keur),
                "sources": _num(p.total_sources_keur),
                "difference": _num(p.sources_uses_difference_keur),
            }
            for p in funding.periods
        ],
        "audit": {
            "uses": _num(funding.total_audit_uses_keur),
            "sources": _num(funding.total_audit_sources_keur),
            "residual": _num(funding.total_audit_residual_keur),
        },
    }


def _day_fraction(start, end, convention_name: str) -> float | None:
    days = (end - start).days
    if convention_name == "ACT_360":
        return days / 360.0
    if convention_name == "ACT_365":
        return days / 365.0
    return None


def _senior_debt(clean_run, model) -> dict[str, Any]:
    from finco_core.inputs.senior_rate_schedule import SeniorRateMode

    fin = clean_run.project_inputs.financing
    senior = model.senior_debt
    rate_cfg = fin.senior_debt_interest_config
    schedule = rate_cfg.rate_schedule
    convention = getattr(rate_cfg.day_count, "name", str(rate_cfg.day_count))
    explicit = schedule.explicit_all_in_rates if schedule.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE else ()
    sculpting = fin.senior_sculpting_config
    dates = {p.period_index: (p.period_start, p.period_end) for p in model.periods}
    bank_cfads = dict(zip(model.debt_sizing.period_indices, model.debt_sizing.bank_cfads_keur))
    base_cfads = dict(zip(model.post_senior_cash.period_indices, model.post_senior_cash.base_cfads_keur))
    from financial_engine.financing.multisenior import MultiSeniorFinancingResult
    financing = clean_run.g2c_result.financing_result
    facility_rates = ({r.period_index: r.annual_rate for r in financing.aggregate_period_rates}
                      if isinstance(financing, MultiSeniorFinancingResult) else None)

    periods = []
    for position, index in enumerate(senior.period_indices):
        start, end = dates[index]
        if facility_rates is not None:
            rate = facility_rates.get(index)
        elif explicit:
            rate = explicit[position] if position < len(explicit) else None
        elif schedule.mode == SeniorRateMode.FLAT_ALL_IN:
            rate = schedule.flat_all_in_rate
        else:
            rate = None
        target = (sculpting.target_dscr_schedule[position]
                  if sculpting.target_dscr_schedule and position < len(sculpting.target_dscr_schedule)
                  else fin.target_dscr)
        availability = (sculpting.debt_service_availability_schedule[position]
                        if sculpting.debt_service_availability_schedule
                        and position < len(sculpting.debt_service_availability_schedule) else 1.0)
        periods.append({
            "period_index": int(index),
            "opening": _num(senior.senior_debt_opening_keur[position]),
            "interest": _num(senior.senior_interest_keur[position]),
            "principal": _num(senior.senior_principal_keur[position]),
            "debt_service": _num(senior.senior_debt_service_keur[position]),
            "closing": _num(senior.senior_debt_closing_keur[position]),
            "annual_rate": _num(rate),
            "day_fraction": _num(_day_fraction(start, end, convention)),
            "target_dscr": _num(target),
            "availability": _num(availability),
            "bank_cfads": _num(bank_cfads.get(index)),
            "base_cfads": _num(base_cfads.get(index)),
            "reported_dscr": _num(senior.base_dscr[position]),
        })
    diagnostics = senior.diagnostics
    return {
        "diagnostics": {
            "termination_reason": diagnostics.get("termination_reason"),
            "is_authoritative": bool(diagnostics.get("is_authoritative")),
            "converged": bool(diagnostics.get("converged")),
            "binding_constraint": diagnostics.get("binding_constraint"),
            "final_debt_size_keur": _num(diagnostics.get("final_debt_size_keur")),
        },
        "day_count": convention,
        "permit_terminal_balloon": True,  # the generic product contract permits a terminal balloon
        "periods": periods,
    }


def _cash(model) -> list[dict[str, Any]]:
    post = model.post_senior_cash
    return [
        {"period_index": int(i), "cash_after_senior_before_reserves": _num(v)}
        for i, v in zip(post.period_indices, post.cash_after_senior_before_reserves_keur)
    ]


def _balance_sheet(clean_run) -> list[dict[str, Any]]:
    statements = clean_run.financial_statements_result
    rows = []
    for p in statements.balance_sheet_periods:
        rows.append({
            "period_index": int(p.period_index),
            "gross_fixed_assets": _num(p.gross_fixed_assets_keur),
            "accumulated_depreciation": _num(p.accumulated_book_depreciation_keur),
            "unrestricted_cash": _num(p.unrestricted_cash_keur),
            "dsra_balance": _num(p.dsra_balance_keur),
            "distribution_account": _num(p.distribution_account_balance_keur),
            "senior_debt": _num(p.senior_debt_balance_keur),
            "shl": _num(p.shl_balance_keur),
            "share_capital": _num(p.share_capital_keur),
            "share_premium": _num(p.share_premium_keur),
            "legal_reserve": _num(p.legal_reserve_keur),
            "retained_earnings": _num(p.retained_earnings_keur),
            "net_cit_payable": _num(p.net_cit_payable_keur),
            "reported_balance_check": _num(p.balance_check_keur),
        })
        from financial_engine.financing.multisenior import MultiSeniorFinancingResult
        if isinstance(clean_run.g2c_result.financing_result, MultiSeniorFinancingResult):
            rows[-1]["additional_equity"] = _num(p.additional_equity_keur)
    return rows


def _sponsor(g2c) -> dict[str, Any]:
    periods = []
    for wp in g2c.waterfall_periods:
        periods.append({
            "period": int(wp.period_index),
            "date": wp.cashflow_date.isoformat() if wp.cashflow_date else None,
            "is_construction": bool(wp.is_construction),
            "share_capital": _num(wp.share_capital_contribution_keur),
            "share_premium": _num(wp.share_premium_contribution_keur),
            "other_committed_equity": _num(wp.other_committed_equity_contribution_keur),
            "additional_equity": _num(wp.additional_equity_contribution_keur),
            "shl_contribution": _num(wp.shl_cash_contribution_keur),
            "shl_cash_interest": _num(wp.shl_cash_interest_receipt_keur),
            "shl_principal": _num(wp.actual_shl_principal_paid_keur),
            "legal_equity_distribution": _num(wp.legal_equity_distribution_keur),
            "pure_equity_net": _num(wp.pure_equity_net_cashflow_keur),
            "total_sponsor_net": _num(wp.total_sponsor_net_cashflow_keur),
        })

    def status(value):
        return getattr(value, "value", None) or (str(value) if value is not None else None)

    return {
        "periods": periods,
        "reported": {
            "pure_equity_xirr": _num(g2c.pure_equity_xirr),
            "pure_equity_xirr_status": status(g2c.pure_equity_xirr_status),
            "total_sponsor_xirr": _num(g2c.total_sponsor_xirr),
            "total_sponsor_xirr_status": status(g2c.total_sponsor_xirr_status),
        },
    }


def build_run_integrity_evidence(clean_run) -> dict[str, Any]:
    """Record the integrity evidence of one clean production run (commit time only)."""
    g2c = clean_run.g2c_result
    financing = g2c.financing_result
    model = financing.project_model_result
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "sources_uses": _sources_uses(financing),
        "senior_debt": _senior_debt(clean_run, model),
        "cash": _cash(model),
        "balance_sheet": _balance_sheet(clean_run),
        "sponsor": _sponsor(g2c),
    }
    from financial_engine.financing.multisenior import MultiSeniorFinancingResult
    if isinstance(financing, MultiSeniorFinancingResult):
        evidence["financing_authority"] = "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
    evidence["digest"] = evidence_digest(evidence)
    return evidence
