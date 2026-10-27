"""FIN-V2-3 orchestration over one completed canonical run. No second Run.

Stored inside financing_evidence so the existing atomic CAS commit binds the
entire policy, audit and metrics to the same immutable Run identifier/hash.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum

from finco_core.inputs.serialization import _ser_valuation_policies
from financial_engine.shl.timing_contract import timing_evidence
from financial_engine.valuation.loan_life import calculate_loan_life_coverage
from financial_engine.valuation.sponsor import calculate_total_sponsor_npv

EVIDENCE_KEY = "financial_core_v1"
VERSION = "FIN_V2_3_EVIDENCE_V1"


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(v) for v in value]
    return value


def build_financial_core_evidence(clean_run, debt_evidence=None):
    g = clean_run.g2c_result
    pi = clean_run.project_inputs
    model = g.financing_result.project_model_result
    policy = pi.valuation
    extended = calculate_loan_life_coverage(model, policy.coverage, debt_evidence,
                                           g.return_summary.terminal.senior)
    sponsor = calculate_total_sponsor_npv(g.waterfall_periods, policy.sponsor,
        g.shl_bullet_unpaid_at_maturity, financial_close=pi.info.financial_close)
    c2 = json_value(g.valuation_summary)
    senior = model.senior_debt
    service = list(zip(senior.period_indices, senior.senior_debt_service_keur)) if senior else []
    active = [(i, v) for i, v in service if v > 1e-4]
    statements = clean_run.financial_statements_result
    pnl = {r.period_end: r for r in statements.income_statement_periods} if statements else {}
    cash = {r.cashflow_date: r for r in statements.pf_cash_waterfall_periods} if statements else {}
    opening = dict(zip(senior.period_indices, senior.senior_debt_opening_keur)) if senior else {}
    base = dict(zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.cfads_keur)) if model.tax_and_cfads else {}
    bank = dict(zip(model.debt_sizing.period_indices, model.debt_sizing.bank_cfads_keur)) if model.debt_sizing else {}
    input_rows = []
    for p in model.periods:
        income, cf = pnl.get(p.period_end), cash.get(p.period_end)
        input_rows.append({
            "period_index": p.period_index, "period_start": p.period_start.isoformat(),
            "period_end": p.period_end.isoformat(), "is_operation": p.is_operation,
            "base_cfads_keur": base.get(p.period_index), "bank_cfads_keur": bank.get(p.period_index),
            "senior_opening_balance_keur": opening.get(p.period_index),
            "statement_ebitda_keur": income.ebitda_keur if income else None,
            "statement_financing_income_keur": income.financing_income_keur if income else None,
            "statement_cash_tax_keur": cf.cash_tax_keur if cf else None,
            "component_authority": "FULL_PRECISION_CANONICAL_FINANCIAL_STATEMENTS" if income and cf else "NOT_AVAILABLE",
        })
    # Observational discontinuity markers, not contractual maturity/payoff evidence.
    regime = (getattr(g.financing_result, "binding_senior_constraint", None),
              max(active, key=lambda x: x[1])[0] if active else None,
              active[-1][0] if active else None)
    def coverage_value(observation):
        return observation.ratio if observation else None
    return {
        "schema_version": VERSION,
        "status": "CALCULATED",
        "authority": "CANONICAL_G2C_AND_C2_FINANCIAL_CORE",
        "valuation_policy_version": policy.policy_version,
        "valuation_policy": _ser_valuation_policies(policy),
        "input_rate_contract": "human_percent_v1" if policy.policy_version else "EXPLICIT_TYPED_RATIO",
        "typed_rate_unit": "ratio",
        "goal_seek_regime": regime,
        "valuation_summary": c2,
        "coverage_input_periods": input_rows,
        "project_cashflows": json_value(g.return_summary.project.cashflows),
        "loan_life_coverage": json_value(extended),
        "project_npv_keur": g.valuation_summary.project_npv.npv_keur,
        "llcr_contractual_maturity": coverage_value(extended.contractual),
        "llcr_actual_repayment": coverage_value(extended.actual_repayment),
        "llcr_at_first_senior_opening": g.valuation_summary.lender_coverage.llcr.ratio,
        "min_rolling_llcr": coverage_value(extended.minimum),
        "rolling_loan_life": policy.coverage.rolling_loan_life.value if policy.coverage else None,
        "plcr": g.valuation_summary.lender_coverage.plcr.ratio,
        "sponsor_npv": json_value(sponsor),
        "sponsor_policy": json_value(policy.sponsor),
        "sponsor_npv_keur": sponsor.npv_keur,
        "shl_timing": timing_evidence(pi.financing, model.periods, g.return_summary.terminal.shareholder_loan),
        "sponsor_metric_policy": {
            "primary": "TOTAL_SPONSOR_XIRR", "secondary": "PURE_EQUITY_XIRR",
            "pure_equity_denominator": "LEGAL_EQUITY_CONTRIBUTIONS",
            "total_sponsor_denominator": "LEGAL_EQUITY_AND_SHL_CASH_CONTRIBUTIONS",
            "funding_date_convention": "FINANCIAL_CLOSE_LUMP_FUNDING",
            "shl_amount_authority": "ENGINE_DERIVED_SOURCES_AND_USES",
            "entered_shl_amount": "INDICATIVE_NON_AUTHORITATIVE",
            "standalone_g2b": "NON_PRODUCTION_RESEARCH_MODEL",
        },
        "tax_policy_classification": "GENERIC_MVP_POLICY",
        "contractual_assessment": "CONTRACTUAL_ASSESSMENT_NOT_AVAILABLE",
        "lender_acceptance": "NOT_VERIFIED",
    }


def attach_financial_core(payload, clean_run):
    finance = payload["financing_evidence"]
    # The FIN-V2-2 runner hunk should precede this call. On the isolated branch
    # the dependency is intentionally absent; extended debt metrics fail closed.
    evidence = build_financial_core_evidence(clean_run, finance.get("senior_debt_evidence"))
    finance[EVIDENCE_KEY] = evidence
    payload["valuation_summary"] = evidence["valuation_summary"]
    for key in ("llcr_contractual_maturity", "llcr_actual_repayment", "llcr_at_first_senior_opening",
                "min_rolling_llcr", "plcr", "sponsor_npv_keur"):
        payload["kpis"][key] = evidence[key]


def from_runtime_summary(runtime_summary, *, snapshot_id=None, composite_hash=None):
    finance = runtime_summary.get("financing_evidence") or {}
    evidence = finance.get(EVIDENCE_KEY)
    if not isinstance(evidence, dict) or evidence.get("schema_version") != VERSION:
        return {"status": "NOT_PERSISTED", "reason": "Historical Run has no FIN-V2-3 evidence"}
    binding = finance.get("run_binding")
    if not isinstance(binding, dict) or not binding.get("snapshot_id"):
        return {"status": "NOT_PERSISTED", "reason": "No committed Run binding"}
    if ((snapshot_id is not None and binding.get("snapshot_id") != snapshot_id)
            or (composite_hash is not None and binding.get("composite_hash") != composite_hash)):
        return {"status": "RUN_BINDING_MISMATCH", "reason": "Evidence belongs to another Run/input identity"}
    return {**evidence, "status": "PERSISTED"}
