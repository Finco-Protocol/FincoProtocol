"""Committed (Run-bound) Developer Economics view and the editor model. Display only.

Everything shown as a result comes from the validated evidence committed with a Run
(``app.model_v2.developer_evidence``); the Working Copy configuration is shown separately and is
never used to reconstruct a Last Run or a historical Run. No calculation happens here.
"""
from __future__ import annotations

from typing import Any, Optional

from app.model_v2.developer_evidence import has_developer_key, read_committed_evidence
from app.v2.developer_economics_projection import NA, _STATUS_REASON, _keur, _multiple, _pct

NOT_RUN, CURRENT, STALE, HISTORICAL = "NOT_RUN", "CURRENT", "STALE", "HISTORICAL"
UNAVAILABLE, NOT_ENABLED = "UNAVAILABLE", "NOT_ENABLED_AT_RUN"
BLANK_SPEND_ROWS = 3


def build_committed_view(summary: Optional[dict], *, freshness: str, snapshot_id: Optional[str],
                         composite_hash: Optional[str], historical: bool = False,
                         ran_at: str = "") -> dict:
    """``freshness`` is the canonical CURRENT/STALE/NOT_RUN of the Last Run; ignored when historical."""
    if not summary or (not historical and freshness == NOT_RUN):
        return {"state": NOT_RUN, "note": "No committed Run: Developer Economics results exist only after a canonical Run."}
    label = HISTORICAL if historical else (STALE if freshness == STALE else CURRENT)
    if not has_developer_key(summary):
        return {"state": NOT_ENABLED, "freshness": label, "ran_at": ran_at,
                "note": "Developer Economics was not enabled in this Run; the Run carries no Developer ledger."}
    evidence = read_committed_evidence(summary, expect_snapshot_id=snapshot_id, expect_composite_hash=composite_hash)
    if evidence is None:
        return {"state": UNAVAILABLE, "freshness": label, "ran_at": ran_at,
                "note": "The stored Developer evidence failed validation (shape, finite numbers or Run binding); no figure is shown."}
    status_note = {k: _STATUS_REASON.get(evidence[k], "") for k in ("developer_moic_status", "developer_xirr_status")}
    metrics = (
        {"key": "developer_moic", "label": "Developer MOIC", "display": _multiple(evidence["developer_moic"]),
         "available": evidence["developer_moic"] is not None, "reason": status_note["developer_moic_status"]},
        {"key": "developer_xirr", "label": "Developer XIRR", "display": _pct(evidence["developer_xirr"]),
         "available": evidence["developer_xirr"] is not None, "reason": status_note["developer_xirr_status"]},
    )
    fee_basis = evidence["fee_basis"]
    return {
        "state": label, "freshness": label, "ran_at": ran_at, "outcome": evidence["outcome"],
        "settlement_date": evidence["settlement_date"], "metrics": metrics,
        "total_spend": _keur(evidence["total_development_spend_keur"]),
        "reimbursement": _keur(evidence["reimbursed_development_cost_keur"]),
        "fee": _keur(evidence["developer_fee_keur"]), "receipts": _keur(evidence["total_developer_receipts_keur"]),
        "fee_basis": NA if fee_basis["basis_keur"] is None else f"{_keur(fee_basis['basis_keur'])} kEUR hard CAPEX",
        "fee_mode": fee_basis["mode"],
        "vector": [{"date": r["date"], "spend": _keur(-r["development_spend_keur"] if r["development_spend_keur"] else 0.0),
                    "reimbursement": _keur(r["development_cost_reimbursement_keur"]), "fee": _keur(r["developer_fee_keur"]),
                    "net": _keur(r["net_developer_cashflow_keur"])} for r in evidence["cashflows"]],
        "note": ("Prior committed result; the Working Copy changed since this Run. Run again to refresh."
                 if label == STALE else
                 "Committed with the selected historical Run; never recomputed from the Working Copy." if historical else
                 "Committed with the Last Run."),
    }


def build_editor_model(config: Any, *, scenario_name: str, is_base: bool, overridden: bool, raw_error: str = "") -> dict:
    """Display model for the configuration form. Percent fees are shown in percentage points; the
    stored value stays the typed 0..1 fraction."""
    rows = [{"date": e.spend_date.isoformat(), "amount": e.amount_keur} for e in (config.spend_schedule if config else ())]
    pct = bool(config) and config.developer_fee_mode.value == "PCT_OF_HARD_CAPEX"
    return {
        "enabled": bool(config and config.enabled), "outcome": config.outcome.value if config else "REALIZED",
        "rows": rows + [{"date": "", "amount": ""}] * BLANK_SPEND_ROWS,
        "reimbursed": config.reimbursed_development_cost_keur if config else 0.0,
        "fee_mode": config.developer_fee_mode.value if config else "FIXED_KEUR",
        "fee_value_display": (round(config.developer_fee_value * 100, 10) if pct else config.developer_fee_value) if config else 0.0,
        "scope": scenario_name, "is_base": is_base, "overridden": overridden, "error": raw_error,
    }


def document_from_form(form) -> dict:
    """Translate the submitted form into the strict typed document (units converted exactly once).
    Raises ``DeveloperConfigError`` for anything incomplete; never defaults a financial term."""
    from app.workbook.developer_economics_config import DeveloperConfigError, VERSION

    def number(name):
        text = str(form.get(name) or "").strip().replace(",", "")
        try:
            return float(text)
        except ValueError as exc:
            raise DeveloperConfigError(f"DEV_ECON_NUMBER: {name} must be a number") from exc

    dates, amounts = form.getlist("spend_date"), form.getlist("spend_amount")
    if len(dates) != len(amounts):
        raise DeveloperConfigError("DEV_ECON_SCHEDULE: spend rows are incomplete")
    rows = []
    for spend_date, amount in zip(dates, amounts):
        spend_date, amount = str(spend_date).strip(), str(amount).strip().replace(",", "")
        if not spend_date and not amount:
            continue                       # untouched blank row
        if not spend_date or not amount:
            raise DeveloperConfigError("DEV_ECON_SCHEDULE: every spend row needs both a date and an amount")
        try:
            rows.append({"spend_date": spend_date, "amount_keur": float(amount)})
        except ValueError as exc:
            raise DeveloperConfigError("DEV_ECON_NUMBER: spend amount must be a number") from exc
    mode = str(form.get("fee_mode") or "")
    fee = number("fee_value")
    if mode == "PCT_OF_HARD_CAPEX":
        fee = round(fee / 100.0, 12)       # displayed percentage points -> typed fraction
    return {
        "version": VERSION, "enabled": form.get("enabled") == "on", "outcome": str(form.get("outcome") or ""),
        "spend_schedule": rows, "reimbursed_development_cost_keur": number("reimbursed"),
        "developer_fee_mode": mode, "developer_fee_value": fee,
        "settlement": "AT_FINANCIAL_CLOSE", "book_basis_mode": "CAPITALISE_AS_SOFT_COSTS",
    }
