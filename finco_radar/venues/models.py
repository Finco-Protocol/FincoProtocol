"""Typed domain model for the Tokenized Markets venue registry.

Identity rules (hard):
  - identity is deterministic and exact: canonical underlying symbol,
    explicit ISIN where authoritative, exact chain + contract address,
    exact venue instrument identifier;
  - NO fuzzy matching, name similarity, or uncontrolled ticker fallback
    exists anywhere in this module;
  - missing metadata stays missing (None) — never invented, never zero;
  - cross-source disagreement is represented explicitly (CONFLICT) and
    excludes the ambiguous representation from canonical active use.

Source metadata is preserved per imported fact: external registry data
seeds the registry but never silently becomes FINCO-authored fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegistryStatus(str, Enum):
    """Deterministic registry-level availability state for a representation.

    ACTIVE       — reviewed, unambiguous, not quarantined.
    QUARANTINED  — exact chain + contract is on the deny/quarantine list
                   (e.g. a known impostor contract).
    CONFLICT     — two or more sources disagree on the exact identity for
                   the same (platform, symbol, network); excluded from
                   canonical active use until resolved.
    INACTIVE     — source marks the deployment inactive/delisted.
    """

    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    CONFLICT = "CONFLICT"
    INACTIVE = "INACTIVE"


class InstrumentType(str, Enum):
    TOKENIZED_EQUITY = "tokenized-equity"
    XSTOCK = "xstock"
    PERPETUAL = "perpetual"
    OTHER = "other"


def canonical_underlying_symbol(symbol: str) -> str:
    """Exact canonical underlying symbol: trimmed uppercase.

    This is normalization of an EXPLICIT identifier, not fuzzy matching:
    callers pass the authoritative underlyingSymbol / registry mapping and
    this only fixes case/whitespace.  There is no fallback path.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("underlying symbol is required")
    return symbol.strip().upper()


@dataclass(frozen=True)
class CanonicalUnderlying:
    """The real-world asset a tokenized representation references."""

    canonical_symbol: str            # exact, upper (e.g. NVDA)
    underlying_isin: str | None      # only when a source provides it
    underlying_name: str | None      # only when a source provides it
    sources: tuple[str, ...]         # which seed sources reference it

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "canonical_symbol",
            canonical_underlying_symbol(self.canonical_symbol))


@dataclass(frozen=True)
class Deployment:
    """One exact on-chain deployment of a representation."""

    network: str | None              # canonical network key (e.g. ethereum)
    chain_id: int | None             # EVM chain id where authoritative
    contract_address: str            # exact contract (lowercase)
    decimals: int | None             # only when authoritative

    def __post_init__(self) -> None:
        if not isinstance(self.contract_address, str) or not self.contract_address:
            raise ValueError("deployment contract_address is required")


@dataclass(frozen=True)
class RepresentationEntry:
    """One imported representation fact from one seed source.

    ``status`` is DERIVED by the registry (quarantine/conflict resolution),
    never trusted from the source row.
    """

    platform: str                    # issuer/platform: robinhood / ondo / xstocks / …
    representation_symbol: str       # exact venue-side symbol (e.g. NVDA, AAPLx)
    underlying_symbol: str | None    # exact underlying symbol when the source states it
    underlying_isin: str | None
    isin: str | None
    instrument_type: str
    name: str | None
    network: str | None              # canonical network key; None = venue w/o chain
    chain_id: int | None
    contract_address: str | None     # exact, lowercase; None = non-chain venue row
    decimals: int | None
    deployment_status: str | None    # source-native deployment status, if stated
    trading_halted: bool | None      # official trading-halt state, if stated
    deployments: tuple[Deployment, ...]  # embedded matrix (xStocks asset rows)
    source: str                      # seed source id (provenance)
    source_ref: str                  # repo@revision / URL provenance

    @property
    def identity_key(self) -> tuple:
        """Exact identity tuple (no fuzzy component anywhere)."""
        return (
            self.platform,
            self.representation_symbol.strip().upper(),
            self.network,
            self.contract_address,
        )


@dataclass(frozen=True)
class InstrumentIdentity:
    """The exact instrument a market observation is about."""

    canonical_asset_id: str          # exact canonical underlying symbol
    venue_id: str                    # platform/network key
    instrument_id: str               # exact symbol or 0x-contract identity
    instrument_type: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "canonical_asset_id",
            canonical_underlying_symbol(self.canonical_asset_id))
        if not isinstance(self.venue_id, str) or not self.venue_id:
            raise ValueError("venue_id is required")
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id is required")
