"""Owned lifecycle acceptance; deadlines never turn a surviving writer into PASS."""
import ast
import asyncio
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from app.background_lifecycle import RecurringService, ShutdownIncomplete
from app.radar_rwa import r_live_warming as warming


def test_demo_repeated_lifespans_interrupt_initial_wait_without_work():
    writes = []
    service = RecurringService(lambda: writes.append(1), name='demo-cleanup', initial_delay=300, interval=3600)
    for _ in range(3):
        assert service.start()
        assert not service.start()
        service.shutdown(1)
        assert not service._thread.is_alive()
    assert writes == []


def test_demo_inflight_timeout_retains_owner_until_work_finishes():
    entered, finish = threading.Event(), threading.Event()
    writes = []
    def operation():
        entered.set()
        assert finish.wait(5)
        writes.append(1)
    service = RecurringService(operation, name='demo-cleanup', initial_delay=0, interval=3600)
    try:
        assert service.start() and entered.wait(3)
        with pytest.raises(ShutdownIncomplete): service.shutdown(0)
        with pytest.raises(ShutdownIncomplete): service.start()
        assert service._thread.is_alive() and not writes
        finish.set(); service.shutdown(3)
        assert not service._thread.is_alive() and writes == [1]
        service.shutdown(0)
        assert writes == [1]
    finally:
        finish.set(); service.shutdown(3)


def test_warmer_repeated_real_sqlite_lifespans_release_lease(tmp_path, monkeypatch):
    monkeypatch.delenv('ROBINHOOD_RPC_URL', raising=False)
    path = str(tmp_path / 'snapshot.sqlite')
    for _ in range(3):
        warmer = warming.RLiveSnapshotWarmer(store_path=path)
        entered = threading.Event()
        original_cycle = warmer.run_cycle
        def cycle():
            result = original_cycle(); entered.set(); return result
        monkeypatch.setattr(warmer, 'run_cycle', cycle)
        assert warmer.start() and entered.wait(3)
        warmer.shutdown(3)
        assert not warmer._thread.is_alive()
        assert warmer._lease is None
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM r_live_warming_lease').fetchone()[0] == 0
        foreign = warming._SnapshotLease(path)
        try:
            assert foreign.acquire_or_renew(ttl_seconds=30)
            foreign.release()
        finally: foreign.close()


def test_warmer_inflight_timeout_cannot_release_lease_or_allow_replacement(tmp_path, monkeypatch):
    path = str(tmp_path / 'snapshot.sqlite')
    entered, finish = threading.Event(), threading.Event(); writes = []
    def acquire(*args, **kwargs):
        entered.set(); assert finish.wait(5)
        writes.append(1); return {'state':'OK'}
    monkeypatch.setenv('ROBINHOOD_RPC_URL', 'https://fixture.invalid')
    monkeypatch.setattr(warming, 'warm_snapshot_once', acquire)
    warmer = warming.RLiveSnapshotWarmer(store_path=path, heartbeat_period_seconds=.01)
    foreign = None
    try:
        assert warmer.start() and entered.wait(3)
        with pytest.raises(ShutdownIncomplete): warmer.shutdown(0)
        with pytest.raises(ShutdownIncomplete): warmer.start()
        foreign = warming._SnapshotLease(path)
        assert not foreign.acquire_or_renew(ttl_seconds=30)
        assert warmer._lease is not None and not writes
        finish.set(); warmer.shutdown(3)
        assert writes == [1] and warmer._lease is None
        assert not warmer._thread.is_alive() and not warmer._heartbeat.is_alive()
        assert foreign.acquire_or_renew(ttl_seconds=30)
        assert warmer.run_cycle(rpc_url='unused') is None
        assert writes == [1]
    finally:
        finish.set(); warmer.shutdown(3)
        if foreign is not None: foreign.release(); foreign.close()


def test_background_owner_cannot_stop_foreign_lifespan(tmp_path, monkeypatch):
    monkeypatch.setenv('FINCO_RLIVE_WARMING_ENABLED', '1')
    monkeypatch.delenv('ROBINHOOD_RPC_URL', raising=False)
    monkeypatch.setattr(warming, '_WARMER', None)
    monkeypatch.setattr(warming, '_WARMER_OWNER', None)
    factory = warming.RLiveSnapshotWarmer
    monkeypatch.setattr(warming, 'RLiveSnapshotWarmer', lambda: factory(store_path=str(tmp_path/'db')))
    owner, foreign = object(), object()
    try:
        assert warming.start_background_warmer(owner=owner)
        assert not warming.start_background_warmer(owner=owner)
        assert not warming.stop_background_warmer(owner=foreign)
        with pytest.raises(ShutdownIncomplete): warming.start_background_warmer(owner=foreign)
        assert warming.stop_background_warmer(owner=owner)
        assert warming._WARMER is None and warming._WARMER_OWNER is None
    finally: warming.stop_background_warmer(owner=owner)


