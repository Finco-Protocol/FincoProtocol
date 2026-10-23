"""Independent Linux supervisor cleanup, including orphaned setsid descendants."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import signal
import sys
import time


def enable_subreaper():
    if sys.platform != 'linux':
        raise RuntimeError('independent CI descendant cleanup requires Linux')
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(),'cannot establish CI child subreaper')


def children():
    result=[]
    # Some supported Linux kernels omit task/*/children. Enumerate proc stat
    # instead: PPID is authoritative for live and adopted children, including
    # setsid descendants. An inaccessible stat is an error, never clean evidence.
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            text=(entry/'stat').read_text();fields=text[text.rfind(')')+2:].split()
        except (FileNotFoundError,ProcessLookupError):
            continue
        if int(fields[1])==os.getpid():
            result.append({'pid':int(entry.name),'state':fields[0],'start_ticks':int(fields[19])})
    return sorted(result,key=lambda p:p['pid'])



def reap():
    while True:
        try:
            if os.waitpid(-1,os.WNOHANG)[0]==0:return
        except ChildProcessError:return


def finish_cleanup():
    """A found survivor is a failure even if subsequent forced cleanup succeeds."""
    reap();observed=children()
    deadline=time.monotonic()+5
    for sig in (signal.SIGTERM,signal.SIGKILL):
        while True:
            reap();live=children()
            if not live:break
            for item in live:
                try:os.kill(item['pid'],sig)
                except ProcessLookupError:pass
            until=min(deadline,time.monotonic()+(1 if sig==signal.SIGTERM else .1))
            while time.monotonic()<until:
                reap()
                if not children():break
                time.sleep(.02)
            if sig==signal.SIGTERM or time.monotonic()>=deadline:break
    reap();remaining=children()
    return {'mechanism':'linux-subreaper-proc-waitpid-v1','cleanup_verified':not observed and not remaining,
            'survivors_observed':observed,'survivors_remaining':remaining}
