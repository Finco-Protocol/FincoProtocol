from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3

import pytest

import app.radar_rwa.r_live_service as service
from app.radar_rwa.robinhood_registry_snapshot_store import RobinhoodRegistrySnapshotStore
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.engine import select_robinhood_registry
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from tests.test_r_live_onchain import BLOCK_TIME
from tests.test_r_live_v2_multi_asset import ReviewedPoolRpc


T0 = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
NVDA = next(p for p in APPROVED_BY_CANONICAL_ID.values() if p.symbol == "NVDA")
AAPL = next(p for p in APPROVED_BY_CANONICAL_ID.values() if p.symbol == "AAPL")


def _asset_row(policy, *, uid=None, current_multiplier="1", extra=None):
    row = {
        "id": uid or policy.economic_asset_uid,
        "tokenSymbol": policy.symbol,
        "tokenName": policy.symbol + " Robinhood Token",
        "deployments": [{
            "chainId": policy.asset_key.chain_id,
            "contractAddress": policy.asset_key.contract_address,
        }],
        "currentMultiplier": current_multiplier,
        "pendingMultiplier": "",
        "status": "ASSET_STATUS_ACTIVE",
        "tradingCapabilities": {"fractionalTradability": "tradable"},
    }
    if extra:
        row.update(extra)
    return row


def _snapshot(*policies, observed_at=T0):
    return RobinhoodAssetRegistryAdapter.parse_snapshot(
        {"assets": [_asset_row(policy) for policy in policies]},
        observed_at=observed_at,
    )


def _rewrite_envelope(path, mutate):
    with sqlite3.connect(path) as conn:
        payload, _digest = conn.execute(
            "SELECT payload, digest FROM robinhood_registry_snapshot WHERE singleton=1"
        ).fetchone()
        envelope = json.loads(payload)
        mutate(envelope)
        changed = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(changed.encode("utf-8")).hexdigest()
        conn.execute(
            "UPDATE robinhood_registry_snapshot SET payload=?, digest=? WHERE singleton=1",
            (changed, digest),
        )
        conn.commit()


def test_store_round_trip_preserves_original_official_evidence_and_identity(tmp_path):
    store = RobinhoodRegistrySnapshotStore(str(tmp_path / "registry.db"))
    original = RobinhoodAssetRegistryAdapter.parse_snapshot(
        {"assets": [_asset_row(
            NVDA,
            current_multiplier="1.250000000000000000",
            extra={
                "pendingMultiplier": "2.500000000000000000",
                "pendingMultiplierEffectiveTime": "2026-10-07T00:00:00Z",
            },
        )]},
        observed_at=T0,
    )

    digest = store.put(original)
    loaded = store.load_latest()

    assert len(digest) == 64
    assert loaded == original
    assert loaded is not original
    assert loaded.observed_at == T0
    asset = loaded.require_by_key(NVDA.asset_key)
    assert asset.asset_uid == NVDA.economic_asset_uid
    assert asset.current_multiplier == original.assets[0].current_multiplier
    assert asset.pending_multiplier == original.assets[0].pending_multiplier
    assert asset.raw_evidence == original.assets[0].raw_evidence


def test_store_read_never_restamps_observed_at(tmp_path):
    store = RobinhoodRegistrySnapshotStore(str(tmp_path / "registry.db"))
    original = _snapshot(NVDA, observed_at=T0)
    store.put(original)
    assert store.load_latest().observed_at == T0
    assert store.load_latest().observed_at == T0


def test_missing_store_returns_no_fallback(tmp_path):
    store = RobinhoodRegistrySnapshotStore(str(tmp_path / "missing.db"))
    assert store.load_latest() is None


