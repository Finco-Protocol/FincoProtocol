from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib, json
from typing import Any

def _primitive(value: Any) -> Any:
    if is_dataclass(value): return _primitive(asdict(value))
    if isinstance(value, dict): return {str(k): _primitive(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [_primitive(v) for v in value]
    if isinstance(value, Decimal): return format(value, "f")
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, Enum): return value.value
    return value

def canonical_json(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()

@dataclass(frozen=True)
class YieldEvidenceRecord:
    yield_opportunity_uid: str
    evidence: Any
    normalized_inputs: Any
    assumptions: Any
    outputs: Any
    calculation_version: str

    @property
    def canonical_input_hash(self) -> str:
        return sha256_canonical({"evidence":self.evidence,"normalized_inputs":self.normalized_inputs,"assumptions":self.assumptions,"calculation_version":self.calculation_version})

    @property
    def canonical_output_hash(self) -> str:
        return sha256_canonical({"input_hash":self.canonical_input_hash,"outputs":self.outputs,"calculation_version":self.calculation_version})
