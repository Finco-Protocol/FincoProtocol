"""Radar / crypto surface coherence: one navigation hierarchy, one visual system, truthful state wording.

Presentation-only correction. No market, reference, oracle, collector or entitlement authority is changed.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)


def _render(name: str, **ctx) -> str:
    return _env.get_template(name).render(**ctx)


def _nav(active: str) -> str:
    return _render("partials/_protocol_nav.html", proto_active_page=active)


def _primary_links(html: str) -> list[tuple[str, str]]:
    block = html.split('data-testid="proto-nav-primary"', 1)[1].split("</div>", 1)[0]
    return re.findall(r'<a href="([^"]+)"\s+class="([^"]*)"', block)


# ── 1-4: navigation hierarchy ────────────────────────────────────────────────────────────────────
def test_global_nav_has_radar_but_no_duplicate_global_rlive():
    links = _primary_links(_nav("home"))
    assert [href for href, _ in links] == ["/radar", "/library", "/api", "/docs"]
    assert "/radar/r-live" not in {href for href, _ in links}


@pytest.mark.parametrize("page", ["radar", "rlive", "tokenized"])
def test_radar_is_globally_active_on_every_radar_domain_page(page):
    links = dict(_primary_links(_nav(page)))
    assert "proto-nav__link--active" in links["/radar"]
    assert not any("proto-nav__link--active" in cls for href, cls in links.items() if href != "/radar")


def test_radar_not_active_outside_the_radar_domain():
    assert "proto-nav__link--active" not in dict(_primary_links(_nav("model")))["/radar"]


def test_tokenized_is_not_a_global_or_more_menu_entry():
    html = _nav("home")
    assert "/radar/tokenized-markets" not in html


@pytest.mark.parametrize("template,active", [
    ("radar/r_live_landing.html", "rlive"), ("radar/r_live_detail.html", "rlive"),
    ("radar/tokenized_markets.html", "tokenized"), ("radar/tokenized_markets_detail.html", "tokenized"),
    ("radar/index.html", "radar"), ("radar/economy.html", "radar"), ("radar/crypto.html", "radar"),
])
def test_radar_pages_mark_the_global_radar_entry_active_and_include_domain_nav(template, active):
    source = (TEMPLATES / template).read_text(encoding="utf-8")
    assert f'proto_active_page="{active}"' in source
    assert 'include "radar/domain_nav.html"' in source


def test_radar_domain_nav_exposes_rlive_first():
    html = _render("radar/domain_nav.html", radar_domain="rlive")
    hrefs = re.findall(r'<a href="([^"]+)"', html)
    assert hrefs == ["/radar/r-live", "/radar/tokenized-markets", "/radar/stocks", "/radar/crypto", "/radar/economy"]


def test_radar_domain_nav_does_not_contain_account_or_yield():
    html = _render("radar/domain_nav.html", radar_domain="tokenized")
    assert "/crypto\"" not in html.replace('/radar/crypto"', "") and "/yield" not in html


def test_slash_radar_opens_rlive_with_an_explicit_redirect():
    from app.radar_ui.r_live_router import router
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app, follow_redirects=False).get("/radar")
    assert response.status_code == 302 and response.headers["location"] == "/radar/r-live"


# ── 5: no stacked crypto-domain nav on Radar pages ───────────────────────────────────────────────
@pytest.mark.parametrize("template", [
    "radar/tokenized_markets.html", "radar/tokenized_markets_detail.html", "radar/crypto.html",
    "radar/r_live_landing.html", "radar/r_live_detail.html", "crypto/overview.html"])
def test_no_crypto_domain_nav_on_radar_or_account_pages(template):
    assert "_crypto_domain_nav" not in (TEMPLATES / template).read_text(encoding="utf-8")


# ── Tokenized Markets presentation ───────────────────────────────────────────────────────────────
@pytest.fixture()
def tm(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
    session = SimpleNamespace(user_id="u1", username="qa", login_at=None, session_type="user")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)
    from app.radar_ui import tokenized_router
    app = FastAPI()
    app.include_router(tokenized_router.router)
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=True), mp=monkeypatch)


def test_tokenized_zero_priced_renders_compact_state_not_the_market_table(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert 'data-testid="tm-empty"' in page
    assert 'data-testid="tokenized-markets-table"' not in page
    assert len(re.findall(r'data-testid="tm-row-', page)) == 0
    assert "13 reviewed assets ready for live collection" in page
    assert "No fresh source-observed market prices are currently persisted" in page
    assert 'data-testid="tm-open-rlive"' in page and 'href="/radar/r-live"' in page
    assert "Collector:" in page


def test_tokenized_uses_the_radar_terminal_visual_system(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert "/static/css/finco-surface.css" in page and "/static/radar/radar.css" in page
    assert "yield.css" not in page and "y-table" not in page and "y-header" not in page
    assert '<body class="radar">' in page


def test_tokenized_detail_uses_the_radar_terminal_visual_system(tm):
    page = tm.client.get("/radar/tokenized-markets/NVDA").text
    assert "yield.css" not in page and "y-table" not in page and "crypto-domain-nav" not in page
    assert "/static/css/finco-surface.css" in page


def test_tokenized_page_has_no_crypto_domain_nav_and_single_radar_hierarchy(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert 'data-testid="crypto-domain-nav"' not in page
    assert 'data-testid="radar-domain-nav"' in page
    assert page.count('data-testid="proto-nav-primary"') == 1


def test_never_run_state_wording_is_a_preview_and_never_contradicts_collector_state(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert "Preview · collection has not started" in page
    assert "DATA COLLECTION NOT ACTIVE" not in page


def test_state_labels_only_call_a_never_run_collector_inactive():
    from app.radar_ui import tokenized_operational as op
    S = op.TokenizedOperationalState
    expected = {
        S.COLLECTOR_NOT_STARTED: "Preview · collection has not started",
        S.COLLECTOR_UNHEALTHY: "Collecting · current source evidence unavailable",
        S.NO_PRICED_OBSERVATIONS: "Collecting · no fresh priced observations yet",
        S.PARTIAL_LIVE: "Partially live",
        S.LIVE: "Live",
    }
    for state, label in expected.items():
        assert op.STATE_LABELS[state] == label
    for state in S:
        text = (op.STATE_LABELS[state] + " " + op.STATE_HEADLINES[state]).lower()
        assert "not active" not in text.replace("has not started", "")
    for state in (S.COLLECTOR_UNHEALTHY, S.NO_PRICED_OBSERVATIONS, S.PARTIAL_LIVE, S.LIVE):
        assert not op.STATE_LABELS[state].lower().startswith("preview")


def test_identity_catalog_is_a_secondary_disclosure_not_a_primary_metric(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    kpis = page.split('data-testid="tm-coverage"', 1)[1].split("</div>\n\n<details", 1)[0]
    assert 'data-testid="tm-cov-catalog"' not in kpis
    for testid in ("tm-cov-eligible", "tm-cov-priced", "tm-cov-history", "tm-collector-health"):
        assert testid in page
    assert '<details class="fs-details" data-testid="tm-research-catalog">' in page
    disclosure = page.split('data-testid="tm-research-catalog"', 1)[1].split("</details>", 1)[0]
    assert 'data-testid="tm-cov-catalog"' in disclosure
    assert "identity coverage is not market coverage" in disclosure


def test_audit_and_catalog_links_remain_available(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert 'href="/radar/tokenized-markets?view=catalog"' in page
    assert 'href="/radar/tokenized-markets?view=audit"' in page
    assert tm.client.get("/radar/tokenized-markets?view=catalog").status_code == 200
    assert tm.client.get("/radar/tokenized-markets?view=audit").status_code == 200


# ── Account & access ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def account(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "crypto.db"))
    import app.persistence.db as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "crypto.db"))
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: None)
    from app.crypto_ui import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def test_account_and_access_uses_the_finco_shell_and_terminal_styles(account):
    page = account.get("/crypto").text
    for sheet in ("/static/tokens.css", "/static/radar/radar.css", "/static/css/protocol-shell.css",
                  "/static/css/finco-surface.css"):
        assert sheet in page
    assert '<body class="radar">' in page and 'class="radar-main fs-main"' in page
    assert 'style="width:100%;border-collapse:collapse' not in page
    assert 'data-testid="crypto-domain-nav"' not in page


def test_account_and_access_is_secondary_navigation_only(account):
    page = account.get("/crypto").text
    assert 'data-testid="proto-nav-current"' in page and "Account &amp; access" in page
    nav = _nav("home")
    assert 'href="/crypto"' in nav.split('data-testid="proto-nav-secondary"', 1)[1]
    assert 'href="/crypto"' not in nav.split('data-testid="proto-nav-secondary"', 1)[0]


def test_default_account_page_leads_with_user_states_not_entitlement_codes(account):
    page = account.get("/crypto").text
    technical_start = page.index('data-testid="crypto-technical-status"')
    visible = page[:technical_start]
    for code in ("NOT_ACTIVATED", "TOKEN_GATING_OFF", "PUBLIC_RESOURCE", "yield.execution_preflight",
                 "crypto-access-row-"):
        assert code not in visible, code
    assert "No production $FINCO access gate is currently active" in visible
    for section in ("Wallet", "Access", "Saved items", "Alerts"):
        assert f">{section}" in visible or f"<h2>{section}" in visible
    technical = page[technical_start:]
    assert "crypto-access-row-yield.basic" in technical and "NOT_ACTIVATED" in technical
    assert re.search(r"<details[^>]*data-testid=\"crypto-technical-status\"", page)


# ── R-LIVE presentation ──────────────────────────────────────────────────────────────────────────
def test_rlive_landing_title_is_user_facing_and_never_claims_executable_prices():
    page = (TEMPLATES / "radar/r_live_landing.html").read_text(encoding="utf-8")
    assert "R-LIVE — Stock Token Market Tape" in page
    assert "Independent Token Reference\n" not in page.split("</h1>", 1)[0]
    assert "not tradeable or executable prices" in page


def test_rlive_last_canonical_price_is_live_without_separate_landing_historical_badge():
    page = (TEMPLATES / "radar/r_live_detail.html").read_text(encoding="utf-8")
    assert 'badge.textContent = live ? "LIVE" : "UNAVAILABLE"' in page
    assert 'var product_state = is_current ? "LIVE" : "UNAVAILABLE";' in page
    assert 'populate(row.state, row.data, row.read_time_ages, row.source)' in page
    assert 'presentation_source !== "CANONICAL_B1_3_HISTORY"' in page
    assert "latest canonical on-chain price · original evidence age shown above" in page

    table = (ROOT / "static/radar/r_live_table.js").read_text(encoding="utf-8")
    assert 'badge.textContent = live ? "LIVE" : "UNAVAILABLE"' in table
    assert 'presentation_source: view_row.source' in table
    assert 'mark_historical(row_el, ["trend", "range_1h", "range_24h"])' not in table
    assert "if (!is_current) mark_historical" not in table
    assert "Market " in table and "Oracle " in table


def test_rlive_legs_show_age_but_only_policy_fresh_acquisition_claims_available():
    page = (TEMPLATES / "radar/r_live_detail.html").read_text(encoding="utf-8")
    assert 'var is_current = (state === "AVAILABLE");' in page
    assert 'var is_policy_fresh = is_current && presentation_source !== "CANONICAL_B1_3_HISTORY";' in page
    assert 'var leg_state = is_policy_fresh ? "AVAILABLE · " : "";' in page
    assert 'var leg_state = is_current ? "AVAILABLE · " : "";' not in page
    assert 'legs.push("Market " + leg_state + fmt_age(market_age));' in page
    assert 'legs.push("Oracle " + leg_state + fmt_age(quote_age_kpi));' in page
    assert 'is_policy_fresh ? "each leg within its source freshness policy · " : ""' in page
    assert "within source heartbeat policy" in page
    assert "read_time_ages" in page


# ── NVDA data path: R-LIVE leg ages vs the Tokenized observation clock ───────────────────────────
def _nvda_row(*, token_observed_at: datetime, collected_at: datetime):
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    cid, policy = next((c, p) for c, p in APPROVED_BY_CANONICAL_ID.items() if p.symbol == "NVDA")
    chain, contract = cid.split(":", 1)
    return cid, policy, {
        "exact_asset_key": {"canonical_id": cid, "chain_id": int(chain), "contract_address": contract},
        "economic_asset_uid": policy.economic_asset_uid,
        "token_reference": {"state": "AVAILABLE", "price_usd_per_token": "190.10",
                            "source": "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD",
                            "observed_at": token_observed_at.isoformat(), "reason": None},
        "robinhood_basis": {"state": "AVAILABLE", "price_usd_per_token": "189.90",
                            "source": "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
                            "observed_at": collected_at.isoformat(), "reason": None},
    }


def test_tokenized_observation_clock_uses_market_window_end_and_preserves_oracle_clock():
    """Fresh TWAP block remains current despite a valid 19h oracle heartbeat."""
    from finco_radar.authority.r_live_policy import MAX_QUOTE_AGE_SECONDS
    from finco_radar.venues.intelligence import effective_observation_state
    from finco_radar.venues.registry import VenueRegistry
    from finco_radar.venues.robinhood_live import market_observation_from_r_live

    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    market = now - timedelta(seconds=30)
    oracle = now - timedelta(hours=19)
    pool_activity = now - timedelta(seconds=60)
    cid, policy, data = _nvda_row(token_observed_at=oracle, collected_at=now)
    data["token_reference"]["source_evidence"] = {
        "blockNumber": 123,
        "blockHash": "0x" + "ab" * 32,
        "blockTimestamp": market.isoformat(),
        "dexWindowEndAt": market.isoformat(),
        "dexWindowStartAt": (market - timedelta(seconds=300)).isoformat(),
        "twapWindowSeconds": 300,
        "lastPoolActivityAt": pool_activity.isoformat(),
        "quoteUpdatedAt": oracle.isoformat(),
        "effectiveObservedAt": oracle.isoformat(),
    }
    observation = market_observation_from_r_live(
        canonical_id=cid, state="AVAILABLE", data=data,
        registry=VenueRegistry.load(), collected_at=now)
    assert observation is not None
    assert observation.ts == market.isoformat()
    assert observation.ts != oracle.isoformat()
    assert observation.payload["market_block_timestamp"] == observation.ts
    assert observation.payload["normalization_oracle_observed_at"] == oracle.isoformat()
    assert observation.payload["effective_evidence_at"] == oracle.isoformat()
    assert observation.payload["last_pool_activity_at"] == pool_activity.isoformat()
    assert observation.payload["reference_observed_at"] == now.isoformat()
    assert observation.collected_at == now.isoformat()
    assert (market - oracle).total_seconds() <= policy.max_quote_age_seconds
    assert policy.max_quote_age_seconds == MAX_QUOTE_AGE_SECONDS
    assert effective_observation_state(
        observation, as_of=now, max_age_seconds=900) == "AVAILABLE"

    # Independent oracle-expiry check with a deliberately generous market
    # age ceiling; 19h oracle + 6h at read-time breaches the 24h heartbeat.
    late = now + timedelta(hours=6)
    assert effective_observation_state(
        observation, as_of=late,
        max_age_seconds=MAX_QUOTE_AGE_SECONDS + 3600) == "STALE"


def test_non_available_rlive_rows_never_become_market_observations():
    from finco_radar.venues.registry import VenueRegistry
    from finco_radar.venues.robinhood_live import market_observation_from_r_live
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    cid, _policy, data = _nvda_row(token_observed_at=now, collected_at=now)
    for state in ("STALE", "UNAVAILABLE"):
        assert market_observation_from_r_live(
            canonical_id=cid, state=state, data=data, registry=VenueRegistry.load(), collected_at=now) is None


# ── frozen authorities ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "financial_engine", "finco_core", "finco_yield", "finco_radar/authority", "finco_radar/venues",
    "app/radar_rwa", "app/crypto_resource_access.py", "app/crypto_access.py"])
def test_authorities_have_zero_diff(path):
    # Existing authority files must not be modified or deleted; later PRs may ADD new modules beside them.
    excluded = [
        ":(exclude)app/radar_rwa/stock_token_oracle.py", ":(exclude)app/radar_rwa/stock_token_oracle_registry.py",
        ":(exclude)app/radar_rwa/multi_source_evidence.py", ":(exclude)app/radar_rwa/multi_source_collect.py",
        ":(exclude)app/radar_rwa/keccak.py", ":(exclude)app/radar_rwa/data/stock_token_oracle_feeds.json",
        ":(exclude)app/radar_rwa/data/stock_token_oracle_candidates.json"]   # multi-source modules (#188) have their own guards
    from model_v2_governance import merge_base_ref

    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=MD",
                          f"{merge_base_ref('origin/main')}..HEAD", "--", path, *excluded],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("git unavailable")
    # Explicitly authorized Model V2 epic engine files are governed by the
    # Model V2 scope contract (tests/model_v2_governance.py); this guard keeps
    # protecting every other authority path, including all Radar/Yield/Crypto
    # namespaces, which the Model V2 scope can never approve.
    from finance_integrity_governance import approved_frozen_path
    changed = [p for p in out.stdout.split() if not approved_frozen_path(p)]
    assert changed == [], changed
