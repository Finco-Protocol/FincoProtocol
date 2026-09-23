"""Read-only live market cache: canonical binding, TTL, stale and call counts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

from app.radar_ui.market_read import MarketReadService, board_metadata
from app.radar_ui import router as radar_router
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.registry import validate_reference_price_payload


def _asset(uid, symbol, address):
    return {"id": uid, "tokenSymbol": symbol, "tokenName": symbol,
            "deployments": [{"chainId": 4663, "contractAddress": address}],
            "currentMultiplier": "1", "pendingMultiplier": "", "status": "ASSET_STATUS_ACTIVE"}


class FakeRegistry:
    def __init__(self):
        self.assets = [_asset("0x" + "11" * 32, "AAPL", "0x" + "aa" * 20),
                       _asset("0x" + "22" * 32, "NVDA", "0x" + "bb" * 20)]
        self.registry_calls = 0
        self.price_calls = []
        self.fail = False
        self.price_fail = False

    def fetch_snapshot(self):
        self.registry_calls += 1
        if self.fail:
            raise RuntimeError("offline")
        return RobinhoodAssetRegistryAdapter.parse_snapshot({"assets": self.assets})

    def fetch_bound_reference(self, snapshot, key):
        asset = snapshot.require_by_key(key)
        self.price_calls.append(asset.asset_uid)
        if self.price_fail:
            raise RuntimeError("reference source offline")
        row = {"tokenSymbol": asset.token_symbol,
               "deployments": [{"chainId": key.chain_id, "contractAddress": key.contract_address}],
               "bid": "340.63", "ask": "340.72", "currency": "USD",
               "generatedAt": datetime.now(timezone.utc).isoformat(), "isTradingHalt": False}
        binding = snapshot.reference_binding(key)
        return binding, validate_reference_price_payload(binding, {"quotes": [row]})

    def close(self):
        pass


def test_board_one_registry_fetch_bounded_fanout_and_selected_reuse():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter, ttl_seconds=10)
    rows = service.read(featured_symbols=("AAPL", "NVDA"))
    assert [r["state"] for r in rows] == ["FRESH", "FRESH"]
    assert rows[0]["price"] == "340.675"
    assert rows[0]["source"] == "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE"
    assert adapter.registry_calls == 1 and len(adapter.price_calls) == 2
    assert service.read(featured_symbols=("AAPL", "NVDA")) == rows
    assert service.read(uids=(rows[0]["uid"],)) == [rows[0]]
    assert adapter.registry_calls == 1 and len(adapter.price_calls) == 2


def test_unknown_uid_fails_closed_without_ticker_lookup():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter)
    assert service.read(uids=("0x" + "33" * 32,))[0]["state"] == "UNAVAILABLE"
    assert adapter.price_calls == []
    assert service.read(uids=("0x" + "33" * 32,))[0]["state"] == "UNAVAILABLE"
    assert adapter.registry_calls == 1


def test_provider_failure_preserves_last_known_value_as_stale():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter, ttl_seconds=0)
    uid = adapter.assets[0]["id"]
    first = service.read(uids=(uid,))[0]
    adapter.fail = True
    stale = service.read(uids=(uid,))[0]
    assert stale["state"] == "STALE"
    assert stale["price"] == first["price"]
    assert stale["observed_at"] == first["observed_at"]


def test_changed_canonical_contract_does_not_reuse_old_price():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter, ttl_seconds=0)
    uid = adapter.assets[0]["id"]
    assert service.read(uids=(uid,))[0]["state"] == "FRESH"
    adapter.assets[0] = _asset(uid, "AAPL", "0x" + "cc" * 20)
    adapter.price_fail = True
    result = service.read(uids=(uid,))[0]
    assert result["state"] == "UNAVAILABLE" and result["price"] is None


def test_simultaneous_board_reads_are_coalesced():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: service.read(featured_symbols=("AAPL", "NVDA")), range(5)))
    assert all(result == results[0] for result in results)
    assert adapter.registry_calls == 1 and len(adapter.price_calls) == 2


def test_board_cache_is_keyed_by_requested_symbols_and_missing_row_is_explicit():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter)
    first = service.read(featured_symbols=("AAPL", "NVDA"))
    second = service.read(featured_symbols=("AAPL", "MISSING"))
    assert [row["symbol"] for row in first] == ["AAPL", "NVDA"]
    assert [row["symbol"] for row in second] == ["AAPL", "MISSING"]
    assert second[1]["state"] == "UNAVAILABLE" and second[1]["price"] is None
    assert adapter.registry_calls == 2
    assert board_metadata(second) == {
        "state": "PARTIAL", "refreshed_at": second[0]["observed_at"],
        "asset_count": 2, "fresh_count": 1, "stale_count": 0, "unavailable_count": 1,
    }


def test_first_provider_failure_is_unavailable_without_fabricated_time():
    adapter = FakeRegistry()
    adapter.fail = True
    rows = MarketReadService(lambda: adapter).read(featured_symbols=("AAPL", "NVDA"))
    assert [row["state"] for row in rows] == ["UNAVAILABLE", "UNAVAILABLE"]
    assert board_metadata(rows) == {
        "state": "UNAVAILABLE", "refreshed_at": None,
        "asset_count": 2, "fresh_count": 0, "stale_count": 0, "unavailable_count": 2,
    }


def test_board_outage_preserves_each_observation_and_price():
    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter, ttl_seconds=0)
    first = service.read(featured_symbols=("AAPL", "NVDA"))
    adapter.fail = True
    stale = service.read(featured_symbols=("AAPL", "NVDA"))
    assert [(row["state"], row["price"], row["observed_at"]) for row in stale] == [
        ("STALE", row["price"], row["observed_at"]) for row in first
    ]
    assert board_metadata(stale)["refreshed_at"] is None


def test_partial_provider_failure_keeps_other_fresh_row_and_stale_observation():
    class PartialRegistry(FakeRegistry):
        failing_symbol = None

        def fetch_bound_reference(self, snapshot, key):
            if snapshot.require_by_key(key).token_symbol == self.failing_symbol:
                raise RuntimeError("one provider row failed")
            return super().fetch_bound_reference(snapshot, key)

    adapter = PartialRegistry()
    service = MarketReadService(lambda: adapter, ttl_seconds=0)
    before = service.read(featured_symbols=("AAPL", "NVDA"))
    adapter.failing_symbol = "NVDA"
    after = service.read(featured_symbols=("AAPL", "NVDA"))
    assert after[0]["state"] == "FRESH"
    assert after[1]["state"] == "STALE"
    assert after[1]["price"] == before[1]["price"]
    assert after[1]["observed_at"] == before[1]["observed_at"]
    assert board_metadata(after)["fresh_count"] == 1
    assert board_metadata(after)["stale_count"] == 1


def test_selected_uid_is_not_serialized_behind_unrelated_board_fanout():
    entered, release = Event(), Event()

    class SlowBoardRegistry(FakeRegistry):
        def fetch_bound_reference(self, snapshot, key):
            if key.contract_address.lower() == ("0x" + "bb" * 20):
                entered.set()
                assert release.wait(3), "test failed to release blocked board read"
            return super().fetch_bound_reference(snapshot, key)

    adapter = SlowBoardRegistry()
    adapter.assets.append(_asset("0x" + "33" * 32, "MSFT", "0x" + "cc" * 20))
    service = MarketReadService(lambda: adapter, ttl_seconds=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        board = pool.submit(service.read, featured_symbols=("NVDA",))
        assert entered.wait(2)
        try:
            selected = pool.submit(service.read, uids=("0x" + "33" * 32,))
            assert selected.result(timeout=1)[0]["state"] == "FRESH"
        finally:
            release.set()
        assert board.result(timeout=2)[0]["state"] == "FRESH"


def test_market_endpoints_never_invoke_executable_acquisition():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    adapter = FakeRegistry()
    service = MarketReadService(lambda: adapter)
    old_market = radar_router._market_read_service
    old_acquisition = radar_router._service_instance

    class ForbiddenAcquisition:
        def acquire(self, *args, **kwargs):
            raise AssertionError("market read attempted executable acquisition")

    radar_router.set_market_read_service(service)
    radar_router.set_service(ForbiddenAcquisition())
    try:
        app = FastAPI()
        app.include_router(radar_router.router)
        with TestClient(app) as client:
            board = client.get("/radar/market/board")
            assert board.status_code == 200
            uid = adapter.assets[0]["id"]
            selected = client.get(f"/radar/market/asset/{uid}")
            assert selected.status_code == 200
            assert selected.json()["asset"]["price_display"] == "$340.68"
            assert selected.json()["asset"]["price"] == "340.675"
            assert selected.json()["asset"]["uid"] == uid
            malformed = client.get("/radar/market/asset/AAPL")
            assert malformed.status_code == 400
            assert adapter.registry_calls == 1
    finally:
        radar_router.set_market_read_service(old_market)
        radar_router.set_service(old_acquisition)
