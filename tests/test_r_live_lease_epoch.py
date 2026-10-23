"""Deterministic lease epochs; real SQLite transactions, no race-assertion sleeps."""
from datetime import datetime, timedelta, timezone
import sqlite3
import threading

import pytest
from app.background_lifecycle import ShutdownIncomplete
from app.radar_rwa import r_live_warming as warming
from app.radar_rwa import r_live_snapshot_store as snapshots


@pytest.fixture
def authority(tmp_path, monkeypatch):
    class Clock(datetime):
        current = datetime(2030, 1, 1, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None): return cls.current
    monkeypatch.setattr(snapshots, 'datetime', Clock)
    path = str(tmp_path/'snapshot.sqlite')
    leases = []
    def lease():
        value = warming._SnapshotLease(path, clock=lambda: Clock.current)
        leases.append(value)
        return value
    yield Clock, path, lease
    for value in leases:
        value.release(); value.close()


def publish(path, lease):
    with lease.publication_guard(), snapshots.RLiveSnapshotStore(path=path) as store:
        return store.write_batch([('asset', 'AVAILABLE', {'value': 123})], lease_holder=lease._holder)


def test_valid_renewal_preserves_epoch_and_cadence(authority):
    clock, path, factory = authority; lease=factory()
    assert lease.acquire(ttl_seconds=30); token=lease._holder
    for _ in range(4):
        clock.current += timedelta(seconds=10)
        assert lease.renew(ttl_seconds=30)
        assert lease._holder == token
        assert not factory().acquire(ttl_seconds=30)
    assert publish(path, lease) == 1


@pytest.mark.parametrize('loss', ['expired', 'missing', 'foreign'])
def test_lost_epoch_cannot_renew_or_reacquire(authority, loss):
    clock, path, factory=authority; lease=factory()
    assert lease.acquire(ttl_seconds=30)
    if loss == 'expired': clock.current += timedelta(seconds=30)
    else:
        with sqlite3.connect(path) as db:
            db.execute('DELETE FROM r_live_warming_lease' if loss=='missing' else
                       "UPDATE r_live_warming_lease SET holder='foreign'")
    assert not lease.renew(ttl_seconds=30)
    assert not lease.acquire_or_renew(ttl_seconds=30)
    assert not lease.acquire(ttl_seconds=30)
    with pytest.raises(snapshots.LeaseOwnershipLost): publish(path, lease)
    assert snapshots.read_snapshots_readonly(path=path) == []


def test_expired_same_owner_publication_rejected_without_heartbeat(authority):
    clock,path,factory=authority; lease=factory()
    assert lease.acquire(ttl_seconds=30)
    clock.current += timedelta(seconds=30)
    with pytest.raises(snapshots.LeaseOwnershipLost): publish(path,lease)
    assert lease._lost
    assert not lease.renew(ttl_seconds=30)


def test_foreign_takeover_rejects_stale_batch(authority):
    clock,path,factory=authority; first=factory(); second=factory()
    assert first.acquire(ttl_seconds=30)
    clock.current += timedelta(seconds=31)
    assert second.acquire(ttl_seconds=30)
    with pytest.raises(snapshots.LeaseOwnershipLost): publish(path,first)
    first.release()  # cannot delete second owner's row
    assert publish(path,second)==1


class ConnectionHook:
    def __init__(self, connection, hook): self.connection, self.hook=connection,hook
    def __getattr__(self,name): return getattr(self.connection,name)
    def execute(self,sql,*args):
        result=self.connection.execute(sql,*args)
        self.hook(sql)
        return result


def test_clock_sampled_after_actual_sqlite_writer_transaction(authority):
    clock,path,factory=authority; lease=factory()
    statements=[]; lease._conn.set_trace_callback(statements.append)
    assert lease.acquire(ttl_seconds=30)
    def acquired_writer(sql):
        if sql=='BEGIN IMMEDIATE':
            assert lease._conn.in_transaction
            clock.current += timedelta(seconds=31)
    lease._conn=ConnectionHook(lease._conn,acquired_writer)
    assert not lease.renew(ttl_seconds=30)
    assert statements[-1]=='ROLLBACK'
    assert not any(sql.startswith('UPDATE') for sql in statements)