def test_store_rejects_wrong_source_and_naive_timestamp(tmp_path):
    store = RobinhoodRegistrySnapshotStore(str(tmp_path / "registry.db"))
    valid = _snapshot(NVDA)
    wrong_source = RegistrySnapshot(
        source="NOT_ROBINHOOD",
        observed_at=valid.observed_at,
        assets=valid.assets,
    )
    with pytest.raises(ValueError, match="official Robinhood"):
        store.put(wrong_source)
    naive = RegistrySnapshot(
        source=RobinhoodAssetRegistryAdapter.source_name,
        observed_at=T0.replace(tzinfo=None),
        assets=valid.assets,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        store.put(naive)


def test_store_rejects_digest_mismatch_and_corrupt_json(tmp_path):
    path = tmp_path / "registry.db"
    store = RobinhoodRegistrySnapshotStore(str(path))
    store.put(_snapshot(NVDA))
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE robinhood_registry_snapshot SET digest=? WHERE singleton=1",
            ("0" * 64,),
        )
        conn.commit()
    assert store.load_latest() is None

    store.put(_snapshot(NVDA))
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE robinhood_registry_snapshot SET payload=?, digest=? WHERE singleton=1",
            ("{not-json", hashlib.sha256(b"{not-json").hexdigest()),
        )
        conn.commit()
    assert store.load_latest() is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda env: env.__setitem__("schema_version", "WRONG"),
        lambda env: env.__setitem__("source", "NOT_ROBINHOOD"),
        lambda env: env.__setitem__("observed_at", "2026-10-06T00:00:00"),
        lambda env: env["assets"][0].__setitem__("deployments", "malformed"),
    ],
)
def test_store_fails_closed_on_invalid_retained_envelope(tmp_path, mutation):
    path = tmp_path / "registry.db"
    store = RobinhoodRegistrySnapshotStore(str(path))
    store.put(_snapshot(NVDA))
    _rewrite_envelope(path, mutation)
    assert store.load_latest() is None


def test_store_fails_closed_on_canonical_identity_collision(tmp_path):
    path = tmp_path / "registry.db"
    store = RobinhoodRegistrySnapshotStore(str(path))
    store.put(_snapshot(NVDA))

    def collide(env):
        duplicate = dict(env["assets"][0])
        duplicate["id"] = "0x" + "99" * 32
        duplicate["tokenSymbol"] = "CLASH"
        duplicate["tokenName"] = "Clash Token"
        env["assets"].append(duplicate)

    _rewrite_envelope(path, collide)
    assert store.load_latest() is None


def test_store_requires_original_raw_official_rows(tmp_path):
    store = RobinhoodRegistrySnapshotStore(str(tmp_path / "registry.db"))
    parsed = _snapshot(NVDA)
    asset = parsed.assets[0]
    stripped = type(asset)(
        asset_uid=asset.asset_uid,
        token_symbol=asset.token_symbol,
        token_name=asset.token_name,
        deployments=asset.deployments,
        current_multiplier=asset.current_multiplier,
        pending_multiplier=asset.pending_multiplier,
        pending_multiplier_effective_at=asset.pending_multiplier_effective_at,
        status=asset.status,
        trading_capabilities=asset.trading_capabilities,
        raw_evidence={},
    )
    with pytest.raises(ValueError, match="original official"):
        store.put(RegistrySnapshot(
            source=parsed.source, observed_at=parsed.observed_at, assets=(stripped,)
        ))


def test_existing_authority_live_first_and_fresh_retained_fallback():
    retained = _snapshot(NVDA, observed_at=T0 - timedelta(seconds=100))
    live = _snapshot(NVDA, observed_at=T0)
    assert select_robinhood_registry(
        lambda: live, retained, as_of=T0, max_age_seconds=300
    ) is live

    def fail_live():
        raise RuntimeError("live unavailable")

    assert select_robinhood_registry(
        fail_live, retained, as_of=T0, max_age_seconds=300
    ) is retained


def test_existing_authority_300_second_boundary_and_no_restamp():
    retained = _snapshot(NVDA, observed_at=T0)
    fail_live = lambda: (_ for _ in ()).throw(RuntimeError("live unavailable"))
    assert select_robinhood_registry(
        fail_live, retained, as_of=T0 + timedelta(seconds=300), max_age_seconds=300
    ) is retained
    assert select_robinhood_registry(
        fail_live, retained, as_of=T0 + timedelta(seconds=301), max_age_seconds=300
    ) is None
    assert retained.observed_at == T0


