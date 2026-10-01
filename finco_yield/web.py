"""FINCO Yield V1 beta product surface.

Presentation uses FINCO Jinja templates with autoescaping. Global Product Truth
navigation/status is owned by the merged Product Truth surface; Yield remains
feature-gated and IN DEVELOPMENT until PR #148 merges.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .evidence_v1 import build_evidence, canonical_json
from .execution import (
    ExecutionIntent,
    ExecutionValidationError,
    build_direct_erc4626_deposit,
    build_pre_trade_evidence,
    validate_quote,
)
from .explore import ExploreFilters, compare, explore
from .flags import execution_enabled, yield_enabled
from .freshness import evaluate_freshness
from .history import YieldHistoryStore, history_window_summary
from .monitor import detect_positions
from .onchain import OnchainReadError, read_allowance, read_erc4626, rpc_url_for_chain
from .registry import RegistryError, load_bundled_registry
from .schema import SourceReference
from .underwriting import decompose, run_scenario
from .access import (
    YieldAccessDecision,
    YieldAccessState,
    YieldResource,
    denial_payload,
    resolve_yield_access,
)


async def _enforce_premium(request: Request, resource: YieldResource):
    """Server-side trust boundary for premium Yield resources.

    Returns a typed denial response when access is not ENTITLED; returns
    None when entitled.  Direct API invocation cannot bypass this: the
    decision is made inside the endpoint before any protected payload is
    built or serialized.
    """
    decision: YieldAccessDecision = await resolve_yield_access(request, resource)
    if decision.entitled:
        return None
    return JSONResponse(status_code=403, content=denial_payload(decision))

router = APIRouter(prefix="/yield", tags=["yield-beta"])

_REPO_ROOT = Path(__file__).resolve().parents[1]
_templates = Jinja2Templates(directory=str(_REPO_ROOT / "app" / "templates"))
_templates.env.autoescape = True


def _require() -> None:
    if not yield_enabled():
        raise HTTPException(404, "FINCO Yield is not enabled.")


def _source(opportunity):
    return SourceReference(
        opportunity.source_type,
        opportunity.source_uri,
        opportunity.observed_at,
        opportunity.block_number,
        opportunity.adapter,
        opportunity.adapter_version,
    )


def _pct(value) -> str:
    return "—" if value is None else f"{value * Decimal(100):.2f}%"


def _usd(value) -> str:
    return "—" if value is None else f"${value:,.0f}"


def _chain(chain_id: int) -> str:
    return {1: "Ethereum", 8453: "Base", 4663: "Robinhood"}.get(
        chain_id, str(chain_id)
    )


def _d(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise HTTPException(400, "Invalid decimal filter") from exc


def _allowed_source_domains() -> frozenset[str]:
    raw = os.getenv("FINCO_YIELD_SOURCE_DOMAINS", "app.morpho.org")
    return frozenset(
        domain.strip().lower()
        for domain in raw.split(",")
        if domain.strip()
    )


def _safe_external_href(value: str | None) -> str | None:
    """Allow only explicit HTTPS links to configured source domains."""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host not in _allowed_source_domains():
        return None
    if parsed.username or parsed.password:
        return None
    return value


@router.get("", response_class=HTMLResponse)
async def yield_explore(
    request: Request,
    chain_id: int | None = None,
    protocol: str | None = None,
    asset: str | None = None,
    category: str | None = None,
    min_tvl: str | None = None,
    min_history_days: int | None = None,
    max_reward_dependency: str | None = None,
    evidence: str | None = None,
):
    _require()
    registry = load_bundled_registry()
    history_days = {}
    path = os.getenv("FINCO_YIELD_HISTORY_PATH", "").strip()
    if path:
        store = YieldHistoryStore(path)
        for opportunity in registry.all():
            history_days[opportunity.uid] = history_window_summary(
                store.for_opportunity(opportunity.uid)
            )["history_days"]

    rows = explore(
        registry,
        filters=ExploreFilters(
            chain_id,
            protocol,
            asset,
            category,
            _d(min_tvl),
            min_history_days,
            _d(max_reward_dependency),
            None,
            evidence,
        ),
        history_days_by_uid=history_days,
    )

    view_rows = []
    for opportunity in rows:
        view_rows.append(
            {
                "uid": opportunity.uid,
                "name": opportunity.name,
                "underlying_symbol": opportunity.underlying_symbol,
                "protocol": opportunity.protocol,
                "chain": _chain(opportunity.chain_id),
                "tvl": _usd(opportunity.observation.tvl_usd),
                "total_apy": _pct(opportunity.observation.apy_total),
                "base_apy": _pct(opportunity.observation.apy_base),
                "rewards_apy": _pct(opportunity.observation.apy_rewards),
                "evidence": opportunity.source_type.value,
                "exit": (
                    opportunity.observation.withdrawal_type or "UNKNOWN"
                ).upper(),
                "freshness": evaluate_freshness(_source(opportunity)).state,
                "support_state": opportunity.support_state.value,
            }
        )

    return _templates.TemplateResponse(
        request=request,
        name="yield/explore.html",
        context={
            "rows": view_rows,
            "filters": {
                "chain_id": chain_id,
                "protocol": protocol or "",
                "asset": asset or "",
                "category": category or "",
                "min_tvl": min_tvl or "",
                "min_history_days": min_history_days or "",
                "max_reward_dependency": max_reward_dependency or "",
                "evidence": evidence or "",
            },
        },
    )


@router.get("/compare", response_class=HTMLResponse)
async def yield_compare(request: Request, uid: list[str] = Query(default=[])):
    _require()
    denial = await _enforce_premium(request, YieldResource.ADVANCED_COMPARE)
    if denial is not None:
        return denial
    try:
        rows = compare(load_bundled_registry(), uid)
    except (ValueError, RegistryError) as exc:
        raise HTTPException(400, str(exc)) from exc

    columns = [
        {
            "uid": row.opportunity_uid,
            "name": row.name,
        }
        for row in rows
    ]
    metrics = [
        ("Chain", [_chain(row.chain_id) for row in rows]),
        ("TVL", [_usd(row.tvl_usd) for row in rows]),
        ("Total APY", [_pct(row.gross_apy) for row in rows]),
        ("Base APY", [_pct(row.base_apy) for row in rows]),
        ("Rewards APY", [_pct(row.rewards_apy) for row in rows]),
        (
            "Reward dependency",
            [
                "UNAVAILABLE"
                if row.reward_dependency is None
                else str(row.reward_dependency)
                for row in rows
            ],
        ),
        ("Evidence", [row.evidence_confidence for row in rows]),
        ("Freshness", [row.freshness for row in rows]),
        ("Exit", [row.exit_type for row in rows]),
        ("Rewards off", [_pct(row.rewards_off_apy) for row in rows]),
        ("Rewards -50%", [_pct(row.rewards_minus_50_apy) for row in rows]),
        ("Exit stress", [row.exit_stress_state for row in rows]),
        ("Gas shock", [row.gas_shock_state for row in rows]),
    ]

    return _templates.TemplateResponse(
        request=request,
        name="yield/compare.html",
        context={"columns": columns, "metrics": metrics},
    )


@router.get("/monitor", response_class=HTMLResponse)
async def yield_monitor(request: Request):
    _require()
    denial = await _enforce_premium(request, YieldResource.ALERTS)
    if denial is not None:
        return denial
    from app.auth import resolve_request_session
    from app.protocol.wallet_auth import get_verified_wallet

    user = resolve_request_session(request)
    if not user:
        return RedirectResponse("/login", 302)

    wallet = get_verified_wallet(user.user_id)
    positions_view = []
    if wallet:
        positions = await detect_positions(
            load_bundled_registry(),
            wallet_address=wallet["wallet_address"],
        )
        for position in positions:
            positions_view.append(
                {
                    "name": position.name,
                    "balance": str(position.balance),
                    "observed_apy": _pct(position.observed_apy),
                    "exit_state": position.exit_state,
                    "evidence_freshness": position.evidence_freshness,
                }
            )

    if not wallet:
        info = (
            "No verified FINCO wallet is linked. Yield reuses the existing "
            "wallet verification flow."
        )
    else:
        info = (
            f'Verified wallet {wallet["wallet_address"]}. Ownership is '
            "read-only context, not signing authority and not $FINCO entitlement."
        )

    return _templates.TemplateResponse(
        request=request,
        name="yield/monitor.html",
        context={
            "wallet": wallet,
            "info": info,
            "positions": positions_view,
        },
    )


# Explicit tombstone before dynamic UID routes: never interpret "prototype" as a UID.
@router.get("/prototype", include_in_schema=False)
async def prototype_removed():
    _require()
    return PlainTextResponse(
        "FINCO Yield prototype route was removed; use /yield.",
        status_code=410,
    )


@router.get("/{opportunity_uid}/evidence.json")
async def evidence_json(opportunity_uid: str):
    _require()
    try:
        evidence = build_evidence(
            load_bundled_registry().resolve(opportunity_uid)
        )
    except RegistryError as exc:
        raise HTTPException(404, "Unknown Yield opportunity") from exc
    payload = json.loads(canonical_json(evidence))
    payload["canonical_input_hash"] = evidence.canonical_input_hash
    payload["canonical_output_hash"] = evidence.canonical_output_hash
    return JSONResponse(payload)


@router.get("/{opportunity_uid}/history.json")
async def history_json(opportunity_uid: str, request: Request):
    _require()
    denial = await _enforce_premium(request, YieldResource.HISTORY)
    if denial is not None:
        return denial
    registry = load_bundled_registry()
    try:
        registry.resolve(opportunity_uid)
    except RegistryError as exc:
        raise HTTPException(404, "Unknown Yield opportunity") from exc

    path = os.getenv("FINCO_YIELD_HISTORY_PATH", "").strip()
    if not path:
        return {
            "schema": "YIELD_HISTORY_V1",
            "observations": [],
            "status": "HISTORY_NOT_CONFIGURED",
        }
    rows = YieldHistoryStore(path).for_opportunity(opportunity_uid)
    return {
        "schema": "YIELD_HISTORY_V1",
        "observations": list(rows),
        "summary": history_window_summary(rows),
        "status": "AVAILABLE",
    }


@router.get("/{opportunity_uid}", response_class=HTMLResponse)
async def detail(request: Request, opportunity_uid: str):
    _require()
    registry = load_bundled_registry()
    try:
        opportunity = registry.resolve(opportunity_uid)
    except RegistryError as exc:
        raise HTTPException(404, "Unknown Yield opportunity") from exc

    decomposition = decompose(opportunity.observation)
    freshness = evaluate_freshness(_source(opportunity))
    evidence = build_evidence(opportunity)
    path = os.getenv("FINCO_YIELD_HISTORY_PATH", "").strip()
    history = (
        history_window_summary(
            YieldHistoryStore(path).for_opportunity(opportunity.uid)
        )
        if path
        else {
            "observation_count": 0,
            "history_days": 0,
            "available_windows": [],
        }
    )
    scenarios = [
        run_scenario(name, opportunity.observation)
        for name in (
            "REWARDS_OFF",
            "REWARDS_MINUS_50",
            "EXIT_STRESS",
            "GAS_SHOCK",
        )
    ]
    scenario_rows = [
        {
            "name": scenario.name,
            "result": (
                str(scenario.apy)
                if scenario.apy is not None
                else scenario.state.value
            ),
            "note": scenario.note,
        }
        for scenario in scenarios
    ]

    return _templates.TemplateResponse(
        request=request,
        name="yield/detail.html",
        context={
            "o": opportunity,
            "chain": _chain(opportunity.chain_id),
            "source_href": _safe_external_href(opportunity.source_uri),
            "total_apy": _pct(opportunity.observation.apy_total),
            "tvl": _usd(opportunity.observation.tvl_usd),
            "base_apy": _pct(opportunity.observation.apy_base),
            "rewards_apy": _pct(opportunity.observation.apy_rewards),
            "reward_dependency": (
                str(decomposition.reward_dependency)
                if decomposition.reward_dependency is not None
                else "COMPONENTS_UNAVAILABLE"
            ),
            "reward_off_apy": (
                str(decomposition.reward_off_apy)
                if decomposition.reward_off_apy is not None
                else "COMPONENTS_UNAVAILABLE"
            ),
            "freshness": freshness.state,
            "history": history,
            "exit_type": (
                opportunity.observation.withdrawal_type or "UNKNOWN"
            ).upper(),
            "capacity": (
                str(opportunity.observation.capacity_usd)
                if opportunity.observation.capacity_usd is not None
                else "UNAVAILABLE"
            ),
            "fee": (
                str(opportunity.observation.fee_bps)
                if opportunity.observation.fee_bps is not None
                else "UNAVAILABLE"
            ),
            "slippage": (
                str(opportunity.observation.slippage_bps)
                if opportunity.observation.slippage_bps is not None
                else "UNAVAILABLE"
            ),
            "support_state": opportunity.support_state.value,
            "component_state": decomposition.state.value,
            "scenario_rows": scenario_rows,
            "evidence": evidence,
            "execution_enabled": execution_enabled(),
        },
    )


@router.post("/{opportunity_uid}/plan")
async def transaction_plan(request: Request, opportunity_uid: str):
    _require()
    # execution_preflight is a premium + verified-wallet resource.  The
    # entitlement gate does NOT enable execution (the EXECUTION_DISABLED
    # contract below still applies afterwards).
    denial = await _enforce_premium(request, YieldResource.EXECUTION_PREFLIGHT)
    if denial is not None:
        return denial
    if not execution_enabled():
        return JSONResponse(
            {
                "code": "EXECUTION_DISABLED",
                "error": "Yield execution planning is disabled.",
            },
            409,
        )

    from app.auth import resolve_request_session
    from app.protocol.wallet_auth import get_verified_wallet

    user = resolve_request_session(request)
    if not user:
        return JSONResponse(
            {"code": "UNAUTHENTICATED", "error": "Authentication required."},
            401,
        )
    wallet = get_verified_wallet(user.user_id)
    if not wallet:
        return JSONResponse(
            {
                "code": "WALLET_NOT_VERIFIED",
                "error": "Verified wallet required.",
            },
            409,
        )

    try:
        form = await request.form()
        amount = int(str(form.get("amount", "0")))
        registry = load_bundled_registry()
        # Canonical identity may be used only to perform the direct block-bound
        # revalidation. It does not authorize execution by itself.
        binding = registry.canonical_binding(opportunity_uid)
        rpc = rpc_url_for_chain(binding.chain_id)
        if not rpc:
            return JSONResponse(
                {
                    "code": "DIRECT_RPC_NOT_CONFIGURED",
                    "error": "Direct chain read is not configured.",
                },
                503,
            )
        intent = ExecutionIntent(
            opportunity_uid,
            amount,
            wallet["wallet_address"],
        )
        direct = await read_erc4626(
            binding,
            rpc_url=rpc,
            preview_deposit_assets=amount,
        )
        allowance, allowance_block = await read_allowance(
            chain_id=binding.chain_id,
            token_address=binding.underlying_asset,
            owner=wallet["wallet_address"],
            spender=binding.contract_address,
            rpc_url=rpc,
        )
        plan = build_direct_erc4626_deposit(
            intent,
            registry=registry,
            direct_observation=direct,
            current_allowance=allowance,
            allowance_block_number=allowance_block,
        )
        validate_quote(intent, plan, registry=registry)
        pre = build_pre_trade_evidence(
            build_evidence(registry.resolve(opportunity_uid)),
            plan,
        )
    except (
        ValueError,
        RegistryError,
        OnchainReadError,
        ExecutionValidationError,
    ):
        return JSONResponse(
            {
                "code": "PLAN_REJECTED",
                "error": "Execution plan could not be safely constructed.",
            },
            409,
        )

    return JSONResponse(
        json.loads(
            canonical_json(
                {
                    "schema": "YIELD_TRANSACTION_PLAN_V1",
                    "plan": plan,
                    "pre_trade_evidence": pre,
                    "wallet_handoff": {
                        "status": "NOT_ACTIVATED",
                        "requires_explicit_user_wallet_action": True,
                        "reason": (
                            "Production mainnet signing/broadcast is not "
                            "activated in PR #148."
                        ),
                    },
                }
            )
        )
    )
