"""Read-only commercial-price stress over ONE existing canonical financial runner.

No portfolio store, separate scenario manager, last-run promotion, bank solver,
or financial formula. Results are hypothetical comparisons against the selected
Working Copy/scenario. Lender-specific pricing is explicitly NOT certified.
"""
from __future__ import annotations

import json
import math
from datetime import date
from dataclasses import replace

from app.workbook.revenue_multistream import canonical_json
from domain.revenue.multistream_runtime import parse_config


class CommercialStressUnavailable(ValueError):
    pass


SUPPORTED = {
    "merchant_down": "Downside Merchant reference price",
    "merchant_up": "Upside Merchant reference price",
    "ppa_down": "Downside contracted PPA price",
    "ppa_expiry": "Earlier PPA expiry and residual Merchant exposure",
}


def changed_book(raw: str, shock: str, amount_pct: float, *, expiry_date: str = "") -> str:
    if shock not in SUPPORTED:
        raise CommercialStressUnavailable("STRESS_UNSUPPORTED: unrecognized commercial stress")
    if isinstance(amount_pct, bool) or not isinstance(amount_pct, (int, float)) or not math.isfinite(amount_pct):
        raise CommercialStressUnavailable("STRESS_AMOUNT_INVALID: finite percentage required")
    if not 0 <= amount_pct <= 100:
        raise CommercialStressUnavailable("STRESS_AMOUNT_INVALID: magnitude must be between 0 and 100 percent")
    cfg = parse_config(raw)
    if cfg is None:
        raise CommercialStressUnavailable("STRESS_NO_CONTRACTS: explicit Revenue V2 contracts required")
    book = json.loads(cfg.canonical_json)
    changed = False
    for row in book["streams"]:
        kind = row["type"]
        if (shock in ("merchant_down", "merchant_up") and kind == "merchant" or
            shock == "ppa_down" and kind == "ppa"):
            factor = 1 + amount_pct / 100 if shock == "merchant_up" else 1 - amount_pct / 100
            row["price_eur_mwh"] *= factor
            if "price_curve" in row:
                for point in row["price_curve"]:
                    point["price_eur_mwh"] *= factor
            changed = True
    if shock == "ppa_expiry":
        if not any(r["type"] == "merchant" and r["volume_share"] is None for r in book["streams"]):
            raise CommercialStressUnavailable(
                "STRESS_EXPIRY_RESIDUAL_REQUIRED: no residual Merchant contract to absorb expired PPA")
        try:
            end = date.fromisoformat(expiry_date)
        except (ValueError, TypeError) as exc:
            raise CommercialStressUnavailable("STRESS_EXPIRY_DATE: exact ISO operating boundary required") from exc
        if end.isoformat() != expiry_date:
            raise CommercialStressUnavailable("STRESS_EXPIRY_DATE: exact ISO date required")
        affected = [r for r in book["streams"]
                    if r["type"] == "ppa" and r["start_date"] < expiry_date < r["end_date"]]
        if len(affected) != 1:
            raise CommercialStressUnavailable("STRESS_EXPIRY_AMBIGUOUS: expiry must identify exactly one active PPA")
        row = affected[0]
        # "Increased Merchant exposure" is real only if a residual Merchant
        # can take the freed volume throughout the previously contracted tail.
        residuals = [r for r in book["streams"]
                     if r["type"] == "merchant" and r["volume_share"] is None
                     and r["start_date"] <= expiry_date and r["end_date"] >= row["end_date"]]
        if len(residuals) != 1:
            raise CommercialStressUnavailable(
                "STRESS_EXPIRY_COVERAGE: residual Merchant must cover the complete exposed tail")
        row["end_date"] = expiry_date
        if "price_curve" in row:
            row["price_curve"] = [p for p in row["price_curve"] if p["period_start"] < expiry_date]
        changed = True
    if not changed:
        raise CommercialStressUnavailable("STRESS_NO_ELIGIBLE_CONTRACT: selected stress has no applicable contract")
    # Re-validate the same typed authority, preserving saved v1 unless a curve exists.
    return canonical_json(json.dumps(book, sort_keys=True, separators=(",", ":"), allow_nan=False))


def compare_commercial_cases(project_inputs, *, shock: str, amount_pct: float, expiry_date: str = "") -> dict:
    """Execute two independent canonical sensitivity runs; never persist either."""
    if not hasattr(project_inputs.revenue, "multistream_config_json"):
        raise CommercialStressUnavailable("STRESS_NO_CONTRACTS: inactive Revenue V2")
    from app.services.sensitivity_service import _run_once, KPI_DEFS
    book_raw = project_inputs.revenue.multistream_config_json
    variant = changed_book(book_raw, shock, amount_pct, expiry_date=expiry_date)
    stressed = replace(project_inputs, revenue=replace(
        project_inputs.revenue, multistream_config_json=variant))
    # Protected input authority: same complete upstream model, different explicit
    # prices/expiry only. Do NOT invoke legacy scalar sensitivity aliases.
    base = _run_once(project_inputs)
    outcome = _run_once(stressed)
    rows = []
    for key, label, unit in KPI_DEFS:
        original, changed = base.get(key), outcome.get(key)
        rows.append({
            "key": key, "label": label, "unit": unit,
            "base": original, "stress": changed,
            "delta": changed - original if original is not None and changed is not None else None,
        })
    return {
        "status": "COMPARISON",
        "shock": shock,
        "label": SUPPORTED[shock],
        "amount_pct": amount_pct,
        "expiry_date": expiry_date if shock == "ppa_expiry" else "",
        "metrics": rows,
        "bank_case_status": "UNAVAILABLE",
        "bank_case_reason": (
            "Lender-specific bank-price/discount/haircut case is not established; "
            "figures use FINCO's existing canonical financing methodology."
        ),
        "persistence": "NONE",
    }
