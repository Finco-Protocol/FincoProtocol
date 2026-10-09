"""F1 read-only Sources & Uses projection over persisted canonical evidence.

There is deliberately no calculator, no funding plug and no engine import here.
V1 data lives in the exact committed RuntimeResult.runtime_summary and its
append-only Run History copy. Legacy records remain unavailable, never backfilled.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any

from app.workbook.runtime_projection import thaw_runtime_payload

NA = "Unavailable"
FULL_SU_AUTHORITY = (
    "Legacy Run — financing evidence unavailable. A new canonical Run must "
    "persist the versioned engine SourcesAndUses result. Never backfill history."
)
BALANCE_WRITE_GAP = (
    "Balance S&U is disabled: no approved atomic financing-stack update "
    "contract covers equity/SHL/source selection, owner authorization, protected "
    "references, workbook CAS, scenario identity and new-Run reconciliation."
)


class FinancingEvidenceInvalid(ValueError):
    """Malformed persisted evidence cannot be silently repaired from inputs."""


@dataclass(frozen=True)
class Amount:
    label: str
    value: float | str | None
    display: str
    authority: str
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def amount(label: str, raw: Any, authority: str, reason: str = "") -> Amount:
    value = _number(raw)
    if value is None:
        return Amount(label, None, NA, authority, reason or "Not persisted in this evidence.")
    return Amount(label, value, f"{value:,.2f}", authority)


def ratio(label: str, raw: Any, authority: str, *, percent: bool = False, reason: str = "") -> Amount:
    """Format an authoritative fraction or coverage multiple; no economic arithmetic."""
    item = amount(label, raw, authority, reason)
    if item.value is None:
        return item
    display = f"{item.value * 100:.2f}%" if percent else f"{item.value:.2f}x"
    return Amount(label, item.value, display, authority)


def missing(label: str, path: str, *, reason: str = FULL_SU_AUTHORITY) -> Amount:
    return amount(label, None, path, reason)


def _mapping(value: Any, path: str, *, optional: bool = True) -> Mapping:
    if value is None and optional:
        return {}
    value = thaw_runtime_payload(value)
    if not isinstance(value, Mapping):
        raise FinancingEvidenceInvalid(f"MALFORMED_PERSISTED_FINANCING_EVIDENCE: {path} must be an object")
    return value


def _summary(payload: Any, path: str) -> Mapping:
    container = _mapping(payload, path)
    return _mapping(container.get("summary"), path + ".summary")


def _raw_attr(obj: Any, name: str):
    return getattr(obj, name, None) if obj is not None else None



FINANCE_SCHEMA = "FINANCING_F1_V1"
FINANCE_AUTHORITY = "CANONICAL_PROJECT_FINANCING_RESULT"
SU_USES = (
    "base_project_capex_keur", "capitalized_idc_keur", "commitment_fee_keur",
    "structuring_fee_keur", "other_financing_costs_keur", "initial_dsra_funding_keur",
    "other_uses_keur", "development_cost_reimbursement_keur", "developer_fee_keur",
)
SU_SOURCES = (
    "senior_debt_keur", "junior_or_other_keur",
    "share_capital_and_other_equity_keur", "shareholder_loan_cash_keur",
)
SU_REQUIRED = SU_USES + SU_SOURCES + (
    "total_sources_keur", "total_uses_keur", "difference_keur",
)
FINANCE_TOLERANCE_KEUR = 1e-6  # existing G2A allocation audit, not an alternative model


def _required_number(container: Mapping, key: str, source: str) -> float:
    if key not in container or _number(container[key]) is None:
        raise FinancingEvidenceInvalid(
            f"MALFORMED_FINANCING_EVIDENCE: {source}.{key} missing / not finite")
    return float(container[key])


def _optional_number(container: Mapping, key: str, source: str):
    if key in container and container[key] is not None and _number(container[key]) is None:
        raise FinancingEvidenceInvalid(
            f"MALFORMED_FINANCING_EVIDENCE: {source}.{key} is not finite")
    return container.get(key)


def _close(a: float, b: float) -> bool:
    # Verification only: never substitutes a computed result for canonical numbers.
    return math.isclose(a, b, rel_tol=0.0, abs_tol=FINANCE_TOLERANCE_KEUR)


def _read_finance_evidence(runtime: Mapping, *, snapshot_id: str | None,
                           composite_hash: str | None, scenario_id: str | None):
    if "financing_evidence" not in runtime:
        return None
    evidence = _mapping(runtime["financing_evidence"], "runtime_summary.financing_evidence", optional=False)
    if evidence.get("schema_version") != FINANCE_SCHEMA or evidence.get("authority") != FINANCE_AUTHORITY:
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_SCHEMA_OR_AUTHORITY_UNKNOWN")
    if evidence.get("units") != "kEUR":
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_UNITS_INVALID")
    binding = _mapping(evidence.get("run_binding"), "financing_evidence.run_binding", optional=False)
    if (not isinstance(binding.get("snapshot_id"), str) or not binding["snapshot_id"]
            or not isinstance(binding.get("composite_hash"), str) or not binding["composite_hash"]
            or ("scenario_id" not in binding)
            or (binding["scenario_id"] is not None and not isinstance(binding["scenario_id"], str))):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_RUN_BINDING_INVALID")
    if (snapshot_id is not None and binding["snapshot_id"] != snapshot_id
            or composite_hash is not None and binding["composite_hash"] != composite_hash
            or binding["scenario_id"] != scenario_id):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_RUN_BINDING_MISMATCH")

    su = _mapping(evidence.get("sources_uses"), "financing_evidence.sources_uses", optional=False)
    for key in SU_REQUIRED:
        _required_number(su, key, "sources_uses")
    if not _close(sum(su[k] for k in SU_USES), su["total_uses_keur"]):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_USES_SUBTOTAL_MISMATCH")
    if not _close(sum(su[k] for k in SU_SOURCES), su["total_sources_keur"]):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_SOURCES_SUBTOTAL_MISMATCH")
    if not _close(su["total_sources_keur"] - su["total_uses_keur"], su["difference_keur"]):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_RESIDUAL_MISMATCH")

    bank = _mapping(evidence.get("bankability"), "financing_evidence.bankability", optional=False)
    for key in (
        "dscr_debt_capacity_keur", "gearing_debt_capacity_keur", "final_senior_commitment_keur",
        "gearing_basis_keur", "gearing_ratio", "fixed_point_iteration_count",
        "fixed_point_maximum_difference_keur",
    ):
        _optional_number(bank, key, "bankability")
    binding_reason = bank.get("binding_senior_constraint")
    if binding_reason is not None and (
        not isinstance(binding_reason, str) or not binding_reason.strip()):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_BINDING_CONSTRAINT_INVALID")
    if (bank.get("final_senior_commitment_keur") is not None
            and not _close(bank["final_senior_commitment_keur"], su["senior_debt_keur"])):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_SENIOR_MISMATCH")

    construction = _mapping(evidence.get("construction_funding"),
                            "financing_evidence.construction_funding", optional=False)
    if not isinstance(construction.get("policy"), str):
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_CONSTRUCTION_POLICY_MISSING")
    for key, sukey in (("total_audit_uses_keur", "total_uses_keur"),
                       ("total_audit_sources_keur", "total_sources_keur"),
                       ("total_audit_residual_keur", "difference_keur")):
        if not _close(_required_number(construction, key, "construction_funding"), su[sukey]):
            raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_CONSTRUCTION_AUDIT_MISMATCH")
    periods = construction.get("periods")
    if not isinstance(periods, (tuple, list)) or len(periods) > 3000:
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_PERIODS_INVALID")
    period_keys = (
        "project_cash_uses_keur", "senior_draw_keur",
        "junior_or_other_main_funding_draw_keur", "share_capital_draw_keur",
        "share_premium_draw_keur", "other_committed_equity_draw_keur",
        "additional_equity_draw_keur", "shl_cash_draw_keur",
        "sponsor_shl_cash_contribution_keur", "total_sources_keur",
        "sources_uses_difference_keur", "cumulative_project_cash_uses_keur",
        "cumulative_total_sources_keur", "cumulative_sources_uses_difference_keur",
    )
    for row in periods:
        if not isinstance(row, Mapping) or type(row.get("period_index")) is not int:
            raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_PERIOD_ROW_INVALID")
        for key in period_keys:
            _required_number(row, key, "construction_funding.periods")
        if not _close(row["total_sources_keur"] - row["project_cash_uses_keur"],
                      row["sources_uses_difference_keur"]):
            raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_PERIOD_RESIDUAL_MISMATCH")
        for dkey in ("period_start", "period_end", "cashflow_date"):
            if row.get(dkey) is not None and not isinstance(row[dkey], str):
                raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_PERIOD_DATE_INVALID")
    fc = construction.get("non_construction_fc_use")
    if fc is not None:
        fc = _mapping(fc, "financing_evidence.non_construction_fc_use", optional=False)
        for key in ("uses_keur", "total_sources_keur", "residual_keur"):
            _required_number(fc, key, "non_construction_fc_use")
        if not _close(fc["total_sources_keur"]-fc["uses_keur"], fc["residual_keur"]):
            raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_FC_RESIDUAL_MISMATCH")
    return su, bank, construction


def _text_amount(label: str, raw: Any, authority: str) -> Amount:
    if raw is None:
        return missing(label, authority, reason="The canonical Run did not provide this value.")
    if not isinstance(raw, str) or not raw.strip():
        raise FinancingEvidenceInvalid("FINANCING_EVIDENCE_TEXT_METRIC_INVALID")
    return Amount(label, raw, raw, authority)


def build_sources_uses_projection(
    *, runtime_result: Any = None, integrity_evidence: Any = None,
    working_financing: Any = None, working_capex: Any = None,
    freshness: str = "NOT_RUN", run_kind: str = "LAST_RUN",
    expected_snapshot_id: str | None = None,
    expected_composite_hash: str | None = None,
    expected_scenario_id: str | None = None,
) -> dict:
    """Present only the SAME canonical Run; validation never creates financing values."""
    if freshness not in {"CURRENT", "STALE", "NOT_RUN"}:
        raise FinancingEvidenceInvalid("UNKNOWN_RUNTIME_FRESHNESS")
    if run_kind not in {"LAST_RUN", "HISTORICAL_RUN"}:
        raise FinancingEvidenceInvalid("UNKNOWN_RUN_KIND")
    historical = run_kind == "HISTORICAL_RUN"
    has_run = runtime_result is not None
    rs = _mapping(getattr(runtime_result, "runtime_summary", None),
                  "RuntimeResult.runtime_summary")
    debt = _summary(getattr(runtime_result, "debt_schedule", None),
                    "RuntimeResult.debt_schedule")
    sponsor = _summary(getattr(runtime_result, "sponsor_schedule", None),
                       "RuntimeResult.sponsor_schedule")
    existing_integrity = _mapping(integrity_evidence, "Run.integrity_evidence")
    checks = existing_integrity.get("checks")
    if checks is not None and (not isinstance(checks, (list, tuple))
                               or any(not isinstance(c, Mapping) for c in checks)):
        raise FinancingEvidenceInvalid("MALFORMED_INTEGRITY_CHECKS")
    overall = existing_integrity.get("overall")
    integrity = overall if checks and overall in ("PASS", "FAIL", "INCOMPLETE") else "UNAVAILABLE"

    finance = _read_finance_evidence(
        rs, snapshot_id=expected_snapshot_id,
        composite_hash=expected_composite_hash, scenario_id=expected_scenario_id,
    ) if has_run else None
    typed = finance is not None
    if typed:
        su, bank, construction = finance
        prefix = "RuntimeResult.runtime_summary.financing_evidence."
        sources = tuple(
            amount(label, su[key], prefix + "sources_uses." + key)
            for label, key in (
                ("Senior debt (actual sized)", "senior_debt_keur"),
                ("Junior / other project financing", "junior_or_other_keur"),
                ("Share capital and other equity (aggregate)", "share_capital_and_other_equity_keur"),
                ("Shareholder loan cash principal", "shareholder_loan_cash_keur"),
            )
        )
        uses = tuple(
            amount(label, su[key], prefix + "sources_uses." + key)
            for label, key in (
                ("Hard project CAPEX", "base_project_capex_keur"),
                ("Capitalised IDC (incl. VAT IDC)", "capitalized_idc_keur"),
                ("Commitment fees (incl. VAT fees)", "commitment_fee_keur"),
                ("Structuring / bank fees", "structuring_fee_keur"),
                ("Other financing costs", "other_financing_costs_keur"),
                ("Initial cash DSRA funding", "initial_dsra_funding_keur"),
                ("Developer cost reimbursement", "development_cost_reimbursement_keur"),
                ("Developer fee", "developer_fee_keur"),
                ("Other project uses", "other_uses_keur"),
            )
        )
        total_sources = amount("Total Sources", su["total_sources_keur"], prefix+"sources_uses.total_sources_keur")
        total_uses = amount("Total Uses", su["total_uses_keur"], prefix+"sources_uses.total_uses_keur")
        residual = amount("Funding Residual", su["difference_keur"], prefix+"sources_uses.difference_keur")
        balance_status = (
            "BALANCED" if abs(su["difference_keur"]) <= FINANCE_TOLERANCE_KEUR
            else "OVERFUNDED" if su["difference_keur"] > 0 else "UNDERFUNDED"
        )
        bank_metrics = (
            amount("DSCR debt capacity", bank.get("dscr_debt_capacity_keur"),
                   prefix+"bankability.dscr_debt_capacity_keur"),
            amount("Gearing debt capacity", bank.get("gearing_debt_capacity_keur"),
                   prefix+"bankability.gearing_debt_capacity_keur"),
            amount("Final sized Senior commitment", bank.get("final_senior_commitment_keur"),
                   prefix+"bankability.final_senior_commitment_keur"),
            _text_amount("Binding Senior constraint", bank.get("binding_senior_constraint"),
                         prefix+"bankability.binding_senior_constraint"),
            amount("Gearing basis", bank.get("gearing_basis_keur"),
                   prefix+"bankability.gearing_basis_keur"),
            ratio("Requested gearing cap (Run)", bank.get("gearing_ratio"),
                   prefix+"bankability.gearing_ratio", percent=True),
            amount("Fixed-point iterations", bank.get("fixed_point_iteration_count"),
                   prefix+"bankability.fixed_point_iteration_count"),
            amount("Fixed-point convergence residual", bank.get("fixed_point_maximum_difference_keur"),
                   prefix+"bankability.fixed_point_maximum_difference_keur"),
        )
        construction_fields = (
            ("Project uses", "project_cash_uses_keur"),
            ("Senior draw", "senior_draw_keur"),
            ("Junior draw", "junior_or_other_main_funding_draw_keur"),
            ("Share capital draw", "share_capital_draw_keur"),
            ("Share premium draw", "share_premium_draw_keur"),
            ("Other equity draw", "other_committed_equity_draw_keur"),
            ("Additional equity draw", "additional_equity_draw_keur"),
            ("SHL allocated to Uses", "shl_cash_draw_keur"),
            ("SHL sponsor cash contribution", "sponsor_shl_cash_contribution_keur"),
            ("Total period sources", "total_sources_keur"),
            ("Period residual", "sources_uses_difference_keur"),
            ("Cumulative uses", "cumulative_project_cash_uses_keur"),
            ("Cumulative sources", "cumulative_total_sources_keur"),
            ("Cumulative residual", "cumulative_sources_uses_difference_keur"),
        )
        construction_rows = tuple({
            "period": row["period_index"],
            "date": row.get("cashflow_date") or row.get("period_end") or "Not dated",
            "fields": tuple(amount(label, row[key], prefix+"construction_funding.periods."+key)
                            for label, key in construction_fields),
        } for row in construction["periods"])
        nc = construction.get("non_construction_fc_use")
        non_construction = ({
            "policy": nc.get("policy"),
            "uses": amount("FC/COD Uses", nc["uses_keur"], prefix+"construction_funding.non_construction_fc_use.uses_keur"),
            "sources": amount("FC/COD Sources", nc["total_sources_keur"], prefix+"construction_funding.non_construction_fc_use.total_sources_keur"),
            "residual": amount("FC/COD Residual", nc["residual_keur"], prefix+"construction_funding.non_construction_fc_use.residual_keur"),
        } if nc is not None else None)
        waterfall_note = (
            "Canonical construction allocations from the exact Run. SHL allocated to "
            "project Uses and sponsor SHL cash contribution are distinct timing concepts."
        )
    else:
        su, bank, construction = {}, {}, {}
        sources = (
            amount("Actual sized Senior debt", rs.get("senior_debt_keur"),
                   "RuntimeResult.runtime_summary.senior_debt_keur"),
            missing("Junior / other financing", "SourcesAndUses.junior_or_other_keur"),
            missing("Share capital and other equity", "SourcesAndUses.share_capital_and_other_equity_keur"),
            amount("SHL cash contributed", sponsor.get("total_shl_cash_contributed_keur"),
                   "RuntimeResult.sponsor_schedule.summary.total_shl_cash_contributed_keur"),
        )
        uses = tuple(missing(label, "SourcesAndUses."+key) for label, key in (
            ("Hard project CAPEX", "base_project_capex_keur"),
            ("Capitalised IDC", "capitalized_idc_keur"),
            ("Commitment fees", "commitment_fee_keur"),
            ("Structuring / bank fees", "structuring_fee_keur"),
            ("Other financing costs", "other_financing_costs_keur"),
            ("Cash DSRA initial funding", "initial_dsra_funding_keur"),
            ("Developer cost reimbursement", "development_cost_reimbursement_keur"),
            ("Developer fee", "developer_fee_keur"),
            ("Other project uses", "other_uses_keur"),
        ))
        total_sources = missing("Total Sources", "SourcesAndUses.total_sources_keur")
        total_uses = missing("Total Uses", "SourcesAndUses.total_uses_keur")
        residual = missing("Funding Residual", "SourcesAndUses.difference_keur")
        balance_status = "UNAVAILABLE"
        bank_metrics = tuple(
            missing(label, "ProjectFinancingResult."+key)
            for label, key in (
                ("DSCR debt capacity", "dscr_debt_capacity_keur"),
                ("Gearing debt capacity", "gearing_debt_capacity_keur"),
                ("Final sized Senior commitment", "final_senior_commitment_keur"),
                ("Binding Senior constraint", "binding_senior_constraint"),
                ("Gearing basis", "gearing_basis_keur"),
                ("Requested gearing cap (Run)", "gearing_ratio"),
                ("Fixed-point iterations", "fixed_point_iteration_count"),
                ("Fixed-point convergence residual", "fixed_point_maximum_difference_keur"),
            )
        )
        construction_rows, non_construction = (), None
        construction_fields = ()
        waterfall_note = "LEGACY RUN — FINANCING EVIDENCE UNAVAILABLE. No historical backfill."

    bankability = (
        ratio("Actual gearing (Last Run)", rs.get("actual_gearing_pct"),
              "RuntimeResult.runtime_summary.actual_gearing_pct", percent=True),
        ratio("Gearing cap (Last Run)", rs.get("gearing_cap_pct"),
              "RuntimeResult.runtime_summary.gearing_cap_pct", percent=True),
        ratio("DSCR target", debt.get("target_dscr"),
              "RuntimeResult.debt_schedule.summary.target_dscr"),
        ratio("Minimum DSCR", debt.get("actual_min_dscr"),
              "RuntimeResult.debt_schedule.summary.actual_min_dscr"),
        ratio("Minimum LLCR", debt.get("min_llcr"),
              "RuntimeResult.debt_schedule.summary.min_llcr",
              reason=str(debt.get("llcr_unavailable_reason") or "Minimum LLCR not persisted.")),
    ) + bank_metrics
    working = ()
    if not historical:
        working = (
            amount("Hard CAPEX input (not Total Project Uses)", _raw_attr(working_capex, "hard_capex_keur"),
                   "Current typed ProjectInputs.capex.hard_capex_keur"),
            ratio("Requested gearing ratio", _raw_attr(working_financing, "gearing_ratio"),
                   "Current typed ProjectInputs.financing.gearing_ratio", percent=True),
            amount("Configured senior amount (not sized debt)",
                   _raw_attr(working_financing, "senior_debt_amount_keur"),
                   "Current typed ProjectInputs.financing.senior_debt_amount_keur"),
            amount("Share capital configuration", _raw_attr(working_financing, "share_capital_keur"),
                   "Current typed ProjectInputs.financing.share_capital_keur"),
            amount("Share premium configuration", _raw_attr(working_financing, "share_premium_keur"),
                   "Current typed ProjectInputs.financing.share_premium_keur"),
            amount("Other committed equity configuration",
                   _raw_attr(working_financing, "other_equity_funding_before_shl_keur"),
                   "Current typed ProjectInputs.financing.other_equity_funding_before_shl_keur"),
            amount("Junior / other funding configuration",
                   _raw_attr(working_financing, "junior_or_other_project_funding_keur"),
                   "Current typed ProjectInputs.financing.junior_or_other_project_funding_keur"),
            amount("SHL configured amount (not actual principal)",
                   _raw_attr(working_financing, "shl_amount_keur"),
                   "Current typed ProjectInputs.financing.shl_amount_keur"),
        )
    return {
        "run_kind": run_kind,
        "freshness": "HISTORICAL" if historical else freshness,
        "has_run": has_run,
        "has_financing_evidence": typed,
        "legacy_financing": has_run and not typed,
        "sources": sources, "uses": uses, "working": working, "bankability": bankability,
        "total_sources": total_sources, "total_uses": total_uses, "residual": residual,
        "balance_status": balance_status,
        "construction_rows": construction_rows,
        "construction_fields": tuple(label for label, key in construction_fields),
        "non_construction": non_construction,
        "construction_policy": construction.get("policy") if typed else None,
        "integrity": integrity,
        "integrity_note": (
            "Run Integrity and Sources & Uses balance are independent. "
            "CURRENT is an input freshness verdict, not a financial PASS."
        ),
        "funding_waterfall_reason": waterfall_note,
        "su_authority_gap": (
            "FINANCING_F1_V1: full-precision canonical SourcesAndUses, debt capacity and "
            "funding allocations, bound atomically to this committed Run."
            if typed else FULL_SU_AUTHORITY
        ),
        "balance_write_gap": BALANCE_WRITE_GAP,
        "sponsor_mode": (
            str(getattr(_raw_attr(working_financing, "sponsor_funding_mode"), "value",
                        _raw_attr(working_financing, "sponsor_funding_mode")))
            if working_financing is not None and not historical else "Not bound to historical run"
        ),
        "integrity_codes": tuple(str(c.get("reason_code", "")) for c in (checks or ())
                                 if c.get("status") in {"FAIL", "UNAVAILABLE"} and c.get("reason_code")),
    }
