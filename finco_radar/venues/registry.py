"""Exact-identity venue registry over the committed seed.

Every lookup is exact:
  - underlying by canonical symbol;
  - representations by underlying / platform / network;
  - representation by exact chain + contract (embedded xStocks deployments
    are expanded into exact contract facts);
  - exact instrument resolution.

There is NO fuzzy resolver, NO name-similarity matching, NO ticker fallback.

Derived status semantics:
  - QUARANTINED beats everything: an exact (network|chain_id, contract) on
    the quarantine list can never resolve as a canonical representation;
  - CONFLICT: two or more sources assign DIFFERENT contracts to the same
    (platform, symbol, network) — both rows stay visible but are excluded
    from canonical active resolution until resolved;
  - INACTIVE: the source itself marks the deployment inactive;
  - otherwise ACTIVE.
"""
from __future__ import annotations

from dataclasses import dataclass

from finco_radar.venues.models import (
    CanonicalUnderlying,
    RegistryStatus,
    RepresentationEntry,
)
from finco_radar.venues.seed_loader import (
    load_registry_entries,
    parse_underlying,
)


def _norm_symbol(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


@dataclass(frozen=True)
class ResolvedRepresentation:
    """A representation row with its registry-derived status."""

    entry: RepresentationEntry
    status: RegistryStatus


class VenueRegistry:
    """Read-only exact-identity registry over the committed seed."""

    def __init__(
        self,
        underlyings: dict[str, CanonicalUnderlying],
        entries: list[RepresentationEntry],
        quarantines: list[dict],
    ) -> None:
        self._underlyings = dict(underlyings)
        self._entries = list(entries)

        # Quarantine keys: (network, contract) and (chain_id, contract).
        self._quarantine_by_network = {
            (q.get("network"), str(q.get("contract_address") or "").lower())
            for q in quarantines if q.get("contract_address")
        }
        self._quarantine_by_chain = {
            (q.get("chain_id"), str(q.get("contract_address") or "").lower())
            for q in quarantines if q.get("contract_address")
        }

        # Indexes (exact keys only).
        self._by_contract: dict[tuple[str | None, str], list[RepresentationEntry]] = {}
        self._by_chain_contract: dict[tuple[int | None, str], list[RepresentationEntry]] = {}
        self._by_underlying: dict[str, list[RepresentationEntry]] = {}
        self._by_platform_symbol: dict[tuple[str, str], list[RepresentationEntry]] = {}
        for entry in self._entries:
            if entry.contract_address:
                self._by_contract.setdefault(
                    (entry.network, entry.contract_address), []).append(entry)
                if entry.chain_id is not None:
                    self._by_chain_contract.setdefault(
                        (entry.chain_id, entry.contract_address), []).append(entry)
            symbol = _norm_symbol(entry.underlying_symbol)
            if symbol:
                self._by_underlying.setdefault(symbol, []).append(entry)
            self._by_platform_symbol.setdefault(
                (entry.platform, entry.representation_symbol.strip().upper()),
                []).append(entry)

        # Conflict detection: same (platform, symbol, network) from >=2
        # sources with DIFFERENT non-null contracts.  Quarantined entries
        # never participate — a known impostor must not turn the canonical
        # representation into a conflict.
        self._conflict_keys: set[tuple] = set()
        groups: dict[tuple, dict[str, set[str]]] = {}
        for entry in self._entries:
            if not entry.contract_address or not entry.network:
                continue
            if self.status_for(entry) is RegistryStatus.QUARANTINED:
                continue
            key = (entry.platform,
                   entry.representation_symbol.strip().upper(), entry.network)
            groups.setdefault(key, {}).setdefault(
                entry.source, set()).add(entry.contract_address)
        for key, by_source in groups.items():
            if len(by_source) > 1:
                contracts = set().union(*by_source.values())
                if len(contracts) > 1:
                    self._conflict_keys.add(key)

    # ── construction ──────────────────────────────────────────────────────
    @classmethod
    def load(cls, path=None) -> "VenueRegistry":
        from finco_radar.venues.seed_loader import DEFAULT_SEED_PATH
        underlyings, entries, quarantines = load_registry_entries(
            path or DEFAULT_SEED_PATH)
        return cls(underlyings, entries, quarantines)

    # ── status derivation ─────────────────────────────────────────────────
    def status_for(self, entry: RepresentationEntry) -> RegistryStatus:
        contract = entry.contract_address
        if contract:
            if (entry.network, contract) in self._quarantine_by_network:
                return RegistryStatus.QUARANTINED
            if (entry.chain_id, contract) in self._quarantine_by_chain:
                return RegistryStatus.QUARANTINED
            if (entry.platform, entry.representation_symbol.strip().upper(),
                    entry.network) in self._conflict_keys:
                return RegistryStatus.CONFLICT
        if (entry.deployment_status or "").lower() in ("inactive", "delisted"):
            return RegistryStatus.INACTIVE
        return RegistryStatus.ACTIVE

    def _canonical(self, entry: RepresentationEntry) -> ResolvedRepresentation | None:
        """Entry only when canonically usable (not quarantined/conflict)."""
        status = self.status_for(entry)
        if status in (RegistryStatus.QUARANTINED, RegistryStatus.CONFLICT):
            return None
        return ResolvedRepresentation(entry=entry, status=status)

    # ── exact lookups ─────────────────────────────────────────────────────
    def get_underlying(self, canonical_symbol: str) -> CanonicalUnderlying | None:
        from finco_radar.venues.models import canonical_underlying_symbol
        try:
            key = canonical_underlying_symbol(canonical_symbol)
        except ValueError:
            return None
        return self._underlyings.get(key)

    def representations_for_underlying(
            self, canonical_symbol: str) -> list[ResolvedRepresentation]:
        symbol = _norm_symbol(canonical_symbol)
        if not symbol:
            return []
        results = []
        for entry in self._by_underlying.get(symbol, []):
            resolved = self._canonical(entry)
            if resolved is not None:
                results.append(resolved)
        results.sort(key=lambda r: (
            r.entry.platform, r.entry.network or "", r.entry.representation_symbol))
        return results

    def representation_by_contract(
            self, *, network: str | None = None,
            chain_id: int | None = None,
            contract_address: str) -> list[tuple[RepresentationEntry, RegistryStatus]]:
        """ALL rows for an exact contract address (quarantined included —
        the caller must respect the returned status)."""
        contract = str(contract_address or "").lower()
        if not contract:
            return []
        entries: list[RepresentationEntry] = []
        if network is not None:
            entries.extend(self._by_contract.get((network, contract), []))
        elif chain_id is not None:
            entries.extend(self._by_chain_contract.get((chain_id, contract), []))
        else:
            entries.extend(self._by_contract.get((None, contract), []))
            for (cid, addr), group in self._by_chain_contract.items():
                if addr == contract and (chain_id is None or cid == chain_id):
                    entries.extend(e for e in group if e not in entries)
        # Embedded xStocks deployment matrices.
        for entry in self._entries:
            if entry.deployments and entry not in entries:
                if any(d.contract_address == contract
                       and (network is None or d.network == network)
                       for d in entry.deployments):
                    entries.append(entry)
        return [(entry, self.status_for(entry)) for entry in entries]

    def representations_for_venue(
            self, platform: str) -> list[ResolvedRepresentation]:
        results = []
        for (entry_platform, _symbol), group in self._by_platform_symbol.items():
            if entry_platform != platform:
                continue
            for entry in group:
                resolved = self._canonical(entry)
                if resolved is not None:
                    results.append(resolved)
        results.sort(key=lambda r: (
            r.entry.representation_symbol.strip().upper(),
            r.entry.network or ""))
        return results

    def resolve_exact_instrument(
            self, *, platform: str, symbol: str,
            network: str | None = None) -> ResolvedRepresentation | None:
        """Exact (platform, symbol[, network]) resolution.

        Returns None when the row is quarantined/conflicting/ambiguous —
        ambiguity NEVER silently resolves to one of the candidates.
        """
        symbol_key = _norm_symbol(symbol)
        if not symbol_key:
            return None
        candidates = [
            entry for entry in self._by_platform_symbol.get(
                (platform, symbol_key), [])
            if network is None or entry.network == network
        ]
        if not candidates:
            return None
        canonical = [resolved for resolved in
                     (self._canonical(entry) for entry in candidates)
                     if resolved is not None]
        # Multiple sources agreeing on the EXACT same identity are one
        # instrument, not ambiguity.  Collapse by full identity content
        # before the count check.
        distinct = {r.entry.identity_key: r for r in canonical}
        if len(distinct) != 1:
            return None  # zero or genuinely ambiguous: never guess
        return next(iter(distinct.values()))

    def underlying_for_contract(
            self, *, network: str | None = None,
            chain_id: int | None = None,
            contract_address: str) -> CanonicalUnderlying | None:
        """Exact contract → canonical underlying, ONLY when the contract is
        canonical-active (quarantined/conflicting contracts resolve None)."""
        for entry, status in self.representation_by_contract(
                network=network, chain_id=chain_id,
                contract_address=contract_address):
            if status is not RegistryStatus.ACTIVE:
                continue
            symbol = _norm_symbol(entry.underlying_symbol)
            if symbol:
                underlying = self._underlyings.get(symbol)
                if underlying is not None:
                    return underlying
                # Underlying seen only through this row: synthesize the
                # exact-symbol underlying (missing metadata stays missing).
                return parse_underlying({
                    "canonical_symbol": symbol, "sources": [entry.source]})
        return None

    def stats(self) -> dict:
        statuses: dict[str, int] = {}
        for entry in self._entries:
            statuses[self.status_for(entry).value] = (
                statuses.get(self.status_for(entry).value, 0) + 1)
        return {
            "entries": len(self._entries),
            "underlyings": len(self._underlyings),
            "quarantine_keys": len(self._quarantine_by_network),
            "statuses": statuses,
        }
