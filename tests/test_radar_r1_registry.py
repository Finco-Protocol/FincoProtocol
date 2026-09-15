from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    RegistryAssetStatus,
    RegistryConflictError,
    RegistryLookupError,
    RegistrySourceError,
)
from finco_radar.assets.registry import RegistrySnapshot, validate_reference_price_payload

UID_A = "0x" + "11" * 32
UID_B = "0x" + "22" * 32
ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20
ADDR_C = "0x" + "cc" * 20


def record(
    uid: str = UID_A,
    symbol: str = "AAA",
    address: str = ADDR_A,
    *,
    chain_id: int = 4663,
) -> CanonicalAssetRecord:
    return CanonicalAssetRecord(
        asset_uid=uid,
        token_symbol=symbol,
        token_name=f"{symbol} Token",
        deployments=(AssetKey(chain_id, address),),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )


def asset_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": UID_A,
        "tokenSymbol": "AAA",
        "tokenName": "AAA Token",
        "deployments": [{"chainId": 4663, "contractAddress": ADDR_A}],
        "currentMultiplier": "1",
        "pendingMultiplier": "",
        "status": "ASSET_STATUS_ACTIVE",
    }
    row.update(overrides)
    return row


def snapshot(*assets: CanonicalAssetRecord) -> RegistrySnapshot:
    return RegistrySnapshot(
        source="TEST",
        observed_at=datetime.now(timezone.utc),
        assets=tuple(assets),
    )


def test_asset_key_is_canonical_chain_plus_lowercase_address() -> None:
    key = AssetKey(4663, "0x" + "Aa" * 20)
    assert key.canonical_id == f"4663:{('0x' + 'aa' * 20)}"


def test_nonpositive_chain_id_fails_closed() -> None:
    with pytest.raises(RegistrySourceError, match="chain_id must be positive"):
        AssetKey(0, ADDR_A)


def test_malformed_uid_fails_closed() -> None:
    with pytest.raises(RegistrySourceError, match="asset_uid"):
        record("0x123", "AAA", ADDR_A)


@pytest.mark.parametrize("symbol", ["../AAA", "AAA/BBB", "AAA?X", "AAA%2FBBB", "AAA BBB"])
def test_unsafe_symbol_cannot_become_reference_path(symbol: str) -> None:
    with pytest.raises(RegistrySourceError):
        ReferenceBinding(asset_uid=UID_A, asset_key=AssetKey(4663, ADDR_A), reference_symbol=symbol)


def test_symbol_collision_is_allowed_but_never_unique_identity() -> None:
    registry = snapshot(record(UID_A, "DUP", ADDR_A), record(UID_B, "DUP", ADDR_B))
    assert len(registry.find_by_symbol("dup")) == 2
    with pytest.raises(RegistryLookupError):
        registry.require_unique_symbol("DUP")
    assert registry.require_by_key(AssetKey(4663, ADDR_A)).asset_uid == UID_A
    assert registry.require_by_key(AssetKey(4663, ADDR_B)).asset_uid == UID_B


def test_duplicate_canonical_deployment_fails_closed() -> None:
    with pytest.raises(RegistryConflictError):
        snapshot(record(UID_A, "AAA", ADDR_A), record(UID_B, "BBB", ADDR_A))


def test_duplicate_asset_uid_fails_closed() -> None:
    with pytest.raises(RegistryConflictError):
        snapshot(record(UID_A, "AAA", ADDR_A), record(UID_A, "BBB", ADDR_B))


def test_multi_chain_deployments_for_one_uid_are_supported() -> None:
    asset = CanonicalAssetRecord(
        asset_uid=UID_A,
        token_symbol="AAA",
        token_name="AAA Token",
        deployments=(AssetKey(4663, ADDR_A), AssetKey(1, ADDR_C)),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )
    registry = snapshot(asset)
    assert registry.require_by_key(AssetKey(4663, ADDR_A)).asset_uid == UID_A
    assert registry.require_by_key(AssetKey(1, ADDR_C)).asset_uid == UID_A
    assert registry.canonical_key_count == 2


def test_snapshot_is_intentionally_unhashable_and_indexes_do_not_drive_equality() -> None:
    assert RegistrySnapshot.__hash__ is None
    left = snapshot(record())
    right = RegistrySnapshot(source=left.source, observed_at=left.observed_at, assets=left.assets)
    assert left == right


def test_reference_binding_requires_exact_deployment_not_ticker_only() -> None:
    registry = snapshot(record(UID_A, "AAA", ADDR_A))
    binding = registry.reference_binding(AssetKey(4663, ADDR_A))
    good = {
        "quotes": [
            {
                "tokenSymbol": "AAA",
                "deployments": [{"chainId": 4663, "contractAddress": ADDR_A}],
                "bid": "10",
                "ask": "11",
            }
        ]
    }
    assert validate_reference_price_payload(binding, good)["bid"] == "10"
    wrong_address_same_ticker = {
        "quotes": [
            {
                "tokenSymbol": "AAA",
                "deployments": [{"chainId": 4663, "contractAddress": ADDR_B}],
            }
        ]
    }
    with pytest.raises(RegistryLookupError):
        validate_reference_price_payload(binding, wrong_address_same_ticker)


def test_reference_binding_rejects_symbol_conflict_on_exact_key() -> None:
    registry = snapshot(record(UID_A, "AAA", ADDR_A))
    binding = registry.reference_binding(AssetKey(4663, ADDR_A))
    payload = {
        "quotes": [
            {
                "tokenSymbol": "BBB",
                "deployments": [{"chainId": 4663, "contractAddress": ADDR_A}],
            }
        ]
    }
    with pytest.raises(RegistrySourceError):
        validate_reference_price_payload(binding, payload)


