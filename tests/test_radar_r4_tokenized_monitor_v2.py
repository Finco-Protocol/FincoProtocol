"""R4 Monitor V2: exact market truth, gated historical metrics, no frozen-authority change."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from finco_radar.venues.intelligence import BasisPoint, RepresentationHistory
from app.radar_ui.tokenized_monitor_v2 import (
    MAX_MONITORED_UNDERLYINGS, detail_relative_value, enrich_landing_row,
    overview, sorted_filtered_rows,
)

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def gates(history=True, dislocation=True):
    return SimpleNamespace(
        history=SimpleNamespace(access_allowed=history),
        dislocation=SimpleNamespace(access_allowed=dislocation),
        any_premium_allowed=history or dislocation,
    )


def evidence(*, state="AVAILABLE", venue="robinhood", instrument="NVDA"):
    points = tuple(BasisPoint(
        t=(NOW - timedelta(minutes=90 - 10 * index)).isoformat(),
        v=str(value), reason=None,
    ) for index, value in enumerate((0, 20, -10, 15, 25, 40, 55, 70, 120, 150)))
    return RepresentationHistory(
        venue_id=venue, instrument_id=instrument,
        representation_type="tokenized_stock", current_state=state,
        latest_price="100.1", latest_basis_bps="150", latest_basis_reason=None,
        basis_change_24h_bps="10", basis_change_7d_bps="15", points=points,
    )


def fixture_row(*, state="AVAILABLE", basis="150", instrument="NVDA"):
    selected = SimpleNamespace(
        venue_id="robinhood", instrument_id=instrument,
        freshness_state=state, basis_bps=basis,
        source_timestamp=(NOW - timedelta(minutes=2)).isoformat(),
        collected_at=(NOW - timedelta(minutes=1)).isoformat(),
    )
    view = SimpleNamespace(representations=(selected,))
    intel = SimpleNamespace(representations=(evidence(state=state, instrument=instrument),))
    row = {
        "canonical_asset_id": "NVDA", "underlying_name": "NVIDIA",
        "best_venue": "robinhood", "best_instrument_id": instrument,
        "best_price": "100.1", "best_basis_bps": basis,
        "overall_state": state,
    }
    return row, view, intel


def test_pr183_distribution_and_persistence_reused_without_recalculation_or_price_invention():
    row, view, intel = fixture_row()
    out = enrich_landing_row(row, view, intel, gates(), now=NOW)
    assert out["current_basis_bps"] == "150"
    assert out["basis_direction"] == "PREMIUM"
    assert out["evidence_age_seconds"] == 120
    assert out["historical"]["state"] == "AVAILABLE"
    assert out["historical"]["usable_observation_count"] == 10
    assert out["historical"]["history_span_seconds"] == 5400
    assert out["historical"]["historical_median_basis_bps"] is not None
    assert out["historical"]["current_basis_percentile"] is not None
    assert out["persistence"]["state"] == "PREMIUM_DISLOCATION"
    assert out["persistence"]["start_state"] == "PROVEN_CROSSING"
    assert out["persistence"]["duration_seconds"] is not None
    assert out["current_dislocation"]
    assert overview([out], gates())["current_dislocations"] == 1


def test_stale_current_basis_suppressed_while_historical_distribution_survives():
    row, view, intel = fixture_row(state="STALE", basis=None)
    out = enrich_landing_row(row, view, intel, gates(), now=NOW)
    assert out["current_basis_bps"] is None
    assert out["basis_direction"] is None
    assert out["current_dislocation"] is False
    assert out["historical"]["state"] == "STALE"
    assert out["historical"]["historical_median_basis_bps"] is not None
    assert out["historical"]["current_basis_percentile"] is None
    assert out["persistence"]["duration_seconds"] is None


def test_denied_payload_never_enters_shared_html_api_read_projection():
    row, view, intel = fixture_row()
    for history, dislocation in ((False, False), (True, False), (False, True), (True, True)):
        gate = gates(history, dislocation)
        out = enrich_landing_row(row, view, intel if gate.any_premium_allowed else None, gate, now=NOW)
        assert (out["historical"] is not None) == history
        assert (out["persistence"] is not None) == dislocation
        assert out["current_basis_bps"] == "150"  # basic price/basis is not a premium field
        detail = detail_relative_value(intel, gate, now=NOW)
        if not history and not dislocation:
            assert detail == []
        else:
            assert len(detail) == 1
            assert (detail[0]["distribution"] is not None) == history
            assert (detail[0]["persistence"] is not None) == dislocation
            assert "points" not in detail[0]
        summary = overview([out], gate)
        assert (summary["distribution"] is None) == (not history)
        assert (summary["current_dislocations"] is None) == (not dislocation)
        assert (summary["deepstate_historical"] is None) == (not (history and dislocation))


def test_exact_representation_selection_does_not_mix_other_instrument():
    row, view, intel = fixture_row(instrument="NVDA-EXACT")
    mismatched = SimpleNamespace(representations=(evidence(instrument="OTHER"),))
    out = enrich_landing_row(row, view, mismatched, gates(), now=NOW)
    # No borrowed OTHER history/current-dislocation inference.
    assert out["historical"] is None
    assert out["current_dislocation"] is False
    assert out["current_basis_bps"] == "150"  # exact current public market basis remains visible


def test_null_vs_zero_filtering_sorting_and_sensitive_sorting_metadata():
    row, view, intel = fixture_row()
    priced = enrich_landing_row(row, view, intel, gates(), now=NOW)
    no_price = dict(priced, canonical_asset_id="EMPTY", underlying_name="Empty Asset", current_basis_bps=None,
                    current_dislocation=False, basis_direction=None,
                    historical=None, persistence=None, deepstate_state=None)
    par = dict(priced, canonical_asset_id="PAR", underlying_name="Par Asset", current_basis_bps="0",
               current_dislocation=False, basis_direction="PAR")
    rows = [no_price, par, priced]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, sort="basis_abs")] == [
        "NVDA", "PAR", "EMPTY",
    ]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, evidence_filter="available")] == [
        "NVDA", "PAR",
    ]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, evidence_filter="unavailable")] == ["EMPTY"]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, evidence_filter="premium")] == ["NVDA"]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, evidence_filter="discount")] == []
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, query="nVi")] == ["NVDA"]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, query="nVd")] == ["NVDA"]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, query="EMPty ASSET")] == ["EMPTY"]
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, query="PAR")] == ["PAR"]
    assert sorted_filtered_rows(rows, query="unrelated asset") == []
    assert sorted_filtered_rows(rows, query="price hidden under access gate") == []
    assert [r["canonical_asset_id"] for r in sorted_filtered_rows(rows, sort="duration")][-1] == "EMPTY"


def test_deepstate_is_historical_only_and_requires_both_premium_gates():
    row, view, intel = fixture_row()
    source = SimpleNamespace(state="HISTORICAL_EXECUTION_PROVEN")
    denied = enrich_landing_row(row, view, intel, gates(True, False), now=NOW, deepstate=source)
    allowed = enrich_landing_row(row, view, intel, gates(True, True), now=NOW, deepstate=source)
    assert denied["deepstate_state"] is None
    assert allowed["deepstate_state"] == "HISTORICAL_EXECUTION_PROVEN"
    assert overview([allowed], gates())["deepstate_historical"] == 1
    template = (ROOT / "app/templates/radar/tokenized_markets_detail.html").read_text()
    for phrase in ("HISTORICAL EXECUTION", "CURRENT_CROSS_VENUE", "USDG/NVDA",
                   "normalization", "tokenized.history", "tokenized.dislocation"):
        assert phrase.lower() in template.lower()
    assert "CURRENT_CROSS_VENUE = {{ deepstate_history.current_cross_venue_state }}" in template


def test_bounded_read_only_product_scope():
    assert 1 <= MAX_MONITORED_UNDERLYINGS <= 60
    router = (ROOT / "app/radar_ui/tokenized_router.py").read_text()
    assert "[:MAX_MONITORED_UNDERLYINGS]" in router
    assert "build_deepstate_historical_context" in router
    assert "gates.history.access_allowed and gates.dislocation.access_allowed" in router
    shared = (ROOT / "app/crypto_terminal/tokenized_read.py").read_text()
    assert "detail_relative_value(raw_intelligence, gates, now=now)" in shared
    assert "redact_intelligence(raw_intelligence, gates)" in shared
    assert "include_points=True" in shared
    for token in ("requests.get(", "httpx.get(", "WebSocket(", "start_collector(", "requests.post("):
        assert token not in (ROOT / "app/radar_ui/tokenized_monitor_v2.py").read_text()


def test_no_frozen_financial_venue_or_collector_authority_changed():
    import subprocess
    diff = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    forbidden = (
        "financial_engine/", "finco_core/", "finco_yield/",
        "finco_radar/venues/", "finco_radar/signals/",
        "finco_radar/history/", "app/radar_rwa/",
    )
    assert not [path for path in diff if path.startswith(forbidden)]
    assert "app/crypto_terminal/deepstate_composition.py" not in diff
    assert "tools/public_safety_scan.py" not in diff


def test_live_http_render_preserves_empty_state_and_exposes_r4_detail(tmp_path, monkeypatch):
    """Real FastAPI + Jinja integration, with a fresh offline market store and no provider calls."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui.tokenized_router import router
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
    monkeypatch.setattr(
        "app.auth.resolve_request_session",
        lambda _request: SimpleNamespace(user_id="r4-qa", username="r4-qa",
                                         login_at=None, session_type="user"),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    empty = client.get("/radar/tokenized-markets")
    assert empty.status_code == 200
    assert 'data-testid="tm-monitor-summary"' in empty.text
    assert 'data-testid="tm-monitor-filters"' in empty.text
    assert 'data-testid="tm-empty"' in empty.text
    assert 'data-testid="tokenized-markets-table"' not in empty.text
    catalog = client.get("/radar/tokenized-markets?view=catalog")
    assert catalog.status_code == 200 and 'data-testid="tm-catalog-table"' in catalog.text

    nvda = client.get("/radar/tokenized-markets/NVDA")
    assert nvda.status_code == 200
    assert 'data-testid="tmd-relative-value"' in nvda.text
    assert 'data-testid="tmd-deepstate-historical"' in nvda.text
    assert "HISTORICAL EXECUTION" in nvda.text
    assert 'data-testid="tmd-integrity"' in nvda.text
