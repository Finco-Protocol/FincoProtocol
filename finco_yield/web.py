"""FINCO Yield V1 beta product surface. Global nav/status remains owned by Product Truth PR #147."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .evidence_v1 import build_evidence, canonical_json
from .execution import ExecutionIntent, ExecutionValidationError, build_direct_erc4626_deposit, build_pre_trade_evidence, validate_quote
from .explore import ExploreFilters, compare, explore
from .flags import execution_enabled, yield_enabled
from .freshness import evaluate_freshness
from .history import YieldHistoryStore, history_window_summary
from .monitor import detect_positions
from .onchain import OnchainReadError, read_allowance, read_erc4626, rpc_url_for_chain
from .registry import RegistryError, load_bundled_registry
from .schema import SourceReference
from .underwriting import decompose, run_scenario

router=APIRouter(prefix="/yield",tags=["yield-beta"])

_STYLE="""<style>body{font-family:Inter,system-ui,sans-serif;background:#f8fafc;color:#111827;margin:0}.y{max-width:1180px;margin:auto;padding:28px 18px 64px}.k{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#6b7280}.sub{color:#4b5563}.nav{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 22px}.a,.btn{display:inline-block;border:1px solid #d1d5db;border-radius:7px;padding:8px 12px;text-decoration:none;color:#1f2937;background:white;font-weight:600}.btn{background:#1a56db;color:white;border:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.card,.filters{background:white;border:1px solid #e5e7eb;border-radius:10px;padding:15px}.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:16px}.filters input,.filters select{padding:8px;border:1px solid #d1d5db;border-radius:6px}table{width:100%;border-collapse:collapse;background:white}th,td{padding:10px;border-bottom:1px solid #eef2f7;text-align:left;font-size:13px;white-space:nowrap}th{font-size:11px;text-transform:uppercase;color:#6b7280}.scroll{overflow:auto;border:1px solid #e5e7eb;border-radius:10px}.badge{border:1px solid #d1d5db;border-radius:999px;padding:3px 7px;font-size:11px}.warn{border-left:4px solid #f59e0b;background:#fffbeb;padding:10px}.bound{border-left:4px solid #1a56db;background:#eff6ff;padding:10px;margin-top:18px}.hash{font-family:monospace;word-break:break-all;font-size:11px}@media(max-width:700px){.y{padding:20px 12px}.filters,.grid{grid-template-columns:1fr}}</style>"""

def _require():
    if not yield_enabled(): raise HTTPException(404,"FINCO Yield is not enabled.")

def _source(o): return SourceReference(o.source_type,o.source_uri,o.observed_at,o.block_number,o.adapter,o.adapter_version)
def _pct(v): return "—" if v is None else f"{v*Decimal(100):.2f}%"
def _usd(v): return "—" if v is None else f"${v:,.0f}"
def _chain(cid): return {1:"Ethereum",8453:"Base",4663:"Robinhood"}.get(cid,str(cid))
def _page(title,body): return f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="stylesheet" href="/static/css/protocol-shell.css">{_STYLE}</head><body><main class="y">{body}</main></body></html>'
def _d(v):
    if v in (None,""): return None
    try: return Decimal(str(v))
    except InvalidOperation as exc: raise HTTPException(400,"Invalid decimal filter") from exc

@router.get("",response_class=HTMLResponse)
async def yield_explore(request:Request,chain_id:int|None=None,protocol:str|None=None,asset:str|None=None,category:str|None=None,min_tvl:str|None=None,min_history_days:int|None=None,max_reward_dependency:str|None=None,evidence:str|None=None):
    _require(); registry=load_bundled_registry(); history_days={}; path=os.getenv("FINCO_YIELD_HISTORY_PATH","").strip()
    if path:
        store=YieldHistoryStore(path)
        for o in registry.all(): history_days[o.uid]=history_window_summary(store.for_opportunity(o.uid))["history_days"]
    rows=explore(registry,filters=ExploreFilters(chain_id,protocol,asset,category,_d(min_tvl),min_history_days,_d(max_reward_dependency),None,evidence),history_days_by_uid=history_days)
    tr=[]
    for o in rows:
        fresh=evaluate_freshness(_source(o)).state
        tr.append(f'<tr><td><a href="/yield/{o.uid}">{o.name}</a><br><small>{o.underlying_symbol}</small></td><td>{o.protocol}</td><td>{_chain(o.chain_id)}</td><td>{_usd(o.observation.tvl_usd)}</td><td>{_pct(o.observation.apy_total)}</td><td>{_pct(o.observation.apy_base)}</td><td>{_pct(o.observation.apy_rewards)}</td><td><span class="badge">{o.source_type.value}</span></td><td>{(o.observation.withdrawal_type or "UNKNOWN").upper()}</td><td><span class="badge">{fresh}</span></td></tr>')
    body=f'''<p class="k">FINCO Yield · V1 Beta</p><h1>Explore</h1><p class="sub">Evidence-backed DeFi opportunities. Source confidence and freshness stay visible; FINCO does not rank a winner.</p><div class="nav"><a class="a" href="/">FINCO</a><a class="a" href="/yield/monitor">Wallet Monitor</a></div><form class="filters"><select name="chain_id"><option value="">All chains</option><option value="1">Ethereum</option><option value="8453">Base</option></select><input name="protocol" placeholder="Protocol"><input name="asset" placeholder="Asset"><select name="category"><option value="">All assets</option><option value="stablecoin">Stablecoin</option><option value="major">Major</option></select><input name="min_tvl" placeholder="Min TVL USD"><input name="min_history_days" placeholder="Min history days"><input name="max_reward_dependency" placeholder="Max reward dependency"><select name="evidence"><option value="">All evidence</option><option>NATIVE_ENRICHED</option><option>DIRECT_ONCHAIN</option><option>THIRD_PARTY_REFERENCE</option></select><button class="btn">Filter</button></form><div class="scroll"><table><thead><tr><th>Opportunity</th><th>Protocol</th><th>Chain</th><th>TVL</th><th>Total APY</th><th>Base APY</th><th>Rewards APY</th><th>Evidence</th><th>Exit</th><th>Freshness</th></tr></thead><tbody>{''.join(tr) or '<tr><td colspan="10">No exact matches.</td></tr>'}</tbody></table></div><p class="bound">Read-only by default. Execution planning is separately gated. FINCO never custodies assets, holds private keys, auto-invests or rebalances.</p>'''
    return _page("FINCO Yield — Explore",body)

@router.get("/compare",response_class=HTMLResponse)
async def yield_compare(uid:list[str]=Query(default=[])):
    _require()
    try: rows=compare(load_bundled_registry(),uid)
    except (ValueError,RegistryError) as exc: raise HTTPException(400,str(exc)) from exc
    heads="".join(f"<th>{r.name}</th>" for r in rows)
    def line(label,fn): return f"<tr><th>{label}</th>"+"".join(f"<td>{fn(r)}</td>" for r in rows)+"</tr>"
    table=line("Chain",lambda r:_chain(r.chain_id))+line("TVL",lambda r:_usd(r.tvl_usd))+line("Total APY",lambda r:_pct(r.gross_apy))+line("Base APY",lambda r:_pct(r.base_apy))+line("Rewards APY",lambda r:_pct(r.rewards_apy))+line("Reward dependency",lambda r:"UNAVAILABLE" if r.reward_dependency is None else str(r.reward_dependency))+line("Evidence",lambda r:r.evidence_confidence)+line("Freshness",lambda r:r.freshness)+line("Exit",lambda r:r.exit_type)+line("Rewards off",lambda r:_pct(r.rewards_off_apy))+line("Rewards -50%",lambda r:_pct(r.rewards_minus_50_apy))+line("Exit stress",lambda r:r.exit_stress_state)+line("Gas shock",lambda r:r.gas_shock_state)
    return _page("FINCO Yield — Compare",f'<p class="k">FINCO Yield · Compare</p><h1>Side-by-side mechanics</h1><p class="sub">Up to four exact opportunities. No winner, score or recommendation is generated.</p><div class="nav"><a class="a" href="/yield">← Explore</a></div><div class="scroll"><table><thead><tr><th>Metric</th>{heads}</tr></thead><tbody>{table}</tbody></table></div>')

@router.get("/monitor",response_class=HTMLResponse)
async def yield_monitor(request:Request):
    _require(); from app.auth import resolve_request_session; from app.protocol.wallet_auth import get_verified_wallet
    user=resolve_request_session(request)
    if not user: return RedirectResponse("/login",302)
    wallet=get_verified_wallet(user.user_id); cards=[]
    if wallet:
        positions=await detect_positions(load_bundled_registry(),wallet_address=wallet["wallet_address"])
        for p in positions: cards.append(f'<section class="card"><h2>{p.name}</h2><p>Share balance: {p.balance}</p><p>Observed APY: {_pct(p.observed_apy)}</p><p>Exit: {p.exit_state}</p><p>Evidence freshness: {p.evidence_freshness}</p><p>Position value: UNAVAILABLE</p><p>Estimated earned: UNAVAILABLE</p></section>')
    info='No verified FINCO wallet is linked. Yield reuses the existing wallet verification flow.' if not wallet else f'Verified wallet {wallet["wallet_address"]}. Ownership is read-only context, not signing authority and not $FINCO entitlement.'
    return _page("FINCO Yield — Monitor",f'<p class="k">FINCO Yield · Wallet Monitor</p><h1>Read-only positions</h1><div class="nav"><a class="a" href="/yield">← Explore</a></div><p class="sub">{info}</p><div class="grid">{"".join(cards) or "<p>No supported non-zero vault-share positions detected on configured Yield RPC chains.</p>"}</div><p class="bound">Wallet ownership ≠ transaction signing ≠ $FINCO entitlement.</p>')

@router.get("/{opportunity_uid}/evidence.json")
async def evidence_json(opportunity_uid:str):
    _require()
    try: e=build_evidence(load_bundled_registry().resolve(opportunity_uid))
    except RegistryError as exc: raise HTTPException(404,"Unknown Yield opportunity") from exc
    payload=json.loads(canonical_json(e)); payload["canonical_input_hash"]=e.canonical_input_hash; payload["canonical_output_hash"]=e.canonical_output_hash
    return JSONResponse(payload)

@router.get("/{opportunity_uid}/history.json")
async def history_json(opportunity_uid:str):
    _require(); registry=load_bundled_registry()
    try: registry.resolve(opportunity_uid)
    except RegistryError as exc: raise HTTPException(404,"Unknown Yield opportunity") from exc
    path=os.getenv("FINCO_YIELD_HISTORY_PATH","").strip()
    if not path: return {"schema":"YIELD_HISTORY_V1","observations":[],"status":"HISTORY_NOT_CONFIGURED"}
    rows=YieldHistoryStore(path).for_opportunity(opportunity_uid); return {"schema":"YIELD_HISTORY_V1","observations":list(rows),"summary":history_window_summary(rows),"status":"AVAILABLE"}

@router.get("/{opportunity_uid}",response_class=HTMLResponse)
async def detail(opportunity_uid:str):
    _require(); registry=load_bundled_registry()
    try: o=registry.resolve(opportunity_uid)
    except RegistryError as exc: raise HTTPException(404,"Unknown Yield opportunity") from exc
    d=decompose(o.observation); fresh=evaluate_freshness(_source(o)); evidence=build_evidence(o); path=os.getenv("FINCO_YIELD_HISTORY_PATH","").strip(); hist=history_window_summary(YieldHistoryStore(path).for_opportunity(o.uid)) if path else {"observation_count":0,"history_days":0,"available_windows":[]}
    scenarios=[run_scenario(n,o.observation) for n in ("REWARDS_OFF","REWARDS_MINUS_50","EXIT_STRESS","GAS_SHOCK")]
    scen="".join(f"<p><b>{s.name}</b>: {s.apy if s.apy is not None else s.state.value} · {s.note}</p>" for s in scenarios)
    action='<button class="btn" disabled>Execution flag OFF</button>' if not execution_enabled() else f'<form method="post" action="/yield/{o.uid}/plan"><label>Amount in underlying base units <input name="amount" type="number" min="1" required></label> <button class="btn">Review transaction plan</button></form>'
    body=f'''<p class="k">FINCO Yield · Opportunity Detail</p><h1>{o.name}</h1><p class="sub">{o.protocol} · {_chain(o.chain_id)} · {o.underlying_symbol}</p><div class="nav"><a class="a" href="/yield">← Explore</a><a class="a" href="{o.source_uri}" rel="noopener noreferrer">Open official source ↗</a><a class="a" href="/yield/{o.uid}/evidence.json">Evidence JSON</a></div><div class="grid"><section class="card"><h2>Headline</h2><p>Total APY: {_pct(o.observation.apy_total)}</p><p>TVL: {_usd(o.observation.tvl_usd)}</p><p>Evidence: {o.source_type.value}</p><p>Freshness: {fresh.state}</p></section><section class="card"><h2>Yield Source</h2><p>Base: {_pct(o.observation.apy_base)}</p><p>Rewards: {_pct(o.observation.apy_rewards)}</p><p>Reward dependency: {d.reward_dependency if d.reward_dependency is not None else 'COMPONENTS_UNAVAILABLE'}</p><p>Reward-Off APY: {d.reward_off_apy if d.reward_off_apy is not None else 'COMPONENTS_UNAVAILABLE'}</p></section><section class="card"><h2>History</h2><p>Observations: {hist['observation_count']}</p><p>Real span: {hist['history_days']} days</p><p>Windows: {', '.join(hist['available_windows']) or 'UNAVAILABLE — no fabricated backfill'}</p></section><section class="card"><h2>Exit</h2><p>Type: {(o.observation.withdrawal_type or 'UNKNOWN').upper()}</p><p>Capacity: {o.observation.capacity_usd if o.observation.capacity_usd is not None else 'UNAVAILABLE'}</p><p>Fee: {o.observation.fee_bps if o.observation.fee_bps is not None else 'UNAVAILABLE'}</p><p>Slippage: {o.observation.slippage_bps if o.observation.slippage_bps is not None else 'UNAVAILABLE'}</p></section><section class="card"><h2>Dependencies / Risk Flags</h2><p>No inferred dependency graph. FINCO does not use an opaque risk score.</p><p>Support: {o.support_state}</p><p>APY components: {d.state.value}</p></section><section class="card"><h2>Scenario</h2>{scen}</section><section class="card"><h2>Evidence</h2><p class="hash">Input: {evidence.canonical_input_hash}</p><p class="hash">Output: {evidence.canonical_output_hash}</p><p>{o.source_uri}</p></section></div><section class="card" style="margin-top:14px"><h2>Enter Position</h2><p>Canonical destination, underlying and share token are resolved from the exact opportunity UID.</p>{action}<p class="warn">Bare ERC-4626 previewDeposit is an estimate, not a universal min-shares guarantee. Production signing remains disabled until a protected route is approved.</p></section><p class="bound">No custody. No server-side signing. No automatic broadcast. No auto-invest or rebalance.</p>'''
    return _page(o.name+" — FINCO Yield",body)

@router.post("/{opportunity_uid}/plan")
async def transaction_plan(request:Request,opportunity_uid:str):
    _require()
    if not execution_enabled(): return JSONResponse({"code":"EXECUTION_DISABLED","error":"Yield execution planning is disabled."},409)
    from app.auth import resolve_request_session; from app.protocol.wallet_auth import get_verified_wallet
    user=resolve_request_session(request)
    if not user: return JSONResponse({"code":"UNAUTHENTICATED","error":"Authentication required."},401)
    wallet=get_verified_wallet(user.user_id)
    if not wallet: return JSONResponse({"code":"WALLET_NOT_VERIFIED","error":"Verified wallet required."},409)
    try:
        form=await request.form(); amount=int(str(form.get("amount","0")))
        registry=load_bundled_registry(); binding=registry.execution_binding(opportunity_uid); rpc=rpc_url_for_chain(binding.chain_id)
        if not rpc: return JSONResponse({"code":"DIRECT_RPC_NOT_CONFIGURED","error":"Direct chain read is not configured."},503)
        intent=ExecutionIntent(opportunity_uid,amount,wallet["wallet_address"])
        direct=await read_erc4626(binding,rpc_url=rpc,preview_deposit_assets=amount)
        allowance,allowance_block=await read_allowance(chain_id=binding.chain_id,token_address=binding.underlying_asset,owner=wallet["wallet_address"],spender=binding.contract_address,rpc_url=rpc)
        plan=build_direct_erc4626_deposit(intent,registry=registry,direct_observation=direct,current_allowance=allowance,allowance_block_number=allowance_block); validate_quote(intent,plan,registry=registry)
        pre=build_pre_trade_evidence(build_evidence(registry.resolve(opportunity_uid)),plan)
    except (ValueError,RegistryError,OnchainReadError,ExecutionValidationError): return JSONResponse({"code":"PLAN_REJECTED","error":"Execution plan could not be safely constructed."},409)
    return JSONResponse(json.loads(canonical_json({"schema":"YIELD_TRANSACTION_PLAN_V1","plan":plan,"pre_trade_evidence":pre,"wallet_handoff":{"status":"NOT_ACTIVATED","requires_explicit_user_wallet_action":True,"reason":"Production mainnet signing/broadcast is not activated in PR #148."}})))

# Backward-compatible Y0 prototype route; still non-executable.
@router.get("/prototype",response_class=HTMLResponse,include_in_schema=False)
def prototype()->str:
    return """<!doctype html><html><body><main><h1>ENTER POSITION <small>PROTOTYPE · NO BROADCAST</small></h1><p>Receiver: connected wallet only</p><button disabled>REVIEW & SIGN — EXECUTION FLAG OFF</button><footer>Non-custodial · User-signed · FINCO does not custody.</footer></main></body></html>"""
