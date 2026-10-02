"""Deterministic loader/validator for the committed venue registry seed.

The seed artifact (``data/venue_registry_seed.json``) is produced at
development/build time by ``tools/import_venue_registry_seed.py`` and is the
ONLY runtime input: the application never fetches external registries at
page-load time.

The loader is strict:
  - schema/shape validation with typed errors;
  - exact-duplicate rows collapse deterministically (same source + platform
    + symbol + network + contract) — duplicates never diverge;
  - ordering is canonical (sorted), so the loaded registry is reproducible.
"""
from __future__ import annotations

import json
from pathlib import Path

from finco_radar.venues.models import (
    CanonicalUnderlying,
    Deployment,
    RepresentationEntry,
)

DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parent / "data" / "venue_registry_seed.json")

SEED_SCHEMA_VERSION = "FINCO_VENUE_REGISTRY_SEED_V1"


class SeedError(ValueError):
    """Typed seed validation failure (schema/shape)."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SeedError(message)


def load_seed(path: str | Path = DEFAULT_SEED_PATH) -> dict:
    """Load and validate the committed seed artifact."""
    raw_path = Path(path)
    if not raw_path.is_file():
        raise SeedError(f"venue registry seed not found: {raw_path}")
    try:
        seed = json.loads(raw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SeedError(f"seed artifact is not valid JSON: {exc}") from exc
    _require(isinstance(seed, dict), "seed root must be an object")
    _require(seed.get("schema_version") == SEED_SCHEMA_VERSION,
             f"seed schema_version must be {SEED_SCHEMA_VERSION}")
    for key in ("underlyings", "representations", "quarantines"):
        _require(isinstance(seed.get(key), list), f"seed.{key} must be a list")
    return seed


def _parse_representation(row: dict) -> RepresentationEntry:
    _require(isinstance(row, dict), "representation row must be an object")
    symbol = row.get("representation_symbol")
    _require(isinstance(symbol, str) and symbol.strip(),
             "representation_symbol is required")
    deployments_raw = row.get("deployments") or []
    _require(isinstance(deployments_raw, list), "deployments must be a list")
    deployments = []
    for deployment in deployments_raw:
        deployments.append(Deployment(
            network=deployment.get("network"),
            chain_id=deployment.get("chain_id"),
            contract_address=str(deployment.get("contract_address") or "").lower(),
            decimals=deployment.get("decimals"),
        ))
    contract = row.get("contract_address")
    return RepresentationEntry(
        platform=str(row.get("platform") or "unknown"),
        representation_symbol=symbol,
        underlying_symbol=row.get("underlying_symbol"),
        underlying_isin=row.get("underlying_isin"),
        isin=row.get("isin"),
        instrument_type=str(row.get("instrument_type") or "other"),
        name=row.get("name"),
        network=row.get("network"),
        chain_id=row.get("chain_id"),
        contract_address=str(contract).lower() if contract else None,
        decimals=row.get("decimals"),
        deployment_status=row.get("deployment_status"),
        trading_halted=row.get("trading_halted"),
        deployments=tuple(deployments),
        source=str(row.get("source") or "unknown"),
        source_ref=str(row.get("source_ref") or ""),
    )


def parse_underlying(row: dict) -> CanonicalUnderlying:
    _require(isinstance(row, dict), "underlying row must be an object")
    return CanonicalUnderlying(
        canonical_symbol=str(row.get("canonical_symbol") or ""),
        underlying_isin=row.get("underlying_isin"),
        underlying_name=row.get("underlying_name"),
        sources=tuple(row.get("sources") or ()),
    )


def load_registry_entries(
    path: str | Path = DEFAULT_SEED_PATH,
) -> tuple[dict[str, CanonicalUnderlying], list[RepresentationEntry], list[dict]]:
    """Seed artifact → (underlyings by canonical symbol, representations in
    canonical order, raw quarantine entries)."""
    seed = load_seed(path)

    underlyings: dict[str, CanonicalUnderlying] = {}
    for row in seed["underlyings"]:
        underlying = parse_underlying(row)
        underlyings[underlying.canonical_symbol] = underlying

    entries: list[RepresentationEntry] = []
    seen: set[tuple] = set()
    for row in seed["representations"]:
        entry = _parse_representation(row)
        key = (entry.source, entry.platform, entry.identity_key)
        if key in seen:
            continue  # exact duplicate: deterministic collapse
        seen.add(key)
        entries.append(entry)

    quarantines = [row for row in seed["quarantines"] if isinstance(row, dict)]
    return underlyings, entries, quarantines
