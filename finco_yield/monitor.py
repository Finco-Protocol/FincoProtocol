from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .freshness import evaluate_freshness
from .onchain import OnchainReadError, read_share_balance, rpc_url_for_chain
from .registry import YieldRegistry
from .schema import SourceReference

@dataclass(frozen=True)
class WalletYieldPosition:
    opportunity_uid:str
    name:str
    chain_id:int
    share_token:str
    balance_raw:int
    balance:Decimal
    observed_apy:Decimal|None
    exit_state:str
    evidence_freshness:str
    block_number:int
    position_value:Decimal|None=None
    estimated_earned:Decimal|None=None

async def detect_positions(registry:YieldRegistry,*,wallet_address:str)->tuple[WalletYieldPosition,...]:
    """Read-only. Wallet ownership is context, never signing or token-entitlement authority."""
    positions=[]
    for o in registry.all():
        rpc=rpc_url_for_chain(o.chain_id)
        if not rpc: continue
        try:
            raw,decimals,block=await read_share_balance(chain_id=o.chain_id,token_address=o.share_token,wallet_address=wallet_address,rpc_url=rpc)
        except OnchainReadError:
            continue
        if raw<=0: continue
        source=SourceReference(o.source_type,o.source_uri,o.observed_at,o.block_number,o.adapter,o.adapter_version)
        positions.append(WalletYieldPosition(o.uid,o.name,o.chain_id,o.share_token,raw,Decimal(raw)/(Decimal(10)**decimals),o.observation.apy_total,(o.observation.withdrawal_type or "UNKNOWN").upper(),evaluate_freshness(source).state,block))
    return tuple(positions)
