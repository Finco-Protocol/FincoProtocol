from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .freshness import evaluate_freshness
from .registry import YieldRegistry
from .underwriting import decompose, run_scenario

@dataclass(frozen=True)
class ExploreFilters:
    chain_id:int|None=None
    protocol:str|None=None
    asset:str|None=None
    category:str|None=None
    minimum_tvl_usd:Decimal|None=None
    minimum_history_days:int|None=None
    max_reward_dependency:Decimal|None=None
    exit_type:str|None=None
    evidence_confidence:str|None=None

def _asset_category(symbol:str,category:str|None)->bool:
    if not category: return True
    sym=symbol.lower(); category=category.lower()
    stable={"usdc","usdt","dai","usdg","usds","eurc"}; major={"eth","weth","btc","wbtc","cbeth","wsteth"}
    return sym in (stable if category=="stablecoin" else major if category=="major" else {sym})

def explore(registry:YieldRegistry,*,filters:ExploreFilters|None=None,history_days_by_uid:dict[str,int]|None=None):
    filters=filters or ExploreFilters(); history_days_by_uid=history_days_by_uid or {}; rows=[]
    for o in registry.all():
        if filters.chain_id is not None and o.chain_id!=filters.chain_id: continue
        if filters.protocol and o.protocol!=filters.protocol.strip().lower(): continue
        if filters.asset and o.underlying_symbol.lower()!=filters.asset.strip().lower(): continue
        if not _asset_category(o.underlying_symbol,filters.category): continue
        if filters.minimum_tvl_usd is not None and (o.observation.tvl_usd is None or o.observation.tvl_usd<filters.minimum_tvl_usd): continue
        if filters.minimum_history_days is not None and history_days_by_uid.get(o.uid,0)<filters.minimum_history_days: continue
        dependency=decompose(o.observation).reward_dependency
        if filters.max_reward_dependency is not None and (dependency is None or dependency>filters.max_reward_dependency): continue
        if filters.exit_type and (o.observation.withdrawal_type or "UNKNOWN").upper()!=filters.exit_type.upper(): continue
        if filters.evidence_confidence and o.source_type.value!=filters.evidence_confidence.upper(): continue
        rows.append(o)
    rows.sort(key=lambda x:(x.underlying_symbol.lower(),x.name.lower(),x.uid))
    return tuple(rows)

@dataclass(frozen=True)
class CompareRow:
    opportunity_uid:str; name:str; protocol:str; chain_id:int; underlying_symbol:str
    tvl_usd:Decimal|None; gross_apy:Decimal|None; base_apy:Decimal|None; rewards_apy:Decimal|None; intrinsic_apy:Decimal|None
    reward_dependency:Decimal|None; evidence_confidence:str; freshness:str; exit_type:str; fee_bps:Decimal|None; dependency_count:int
    rewards_off_apy:Decimal|None; rewards_minus_50_apy:Decimal|None; exit_stress_state:str; gas_shock_state:str

def compare(registry:YieldRegistry,uids:list[str]|tuple[str,...])->tuple[CompareRow,...]:
    if not 1<=len(uids)<=4: raise ValueError("compare accepts 1 to 4 exact opportunity UIDs")
    if len(set(uids))!=len(uids): raise ValueError("duplicate opportunity UIDs are not allowed")
    out=[]
    for uid in uids:
        o=registry.resolve(uid); d=decompose(o.observation)
        source=__import__("finco_yield.schema",fromlist=["SourceReference"]).SourceReference(o.source_type,o.source_uri,o.observed_at,o.block_number,o.adapter,o.adapter_version)
        r0=run_scenario("REWARDS_OFF",o.observation); r50=run_scenario("REWARDS_MINUS_50",o.observation); ex=run_scenario("EXIT_STRESS",o.observation); gas=run_scenario("GAS_SHOCK",o.observation)
        out.append(CompareRow(uid,o.name,o.protocol,o.chain_id,o.underlying_symbol,o.observation.tvl_usd,o.observation.apy_total,o.observation.apy_base,o.observation.apy_rewards,o.observation.apy_intrinsic,d.reward_dependency,o.source_type.value,evaluate_freshness(source).state,(o.observation.withdrawal_type or "UNKNOWN").upper(),o.observation.fee_bps,0,r0.apy,r50.apy,ex.state.value,gas.state.value))
    return tuple(out)
