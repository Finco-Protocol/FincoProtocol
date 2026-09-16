"""Isolated read-only FastAPI surface and safe server-side renderer for R6."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .contracts import TerminalSnapshot

ROOT = Path(__file__).resolve().parent


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _chip(value: str) -> str:
    return f'<span class="chip" data-state="{_e(value)}">{_e(value.replace("_", " "))}</span>'


def render_terminal_html(snapshot: TerminalSnapshot) -> str:
    template = (ROOT / "templates" / "radar_terminal.html").read_text(encoding="utf-8")
    asset, ref, liq, sig, hist = (snapshot.asset, snapshot.reference_panel,
                                  snapshot.liquidity_panel, snapshot.signal_panel,
                                  snapshot.history_panel)
    warning = ""
    if not ref.reference_usable:
        reasons = "".join(f"<li>{_e(x)}</li>" for x in ref.blocking_reasons)
        warning = (f'<section class="alert" aria-label="Reference suppression">'
                   f'<strong>REFERENCE NOT USABLE FOR ACTIVE SIGNAL INTERPRETATION</strong>'
                   f'<ul>{reasons}</ul></section>')
    rows = "".join(
        "<tr>" + "".join((
            f"<th scope='row'>{_e(o.side)} ${_e(o.notional_usd)}</th>",
            f"<td>{_e(o.execution_price.display)}</td>",
            f"<td>{_e(o.reference_price.display)}</td>",
            f"<td title='Raw: {_e(o.gap_bps.raw)}'>{_e(o.gap_bps.display)}</td>",
            f"<td>{_chip(o.direction)}</td>",
            f"<td class='time'>{_e(o.quote_timestamp)}</td>",
        )) + "</tr>" for o in snapshot.market_panel
    )
    size_cards = "".join(
        f'<article class="metric-card"><h3>{_e(x.side)} SIZE PERSISTENCE</h3>{_chip(x.size_state)}'
        f'<dl><dt>Small GAP</dt><dd>{_e(x.small_gap_bps.display)}</dd>'
        f'<dt>Large GAP</dt><dd>{_e(x.large_gap_bps.display)}</dd>'
        f'<dt>Directional delta</dt><dd>{_e(x.directional_gap_delta_bps.display)}</dd>'
        f'<dt>R0 size impact</dt><dd>{_e(x.size_impact_bps.display)}</dd></dl></article>'
        for x in snapshot.size_panel
    )
    event_rows = "".join(
        f'<li><strong>{_e(x["kind"])}</strong> · {_e(x["side"])} · '
        f'{_e(x["smallDirection"])} → {_e(x["largeDirection"])} · {_e(x["sizeState"])}'
        f'<span class="detail">Small {_e(x["smallGapBps"])} bps · '
        f'Large {_e(x["largeGapBps"])} bps · Size impact {_e(x["sizeImpactBps"])} bps · '
        f'Route changed {_e(x["routeChanged"])}</span></li>'
        for x in sig.events
    ) or '<li>No material R5 signal events in this observation.</li>'
    change_rows = "".join(
        f'<li><strong>{_e(x["kind"])}</strong> · {_e(x.get("side") or "ALL")}'
        f'<pre class="change-detail">{_e(__import__("json").dumps(x.get("details", {}), sort_keys=True))}</pre></li>'
        for x in hist.changes
    ) or f'<li>{_e(hist.message)}</li>'
    evidence = html.escape(__import__("json").dumps(snapshot.to_evidence_dict(), indent=2,
                                                    sort_keys=True), quote=False)
    replacements = {
        "__SYMBOL__": _e(asset.symbol), "__TOKEN_NAME__": _e(asset.token_name),
        "__CANONICAL_KEY__": _e(asset.canonical_key), "__ASSET_UID__": _e(asset.asset_uid),
        "__CONTRACT__": _e(asset.contract_address), "__GENERATED_AT__": _e(snapshot.generated_at.isoformat()),
        "__WARNING__": warning, "__REFERENCE_USABLE__": _chip("USABLE" if ref.reference_usable else "SUPPRESSED"),
        "__OFFICIAL_BID__": _e(ref.official_bid.display), "__OFFICIAL_ASK__": _e(ref.official_ask.display),
        "__TOKEN_BID__": _e(ref.token_equivalent_bid.display), "__TOKEN_ASK__": _e(ref.token_equivalent_ask.display),
        "__MULTIPLIER__": _e(ref.current_multiplier.display), "__REFERENCE_AGE__": _e(ref.age_seconds.display),
        "__SESSION_LABEL__": _e(ref.session_label), "__REFERENCE_STATES__": " ".join(_chip(x) for x in (
            ref.asset_lifecycle, ref.halt_state, ref.freshness_state, ref.market_session_state,
            ref.corporate_action_state, ref.multiplier_state)),
        "__MARKET_ROWS__": rows, "__SIZE_CARDS__": size_cards,
        "__SPREAD_100__": _e(liq.spread_small_bps.display), "__SPREAD_1000__": _e(liq.spread_large_bps.display),
        "__SPREAD_SMALL_STATE__": _chip(liq.spread_small_state),
        "__SPREAD_LARGE_STATE__": _chip(liq.spread_large_state),
        "__BUY_ROUTE__": _e(f"{liq.buy_small_route} → {liq.buy_large_route}"),
        "__SELL_ROUTE__": _e(f"{liq.sell_small_route} → {liq.sell_large_route}"),
        "__COST_AUTHORITY__": _e(liq.cost_authority), "__COST_DISCLOSURE__": _e(liq.cost_disclosure),
        "__SIGNAL_STATE__": _e(sig.display_state), "__SIGNAL_EVENTS__": event_rows,
        "__HISTORY_CHANGES__": change_rows, "__SOURCE_DIGEST__": _e(snapshot.source_signal_snapshot_digest),
        "__TERMINAL_DIGEST__": _e(snapshot.terminal_snapshot_digest), "__EVIDENCE_JSON__": evidence,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def create_radar_app(snapshot_provider: Callable[[], TerminalSnapshot]) -> FastAPI:
    app = FastAPI(title="FINCO Radar R6", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/radar/static", StaticFiles(directory=ROOT / "static"), name="radar-static")

    @app.get("/radar", response_class=HTMLResponse)
    def terminal() -> str:
        return render_terminal_html(snapshot_provider())

    @app.get("/radar/api/snapshot")
    def snapshot() -> dict:
        return snapshot_provider().to_evidence_dict()

    @app.get("/radar/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "authority": "R6_READ_ONLY"}

    return app
