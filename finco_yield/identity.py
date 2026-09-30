from dataclasses import dataclass
import hashlib
import json
import re

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")

def canonical_address(value: str) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        raise ValueError("EVM address must be exact 0x + 40 hex characters")
    return value.lower()

def _clean_slug(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    cleaned = value.strip().lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z0-9_.-]+", cleaned):
        raise ValueError(f"invalid {field}")
    return cleaned

@dataclass(frozen=True)
class YieldIdentity:
    chain_id: int
    protocol: str
    product_type: str
    contract_address: str
    underlying_assets: tuple[str, ...]
    share_token: str | None = None

    def canonical(self) -> dict:
        if self.chain_id <= 0:
            raise ValueError("chain_id must be positive")
        assets = tuple(canonical_address(a) for a in self.underlying_assets)
        if not assets:
            raise ValueError("at least one underlying asset is required")
        return {
            "chain_id": int(self.chain_id),
            "protocol": _clean_slug(self.protocol, "protocol"),
            "product_type": _clean_slug(self.product_type, "product_type"),
            "contract_address": canonical_address(self.contract_address),
            "underlying_assets": sorted(set(assets)),
            "share_token": canonical_address(self.share_token) if self.share_token else None,
        }

def yield_opportunity_uid(identity: YieldIdentity) -> str:
    payload = json.dumps(identity.canonical(), sort_keys=True, separators=(",", ":"))
    return "yld_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
