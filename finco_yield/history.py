from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

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

class YieldHistoryStore:
    """Append-only JSONL history. Corrections append a superseding record."""
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
