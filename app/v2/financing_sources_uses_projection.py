"""F1 read-only Sources & Uses projection over persisted canonical evidence.

There is deliberately no calculator, no funding plug and no engine import here.
The full typed SourcesAndUses object produced by the financing engine is NOT
persisted by RuntimeResult as of F1.  Missing rows, totals and residuals must
remain unavailable until a separately reviewed run-bound serialization seam exists.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any

from app.workbook.runtime_projection import thaw_runtime_payload

NA = "Unavailable"
FULL_SU_AUTHORITY = (
    "RuntimeResult has no persisted financing.project_uses / SourcesAndUses / "
    "construction_funding totals and residual. Requires a reviewed Run-bound "
    "serialization and Run History bridge."
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
    value: float | None
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


def ratio(label: str, raw: Any, authority: str, *, percent: bool = False) -> Amount:
    """Format an authoritative fraction or coverage multiple; no economic arithmetic."""
    item = amount(label, raw, authority)
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


def build_sources_uses_projection(
    *, runtime_result: Any = None, integrity_evidence: Any = None,
    working_financing: Any = None, working_capex: Any = None,
    freshness: str = "NOT_RUN", run_kind: str = "LAST_RUN",
) -> dict:
    """No financial arithmetic: every observed value retains its owning source.

    For HISTORICAL_RUN, working inputs are suppressed because their current state
    is unrelated to the selected immutable run.
    """
    if freshness not in {"CURRENT", "STALE", "NOT_RUN"}:
        raise FinancingEvidenceInvalid("UNKNOWN_RUNTIME_FRESHNESS")
    if run_kind not in {"LAST_RUN", "HISTORICAL_RUN"}:
        raise FinancingEvidenceInvalid("UNKNOWN_RUN_KIND")
    historical = run_kind == "HISTORICAL_RUN"
    rs = _mapping(getattr(runtime_result, "runtime_summary", None),
                  "RuntimeResult.runtime_summary")
    debt = _summary(getattr(runtime_result, "debt_schedule", None),
                    "RuntimeResult.debt_schedule")
    sponsor = _summary(getattr(runtime_result, "sponsor_schedule", None),
                       "RuntimeResult.sponsor_schedule")
    evidence = _mapping(integrity_evidence, "Run.integrity_evidence")
    checks = evidence.get("checks")
    if checks is not None and (not isinstance(checks, (list, tuple))
                               or any(not isinstance(c, Mapping) for c in checks)):
        raise FinancingEvidenceInvalid("MALFORMED_INTEGRITY_CHECKS")
    overall = evidence.get("overall")
    integrity = overall if checks and overall in ("PASS", "FAIL", "INCOMPLETE") else "UNAVAILABLE"

    has_run = runtime_result is not None
    senior = amount("Actual sized Senior debt", rs.get("senior_debt_keur") if has_run else None,
                    "RuntimeResult.runtime_summary.senior_debt_keur")
    shl = amount("SHL cash contributed (not total sponsor funding)",
                 sponsor.get("total_shl_cash_contributed_keur") if has_run else None,
                 "RuntimeResult.sponsor_schedule.summary.total_shl_cash_contributed_keur")
    sources = (
        senior,
        missing("Junior / other funds drawn", "ProjectFinancingResult.junior_or_other_main_project_funding_keur"),
        missing("Legal-equity capital drawn", "ConstructionFundingResult.periods.legal_equity_draws"),
        shl,
        missing("Additional sponsor funding drawn", "ProjectFinancingResult.additional_equity_keur"),
    )
    uses = tuple(missing(label, path) for label, path in (
        ("Hard project CAPEX", "ProjectUses.hard_project_capex_keur"),
        ("Capitalised IDC", "ConstructionFinancingResult.senior_idc_capitalized_uses_keur"),
        ("Commitment fees", "ConstructionFinancingResult.senior_commitment_fee_capitalized_keur"),
        ("Structuring / bank fees", "ConstructionFinancingResult.structuring_fee_keur"),
        ("VAT-facility financing costs", "ConstructionFinancingResult.vat_idc_keur / vat_commitment_fee_keur"),
        ("Cash DSRA initial funding", "ProjectUses.reserve_account_funding_keur"),
        ("Developer cost reimbursement", "ProjectUses.development_cost_reimbursement_keur"),
        ("Developer fee", "ProjectUses.developer_fee_keur"),
        ("Other project uses", "ProjectUses.other_explicit_project_uses_keur"),
    ))
    bankability = (
        ratio("Actual gearing (Last Run)", rs.get("actual_gearing_pct"),
               "RuntimeResult.runtime_summary.actual_gearing_pct", percent=True),
        ratio("Gearing cap (Last Run)", rs.get("gearing_cap_pct"),
               "RuntimeResult.runtime_summary.gearing_cap_pct", percent=True),
        ratio("DSCR target (Last Run)", debt.get("target_dscr"),
               "RuntimeResult.debt_schedule.summary.target_dscr"),
        ratio("Minimum DSCR", debt.get("actual_min_dscr"),
               "RuntimeResult.debt_schedule.summary.actual_min_dscr"),
        ratio("Minimum LLCR", debt.get("min_llcr"),
               "RuntimeResult.debt_schedule.summary.min_llcr",
               str(debt.get("llcr_unavailable_reason") or "Minimum LLCR is not persisted.")),
        missing("DSCR debt capacity", "ProjectFinancingResult.dscr_debt_capacity_keur",
                reason="Debt capacity engine output is not persisted."),
        missing("Gearing debt capacity", "ProjectFinancingResult.gearing_debt_capacity_keur",
                reason="Gearing capacity engine output is not persisted."),
        missing("Binding senior constraint", "ProjectFinancingResult.binding_senior_constraint",
                reason="Typed binding constraint is engine-only; not persisted."),
        missing("Solver feasibility", "ProjectFinancingResult.fixed_point_maximum_difference_keur",
                reason="The financing solver verdict is not persisted."),
    )
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
        "sources": sources,
        "uses": uses,
        "working": working,
        "bankability": bankability,
        "total_sources": missing("Total Sources", "SourcesAndUses.total_sources_keur"),
        "total_uses": missing("Total Uses", "SourcesAndUses.total_uses_keur"),
        "residual": missing("Funding residual", "SourcesAndUses.difference_keur"),
        "integrity": integrity,
        "integrity_note": (
            "This is the persisted Run Integrity verdict, NOT proof that Sources & Uses "
            "are balanced. Freshness and integrity are independent."
        ),
        "funding_waterfall_reason": (
            "ConstructionFundingResult period allocation and non-construction FC use "
            "are not in the current RuntimeResult / Run History payload."
        ),
        "su_authority_gap": FULL_SU_AUTHORITY,
        "balance_write_gap": BALANCE_WRITE_GAP,
        "sponsor_mode": (
            str(getattr(_raw_attr(working_financing, "sponsor_funding_mode"), "value",
                        _raw_attr(working_financing, "sponsor_funding_mode")))
            if working_financing is not None and not historical else "Not bound to historical run"
        ),
        "integrity_codes": tuple(str(c.get("reason_code", "")) for c in (checks or ())
                                 if c.get("status") in {"FAIL", "UNAVAILABLE"} and c.get("reason_code")),
    }
