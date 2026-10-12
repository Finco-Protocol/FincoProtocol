"""F3.7 instrument-level Sources & Uses reconciliation: verification over persisted evidence only.

Every amount here is read from the exact committed Run (``financing_evidence``): the per-facility
construction ledgers (``facility_schedules`` or ``senior_facility`` / ``junior_facility``) and the
aggregate ``sources_uses`` / ``construction_funding`` already validated by the F1 projection.
Sums are presentation sums of persisted numbers used to VERIFY that the instrument ledgers explain
the aggregate lines.  Nothing is derived from a commitment, nothing is plugged, nothing is written,
and a disagreement is reported as DIFFERS with its difference, never repaired.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import re
from typing import Any

from app.v2.financing_sources_uses_projection import (
    Amount, FINANCE_TOLERANCE_KEUR, FinancingEvidenceInvalid, NA, amount,
)

EQUITY_FIELDS = (
    ("Share capital", "share_capital_draw_keur"),
    ("Share premium", "share_premium_draw_keur"),
    ("Other committed equity", "other_committed_equity_draw_keur"),
    ("Additional equity", "additional_equity_draw_keur"),
)
_LEDGER = ("construction_draws_keur", "construction_idc_keur", "upfront_fees_keur",
           "construction_commitment_fees_keur")
UNAVAILABLE_AGGREGATE = (
    "Per-instrument funding is not persisted for this Run (single aggregate Senior sizing or a legacy "
    "Run). A commitment is not proof of funding drawn, so no instrument split is derived."
)
PREFIX = "RuntimeResult.runtime_summary.financing_evidence."
# Facility authorities are the exact strings written by the canonical serializer (app/api/project_runner.py).
TWO_SENIOR_AUTHORITY = "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
JUNIOR_AUTHORITY = "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1"
_TWO_SENIOR_KEYS = ("facility_schedules", "aggregate_period_rates")
_JUNIOR_KEYS = ("senior_facility", "junior_facility", "junior_cash_idc", "junior_policy_digest")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _ledger(facility: Mapping, key: str, periods: int, who: str) -> tuple[float, ...]:
    values = facility.get(key)
    if (not isinstance(values, (list, tuple)) or len(values) != periods
            or any(not _finite(v) or v < -FINANCE_TOLERANCE_KEUR for v in values)):
        raise FinancingEvidenceInvalid(f"FINANCING_INSTRUMENT_LEDGER_INVALID: {who}.{key}")
    return tuple(float(v) for v in values)


def _facility(raw: Any, periods: list, role: str, path: str) -> dict:
    if not isinstance(raw, Mapping):
        raise FinancingEvidenceInvalid(f"FINANCING_INSTRUMENT_INVALID: {path}")
    ident = raw.get("instrument_id")
    if not isinstance(ident, str) or not ident or not _finite(raw.get("commitment_keur")) or raw["commitment_keur"] < 0:
        raise FinancingEvidenceInvalid(f"FINANCING_INSTRUMENT_INVALID: {path}")
    ledgers = {key: _ledger(raw, key, len(periods), path) for key in _LEDGER}
    total = {key: math.fsum(values) for key, values in ledgers.items()}
    drawn, commitment = total["construction_draws_keur"], float(raw["commitment_keur"])
    if drawn > commitment + FINANCE_TOLERANCE_KEUR:
        raise FinancingEvidenceInvalid(f"FINANCING_INSTRUMENT_OVERDRAWN: {path}")
    src = PREFIX + path
    if abs(drawn - commitment) <= FINANCE_TOLERANCE_KEUR:
        state = "FULLY DRAWN in construction"
    else:
        state = f"PARTLY DRAWN: {commitment - drawn:,.2f} kEUR of the commitment is not drawn"
    return {
        "instrument_id": ident, "role": role, "ledgers": ledgers, "totals": total,
        "commitment": amount("Contractual commitment", commitment, src + ".commitment_keur"),
        "drawn": amount("Actual construction draws", drawn, src + ".construction_draws_keur"),
        "idc": amount("Capitalised IDC", total["construction_idc_keur"], src + ".construction_idc_keur"),
        "upfront": amount("Upfront fee", total["upfront_fees_keur"], src + ".upfront_fees_keur"),
        "commitment_fee": amount("Commitment fee", total["construction_commitment_fees_keur"],
                                 src + ".construction_commitment_fees_keur"),
        "draw_state": state,
        "periods": tuple({
            "period": row["period_index"], "date": row.get("cashflow_date") or row.get("period_end") or "Not dated",
            "draw": amount("Draw", ledgers["construction_draws_keur"][i], src + ".construction_draws_keur"),
            "idc": amount("IDC", ledgers["construction_idc_keur"][i], src + ".construction_idc_keur"),
            "fees": amount("Fees", ledgers["upfront_fees_keur"][i] + ledgers["construction_commitment_fees_keur"][i],
                           src + ".upfront_fees_keur+construction_commitment_fees_keur"),
        } for i, row in enumerate(periods)),
    }


def _check(label: str, expected_label: str, expected: float, parts: list[tuple[str, float]], path: str) -> dict:
    actual = math.fsum(v for _, v in parts)
    difference = actual - expected
    ok = abs(difference) <= FINANCE_TOLERANCE_KEUR
    difference = 0.0 if ok else difference         # display only: never show float noise as -0.00
    return {
        "label": label, "status": "RECONCILED" if ok else "DIFFERS",
        "aggregate": amount(expected_label, expected, path), "instruments": amount("Instrument ledgers", actual, "Σ persisted instrument ledgers"),
        "difference": amount("Difference", difference, "instrument ledgers − aggregate"),
        "contributors": tuple((name, f"{value:,.2f}") for name, value in parts),
    }


def _digest(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise FinancingEvidenceInvalid(f"FINANCING_EVIDENCE_DIGEST_INVALID: {what}")
    return value


def _authority_mode(evidence: Mapping) -> str:
    """Strict facility-authority dispatch; ambiguity is rejected, aggregate-only stays UNAVAILABLE."""
    authority = evidence.get("facility_authority")
    two = [k for k in _TWO_SENIOR_KEYS if k in evidence]
    junior = [k for k in _JUNIOR_KEYS if k in evidence]
    if authority is None:
        if two or junior or "collection_digest" in evidence:
            raise FinancingEvidenceInvalid("FINANCING_FACILITY_AUTHORITY_MISSING")
        return "AGGREGATE"
    if authority == TWO_SENIOR_AUTHORITY:
        if junior:
            raise FinancingEvidenceInvalid("FINANCING_MIXED_FACILITY_SERIALIZER")
        schedules = evidence.get("facility_schedules")
        if not isinstance(schedules, (list, tuple)) or len(schedules) != 2:
            raise FinancingEvidenceInvalid("FINANCING_TWO_SENIOR_REQUIRES_EXACTLY_TWO_SCHEDULES")
        _digest(evidence.get("collection_digest"), "collection_digest")
        if not isinstance(evidence.get("aggregate_period_rates"), (list, tuple)):
            raise FinancingEvidenceInvalid("FINANCING_TWO_SENIOR_RATES_MISSING")
        return "TWO_SENIOR"
    if authority == JUNIOR_AUTHORITY:
        if two:
            raise FinancingEvidenceInvalid("FINANCING_MIXED_FACILITY_SERIALIZER")
        if len(junior) != len(_JUNIOR_KEYS) or "facility_schedules" in evidence:
            raise FinancingEvidenceInvalid("FINANCING_JUNIOR_EVIDENCE_INCOMPLETE")
        _digest(evidence.get("collection_digest"), "collection_digest")
        _digest(evidence.get("junior_policy_digest"), "junior_policy_digest")
        return "JUNIOR"
    raise FinancingEvidenceInvalid("FINANCING_FACILITY_AUTHORITY_UNKNOWN")


def _validate_junior_cash_idc(evidence: Mapping, junior: dict, periods: list) -> float:
    """Bind the canonical Junior cash-IDC ledger to this Run's collection, instrument and facility."""
    cash = evidence.get("junior_cash_idc")
    if not isinstance(cash, Mapping):
        raise FinancingEvidenceInvalid("FINANCING_JUNIOR_CASH_IDC_MISSING")
    values = cash.get("capitalized_cash_by_period_keur")
    if (not isinstance(values, (list, tuple)) or len(values) != len(periods)
            or any(not _finite(v) or v < 0 for v in values)):
        raise FinancingEvidenceInvalid("FINANCING_JUNIOR_CASH_IDC_LEDGER_INVALID")
    if cash.get("instrument_id") != junior["instrument_id"]:
        raise FinancingEvidenceInvalid("FINANCING_JUNIOR_CASH_IDC_INSTRUMENT_MISMATCH")
    if _digest(cash.get("collection_digest"), "junior_cash_idc.collection_digest") != evidence["collection_digest"]:
        raise FinancingEvidenceInvalid("FINANCING_JUNIOR_CASH_IDC_COLLECTION_MISMATCH")
    book_life = cash.get("book_life_years")
    if type(book_life) is not int or not 1 <= book_life <= 100:
        raise FinancingEvidenceInvalid("FINANCING_JUNIOR_CASH_IDC_BOOK_LIFE_INVALID")
    payload = (cash["instrument_id"], cash["collection_digest"], tuple(float(v) for v in values), book_life)
    # Same self-binding digest the canonical contract records; recomputed here, never trusted.
    if _digest(cash.get("evidence_digest"), "junior_cash_idc.evidence_digest") != hashlib.sha256(
            json.dumps(payload, separators=(",", ":")).encode()).hexdigest():
        raise FinancingEvidenceInvalid("FINANCING_JUNIOR_CASH_IDC_EVIDENCE_TAMPERED")
    for index, (ledger, facility) in enumerate(zip(values, junior["ledgers"]["construction_idc_keur"])):
        if abs(ledger - facility) > FINANCE_TOLERANCE_KEUR:
            raise FinancingEvidenceInvalid(f"FINANCING_JUNIOR_CASH_IDC_PERIOD_MISMATCH: period {index + 1}")
    return math.fsum(values)