def test_existing_authority_rejects_future_and_wrong_source_retained():
    retained = _snapshot(NVDA, observed_at=T0 + timedelta(seconds=1))
    fail_live = lambda: (_ for _ in ()).throw(RuntimeError("live unavailable"))
    assert select_robinhood_registry(
        fail_live, retained, as_of=T0, max_age_seconds=300
    ) is None

    valid = _snapshot(NVDA)
    wrong = RegistrySnapshot("NOT_ROBINHOOD", valid.observed_at, valid.assets)
    assert select_robinhood_registry(
        fail_live, wrong, as_of=T0, max_age_seconds=300
    ) is None


class _FakeAdapter:
    def __init__(self, *, live=None, live_error=False):
        self.live = live
        self.live_error = live_error
        self.fetch_calls = 0
        self.bound_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def fetch_snapshot(self):
        self.fetch_calls += 1
        if self.live_error:
            raise RuntimeError("registry unavailable")
        return self.live

    def fetch_bound_reference(self, registry, key):
        self.bound_calls += 1
        raise RuntimeError("bound reference unavailable")


class _FakeRpc:
    def __init__(self, *_args, **_kwargs):
        pass

    def close(self):
        pass


class _CountingStore:
    def __init__(self, retained=None, *, fail_write=False):
        self.retained = retained
        self.fail_write = fail_write
        self.reads = 0
        self.writes = 0
        self.written = None

    def load_latest(self):
        self.reads += 1
        return self.retained

    def put(self, snapshot):
        self.writes += 1
        if self.fail_write:
            raise OSError("disk unavailable")
        self.written = snapshot
        return "digest"


def _patch_single(monkeypatch, adapter, captured):
    monkeypatch.setattr(service, "RobinhoodAssetRegistryAdapter", lambda: adapter)
    monkeypatch.setattr(service, "JsonRpc", _FakeRpc)

    def fake_compose(**kwargs):
        captured.append(kwargs)
        return kwargs

    monkeypatch.setattr(service, "compose_r_live", fake_compose)


def test_collect_single_live_selected_retained_and_storage_failure_nonfatal(monkeypatch):
    live = _snapshot(NVDA, observed_at=T0)
    adapter = _FakeAdapter(live=live)
    store = _CountingStore(fail_write=True)
    captured = []
    _patch_single(monkeypatch, adapter, captured)

    result = service.collect_r_live(
        canonical_asset_id=NVDA.asset_key.canonical_id,
        rpc_url="https://rpc.invalid",
        as_of=T0,
        registry_store=store,
    )

    assert result["registry"] is live
    assert store.reads == 1
    assert store.writes == 1
    assert adapter.fetch_calls == 1
    assert result["underlying"] is None


def test_collect_single_live_failure_fresh_retained_preserves_exact_identity(monkeypatch):
    retained = _snapshot(NVDA, observed_at=T0 - timedelta(seconds=120))
    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(retained)
    captured = []
    _patch_single(monkeypatch, adapter, captured)

    result = service.collect_r_live(
        canonical_asset_id=NVDA.asset_key.canonical_id,
        rpc_url="https://rpc.invalid",
        as_of=T0,
        registry_store=store,
    )

    assert result["registry"] is retained
    assert result["registry"].require_by_key(NVDA.asset_key).asset_uid == NVDA.economic_asset_uid
    assert store.reads == 1
    assert store.writes == 0
    assert adapter.fetch_calls == 1
    assert result["underlying"] is None


@pytest.mark.parametrize("age", [301, 900])
def test_collect_single_rejects_stale_retained_identity(monkeypatch, age):
    retained = _snapshot(NVDA, observed_at=T0 - timedelta(seconds=age))
    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(retained)
    captured = []
    _patch_single(monkeypatch, adapter, captured)

    result = service.collect_r_live(
        canonical_asset_id=NVDA.asset_key.canonical_id,
        rpc_url="https://rpc.invalid",
        as_of=T0,
        registry_store=store,
    )
    assert result["registry"] is None


def test_collect_single_corrupt_store_fails_closed(monkeypatch):
    class CorruptStore:
        def load_latest(self):
            raise ValueError("corrupt")

        def put(self, _snapshot):
            raise AssertionError("must not write fallback")

    adapter = _FakeAdapter(live_error=True)
    captured = []
    _patch_single(monkeypatch, adapter, captured)
    result = service.collect_r_live(
        canonical_asset_id=NVDA.asset_key.canonical_id,
        rpc_url="https://rpc.invalid",
        as_of=T0,
        registry_store=CorruptStore(),
    )
    assert result["registry"] is None