def test_reference_binding_requires_exactly_one_matching_row() -> None:
    registry = snapshot(record(UID_A, "AAA", ADDR_A))
    binding = registry.reference_binding(AssetKey(4663, ADDR_A))
    with pytest.raises(RegistryLookupError):
        validate_reference_price_payload(binding, {"quotes": []})
    row = {
        "tokenSymbol": "AAA",
        "deployments": [{"chainId": 4663, "contractAddress": ADDR_A}],
    }
    with pytest.raises(RegistryLookupError):
        validate_reference_price_payload(binding, {"quotes": [row, dict(row)]})


def test_reference_row_rejects_duplicate_deployment_keys() -> None:
    registry = snapshot(record(UID_A, "AAA", ADDR_A))
    binding = registry.reference_binding(AssetKey(4663, ADDR_A))
    payload = {
        "quotes": [
            {
                "tokenSymbol": "AAA",
                "deployments": [
                    {"chainId": 4663, "contractAddress": ADDR_A},
                    {"chainId": 4663, "contractAddress": ADDR_A},
                ],
            }
        ]
    }
    with pytest.raises(RegistrySourceError, match="duplicate deployment"):
        validate_reference_price_payload(binding, payload)


def test_official_identity_requires_uid_and_deployment_handshake() -> None:
    registry = snapshot(record(UID_A, "AAA", ADDR_A), record(UID_B, "BBB", ADDR_B))
    resolved = registry.resolve_official_identity(
        asset_uid=UID_A,
        deployments=(AssetKey(4663, ADDR_A),),
    )
    assert resolved.asset_uid == UID_A
    with pytest.raises(RegistryLookupError):
        registry.resolve_official_identity(
            asset_uid=UID_A,
            deployments=(AssetKey(4663, ADDR_C),),
        )
    with pytest.raises(RegistryLookupError):
        registry.resolve_official_identity(
            asset_uid=UID_A,
            deployments=(AssetKey(4663, ADDR_B),),
        )
    with pytest.raises(RegistryConflictError):
        registry.resolve_official_identity(
            asset_uid=UID_A,
            deployments=(AssetKey(4663, ADDR_A), AssetKey(4663, ADDR_B)),
        )


def test_robinhood_parser_preserves_multiplier_and_pending_metadata() -> None:
    payload = {
        "assets": [
            asset_row(
                currentMultiplier="1.250000000000000000",
                pendingMultiplier="2.500000000000000000",
                pendingMultiplierEffectiveTime="2026-09-20T14:30:00Z",
                tradingCapabilities={"fractionalTradability": "tradable"},
            )
        ]
    }
    registry = RobinhoodAssetRegistryAdapter.parse_snapshot(
        payload,
        observed_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    asset = registry.require_by_key(AssetKey(4663, ADDR_A))
    assert asset.current_multiplier == Decimal("1.250000000000000000")
    assert asset.pending_multiplier == Decimal("2.500000000000000000")
    assert asset.pending_multiplier_effective_at is not None
    assert asset.pending_multiplier_effective_at.tzinfo is not None


def test_missing_current_multiplier_fails_closed_explicitly() -> None:
    row = asset_row()
    row.pop("currentMultiplier")
    with pytest.raises(RegistrySourceError, match="currentMultiplier is required"):
        RobinhoodAssetRegistryAdapter.parse_snapshot({"assets": [row]})


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", ""])
def test_invalid_current_multiplier_fails_closed(value: str) -> None:
    with pytest.raises(RegistrySourceError):
        RobinhoodAssetRegistryAdapter.parse_snapshot(
            {"assets": [asset_row(currentMultiplier=value)]}
        )


def test_unknown_status_and_invalid_address_fail_closed() -> None:
    with pytest.raises(RegistrySourceError):
        RobinhoodAssetRegistryAdapter.parse_snapshot(
            {"assets": [asset_row(status="ASSET_STATUS_NEW_UNKNOWN")]}
        )
    with pytest.raises(RegistrySourceError, match="20-byte EVM"):
        RobinhoodAssetRegistryAdapter.parse_snapshot(
            {
                "assets": [
                    asset_row(
                        deployments=[
                            {"chainId": 4663, "contractAddress": "0xnot-an-address"}
                        ]
                    )
                ]
            }
        )


def test_pending_multiplier_without_effective_time_fails_closed() -> None:
    with pytest.raises(RegistrySourceError):
        RobinhoodAssetRegistryAdapter.parse_snapshot(
            {"assets": [asset_row(pendingMultiplier="2")]}
        )


def test_adapter_fetches_assets_and_bound_reference_with_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/assets"):
            return httpx.Response(200, json={"assets": [asset_row()]})
        if request.url.path.endswith("/prices/AAA"):
            return httpx.Response(
                200,
                json={
                    "quotes": [
                        {
                            "tokenSymbol": "AAA",
                            "deployments": [
                                {"chainId": 4663, "contractAddress": ADDR_A}
                            ],
                            "bid": "10",
                            "ask": "11",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    )
    try:
        adapter = RobinhoodAssetRegistryAdapter(client=client)
        registry = adapter.fetch_snapshot()
        asset = registry.require_by_key(AssetKey(4663, ADDR_A))
        binding, row = adapter.fetch_bound_reference(registry, asset.deployments[0])
        assert binding.asset_key == AssetKey(4663, ADDR_A)
        assert row["ask"] == "11"
    finally:
        client.close()
