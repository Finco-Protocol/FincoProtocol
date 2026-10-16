"""Zero-write, bounded, offline FINCO Radar V1 audit tests.

All data is deterministic synthetic fixture data; never represented as
historical market production evidence. There is no provider acquisition.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3

import pytest

from finco_radar.venues.observations import (
    FreshnessState, MarketObservation, ObservationStatus,
)
from finco_radar.venues.store import VenueMarketStore
from tools.radar_tokenized_closeout_audit import (
    AuditBlocked, _as_of, _readonly_snapshot, _snapshot_integrity,
    _existing_safe_source, main, run_audit,
)

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "input.db"
    VenueMarketStore(path)
    return path


def _observation(*, source_time=True, collected_shift=0, v2=False):
    ts = NOW - timedelta(seconds=60)
    payload = {"reference_state": "AVAILABLE",
               "reference_observed_at": ts.isoformat()}
    if v2:
        from finco_radar.venues.robinhood_live import EVIDENCE_CLOCK_CONTRACT
        payload["evidence_clock_contract"] = EVIDENCE_CLOCK_CONTRACT
    return MarketObservation(
        ts=ts.isoformat() if source_time else None,
        collected_at=(ts + timedelta(seconds=10 + collected_shift)).isoformat(),
        canonical_asset_id="NVDA", venue_id="fixture-venue",
        instrument_id="fixture-instrument",
        instrument_type="tokenized-equity",
        price="101.25", reference_price="100.0", basis_bps=None,
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=ObservationStatus.OK,
        source="SYNTHETIC_TEST_ONLY", payload=payload,
    )


def _signature(path: Path):
    v = path.stat()
    return v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns


def test_missing_source_never_creates_database_or_parent(tmp_path):
    missing = tmp_path / "missing-parent" / "observations.db"
    with pytest.raises(AuditBlocked, match="DATA_NOT_READY"):
        run_audit(missing, as_of=NOW)
    assert not missing.exists()
    assert not missing.parent.exists()


def test_empty_existing_schema_returns_explicit_not_ready(database):
    before = _signature(database)
    result = run_audit(database, as_of=NOW, max_assets=1)
    assert result["status"] == "DATA_NOT_READY"
    assert result["observation_store"]["total_observations"] == 0
    assert result["release_gate"] == "NOT_ASSESSED_NO_DEPLOYMENT_EVIDENCE"
    assert _signature(database) == before


def test_readonly_snapshot_does_not_mutate_source_or_create_sidecars(database, tmp_path):
    VenueMarketStore(database).append_observation(_observation())
    before = _signature(database)
    files_before = sorted(p.name for p in database.parent.iterdir())
    destination = tmp_path / "copy.db"
    proof = _readonly_snapshot(database, destination, 10**7)
    assert proof["source_file_unchanged"]
    assert proof["copy_kind"] == "TEMPORARY_OFFLINE_SNAPSHOT"
    assert _snapshot_integrity(destination)["total_observations"] == 1
    assert _signature(database) == before
    assert sorted(p.name for p in database.parent.iterdir()) == (
        sorted(files_before + ["copy.db"]))


def test_repeat_fixed_as_of_is_deterministic_and_original_rows_immutable(database):
    VenueMarketStore(database).append_observation(_observation())
    first = run_audit(database, as_of=NOW, max_assets=1)
    second = run_audit(database, as_of=NOW, max_assets=1)
    assert first == second
    assert first["status"] == "EVIDENCE_AUDITED"
    assert first["source"]["source_file_unchanged"]
    assert VenueMarketStore(database).count() == 1


def test_new_v2_and_legacy_clocks_are_counted_without_restamping(database):
    store = VenueMarketStore(database)
    old = _observation(source_time=False)
    new = _observation(v2=True)
    store.append_observation(old)
    store.append_observation(new)
    before = [(r.ts, r.collected_at) for r in
              store.get_window_for_underlying("NVDA", since=NOW - timedelta(days=1), until=NOW)]
    result = run_audit(database, as_of=NOW, max_assets=1)
    facts = result["observation_store"]
    assert facts["total_observations"] == 2
    assert facts["v2_clock_rows"] == 1
    assert facts["other_or_legacy_clock_rows"] == 1
    assert facts["missing_source_times"] == 1
    assert [(r.ts, r.collected_at) for r in
            store.get_window_for_underlying("NVDA", since=NOW - timedelta(days=1), until=NOW)] == before


def test_missing_source_timestamp_never_borrows_transport_clock(database):
    VenueMarketStore(database).append_observation(_observation(source_time=False))
    report = run_audit(database, as_of=NOW, max_assets=1)
    assert report["observation_store"]["distinct_source_times"] == 0
    assert report["observation_store"]["latest_source_timestamp"] is None
    assert report["observation_store"]["latest_collected_at"] is not None


def test_active_wal_fails_closed_without_checkpointing(database, tmp_path):
    wal = Path(str(database) + "-wal")
    wal.write_bytes(b"this represents an uncheckpointed WAL")
    before = _signature(database)
    with pytest.raises(AuditBlocked, match="SOURCE_WAL_ACTIVE"):
        _readonly_snapshot(database, tmp_path / "copy.db", 10**7)
    assert _signature(database) == before
    assert wal.exists()


def test_symlink_is_not_followed(tmp_path, database):
    symlink = tmp_path / "alias.db"
    symlink.symlink_to(database)
    with pytest.raises(AuditBlocked, match="symlink"):
        _existing_safe_source(symlink, 10**7)


def test_corrupt_source_fails_without_repair_or_schema_writes(tmp_path):
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"this is not sqlite")
    before = bad.read_bytes()
    with pytest.raises(AuditBlocked, match="DATA_CORRUPT"):
        run_audit(bad, as_of=NOW)
    assert bad.read_bytes() == before


def test_size_limit_rejects_without_source_mutation(database):
    before = _signature(database)
    with pytest.raises(AuditBlocked, match="configured bound"):
        run_audit(database, as_of=NOW, max_db_bytes=4096)
    assert _signature(database) == before


def test_bad_as_of_and_limits_fail_closed(database):
    with pytest.raises(ValueError, match="offset"):
        _as_of("2026-10-16T09:00:00")
    with pytest.raises(ValueError, match="aware"):
        run_audit(database, as_of=datetime(2026, 10, 16))
    with pytest.raises(ValueError, match="max_assets"):
        run_audit(database, as_of=NOW, max_assets=61)


def test_main_machine_json_exit_status_and_no_source_creation(tmp_path, capsys):
    missing = tmp_path / "missing.db"
    assert main(["--db-path", str(missing), "--as-of", NOW.isoformat()]) == 2
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "DATA_NOT_READY"
    assert data["release_gate"] == "NOT_ASSESSED"
    assert not missing.exists()


def test_audit_makes_no_network_calls(database, monkeypatch):
    from unittest.mock import patch
    VenueMarketStore(database).append_observation(_observation())
    with patch("socket.socket", side_effect=AssertionError("provider/network call prohibited")):
        report = run_audit(database, as_of=NOW, max_assets=1)
    assert report["status"] == "EVIDENCE_AUDITED"


def test_operator_observation_store_never_passed_to_schema_initializer(database, monkeypatch):
    VenueMarketStore(database).append_observation(_observation())
    original = VenueMarketStore.__init__
    seen = []

    def track(self, path=None):
        seen.append(Path(path))
        assert Path(path).resolve() != database.resolve()
        original(self, path)

    monkeypatch.setattr(VenueMarketStore, "__init__", track)
    run_audit(database, as_of=NOW, max_assets=1)
    assert seen and all(x.resolve() != database.resolve() for x in seen)
