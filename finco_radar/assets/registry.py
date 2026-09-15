"""Fail-closed canonical asset registry and official reference binding."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    RegistryConflictError,
    RegistryLookupError,
    RegistrySourceError,
    normalize_asset_uid,
    normalize_symbol,
)


@dataclass(frozen=True)
class RegistrySnapshot:
    """Immutable registry view; intentionally unhashable because it owns indexed mappings."""

    __hash__ = None

    source: str
    observed_at: datetime
    assets: tuple[CanonicalAssetRecord, ...]
    _by_key: Mapping[AssetKey, CanonicalAssetRecord] = field(
        init=False, repr=False, compare=False
    )
    _by_uid: Mapping[str, CanonicalAssetRecord] = field(
        init=False, repr=False, compare=False
    )
    _by_symbol: Mapping[str, tuple[CanonicalAssetRecord, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise RegistrySourceError("registry source must be non-empty")
        by_key: dict[AssetKey, CanonicalAssetRecord] = {}
        by_uid: dict[str, CanonicalAssetRecord] = {}
        by_symbol_lists: dict[str, list[CanonicalAssetRecord]] = {}
        for asset in self.assets:
            if asset.asset_uid in by_uid:
                raise RegistryConflictError(f"duplicate asset uid: {asset.asset_uid}")
            by_uid[asset.asset_uid] = asset
            by_symbol_lists.setdefault(asset.token_symbol, []).append(asset)
            for key in asset.deployments:
                prior = by_key.get(key)
                if prior is not None:
                    raise RegistryConflictError(
                        f"canonical deployment collision {key.canonical_id}: "
                        f"{prior.asset_uid} vs {asset.asset_uid}"
                    )
                by_key[key] = asset
        object.__setattr__(self, "_by_key", by_key)
        object.__setattr__(self, "_by_uid", by_uid)
        object.__setattr__(
            self,
            "_by_symbol",
            {symbol: tuple(records) for symbol, records in by_symbol_lists.items()},
        )

    @property
    def canonical_key_count(self) -> int:
        return len(self._by_key)

    @property
    def asset_uid_count(self) -> int:
        return len(self._by_uid)

    def get_by_key(self, key: AssetKey) -> CanonicalAssetRecord | None:
        return self._by_key.get(key)

    def require_by_key(self, key: AssetKey) -> CanonicalAssetRecord:
        asset = self.get_by_key(key)
        if asset is None:
            raise RegistryLookupError(f"canonical asset not found: {key.canonical_id}")
        return asset

    def get_by_uid(self, asset_uid: str) -> CanonicalAssetRecord | None:
        return self._by_uid.get(normalize_asset_uid(asset_uid))

    def find_by_symbol(self, symbol: str) -> tuple[CanonicalAssetRecord, ...]:
        """Discovery only. A symbol is never a canonical identity."""
        return self._by_symbol.get(normalize_symbol(symbol), ())

    def require_unique_symbol(self, symbol: str) -> CanonicalAssetRecord:
        matches = self.find_by_symbol(symbol)
        if len(matches) != 1:
            raise RegistryLookupError(
                f"symbol discovery is not unique for {symbol!r}: {len(matches)} matches"
            )
        return matches[0]

    def reference_binding(self, key: AssetKey) -> ReferenceBinding:
        asset = self.require_by_key(key)
        return ReferenceBinding(
            asset_uid=asset.asset_uid,
            asset_key=key,
            reference_symbol=asset.token_symbol,
        )

    def resolve_official_identity(
        self,
        *,
        asset_uid: str,
        deployments: tuple[AssetKey, ...],
    ) -> CanonicalAssetRecord:
        """Re-validate an official-registry UID against exact canonical deployments."""
        uid = normalize_asset_uid(asset_uid)
        asset = self._by_uid.get(uid)
        if asset is None:
            raise RegistryLookupError(f"official uid is absent from registry: {uid}")
        official_keys = set(deployments)
        if not official_keys.intersection(asset.deployments):
            raise RegistryLookupError("official row uid does not match any canonical deployment")
        for key in official_keys:
            owner = self._by_key.get(key)
            if owner is not None and owner.asset_uid != uid:
                raise RegistryConflictError(
                    f"official row mixes uid {uid} with deployment owned by {owner.asset_uid}"
                )
        return asset


def validate_reference_price_payload(
    binding: ReferenceBinding,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the one quote row whose deployment exactly matches the bound identity."""
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise RegistrySourceError("reference payload quotes must be a list")
    exact_rows: list[Mapping[str, Any]] = []
    for row in quotes:
        if not isinstance(row, Mapping):
            raise RegistrySourceError("reference quote row must be an object")
        deployments = row.get("deployments")
        if not isinstance(deployments, list):
            raise RegistrySourceError("reference quote deployments must be a list")
        row_keys: list[AssetKey] = []
        for deployment in deployments:
            if not isinstance(deployment, Mapping):
                raise RegistrySourceError("reference deployment must be an object")
            try:
                row_keys.append(
                    AssetKey(
                        chain_id=int(deployment["chainId"]),
                        contract_address=str(deployment["contractAddress"]),
                    )
                )
            except RegistrySourceError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistrySourceError("invalid deployment in reference payload") from exc
        if len(set(row_keys)) != len(row_keys):
            raise RegistrySourceError("reference quote contains duplicate deployment keys")
        if binding.asset_key in row_keys:
            symbol = normalize_symbol(
                str(row.get("tokenSymbol") or ""), field_name="reference tokenSymbol"
            )
            if symbol != binding.reference_symbol:
                raise RegistrySourceError(
                    "reference deployment matches canonical key but symbol metadata conflicts"
                )
            exact_rows.append(row)
    if len(exact_rows) != 1:
        raise RegistryLookupError(
            f"reference payload has {len(exact_rows)} exact rows for {binding.asset_key.canonical_id}"
        )
    return exact_rows[0]