def test_database_renewal_error_invalidates_even_still_live_row(authority):
    clock,path,factory=authority; lease=factory()
    assert lease.acquire(ttl_seconds=30)
    def fail(sql):
        if sql=='BEGIN IMMEDIATE': raise sqlite3.OperationalError('injected unavailable DB')
    lease._conn=ConnectionHook(lease._conn,fail)
    assert not lease.renew(ttl_seconds=30)
    with pytest.raises(snapshots.LeaseOwnershipLost): publish(path,lease)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT holder FROM r_live_warming_lease').fetchone()[0]==lease._holder
    lease._conn=lease._conn.connection


def test_delayed_heartbeat_fails_and_shutdown_is_bounded(authority):
    clock,path,factory=authority; lease=factory()
    assert lease.acquire(ttl_seconds=30)
    warmer=warming.RLiveSnapshotWarmer(store_path=path,lease_ttl_seconds=30)
    warmer._lease=lease
    class DelayedHeartbeat:
        def wait(self,period):
            clock.current += timedelta(seconds=31)
            return False
    warmer._renew_until(DelayedHeartbeat())
    assert warmer._stop.is_set() and lease._lost
    with pytest.raises(snapshots.LeaseOwnershipLost): publish(path,lease)
    # Normal close still must complete, but the original failure stays visible.
    with pytest.raises(ShutdownIncomplete,match='failed before clean shutdown'): warmer.shutdown(2)
    assert warmer._lease is None and not warmer._cleanup_thread.is_alive()
    # fixture owns the already closed connection; remove its cleanup obligation
    lease.release=lambda: None; lease.close=lambda: None


def test_fresh_epoch_only_after_cycle_and_resource_cleanup(authority,monkeypatch):
    clock,path,factory=authority; warmer=warming.RLiveSnapshotWarmer(store_path=path)
    warmer._lease=factory(); first=warmer._lease; token=first._holder
    assert first.acquire(ttl_seconds=30)
    clock.current += timedelta(seconds=31)
    assert not first.renew(ttl_seconds=30)
    # Active acquisition retains its resources and prevents shutdown success.
    warmer._cycle_lock.acquire()
    try:
        with pytest.raises(ShutdownIncomplete): warmer.shutdown(0)
        assert warmer._lease is first
    finally: warmer._cycle_lock.release()
    warmer.shutdown(2)
    assert warmer._lease is None
    first.release=lambda: None; first.close=lambda: None
    fresh=factory()
    assert fresh._holder != token and fresh.acquire(ttl_seconds=30)
    assert publish(path,fresh)==1


def test_live_contention_admits_only_one_canonical_acquisition(authority,monkeypatch):
    clock,path,factory=authority
    first=warming.RLiveSnapshotWarmer(store_path=path); second=warming.RLiveSnapshotWarmer(store_path=path)
    first._lease=factory(); second._lease=factory()
    entered,finish=threading.Event(),threading.Event(); calls=[]; errors=[]
    def acquisition(*args,**kwargs):
        calls.append(kwargs['lease_holder']); entered.set()
        assert finish.wait(3)
        return {'state':'OK','written':0}
    monkeypatch.setattr(warming,'warm_snapshot_once',acquisition)
    def run():
        try:first.run_cycle(rpc_url='fixture')
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=run); thread.start()
    try:
        assert entered.wait(3)
        assert second.run_cycle(rpc_url='fixture') is None
        assert len(calls)==1
    finally:finish.set();thread.join(3)
    assert not thread.is_alive() and not errors


