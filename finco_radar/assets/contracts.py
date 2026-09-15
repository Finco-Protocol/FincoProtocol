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
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")


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


def normalize_symbol(value: str, *, field_name: str = "symbol") -> str:
    """Normalize a provider symbol while keeping it safe as one URL path segment."""
    symbol = value.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise RegistrySourceError(
            f"{field_name} must be 1-32 chars using only A-Z, 0-9, '.', '_' or '-'"
        )
    return symbol


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
        object.__setattr__(
            self,
            "reference_symbol",
            normalize_symbol(self.reference_symbol, field_name="reference_symbol"),
        )

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
        object.__setattr__(
            self,
            "token_symbol",
            normalize_symbol(self.token_symbol, field_name="token_symbol"),
        )
        if not self.token_name.strip():
            raise RegistrySourceError("token_name must be non-empty")
        if not self.deployments:
            raise RegistrySourceError("asset must have at least one deployment")
        if len(set(self.deployments)) != len(self.deployments):
            raise RegistryConflictError("duplicate deployment key within one asset")
        chain_ids = [deployment.chain_id for deployment in self.deployments]
        if len(set(chain_ids)) != len(chain_ids):
            raise RegistryConflictError("asset has more than one deployment on the same chain")
        if not self.current_multiplier.is_finite() or self.current_multiplier <= 0:
            raise RegistrySourceError("current_multiplier must be positive and finite")
        if self.pending_multiplier is not None and (
            not self.pending_multiplier.is_finite() or self.pending_multiplier <= 0
        ):
            raise RegistrySourceError("pending_multiplier must be positive and finite when present")
        if self.pending_multiplier is None and self.pending_multiplier_effective_at is not None:
            raise RegistrySourceError("pending multiplier effective time exists without pending multiplier")
        if self.pending_multiplier is not None and self.pending_multiplier_effective_at is None:
            raise RegistrySourceError("pending multiplier requires an effective time")
        if (
            self.pending_multiplier_effective_at is not None
            and self.pending_multiplier_effective_at.tzinfo is None
        ):
            raise RegistrySourceError("pending multiplier effective time must be timezone-aware")

    def deployment_for_chain(self, chain_id: int) -> AssetKey | None:
        return next((item for item in self.deployments if item.chain_id == chain_id), None)
