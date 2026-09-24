"""Focused tests for the Radar product UX correction pass.

Covers:
- Task 1/2: Selected Asset 'Open Company Terminal →' CTA
- Task 11: Company Terminal identity continuity
- Task 12: Featured asset fail-closed behaviour
- Task 14: Generic Revenue period breakdown
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from types import SimpleNamespace as SN
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_ui import composition
from app.radar_ui import router as radar_router_module

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)

_AAPL_UID = "0x" + "aa" * 32
_NVDA_UID = "0x" + "ab" * 32

_AAPL_ADDR = "0x" + "aa" * 20
_NVDA_ADDR = "0x" + "ab" * 20

_CHAIN_ID = 4663


def _make_asset(uid: str, symbol: str, name: str, addr: str) -> SN:
    key = SN(chain_id=_CHAIN_ID, contract_address=addr)
    return SN(
        asset_uid=uid,
        token_symbol=symbol,
        token_name=name,
        raw_evidence={"tokenDecimals": 18},
        deployment_for_chain=lambda c, _k=key: _k if c == _CHAIN_ID else None,
    )


_AAPL_ASSET = _make_asset(_AAPL_UID, "AAPL", "Apple Inc.", _AAPL_ADDR)
_NVDA_ASSET = _make_asset(_NVDA_UID, "NVDA", "NVIDIA Corporation", _NVDA_ADDR)


def _offline_registry(*assets):
    snap = SN(
        assets=list(assets),
        get_by_uid=lambda u: next((a for a in assets if a.asset_uid == u), None),
    )
    return lambda: SN(
        fetch_snapshot=lambda: snap,
        fetch_bound_reference=lambda sn, k: ({}, {}),
    )


def _null_enrichment_result():
    from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult
    return EquityEnrichmentResult(
        state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
    )


def _make_client(universe_assets):
    """Return a TestClient with an offline universe containing the given assets."""
    from app.radar_runtime.service import AcquisitionService, ServiceConfig
    from app.radar_runtime.snapshot_store import SnapshotStore

    composition.set_registry_factory(_offline_registry(*universe_assets))
    service = AcquisitionService(
        SnapshotStore(":memory:"),
        {"radar-core": lambda req: {"evidence": {}, "observedAt": "2026-09-24T09:00:00+00:00"}},
        config=ServiceConfig(per_provider_timeout_seconds=2.0, total_budget_seconds=5.0),
        clock=lambda: NOW,
    )
    radar_router_module.set_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Task 11A: Featured asset CTA still opens the correct canonical terminal
# ─────────────────────────────────────────────────────────────────────────────

class TestFeaturedAssetTerminalCTA:
    """11A: Featured Equity 'Open Company Terminal →' resolves to canonical UID."""

    def test_featured_board_cta_uses_canonical_uid(self):
        """details_url for a featured asset contains its canonical economic_asset_uid."""
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult
        from app.radar_ui.equity_view_model import build_equity_board_row

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(
            result,
            asset_uid=_AAPL_UID,
            fallback_name="Apple Inc.",
            token_symbol="AAPL",
        )
        assert row["details_url"] == f"/radar/equity/{_AAPL_UID}", (
            f"Featured CTA must use canonical UID; got {row['details_url']!r}"
        )
        assert "AAPL" not in row["details_url"] or row["details_url"].endswith(
            _AAPL_UID
        ), "details_url must not embed ticker as the routing key"

    def test_featured_board_cta_uid_not_ticker(self):
        """The routing key in details_url is the UID hex, not the ticker symbol."""
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult
        from app.radar_ui.equity_view_model import build_equity_board_row

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(
            result,
            asset_uid=_NVDA_UID,
            fallback_name="NVIDIA Corporation",
            token_symbol="NVDA",
        )
        assert row["details_url"] == f"/radar/equity/{_NVDA_UID}"
        # The UID must NOT equal the ticker
        assert _NVDA_UID != "NVDA"


# ─────────────────────────────────────────────────────────────────────────────
# Task 11B / 11C: Non-featured canonical asset — Selected Asset CTA + identity
# ─────────────────────────────────────────────────────────────────────────────

class TestSelectedAssetTerminalCTA:
    """11B + 11C: Non-featured canonical asset shows CTA; UID continuity preserved."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        # NVDA is NOT in the default featured symbols list as a real match here
        # because the offline registry only has NVDA — no featured-board assets
        # resolve.  This tests the non-featured path.
        self._client = _make_client([_NVDA_ASSET])
        with patch(
            "app.radar_ui.equity_enrichment.enrich_selected_asset",
            return_value=_null_enrichment_result(),
        ), patch(
            "app.radar_ui.equity_enrichment.enrich_many_selected_assets",
            return_value=[],
        ):
            yield
        composition.set_registry_factory(None)

    def test_selected_asset_panel_shows_cta(self):
        """GET /radar?asset_uid=<NVDA_UID> renders the Company Terminal CTA."""
        page = self._client.get(f"/radar?asset_uid={_NVDA_UID}").text
        assert "Open Company Terminal" in page, (
            "Selected Asset panel must show 'Open Company Terminal →' when a canonical asset is loaded"
        )

    def test_cta_url_contains_canonical_uid(self):
        """The CTA href uses the canonical economic_asset_uid, not the ticker."""
        page = self._client.get(f"/radar?asset_uid={_NVDA_UID}").text
        expected_href = f"/radar/equity/{_NVDA_UID}"
        assert expected_href in page, (
            f"CTA href must be '/radar/equity/{_NVDA_UID}'; page snippet: "
            + page[page.find("Open Company Terminal") - 200: page.find("Open Company Terminal") + 100]
        )

    def test_cta_url_does_not_contain_ticker(self):
        """The CTA href must not route via ticker symbol only."""
        page = self._client.get(f"/radar?asset_uid={_NVDA_UID}").text
        # The terminal link should not be /radar/equity/NVDA
        assert "/radar/equity/NVDA" not in page, (
            "Ticker-only terminal routing detected; must use canonical UID"
        )

    def test_selected_asset_identity_fields_present(self):
        """Selected Asset panel shows canonical identity fields."""
        page = self._client.get(f"/radar?asset_uid={_NVDA_UID}").text
        assert "NVDA" in page
        assert "NVIDIA Corporation" in page
        assert str(_CHAIN_ID) in page
        assert _NVDA_ADDR in page


