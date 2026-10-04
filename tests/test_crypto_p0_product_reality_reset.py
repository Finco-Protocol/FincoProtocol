"""P0 product-reality reset — the public crypto/RWA product tells the truth about real operational data.

Covers: Tokenized operational state gate, identity-catalog vs live coverage, public identity eligibility,
live-only Yield default, navigation / homepage / product-truth copy, R-LIVE per-leg freshness and ordering.
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

from app.radar_ui import tokenized_operational as op
from app.radar_ui import tokenized_router
from app.radar_ui.tokenized_operational import TokenizedOperationalState as S
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.store import VenueMarketStore
from tests.test_tokenized_live_intelligence_v1 import _market_obs
from tests.test_tokenized_markets_composition import ROBINHOOD_NVDA, _entry, _registry

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"


def collector(outcome="SUCCESS", health="HEALTHY", last_success="2026-10-04T10:00:00Z", reason=None):
    return SimpleNamespace(outcome=outcome, health_state=health, last_success_at=last_success,
                           failure_reason=reason)


# ── operational state (pure) ─────────────────────────────────────────────────────────────────────
def test_no_live_collection_universe_is_identity_only():
    assert op.derive_state(live_eligible=0, collector=collector(), priced_now=5) is S.IDENTITY_ONLY


def test_collector_never_run_cannot_be_live_even_with_priced_rows():
    never = collector("NEVER_RUN", "UNHEALTHY", None)
    for priced in (0, 3, 13):
        state = op.derive_state(live_eligible=13, collector=never, priced_now=priced)
        assert state is S.COLLECTOR_NOT_STARTED
        assert state not in op.OPERATING_STATES


def test_collector_that_never_succeeded_or_is_unhealthy_is_not_operating():
    assert op.derive_state(live_eligible=13, collector=collector("FAILED", "UNHEALTHY", None), priced_now=4) \
        is S.COLLECTOR_UNHEALTHY
    assert op.derive_state(live_eligible=13, collector=collector(health="UNHEALTHY"), priced_now=4) \
        is S.COLLECTOR_UNHEALTHY


def test_healthy_collector_with_empty_store_reports_no_priced_observations():
    assert op.derive_state(live_eligible=13, collector=collector(), priced_now=0) is S.NO_PRICED_OBSERVATIONS


def test_partial_and_full_live_require_priced_evidence():
    assert op.derive_state(live_eligible=13, collector=collector(), priced_now=5) is S.PARTIAL_LIVE
    assert op.derive_state(live_eligible=13, collector=collector(health="DEGRADED"), priced_now=13) \
        is S.PARTIAL_LIVE
    assert op.derive_state(live_eligible=13, collector=collector(), priced_now=13) is S.LIVE


def test_empty_store_cannot_report_priced_coverage():
    registry = _registry([_entry()])
    view = op.build_operational_view(registry, None, collector(), eligible_ids=("a",), primary_views=[])
    assert view.coverage.priced_now == 0 and view.coverage.history_available == 0
    assert not view.operating
    assert op.symbols_with_market_evidence(registry, None) == set()


# ── public identity eligibility / quarantine ─────────────────────────────────────────────────────
def test_numeric_and_malformed_identities_are_excluded_but_inspectable():
    registry = VenueRegistry.load()
    included, excluded = op.classify_identity_catalog(registry)
    included_ids = {row["canonical_asset_id"] for row in included}
    reasons = {row["canonical_asset_id"]: row["exclusion_reason"] for row in excluded}
    assert "1" not in included_ids and reasons["1"] == "NUMERIC_ONLY_SYMBOL"
    assert not any(symbol.isdigit() for symbol in included_ids)
    assert any(reason == "MALFORMED_SYMBOL" for reason in reasons.values())
    # nothing is deleted: every catalog identity is either included or inspectable as excluded
    assert len(included) + len(excluded) == len(registry._underlyings)
    # provenance of the third-party seed stays on the excluded row
    assert all(row["sources"] is not None and "exclusion_reason" in row for row in excluded)


def test_exact_contract_type_conflict_excludes_the_only_representation():
    conflicting = [
        _entry(instrument_type="tokenized-equity"),
        _entry(instrument_type="debt-security"),          # same exact chain+contract, different type
    ]
    included, excluded = op.classify_identity_catalog(_registry(conflicting))
    assert "NVDA" not in {row["canonical_asset_id"] for row in included}
    row = next(r for r in excluded if r["canonical_asset_id"] == "NVDA")
    assert row["exclusion_reason"] == "REPRESENTATION_TYPE_CONFLICT_SAME_CONTRACT"
    conflicts = op.representation_conflicts(_registry(conflicting))
    assert len(conflicts) == 1 and conflicts[0]["reason"] == "REPRESENTATION_TYPE_CONFLICT_SAME_CONTRACT"


def test_clean_identity_is_included():
    included, excluded = op.classify_identity_catalog(_registry([_entry()]))
    assert "NVDA" in {row["canonical_asset_id"] for row in included}


def test_reviewed_robinhood_contracts_resolve_so_collector_universe_is_full():
    """Superseded 0/13 finding: sources agree on the exact deployment and differ only on taxonomy."""
    registry = VenueRegistry.load()
    assert len(op.live_eligible_ids(registry)) == 13


# ── routes ───────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def tm(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
    session = SimpleNamespace(user_id="u1", username="qa", login_at=None, session_type="user")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)
    app = FastAPI()
    app.include_router(tokenized_router.router)
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=True), mp=monkeypatch,
                           db=tmp_path / "venues.db")


def test_collector_never_run_renders_preview_not_live(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert 'data-testid="tm-operational-state"' in page
    assert "Preview · collection has not started" in page and "DATA COLLECTION NOT ACTIVE" not in page
    state = re.search(r'data-state="([A-Z_]+)"', page).group(1)
    assert state == "COLLECTOR_NOT_STARTED"


def test_identity_catalog_count_is_not_market_coverage(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    catalog = int(re.search(r'data-testid="tm-cov-catalog">(\d+)<', page).group(1))   # secondary disclosure, not a KPI
    priced = int(re.search(r'data-testid="tm-cov-priced">(\d+)<', page).group(1))
    eligible = int(re.search(r'data-testid="tm-cov-eligible">(\d+)<', page).group(1))
    history = int(re.search(r'data-testid="tm-cov-history">(\d+)<', page).group(1))
    assert catalog > 1000 and priced == 0 and eligible == 13 and history == 0
    assert "not market coverage" in page and "research identity source" in page
    assert "canonical underlyings with active representations" not in page
    # no priced evidence → compact collecting state; neither the identity catalog nor a 13-row empty table is listed
    assert len(re.findall(r'data-testid="tm-row-', page)) == 0 and 'data-testid="tm-empty"' in page


def test_primary_list_excludes_malformed_numeric_and_identity_only_rows(tm):
    page = tm.client.get("/radar/tokenized-markets").text
    assert 'data-testid="tm-row-1"' not in page and 'data-testid="tm-row-1024"' not in page
    assert 'data-testid="tm-row-ZZZZ"' not in page
    assert 'data-testid="tm-row-AAPL"' not in page           # nothing priced → compact state, no empty table
    assert 'href="/radar/tokenized-markets/AAPL"' in page    # reviewed asset still reachable
    assert int(re.search(r'data-testid="tm-cov-priced">(\d+)<', page).group(1)) == 0


def test_audit_view_keeps_excluded_evidence_inspectable(tm):
    page = tm.client.get("/radar/tokenized-markets?view=audit").text
    assert 'data-testid="tm-audit-table"' in page and 'data-testid="tm-audit-row-1"' in page
    assert "NUMERIC_ONLY_SYMBOL" in page and 'data-testid="tm-audit-conflicts"' in page
    assert 'data-testid="tm-audit-taxonomy"' in page


def test_catalog_view_is_identity_only_and_labelled(tm):
    page = tm.client.get("/radar/tokenized-markets?view=catalog").text
    assert 'data-testid="tm-catalog-table"' in page and "not market coverage" in page
    assert 'data-testid="tm-catalog-row-AAPL"' in page and 'data-testid="tm-catalog-row-1"' not in page


def test_unknown_view_falls_back_to_primary_and_deep_links_still_work(tm):
    assert 'data-testid="tm-empty"' in tm.client.get("/radar/tokenized-markets?view=bogus").text
    assert tm.client.get("/radar/tokenized-markets/NVDA").status_code == 200


def test_store_evidence_makes_a_row_primary_but_collector_state_still_gates_the_claim(tm):
    store = VenueMarketStore(tm.db)
    now = datetime.now(timezone.utc)
    store.append_observation(_market_obs(venue="robinhood-chain", instrument=ROBINHOOD_NVDA, price="102",
                                         at=now - timedelta(seconds=30), reference_at=now - timedelta(seconds=30)))
    page = tm.client.get("/radar/tokenized-markets").text
    assert 'data-testid="tm-row-NVDA"' in page              # real persisted evidence is shown...
    assert "Preview · collection has not started" in page    # ...but the collector never ran: not a live product
    assert 'data-state="COLLECTOR_NOT_STARTED"' in page or 'data-state="IDENTITY_ONLY"' in page


def test_missing_evidence_stays_null_not_zero():
    from app.radar_ui.tokenized_composition import compose_underlying
    registry = _registry([_entry()])
    view = compose_underlying("NVDA", registry=registry, reference_reader=lambda s: [], store=None,
                              now=datetime.now(timezone.utc))
    assert view.priced_representations == () and view.history_available is False
    row = tokenized_router._landing_row(view)
    assert row["best_price"] is None and row["best_basis_bps"] is None
    assert row["basis_change_24h_bps"] is None and row["cross_venue_divergence_bps"] is None


# ── Yield: live-only public default ──────────────────────────────────────────────────────────────
@pytest.fixture()
def yield_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "web.db"))
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_SNAPSHOT_PATH", raising=False)
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "web.db"))
    _db.init_db()
    import main_web
    with TestClient(main_web.app, base_url="https://reset.local", raise_server_exceptions=True) as client:
        yield client


def _table_body(page: str) -> str:
    return page.split("<tbody>")[1].split("</tbody>")[0]


def test_public_yield_default_has_no_reference_fixture_rows(yield_client):
    page = yield_client.get("/yield").text
    body = _table_body(page)
    assert "REFERENCE" not in body and "Reference fixture" not in body
    assert re.search(r'data-testid="yield-result-count">0<', page)


def test_removing_fixtures_does_not_fabricate_live_replacements(yield_client):
    page = yield_client.get("/yield").text
    assert "Source-observed" not in page and "SOURCE_OBSERVED" not in _table_body(page)
    assert "does not substitute reference samples" in page


def test_reference_sample_only_appears_in_explicit_research_mode(yield_client):
    default = yield_client.get("/yield").text
    research = yield_client.get("/yield?include_reference=1").text
    assert 'data-research-mode="off"' in default and 'data-research-mode="on"' in research
    assert "Reference fixture" in research and "not live data" in research


# ── navigation / homepage / crypto demotion ─────────────────────────────────────────────────────
def _nav(page_html: str):
    nav = page_html.split('<nav class="proto-nav"', 1)[1].split("</nav>", 1)[0]
    primary = nav.split('data-testid="proto-nav-primary"', 1)[1].split('data-testid="proto-nav-secondary"', 1)[0]
    secondary = nav.split('data-testid="proto-nav-secondary"', 1)[1]
    return primary, secondary


@pytest.fixture()
def home():
    import main_web
    with TestClient(main_web.app, base_url="https://reset.local") as client:
        yield client


def test_finco_token_is_not_in_primary_navigation_but_stays_reachable(home):
    primary, secondary = _nav(home.get("/").text)
    assert "$FINCO" not in primary and "/protocol/finco" not in primary
    assert "/protocol/finco" in secondary                     # deep link / secondary navigation kept
    assert home.get("/protocol/finco").status_code == 200


def test_primary_navigation_is_compact_and_rlive_first(home):
    primary, _ = _nav(home.get("/").text)
    hrefs = re.findall(r'href="([^"]+)"', primary)
    assert hrefs == ["/radar", "/library", "/api", "/docs"]      # Radar opens R-LIVE; no duplicate global R-LIVE entry
    for demoted in ("/yield", "/crypto", "/roadmap", "/verify"):
        assert demoted not in primary


def test_homepage_carries_no_internal_activation_or_status_copy(home):
    text = home.get("/").text
    for forbidden in ("production deployment count", "gating defaults OFF", "token gating", "CONFIGURABLE BUT INACTIVE",
                      "NOT_ACTIVATED", "activation-readiness", "ILLUSTRATIVE", "illustrative"):
        assert forbidden not in text, forbidden


def test_rlive_is_the_prominent_public_product_and_reachable(home):
    text = home.get("/").text
    assert 'data-testid="home-primary-message"' in text and "Stock Tokens" in text
    assert 'href="/radar/r-live" class="proto-cta proto-cta--primary"' in text
    assert 'data-testid="home-product-rlive"' in text
    assert home.get("/radar/r-live").status_code == 200


def test_model_is_reachable_and_not_bound_to_rwa_assets(home):
    text = home.get("/").text
    assert 'href="/library"' in text and "not connected to the market data" in text
    assert "R-LIVE" in text.split('data-testid="home-product-rlive"', 1)[1].split("</a>", 1)[0]
    model_card = text.split('href="/library" class="proto-arch__product"', 1)[1].split("</a>", 1)[0]
    assert "tokenized" not in model_card.lower() or "not connected" in model_card.lower()


def test_crypto_status_is_demoted_in_domain_navigation():
    html = (TEMPLATES / "partials" / "_crypto_domain_nav.html").read_text()
    order = re.findall(r'\("(\w+)", "([^"]+)", "([^"]+)"\)', html)
    assert [o[0] for o in order][0] == "rlive" and order[-1][0] == "overview"
    assert order[-1][2] == "Account & access"


# ── R-LIVE presentation: per-leg freshness and chronological chart axis ──────────────────────────
def test_rlive_detail_shows_each_evidence_leg_age_separately():
    html = (TEMPLATES / "radar" / "r_live_detail.html").read_text()
    assert 'legs.push("Market " + leg_state + fmt_age(market_age))' in html
    assert 'legs.push("Oracle " + leg_state + fmt_age(quote_age_kpi))' in html
    assert "Evidence age (per leg)" in html
    assert 'set_text("kpi-freshness", market_age != null' not in html     # no single collapsed age


def test_rlive_landing_already_keeps_market_and_oracle_age_separate():
    js = (ROOT / "static" / "radar" / "r_live_table.js").read_text()
    assert '"Market " + market + " · Oracle " + oracle' in js


HISTORY_ORDER_JS = ROOT / "static" / "radar" / "r_live_history_order.js"


def _run_order(points: list[dict], which: str) -> list[str]:
    """Execute the real presentation helper under Node with deliberately shuffled canonical points."""
    import json
    import shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = (
        "const h=require(%s);const pts=JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(h.%s(pts).map(p=>p.id)));" % (json.dumps(str(HISTORY_ORDER_JS)), which))
    out = subprocess.run([node, "-e", script, json.dumps(points)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _pt(identifier, collected, observed=None, **extra):
    return {"id": identifier, "collected_at": collected, "observed_at": observed, **extra}


SHUFFLED = [
    _pt("t1003", "2026-10-04T10:03:00Z"),
    _pt("t1001", "2026-10-04T10:01:00Z"),
    _pt("t1002", "2026-10-04T10:02:00Z"),
]


def test_history_table_is_newest_first_for_deliberately_shuffled_points():
    assert _run_order(SHUFFLED, "tableOrder") == ["t1003", "t1002", "t1001"]


def test_history_chart_is_oldest_first_for_the_same_points():
    assert _run_order(SHUFFLED, "chartOrder") == ["t1001", "t1002", "t1003"]


@pytest.mark.parametrize("permutation", [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)])
def test_history_order_is_independent_of_input_order_for_distinct_times(permutation):
    points = [SHUFFLED[i] for i in permutation]
    assert _run_order(points, "tableOrder") == ["t1003", "t1002", "t1001"]
    assert _run_order(points, "chartOrder") == ["t1001", "t1002", "t1003"]


def test_equal_timestamps_keep_a_stable_deterministic_order():
    tied = [_pt("a", "2026-10-04T10:00:00Z"), _pt("b", "2026-10-04T10:00:00Z"),
            _pt("c", "2026-10-04T10:00:00Z"), _pt("old", "2026-10-04T09:00:00Z")]
    # table: ties keep input order (stable); chart: ties reverse the newest-first API order (stable)
    assert _run_order(tied, "tableOrder") == ["a", "b", "c", "old"]
    assert _run_order(tied, "chartOrder") == ["old", "c", "b", "a"]
    # repeated runs give the identical result
    assert _run_order(tied, "tableOrder") == _run_order(tied, "tableOrder")


def test_history_order_uses_canonical_timestamps_with_observed_at_fallback_and_missing_last():
    points = [
        _pt("no_time", None, None),
        _pt("fallback", "not-a-date", "2026-10-04T10:05:00Z"),     # collected_at invalid -> observed_at
        _pt("collected", "2026-10-04T10:02:00Z", "2026-10-04T12:00:00Z"),   # collected_at wins over observed_at
        _pt("offset", "2026-10-04T12:04:00+02:00"),                # same instant as 10:04Z, different offset
    ]
    assert _run_order(points, "tableOrder") == ["fallback", "offset", "collected", "no_time"]
    assert _run_order(points, "chartOrder") == ["collected", "offset", "fallback", "no_time"]


def test_history_helper_does_not_mutate_points_or_input_array():
    import json
    import shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = (
        "const h=require(%s);const pts=JSON.parse(process.argv[1]);const copy=JSON.stringify(pts);"
        "h.tableOrder(pts);h.chartOrder(pts);console.log(JSON.stringify(JSON.stringify(pts)===copy));"
        % json.dumps(str(HISTORY_ORDER_JS)))
    out = subprocess.run([node, "-e", script, json.dumps(SHUFFLED)], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) is True


def test_rlive_detail_wires_table_newest_first_and_chart_oldest_first_through_the_helper():
    html = (TEMPLATES / "radar" / "r_live_detail.html").read_text()
    assert '<script src="/static/radar/r_live_history_order.js"></script>' in html
    table_body = html.split("function build_history_table(points) {", 1)[1].split("fetch(HIST_URL)", 1)[0]
    assert "FincoRLiveHistoryOrder.tableOrder(points).slice(0, 20)" in table_body
    assert "points.slice(0, 20)" not in table_body.replace("tableOrder(points).slice(0, 20)", "")
    chart_body = html.split("function chart_points(points, picker) {", 1)[1].split("// Signed bps formatter", 1)[0]
    assert "FincoRLiveHistoryOrder.chartOrder(points)" in chart_body
    # the helper is served as a static asset
    assert HISTORY_ORDER_JS.is_file()


# ── product-truth documentation ──────────────────────────────────────────────────────────────────
def test_product_truth_separates_code_capability_from_operational_availability():
    doc = (ROOT / "docs" / "CRYPTO_TERMINAL_PRODUCT_TRUTH.md").read_text()
    assert "CODE CAPABILITY" in doc and "OPERATIONAL DATA AVAILABILITY" in doc
    tokenized = doc.split("- **Tokenized Markets**", 1)[1].split("- **Yield**", 1)[0]
    assert "AVAILABLE TODAY" not in tokenized
    assert "PREVIEW" in tokenized and "runtime-dependent" in tokenized
    for state in ("IDENTITY_ONLY", "COLLECTOR_NOT_STARTED", "COLLECTOR_UNHEALTHY",
                  "NO_PRICED_OBSERVATIONS", "PARTIAL_LIVE", "LIVE"):
        assert state in doc
    assert "research identity source" in doc and "live, source-observed opportunities only" in doc


# ── frozen boundaries ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("namespace", ["financial_engine", "finco_core", "finco_radar/venues"])
def test_frozen_namespaces_zero_diff(namespace):
    out = subprocess.run(["git", "diff", "--name-only", "origin/main..HEAD", "--", namespace],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("git unavailable")
    # Authorised by the exact-identity correction (registry collapse of same-identity source rows);
    # every other path in this namespace stays frozen.
    allowed = {"finco_radar/venues/registry.py", "finco_radar/venues/models.py"}
    changed = [p for p in out.stdout.split() if p not in allowed]
    assert changed == [], changed
