"""Y-LIVE V1 — source observation, snapshot, history, collector, truthful UI.

Network-free: every provider interaction goes through ``httpx.MockTransport``
so the real httpx error paths (timeouts, transport errors, HTTP statuses) are
exercised without a socket.

FIXTURE PROVENANCE: the Morpho responses below follow the documented
``vaultByAddress`` GraphQL response shape, built deterministically from the
bundled reference identities.  They are NOT captured live responses (the
authoring sandbox cannot reach api.morpho.org); see docs/YIELD_LIVE_V1.md.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path

import httpx
import pytest

from finco_yield import collect_live
from finco_yield.history import (
    HistoryCorruptionError,
    ImmutableObservationRecord,
    YieldHistoryStore,
)
from finco_yield.live_sources import (
    MorphoGraphQLAdapter,
    SourceTarget,
)
from finco_yield.registry import bundled_reference_rows, load_bundled_registry, _from_row
from finco_yield.snapshot import (
    SnapshotError,
    SnapshotWriteError,
    build_snapshot_payload,
    displayed_freshness,
    load_active_registry,
    merge_rows,
    read_snapshot,
    write_snapshot_atomic,
)

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _reference():
    return [_from_row(r) for r in bundled_reference_rows()]


def _targets():
    return [SourceTarget.from_opportunity(o) for o in _reference()]


class FakeClock:
    def __init__(self, start=T0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def _vault(target, *, net_apy=0.0412, apy=0.05, tvl=1_250_000.5, **override):
    body = {
        "address": target.contract_address,
        "name": target.name,
        "symbol": "VAULT",
        "asset": {"address": target.underlying_address, "symbol": target.underlying_symbol},
        "chain": {"id": target.chain_id},
        "state": {"apy": apy, "netApy": net_apy, "totalAssetsUsd": tvl},
    }
    body.update(override)
    return body


def _ok(vault):
    return httpx.Response(200, json={"data": {"vaultByAddress": vault}})


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _by_address(responders, default=None):
    """handler: per-vault behaviour keyed by request variables."""
    by_addr = {t.contract_address: t for t in _targets()}

    def handler(request: httpx.Request):
        variables = json.loads(request.content)["variables"]
        target = by_addr[variables["address"]]
        responder = responders.get(target.contract_address, default)
        return responder(target, request)

    return handler


def _adapter(handler, clock=None):
    return MorphoGraphQLAdapter(
        url="https://morpho.test/graphql", client=_client(handler),
        timeout=1.0, clock=clock or FakeClock())


def _env(tmp_path, **extra):
    env = {
        "FINCO_YIELD_COLLECTOR_ENABLED": "1",
        "FINCO_YIELD_SNAPSHOT_PATH": str(tmp_path / "snap" / "current.json"),
        "FINCO_YIELD_HISTORY_PATH": str(tmp_path / "hist" / "history.jsonl"),
    }
    env.update(extra)
    return env


def _run(tmp_path, adapter, clock=None, **env_extra):
    import io
    out = io.StringIO()
    clock = clock or FakeClock()
    code = collect_live.main([], env=_env(tmp_path, **env_extra), adapters=[adapter], now=clock, out=out)
    return code, json.loads(out.getvalue())


def _all_ok(target, request):
    return _ok(_vault(target))


# ── 1. source adapter: valid payload & field semantics ───────────────────────

class TestAdapterNormalization:
    def test_valid_payload_normalizes_deterministically(self):
        clock = FakeClock()
        result = _adapter(_by_address({}, _all_ok), clock).fetch(_targets())
        assert result.status == "SUCCEEDED" and not result.failures
        assert len(result.observations) == len(_targets()) == 14
        obs = result.observations[0]
        assert obs.apy_total == Decimal("0.0412")           # state.netApy passthrough
        assert obs.tvl_usd == Decimal("1250000.5")
        assert obs.apy_base is None and obs.apy_rewards is None   # never derived
        assert obs.source_native["state.apy"] == 0.05       # kept native-only
        assert obs.observed_at_policy == "FETCHED_AT" and obs.observed_at == obs.fetched_at == T0
        assert obs.provider == "morpho_graphql"
        assert obs.source_record_id == f"{obs.chain_id}:{obs.contract_address}"
        assert "UNAVAILABLE" in obs.derived["apy_base"]
        again = _adapter(_by_address({}, _all_ok), FakeClock()).fetch(_targets())
        assert [o.payload() for o in result.observations] == [o.payload() for o in again.observations]

    def test_canonical_identity_matches_registry_uid(self):
        result = _adapter(_by_address({}, _all_ok)).fetch(_targets())
        assert {o.uid for o in result.observations} == {o.uid for o in _reference()}
        assert len({o.uid for o in result.observations}) == 14

    @pytest.mark.parametrize("field", ["netApy", "totalAssetsUsd"])
    def test_missing_metric_is_unavailable_not_zero(self, field):
        def responder(target, request):
            v = _vault(target)
            v["state"][field] = None
            return _ok(v)
        obs = _adapter(_by_address({}, responder)).fetch(_targets()).observations[0]
        value = obs.apy_total if field == "netApy" else obs.tvl_usd
        assert value is None
        payload = obs.payload()
        assert payload["apy_total" if field == "netApy" else "tvl_usd"] is None   # not "0"

    def test_missing_base_and_rewards_apy_are_unavailable_everywhere(self):
        obs = _adapter(_by_address({}, _all_ok)).fetch(_targets()).observations[0]
        assert obs.payload()["apy_base"] is None and obs.payload()["apy_rewards"] is None

    def test_explicit_zero_is_valid_data_and_stays_zero(self):
        def responder(target, request):
            return _ok(_vault(target, net_apy=0, tvl=0))
        obs = _adapter(_by_address({}, responder)).fetch(_targets()).observations[0]
        assert obs.apy_total == Decimal("0") and obs.tvl_usd == Decimal("0")
        assert obs.payload()["apy_total"] == "0" and obs.payload()["tvl_usd"] == "0"

    def test_record_with_no_proven_economic_value_is_rejected(self):
        def responder(target, request):
            v = _vault(target)
            v["state"] = {"apy": 0.05, "netApy": None, "totalAssetsUsd": None}
            return _ok(v)
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert not result.observations
        assert all(f.rejected and f.code == "OBSERVATION_EMPTY" for f in result.failures)

    @pytest.mark.parametrize("bad", [True, "0.04", float("nan"), float("inf")])
    def test_non_numeric_or_non_finite_values_rejected(self, bad):
        def responder(target, request):
            v = _vault(target)
            v["state"]["netApy"] = bad
            if isinstance(bad, float):
                return httpx.Response(200, content=json.dumps({"data": {"vaultByAddress": v}}))
            return _ok(v)
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert not result.observations
        assert all(f.rejected for f in result.failures)

    def test_out_of_range_apy_rejected(self):
        result = _adapter(_by_address({}, lambda t, r: _ok(_vault(t, net_apy=250)))).fetch(_targets())
        assert not result.observations and all(f.code == "OBSERVATION_VALUE_INVALID" for f in result.failures)


# ── 2. provider failures are UNAVAILABLE, never zero ────────────────────────

class TestProviderFailures:
    def test_timeout(self):
        def responder(target, request):
            raise httpx.ReadTimeout("slow", request=request)
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert result.status == "FAILED" and not result.observations
        assert {f.code for f in result.failures} == {"SOURCE_TIMEOUT"}
        assert not any(f.rejected for f in result.failures)

    @pytest.mark.parametrize("status,code", [
        (500, "SOURCE_UPSTREAM_UNAVAILABLE"), (503, "SOURCE_UPSTREAM_UNAVAILABLE"),
        (429, "SOURCE_RATE_LIMITED"), (403, "SOURCE_ACCESS_DENIED"), (404, "SOURCE_HTTP_ERROR"),
    ])
    def test_http_failure(self, status, code):
        result = _adapter(_by_address({}, lambda t, r: httpx.Response(status, text="boom"))).fetch(_targets())
        assert not result.observations
        assert {f.code for f in result.failures} == {code}

    def test_transport_error_does_not_leak_secrets(self):
        def responder(target, request):
            raise httpx.ConnectError("https://x.test/?key=SUPERSECRET Bearer abc", request=request)
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert {f.code for f in result.failures} == {"SOURCE_NETWORK_ERROR"}
        assert "SUPERSECRET" not in repr(result)

    def test_malformed_json(self):
        result = _adapter(_by_address({}, lambda t, r: httpx.Response(200, text="<html>nope"))).fetch(_targets())
        assert {f.code for f in result.failures} == {"SOURCE_MALFORMED_JSON"}

    def test_graphql_errors_and_not_found(self):
        r1 = _adapter(_by_address({}, lambda t, r: httpx.Response(200, json={"errors": [{"message": "secret detail"}]}))).fetch(_targets())
        assert {f.code for f in r1.failures} == {"SOURCE_GRAPHQL_ERROR"}
        assert "secret detail" not in repr(r1)
        r2 = _adapter(_by_address({}, lambda t, r: _ok(None))).fetch(_targets())
        assert {f.code for f in r2.failures} == {"SOURCE_RECORD_NOT_FOUND"}

    def test_wrong_shape_is_rejected_not_unavailable(self):
        result = _adapter(_by_address({}, lambda t, r: httpx.Response(200, json={"data": {"vaultByAddress": {"address": t.contract_address}}}))).fetch(_targets())
        assert {f.code for f in result.failures} == {"SOURCE_SCHEMA_REJECTED"}
        assert all(f.rejected for f in result.failures)

    def test_partial_provider_result_keeps_good_targets(self):
        bad = _targets()[3].contract_address

        def failing(target, request):
            return httpx.Response(500)
        result = _adapter(_by_address({bad: failing}, _all_ok)).fetch(_targets())
        assert result.status == "PARTIAL"
        assert len(result.observations) == 13 and len(result.failures) == 1
        assert result.failures[0].uid == _targets()[3].uid


# ── 3. identity collision protection ────────────────────────────────────────

class TestIdentityProtection:
    @pytest.mark.parametrize("mutate", [
        lambda v, t: v.update(address="0x" + "ab" * 20),
        lambda v, t: v["asset"].update(address="0x" + "cd" * 20),
        lambda v, t: v["chain"].update(id=t.chain_id + 1),
        lambda v, t: v["chain"].update(id=True),
    ])
    def test_response_for_a_different_vault_is_rejected(self, mutate):
        def responder(target, request):
            v = _vault(target)
            mutate(v, target)
            return _ok(v)
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert not result.observations
        assert {f.code for f in result.failures} == {"SOURCE_IDENTITY_MISMATCH"}

    def test_names_and_symbols_never_establish_identity(self):
        refs = _reference()
        same_symbol = [o for o in refs if o.underlying_symbol == refs[0].underlying_symbol]
        assert len(same_symbol) > 1
        assert len({o.uid for o in same_symbol}) == len(same_symbol)

        def responder(target, request):   # rename + re-symbol the vault: still the same identity
            return _ok(_vault(target, name="Totally Different Name", symbol="USDC"))
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert {o.uid for o in result.observations} == {o.uid for o in refs}

    def test_address_case_is_normalised_not_trusted(self):
        def responder(target, request):
            return _ok(_vault(target, address=target.contract_address.upper().replace("0X", "0x")))
        result = _adapter(_by_address({}, responder)).fetch(_targets())
        assert len(result.observations) == 14


# ── 4. history: append-only, dedupe, read interface ─────────────────────────

def _record(uid="yld_x", at=T0, **payload):
    return ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=at, source_authority="NATIVE_ENRICHED",
        source_uri="https://evidence.test", adapter_version="t", payload=payload or {"apy_total": "0.04"})


class TestHistory:
    def test_exact_retry_dedupe(self, tmp_path):
        store = YieldHistoryStore(tmp_path / "h.jsonl")
        first = store.append_idempotent(_record())
        second = store.append_idempotent(_record())
        assert first[1] is True and second[1] is False and first[0] == second[0]
        assert len(store.read_all()) == 1

    def test_append_only_immutability(self, tmp_path):
        path = tmp_path / "h.jsonl"
        store = YieldHistoryStore(path)
        store.append_idempotent(_record(at=T0))
        before = path.read_bytes()
        store.append_idempotent(_record(at=T0 + timedelta(minutes=5), apy_total="0.05"))
        store.append_idempotent(_record(at=T0))               # retry of the first
        after = path.read_bytes()
        assert after.startswith(before)                       # prefix untouched
        assert len(store.read_all()) == 2

    def test_read_interface_latest_prior_window(self, tmp_path):
        store = YieldHistoryStore(tmp_path / "h.jsonl")
        for i in (3, 1, 2):                                    # out-of-order writes
            store.append_idempotent(_record(at=T0 + timedelta(hours=i), apy_total=f"0.0{i}"))
        store.append_idempotent(_record(uid="yld_other", at=T0 + timedelta(hours=9)))
        assert store.latest("yld_x")["payload"]["apy_total"] == "0.03"
        assert store.latest("yld_missing") is None
        win = store.window("yld_x", since=T0 + timedelta(hours=2), until=T0 + timedelta(hours=3))
        assert [r["payload"]["apy_total"] for r in win] == ["0.02", "0.03"]
        prior = store.prior("yld_x", before=T0 + timedelta(hours=3), limit=2)
        assert [r["payload"]["apy_total"] for r in prior] == ["0.01", "0.02"]
        assert [r["payload"]["apy_total"] for r in store.window("yld_x")] == ["0.01", "0.02", "0.03"]
        with pytest.raises(ValueError):
            store.prior("yld_x", before=T0, limit=0)

    def test_torn_file_fails_closed_without_extending_it(self, tmp_path):
        path = tmp_path / "h.jsonl"
        store = YieldHistoryStore(path)
        store.append_idempotent(_record())
        with path.open("ab") as fh:
            fh.write(b'{"torn":')
        before = path.read_bytes()
        with pytest.raises(HistoryCorruptionError):
            store.append_idempotent(_record(at=T0 + timedelta(hours=1)))
        assert path.read_bytes() == before

    def test_naive_timestamp_rejected(self, tmp_path):
        store = YieldHistoryStore(tmp_path / "h.jsonl")
        with pytest.raises(ValueError):
            store.append_idempotent(_record(at=datetime(2026, 1, 1)))

    def test_existing_append_contract_is_unchanged(self, tmp_path):
        store = YieldHistoryStore(tmp_path / "h.jsonl")
        store.append(_record())
        store.append(_record())                                # legacy API still appends
        assert len(store.read_all()) == 2


# ── 5. snapshot: atomic, last-good preserved ────────────────────────────────

def _snapshot_with(rows, at=T0):
    return build_snapshot_payload(rows, at)


class TestSnapshot:
    def test_atomic_write_roundtrip_and_no_temp_leak(self, tmp_path):
        path = tmp_path / "s" / "current.json"
        payload = _snapshot_with([{"opportunity_uid": "b", "observed_at": "2026-10-02T12:00:00Z"},
                                  {"opportunity_uid": "a", "observed_at": "2026-10-02T12:00:00Z"}])
        write_snapshot_atomic(path, payload)
        snap = read_snapshot(path)
        assert [r["opportunity_uid"] for r in snap.rows] == ["a", "b"]         # stable order
        assert [p.name for p in path.parent.iterdir()] == ["current.json"]
        write_snapshot_atomic(path, payload)
        assert path.read_bytes() == path.read_bytes()

    def test_failed_write_preserves_previous_snapshot(self, tmp_path, monkeypatch):
        path = tmp_path / "current.json"
        write_snapshot_atomic(path, _snapshot_with([{"opportunity_uid": "a", "observed_at": "2026-10-02T12:00:00Z"}]))
        before = path.read_bytes()

        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(SnapshotWriteError):
            write_snapshot_atomic(path, _snapshot_with([{"opportunity_uid": "z", "observed_at": "2026-10-02T13:00:00Z"}]))
        monkeypatch.undo()
        assert path.read_bytes() == before
        assert [p.name for p in tmp_path.iterdir()] == ["current.json"]       # temp removed

    @pytest.mark.parametrize("content,code", [
        (None, "SNAPSHOT_MISSING"),
        ("{not json", "SNAPSHOT_MALFORMED"),
        ('{"schema":"other"}', "SNAPSHOT_SCHEMA_UNSUPPORTED"),
        ('{"schema":"YIELD_CURRENT_SNAPSHOT_V1","rows":"x"}', "SNAPSHOT_MALFORMED"),
    ])
    def test_invalid_snapshots_are_errors_never_empty(self, tmp_path, content, code):
        path = tmp_path / "current.json"
        if content is not None:
            path.write_text(content)
        with pytest.raises(SnapshotError) as exc:
            read_snapshot(path)
        assert exc.value.code == code

    def test_tampered_rows_fail_integrity(self, tmp_path):
        path = tmp_path / "current.json"
        write_snapshot_atomic(path, _snapshot_with([{"opportunity_uid": "a", "observed_at": "2026-10-02T12:00:00Z", "apy_total": "0.04"}]))
        path.write_text(path.read_text().replace('"0.04"', '"0.99"'))
        with pytest.raises(SnapshotError) as exc:
            read_snapshot(path)
        assert exc.value.code == "SNAPSHOT_INTEGRITY_FAILED"

    def test_merge_carries_forward_and_never_regresses_or_deletes(self):
        old = ({"opportunity_uid": "a", "observed_at": "2026-10-02T12:00:00Z", "v": 1},
               {"opportunity_uid": "b", "observed_at": "2026-10-02T12:00:00Z", "v": 1})
        merged = merge_rows(old, [
            {"opportunity_uid": "a", "observed_at": "2026-10-02T11:00:00Z", "v": 0},    # older: ignored
            {"opportunity_uid": "c", "observed_at": "2026-10-02T12:30:00Z", "v": 2},
        ])
        assert [(r["opportunity_uid"], r["v"]) for r in merged] == [("a", 1), ("b", 1), ("c", 2)]
        assert merge_rows(old, []) == list(old)                                         # [] never wipes


# ── 6. collector: reports, exit codes, history+snapshot ─────────────────────

class TestCollector:
    def test_success_report_snapshot_and_history(self, tmp_path):
        code, report = _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        assert code == 0 and report["status"] == "OK"
        assert report["providers_attempted"] == ["morpho_graphql"]
        assert report["providers_succeeded"] == ["morpho_graphql"] and report["providers_failed"] == []
        assert report["observations_fetched"] == report["observations_accepted"] == 14
        assert report["observations_rejected"] == 0 and report["duplicates_skipped"] == 0
        assert report["history_append"]["appended"] == 14 and report["snapshot_update"]["result"] == "UPDATED"
        for key in ("started_at", "finished_at", "schema"):
            assert key in report
        snap = read_snapshot(Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"]))
        assert len(snap.rows) == 14
        assert all(r["data_origin"] == "SOURCE_OBSERVED" and r["history_observation_hash"] for r in snap.rows)
        hist = YieldHistoryStore(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).read_all()
        assert len(hist) == 14

    def test_repeated_execution_does_not_duplicate_history(self, tmp_path):
        clock = FakeClock()
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        clock.advance(minutes=5)
        code, report = _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        assert code == 0
        assert report["history_append"]["appended"] == 0 and report["history_append"]["skipped_unchanged"] == 14
        assert report["duplicates_skipped"] == 14
        assert len(YieldHistoryStore(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).read_all()) == 14
        # the snapshot still advances: the re-observation is recorded as current
        snap = read_snapshot(Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"]))
        assert snap.rows[0]["fetched_at"] == "2026-10-02T12:05:00Z"

    def test_changed_value_and_heartbeat_append_new_observations(self, tmp_path):
        clock = FakeClock()
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        clock.advance(minutes=5)
        changed = lambda t, r: _ok(_vault(t, net_apy=0.0999))
        _, report = _run(tmp_path, _adapter(_by_address({}, changed), clock), clock)
        assert report["history_append"]["appended"] == 14
        clock.advance(minutes=20)                                  # past the 900 s heartbeat, same values
        _, report = _run(tmp_path, _adapter(_by_address({}, changed), clock), clock)
        assert report["history_append"]["appended"] == 14
        assert len(YieldHistoryStore(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).read_all()) == 42

    def test_partial_failure_still_persists_valid_observations(self, tmp_path):
        bad = _targets()[0].contract_address
        code, report = _run(tmp_path, _adapter(_by_address({bad: lambda t, r: httpx.Response(500)}, _all_ok)))
        assert code == 3 and report["status"] == "PARTIAL"
        assert report["observations_accepted"] == 13
        assert report["providers_succeeded"] == ["morpho_graphql"]
        assert report["provider_detail"]["morpho_graphql"]["status"] == "PARTIAL"
        assert len(read_snapshot(Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"])).rows) == 13

    def test_rejected_observations_are_counted_and_make_run_partial(self, tmp_path):
        bad = _targets()[1].contract_address
        wrong = lambda t, r: _ok(_vault(t, address="0x" + "11" * 20))
        code, report = _run(tmp_path, _adapter(_by_address({bad: wrong}, _all_ok)))
        assert code == 3
        assert report["observations_rejected"] == 1 and report["observations_fetched"] == 14
        assert report["observations_accepted"] == 13

    def test_total_provider_failure_is_failed_and_writes_nothing(self, tmp_path):
        code, report = _run(tmp_path, _adapter(_by_address({}, lambda t, r: httpx.Response(503))))
        assert code == 2 and report["status"] == "FAILED"
        assert report["providers_failed"] == ["morpho_graphql"]
        assert report["snapshot_update"]["result"] == "SKIPPED"
        assert not Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"]).exists()      # no [] snapshot
        assert not Path(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).exists()

    def test_failed_refresh_preserves_stale_last_good(self, tmp_path):
        clock = FakeClock()
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        snap_path = Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"])
        good = snap_path.read_bytes()
        hist = Path(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).read_bytes()
        clock.advance(hours=3)
        code, report = _run(tmp_path, _adapter(_by_address({}, lambda t, r: httpx.Response(500)), clock), clock)
        assert code == 2 and report["snapshot_update"]["previous_preserved"] is True
        assert snap_path.read_bytes() == good                                       # byte-identical
        assert Path(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).read_bytes() == hist
        # last-good stays visible but canonical freshness classifies it STALE
        registry, status = load_active_registry(_env(tmp_path))
        assert status.origin == "SNAPSHOT" and status.live_rows == 14
        from finco_yield.freshness import evaluate_freshness
        from finco_yield.schema import SourceReference
        for o in registry.all():
            src = SourceReference(o.source_type, o.source_uri, o.observed_at, o.block_number, o.adapter, o.adapter_version)
            assert evaluate_freshness(src, now=T0 + timedelta(hours=3)).state == "STALE"
            assert evaluate_freshness(src, now=T0 + timedelta(minutes=5)).state == "CURRENT"

    def test_partial_refresh_carries_forward_untouched_rows(self, tmp_path):
        clock = FakeClock()
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        clock.advance(minutes=10)
        skip = _targets()[2]
        code, _ = _run(tmp_path, _adapter(_by_address({skip.contract_address: lambda t, r: httpx.Response(500)}, _all_ok), clock), clock)
        assert code == 3
        rows = {r["opportunity_uid"]: r for r in read_snapshot(Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"])).rows}
        assert len(rows) == 14
        assert rows[skip.uid]["fetched_at"] == "2026-10-02T12:00:00Z"               # old, carried
        assert all(r["fetched_at"] == "2026-10-02T12:10:00Z" for u, r in rows.items() if u != skip.uid)

    def test_snapshot_write_failure_is_failed_and_keeps_previous(self, tmp_path, monkeypatch):
        clock = FakeClock()
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        snap_path = Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"])
        before = snap_path.read_bytes()
        clock.advance(minutes=10)
        monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        code, report = _run(tmp_path, _adapter(_by_address({}, lambda t, r: _ok(_vault(t, net_apy=0.07))), clock), clock)
        monkeypatch.undo()
        assert code == 2 and report["snapshot_update"]["result"] == "FAILED"
        assert report["snapshot_update"]["previous_preserved"] is True
        assert snap_path.read_bytes() == before

    def test_history_failure_does_not_block_current_snapshot(self, tmp_path):
        hist = Path(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"])
        hist.parent.mkdir(parents=True)
        hist.write_bytes(b'{"opportunity_uid":"x","observed_at":"2026-10-02T11:00:00Z"}\n{"torn"')
        code, report = _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        assert code == 3
        assert report["history_append"]["failed"] == 14
        assert report["snapshot_update"]["result"] == "UPDATED"
        assert hist.read_bytes().endswith(b'{"torn"')                                # history untouched

    def test_corrupt_previous_snapshot_is_preserved_as_evidence_then_replaced(self, tmp_path):
        snap_path = Path(_env(tmp_path)["FINCO_YIELD_SNAPSHOT_PATH"])
        snap_path.parent.mkdir(parents=True)
        snap_path.write_text("{garbage")
        code, _ = _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        assert code == 0
        assert (snap_path.parent / "current.json.corrupt").read_text() == "{garbage"
        assert len(read_snapshot(snap_path).rows) == 14

    def test_history_rows_are_compatible_with_alert_readers(self, tmp_path):
        from finco_yield.alerts_eval import _row_field
        _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        row = YieldHistoryStore(_env(tmp_path)["FINCO_YIELD_HISTORY_PATH"]).read_all()[0]
        assert _row_field(row, "apy_total") == "0.0412"
        assert _row_field(row, "apy_rewards") is None                              # MISSING, not 0
        assert row["source_authority"] == "NATIVE_ENRICHED" and row["observation_hash"]


class TestExitCodePolicy:
    def test_disabled_makes_no_provider_call(self, tmp_path):
        class Exploding:
            provider_id = "x"

            def supports(self, t):
                raise AssertionError("must not run")

            def fetch(self, t):
                raise AssertionError("must not run")
        import io
        out = io.StringIO()
        env = _env(tmp_path)
        env.pop("FINCO_YIELD_COLLECTOR_ENABLED")
        assert collect_live.main([], env=env, adapters=[Exploding()], out=out) == 4
        assert json.loads(out.getvalue())["status"] == "DISABLED"

    @pytest.mark.parametrize("drop", ["FINCO_YIELD_SNAPSHOT_PATH", "FINCO_YIELD_HISTORY_PATH"])
    def test_missing_paths_is_config_error(self, tmp_path, drop):
        import io
        env = _env(tmp_path)
        env.pop(drop)
        out = io.StringIO()
        assert collect_live.main([], env=env, adapters=[], out=out) == 4
        assert json.loads(out.getvalue())["status"] == "CONFIG_ERROR"

    def test_concurrent_run_exits_locked(self, tmp_path):
        import io
        env = _env(tmp_path)
        snap = Path(env["FINCO_YIELD_SNAPSHOT_PATH"])
        snap.parent.mkdir(parents=True)
        with open(snap.with_name(snap.name + ".collect.lock"), "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            out = io.StringIO()
            assert collect_live.main([], env=env, adapters=[], out=out) == 75
        assert json.loads(out.getvalue())["status"] == "LOCKED"

    def test_adapter_crash_is_a_failed_provider_not_a_crash(self, tmp_path):
        class Crashy:
            provider_id = "crashy"

            def supports(self, t):
                return True

            def fetch(self, t):
                raise RuntimeError("https://x?key=SECRETVALUE")
        code, report = _run(tmp_path, Crashy())
        assert code == 2 and report["providers_failed"] == ["crashy"]
        assert "SECRETVALUE" not in json.dumps(report)

    def test_report_contains_no_environment_secrets(self, tmp_path):
        code, report = _run(tmp_path, _adapter(_by_address({}, _all_ok)), SOME_SECRET="hunter2-token")
        assert "hunter2-token" not in json.dumps(report)

    @pytest.mark.parametrize("url", ["http://morpho.test/graphql", "ftp://x", "morpho.test"])
    def test_non_https_endpoint_is_config_error_before_any_network(self, tmp_path, url):
        import io
        out = io.StringIO()
        code = collect_live.main([], env=_env(tmp_path, FINCO_YIELD_MORPHO_API_URL=url), out=out)
        assert code == 4 and json.loads(out.getvalue())["status"] == "CONFIG_ERROR"
        with pytest.raises(ValueError):
            MorphoGraphQLAdapter(url=url)

    def test_interval_clamp(self):
        f = collect_live.history_min_interval
        assert f({}) == 900 and f({"FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS": "x"}) == 900
        assert f({"FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS": "99999"}) == 1500
        assert f({"FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS": "-5"}) == 0


# ── 7. truthful reference-vs-live presentation ──────────────────────────────

class TestReferenceVsLive:
    def test_bundled_registry_is_reference_fixture_never_live(self):
        reg = load_bundled_registry()
        assert {o.data_origin for o in reg.all()} == {"REFERENCE_FIXTURE"}

    def test_reference_fixture_is_never_displayed_current(self):
        ref = load_bundled_registry().all()[0]
        assert displayed_freshness(ref, "CURRENT") == "REFERENCE"
        assert displayed_freshness(ref, "STALE") == "STALE"
        assert displayed_freshness(ref, "UNAVAILABLE") == "UNAVAILABLE"

    def test_unspecified_origin_keeps_canonical_state(self):
        ref = load_bundled_registry().all()[0]
        import dataclasses
        plain = dataclasses.replace(ref, data_origin="UNSPECIFIED")
        assert displayed_freshness(plain, "CURRENT") == "CURRENT"

    def test_registry_origin_states(self, tmp_path):
        reg, status = load_active_registry({})
        assert status.origin == "REFERENCE_FIXTURE" and not status.is_live
        env = _env(tmp_path)
        reg, status = load_active_registry(env)                          # configured but absent
        assert status.origin == "REFERENCE_FALLBACK" and status.reason == "SNAPSHOT_MISSING"
        assert {o.data_origin for o in reg.all()} == {"REFERENCE_FIXTURE"}
        _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        reg, status = load_active_registry(env)
        assert status.origin == "SNAPSHOT" and status.is_live and status.live_rows == 14
        assert {o.data_origin for o in reg.all()} == {"SOURCE_OBSERVED"}
        assert all(o.provider == "morpho_graphql" and o.fetched_at for o in reg.all())

    def test_corrupt_snapshot_falls_back_visibly(self, tmp_path):
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        p = Path(env["FINCO_YIELD_SNAPSHOT_PATH"])
        p.write_text(p.read_text().replace("0.0412", "0.5"))
        reg, status = load_active_registry(env)
        assert status.origin == "REFERENCE_FALLBACK" and status.reason == "SNAPSHOT_INTEGRITY_FAILED"
        assert {o.data_origin for o in reg.all()} == {"REFERENCE_FIXTURE"}

    def test_live_none_never_falls_back_to_reference_value(self, tmp_path):
        reference_tvl = _reference()[0].observation.tvl_usd
        assert reference_tvl is not None                                  # reference carries a TVL
        def responder(target, request):
            return _ok(_vault(target, tvl=None))
        _run(tmp_path, _adapter(_by_address({}, responder)))
        reg, _ = load_active_registry(_env(tmp_path))
        assert all(o.observation.tvl_usd is None for o in reg.all())      # UNAVAILABLE != reference

    def test_universe_cannot_shrink_or_grow_from_snapshot(self, tmp_path):
        env = _env(tmp_path)
        clock = FakeClock()
        only_one = _targets()[0].contract_address
        _run(tmp_path, _adapter(_by_address({}, lambda t, r: _ok(_vault(t)) if t.contract_address == only_one else httpx.Response(500)), clock), clock)
        reg, status = load_active_registry(env)
        assert len(reg.all()) == 14                                       # universe unchanged
        assert status.live_rows == 1 and status.reference_rows == 13
        origins = sorted(o.data_origin for o in reg.all())
        assert origins.count("SOURCE_OBSERVED") == 1 and origins.count("REFERENCE_FIXTURE") == 13

    def test_snapshot_row_cannot_move_identity(self, tmp_path):
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok)))
        p = Path(env["FINCO_YIELD_SNAPSHOT_PATH"])
        payload = json.loads(p.read_text())
        payload["rows"][0]["contract_address"] = "0x" + "99" * 20          # try to repoint
        payload["content_hash"] = __import__("finco_yield.evidence_v1", fromlist=["x"]).canonical_hash(payload["rows"])
        p.write_text(json.dumps(payload))
        reg, status = load_active_registry(env)
        assert len(reg.all()) == 14
        # the overlay takes observation fields only; identity stays the reference identity
        assert {o.contract_address for o in reg.all()} == {o.contract_address for o in _reference()}


# ── 8. web surfaces ─────────────────────────────────────────────────────────

@pytest.fixture()
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "web.db"))
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_SNAPSHOT_PATH", raising=False)
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "web.db"))
    _db.init_db()
    from starlette.testclient import TestClient
    import main_web
    with TestClient(main_web.app, base_url="https://yield-live.local", raise_server_exceptions=True) as c:
        yield c, monkeypatch


class TestWebProvenance:
    def test_default_explorer_is_labelled_reference_not_live(self, web):
        client, _ = web
        page = client.get("/yield").text
        assert 'data-testid="yield-source-status"' in page and 'data-origin="REFERENCE_FIXTURE"' in page
        assert "not live data" in page
        assert "Reference fixture — not live" in page
        assert "Source-observed" not in page

    def test_live_snapshot_rows_show_provider_and_state(self, web, tmp_path):
        client, mp = web
        clock = FakeClock(datetime.now(timezone.utc))
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        mp.setenv("FINCO_YIELD_SNAPSHOT_PATH", env["FINCO_YIELD_SNAPSHOT_PATH"])
        page = client.get("/yield").text
        assert 'data-origin="SNAPSHOT"' in page
        assert "Source-observed" in page and "morpho_graphql" in page
        assert "4.12%" in page                                                # netApy 0.0412
        assert "CURRENT" in page
        assert "Reference fixture — not live" not in page

    def test_stale_live_snapshot_is_stale_not_unavailable_not_zero(self, web, tmp_path):
        client, mp = web
        clock = FakeClock(datetime.now(timezone.utc) - timedelta(hours=5))
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        mp.setenv("FINCO_YIELD_SNAPSHOT_PATH", env["FINCO_YIELD_SNAPSHOT_PATH"])
        page = client.get("/yield").text
        assert "STALE" in page and "4.12%" in page and "Source-observed" in page
        assert "UNAVAILABLE" not in page.split("<tbody>")[1].split("</tbody>")[0].replace("Last observed", "")

    def test_unavailable_snapshot_falls_back_with_visible_reason(self, web, tmp_path):
        client, mp = web
        mp.setenv("FINCO_YIELD_SNAPSHOT_PATH", str(tmp_path / "missing.json"))
        page = client.get("/yield").text
        assert 'data-origin="REFERENCE_FALLBACK"' in page
        assert "SNAPSHOT_MISSING" in page and "not live data" in page

    def test_missing_apy_components_render_unavailable_never_zero(self, web, tmp_path):
        client, mp = web
        clock = FakeClock(datetime.now(timezone.utc))
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        mp.setenv("FINCO_YIELD_SNAPSHOT_PATH", env["FINCO_YIELD_SNAPSHOT_PATH"])
        page = client.get("/yield").text
        assert "<td>—</td>" in page and "0.00%" not in page

    def test_detail_page_shows_origin_provider_and_fetch_time(self, web, tmp_path):
        client, mp = web
        clock = FakeClock(datetime.now(timezone.utc))
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        mp.setenv("FINCO_YIELD_SNAPSHOT_PATH", env["FINCO_YIELD_SNAPSHOT_PATH"])
        uid = _reference()[0].uid
        page = client.get(f"/yield/{uid}").text
        assert 'data-testid="data-origin-detail"' in page
        assert "Source-observed" in page and "morpho_graphql" in page and "Fetched:" in page

    def test_execution_stays_off_with_live_data(self, web, tmp_path):
        client, mp = web
        from finco_yield.flags import execution_enabled
        assert execution_enabled() is False
        clock = FakeClock(datetime.now(timezone.utc))
        env = _env(tmp_path)
        _run(tmp_path, _adapter(_by_address({}, _all_ok), clock), clock)
        mp.setenv("FINCO_YIELD_SNAPSHOT_PATH", env["FINCO_YIELD_SNAPSHOT_PATH"])
        assert execution_enabled() is False
        uid = _reference()[0].uid
        resp = client.post(f"/yield/{uid}/transaction-plan", json={})
        assert resp.status_code in (400, 401, 403, 404, 405, 409, 422, 503)       # never a plan


# ── 9. structural guarantees ────────────────────────────────────────────────

class TestStructure:
    def test_live_modules_never_import_execution_or_signing(self):
        for name in ("observation.py", "live_sources.py", "snapshot.py", "collect_live.py"):
            tree = ast.parse((REPO / "finco_yield" / name).read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported.add((node.module or "").split(".")[0] if node.level == 0 else (node.module or ""))
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
            assert not ({"execution", "onchain", "providers", "access"} & imported), (name, imported)

    def test_staging_env_keeps_execution_off_and_collector_disabled(self):
        text = (REPO / "deploy" / "staging.env.example").read_text()
        assert "FINCO_YIELD_EXECUTION_ENABLED=0" in text
        assert "FINCO_YIELD_COLLECTOR_ENABLED=0" in text
        collector_env = (REPO / "deploy" / "yield_collector_v1" / "yield-collector.env.example").read_text()
        assert "FINCO_YIELD_COLLECTOR_ENABLED=0" in collector_env
        assert "FINCO_YIELD_EXECUTION_ENABLED" not in collector_env

    def test_systemd_units_are_prepared_not_installed(self):
        base = REPO / "deploy" / "yield_collector_v1"
        service = (base / "finco-yield-collector.service").read_text()
        timer = (base / "finco-yield-collector.timer").read_text()
        assert "python -m finco_yield.collect_live" in service
        assert "flock -n -E 75" in service and "Type=oneshot" in service
        assert "Unit=finco-yield-collector.service" in timer
        assert "SuccessExitStatus=3" in service
        assert "NoNewPrivileges=true" in service
        staging = base / "staging"
        for unit in (service, (staging / "finco-staging-yield-collector.service").read_text()):
            headers = [ln.strip() for ln in unit.splitlines() if ln.strip().startswith("[")]
            assert "[Install]" not in headers          # only the timer activates the service
            assert "python -m finco_yield.collect_live" in unit and "flock -n -E 75" in unit
        assert "Unit=finco-staging-yield-collector.service" in (staging / "finco-staging-yield-collector.timer").read_text()
        assert "FINCO_YIELD_COLLECTOR_ENABLED=0" in (staging / "yield-collector.staging.env.example").read_text()

    def test_no_secret_or_credential_is_required(self):
        src = (REPO / "finco_yield" / "live_sources.py").read_text()
        assert "api_key" not in src.lower() and "authorization" not in src.lower()
