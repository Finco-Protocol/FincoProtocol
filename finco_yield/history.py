from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import json
from typing import Any, Iterator

from .durable_io import write_all
from .evidence_v1 import canonical_hash, canonical_json

@dataclass(frozen=True)
class ImmutableObservationRecord:
    opportunity_uid:str
    observed_at:datetime
    source_authority:str
    source_uri:str
    adapter_version:str
    payload:dict[str,Any]
    supersedes:str|None=None
    schema_version:str="YIELD_OBSERVATION_V1"
    @property
    def observation_hash(self)->str:
        return canonical_hash(self)

class HistoryCorruptionError(RuntimeError):
    """The history file is structurally unsafe to append to (fail closed)."""


def _row_time(row: dict[str, Any]) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(row.get("observed_at")).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return moment.astimezone(timezone.utc) if moment.tzinfo else None


def _as_utc(value: datetime | str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return moment.astimezone(timezone.utc)


class YieldHistoryStore:
    """Append-only JSONL history. Corrections append a superseding record.

    This is THE canonical Yield observation history.  Besides ``append`` it
    exposes one small deterministic read interface used by Yield Alerts and the
    future Yield Intelligence stream: ``latest``, ``prior`` and ``window``.
    """
    def __init__(self,path:str|Path): self.path=Path(path)
    def read_all(self)->list[dict[str,Any]]:
        if not self.path.exists(): return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    def append(self,record:ImmutableObservationRecord)->str:
        if record.observed_at.tzinfo is None: raise ValueError("observed_at must be timezone-aware")
        known={row["observation_hash"] for row in self.read_all()}
        if record.supersedes is not None and record.supersedes not in known: raise ValueError("supersedes must reference an existing observation")
        payload=asdict(record)
        payload["observed_at"]=record.observed_at.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        payload["observation_hash"]=record.observation_hash
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a",encoding="utf-8") as handle: handle.write(canonical_json(payload)+"\n")
        return record.observation_hash
    def for_opportunity(self,uid:str)->tuple[dict[str,Any],...]:
        return tuple(row for row in self.read_all() if row.get("opportunity_uid")==uid)

    # ── idempotent append (collector path) ─────────────────────────────────
    @contextmanager
    def _exclusive(self)->Iterator[None]:
        """Cross-process writer lock (advisory) so concurrent collectors cannot
        interleave appends."""
        self.path.parent.mkdir(parents=True,exist_ok=True)
        lock_path=self.path.with_name(self.path.name+".lock")
        import fcntl
        with open(lock_path,"a+") as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle,fcntl.LOCK_UN)

    def append_idempotent(self,record:ImmutableObservationRecord)->tuple[str,bool]:
        """Append unless an identical observation (same hash) already exists.

        Returns ``(observation_hash, appended)``.  Existing rows are never
        rewritten.  A file whose last line is not newline-terminated (torn
        write) is refused rather than extended.
        """
        if record.observed_at.tzinfo is None: raise ValueError("observed_at must be timezone-aware")
        digest=record.observation_hash
        with self._exclusive():
            if self.path.exists() and self.path.stat().st_size>0:
                with self.path.open("rb") as handle:
                    handle.seek(-1,os.SEEK_END)
                    if handle.read(1)!=b"\n": raise HistoryCorruptionError("history file is not newline-terminated")
            rows=self.read_all()
            known={row.get("observation_hash") for row in rows}
            if digest in known: return digest,False
            if record.supersedes is not None and record.supersedes not in known: raise ValueError("supersedes must reference an existing observation")
            payload=asdict(record)
            payload["observed_at"]=record.observed_at.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
            payload["observation_hash"]=digest
            line=(canonical_json(payload)+"\n").encode("utf-8")
            fd=os.open(self.path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o640)
            try:
                start=os.fstat(fd).st_size
                try:
                    write_all(fd,line)      # full line or failure; never a deliberate partial
                    os.fsync(fd)
                except BaseException:
                    # We hold the exclusive lock: restore the pre-append size so a
                    # failed write cannot leave a torn canonical JSONL record.
                    try:
                        os.ftruncate(fd,start); os.fsync(fd)
                    except OSError: pass
                    raise
            finally: os.close(fd)
        return digest,True

    # ── canonical read interface ───────────────────────────────────────────
    def window(self,uid:str,*,since:datetime|str|None=None,until:datetime|str|None=None)->tuple[dict[str,Any],...]:
        """Observations for ``uid`` with ``since <= observed_at <= until``,
        ordered by observed_at then file order.  Rows with unparseable
        timestamps are excluded (never coerced)."""
        lo=_as_utc(since) if since is not None else None
        hi=_as_utc(until) if until is not None else None
        selected=[]
        for order,row in enumerate(self.read_all()):
            if row.get("opportunity_uid")!=uid: continue
            moment=_row_time(row)
            if moment is None: continue
            if lo is not None and moment<lo: continue
            if hi is not None and moment>hi: continue
            selected.append((moment,order,row))
        selected.sort(key=lambda item:(item[0],item[1]))
        return tuple(row for _,_,row in selected)

    def latest(self,uid:str)->dict[str,Any]|None:
        rows=self.window(uid)
        return rows[-1] if rows else None

    def prior(self,uid:str,*,before:datetime|str,limit:int=1)->tuple[dict[str,Any],...]:
        """Up to ``limit`` observations strictly before ``before`` (most recent
        last)."""
        if limit<1: raise ValueError("limit must be >= 1")
        cutoff=_as_utc(before)
        rows=[row for row in self.window(uid) if _row_time(row)<cutoff]
        return tuple(rows[-limit:])

def history_window_summary(rows)->dict[str,Any]:
    times=[]
    for row in rows:
        try:
            dt=datetime.fromisoformat(str(row.get("observed_at")).replace("Z","+00:00"))
            if dt.tzinfo: times.append(dt.astimezone(timezone.utc))
        except (ValueError,TypeError): pass
    if not times: return {"observation_count":0,"history_days":0,"available_windows":[]}
    span=(max(times)-min(times)).total_seconds()/86400
    windows=[]
    if span>=7: windows.append("7d")
    if span>=30: windows.append("30d")
    return {"observation_count":len(times),"history_days":int(span),"available_windows":windows}
