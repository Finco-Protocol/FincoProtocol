"""RC-3/M6: read-only exact G2C acquisition evidence; no finance calculation."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math

KEY = "acquisition_source_candidate_v1"
SOURCE_VERSION = 1
AUTHORITY = "COVENANT_GATED_G2C_AND_C1_PROJECT_RETURN"
TOL = 1e-7


class AcquisitionEvidenceError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value, *, positive=True):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise AcquisitionEvidenceError("NON_FINITE_OR_MISSING_SOURCE")
    if positive and value < 0:
        raise AcquisitionEvidenceError("NEGATIVE_RECEIPT")
    return float(value)


def _day(value):
    if type(value) is not date:
        raise AcquisitionEvidenceError("SOURCE_DATE_MISSING")
    return value.isoformat()


def extract(g2c):
    """Pass-through immutable-ready full-precision source facts from completed G2C.

    No investor waterfall, discounting, valuation, or allocation executes here.
    A missing mandatory G2C field makes only M6 evidence unavailable.
    """
    rows = []
    previous = None
    for p in g2c.waterfall_periods:
        day = _day(p.cashflow_date)
        if previous is not None and day <= previous:
            raise AcquisitionEvidenceError("SOURCE_DATE_AXIS_INVALID")
        previous = day
        gross = _number(p.gross_dividend_paid_keur)
        wht = _number(p.dividend_wht_keur)
        net = _number(p.net_dividend_received_keur)
        if abs(gross - wht - net) > TOL:
            raise AcquisitionEvidenceError("SOURCE_GROSS_NET_RECONCILIATION")
        rows.append({
            "period_index": p.period_index,
            "date": day,
            "gross_legal_dividend_keur": gross,
            "dividend_wht_keur": wht,
            "net_legal_dividend_keur": net,
            "shl_interest_keur": _number(p.shl_cash_interest_receipt_keur),
            "shl_principal_keur": _number(p.actual_shl_principal_paid_keur),
        })
    if not rows:
        raise AcquisitionEvidenceError("SOURCE_PERIODS_MISSING")
    if abs(math.fsum(x["net_legal_dividend_keur"] for x in rows)
           - _number(g2c.total_net_dividend_received_keur)) > TOL:
        raise AcquisitionEvidenceError("SOURCE_NET_TOTAL_MISMATCH")
    # C1 is financing-independent and never a proxy for ordinary equity dividends.
    project = []
    c1 = g2c.return_summary.project
    for p in c1.cashflows:
        project.append({
            "date": _day(p.cashflow_date),
            "net_unlevered_project_cashflow_keur":
                _number(p.net_unlevered_project_cashflow_keur, positive=False),
        })
    return {
        "schema_version": SOURCE_VERSION,
        "authority": AUTHORITY,
        "currency": "EUR",
        "unit": "kEUR",
        "equity_periods": rows,
        "project_cashflows": project,
        "project_return_status": c1.project_xirr_status.value,
    }


def bind(source, *, owner_id, project_id, snapshot_id, composite_hash, scenario_id):
    if not isinstance(source, dict) or source.get("schema_version") != SOURCE_VERSION:
        raise AcquisitionEvidenceError("SOURCE_SCHEMA_INVALID")
    if not all(type(x) is str and bool(x) for x in
               (owner_id, project_id, snapshot_id, composite_hash)):
        raise AcquisitionEvidenceError("RUN_BINDING_INVALID")
    if scenario_id is not None and (type(scenario_id) is not str or not scenario_id):
        raise AcquisitionEvidenceError("SCENARIO_BINDING_INVALID")
    result = dict(source)
    result["binding"] = {
        "owner_id": owner_id, "project_id": project_id,
        "snapshot_id": snapshot_id, "composite_hash": composite_hash,
        "scenario_id": scenario_id,
    }
    result["digest"] = hashlib.sha256(_canonical(result).encode()).hexdigest()
    return result


def validate(evidence, *, owner_id, project_id, snapshot_id, composite_hash, scenario_id):
    """Strict historical read; never reconstruct from a mutable Working Copy."""
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise AcquisitionEvidenceError("EVIDENCE_UNAVAILABLE")
    expected = dict(owner_id=owner_id, project_id=project_id,
                    snapshot_id=snapshot_id, composite_hash=composite_hash,
                    scenario_id=scenario_id)
    if evidence.get("binding") != expected:
        raise AcquisitionEvidenceError("EVIDENCE_RUN_BINDING_MISMATCH")
    unsigned = {k: v for k, v in evidence.items() if k != "digest"}
    if hashlib.sha256(_canonical(unsigned).encode()).hexdigest() != evidence.get("digest"):
        raise AcquisitionEvidenceError("EVIDENCE_DIGEST_MISMATCH")
    if evidence.get("authority") != AUTHORITY or evidence.get("currency") != "EUR" or evidence.get("unit") != "kEUR":
        raise AcquisitionEvidenceError("EVIDENCE_UNIT_OR_AUTHORITY_MISMATCH")
    rows = evidence.get("equity_periods")
    if not isinstance(rows, list) or not rows:
        raise AcquisitionEvidenceError("EVIDENCE_PERIODS_MISSING")
    prev = None
    for row in rows:
        if type(row) is not dict or set(row) != {
            "period_index", "date", "gross_legal_dividend_keur",
            "dividend_wht_keur", "net_legal_dividend_keur",
            "shl_interest_keur", "shl_principal_keur",
        }:
            raise AcquisitionEvidenceError("EVIDENCE_PERIOD_INVALID")
        try:
            day = date.fromisoformat(row["date"])
        except (TypeError, ValueError):
            raise AcquisitionEvidenceError("EVIDENCE_DATE_INVALID") from None
        if day.isoformat() != row["date"] or (prev is not None and day <= prev):
            raise AcquisitionEvidenceError("EVIDENCE_DATE_AXIS_INVALID")
        prev = day
        gross, wht, net = (_number(row[k]) for k in (
            "gross_legal_dividend_keur", "dividend_wht_keur",
            "net_legal_dividend_keur"))
        _number(row["shl_interest_keur"])
        _number(row["shl_principal_keur"])
        if abs(gross - wht - net) > TOL:
            raise AcquisitionEvidenceError("EVIDENCE_GROSS_NET_MISMATCH")
    project = evidence.get("project_cashflows")
    if type(project) is not list:
        raise AcquisitionEvidenceError("EVIDENCE_PROJECT_SERIES_INVALID")
    for row in project:
        if type(row) is not dict or set(row) != {"date", "net_unlevered_project_cashflow_keur"}:
            raise AcquisitionEvidenceError("EVIDENCE_PROJECT_ROW_INVALID")
        try:
            d = date.fromisoformat(row["date"])
            if d.isoformat() != row["date"]:
                raise ValueError()
        except (TypeError, ValueError):
            raise AcquisitionEvidenceError("EVIDENCE_PROJECT_DATE_INVALID") from None
        _number(row["net_unlevered_project_cashflow_keur"], positive=False)
    return evidence
