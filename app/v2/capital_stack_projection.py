"""Capital Stack Workspace presentation (F3.6).  Read-only projection over existing authorities.

Nothing here calculates financing economics or writes state.  Rows are the typed F3 proposal
(``multisenior_config.build_view``); every status label is derived from persisted backend state
(saved scope entry + digest-bound activation + canonical freshness), never guessed in the browser.
Totals are plain sums of persisted typed numbers (working inputs) or of persisted Last Run ledgers.
"""
from __future__ import annotations

from typing import Any

from app.v2.financing_projection import UNAVAILABLE, label, number

DRAFT, SAVED, ACTIVE, UNSUPPORTED = "DRAFT", "SAVED PROPOSAL", "ACTIVE", "UNSUPPORTED"

_REPAYMENT = {"LEVEL_PRINCIPAL": "Level principal", "BULLET": "Bullet at maturity"}

# Static, backend-owned catalogue of structures the engine fails closed on (F3 acceptance report).
# These rows are never editable and never carry a commitment: they exist so a user can see why
# a structure is not executable instead of guessing.
UNSUPPORTED_STRUCTURES = (
    ("Junior / subordinated term loan", "Junior financing is not released for execution; no proposal is calculated."),
    ("Mezzanine / PIK instrument", "PIK and mezzanine accrual have no engine authority."),
    ("Third or further senior facility", "Exactly two Senior term loans are supported."),
    ("Floating-rate / benchmark facility", "Only fixed contractual cash interest is supported."),
    ("DSRA / debt service reserve facility", "Reserve integration is not released; reserve support must be NONE."),
    ("Active shareholder loan alongside instruments", "Residual funding is equity only in this mode."),
)


def _draws_total(instrument: dict) -> float:
    return sum(number(d.get("amount_keur")) or 0.0 for d in instrument.get("drawdowns") or ())


def build_capital_stack(f3: dict, freshness: Any, *, day_count: Any = None) -> dict:
    """Return the workspace model.  ``f3`` is the existing ``build_view`` dict."""
    if not f3 or not f3.get("available"):
        return {"available": False, "reason": (f3 or {}).get("reason") or "Financing instruments are unavailable."}
    entry = f3["entry"]
    saved = f3["scope"] in (f3.get("state") or {}).get("scopes", {})
    active = bool(f3.get("active"))
    status = ACTIVE if active else SAVED if saved else DRAFT
    run_state = getattr(getattr(freshness, "state", None), "value", None) or "NOT_RUN"
    rows = []
    for i in entry["proposal"]["instruments"]:
        fees = {f.get("kind"): number(f.get("rate")) or 0.0 for f in i.get("fees") or ()}
        rows.append({
            "instrument_id": i["instrument_id"], "name": i["name"], "type": "Senior term loan",
            "rank": "Senior · pari passu", "commitment_keur": number(i["commitment_keur"]) or 0.0,
            "currency": "EUR", "rate_type": "Fixed", "rate_pct": (number(i["interest"].get("fixed_rate")) or 0.0) * 100,
            "day_count": label(day_count) if day_count is not None else UNAVAILABLE,
            "repayment_mode": i["repayment"]["mode"], "repayment": _REPAYMENT.get(i["repayment"]["mode"], i["repayment"]["mode"]),
            "grace_months": i["repayment"]["grace_months"], "maturity_date": i["repayment"]["maturity_date"],
            "draws": [{"date": d["draw_date"], "amount_keur": number(d["amount_keur"]) or 0.0} for d in i.get("drawdowns") or ()],
            "draws_total_keur": _draws_total(i),
            "upfront_pct": fees.get("UPFRONT", 0.0) * 100, "commitment_fee_pct": fees.get("COMMITMENT", 0.0) * 100,
            "status": status, "executable": active,
        })
    working = {
        "senior_commitments_keur": sum(r["commitment_keur"] for r in rows),
        "junior_commitments_keur": 0.0,
        "scheduled_draws_keur": sum(r["draws_total_keur"] for r in rows),
        "reconciled": all(abs(r["draws_total_keur"] - r["commitment_keur"]) <= 1e-6 for r in rows),
        "facility_count": len(rows),
    }
    last = None
    schedules = f3.get("last_run")
    if schedules and active:
        by_id = {s["instrument_id"]: s for s in schedules}
        last = {
            "facilities": [{
                "instrument_id": s["instrument_id"], "commitment_keur": s["commitment_keur"],
                "idc_keur": sum(s["construction_idc_keur"]), "fees_keur": sum(s["upfront_fees_keur"]) + sum(s["construction_commitment_fees_keur"]),
                "operating_interest_keur": sum(s["interest_keur"]), "principal_keur": sum(s["principal_keur"]),
                "final_period": s["period_indices"][-1] if s["period_indices"] else None,
            } for s in by_id.values()],
        }
        last["total_commitment_keur"] = sum(f["commitment_keur"] for f in last["facilities"])
        last["total_idc_keur"] = sum(f["idc_keur"] for f in last["facilities"])
        last["total_operating_interest_keur"] = sum(f["operating_interest_keur"] for f in last["facilities"])
    return {
        "available": True, "status": status, "scope": f3["scope"], "rows": rows, "working": working,
        "last_run": last, "run_state": run_state,
        "last_run_is_current": run_state == "CURRENT",
        "last_run_label": {"CURRENT": "LAST RUN · CURRENT", "STALE": "LAST RUN · STALE (inputs changed since the run)"}.get(run_state, "NOT RUN"),
        "unsupported": [{"name": n, "reason": r, "status": UNSUPPORTED} for n, r in UNSUPPORTED_STRUCTURES],
        "debt_service_priority": "Pari passu between Senior facilities; no subordination configured.",
        "release_enabled": bool(f3.get("release_enabled")),
    }
