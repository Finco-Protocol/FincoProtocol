"""Typed canonical asset-registry contracts for FINCO Radar R1."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ASSET_UID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class RegistryConflictError(ValueError):
    """Raised when source rows violate canonical identity uniqueness."""


class RegistryLookupError(LookupError):
    """Raised when an external mapping cannot resolve unambiguously."""


class RegistrySourceError(ValueError):
    """Raised when upstream registry/reference payloads are malformed."""


def normalize_evm_address(value: str, *, field_name: str = "contract_address") -> str:
    address = value.strip()
    if not _EVM_ADDRESS_RE.fullmatch(address):
        raise RegistrySourceError(f"{field_name} must be a 20-byte EVM hex address")
    return address.lower()


def normalize_asset_uid(value: str) -> str:
    uid = value.strip()
    if not _ASSET_UID_RE.fullmatch(uid):
        raise RegistrySourceError("asset_uid must be a 32-byte 0x-prefixed hex value")
    return uid.lower()


class RegistryAssetStatus(str, Enum):
    UNSPECIFIED = "ASSET_STATUS_UNSPECIFIED"
    ACTIVE = "ASSET_STATUS_ACTIVE"
    INACTIVE = "ASSET_STATUS_INACTIVE"


@dataclass(frozen=True, order=True)
class AssetKey:
    """Canonical token deployment identity. Symbols are intentionally excluded."""

    chain_id: int
    contract_address: str

    def __post_init__(self) -> None:
        if self.chain_id <= 0:
            raise RegistrySourceError("chain_id must be positive")
        object.__setattr__(
            self,
            "contract_address",
            normalize_evm_address(self.contract_address),
        )

    @property
    def canonical_id(self) -> str:
        return f"{self.chain_id}:{self.contract_address}"


@dataclass(frozen=True)
class ReferenceBinding:
    """Symbol-based reference endpoint bound back to a canonical asset identity."""

    asset_uid: str
    asset_key: AssetKey
    reference_symbol: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_uid", normalize_asset_uid(self.asset_uid))
        symbol = self.reference_symbol.strip().upper()
        if not symbol:
            raise RegistrySourceError("reference_symbol must be non-empty")
        object.__setattr__(self, "reference_symbol", symbol)

    @property
    def price_path(self) -> str:
        return f"/prices/{self.reference_symbol}"


@dataclass(frozen=True)
class CanonicalAssetRecord:
    asset_uid: str
    token_symbol: str
    token_name: str
    deployments: tuple[AssetKey, ...]
    current_multiplier: Decimal
    pending_multiplier: Decimal | None
    pending_multiplier_effective_at: datetime | None
    status: RegistryAssetStatus
    trading_capabilities: Mapping[str, Any] = field(default_factory=dict)
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_uid", normalize_asset_uid(self.asset_uid))
        symbol = self.token_symbol.strip().upper()
        if not symbol:
            raise RegistrySourceError("token_symbol must be non-empty")
        object.__setattr__(self, "token_symbol", symbol)
        if not self.token_name.strip():
            raise RegistrySourceError("token_name must be non-empty")
        if not self.deployments:
            raise RegistrySourceError("asset must have at least one deployment")
        if len(set(self.deployments)) != len(self.deployments):
            raise RegistryConflictError("duplicate deployment key within one asset")
        chain_ids = [deployment.chain_id for deployment in self.deployments]
        if len(set(chain_ids)) != len(chain_ids):
            raise RegistryConflictError("asset has more than one deployment on the same chain")
        if self.current_multiplier <= 0:
            raise RegistrySourceError("current_multiplier must be positive")
        if self.pending_multiplier is not None and self.pending_multiplier <= 0:
            raise RegistrySourceError("pending_multiplier must be positive when present")
        if self.pending_multiplier is None and self.pending_multiplier_effective_at is not None:
            raise RegistrySourceError("pending multiplier effective time exists without pending multiplier")
        if self.pending_multiplier is not None and self.pending_multiplier_effective_at is None:
            raise RegistrySourceError("pending multiplier requires an effective time")

    def deployment_for_chain(self, chain_id: int) -> AssetKey | None:
        return next((item for item in self.deployments if item.chain_id == chain_id), None)