def build_instrument_reconciliation(evidence: Mapping, su: Mapping, periods: list) -> dict:
    """Return the instrument funding view; ``available`` is False when only aggregate evidence exists."""
    mode = _authority_mode(evidence)
    junior_mode = mode == "JUNIOR"
    equity = tuple(
        amount(label, math.fsum(p[key] for p in periods), PREFIX + "construction_funding.periods." + key)
        for label, key in EQUITY_FIELDS)
    shl = amount("Shareholder loan cash", math.fsum(p["shl_cash_draw_keur"] for p in periods),
                 PREFIX + "construction_funding.periods.shl_cash_draw_keur")
    equity_checks = [
        _check("Equity construction ledger", "Share capital and other equity (aggregate)",
               su["share_capital_and_other_equity_keur"],
               [(label, math.fsum(p[key] for p in periods)) for label, key in EQUITY_FIELDS],
               PREFIX + "sources_uses.share_capital_and_other_equity_keur"),
        _check("Shareholder loan construction ledger", "Shareholder loan cash principal", su["shareholder_loan_cash_keur"],
               [("SHL allocated to Uses", shl.value)], PREFIX + "sources_uses.shareholder_loan_cash_keur"),
    ]
    base = {"equity": equity, "shl": shl, "equity_checks": equity_checks, "capital_stack_link": True}

    if mode == "AGGREGATE":
        return {**base, "available": False, "mode": "AGGREGATE", "instruments": (), "checks": equity_checks,
                "status": "UNAVAILABLE", "unavailable_reason": UNAVAILABLE_AGGREGATE}
    if junior_mode:
        facilities = [_facility(evidence["senior_facility"], periods, "Senior", "senior_facility"),
                      _facility(evidence["junior_facility"], periods, "Junior", "junior_facility")]
    else:
        facilities = [_facility(f, periods, "Senior", f"facility_schedules[{n}]")
                      for n, f in enumerate(evidence["facility_schedules"])]
    if len({f["instrument_id"] for f in facilities}) != len(facilities):
        raise FinancingEvidenceInvalid("FINANCING_INSTRUMENT_DUPLICATE_ID")

    seniors = [f for f in facilities if f["role"] == "Senior"]
    juniors = [f for f in facilities if f["role"] == "Junior"]
    pick = lambda group, key: [(f["instrument_id"], f["totals"][key]) for f in group]  # noqa: E731
    checks = [
        _check("Senior draws", "Senior debt", su["senior_debt_keur"], pick(seniors, "construction_draws_keur"),
               PREFIX + "sources_uses.senior_debt_keur"),
        _check("Junior / other draws", "Junior / other project financing", su["junior_or_other_keur"],
               pick(juniors, "construction_draws_keur"), PREFIX + "sources_uses.junior_or_other_keur"),
        _check("Senior IDC (capitalised once)", "Capitalised IDC", su["capitalized_idc_keur"],
               pick(seniors, "construction_idc_keur"), PREFIX + "sources_uses.capitalized_idc_keur"),
        _check("Senior upfront fees", "Structuring / bank fees", su["structuring_fee_keur"],
               pick(seniors, "upfront_fees_keur"), PREFIX + "sources_uses.structuring_fee_keur"),
        _check("Senior commitment fees", "Commitment fees", su["commitment_fee_keur"],
               pick(seniors, "construction_commitment_fees_keur"), PREFIX + "sources_uses.commitment_fee_keur"),
    ]
    if junior_mode:
        checks.append(_check("Junior IDC (other financing costs)", "Other financing costs", su["other_financing_costs_keur"],
                             pick(juniors, "construction_idc_keur") + pick(juniors, "upfront_fees_keur")
                             + pick(juniors, "construction_commitment_fees_keur"),
                             PREFIX + "sources_uses.other_financing_costs_keur"))
        junior = juniors[0]
        cash_total = _validate_junior_cash_idc(evidence, junior, periods)
        checks.append(_check("Junior cash IDC ledger", "Junior facility IDC", junior["totals"]["construction_idc_keur"],
                             [("junior_cash_idc", cash_total)], PREFIX + "junior_facility.construction_idc_keur"))
    period_rows = []
    for i, p in enumerate(periods):
        for group, key, label in ((seniors, "senior_draw_keur", "Senior draws"),
                                  (juniors, "junior_or_other_main_funding_draw_keur", "Junior draws")):
            period_rows.append({"period": p["period_index"], "label": label,
                                **_pair(math.fsum(f["ledgers"]["construction_draws_keur"][i] for f in group), p[key])})
    checks.extend(equity_checks)
    status = "RECONCILED" if all(c["status"] == "RECONCILED" for c in checks) and all(r["ok"] for r in period_rows) else "DIFFERS"
    return {**base, "available": True, "mode": "JUNIOR" if junior_mode else "TWO_SENIOR", "instruments": tuple(facilities),
            "checks": checks, "period_checks": tuple(period_rows), "status": status, "unavailable_reason": None}


def _pair(ledger: float, aggregate: float) -> dict:
    return {"ledger": f"{ledger:,.2f}", "aggregate": f"{aggregate:,.2f}",
            "ok": abs(ledger - aggregate) <= FINANCE_TOLERANCE_KEUR}


__all__ = ["build_instrument_reconciliation", "UNAVAILABLE_AGGREGATE", "NA", "Amount"]
