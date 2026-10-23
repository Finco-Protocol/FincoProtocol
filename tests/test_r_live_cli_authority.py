"""CLI shares canonical lease authority; explicit direct API fixtures stay valid."""
import json
import sqlite3

import pytest
from app.radar_rwa import r_live_service
from app.radar_rwa import r_live_warming as warming
from app.radar_rwa import r_live_snapshot_store as store


@pytest.fixture
def cli(tmp_path,monkeypatch):
    database=str(tmp_path/'snapshot.sqlite')
    monkeypatch.setenv('R_LIVE_SNAPSHOT_DB_PATH',database)
    monkeypatch.setenv('ROBINHOOD_RPC_URL','https://fixture.invalid/no-network')
    calls=[]
    def acquire(**kwargs):
        calls.append(kwargs)
        return [('fixture-asset','AVAILABLE',{'value':123,'observed_at':'original-evidence-timestamp'})]
    monkeypatch.setattr(r_live_service,'collect_r_live_batch',acquire)
    return database,calls


def test_cli_denies_foreign_live_lease_before_acquisition_or_publication(cli,capsys):
    database,calls=cli;owner=warming._SnapshotLease(database)
    try:
        assert owner.acquire(ttl_seconds=300)
        assert warming.main(['--once'])==1
        assert not calls and not store.read_snapshots_readonly(path=database)
        assert json.loads(capsys.readouterr().out)=={'state':'LEASE_NOT_ACQUIRED','written':0}
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT holder FROM r_live_warming_lease').fetchone()[0]==owner._holder
    finally:owner.release();owner.close()


def test_cli_repeated_once_joins_resources_and_preserves_evidence(cli,capsys,monkeypatch):
    database,calls=cli;factory=warming.RLiveSnapshotWarmer;instances=[]
    def create():
        value=factory();instances.append(value);return value
    monkeypatch.setattr(warming,'RLiveSnapshotWarmer',create)
    for _ in range(3):
        assert warming.main(['--once'])==0
        assert json.loads(capsys.readouterr().out)['state']=='OK'
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT count(*) FROM r_live_warming_lease').fetchone()[0]==0
        instance=instances[-1]
        assert instance._lease is None and not instance._heartbeat.is_alive()
        assert not instance._cleanup_thread.is_alive()
    assert len(calls)==3
    assert store.read_snapshots_readonly(path=database)[0]['payload']['data']=={
        'value':123,'observed_at':'original-evidence-timestamp'}


def test_explicit_direct_store_api_preserved(cli):
    database,_=cli
    with store.RLiveSnapshotStore(path=database) as db:
        assert db.write_batch([('fixture-direct','AVAILABLE',{'seed':'explicit fixture'})],lease_holder=None)==1
    assert store.read_snapshots_readonly(path=database)[0]['payload']['data']=={'seed':'explicit fixture'}


def test_cli_acquisition_error_still_shuts_down_and_preserves_previous_snapshot(cli,capsys,monkeypatch):
    database,_=cli
    with store.RLiveSnapshotStore(path=database) as db:
        db.write_batch([('previous','AVAILABLE',{'observed_at':'original'})])
    before=store.read_snapshots_readonly(path=database)
    def fail(**kwargs):raise RuntimeError('synthetic acquisition failure')
    monkeypatch.setattr(r_live_service,'collect_r_live_batch',fail)
    assert warming.main(['--once'])==1
    assert json.loads(capsys.readouterr().out)['state']=='SYSTEMIC_FAILURE'
    assert store.read_snapshots_readonly(path=database)==before
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT count(*) FROM r_live_warming_lease').fetchone()[0]==0


def test_cli_missing_rpc_does_not_create_lease_or_snapshot(cli,capsys,monkeypatch):
    from pathlib import Path
    database,calls=cli;monkeypatch.delenv('ROBINHOOD_RPC_URL')
    assert warming.main(['--once'])==1
    assert json.loads(capsys.readouterr().out)['state']=='RPC_NOT_CONFIGURED'
    assert not calls and not Path(database).exists()
