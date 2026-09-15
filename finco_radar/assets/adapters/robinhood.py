"""Official Robinhood Stock Token asset-registry adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import httpx

from ..contracts import (
    AssetKey,
    CanonicalAssetRecord,
    RegistryAssetStatus,
    RegistrySourceError,
)
from ..registry import RegistrySnapshot


class RobinhoodAssetRegistryAdapter:
    source_name = "ROBINHOOD_STOCK_TOKEN_ASSETS_API"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.robinhood.com/rhj",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"accept": "application/json"},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "RobinhoodAssetRegistryAdapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_snapshot(self) -> RegistrySnapshot:
        response = self.client.get("/assets")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RegistrySourceError("asset registry returned invalid JSON") from exc
        return self.parse_snapshot(payload)

    def fetch_reference_price_payload(self, symbol: str) -> Mapping[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol:
            raise RegistrySourceError("reference symbol must be non-empty")
        response = self.client.get(f"/prices/{symbol}")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RegistrySourceError("reference price endpoint returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise RegistrySourceError("reference price payload must be an object")
        return payload

    @classmethod
    def parse_snapshot(
        cls,
        payload: Mapping[str, Any],
        *,
        observed_at: datetime | None = None,
    ) -> RegistrySnapshot:
        rows = payload.get("assets")
        if not isinstance(rows, list):
            raise RegistrySourceError("asset registry payload must contain an assets list")
        assets = tuple(cls._parse_asset(row) for row in rows)
        if not assets:
            raise RegistrySourceError("asset registry returned no assets")
        return RegistrySnapshot(
            source=cls.source_name,
            observed_at=observed_at or datetime.now(timezone.utc),
            assets=assets,
        )

    @staticmethod
    def _parse_asset(row: Any) -> CanonicalAssetRecord:
        if not isinstance(row, Mapping):
            raise RegistrySourceError("asset registry row must be an object")
        deployments_raw = row.get("deployments")
        if not isinstance(deployments_raw, list):
            raise RegistrySourceError("asset deployments must be a list")
        deployments: list[AssetKey] = []
        for deployment in deployments_raw:
            if not isinstance(deployment, Mapping):
                raise RegistrySourceError("asset deployment must be an object")
            try:
                deployments.append(
                    AssetKey(
                        chain_id=int(deployment["chainId"]),
                        contract_address=str(deployment["contractAddress"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistrySourceError("invalid asset deployment") from exc

        current_multiplier = _positive_decimal(row.get("currentMultiplier"), "currentMultiplier")
        pending_raw = row.get("pendingMultiplier")
        pending_multiplier = None
        pending_effective_at = None
        if pending_raw not in (None, ""):
            pending_multiplier = _positive_decimal(pending_raw, "pendingMultiplier")
            effective_raw = row.get("pendingMultiplierEffectiveTime")
            if not effective_raw:
                raise RegistrySourceError("pending multiplier is missing effective time")
            pending_effective_at = _parse_datetime(str(effective_raw))
        elif row.get("pendingMultiplierEffectiveTime") not in (None, ""):
            raise RegistrySourceError("effective time exists without pending multiplier")

        try:
            status = RegistryAssetStatus(str(row["status"]))
        except (KeyError, ValueError) as exc:
            raise RegistrySourceError("unknown or missing asset status") from exc

        capabilities = row.get("tradingCapabilities")
        if capabilities is None:
            capabilities = {}
        if not isinstance(capabilities, Mapping):
            raise RegistrySourceError("tradingCapabilities must be an object or null")

        try:
            uid = str(row["id"])
            symbol = str(row["tokenSymbol"])
            name = str(row["tokenName"])
        except KeyError as exc:
            raise RegistrySourceError("asset row is missing identity metadata") from exc

        return CanonicalAssetRecord(
            asset_uid=uid,
            token_symbol=symbol,
            token_name=name,
            deployments=tuple(deployments),
            current_multiplier=current_multiplier,
            pending_multiplier=pending_multiplier,
            pending_multiplier_effective_at=pending_effective_at,
            status=status,
            trading_capabilities=dict(capabilities),
            raw_evidence=dict(row),
        )


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RegistrySourceError(f"{field_name} must be a decimal string") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise RegistrySourceError(f"{field_name} must be positive and finite")
    return parsed


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistrySourceError("invalid pending multiplier effective time") from exc
    if parsed.tzinfo is None:
        raise RegistrySourceError("pending multiplier effective time must be timezone-aware")
    return parsed