def test_fenced_payload_digest_and_freshness_identical(authority):
    clock,path,factory=authority; lease=factory(); assert lease.acquire(ttl_seconds=30)
    rows=[('asset','AVAILABLE',{'price':'1.25','observed_at':'original'}),('missing','UNAVAILABLE',{})]
    with lease.publication_guard(), snapshots.RLiveSnapshotStore(path=path) as store:
        assert store.write_batch(rows,collected_at=clock.current,lease_holder=lease._holder)==1
    fenced=snapshots.read_snapshots_readonly(path=path)
    with snapshots.RLiveSnapshotStore(path=path) as store:
        assert store.write_batch(rows,collected_at=clock.current)==1
    assert snapshots.read_snapshots_readonly(path=path)==fenced
    assert fenced[0]['payload']['data']==rows[0][2]
    assert fenced[0]['collected_at']==clock.current.isoformat()


def test_actual_sqlite_contention_crosses_expiry_before_clock_sample(authority):
    clock,path,factory=authority; lease=factory(); assert lease.acquire(ttl_seconds=30)
    blocker=sqlite3.connect(path); blocker.execute('BEGIN IMMEDIATE')
    entered=threading.Event(); done=threading.Event(); results=[]; samples=[]
    original=lease._conn
    class WaitingConnection(ConnectionHook):
        def execute(self,sql,*args):
            if sql=='BEGIN IMMEDIATE': entered.set()
            return super().execute(sql,*args)
    lease._conn=WaitingConnection(original,lambda sql:None)
    def sample():
        assert original.in_transaction
        samples.append(clock.current); return clock.current
    lease._clock=sample
    def renew():
        try:results.append(lease.renew(ttl_seconds=30))
        finally:done.set()
    worker=threading.Thread(target=renew); worker.start()
    try:
        assert entered.wait(3)
        assert not done.is_set() and samples==[]
        clock.current += timedelta(seconds=31)
    finally:blocker.rollback(); blocker.close(); worker.join(3)
    assert not worker.is_alive() and results==[False] and samples==[clock.current]


def test_real_cycle_never_reports_success_after_failed_heartbeat(authority,monkeypatch):
    clock,path,factory=authority; warmer=warming.RLiveSnapshotWarmer(store_path=path)
    lease=factory(); warmer._lease=lease
    from app.radar_rwa import r_live_service
    class Missed:
        def wait(self,period):
            clock.current+=timedelta(seconds=warmer.lease_ttl+1)
            return False
    def collect(**kwargs):
        warmer._renew_until(Missed())
        return [('asset','AVAILABLE',{'value':123})]
    monkeypatch.setattr(r_live_service,'collect_r_live_batch',collect)
    with pytest.raises(ShutdownIncomplete,match='lost publication authority'):
        warmer.run_cycle(rpc_url='fixture')
    assert warmer.last_summary is None and snapshots.read_snapshots_readonly(path=path)==[]
    with pytest.raises(ShutdownIncomplete,match='failed before clean shutdown'):warmer.shutdown(2)
    assert warmer._lease is None and not warmer._heartbeat.is_alive()
    lease.release=lambda:None;lease.close=lambda:None


@pytest.mark.parametrize('token',[None,'','different-epoch'])
def test_background_authority_cannot_bypass_fence_with_missing_token(authority,monkeypatch,token):
    clock,path,factory=authority; lease=factory(); assert lease.acquire(ttl_seconds=30)
    from app.radar_rwa import r_live_service
    monkeypatch.setattr(r_live_service,'collect_r_live_batch',lambda **kwargs:[('asset','AVAILABLE',{'value':123})])
    summary=warming.warm_snapshot_once('fixture',store_path=path,lease_holder=token,lease_authority=lease)
    assert summary['state']=='LEASE_OWNERSHIP_LOST' and summary['written']==0
    assert lease._lost and snapshots.read_snapshots_readonly(path=path)==[]


def test_publication_database_error_permanently_invalidates_local_epoch(authority):
    clock,path,factory=authority; lease=factory(); assert lease.acquire(ttl_seconds=30)
    with pytest.raises(sqlite3.OperationalError), lease.publication_guard():
        raise sqlite3.OperationalError('publication unavailable')
    assert lease._lost and not lease.renew(ttl_seconds=30)
    with pytest.raises(snapshots.LeaseOwnershipLost):publish(path,lease)