# ─────────────────────────────────────────────────────────────────────────────
# Task 11C: Exact identity continuity assertion
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentityContinuity:
    """11C: economic_asset_uid in terminal URL == selected asset economic_asset_uid."""

    def test_terminal_url_economic_uid_matches_selected(self):
        """The terminal URL embeds the exact same UID as the selected asset."""
        from app.radar_ui.equity_view_model import build_equity_board_row
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        # Simulate the router building a board row for the selected asset
        row = build_equity_board_row(
            result,
            asset_uid=_AAPL_UID,
            fallback_name="Apple Inc.",
            token_symbol="AAPL",
        )
        # Extract the UID from the URL
        url = row["details_url"]
        assert url.endswith(_AAPL_UID), (
            f"Terminal URL {url!r} must end with selected economic_asset_uid {_AAPL_UID!r}"
        )
        extracted_uid = url.split("/")[-1]
        assert extracted_uid == _AAPL_UID, (
            f"Extracted UID {extracted_uid!r} != selected asset UID {_AAPL_UID!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task 11D: No ticker fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestNoTickerFallback:
    """11D: Terminal navigation must not depend solely on ticker/symbol."""

    def test_two_assets_same_symbol_different_uid_different_terminal(self):
        """Two assets with the same symbol but different UIDs must have different terminal URLs."""
        from app.radar_ui.equity_view_model import build_equity_board_row
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult

        uid_a = "0x" + "ca" * 32
        uid_b = "0x" + "cb" * 32

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        row_a = build_equity_board_row(result, asset_uid=uid_a, token_symbol="TEST")
        row_b = build_equity_board_row(result, asset_uid=uid_b, token_symbol="TEST")

        assert row_a["details_url"] != row_b["details_url"], (
            "Two assets sharing a ticker must map to different terminal URLs — "
            "routing must be UID-based, not ticker-based"
        )

    def test_featured_board_cta_does_not_use_ticker_as_routing_key(self):
        """Featured board row details_url routing segment is the UID, not 'AAPL' etc."""
        from app.radar_ui.equity_view_model import build_equity_board_row
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(
            result, asset_uid=_AAPL_UID, token_symbol="AAPL"
        )
        url_segment = row["details_url"].split("/")[-1]
        # The last segment must be the UID, not the ticker
        assert url_segment == _AAPL_UID, (
            f"Terminal URL segment is {url_segment!r}; expected UID {_AAPL_UID!r}"
        )
        assert url_segment != "AAPL", (
            "Ticker-only terminal routing detected"
        )

    def test_selected_asset_cta_does_not_route_by_ticker(self):
        """The Selected Asset CTA in index.html is bound to economic_asset_uid data attribute."""
        with _make_client([_NVDA_ASSET]) as client:
            with patch(
                "app.radar_ui.equity_enrichment.enrich_selected_asset",
                return_value=_null_enrichment_result(),
            ), patch(
                "app.radar_ui.equity_enrichment.enrich_many_selected_assets",
                return_value=[],
            ):
                page = client.get(f"/radar?asset_uid={_NVDA_UID}").text
        # data-economic-asset-uid must be set to the UID, not the ticker
        assert f'data-economic-asset-uid="{_NVDA_UID}"' in page, (
            "CTA must carry data-economic-asset-uid with the canonical UID"
        )
        assert 'data-economic-asset-uid="NVDA"' not in page, (
            "CTA data-economic-asset-uid must not be the ticker string"
        )
        composition.set_registry_factory(None)


# ─────────────────────────────────────────────────────────────────────────────
# Task 12: Featured assets exist in canonical registry (fail-closed proof)
# ─────────────────────────────────────────────────────────────────────────────

class TestFeaturedAssetTruth:
    """Task 12: Featured board is fail-closed — absent assets show unavailable, not fabricated."""

    def test_missing_featured_symbol_shows_unavailable_not_fabricated(self):
        """An asset in the default list that is not in the live registry renders as UNAVAILABLE."""
        from app.radar_ui.equity_view_model import build_equity_board_row
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(result, asset_uid="", token_symbol="NOTREAL")
        assert row["state"] == "NOT_AVAILABLE"

    def test_featured_board_fallback_row_has_no_valid_terminal_url(self):
        """When a featured symbol cannot resolve to a canonical asset, details_url is not a terminal URL."""
        from app.radar_ui.router import _DEFAULT_FEATURED_SYMBOLS
        from app.radar_ui.router import _load_equity_and_featured_board

        # Universe with NO assets — all featured symbols will be unresolved
        with patch(
            "app.radar_ui.equity_enrichment.get_equity_fundamentals_many",
            return_value=[],
        ):
            _, board_rows = _load_equity_and_featured_board(universe=[], selected=None)

        for row in board_rows:
            if row.get("state") == "UNAVAILABLE":
                # Fallback rows must not point to a real terminal
                assert not row["details_url"].startswith("/radar/equity/"), (
                    f"Fallback row for {row['symbol']!r} must not have a terminal URL; "
                    f"got {row['details_url']!r}"
                )

    def test_featured_board_resolved_symbol_has_terminal_url(self):
        """When a featured symbol resolves correctly, details_url is a proper terminal URL."""
        from app.radar_ui.equity_view_model import build_equity_board_row
        from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_AVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(result, asset_uid=_AAPL_UID, token_symbol="AAPL")
        assert row["details_url"].startswith("/radar/equity/"), (
            f"Resolved asset must have terminal URL; got {row['details_url']!r}"
        )
        assert row["details_url"] == f"/radar/equity/{_AAPL_UID}"


# ─────────────────────────────────────────────────────────────────────────────
# Task 14: Generic Revenue period detail
# ─────────────────────────────────────────────────────────────────────────────

class TestGenericRevenuePeriodDetail:
    """Task 14: Revenue detail comes from authoritative engine output; reconciles."""

    def _make_fake_period(self, period_num: int, generation_mwh: float,
                          revenue_keur: float) -> SN:
        return SN(
            period=period_num,
            year_index=period_num,
            period_in_year=1,
            is_operation=True,
            generation_mwh=generation_mwh,
            revenue_keur=revenue_keur,
            opex_keur=revenue_keur * 0.3,
            ebitda_keur=revenue_keur * 0.7,
            cf_after_tax_keur=revenue_keur * 0.5,
            senior_ds_keur=revenue_keur * 0.2,
            senior_balance_keur=1000.0,
            senior_principal_keur=50.0,
            senior_interest_keur=30.0,
        )

    def test_derivation_evidence_includes_revenue_periods(self):
        """_build_runtime_derivation_evidence populates revenue_periods from result.periods[]."""
        from app.api.project_runner import _build_runtime_derivation_evidence

        periods = [
            self._make_fake_period(1, 1000.0, 500.0),
            self._make_fake_period(2, 1100.0, 550.0),
            self._make_fake_period(3, 1050.0, 525.0),
        ]
        result = SN(
            periods=periods,
            total_revenue_keur=1575.0,
            total_ebitda_keur=1102.5,
            total_opex_keur=472.5,
        )
        evidence = _build_runtime_derivation_evidence(result)
        revenue_ev = evidence.get("revenue", {})
        assert "revenue_periods" in revenue_ev, (
            "derivation_evidence.revenue must include revenue_periods"
        )
        assert len(revenue_ev["revenue_periods"]) == 3

    def test_revenue_periods_match_engine_periods(self):
        """Each entry in revenue_periods exactly mirrors the WaterfallResult period values."""
        from app.api.project_runner import _build_runtime_derivation_evidence

        periods = [
            self._make_fake_period(1, 1000.0, 500.0),
            self._make_fake_period(2, 1100.0, 550.0),
        ]
        result = SN(
            periods=periods,
            total_revenue_keur=1050.0,
            total_ebitda_keur=735.0,
            total_opex_keur=315.0,
        )
        evidence = _build_runtime_derivation_evidence(result)
        rev_periods = evidence["revenue"]["revenue_periods"]

        assert rev_periods[0]["generation_mwh"] == 1000.0
        assert rev_periods[0]["revenue_keur"] == 500.0
        assert rev_periods[1]["generation_mwh"] == 1100.0
        assert rev_periods[1]["revenue_keur"] == 550.0

    def test_revenue_periods_reconcile_to_total(self):
        """sum(period.revenue_keur) reconciles to authoritative total_revenue_keur."""
        from app.api.project_runner import _build_runtime_derivation_evidence

        revenues = [500.0, 510.0, 520.0, 530.0]
        periods = [
            self._make_fake_period(i + 1, 1000.0 + i * 10, rev)
            for i, rev in enumerate(revenues)
        ]
        expected_total = sum(revenues)
        result = SN(
            periods=periods,
            total_revenue_keur=expected_total,
            total_ebitda_keur=expected_total * 0.7,
            total_opex_keur=expected_total * 0.3,
        )
        evidence = _build_runtime_derivation_evidence(result)
        rev_ev = evidence["revenue"]
        period_sum = sum(
            p["revenue_keur"] for p in rev_ev["revenue_periods"]
            if p["revenue_keur"] is not None
        )
        assert math.isclose(period_sum, expected_total, rel_tol=1e-9), (
            f"sum(revenue_periods) = {period_sum} does not reconcile to "
            f"total_revenue_keur = {expected_total}"
        )

    def test_no_second_revenue_formula_in_derivation_evidence(self):
        """revenue_periods values are taken verbatim from periods[], not recomputed."""
        from app.api.project_runner import _build_runtime_derivation_evidence

        # Deliberately give a period with an unusual revenue that would not
        # equal tariff × generation.  If the derivation were recomputing,
        # the value would differ.
        period = self._make_fake_period(1, 1000.0, 12345.678)
        result = SN(
            periods=[period],
            total_revenue_keur=12345.678,
            total_ebitda_keur=8641.975,
            total_opex_keur=3703.703,
        )
        evidence = _build_runtime_derivation_evidence(result)
        rev_periods = evidence["revenue"]["revenue_periods"]
        assert rev_periods[0]["revenue_keur"] == 12345.678, (
            "revenue_periods must preserve WaterfallPeriod.revenue_keur verbatim"
        )

    def test_formatted_revenue_derivation_includes_period_list(self):
        """_format_revenue_derivation preserves and formats the period list."""
        from app.ui.runtime_summary import _format_revenue_derivation

        raw = {
            "display_value_keur": 1575.0,
            "summary_method": "Total revenue from backend operating periods.",
            "period_formula": "Revenue_t = WaterfallPeriod.revenue_keur",
            "period_count": 3,
            "sample_period_label": "Y1-H1",
            "sample_generation_mwh": 1000.0,
            "sample_revenue_keur": 500.0,
            "audit_source": "WaterfallResult.total_revenue_keur",
            "revenue_periods": [
                {"period_label": "Y1-H1", "generation_mwh": 1000.0, "revenue_keur": 500.0},
                {"period_label": "Y2-H1", "generation_mwh": 1100.0, "revenue_keur": 550.0},
                {"period_label": "Y3-H1", "generation_mwh": 1050.0, "revenue_keur": 525.0},
            ],
        }
        formatted = _format_revenue_derivation(raw)
        assert "revenue_periods" in formatted
        assert len(formatted["revenue_periods"]) == 3
        assert formatted["revenue_periods"][0]["period_label"] == "Y1-H1"
        assert "MWh" in formatted["revenue_periods"][0]["generation_mwh"]
        assert "kEUR" in formatted["revenue_periods"][0]["revenue_keur"]

    def test_formatted_revenue_derivation_empty_periods_is_empty_list(self):
        """When revenue_periods is absent, formatted result has empty list."""
        from app.ui.runtime_summary import _format_revenue_derivation

        raw = {
            "display_value_keur": 100.0,
            "summary_method": "x",
            "period_formula": "x",
            "period_count": 0,
            "sample_period_label": "",
            "sample_generation_mwh": None,
            "sample_revenue_keur": None,
            "audit_source": "x",
        }
        formatted = _format_revenue_derivation(raw)
        assert formatted["revenue_periods"] == []

    def test_revenue_periods_uses_only_operation_periods(self):
        """Only is_operation=True periods appear in revenue_periods (no construction)."""
        from app.api.project_runner import _build_runtime_derivation_evidence

        op_period = self._make_fake_period(2, 1000.0, 500.0)
        non_op = SN(
            period=1, year_index=0, period_in_year=1, is_operation=False,
            generation_mwh=0.0, revenue_keur=0.0, opex_keur=0.0,
            ebitda_keur=0.0, cf_after_tax_keur=0.0, senior_ds_keur=0.0,
            senior_balance_keur=0.0, senior_principal_keur=0.0,
            senior_interest_keur=0.0,
        )
        result = SN(
            periods=[non_op, op_period],
            total_revenue_keur=500.0,
            total_ebitda_keur=350.0,
            total_opex_keur=150.0,
        )
        evidence = _build_runtime_derivation_evidence(result)
        rev_periods = evidence["revenue"]["revenue_periods"]
        assert len(rev_periods) == 1, (
            "Only operating periods must appear in revenue_periods"
        )
        assert rev_periods[0]["revenue_keur"] == 500.0


# ─────────────────────────────────────────────────────────────────────────────
# Task 15: Frozen namespace verification (static imports check)
# ─────────────────────────────────────────────────────────────────────────────

class TestFrozenNamespace:
    """Task 15: Verify app/ files do not import from financial_engine or finco_core production paths."""

    def test_project_runner_does_not_import_finco_core_revenue(self):
        """project_runner derivation additions must not import finco_core.revenue directly."""
        import ast
        import os
        src = open(
            os.path.join(os.path.dirname(__file__), "..", "app", "api", "project_runner.py")
        ).read()
        tree = ast.parse(src)
        direct_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any(
                alias.name.startswith("finco_core.revenue")
                if isinstance(node, ast.Import) else
                (node.module or "").startswith("finco_core.revenue")
                for alias in (node.names if isinstance(node, ast.Import) else [node])
            )
        ]
        # finco_core.revenue imports are allowed IF they were already there
        # before this correction pass — we just ensure no new ones were added
        # via the derivation evidence extension.  Since the original file had
        # none, assert zero.
        assert len(direct_imports) == 0, (
            "project_runner must not import finco_core.revenue directly — "
            "it only reads from WaterfallResult attributes"
        )

    def test_runtime_summary_does_not_derive_economics(self):
        """_format_revenue_derivation must not call any revenue calculation function."""
        import ast
        import os
        src = open(
            os.path.join(os.path.dirname(__file__), "..", "app", "ui", "runtime_summary.py")
        ).read()
        # Ensure no import of finco_core.revenue or financial_engine in this file
        tree = ast.parse(src)
        forbidden = {"finco_core", "financial_engine"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module_root = node.module.split(".")[0]
                assert module_root not in forbidden, (
                    f"runtime_summary.py imports from {node.module!r} — "
                    "presentation layer must not import engine modules"
                )
