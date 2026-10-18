"""Physical-energy ledger over committed Revenue contract evidence (RC-7 / C1).

A pure, read-only projection of the per-period contract evidence a Run already persisted (``revenue_multistream_audit``).  It owns no price,
volume or settlement arithmetic: it only classifies the MWh the Run itself allocated, so that one MWh is never counted in two places.

Classes (never merged):
* ``contracted_mwh``   - physical energy sold under PPA streams;
* ``merchant_mwh``     - physical energy sold at the merchant price (residual or explicit share);
* ``unallocated_mwh``  - generated energy no active contract or merchant stream took (earns nothing; shown, never hidden);
* ``cfd_overlay_mwh``  - financially settled notional volume.  It is NOT physical energy and is never added to the physical total;
* ``non_energy``       - Revenue V3 products (MW / certificates / currency), carried in their own units and never added to MWh.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

SCHEMA = "finco-contract-energy-ledger-v1"
CONSERVED = "CONSERVED"
UNALLOCATED = "UNALLOCATED_ENERGY"
NOT_CONSERVED = "NOT_CONSERVED"
UNAVAILABLE = "UNAVAILABLE"
TOLERANCE_MWH = 1e-6        # absolute; the engine's own residual on the largest reference period is ~1e-11 MWh
PHYSICAL = {"ppa": "contracted_mwh", "merchant": "merchant_mwh"}


def _num(value: Any):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def build_contract_energy_ledger(audit: Iterable[Mapping[str, Any]] | None,
                                 production_mwh_by_period: Mapping[int, float] | None = None) -> dict:
    """Ledger of the Last Run.  ``audit`` is ``runtime_summary['revenue_multistream_audit']``.

    ``production_mwh_by_period`` (optional, Run-bound physical production) turns the reconstructed physical total into an independent
    cross-check; without it production is reconstructed from the allocation and is labelled so.
    """
    if not isinstance(audit, (list, tuple)) or not audit:
        return {"schema": SCHEMA, "status": UNAVAILABLE, "reason": "NO_COMMITTED_CONTRACT_EVIDENCE", "periods": []}
    periods, totals = [], dict(contracted_mwh=0.0, merchant_mwh=0.0, unallocated_mwh=0.0, cfd_overlay_mwh=0.0, physical_mwh=0.0)
    worst, status = 0.0, CONSERVED
    for entry in audit:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("streams"), list):
            return {"schema": SCHEMA, "status": UNAVAILABLE, "reason": "MALFORMED_CONTRACT_EVIDENCE", "periods": []}
        row = dict(period_index=entry.get("period_index"), contracted_mwh=0.0, merchant_mwh=0.0, cfd_overlay_mwh=0.0)
        for stream in entry["streams"]:
            quantity = _num(stream.get("quantity_mwh")) if isinstance(stream, Mapping) else None
            if quantity is None or quantity < 0:
                return {"schema": SCHEMA, "status": UNAVAILABLE, "reason": "INVALID_STREAM_QUANTITY", "periods": []}
            kind = stream.get("type")
            if kind in PHYSICAL:
                row[PHYSICAL[kind]] += quantity
            elif kind == "cfd":
                row["cfd_overlay_mwh"] += quantity
        unallocated = _num(entry.get("unallocated_generation_mwh"))
        if unallocated is None:
            return {"schema": SCHEMA, "status": UNAVAILABLE, "reason": "UNALLOCATED_ENERGY_NOT_RECORDED", "periods": []}
        unallocated = 0.0 if abs(unallocated) <= TOLERANCE_MWH else unallocated
        row["unallocated_mwh"] = unallocated
        row["physical_mwh"] = row["contracted_mwh"] + row["merchant_mwh"] + unallocated
        if production_mwh_by_period is not None:
            produced = _num(production_mwh_by_period.get(entry.get("period_index")))
            if produced is None:
                return {"schema": SCHEMA, "status": UNAVAILABLE, "reason": "PRODUCTION_NOT_RECORDED_FOR_PERIOD", "periods": []}
            row["production_mwh"] = produced
            row["residual_mwh"] = produced - row["physical_mwh"]
            worst = max(worst, abs(row["residual_mwh"]))
            if abs(row["residual_mwh"]) > TOLERANCE_MWH:
                status = NOT_CONSERVED
        if status == CONSERVED and unallocated > TOLERANCE_MWH:
            status = UNALLOCATED
        for key in totals:
            totals[key] += row[key]
        periods.append(row)
    return {"schema": SCHEMA, "status": status, "basis": "run_production" if production_mwh_by_period is not None else "reconstructed_from_allocation",
            "periods": periods, "totals": totals, "max_abs_residual_mwh": worst,
            "note": "CfD overlay volume is financially settled notional energy and is excluded from the physical total; non-energy products carry their own units."}


__all__ = ["SCHEMA", "CONSERVED", "UNALLOCATED", "NOT_CONSERVED", "UNAVAILABLE", "build_contract_energy_ledger"]
