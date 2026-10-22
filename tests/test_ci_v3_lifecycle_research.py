"""Characterize lifecycle gaps without changing product behavior or allowing leaks.

Owned test threads are always joined by the test. These passing characterizations
are evidence for a separate correction proposal, not shutdown-safety approval.
"""
import ast
import asyncio
from pathlib import Path
import sys
import threading
from types import ModuleType

from app.radar_rwa import r_live_warming as warming


class Lease:
    def __init__(self): self.released = self.closed = 0
    def acquire_or_renew(self, **kwargs): return True
    def release(self): self.released += 1
    def close(self): self.closed += 1


def test_stop_returns_during_inflight_work_and_residual_write_precedes_manual_join(monkeypatch):
    entered, finish = threading.Event(), threading.Event(); writes = []
    def acquisition(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        writes.append('completed after stop')
        return {'state': 'OK'}
    monkeypatch.setattr(warming, 'warm_snapshot_once', acquisition)
    monkeypatch.setenv('ROBINHOOD_RPC_URL', 'https://fixture.invalid/no-request-is-made')
    warmer = warming.RLiveSnapshotWarmer(interval_seconds=15, heartbeat_period_seconds=0.01)
    lease = Lease(); warmer._lease = lease
    try:
        assert warmer.start() and entered.wait(5)
        warmer.stop()
        assert warmer._thread.is_alive()  # current stop() does not join acquisition
        assert lease.released == lease.closed == 0 and not writes
        finish.set(); warmer._thread.join(5)
        assert not warmer._thread.is_alive()
        assert writes == ['completed after stop']
        assert lease.released == lease.closed == 1 and warmer._lease is None
    finally:
        finish.set(); warmer.stop()
        if warmer._thread: warmer._thread.join(5)
        assert not warmer._thread or not warmer._thread.is_alive()


def test_repeated_start_stop_needs_external_join_and_releases_each_lease(monkeypatch):
    monkeypatch.delenv('ROBINHOOD_RPC_URL', raising=False)
    warmer = warming.RLiveSnapshotWarmer(interval_seconds=15)
    for _ in range(3):
        entered = threading.Event(); lease = Lease(); warmer._lease = lease
        def cycle(): entered.set()
        monkeypatch.setattr(warmer, 'run_cycle', cycle)
        try:
            assert warmer.start() and entered.wait(5)
            assert not warmer.start()  # singleton while alive
            warmer.stop(); warmer._thread.join(5)
            assert not warmer._thread.is_alive() and lease.released == lease.closed == 1
        finally:
            warmer.stop(); warmer._thread.join(5)


def test_demo_startup_body_creates_another_unowned_thread_each_time(monkeypatch):
    # Execute the unchanged function body with a recording thread factory, not
    # main_web import/startup and not its sleeping/deleting background target.
    path = Path(__file__).resolve().parents[1] / 'main_web.py'
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_schedule_demo_cleanup')
    node.decorator_list = []
    recorded = []
    class Thread:
        def __init__(self, **kwargs): self.kwargs = kwargs; recorded.append(self)
        def start(self): self.started = True
    auth = ModuleType('app.auth'); auth.DEMO_TTL_HOURS = 24
    monkeypatch.setitem(sys.modules, 'app.auth', auth)
    monkeypatch.setattr(threading, 'Thread', Thread)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    asyncio.run(namespace['_schedule_demo_cleanup']()); asyncio.run(namespace['_schedule_demo_cleanup']())
    assert len(recorded) == 2 and all(t.started for t in recorded)
    assert all(t.kwargs['name'] == 'demo-cleanup' and t.kwargs['daemon'] for t in recorded)
