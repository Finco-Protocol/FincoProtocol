"""Tokenized Markets — operational product state, coverage counts and public identity eligibility.

Presentation-layer read model over the EXISTING authorities only (no second market authority):

  * ``VenueRegistry``                — identity catalog (third-party seeded; research identity source)
  * ``TokenizedCollectorHealthStore``— whether the reviewed collector has ever run / is healthy
  * ``VenueMarketStore``             — persisted observations (the only market evidence)
  * reviewed R-LIVE exact AssetKeys  — the live-collector universe (via the collector's own target rule)

Code capability and operational data availability are separate facts. A UI route, an identity registry or
collector code never imply a functioning live product: the operational state below is derived from what is
actually persisted. Nothing here invents, infers or corrects market evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*([.\-][A-Z0-9]+)?$")


class TokenizedOperationalState(str, Enum):
    IDENTITY_ONLY = "IDENTITY_ONLY"                    # no reviewed live-collector universe at all
    COLLECTOR_NOT_STARTED = "COLLECTOR_NOT_STARTED"    # collector health NEVER_RUN
    COLLECTOR_UNHEALTHY = "COLLECTOR_UNHEALTHY"        # ran, but never succeeded or currently unhealthy
    NO_PRICED_OBSERVATIONS = "NO_PRICED_OBSERVATIONS"  # collector fine, store holds nothing priced
    PARTIAL_LIVE = "PARTIAL_LIVE"                      # some, not all, eligible assets priced / degraded
    LIVE = "LIVE"                                      # every eligible asset priced now, collector healthy


#: states in which the surface may present itself as an operating market-intelligence product
OPERATING_STATES = frozenset({TokenizedOperationalState.PARTIAL_LIVE, TokenizedOperationalState.LIVE})

# User-facing state grammar. Only the state itself decides the wording: a collector that has run (even
# unhealthily) is never described as "not active", and only a never-run collector is a preview.
STATE_LABELS = {
    TokenizedOperationalState.IDENTITY_ONLY: "Preview · identity only",
    TokenizedOperationalState.COLLECTOR_NOT_STARTED: "Preview · collection has not started",
    TokenizedOperationalState.COLLECTOR_UNHEALTHY: "Collecting · current source evidence unavailable",
    TokenizedOperationalState.NO_PRICED_OBSERVATIONS: "Collecting · no fresh priced observations yet",
    TokenizedOperationalState.PARTIAL_LIVE: "Partially live",
    TokenizedOperationalState.LIVE: "Live",
}

STATE_TONES = {
    TokenizedOperationalState.IDENTITY_ONLY: "muted",
    TokenizedOperationalState.COLLECTOR_NOT_STARTED: "muted",
    TokenizedOperationalState.COLLECTOR_UNHEALTHY: "warn",
    TokenizedOperationalState.NO_PRICED_OBSERVATIONS: "warn",
    TokenizedOperationalState.PARTIAL_LIVE: "ok",
    TokenizedOperationalState.LIVE: "ok",
}

STATE_HEADLINES = {
    TokenizedOperationalState.IDENTITY_ONLY:
        "No reviewed live-collection universe is active; only research identities are available.",
    TokenizedOperationalState.COLLECTOR_NOT_STARTED:
        "The reviewed universe is ready, but the collector has not run yet.",
    TokenizedOperationalState.COLLECTOR_UNHEALTHY:
        "The collector is running, but its current source evidence is unavailable or unhealthy.",
    TokenizedOperationalState.NO_PRICED_OBSERVATIONS:
        "The collector is running, but no fresh priced observations are stored yet.",
    TokenizedOperationalState.PARTIAL_LIVE:
        "Only part of the reviewed universe currently has fresh priced evidence.",
    TokenizedOperationalState.LIVE:
        "Every reviewed asset currently has fresh priced evidence.",
}


@dataclass(frozen=True)
class TokenizedCoverage:
    identity_catalog: int      # underlyings with at least one active exact representation (research identity)
    live_eligible: int         # reviewed exact authorities the live collector can actually collect
    priced_now: int            # primary-universe assets with a fresh priced observation
    history_available: int     # primary-universe assets with persisted history
    excluded_identities: int   # catalog identities failing the public eligibility rule (audit-only)


@dataclass(frozen=True)
class TokenizedOperationalView:
    state: TokenizedOperationalState
    coverage: TokenizedCoverage
    headline: str
    collector_outcome: str
    collector_failure_reason: str | None

    @property
    def operating(self) -> bool:
        return self.state in OPERATING_STATES

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]

    @property
    def tone(self) -> str:
        return STATE_TONES[self.state]


# ── public identity eligibility ──────────────────────────────────────────────────────────────────
def _contract_groups(registry) -> dict[tuple, list]:
    groups: dict[tuple, list] = {}
    for entry in registry._entries:
        if entry.contract_address:
            key = (entry.chain_id if entry.chain_id is not None else entry.network,
                   entry.contract_address.lower())
            groups.setdefault(key, []).append(entry)
        for deployment in entry.deployments:
            key = (deployment.chain_id if deployment.chain_id is not None else deployment.network,
                   deployment.contract_address.lower())
            groups.setdefault(key, []).append(entry)
    return groups


def _conflicted_contracts(registry) -> dict[tuple, str]:
    """Exact chain+contract keys whose registry rows disagree on representation type or underlying."""
    conflicted: dict[tuple, str] = {}
    for key, entries in _contract_groups(registry).items():
        if len(entries) < 2:
            continue
        if len({(e.underlying_symbol or "").strip().upper() for e in entries}) > 1:
            conflicted[key] = "UNDERLYING_CONFLICT_SAME_CONTRACT"
        elif len({e.instrument_type for e in entries}) > 1:
            conflicted[key] = "REPRESENTATION_TYPE_CONFLICT_SAME_CONTRACT"
    return conflicted


def classify_identity_catalog(registry) -> tuple[list[dict], list[dict]]:
    """Split the seeded identity catalog into (publicly eligible rows, excluded rows with reasons).

    Excluded rows are never deleted: they stay inspectable through the audit view. No fuzzy correction,
    no ticker/name inference, third-party provenance is preserved on the row.
    """
    from app.radar_ui.tokenized_composition import list_supported_underlyings

    conflicted = _conflicted_contracts(registry)
    entries_by_symbol: dict[str, list] = {}
    for entry in registry._entries:
        if entry.underlying_symbol:
            entries_by_symbol.setdefault(entry.underlying_symbol.strip().upper(), []).append(entry)

    def clean_representations(symbol: str):
        clean = []
        for resolved in registry.representations_for_underlying(symbol):
            entry = resolved.entry
            keys = [((entry.chain_id if entry.chain_id is not None else entry.network),
                     (entry.contract_address or "").lower())] if entry.contract_address else []
            keys += [((d.chain_id if d.chain_id is not None else d.network), d.contract_address.lower())
                     for d in entry.deployments]
            if not any(key in conflicted for key in keys):
                clean.append(resolved)
        return clean

    included, excluded = [], []
    supported = {row["canonical_asset_id"]: row for row in list_supported_underlyings(registry)}
    for symbol in sorted(registry._underlyings):
        reason = None
        if symbol.isdigit():
            reason = "NUMERIC_ONLY_SYMBOL"
        elif not _SYMBOL.match(symbol):
            reason = "MALFORMED_SYMBOL"
        elif symbol not in supported:
            statuses = {registry.status_for(e).value for e in entries_by_symbol.get(symbol, [])}
            reason = ("REGISTRY_CONFLICT_OR_QUARANTINE" if statuses & {"CONFLICT", "QUARANTINED"}
                      else "ONLY_INACTIVE_REPRESENTATIONS" if statuses
                      else "UNRESOLVED_IDENTITY")
        else:
            resolved = registry.representations_for_underlying(symbol)
            clean = clean_representations(symbol)
            if resolved and not clean:
                keys = [k for k in conflicted
                        if any(k == ((r.entry.chain_id if r.entry.chain_id is not None else r.entry.network),
                                     (r.entry.contract_address or "").lower()) for r in resolved)]
                reason = conflicted[keys[0]] if keys else "REPRESENTATION_TYPE_CONFLICT_SAME_CONTRACT"
        row = supported.get(symbol) or {
            "canonical_asset_id": symbol, "underlying_name": registry._underlyings[symbol].underlying_name,
            "venues": [], "representation_count": 0}
        if reason is None:
            included.append(row)
        else:
            excluded.append({**row, "exclusion_reason": reason,
                             "platforms": sorted({e.platform for e in entries_by_symbol.get(symbol, [])}),
                             "sources": list(registry._underlyings[symbol].sources)})
    return included, excluded


# ── market evidence ──────────────────────────────────────────────────────────────────────────────
def symbols_with_market_evidence(registry, store) -> set[str]:
    """Underlyings with at least one persisted priced observation (exact store rows only)."""
    if store is None:
        return set()
    venues = sorted({(entry.network or entry.platform) for entry in registry._entries})
    symbols: set[str] = set()
    for venue in venues:
        try:
            for observation in store.list_latest_by_venue(venue):
                if observation.price is not None:
                    symbols.add(str(observation.canonical_asset_id).strip().upper())
        except Exception:
            continue
    return symbols


def live_eligible_ids(registry) -> tuple[str, ...]:
    """Reviewed exact R-LIVE AssetKeys the live collector can collect (the collector's own target rule)."""
    from app.radar_rwa.tokenized_collect import _target_ids
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    return _target_ids(registry, max_assets=max(len(APPROVED_BY_CANONICAL_ID), 1))


def derive_state(*, live_eligible: int, collector: Any, priced_now: int) -> TokenizedOperationalState:
    """Pure state derivation. Order matters: each gate must pass before a stronger claim is possible."""
    S = TokenizedOperationalState
    if live_eligible <= 0:
        return S.IDENTITY_ONLY
    outcome = str(getattr(collector, "outcome", "NEVER_RUN"))
    if outcome == "NEVER_RUN":
        return S.COLLECTOR_NOT_STARTED
    if getattr(collector, "last_success_at", None) is None \
            or str(getattr(collector, "health_state", "UNHEALTHY")) == "UNHEALTHY":
        return S.COLLECTOR_UNHEALTHY
    if priced_now <= 0:
        return S.NO_PRICED_OBSERVATIONS
    if priced_now < live_eligible or str(getattr(collector, "health_state", "")) != "HEALTHY":
        return S.PARTIAL_LIVE
    return S.LIVE


def build_operational_view(registry, store, collector, *, now: datetime | None = None,
                           primary_views: list | None = None, catalog_count: int | None = None,
                           excluded_count: int = 0, eligible_ids: tuple[str, ...] | None = None
                           ) -> TokenizedOperationalView:
    """Combine registry, store and collector health into the truthful operational view.

    ``primary_views`` are the already-composed read-model views for the primary universe (so priced and
    history counts use the same canonical states the table shows).
    """
    eligible = live_eligible_ids(registry) if eligible_ids is None else eligible_ids
    views = primary_views or []
    priced_now = 0
    history = 0
    for view in views:
        if any(rep.has_market_data and rep.price is not None
               and rep.freshness_state in ("AVAILABLE", "FRESH") for rep in view.representations):
            priced_now += 1
        if view.history_available:
            history += 1
    state = derive_state(live_eligible=len(eligible), collector=collector, priced_now=priced_now)
    coverage = TokenizedCoverage(
        identity_catalog=catalog_count if catalog_count is not None else 0,
        live_eligible=len(eligible), priced_now=priced_now, history_available=history,
        excluded_identities=excluded_count)
    return TokenizedOperationalView(
        state=state, coverage=coverage, headline=STATE_HEADLINES[state],
        collector_outcome=str(getattr(collector, "outcome", "NEVER_RUN")),
        collector_failure_reason=getattr(collector, "failure_reason", None))


def representation_conflicts(registry, *, limit: int = 500) -> list[dict]:
    """Exact chain+contract keys whose registry rows disagree (audit view; evidence is never deleted)."""
    rows = []
    for key, reason in sorted(_conflicted_contracts(registry).items(), key=lambda kv: str(kv[0])):
        entries = _contract_groups(registry)[key]
        rows.append({
            "chain": key[0], "contract": key[1], "reason": reason,
            "representations": sorted({(e.platform, e.representation_symbol, e.instrument_type,
                                        (e.underlying_symbol or "").upper()) for e in entries}),
        })
        if len(rows) >= limit:
            break
    return rows


def resolved_taxonomy_disagreements(registry) -> list[dict]:
    """Exact representations that several sources agreed on but classified differently.

    The disagreement is descriptive (instrument_type is not identity-defining); the economic identity is one
    row, and every source's own assertion stays inspectable here (audit view). Nothing is deleted.
    """
    rows = []
    for entry in registry._entries:
        types = {a.instrument_type for a in entry.source_assertions}
        if len(types) > 1:
            rows.append({
                "chain": entry.chain_id if entry.chain_id is not None else entry.network,
                "contract": entry.contract_address,
                "representation": entry.representation_symbol,
                "resolved_instrument_type": entry.instrument_type,
                "assertions": [(a.source, a.source_ref, a.instrument_type) for a in entry.source_assertions],
            })
    return sorted(rows, key=lambda r: (str(r["chain"]), r["contract"] or ""))
