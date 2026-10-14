"""R4 read-only Tokenized Markets projections.

Canonical statistics belong exclusively to finco_radar.venues.relative_value.
This module selects, redacts and formats their already-authoritative results.
No new price, reference, persistence, normalization or acquisition authority.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from finco_radar.venues.relative_value import (
    compute_basis_distribution, compute_dislocation_persistence,
)

MAX_MONITORED_UNDERLYINGS = 60
FILTERS = frozenset({
    "all", "available", "stale", "unavailable", "dislocations",
    "premium", "discount", "distribution", "deepstate",
})
SORTS = frozenset({
    "priority", "basis_abs", "percentile", "duration", "symbol",
})


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def detail_relative_value(intelligence, gates, *, now: datetime | None = None) -> list[dict]:
    """Bounded, independently redacted history and dislocation projections.

    Dislocation can be available without history entitlement: points are used
    server-side by its canonical calculator but are never serialized here.
    """
    if intelligence is None or not gates.any_premium_allowed:
        return []
    now = now or datetime.now(timezone.utc)
    output = []
    for item in intelligence.representations[:MAX_MONITORED_UNDERLYINGS]:
        distribution = (asdict(compute_basis_distribution(item, now=now))
                        if gates.history.access_allowed else None)
        persistence = (asdict(compute_dislocation_persistence(item, now=now))
                       if gates.dislocation.access_allowed else None)
        output.append({
            "venue_id": item.venue_id,
            "instrument_id": item.instrument_id,
            "market_evidence_state": item.current_state,
            "distribution": distribution,
            "persistence": persistence,
        })
    return output


def enrich_landing_row(row: dict, view, intelligence, gates, *,
                       now: datetime | None = None, deepstate=None) -> dict:
    """One canonical asset, one deterministic representation; null never means zero."""
    now = now or datetime.now(timezone.utc)
    result = dict(row)
    histories = tuple(intelligence.representations) if intelligence is not None else ()
    matching = [h for h in histories
                if h.venue_id == row.get("best_venue")
                and h.instrument_id == row.get("best_instrument_id")]
    # A priced representation NEVER borrows another instrument's statistics.
    # With no currently priced representation, historical-only facts may still
    # use one deterministic exact registry history without claiming currency.
    history = matching[0] if matching else (
        sorted(histories, key=lambda h: (h.venue_id, h.instrument_id))[0]
        if histories and row.get("best_instrument_id") is None else None)
    selected = None
    if history is not None:
        selected = next((r for r in view.representations
                         if r.venue_id == history.venue_id and r.instrument_id == history.instrument_id), None)
    if selected is None:
        selected = next((r for r in view.representations
                         if r.venue_id == row.get("best_venue")
                         and r.instrument_id == row.get("best_instrument_id")), None)
    age_seconds = None
    if selected is not None and selected.source_timestamp:
        try:
            stamp = datetime.fromisoformat(selected.source_timestamp)
            if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                age = (now - stamp).total_seconds()
                if age >= 0:
                    age_seconds = int(age)
        except (ValueError, TypeError):
            pass
    result.update({
        "evidence_age_seconds": age_seconds,
        "current_basis_bps": None,
        "basis_direction": None,
        "evidence_state": selected.freshness_state if selected else row.get("overall_state", "UNAVAILABLE"),
        "source_timestamp": selected.source_timestamp if selected else None,
        "collected_at": selected.collected_at if selected else None,
        "venue_id": selected.venue_id if selected else row.get("best_venue"),
        "historical": None, "persistence": None,
        "deepstate_state": None,
        "current_dislocation": False,
    })
    if (selected is not None and selected.freshness_state == "AVAILABLE"
            and (history is None or history.current_state == "AVAILABLE")):
        basis = _decimal(selected.basis_bps)
        if basis is not None:
            result["current_basis_bps"] = str(basis)
            result["basis_direction"] = "PREMIUM" if basis > 0 else (
                "DISCOUNT" if basis < 0 else "PAR")
    if history is not None:
        if gates.history.access_allowed:
            result["historical"] = asdict(compute_basis_distribution(history, now=now))
        if gates.dislocation.access_allowed:
            state = asdict(compute_dislocation_persistence(history, now=now))
            result["persistence"] = state
            result["current_dislocation"] = (
                result["current_basis_bps"] is not None
                and state["state"] in ("PREMIUM_DISLOCATION", "DISCOUNT_DISLOCATION"))
    if deepstate is not None and gates.history.access_allowed and gates.dislocation.access_allowed:
        result["deepstate_state"] = deepstate.state
    return result


def overview(rows: list[dict], gates) -> dict:
    """Counts describe only the bounded displayed eligible universe."""
    return {
        "monitored": len(rows),
        "current_basis": sum(r["current_basis_bps"] is not None for r in rows),
        "distribution": (sum(bool(r["historical"] and
                                  r["historical"]["historical_median_basis_bps"] is not None)
                             for r in rows) if gates.history.access_allowed else None),
        "current_dislocations": (sum(r["current_dislocation"] for r in rows)
                                  if gates.dislocation.access_allowed else None),
        "stale_unavailable": sum(r["current_basis_bps"] is None for r in rows),
        "deepstate_historical": (
            sum(r["deepstate_state"] == "HISTORICAL_EXECUTION_PROVEN" for r in rows)
            if gates.history.access_allowed and gates.dislocation.access_allowed else None),
    }


def _bucket(row: dict) -> int:
    if row["current_dislocation"]:
        return 0
    if row["current_basis_bps"] is not None:
        return 1
    return 2


def sorted_filtered_rows(rows: list[dict], *, query: str = "",
                         evidence_filter: str = "all",
                         sort: str = "priority") -> list[dict]:
    """All filtering and sorting is server-side over already-redacted fields."""
    evidence_filter = evidence_filter if evidence_filter in FILTERS else "all"
    sort = sort if sort in SORTS else "priority"
    term = query.strip().casefold()[:48]
    out = []
    for row in rows:
        if term and term not in row["canonical_asset_id"].casefold() and term not in (
                row.get("underlying_name") or "").casefold():
            continue
        basis = _decimal(row["current_basis_bps"])
        historical = row["historical"]
        keep = {
            "all": True,
            "available": basis is not None,
            "stale": row["evidence_state"] == "STALE",
            "unavailable": basis is None,
            "dislocations": row["current_dislocation"],
            "premium": basis is not None and basis > 0,
            "discount": basis is not None and basis < 0,
            "distribution": historical is not None
                and historical["historical_median_basis_bps"] is not None,
            "deepstate": row["deepstate_state"] == "HISTORICAL_EXECUTION_PROVEN",
        }[evidence_filter]
        if keep:
            out.append(row)

    def _descending_nullable(value):
        val = _decimal(value)
        return (val is None, -(val if val is not None else Decimal(0)))

    def _key(row):
        basis = _decimal(row["current_basis_bps"])
        distribution = row["historical"] or {}
        persistence = row["persistence"] or {}
        symbol = (row["canonical_asset_id"], row.get("venue_id") or "")
        if sort == "symbol":
            return symbol
        if sort == "basis_abs":
            return (basis is None, -abs(basis) if basis is not None else 0, *symbol)
        if sort == "percentile":
            return (*_descending_nullable(distribution.get("current_basis_percentile")), *symbol)
        if sort == "duration":
            # An unknown beginning remains null and always sorts last.
            return (*_descending_nullable(persistence.get("duration_seconds")), *symbol)
        return (_bucket(row), -(abs(basis) if basis is not None and
                               row["current_dislocation"] else Decimal(0)), *symbol)

    return sorted(out, key=_key)
