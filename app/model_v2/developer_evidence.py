"""Run-bound Developer Economics evidence: serialisation and read-back only, never a calculator.

``serialize_developer_evidence`` passes the canonical ``DeveloperEconomicsResult`` through as plain
JSON next to the exact typed input it was computed from. ``read_committed_evidence`` re-validates a
persisted document (shape, finite numbers, binding) and fails closed to ``None`` so a corrupted or
foreign document is shown as UNAVAILABLE and never reconstructed from the Working Copy.
"""
from __future__ import annotations

import math

EVIDENCE_KEY = "developer_economics"
SCHEMA = "developer_economics_run_evidence_v1"
_BINDING_KEYS = ("snapshot_id", "composite_hash", "scenario_id")


def serialize_developer_evidence(config, result) -> dict:
    from app.workbook.developer_economics_config import to_document
    return {
        "schema": SCHEMA,
        "methodology_authority": result.methodology_authority,
        "input": to_document(config),
        "outcome": result.outcome,
        "settlement_date": result.settlement_date.isoformat(),
        "cashflows": [{
            "date": row.cashflow_date.isoformat(),
            "development_spend_keur": row.development_spend_keur,
            "development_cost_reimbursement_keur": row.development_cost_reimbursement_keur,
            "developer_fee_keur": row.developer_fee_keur,
            "net_developer_cashflow_keur": row.net_developer_cashflow_keur,
        } for row in result.cashflows],
        "total_development_spend_keur": result.total_development_spend_keur,
        "reimbursed_development_cost_keur": result.reimbursed_development_cost_keur,
        "developer_fee_keur": result.developer_fee_keur,
        "total_developer_receipts_keur": result.total_developer_receipts_keur,
        "developer_moic": result.developer_moic,
        "developer_moic_status": result.developer_moic_status.value,
        "developer_xirr": result.developer_xirr,
        "developer_xirr_status": result.developer_xirr_status.value,
        "fee_basis": {
            "mode": result.fee_basis.mode, "fee_value": result.fee_basis.fee_value,
            "basis_keur": result.fee_basis.basis_keur, "basis_authority": result.fee_basis.basis_authority,
            "fee_keur": result.fee_basis.fee_keur,
        },
    }


def bind(evidence: dict, *, snapshot_id, composite_hash, scenario_id) -> dict:
    return {**evidence, "run_binding": {"snapshot_id": snapshot_id, "composite_hash": composite_hash,
                                        "scenario_id": scenario_id}}


_STATUSES = frozenset({"OK", "NO_NEGATIVE_CASHFLOW", "NO_POSITIVE_CASHFLOW", "NON_CONVERGENT", "ZERO_CONTRIBUTION"})
_OUTCOMES = frozenset({"REALIZED", "ABANDONED"})
_FEE_MODES = frozenset({"FIXED_KEUR", "PCT_OF_HARD_CAPEX"})
_ROW_KEYS = frozenset({"date", "development_spend_keur", "development_cost_reimbursement_keur",
                       "developer_fee_keur", "net_developer_cashflow_keur"})
_FEE_KEYS = frozenset({"mode", "fee_value", "basis_keur", "basis_authority", "fee_keur"})
_TOP = frozenset({"schema", "methodology_authority", "input", "outcome", "settlement_date", "cashflows",
                  "total_development_spend_keur", "reimbursed_development_cost_keur", "developer_fee_keur",
                  "total_developer_receipts_keur", "developer_moic", "developer_moic_status", "developer_xirr",
                  "developer_xirr_status", "fee_basis", "run_binding"})


def _finite(value, *, optional=False):
    if value is None:
        return optional
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _iso_date(value):
    from datetime import date
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _valid(document, *, snapshot_id, composite_hash, scenario_id, check_scenario) -> bool:
    """Whole-document structural validation. Never raises: any problem is simply ``False``."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or set(document) != _TOP:
        return False
    binding = document["run_binding"]
    if not isinstance(binding, dict) or set(binding) != set(_BINDING_KEYS):
        return False
    if not (_text(binding["snapshot_id"]) and _text(binding["composite_hash"])
            and (binding["scenario_id"] is None or _text(binding["scenario_id"]))):
        return False
    if snapshot_id is not None and binding["snapshot_id"] != snapshot_id:
        return False
    if composite_hash is not None and binding["composite_hash"] != composite_hash:
        return False
    if check_scenario and (binding["scenario_id"] or None) != (scenario_id or None):
        return False
    if document["outcome"] not in _OUTCOMES or not _iso_date(document["settlement_date"]) \
            or not _text(document["methodology_authority"]):
        return False
    for key in ("total_development_spend_keur", "reimbursed_development_cost_keur", "developer_fee_keur",
                "total_developer_receipts_keur"):
        if not _finite(document[key]) or document[key] < 0:
            return False
    if not (_finite(document["developer_moic"], optional=True) and _finite(document["developer_xirr"], optional=True)):
        return False
    for key in ("developer_moic_status", "developer_xirr_status"):
        if document[key] not in _STATUSES:
            return False
    # A figure is shown only with the status that justifies it; a missing figure needs a non-OK status.
    for value_key, status_key in (("developer_moic", "developer_moic_status"), ("developer_xirr", "developer_xirr_status")):
        if (document[value_key] is None) == (document[status_key] == "OK"):
            return False
    rows = document["cashflows"]
    if not isinstance(rows, list) or not rows:
        return False
    previous = ""
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS or not _iso_date(row["date"]) or row["date"] <= previous:
            return False
        previous = row["date"]
        if not all(_finite(row[k]) for k in _ROW_KEYS - {"date"}):
            return False
    fee = document["fee_basis"]
    if not isinstance(fee, dict) or set(fee) != _FEE_KEYS or fee["mode"] not in _FEE_MODES \
            or not _finite(fee["fee_value"]) or not _finite(fee["fee_keur"]) \
            or not _finite(fee["basis_keur"], optional=True) or not _text(fee["basis_authority"]):
        return False
    if (fee["mode"] == "PCT_OF_HARD_CAPEX") != (fee["basis_keur"] is not None):
        return False
    from app.workbook.developer_economics_config import parse_config
    config = parse_config(document["input"])
    return config is not None and config.enabled and config.outcome.value == document["outcome"]


def read_committed_evidence(summary, *, expect_snapshot_id=None, expect_composite_hash=None,
                            expect_scenario_id=None, check_scenario=False):
    """Return the validated evidence dict from a persisted ``runtime_summary``, or ``None``.

    ``None`` means no Developer evidence was committed with that Run OR the stored document is not
    trustworthy; callers distinguish them with ``has_developer_key``. Never raises.
    """
    document = (summary or {}).get(EVIDENCE_KEY) if isinstance(summary, dict) else None
    try:
        ok = _valid(document, snapshot_id=expect_snapshot_id, composite_hash=expect_composite_hash,
                    scenario_id=expect_scenario_id, check_scenario=check_scenario)
    except Exception:       # defensive: malformed storage must degrade to UNAVAILABLE, never to a 500
        return None
    return document if ok else None


def has_developer_key(summary) -> bool:
    return isinstance(summary, dict) and EVIDENCE_KEY in summary
