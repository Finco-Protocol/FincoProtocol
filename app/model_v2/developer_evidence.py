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


def _finite(value, *, optional=False):
    if value is None:
        return optional
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_committed_evidence(summary, *, expect_snapshot_id=None, expect_composite_hash=None):
    """Return the validated evidence dict from a persisted ``runtime_summary``, or ``None``.

    ``None`` means no Developer evidence was committed with that Run OR the stored document is not
    trustworthy; callers distinguish them with ``has_developer_key``.
    """
    document = (summary or {}).get(EVIDENCE_KEY)
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        return None
    try:
        binding = document["run_binding"]
        if not isinstance(binding, dict) or set(binding) != set(_BINDING_KEYS):
            return None
        if expect_snapshot_id is not None and binding["snapshot_id"] != expect_snapshot_id:
            return None
        if expect_composite_hash is not None and binding["composite_hash"] != expect_composite_hash:
            return None
        for key in ("total_development_spend_keur", "reimbursed_development_cost_keur",
                    "developer_fee_keur", "total_developer_receipts_keur"):
            if not _finite(document[key]):
                return None
        if not (_finite(document["developer_moic"], optional=True) and _finite(document["developer_xirr"], optional=True)):
            return None
        for row in document["cashflows"]:
            if not all(_finite(row[k]) for k in ("development_spend_keur", "development_cost_reimbursement_keur",
                                                  "developer_fee_keur", "net_developer_cashflow_keur")):
                return None
        from app.workbook.developer_economics_config import parse_config
        if parse_config(document["input"]) is None:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return document


def has_developer_key(summary) -> bool:
    return isinstance(summary, dict) and EVIDENCE_KEY in summary
