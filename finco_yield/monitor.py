from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .freshness import evaluate_freshness
from .identity import canonical_address
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

# Typed reasons a chain scan could not produce factual positions.
SCAN_RPC_NOT_CONFIGURED = "RPC_NOT_CONFIGURED"
SCAN_RPC_UNAVAILABLE = "RPC_UNAVAILABLE"
SCAN_WALLET_ADDRESS_INVALID = "WALLET_ADDRESS_INVALID"

@dataclass(frozen=True)
class ChainScanStatus:
    """Typed per-chain scan outcome — absence of evidence is not absence of positions."""
    chain_id:int
    opportunities:int
    reason:str|None      # SCAN_* when the chain could not be scanned factually

@dataclass(frozen=True)
class PositionScan:
    positions:tuple[WalletYieldPosition,...]
    chain_statuses:tuple[ChainScanStatus,...]

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        """Sorted distinct SCAN_* reasons — the typed 'unavailable' state."""
        return tuple(sorted({s.reason for s in self.chain_statuses if s.reason}))

    @property
    def scanned_factually(self) -> bool:
        """True only when every configured-Yield chain was actually scanned."""
        return not self.unavailable_reasons

async def detect_positions_scan(registry:YieldRegistry,*,wallet_address:str)->PositionScan:
    """Read-only multi-chain position scan with typed availability.

    A chain without configured RPC, an unreachable RPC, or an invalid wallet
    address is an UNAVAILABLE chain (typed) — never silently folded into
    "no positions".  Only a factual on-chain scan proving zero balances
    supports the empty-positions state.  Unexpected programming errors
    still propagate (no blanket swallowing).
    """
    positions:list[WalletYieldPosition]=[]
    statuses:list[ChainScanStatus]=[]
    try:
        canonical_address(wallet_address)
    except ValueError:
        # A stored wallet identity that fails canonical validation makes the
        # scan impossible on every chain: typed unavailable, never "no positions".
        return PositionScan(
            (),
            tuple(ChainScanStatus(o.chain_id, 0, SCAN_WALLET_ADDRESS_INVALID)
                  for o in registry.all()),
        )
    for o in registry.all():
        rpc=rpc_url_for_chain(o.chain_id)
        if not rpc:
            statuses.append(ChainScanStatus(o.chain_id,0,SCAN_RPC_NOT_CONFIGURED))
            continue
        try:
            raw,decimals,block=await read_share_balance(chain_id=o.chain_id,token_address=o.share_token,wallet_address=wallet_address,rpc_url=rpc)
        except OnchainReadError:
            statuses.append(ChainScanStatus(o.chain_id,0,SCAN_RPC_UNAVAILABLE))
            continue
        if raw<=0:
            statuses.append(ChainScanStatus(o.chain_id,1,None))
            continue
        source=SourceReference(o.source_type,o.source_uri,o.observed_at,o.block_number,o.adapter,o.adapter_version)
        positions.append(WalletYieldPosition(o.uid,o.name,o.chain_id,o.share_token,raw,Decimal(raw)/(Decimal(10)**decimals),o.observation.apy_total,(o.observation.withdrawal_type or "UNKNOWN").upper(),evaluate_freshness(source).state,block))
        statuses.append(ChainScanStatus(o.chain_id,1,None))
    return PositionScan(tuple(positions),tuple(statuses))

async def detect_positions(registry:YieldRegistry,*,wallet_address:str)->tuple[WalletYieldPosition,...]:
    """Backward-compatible view over :func:`detect_positions_scan`.

    Existing callers that only need the factual positions keep working; the
    monitor route uses the typed scan so unavailable RPC/config never reads
    as "no positions".
    """
    return (await detect_positions_scan(registry, wallet_address=wallet_address)).positions
