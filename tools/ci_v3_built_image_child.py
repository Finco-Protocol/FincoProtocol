"""Independent descendant supervisor for run-built private CI containers."""
import sys
from pathlib import Path
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.ci_process_cleanup import enable_subreaper, finish_cleanup
from tools.ci_v3_schema import write_json

def finalize_multiprocessing(timeout=5):
    """Join this interpreter's stdlib IPC helpers before its parent checks orphans.

    Spawn closes its resource-tracker pipe only at interpreter exit by default.
    That races an immediate independent orphan check. Close/join the actual
    owned handles; never permit a process by its name or kill application work.
    """
    import multiprocessing as mp
    import threading
    live=[t.name for t in threading.enumerate() if t is not threading.current_thread() and t.is_alive()]
    children=mp.active_children()
    if live or children:
        return {'verified':False,'reason':'application work remains','threads':live,'children':[p.pid for p in children]}
    from multiprocessing import resource_tracker, forkserver, util
    tracker=resource_tracker._resource_tracker
    server=forkserver._forkserver
    result={'verified':False,'tracker_pid_before':tracker._pid,'forkserver_pid_before':server._forkserver_pid}
    def close():
        try:
            import gc
            gc.collect()
            # Flush registered IPC finalizers before closing the tracker they use.
            # Do not run _exit_function: it would terminate/join app children.
            util._run_finalizers()
            server._stop()
            tracker._stop()
            result.update(tracker_pid_after=tracker._pid,forkserver_pid_after=server._forkserver_pid,
                          verified=tracker._pid is None and server._forkserver_pid is None)
        except BaseException as exc:
            result.update(verified=False,error=type(exc).__name__+': '+str(exc))
    finalizer=threading.Thread(target=close,name='ci-owned-ipc-finalize',daemon=True)
    finalizer.start();finalizer.join(timeout)
    if finalizer.is_alive():
        return {**result,'verified':False,'error':'owned IPC shutdown exceeded deadline'}
    return dict(result)

if __name__ == '__main__':
    enable_subreaper()
    code = subprocess.call([sys.executable, '-I', str(Path(__file__).with_name('ci_v3_real_child.py')), sys.argv[1]])
    cleanup = finish_cleanup()
    write_json(Path(sys.argv[1]).parent/'descendant-cleanup.json', cleanup)
    raise SystemExit(code if code else (0 if cleanup['cleanup_verified'] else 125))