def test_collect_single_valid_live_survives_retained_read_failure(monkeypatch):
    class BrokenReadStore:
        def __init__(self):
            self.writes = 0

        def load_latest(self):
            raise ValueError("corrupt retained storage")

        def put(self, snapshot):
            self.writes += 1
            assert snapshot is live
            return "digest"

    live = _snapshot(NVDA, observed_at=T0)
    adapter = _FakeAdapter(live=live)
    store = BrokenReadStore()
    captured = []
    _patch_single(monkeypatch, adapter, captured)

    result = service.collect_r_live(
        canonical_asset_id=NVDA.asset_key.canonical_id,
        rpc_url="https://rpc.invalid",
        as_of=T0,
        registry_store=store,
    )
    assert result["registry"] is live
    assert store.writes == 1


def test_collect_single_never_substitutes_ticker_for_missing_exact_key(monkeypatch):
    wrong_address = "0x" + "12" * 20
    wrong = RobinhoodAssetRegistryAdapter.parse_snapshot(
        {"assets": [{
            **_asset_row(NVDA),
            "deployments": [{
                "chainId": NVDA.asset_key.chain_id,
                "contractAddress": wrong_address,
            }],
        }]},
        observed_at=T0,
    )
    assert wrong.find_by_symbol("NVDA")
    assert wrong.get_by_key(NVDA.asset_key) is None

    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(wrong)
    captured = []
    _patch_single(monkeypatch, adapter, captured)
    result = service.collect_r_live(
        canonical_asset_id=NVDA.asset_key.canonical_id,
        rpc_url="https://rpc.invalid",
        as_of=T0,
        registry_store=store,
    )

    assert result["registry"] is wrong
    assert result["underlying"] is None
    assert adapter.bound_calls == 0


def _patch_batch(monkeypatch, adapter, selected_registries):
    monkeypatch.setattr(service, "RobinhoodAssetRegistryAdapter", lambda: adapter)
    monkeypatch.setattr(service, "JsonRpc", _FakeRpc)

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass
        def close(self):
            pass

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    def fake_compose(**kwargs):
        selected_registries.append(kwargs["registry"])
        return kwargs["registry"]

    monkeypatch.setattr(service, "compose_r_live", fake_compose)
    monkeypatch.setattr(
        service,
        "format_r_live_result",
        lambda canonical_id, result: (
            "AVAILABLE" if result is not None else "UNAVAILABLE",
            {"canonical_id": canonical_id},
        ),
    )


def test_batch_uses_one_live_attempt_one_retained_read_and_one_shared_fallback(monkeypatch):
    retained = _snapshot(NVDA, AAPL, observed_at=T0 - timedelta(seconds=120))
    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(retained)
    selected = []
    _patch_batch(monkeypatch, adapter, selected)

    ids = (NVDA.asset_key.canonical_id, AAPL.asset_key.canonical_id)
    rows = list(service.collect_r_live_batch(
        rpc_url="https://rpc.invalid",
        workers=2,
        as_of=T0,
        canonical_ids=ids,
        registry_store=store,
    ))

    assert len(rows) == 2
    assert adapter.fetch_calls == 1
    assert store.reads == 1
    assert store.writes == 0
    assert selected == [retained, retained] or selected == [retained, retained][::-1]
    assert all(registry is retained for registry in selected)


def test_batch_live_wins_over_retained_and_is_retained_once(monkeypatch):
    retained = _snapshot(NVDA, AAPL, observed_at=T0 - timedelta(seconds=120))
    live = _snapshot(NVDA, AAPL, observed_at=T0)
    adapter = _FakeAdapter(live=live)
    store = _CountingStore(retained)
    selected = []
    _patch_batch(monkeypatch, adapter, selected)

    list(service.collect_r_live_batch(
        rpc_url="https://rpc.invalid",
        workers=2,
        as_of=T0,
        canonical_ids=(NVDA.asset_key.canonical_id, AAPL.asset_key.canonical_id),
        registry_store=store,
    ))

    assert adapter.fetch_calls == 1
    assert store.reads == 1
    assert store.writes == 1
    assert store.written is live
    assert all(registry is live for registry in selected)


