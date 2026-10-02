"""FINCO Yield V1 beta product surface.

Crypto Utility V0 integration keeps one authority chain: Agent A produces
ResourceAccessDecision; Agent B enforces it server-side; Agent C only presents
those decisions and owns watchlist UX/CSRF. Token entitlement never changes
Yield mathematics and never enables execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .access import YieldAccessDecision, YieldResource, denial_payload, resolve_yield_access
from .evidence_v1 import build_evidence, canonical_json
from .execution import (
    ExecutionIntent,
    ExecutionValidationError,
    build_direct_erc4626_deposit,
    build_pre_trade_evidence,
    validate_quote,
)
from .explore import (
    CATEGORY_FILTERS,
    CHAIN_FILTERS,
    EVIDENCE_FILTERS,
    ExploreFilters,
    compare,
    explore,
)
from .flags import execution_enabled, yield_enabled
from .freshness import evaluate_freshness
from .history import YieldHistoryStore, history_window_summary
from .intelligence import IntelligenceStatus, build_intelligence
import logging
import sqlite3

from .monitor import detect_positions, detect_positions_scan
from .observation import DATA_ORIGIN_SOURCE_OBSERVED
from .onchain import OnchainReadError, read_allowance, read_erc4626, rpc_url_for_chain
from .registry import RegistryError, load_bundled_registry
from .snapshot import (
    ORIGIN_REFERENCE_FIXTURE,
    RegistrySourceStatus,
    displayed_freshness,
    load_active_registry,
    origin_label,
    snapshot_path_from_env,
)
from .schema import SourceReference
from .underwriting import decompose, run_scenario


async def _enforce_premium(request: Request, resource: YieldResource):
    """Server/API trust boundary for premium Yield resources.

    PUBLIC/ALLOW and canonical INACTIVE proceed.  INACTIVE is not token
    entitlement: it means token gating is not active, so the existing ungated
    product remains available. Canonical DENY returns a typed 403 before any
    protected payload is built or serialized.
    """
    decision: YieldAccessDecision = await resolve_yield_access(request, resource)
    if decision.access_allowed:
        return None
    return JSONResponse(status_code=403, content=denial_payload(decision))


router = APIRouter(prefix="/yield", tags=["yield-beta"])

_REPO_ROOT = Path(__file__).resolve().parents[1]
_templates = Jinja2Templates(directory=str(_REPO_ROOT / "app" / "templates"))
_templates.env.autoescape = True


def _require() -> None:
    if not yield_enabled():
        raise HTTPException(404, "FINCO Yield is not enabled.")


def _active():
    """(registry, RegistrySourceStatus) for READ surfaces.

    Without a configured snapshot this is exactly the bundled reference sample
    (labelled REFERENCE_FIXTURE).  Execution planning keeps using the bundled
    registry directly: an observation is never an executable quote.
    """
    if snapshot_path_from_env() is None:
        registry = load_bundled_registry()
        return registry, RegistrySourceStatus(
            ORIGIN_REFERENCE_FIXTURE, "SNAPSHOT_NOT_CONFIGURED", None,
            0, len(registry.all()), 0)
    return load_active_registry()


# ── Yield Intelligence V1 (derived read model over canonical history) ──────────

def _intelligence_for(uid: str):
    """``(YieldIntelligence | None, history_status)`` from canonical history.

    One ``as_of`` per request.  Unconfigured / unreadable history is a typed
    status -- never numeric zeros.
    """
    path = os.getenv("FINCO_YIELD_HISTORY_PATH", "").strip()
    if not path:
        return None, "HISTORY_NOT_CONFIGURED"
    try:
        intel = build_intelligence(YieldHistoryStore(path), uid, as_of=datetime.now(timezone.utc))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None, "HISTORY_UNAVAILABLE"
    return intel, "AVAILABLE"


def _signed(value: Decimal, fmt: str, unit: str) -> str:
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{sign}{format(abs(value), fmt)}{unit}"


def _bps_label(value) -> str:
    return "—" if value is None else _signed(value, ",.1f", " bps")


def _usd_delta_label(value) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.0f}"


def _pct_delta_label(value) -> str:
    return "—" if value is None else _signed(value * Decimal(100), ",.2f", "%")


def _range_label(stat, fmt) -> str:
    if stat.minimum is None or stat.maximum is None:
        return "—"
    return f"{fmt(stat.minimum)} – {fmt(stat.maximum)}"


def _intelligence_view(intel) -> dict:
    """Presentation only: every unavailable value renders as an em dash."""
    latest = intel.latest
    view = {
        "status": intel.status.value,
        "available": intel.status == IntelligenceStatus.AVAILABLE,
        "as_of": intel.as_of.strftime("%Y-%m-%d %H:%M UTC"),
        "current_apy": _pct(latest.apy_total) if latest else "—",
        "current_tvl": _usd(latest.tvl_usd) if latest else "—",
        "freshness": intel.freshness.state if intel.freshness else "UNAVAILABLE",
        "latest_observed": _last_observed_label(latest.observed_at if latest else None),
        "horizons": [],
    }
    for h in intel.horizons:
        view["horizons"].append({
            "name": h.horizon,
            "coverage": h.coverage.value,
            "observations": h.observation_count,
            "apy_available": h.apy_window.available_count,
            "tvl_available": h.tvl_window.available_count,
            "apy_delta": _bps_label(h.apy_delta.delta_bps),
            "apy_direction": h.apy_delta.direction.value,
            "apy_range": _range_label(h.apy_window, _pct),
            "tvl_delta": _usd_delta_label(h.tvl_delta.delta_usd),
            "tvl_delta_pct": _pct_delta_label(h.tvl_delta.delta_fraction),
            "tvl_direction": h.tvl_delta.direction.value,
            "tvl_range": _range_label(h.tvl_window, _usd),
        })
    return view


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


def _last_observed_label(observed_at, *, now=None) -> str:
    """Human-readable 'Last observed' stamp (age + UTC timestamp).

    Presentation only — it never relabels stale evidence as fresh.  Missing
    observed_at stays missing (no fabricated timestamp).
    """
    from datetime import datetime as _dt, timezone as _tz
    if observed_at is None:
        return "UNAVAILABLE"
    try:
        moment = _dt.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    except ValueError:
        return "UNAVAILABLE"
    if moment.tzinfo is None:
        return "UNAVAILABLE"
    now = now or _dt.now(_tz.utc)
    age_seconds = int((now.astimezone(_tz.utc) - moment.astimezone(_tz.utc)).total_seconds())
    if age_seconds < 0:
        return "timestamp in the future"
    if age_seconds < 90:
        age = f"{age_seconds}s ago"
    elif age_seconds < 5400:
        age = f"{age_seconds // 60}m ago"
    elif age_seconds < 129600:
        age = f"{age_seconds // 3600}h ago"
    else:
        age = f"{age_seconds // 86400}d ago"
    return f"{age} ({moment.astimezone(_tz.utc).strftime('%Y-%m-%d %H:%M UTC')})"


def _chain(chain_id: int) -> str:
    return {1: "Ethereum", 8453: "Base", 4663: "Robinhood"}.get(chain_id, str(chain_id))


def _allowed_source_domains() -> frozenset[str]:
    raw = os.getenv("FINCO_YIELD_SOURCE_DOMAINS", "app.morpho.org")
    return frozenset(domain.strip().lower() for domain in raw.split(",") if domain.strip())


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


class FilterError(ValueError):
    """Typed invalid-filter failure (code + message, HTTP 400 at the route)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _filter_int(value, name: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise FilterError("FILTER_INVALID_INTEGER", f"{name} must be a whole number")


def _filter_decimal(value, name: str, *, minimum: Decimal | None = None) -> Decimal | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        raise FilterError("FILTER_INVALID_NUMBER", f"{name} must be a number")
    if not parsed.is_finite():
        # NaN / Infinity are not valid FINCO numeric filter inputs and would
        # break range comparison downstream.
        raise FilterError("FILTER_INVALID_NUMBER", f"{name} must be a finite number")
    if minimum is not None and parsed < minimum:
        raise FilterError(
            "FILTER_OUT_OF_RANGE", f"{name} must be at least {minimum}")
    return parsed


def _filter_choice(value, name: str, choices) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw not in choices:
        raise FilterError(
            "FILTER_UNKNOWN_VALUE", f"{name} must be one of: {', '.join(choices)}")
    return raw


def _parse_explore_filters(
    chain_id, protocol, asset, category, min_tvl,
    min_history_days, max_reward_dependency, evidence,
):
    """Typed parse of the GET filter string. Raises FilterError (400)."""
    chain_values = {str(cid) for cid, _ in CHAIN_FILTERS}
    chain_raw = (chain_id or "").strip()
    parsed_chain = None
    if chain_raw:
        if chain_raw not in chain_values:
            raise FilterError(
                "FILTER_UNKNOWN_CHAIN",
                "Chain must be one of: " + ", ".join(sorted(chain_values)))
        parsed_chain = int(chain_raw)
    parsed_category = _filter_choice(
        category, "Category", CATEGORY_FILTERS)
    parsed_evidence = _filter_choice(
        evidence, "Evidence", EVIDENCE_FILTERS)
    parsed_min_tvl = _filter_decimal(min_tvl, "Min TVL", minimum=Decimal(0))
    parsed_min_history = _filter_int(min_history_days, "Min history days")
    if parsed_min_history is not None and parsed_min_history < 0:
        raise FilterError(
            "FILTER_OUT_OF_RANGE", "Min history days cannot be negative")
    parsed_max_reward = _filter_decimal(
        max_reward_dependency, "Max reward dependency", minimum=Decimal(0))
    parsed_protocol = (protocol or "").strip()
    parsed_asset = (asset or "").strip()
    return (parsed_chain, parsed_protocol, parsed_asset, parsed_category,
            parsed_min_tvl, parsed_min_history, parsed_max_reward,
            parsed_evidence)


@router.get("", response_class=HTMLResponse)
async def yield_explore(
    request: Request,
    chain_id: str | None = None,
    protocol: str | None = None,
    asset: str | None = None,
    category: str | None = None,
    min_tvl: str | None = None,
    min_history_days: str | None = None,
    max_reward_dependency: str | None = None,
    evidence: str | None = None,
):
    if not yield_enabled():
        return _templates.TemplateResponse(
            request=request,
            name="yield/disabled.html",
            context={"user": _request_user(request)},
        )

    try:
        (parsed_chain, parsed_protocol, parsed_asset, parsed_category,
         parsed_min_tvl, parsed_min_history, parsed_max_reward,
         parsed_evidence) = _parse_explore_filters(
            chain_id, protocol, asset, category, min_tvl,
            min_history_days, max_reward_dependency, evidence)
    except FilterError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="yield/filter_error.html",
            context={
                "user": _request_user(request),
                "error_code": exc.code,
                "error_message": exc.message,
            },
            status_code=400,
        )

    registry, source_status = _active()
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
            parsed_chain,
            parsed_protocol,
            parsed_asset,
            parsed_category,
            parsed_min_tvl,
            parsed_min_history,
            parsed_max_reward,
            None,
            parsed_evidence,
        ),
        history_days_by_uid=history_days,
    )

    view_rows = []
    for opportunity in rows:
        is_live = opportunity.data_origin == DATA_ORIGIN_SOURCE_OBSERVED
        view_rows.append({
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
            "exit": (opportunity.observation.withdrawal_type or "UNKNOWN").upper(),
            "freshness": displayed_freshness(
                opportunity, evaluate_freshness(_source(opportunity)).state),
            "last_observed": _last_observed_label(opportunity.observed_at),
            "origin": origin_label(opportunity),
            "is_live": is_live,
            "origin_class": "LIVE" if is_live else "REFERENCE",
            "provider": opportunity.provider or "—",
            "support_state": opportunity.support_state.value,
        })

    from app.auth import generate_csrf_token
    from app.crypto_access import get_wallet_state
    from finco_yield.watchlist import list_watchlist_items

    user = _request_user(request)
    saved_uids = (set(watchlist_item["opportunity_uid"]
                      for watchlist_item in list_watchlist_items(user.user_id))
                  if user else set())

    return _templates.TemplateResponse(
        request=request,
        name="yield/explore.html",
        context={
            "rows": view_rows,
            "saved_uids": saved_uids,
            "user": user,
            "csrf_token": generate_csrf_token(),
            "source_status": source_status,
            "result_count": len(view_rows),
            "chain_choices": CHAIN_FILTERS,
            "evidence_choices": EVIDENCE_FILTERS,
            "filters": {
                "chain_id": chain_id or "",
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
        rows = compare(_active()[0], uid)
    except (ValueError, RegistryError) as exc:
        raise HTTPException(400, str(exc)) from exc

    columns = [{"uid": row.opportunity_uid, "name": row.name} for row in rows]
    metrics = [
        ("Chain", [_chain(row.chain_id) for row in rows]),
        ("TVL", [_usd(row.tvl_usd) for row in rows]),
        ("Total APY", [_pct(row.gross_apy) for row in rows]),
        ("Base APY", [_pct(row.base_apy) for row in rows]),
        ("Rewards APY", [_pct(row.rewards_apy) for row in rows]),
        ("Reward dependency", [
            "UNAVAILABLE" if row.reward_dependency is None else str(row.reward_dependency)
            for row in rows
        ]),
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


def _request_user(request: Request):
    from app.auth import resolve_request_session
    return resolve_request_session(request)


def _wallet_state_for_request(request: Request) -> str:
    """Wallet presentation state; a wallet-store outage is typed UNAVAILABLE."""
    from app.crypto_access import get_wallet_state
    user = _request_user(request)
    try:
        state, _ = get_wallet_state(user.user_id if user else None)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log_authority_unavailable("wallet_store", exc)
        return "UNAVAILABLE"
    return state


async def _resource_decisions_for_request(request: Request):
    """Agent D wiring: session -> canonical Agent A wallet -> all decisions.

    Typed fail-soft: an outage of the wallet store or the evaluator renders
    typed unavailable decisions instead of an unhandled 500.  Entitlement
    state stays independent of position detection and vice versa.
    """
    from app.protocol.entitlement_evaluator import (
        evaluate_all_resources,
        wallet_context_for_session,
    )
    session = _request_user(request)
    try:
        wallet = wallet_context_for_session(session)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log_authority_unavailable("wallet_store", exc)
        return {}
    return dict(await evaluate_all_resources(wallet))


async def _decisions_for_wallet(wallet):
    """Agent A decisions for a resolved wallet context.

    No broad catch here: canonical evaluation already fails closed internally
    for expected provider/RPC failures.  An unexpected programming error must
    propagate to logs/tests, never masquerade as "no decisions".
    """
    from app.protocol.entitlement_evaluator import evaluate_all_resources
    return dict(await evaluate_all_resources(wallet))


def _wallet_context_fail_soft(user):
    """Canonical wallet context; a wallet-store outage is typed UNAVAILABLE."""
    from app.protocol.entitlement_evaluator import wallet_context_for_session
    try:
        return wallet_context_for_session(user), None
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log_authority_unavailable("wallet_store", exc)
        return None, "WALLET_STORE_UNAVAILABLE"


def _verified_wallet_fail_soft(user_id):
    """Wallet-store read for the monitor; outage is typed, never a crash."""
    from app.protocol.wallet_auth import get_verified_wallet
    try:
        return get_verified_wallet(user_id), None
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log_authority_unavailable("wallet_store", exc)
        return None, "WALLET_STORE_UNAVAILABLE"


def _log_authority_unavailable(authority: str, exc: Exception) -> None:
    """Single audit point for optional-authority degradation (no secrets)."""
    logging.getLogger("finco.yield").warning(
        "YIELD_AUTHORITY_UNAVAILABLE authority=%s error=%s:%s",
        authority, type(exc).__name__, exc,
    )


def _position_scan_view(scan) -> tuple[list[dict], str | None]:
    """Presentation rows + one typed unavailable reason (or None).

    Facts: only a factual on-chain scan supports an empty-positions state.
    Unavailable RPC/config/identity chains yield a typed reason and the UI
    never presents that as a factual zero.
    """
    from .monitor import (
        SCAN_RPC_NOT_CONFIGURED,
        SCAN_RPC_UNAVAILABLE,
        SCAN_WALLET_ADDRESS_INVALID,
    )

    positions_view = []
    for position in scan.positions:
        positions_view.append({
            "name": position.name,
            "chain": _chain(position.chain_id),
            "balance": str(position.balance),
            "observed_apy": _pct(position.observed_apy),
            "exit_state": position.exit_state,
            "evidence_freshness": position.evidence_freshness,
        })

    reasons = scan.unavailable_reasons
    if not reasons:
        return positions_view, None
    if reasons == (SCAN_WALLET_ADDRESS_INVALID,):
        return positions_view, "POSITIONS_UNAVAILABLE_WALLET_IDENTITY"
    if SCAN_RPC_UNAVAILABLE in reasons:
        return positions_view, "POSITIONS_UNAVAILABLE_RPC"
    return positions_view, "POSITIONS_UNAVAILABLE_NOT_CONFIGURED"


@router.get("/monitor", response_class=HTMLResponse)
async def yield_monitor(request: Request):
    """Read-only Wallet Monitor. It is NOT yield.alerts.

    Every optional authority (wallet store, position scan, entitlement
    decisions, watchlist) degrades to a typed product state - an expected
    external/provider failure never becomes an unhandled 500 and never
    becomes a fabricated zero.  Unexpected programming errors still
    propagate and fail visibly in logs.
    """
    _require()
    from app.auth import generate_csrf_token
    from app.crypto_access import build_crypto_access_snapshot, get_wallet_state
    from finco_yield.watchlist import list_watchlist_items

    user = _request_user(request)
    if not user:
        return RedirectResponse("/login", 302)

    wallet, wallet_error = _verified_wallet_fail_soft(user.user_id)

    positions_view: list[dict] = []
    positions_error: str | None = None
    if wallet:
        try:
            scan = await detect_positions_scan(
                _active()[0],
                wallet_address=wallet["wallet_address"],
            )
            positions_view, positions_error = _position_scan_view(scan)
        except OnchainReadError as exc:
            _log_authority_unavailable("position_scan", exc)
            positions_error = "POSITIONS_UNAVAILABLE_RPC"
        except (sqlite3.Error, OSError) as exc:
            # Store/plumbing failure: typed unavailable (logged), no crash.
            # Registry data defects (ValueError) propagate visibly.
            _log_authority_unavailable("position_scan", exc)
            positions_error = "POSITIONS_UNAVAILABLE"

    if wallet_error == "WALLET_STORE_UNAVAILABLE":
        info = "The wallet store is currently unavailable, so no wallet state is shown."
    elif not wallet:
        info = (
            "No verified FINCO wallet is linked. Yield reuses the existing "
            "wallet verification flow."
        )
    else:
        info = (
            f'Verified wallet {wallet["wallet_address"]}. Ownership is '
            "read-only context, not signing authority and not $FINCO entitlement."
        )

    try:
        wallet_state, _ = get_wallet_state(user.user_id)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log_authority_unavailable("wallet_store", exc)
        wallet_state = "UNAVAILABLE"
    wallet_context, context_error = _wallet_context_fail_soft(user)
    if context_error is not None:
        decisions = {}
    else:
        decisions = await _decisions_for_wallet(wallet_context)
    access = build_crypto_access_snapshot(wallet_state, resource_decisions=decisions)
    if context_error is not None:
        access["entitlement_unavailable"] = context_error

    try:
        watchlist_items = list_watchlist_items(user.user_id)
        watchlist_state = {"state": "AVAILABLE", "count": len(watchlist_items),
                           "items": watchlist_items}
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log_authority_unavailable("yield_watchlist", exc)
        watchlist_items = []
        watchlist_state = {"state": "UNAVAILABLE", "count": None, "items": []}

    return _templates.TemplateResponse(
        request=request,
        name="yield/monitor.html",
        context={
            "wallet": wallet,
            "wallet_error": wallet_error,
            "info": info,
            "positions": positions_view,
            "positions_error": positions_error,
            "access": access,
            "watchlist": watchlist_items,
            "watchlist_state": watchlist_state["state"],
            "watchlist_count": watchlist_state["count"],
            "csrf_token": generate_csrf_token(),
        },
    )


@router.get("/prototype", include_in_schema=False)
async def prototype_removed():
    _require()
    return PlainTextResponse(
        "FINCO Yield prototype route was removed; use /yield.",
        status_code=410,
    )


# ── Crypto Utility V0: presentation + watchlist, not entitlement authority ──

def _enforce_csrf(request: Request, form) -> JSONResponse | None:
    """Existing FINCO CSRF primitives for cookie-authenticated mutations."""
    from app.auth import validate_csrf_token
    token = form.get("csrf_token") if form is not None else None
    if not token:
        token = request.headers.get("x-csrf-token")
    if not validate_csrf_token(token or ""):
        return JSONResponse(
            status_code=403,
            content={"state": "UNAVAILABLE", "reason": "CSRF_TOKEN_INVALID"},
        )
    return None


@router.get("/access.json")
async def yield_access_json(request: Request):
    """Presentation of actual Agent A resource decisions; no C-side evaluator."""
    _require()
    from app.crypto_access import build_crypto_access_snapshot

    wallet_state = _wallet_state_for_request(request)
    decisions = await _resource_decisions_for_request(request)
    snapshot = build_crypto_access_snapshot(wallet_state, resource_decisions=decisions)
    snapshot["entitlement_decisions_available"] = bool(decisions)
    return JSONResponse(
        content=snapshot,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/watchlist.json")
async def yield_watchlist_json(request: Request):
    """List the authenticated user's saved canonical Yield opportunities."""
    _require()
    from finco_yield.watchlist import list_watchlist_items

    user = _request_user(request)
    if not user:
        return JSONResponse(
            status_code=401,
            content={"state": "UNAVAILABLE", "reason": "WATCHLIST_AUTH_REQUIRED"},
        )
    items = list_watchlist_items(user.user_id)
    return JSONResponse(
        content={
            "schema_version": "finco-yield-watchlist-v0",
            "count": len(items),
            "items": items,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/watchlist/{opportunity_uid}")
async def yield_watchlist_save(request: Request, opportunity_uid: str):
    """Save one exact canonical yld_* opportunity with auth + CSRF."""
    _require()
    from finco_yield.watchlist import (
        WatchlistError,
        WatchlistOpportunityUnknown,
        save_watchlist_item,
    )

    user = _request_user(request)
    content_type = request.headers.get("content-type") or ""
    is_form = "form" in content_type
    if not user:
        if is_form:
            return RedirectResponse("/login", 302)
        return JSONResponse(
            status_code=401,
            content={"state": "UNAVAILABLE", "reason": "WATCHLIST_AUTH_REQUIRED"},
        )

    form = await request.form() if is_form else None
    csrf_failure = _enforce_csrf(request, form)
    if csrf_failure is not None:
        return csrf_failure

    try:
        result = save_watchlist_item(user.user_id, opportunity_uid)
    except WatchlistOpportunityUnknown:
        return JSONResponse(
            status_code=404,
            content={"state": "UNAVAILABLE", "reason": "YIELD_OPPORTUNITY_UID_UNKNOWN"},
        )
    except WatchlistError as exc:
        return JSONResponse(
            status_code=400,
            content={"state": "UNAVAILABLE", "reason": exc.REASON},
        )
    if is_form:
        return RedirectResponse("/yield/monitor", 302)
    return JSONResponse(
        status_code=201 if result["created"] else 200,
        content={"state": "SAVED", **result},
    )


async def _watchlist_remove(request: Request, opportunity_uid: str):
    _require()
    from finco_yield.watchlist import WatchlistError, remove_watchlist_item

    user = _request_user(request)
    content_type = request.headers.get("content-type") or ""
    is_form = "form" in content_type
    if not user:
        if is_form:
            return RedirectResponse("/login", 302)
        return JSONResponse(
            status_code=401,
            content={"state": "UNAVAILABLE", "reason": "WATCHLIST_AUTH_REQUIRED"},
        )

    form = await request.form() if is_form else None
    csrf_failure = _enforce_csrf(request, form)
    if csrf_failure is not None:
        return csrf_failure

    try:
        removed = remove_watchlist_item(user.user_id, opportunity_uid)
    except WatchlistError as exc:
        return JSONResponse(
            status_code=400,
            content={"state": "UNAVAILABLE", "reason": exc.REASON},
        )
    if is_form:
        return RedirectResponse("/yield/monitor", 302)
    return JSONResponse(content={"state": "REMOVED" if removed else "NOT_PRESENT"})


@router.delete("/watchlist/{opportunity_uid}")
async def yield_watchlist_delete(request: Request, opportunity_uid: str):
    return await _watchlist_remove(request, opportunity_uid)


@router.post("/watchlist/{opportunity_uid}/remove")
async def yield_watchlist_remove_post(request: Request, opportunity_uid: str):
    return await _watchlist_remove(request, opportunity_uid)


@router.get("/{opportunity_uid}/evidence.json")
async def evidence_json(opportunity_uid: str):
    _require()
    try:
        evidence = build_evidence(_active()[0].resolve(opportunity_uid))
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
    registry = _active()[0]
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


@router.get("/{opportunity_uid}/intelligence.json")
async def intelligence_json(opportunity_uid: str, request: Request):
    """Read-only derived intelligence for ONE canonical UID.

    Same entitlement decision as ``history.json`` (it is derived from history);
    no new threshold or policy.  Exact UID resolution only.
    """
    _require()
    denial = await _enforce_premium(request, YieldResource.HISTORY)
    if denial is not None:
        return denial
    try:
        _active()[0].resolve(opportunity_uid)
    except RegistryError as exc:
        raise HTTPException(404, "Unknown Yield opportunity") from exc

    intel, history_status = _intelligence_for(opportunity_uid)
    body = {"schema": "YIELD_INTELLIGENCE_V1", "uid": opportunity_uid,
            "history_status": history_status}
    if intel is not None:
        body["intelligence"] = intel
    return PlainTextResponse(canonical_json(body), media_type="application/json")


@router.get("/{opportunity_uid}", response_class=HTMLResponse)
async def detail(request: Request, opportunity_uid: str):
    _require()
    registry, source_status = _active()
    try:
        opportunity = registry.resolve(opportunity_uid)
    except RegistryError as exc:
        raise HTTPException(404, "Unknown Yield opportunity") from exc

    decomposition = decompose(opportunity.observation)
    freshness = evaluate_freshness(_source(opportunity))
    shown_freshness = displayed_freshness(opportunity, freshness.state)
    evidence = build_evidence(opportunity)
    path = os.getenv("FINCO_YIELD_HISTORY_PATH", "").strip()
    history = (
        history_window_summary(YieldHistoryStore(path).for_opportunity(opportunity.uid))
        if path
        else {"observation_count": 0, "history_days": 0, "available_windows": []}
    )
    # Yield Intelligence is derived from history, so it follows the existing
    # HISTORY entitlement decision (no new policy).
    history_decision = await resolve_yield_access(request, YieldResource.HISTORY)
    if history_decision.access_allowed:
        _intel, intel_history_status = _intelligence_for(opportunity.uid)
        intelligence_view = _intelligence_view(_intel) if _intel is not None else None
    else:
        intelligence_view, intel_history_status = None, "ACCESS_RESTRICTED"
    scenarios = [
        run_scenario(name, opportunity.observation)
        for name in ("REWARDS_OFF", "REWARDS_MINUS_50", "EXIT_STRESS", "GAS_SHOCK")
    ]
    scenario_rows = [{
        "name": scenario.name,
        "result": str(scenario.apy) if scenario.apy is not None else scenario.state.value,
        "note": scenario.note,
    } for scenario in scenarios]

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
            "freshness": shown_freshness,
            "last_observed": _last_observed_label(opportunity.observed_at),
            "origin": origin_label(opportunity),
            "provider": opportunity.provider or "—",
            "fetched": _last_observed_label(opportunity.fetched_at),
            "source_status": source_status,
            "intelligence": intelligence_view,
            "intelligence_history_status": intel_history_status,
            "history": history,
            "exit_type": (opportunity.observation.withdrawal_type or "UNKNOWN").upper(),
            "capacity": (
                str(opportunity.observation.capacity_usd)
                if opportunity.observation.capacity_usd is not None else "UNAVAILABLE"
            ),
            "fee": (
                str(opportunity.observation.fee_bps)
                if opportunity.observation.fee_bps is not None else "UNAVAILABLE"
            ),
            "slippage": (
                str(opportunity.observation.slippage_bps)
                if opportunity.observation.slippage_bps is not None else "UNAVAILABLE"
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
    denial = await _enforce_premium(request, YieldResource.EXECUTION_PREFLIGHT)
    if denial is not None:
        return denial
    # Entitlement never enables execution. This remains the next trust boundary.
    if not execution_enabled():
        return JSONResponse(
            {"code": "EXECUTION_DISABLED", "error": "Yield execution planning is disabled."},
            409,
        )

    from app.protocol.wallet_auth import get_verified_wallet

    user = _request_user(request)
    if not user:
        return JSONResponse(
            {"code": "UNAUTHENTICATED", "error": "Authentication required."},
            401,
        )
    wallet = get_verified_wallet(user.user_id)
    if not wallet:
        return JSONResponse(
            {"code": "WALLET_NOT_VERIFIED", "error": "Verified wallet required."},
            409,
        )

    try:
        form = await request.form()
        amount = int(str(form.get("amount", "0")))
        registry = load_bundled_registry()
        binding = registry.canonical_binding(opportunity_uid)
        rpc = rpc_url_for_chain(binding.chain_id)
        if not rpc:
            return JSONResponse(
                {"code": "DIRECT_RPC_NOT_CONFIGURED", "error": "Direct chain read is not configured."},
                503,
            )
        intent = ExecutionIntent(opportunity_uid, amount, wallet["wallet_address"])
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
        pre = build_pre_trade_evidence(build_evidence(registry.resolve(opportunity_uid)), plan)
    except (ValueError, RegistryError, OnchainReadError, ExecutionValidationError):
        return JSONResponse(
            {"code": "PLAN_REJECTED", "error": "Execution plan could not be safely constructed."},
            409,
        )

    return JSONResponse(json.loads(canonical_json({
        "schema": "YIELD_TRANSACTION_PLAN_V1",
        "plan": plan,
        "pre_trade_evidence": pre,
        "wallet_handoff": {
            "status": "NOT_ACTIVATED",
            "requires_explicit_user_wallet_action": True,
            "reason": "Production mainnet signing/broadcast is not activated in PR #148.",
        },
    })))
