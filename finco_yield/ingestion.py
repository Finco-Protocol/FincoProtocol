from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Protocol

class Adapter(Protocol):
    name:str
    def discover(self,*,chain_id:int,limit:int=20): ...

@dataclass(frozen=True)
class AdapterFailure:
    adapter:str
    code:str
    public_message:str

_SECRET_PATTERNS=(
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[^\s,;]+"),
    re.compile(r"(?i)(authorization|x-api-key|api[-_]?key)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"https?://[^\s]*[?&](?:key|token|signature|sig)=[^&\s]+",re.I),
)

def sanitize_adapter_error(exc:Exception)->str:
    message=str(exc)[:500]
    for pattern in _SECRET_PATTERNS: message=pattern.sub("[REDACTED]",message)
    return message.replace("\n"," ").replace("\r"," ")[:240]

def classify_adapter_error(exc:Exception)->str:
    text=str(exc).lower(); name=type(exc).__name__.lower()
    if "timeout" in text or "timeout" in name: return "TIMEOUT"
    if "401" in text or "403" in text: return "AUTH_UNAVAILABLE"
    if "429" in text: return "RATE_LIMITED"
    if any(code in text for code in ("500","502","503","504")): return "PROVIDER_UNAVAILABLE"
    if "json" in text or "decode" in text: return "MALFORMED_RESPONSE"
    return "ADAPTER_UNAVAILABLE"

def discover_isolated(adapters:list[Adapter],*,chain_id:int,limit:int=20):
    opportunities=[]; failures=[]
    for adapter in adapters:
        try: opportunities.extend(adapter.discover(chain_id=chain_id,limit=limit))
        except Exception as exc:
            failures.append(AdapterFailure(getattr(adapter,"name","unknown"),classify_adapter_error(exc),"Yield source temporarily unavailable."))
    return opportunities[:limit],tuple(failures)

def load_bundled_sample()->list[dict]:
    path=Path(__file__).resolve().parent/"data"/"live_opportunities.json"
    return json.loads(path.read_text(encoding="utf-8"))