def test_batch_rejects_stale_retained_fallback_once_for_whole_batch(monkeypatch):
    retained = _snapshot(NVDA, AAPL, observed_at=T0 - timedelta(seconds=301))
    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(retained)
    selected = []
    _patch_batch(monkeypatch, adapter, selected)

    rows = list(service.collect_r_live_batch(
        rpc_url="https://rpc.invalid",
        workers=2,
        as_of=T0,
        canonical_ids=(NVDA.asset_key.canonical_id, AAPL.asset_key.canonical_id),
        registry_store=store,
    ))

    assert adapter.fetch_calls == 1
    assert store.reads == 1
    assert store.writes == 0
    assert len(rows) == 2
    assert selected == [None, None]


def test_batch_preserves_nvda_exact_identity_in_shared_fallback(monkeypatch):
    retained = _snapshot(NVDA, AAPL, observed_at=T0 - timedelta(seconds=120))
    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(retained)
    selected = []
    _patch_batch(monkeypatch, adapter, selected)

    list(service.collect_r_live_batch(
        rpc_url="https://rpc.invalid",
        workers=2,
        as_of=T0,
        canonical_ids=(NVDA.asset_key.canonical_id, AAPL.asset_key.canonical_id),
        registry_store=store,
    ))

    assert selected
    for registry in selected:
        assert registry is retained
        assert registry.require_by_key(NVDA.asset_key).asset_uid == NVDA.economic_asset_uid
    assert NVDA.asset_key.canonical_id == (
        "4663:0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"
    )


def test_batch_sibling_failure_remains_isolated_after_shared_selection(monkeypatch):
    retained = _snapshot(NVDA, AAPL, observed_at=T0 - timedelta(seconds=120))
    adapter = _FakeAdapter(live_error=True)
    store = _CountingStore(retained)
    monkeypatch.setattr(service, "RobinhoodAssetRegistryAdapter", lambda: adapter)
    monkeypatch.setattr(service, "JsonRpc", _FakeRpc)

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def close(self):
            pass

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    def fake_compose(**kwargs):
        assert kwargs["registry"] is retained
        if kwargs["key"] == NVDA.asset_key:
            raise RuntimeError("NVDA independent evidence unavailable")
        return kwargs["registry"]

    monkeypatch.setattr(service, "compose_r_live", fake_compose)
    monkeypatch.setattr(
        service,
        "format_r_live_result",
        lambda canonical_id, _result: ("AVAILABLE", {"canonical_id": canonical_id}),
    )

    rows = list(service.collect_r_live_batch(
        rpc_url="https://rpc.invalid",
        workers=2,
        as_of=T0,
        canonical_ids=(NVDA.asset_key.canonical_id, AAPL.asset_key.canonical_id),
        registry_store=store,
    ))
    by_id = {canonical_id: state for canonical_id, state, _data in rows}
    assert by_id[NVDA.asset_key.canonical_id] == "UNAVAILABLE"
    assert by_id[AAPL.asset_key.canonical_id] == "AVAILABLE"
    assert adapter.fetch_calls == 1
    assert store.reads == 1


def test_fresh_registry_fallback_does_not_make_stale_market_current():
    policy = NVDA
    retained = RobinhoodAssetRegistryAdapter.parse_snapshot(
        {"assets": [_asset_row(policy)]},
        observed_at=datetime.fromtimestamp(BLOCK_TIME, timezone.utc),
    )
    as_of = datetime.fromtimestamp(BLOCK_TIME + 120, timezone.utc)

    def fail_live():
        raise RuntimeError("registry unavailable")

    selected = select_robinhood_registry(
        fail_live,
        retained,
        as_of=as_of,
        max_age_seconds=300,
    )
    assert selected is retained

    result = service.compose_r_live(
        registry=selected,
        underlying=None,
        rpc=ReviewedPoolRpc(policy, activity_age_seconds=301),
        as_of=as_of,
        history=None,
        key=policy.asset_key,
    )
    assert result.onchain.state is AuthorityState.STALE
    state, _data = service.format_r_live_result(policy.asset_key.canonical_id, result)
    assert state != "AVAILABLE"
