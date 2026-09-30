from pathlib import Path
import json
from typing import Protocol

class Adapter(Protocol):
    name: str
    def discover(self, *, chain_id:int, limit:int=20): ...

def discover_isolated(adapters:list[Adapter], *, chain_id:int, limit:int=20):
    opportunities=[]; errors={}
    for adapter in adapters:
        try: opportunities.extend(adapter.discover(chain_id=chain_id,limit=limit))
        except Exception as exc: errors[adapter.name]=f"{type(exc).__name__}: {exc}"
    return opportunities[:limit], errors

def load_bundled_sample()->list[dict]:
    path=Path(__file__).resolve().parent/"data"/"live_opportunities.json"
    return json.loads(path.read_text(encoding="utf-8"))
