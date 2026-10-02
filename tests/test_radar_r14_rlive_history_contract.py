"""R14-B: R-LIVE UI canonical history schema contract tests.

Verifies that the JS layer in r_live_table.js and r_live_detail.html correctly
consumes the ACTUAL canonical B1.3 history schema produced by
make_r_live_history_point() in app/radar_rwa/bnb_history.py.

Canonical history point shape (from make_r_live_history_point):
  {
    "observed_at": "...",            # ISO8601
    "state": "AVAILABLE",
    "robinhood_basis": {
        "price_usd_per_token": "...",
        "source": "...",
        "observed_at": "...",
    },
    "independent_token_reference": { # from OnchainReferenceObservation.to_evidence_dict()
        "state": "AVAILABLE",
        "assetKey": "...",
        "assetUid": "...",
        "reason": null,
        "priceUsdPerToken": "...",   # camelCase
        "observedAt": "...",         # camelCase
        "evidence": {...},
    },
    "reference_premium_bps": "...",  # snake_case string
    ...
  }

Markers verified:
  RLIVE_UI_1H_RANGE_CANONICAL_HISTORY
  RLIVE_UI_24H_RANGE_CANONICAL_HISTORY
  RLIVE_UI_INSUFFICIENT_HISTORY_DASH
  RLIVE_DETAIL_CANONICAL_BASIS_HISTORY
  RLIVE_DETAIL_CANONICAL_TOKEN_REFERENCE_HISTORY
  RLIVE_DETAIL_CANONICAL_PREMIUM_HISTORY
  RLIVE_UI_HISTORY_SCHEMA_CONTRACT_REAL
  RLIVE_UI_HISTORY_MISSING_NEVER_ZERO
  RLIVE_UI_HISTORY_NEVER_REPLACES_CURRENT_STATE
  RLIVE_HISTORY_NO_RAW_EVIDENCE_INNERHTML
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


# ── Canonical history fixture helpers ────────────────────────────────────────

def _canonical_point(
    observed_at: datetime,
    basis_usd: str = "182.5000",
    token_ref_usd: str = "182.8000",
    premium_bps: str = "+16.4",
    state: str = "AVAILABLE",
    asset_key: str = "4663:0xaf3d76f1834a1d425780943c99ea8a608f8a93f9",
    asset_uid: str = "rh-equity-aapl-001",
) -> dict:
    """Build a canonical history point matching make_r_live_history_point() output."""
    return {
        "economic_asset_uid": asset_uid,
        "asset_key": asset_key,
        "identity_source": "ROBINHOOD_REGISTRY",
        "identity_observed_at": observed_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "state": state,
        "robinhood_basis": {
            "price_usd_per_token": basis_usd,
            "source": "NASDAQ_CLOSE",
            "observed_at": observed_at.isoformat(),
        },
        "independent_token_reference": {
            "state": state,
            "assetKey": asset_key,
            "assetUid": asset_uid,
            "reason": None,
            "priceUsdPerToken": token_ref_usd,
            "observedAt": observed_at.isoformat(),
            "evidence": {"pool": "0xABC", "twap": token_ref_usd},
        },
        "reference_premium_bps": premium_bps,
        "premium_sources": ["UNISWAP_V3_TWAP_CHAINLINK_USDG_USD", "NASDAQ_CLOSE"],
        "premium_evidence_at": [observed_at.isoformat()],
        "execution_state": "UNAVAILABLE",
    }


def _real_history_point_from_builder() -> dict:
    """
    Derive a canonical history point through the actual Python builder.

    This exercises the real make_r_live_history_point() code path using
    minimal mock objects matching its expected interface. We do NOT touch
    financial_engine, finco_core, or authority — we only exercise the
    output-contract of the builder, which is a pure Python dict assembly.
    """
    from app.radar_rwa.bnb_history import make_r_live_history_point
    from finco_radar.authority.contracts import (
        AuthorityState, AuthoritySnapshot, ReferenceLayer, BasisPointQuantity,
        ExecutionLayer, ExecutionGap, IndependentTokenReference,
    )
    from finco_radar.authority.r_live_onchain import OnchainReferenceObservation
    from finco_radar.assets.contracts import AssetKey
    from decimal import Decimal

    t = NOW
    key = AssetKey(chain_id=4663, contract_address="0xaf3d76f1834a1d425780943c99ea8a608f8a93f9")
    uid = "rh-equity-aapl-001"

    underlying = ReferenceLayer(
        state=AuthorityState.AVAILABLE,
        registry_asset_uid=uid,
        asset_key=key,
        label="AAPL",
        price_usd_per_token=Decimal("182.50"),
        source="NASDAQ_CLOSE",
        observed_at=t,
    )
    premium = BasisPointQuantity(
        state=AuthorityState.AVAILABLE,
        value_bps=Decimal("16.4"),
        numerator_usd_per_token=Decimal("182.80"),
        denominator_usd_per_token=Decimal("182.50"),
        formula="(token_ref - basis) / basis * 10000",
        sources=("UNISWAP_V3_TWAP_CHAINLINK_USDG_USD", "NASDAQ_CLOSE"),
        observed_at=(t,),
    )
    execution = ExecutionLayer(
        state=AuthorityState.UNAVAILABLE,
        asset_key=key, side=None,
        requested_notional_usd=None, effective_price_usd_per_token=None,
        provider=None, route=None, fee_cost_usd=None, gas_cost_usd=None,
        observed_at=None, reason="NO_EXECUTION",
    )
    execution_gap = ExecutionGap(
        state=AuthorityState.UNAVAILABLE,
        reference_premium_bps=None,
        execution_impact_bps=None,
        effective_gap_bps=None,
        fee_treatment="UNKNOWN",
        reason="NO_EXECUTION",
    )
    snapshot = AuthoritySnapshot(
        economic_asset_uid=uid,
        canonical_token=key,
        registry_source="ROBINHOOD_REGISTRY",
        registry_observed_at=t,
        underlying=underlying,
        token=underlying,
        premium=premium,
        execution=execution,
        execution_gap=execution_gap,
    )
    observation = OnchainReferenceObservation(
        state=AuthorityState.AVAILABLE,
        asset_key=key,
        registry_asset_uid=uid,
        reason=None,
        price_usd_per_token=Decimal("182.80"),
        observed_at=t,
        evidence={"pool": "0xABC", "twap": "182.80"},
    )
    point = make_r_live_history_point(snapshot, observation)
    assert point is not None, "make_r_live_history_point returned None for valid inputs"
    return point


# ── Schema shape tests ────────────────────────────────────────────────────────

class TestCanonicalHistoryPointShape:
    """Verify the canonical history point shape from the real builder."""

    def test_builder_produces_reference_premium_bps(self):
        """RLIVE_UI_HISTORY_SCHEMA_CONTRACT_REAL: builder uses reference_premium_bps."""
        point = _real_history_point_from_builder()
        assert "reference_premium_bps" in point, (
            "Canonical history point missing reference_premium_bps — "
            "UI must read this field, not premium_bps"
        )
        assert "premium_bps" not in point, (
            "Canonical history point must NOT have flat premium_bps — "
            "that was the wrong field the old UI was reading"
        )

    def test_builder_produces_nested_robinhood_basis(self):
        """Builder wraps basis in robinhood_basis.price_usd_per_token (nested)."""
        point = _real_history_point_from_builder()
        assert "robinhood_basis" in point, "robinhood_basis key missing from canonical point"
        assert isinstance(point["robinhood_basis"], dict), "robinhood_basis must be a dict"
        assert "price_usd_per_token" in point["robinhood_basis"], (
            "robinhood_basis.price_usd_per_token missing — UI must read this nested path"
        )
        # Must NOT be a flat field
        assert "robinhood_basis_price" not in point, (
            "robinhood_basis_price must not be a flat field — was the wrong alias the old UI read"
        )

    def test_builder_produces_camelcase_token_reference(self):
        """independent_token_reference.priceUsdPerToken is camelCase."""
        point = _real_history_point_from_builder()
        itr = point.get("independent_token_reference", {})
        assert "priceUsdPerToken" in itr, (
            "independent_token_reference.priceUsdPerToken missing — "
            "UI must read camelCase priceUsdPerToken, not snake_case token_reference_price"
        )
        # Must NOT be a flat field
        assert "token_reference_price" not in point, (
            "token_reference_price must not be a flat field"
        )

    def test_builder_point_has_observed_at_and_state(self):
        """Canonical point has top-level observed_at and state."""
        point = _real_history_point_from_builder()
        assert "observed_at" in point, "canonical point missing observed_at"
        assert "state" in point, "canonical point missing state"
        assert point["state"] == "AVAILABLE"


# ── Landing JS fmt_range contract ─────────────────────────────────────────────

class TestFmtRangeCanonicalField:
    """RLIVE_UI_1H_RANGE_CANONICAL_HISTORY / RLIVE_UI_24H_RANGE_CANONICAL_HISTORY"""

    def test_r_live_table_js_reads_reference_premium_bps(self):
        """Server reads canonical premium; landing consumes bounded summaries."""
        history = (REPO / "app/radar_rwa/bnb_history.py").read_text()
        js = (REPO / "static/radar/r_live_table.js").read_text()
        assert 'point["reference_premium_bps"]' in history
        assert 'summary.low_bps' in js and 'summary.high_bps' in js

    def test_r_live_table_js_does_not_read_flat_premium_bps_in_fmt_range(self):
        """fmt_range must not read p.premium_bps (old wrong field)."""
        js = (REPO / "static/radar/r_live_table.js").read_text()
        # Find the fmt_range function body
        fmt_range_match = re.search(
            r'function fmt_range\s*\(.*?\{(.*?)^\s*\}',
            js, re.DOTALL | re.MULTILINE
        )
        assert fmt_range_match, "fmt_range function not found in r_live_table.js"
        body = fmt_range_match.group(1)
        # Must not access p.premium_bps (the wrong flat field)
        assert "p.premium_bps" not in body, (
            "fmt_range still reads p.premium_bps — must read p.reference_premium_bps"
        )

    def test_range_suppressed_when_fewer_than_2_points(self):
        """RLIVE_UI_INSUFFICIENT_HISTORY_DASH: < 2 valid points → null/dash."""
        js = (REPO / "static/radar/r_live_table.js").read_text()
        # fmt_range must have the < 2 guard
        assert "summary.observation_count < 2" in js, (
            "RLIVE_UI_INSUFFICIENT_HISTORY_DASH: "
            "fmt_range must return null (dash) when fewer than 2 valid observations"
        )

    def test_js_range_state_still_guarded_by_available_check(self):
        """RLIVE_UI_HISTORY_NEVER_REPLACES_CURRENT_STATE: snapshot state still gated."""
        js = (REPO / "static/radar/r_live_table.js").read_text()
        # The current-snapshot numeric values must still be gated by is_current / AVAILABLE
        assert "is_current" in js or "AVAILABLE" in js, (
            "r_live_table.js must still gate current snapshot values on AVAILABLE state"
        )


# ── Detail history template contract ─────────────────────────────────────────

class TestDetailHistoryCanonicalFields:
    """RLIVE_DETAIL_CANONICAL_BASIS_HISTORY / TOKEN_REFERENCE / PREMIUM"""

    def test_detail_html_reads_nested_robinhood_basis(self):
        """RLIVE_DETAIL_CANONICAL_BASIS_HISTORY: detail reads robinhood_basis.price_usd_per_token."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        assert "robinhood_basis.price_usd_per_token" in html, (
            "RLIVE_DETAIL_CANONICAL_BASIS_HISTORY: "
            "detail template must read pt.robinhood_basis.price_usd_per_token (nested)"
        )
        assert "robinhood_basis_price" not in html, (
            "detail template still reads old flat alias robinhood_basis_price"
        )

    def test_detail_html_reads_camelcase_price_usd_per_token(self):
        """RLIVE_DETAIL_CANONICAL_TOKEN_REFERENCE_HISTORY: detail reads priceUsdPerToken."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        assert "priceUsdPerToken" in html, (
            "RLIVE_DETAIL_CANONICAL_TOKEN_REFERENCE_HISTORY: "
            "detail template must read independent_token_reference.priceUsdPerToken (camelCase)"
        )
        assert "token_reference_price" not in html, (
            "detail template still reads old flat alias token_reference_price"
        )

    def test_detail_html_reads_reference_premium_bps(self):
        """RLIVE_DETAIL_CANONICAL_PREMIUM_HISTORY: detail reads reference_premium_bps."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        assert "reference_premium_bps" in html, (
            "RLIVE_DETAIL_CANONICAL_PREMIUM_HISTORY: "
            "detail template must read pt.reference_premium_bps (canonical field)"
        )
        # The old flat field must be gone from history rendering
        assert "pt.premium_bps" not in html, (
            "detail template still reads old flat pt.premium_bps in history block"
        )

    def test_detail_html_no_raw_innerhtml_for_history(self):
        """RLIVE_HISTORY_NO_RAW_EVIDENCE_INNERHTML: no innerHTML for history data."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        # Find the build_history_table function
        build_fn = re.search(
            r'function build_history_table\s*\(.*?\{(.*?)^\s*\}',
            html, re.DOTALL | re.MULTILINE
        )
        if build_fn:
            body = build_fn.group(1)
            # Check for innerHTML assignment (not just the word in a comment)
            assert not re.search(r'\.innerHTML\s*[+]?=', body), (
                "RLIVE_HISTORY_NO_RAW_EVIDENCE_INNERHTML: "
                "build_history_table assigns innerHTML — must use textContent/createElement"
            )
        # Also verify textContent is used for cell values
        assert "textContent" in html, (
            "detail template must use textContent for history cell values (not innerHTML)"
        )


# ── Missing never zero ────────────────────────────────────────────────────────

class TestMissingNeverZero:
    """RLIVE_UI_HISTORY_MISSING_NEVER_ZERO: absent values show dash, not 0."""

    def test_detail_template_missing_nested_basis_shows_dash(self):
        """Absent robinhood_basis → dash, not 0."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        # The null-guard pattern must be present before formatting
        assert "robinhood_basis &&" in html or "robinhood_basis ?" in html or \
               "robinhood_basis)" in html, (
            "RLIVE_UI_HISTORY_MISSING_NEVER_ZERO: "
            "detail template must null-guard robinhood_basis before accessing price_usd_per_token"
        )

    def test_detail_template_missing_token_ref_shows_dash(self):
        """Absent independent_token_reference → dash, not 0."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        assert "independent_token_reference &&" in html or \
               "independent_token_reference)" in html, (
            "RLIVE_UI_HISTORY_MISSING_NEVER_ZERO: "
            "detail template must null-guard independent_token_reference"
        )

    def test_detail_template_missing_premium_shows_dash(self):
        """Absent reference_premium_bps → dash, not 0."""
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        assert 'prem_raw != null' in html or 'reference_premium_bps) ?' in html or \
               'reference_premium_bps != null' in html, (
            "RLIVE_UI_HISTORY_MISSING_NEVER_ZERO: "
            "detail template must null-guard reference_premium_bps before formatting"
        )

    def test_landing_js_missing_premium_suppressed(self):
        """RLIVE_UI_HISTORY_MISSING_NEVER_ZERO: range summary skips missing premiums."""
        js = (REPO / "static/radar/r_live_table.js").read_text()
        history = (REPO / "app/radar_rwa/bnb_history.py").read_text()
        assert 'Decimal(point["reference_premium_bps"])' in history
        assert 'summary.low_bps' in js and 'summary.high_bps' in js


# ── Current state never replaced by history ───────────────────────────────────

class TestHistoryNeverReplacesCurrentState:
    """RLIVE_UI_HISTORY_NEVER_REPLACES_CURRENT_STATE."""

    def test_landing_js_current_values_gated_on_available(self):
        """Current snapshot values only shown when state is AVAILABLE."""
        js = (REPO / "static/radar/r_live_table.js").read_text()
        assert "snap_state" in js or "is_current" in js, (
            "r_live_table.js must distinguish current snapshot state from history"
        )
        assert "AVAILABLE" in js, (
            "r_live_table.js must gate current numeric values on AVAILABLE state"
        )

    def test_detail_js_current_snapshot_and_history_are_separate_fetches(self):
        """Detail page fetches the canonical snapshot and history separately.

        Invariant contract (name-agnostic — the local JS variable may be
        SNAPSHOT_URL or SNAP_URL, the invariant is what is pinned here):
        1. a distinct fetch of the network-free canonical snapshot endpoint
           drives the initial/current render;
        2. a distinct history fetch exists;
        3. the initial/current render path never calls the live acquisition
           endpoint (/{uid});
        4. the live acquisition endpoint is fetched in exactly one place,
           inside the explicit Refresh now control.
        """
        html = (REPO / "app/templates/radar/r_live_detail.html").read_text()
        # 1. canonical snapshot fetch exists and targets the snapshot endpoint
        snap_url_declared = (
            'SNAP_URL = "/api/v1.1/radar/r-live/snapshot"' in html
            or 'SNAPSHOT_URL = "/api/v1.1/radar/r-live/snapshot"' in html)
        assert snap_url_declared, "detail page must declare the canonical snapshot endpoint"
        assert "fetch(SNAP_URL)" in html or "fetch(SNAPSHOT_URL)" in html, (
            "detail page must have a separate snapshot fetch")
        # 2. separate history fetch
        assert "fetch(HIST_URL)" in html, "detail page must have separate history fetch"
        # The populate and build_history_table functions are independent
        assert "function populate" in html, "populate function for current snapshot missing"
        assert "function build_history_table" in html, "build_history_table function missing"
        # 3+4. live acquisition endpoint appears in exactly one fetch and that
        # call site lives inside the explicit Refresh now control — the initial
        # render can never trigger hidden live acquisition.
        live_fetches = [line for line in html.splitlines() if "fetch(LIVE_URL" in line]
        assert len(live_fetches) == 1, (
            "live acquisition must have exactly one fetch call site")
        refresh_now_pos = html.find("function refresh_now")
        live_fetch_pos = html.find(live_fetches[0])
        assert refresh_now_pos != -1 and live_fetch_pos > refresh_now_pos, (
            "live acquisition fetch must be inside the explicit Refresh now control")
        assert "detail-refresh-now" in html, "explicit Refresh now control missing"


# ── Integration: API endpoint returns canonical-shape points ──────────────────

class TestHistoryApiReturnsCanonicalShape:
    """RLIVE_UI_HISTORY_SCHEMA_CONTRACT_REAL: API serves points in canonical shape."""

    def test_history_api_uses_make_r_live_history_point_schema(self):
        """read_r_live_history returns points with reference_premium_bps (canonical)."""
        from app.radar_rwa.r_live_service import read_r_live_history
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

        # Use any approved canonical_id against an in-memory history
        any_uid = next(iter(APPROVED_BY_CANONICAL_ID))

        # In-memory history store (no DB needed)
        from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore

        from finco_radar.assets.contracts import AssetKey

        class _InMemoryLedger:
            def read(self, uid: str, key: AssetKey, *, limit: int = 30) -> list[dict]:
                return [_canonical_point(NOW)]

        points = read_r_live_history(any_uid, history=_InMemoryLedger(), limit=1)
        assert points, "read_r_live_history must return the injected canonical point"
        pt = points[0]
        assert "reference_premium_bps" in pt, (
            "history point must carry reference_premium_bps — canonical field"
        )
        assert "robinhood_basis" in pt and isinstance(pt["robinhood_basis"], dict), (
            "history point must carry nested robinhood_basis object"
        )
        assert "independent_token_reference" in pt and isinstance(pt["independent_token_reference"], dict), (
            "history point must carry nested independent_token_reference object"
        )

    def test_history_api_real_builder_shape_matches_ui_consumption(self):
        """
        Prove that the fields the UI reads are exactly those the builder produces.
        Derives the fixture from the real make_r_live_history_point() output.
        """
        point = _real_history_point_from_builder()

        # Fields the UI MUST read (from canonical builder output):
        assert point.get("reference_premium_bps") is not None, (
            "Builder must produce reference_premium_bps — UI reads this for 1h/24h range"
        )
        basis = point.get("robinhood_basis", {})
        assert basis.get("price_usd_per_token") is not None, (
            "Builder must produce robinhood_basis.price_usd_per_token — UI reads this for detail basis"
        )
        itr = point.get("independent_token_reference", {})
        assert itr.get("priceUsdPerToken") is not None, (
            "Builder must produce independent_token_reference.priceUsdPerToken — UI reads this for detail token ref"
        )
        assert point.get("observed_at") is not None, (
            "Builder must produce observed_at — used for time windowing in fmt_range"
        )
        assert point.get("state") == "AVAILABLE", (
            "Builder must produce state == AVAILABLE for valid AVAILABLE inputs"
        )