def test_actual_web_demo_hooks_reuse_owned_service_and_shutdown():
    # Execute the actual application hooks without importing unrelated web routes.
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'main_web.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
             and n.name in ('_schedule_demo_cleanup','_stop_demo_cleanup')]
    for n in nodes: n.decorator_list = []
    namespace = {'app': SimpleNamespace(state=SimpleNamespace())}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main_web.py', 'exec'), namespace)
    for _ in range(3):
        asyncio.run(namespace['_schedule_demo_cleanup']())
        service = namespace['app'].state.demo_cleanup_service
        asyncio.run(namespace['_schedule_demo_cleanup']())
        assert namespace['app'].state.demo_cleanup_service is service
        asyncio.run(namespace['_stop_demo_cleanup']())
        assert not service._thread.is_alive()


def test_web_shutdown_attempts_both_owners_before_reporting_failure():
    tree = ast.parse((Path(__file__).resolve().parents[1]/'main_web.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_shutdown_background_services')
    node.decorator_list = []; called = []
    async def demo():
        called.append('demo'); raise ShutdownIncomplete('fixture blocked cleanup')
    async def warmer(): called.append('warmer')
    namespace = {'_stop_demo_cleanup':demo, '_stop_r_live_snapshot_warmer':warmer}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'main_web.py','exec'),namespace)
    with pytest.raises(ExceptionGroup): asyncio.run(namespace['_shutdown_background_services']())
    assert called == ['demo','warmer']


def test_sqlite_release_deadline_is_failure_until_cleanup_is_joined(tmp_path):
    path = str(tmp_path/'locked.sqlite')
    warmer = warming.RLiveSnapshotWarmer(store_path=path)
    warmer._lease = warming._SnapshotLease(path)
    assert warmer._lease.acquire_or_renew(ttl_seconds=30)
    blocker = sqlite3.connect(path)
    blocker.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(ShutdownIncomplete): warmer.shutdown(.01)
        assert warmer._lease is not None and warmer._cleanup_thread.is_alive()
        with pytest.raises(ShutdownIncomplete): warmer.start()
    finally:
        blocker.rollback(); blocker.close(); warmer.shutdown(3)
    assert warmer._lease is None and not warmer._cleanup_thread.is_alive()


def test_concurrent_shutdown_lock_does_not_escape_deadline():
    warmer = warming.RLiveSnapshotWarmer()
    warmer._lifecycle_lock.acquire()
    try:
        with pytest.raises(ShutdownIncomplete,match='lock deadline'): warmer.shutdown(0)
    finally: warmer._lifecycle_lock.release()


def test_partial_web_startup_rolls_back_demo_owner(monkeypatch):
    tree = ast.parse((Path(__file__).resolve().parents[1]/'main_web.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_start_r_live_snapshot_warmer')
    node.decorator_list=[];called=[]
    def fail(**kwargs): raise ShutdownIncomplete('foreign owner')
    monkeypatch.setattr(warming,'start_background_warmer',fail)
    async def stop():called.append('demo stopped')
    namespace={'app':SimpleNamespace(state=SimpleNamespace()),'_stop_demo_cleanup':stop}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'main_web.py','exec'),namespace)
    with pytest.raises(ShutdownIncomplete):asyncio.run(namespace['_start_r_live_snapshot_warmer']())
    assert called==['demo stopped']


def test_expired_or_foreign_lease_cannot_publish_snapshot(tmp_path):
    from datetime import datetime,timedelta,timezone
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore,LeaseOwnershipLost
    path=str(tmp_path/'fenced.sqlite'); lease=warming._SnapshotLease(path)
    try:
        assert lease.acquire_or_renew(ttl_seconds=30)
        rows=[('fixture-id','AVAILABLE',{'value':123})]
        with RLiveSnapshotStore(path=path) as store:
            with pytest.raises(LeaseOwnershipLost):store.write_batch(rows,lease_holder='foreign')
            assert store._read()==[]
            with sqlite3.connect(path) as db:
                db.execute('UPDATE r_live_warming_lease SET expires_at=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
            with pytest.raises(LeaseOwnershipLost):store.write_batch(rows,lease_holder=lease._holder)
            assert store._read()==[]
            assert lease.acquire_or_renew(ttl_seconds=30)
            assert store.write_batch(rows,lease_holder=lease._holder)==1
            assert len(store._read())==1
    finally:lease.release();lease.close()


def test_direct_cycle_admission_before_lease_creation_cannot_escape_shutdown(tmp_path,monkeypatch):
    entered,finish=threading.Event(),threading.Event();writes=[]
    warmer=warming.RLiveSnapshotWarmer(store_path=str(tmp_path/'race.sqlite'))
    original=warmer._lease_or_none
    def gated_lease():
        entered.set();assert finish.wait(5);return original()
    monkeypatch.setattr(warmer,'_lease_or_none',gated_lease)
    monkeypatch.setattr(warming,'warm_snapshot_once',lambda *args,**kwargs: writes.append(1) or {'state':'OK'})
    cycle=threading.Thread(target=lambda:warmer.run_cycle(rpc_url='fixture://offline'))
    try:
        cycle.start();assert entered.wait(3)
        assert warmer._lease is None
        with pytest.raises(ShutdownIncomplete):warmer.shutdown(.01)
        assert not writes
        finish.set();cycle.join(3);warmer.shutdown(3)
        assert not cycle.is_alive() and writes==[1] and warmer._lease is None
    finally:
        finish.set();cycle.join(3);warmer.shutdown(3)
