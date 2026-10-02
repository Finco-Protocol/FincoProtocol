"""RWA Basis / Tokenized Market Monitor V1 acceptance contract."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore, read_r_live_basis_history_summary_readonly
from app.radar_rwa.rwa_basis import (BasisStatus, HISTORY_24H_MAX_SKEW_SECONDS, MarketMetric,
                                     build_basis_record, compute_basis, resolve_policy_by_uid)
from finco_radar.authority.r_live_policy import AAPL_UID, APPROVED_RLIVE_ASSETS

NOW = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)


def policy(symbol="AAPL"):
    return next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == symbol)


def calc(ref, tok, **kw):
    args = dict(reference_value=ref, tokenized_value=tok, identity_bound=True,
                reference_freshness="AVAILABLE", tokenized_freshness="AVAILABLE")
    args.update(kw)
    return compute_basis(**args)


def row(p=None, *, ref="100", tok="101", bps="100", ref_at=NOW, tok_at=NOW,
        state="AVAILABLE", uid=None, key=None, metrics=None):
    p = p or policy()
    cid = key or p.asset_key.canonical_id
    chain, contract = cid.split(":", 1)
    return {"canonical_id": p.asset_key.canonical_id, "state": state, "data": {
        "exact_asset_key": {"canonical_id": cid, "chain_id": int(chain), "contract_address": contract},
        "economic_asset_uid": uid or p.economic_asset_uid,
        "robinhood_basis": {"state": "AVAILABLE", "price_usd_per_token": ref,
                            "source": "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
                            "observed_at": ref_at.isoformat() if ref_at else None},
        "token_reference": {"state": "AVAILABLE", "price_usd_per_token": tok,
                            "source": "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD",
                            "observed_at": tok_at.isoformat() if tok_at else None},
        "b1_0_premium": {"state": "AVAILABLE", "value_bps": bps},
        "market_metrics": metrics or {"liquidity": None, "volume_24h": None},
    }}


def test_exact_identity_and_basis_math():
    out = build_basis_record(row(), policy(), evaluation_time=NOW)
    assert out["evaluation_status"] == "AVAILABLE"
    assert out["basis"]["basis_fraction"] == "0.01"
    assert out["basis"]["basis_bps"] == "100.00"
    assert out["basis"]["premium_discount"] == "PREMIUM"


def test_cross_asset_pairing_rejected_and_ticker_forbidden():
    aapl, nvda = policy("AAPL"), policy("NVDA")
    assert build_basis_record(row(aapl, uid=nvda.economic_asset_uid), aapl, evaluation_time=NOW)["evaluation_status"] == "UNBOUND"
    assert resolve_policy_by_uid("AAPL") is None
    assert resolve_policy_by_uid("Apple Inc.") is None
    assert resolve_policy_by_uid(AAPL_UID).symbol == "AAPL"


def test_missing_factual_zero_and_denominator_rules():
    assert calc(None, Decimal("1")).basis_bps is None
    assert calc(Decimal("1"), None).basis_bps is None
    zero = calc(Decimal("100"), Decimal("0"))
    assert zero.status is BasisStatus.AVAILABLE and zero.basis_bps == Decimal("-10000")
    assert calc(Decimal("0"), Decimal("1")).basis_bps is None
    assert MarketMetric(Decimal("0"), "RAW", "SOURCE").to_dict()["value"] == "0"


def test_unit_currency_stale_and_decimal_semantics():
    assert calc(Decimal("1"), Decimal("1"), tokenized_unit="EUR_PER_TOKEN").reason == "UNIT_MISMATCH"
    assert calc(Decimal("1"), Decimal("1"), tokenized_currency="EUR").reason == "CURRENCY_MISMATCH"
    assert calc(Decimal("1"), Decimal("1"), reference_freshness="STALE").status is BasisStatus.STALE
    assert calc(Decimal("1"), Decimal("1"), tokenized_freshness="STALE").status is BasisStatus.STALE
    assert calc(Decimal("100"), Decimal("99")).basis_bps == Decimal("-100.00")
    assert calc(Decimal("100"), Decimal("100")).basis_bps == Decimal("0")
    assert calc(Decimal("0.1"), Decimal("0.3")).basis_bps == Decimal("20000")


def test_timestamp_gap_and_missing_market_metrics():
    out = build_basis_record(row(ref_at=NOW - timedelta(days=2)), policy(), evaluation_time=NOW)
    assert out["evaluation_status"] == "UNAVAILABLE"
    assert out["basis"]["basis_bps"] is None
    assert out["timing_relationship"] == "OUTSIDE_CANONICAL_COMPARISON_WINDOW"
    current = build_basis_record(row(), policy(), evaluation_time=NOW)
    assert current["tokenized_observation"]["liquidity"] is None
    assert current["tokenized_observation"]["volume_24h"] is None


def point(p, at, premium, seq):
    return {"economic_asset_uid": p.economic_asset_uid, "asset_key": p.asset_key.canonical_id,
            "observed_at": at.isoformat(), "collected_at": at.isoformat(), "state": "AVAILABLE",
            "robinhood_basis": {"price_usd_per_token": "100"},
            "independent_token_reference": {"priceUsdPerToken": "101", "evidence": {"retrievedAt": at.isoformat(), "seq": seq}},
            "reference_premium_bps": premium}


def history_summary(tmp_path, points):
    p, db = policy(), tmp_path / "history.db"
    store = BnbIntelligenceHistoryStore(str(db), allowed_chain_id=4663)
    try:
        for item in points:
            store.put(item)
    finally:
        store.close()
    return read_r_live_basis_history_summary_readonly(
        p.economic_asset_uid, p.asset_key, as_of=NOW,
        max_24h_baseline_skew_seconds=HISTORY_24H_MAX_SKEW_SECONDS, path=str(db))


def test_history_prior_change_and_no_interpolation(tmp_path):
    p = policy()
    summary = history_summary(tmp_path, [point(p, NOW-timedelta(hours=24, minutes=10), "50", 1),
                                         point(p, NOW-timedelta(minutes=10), "80", 2),
                                         point(p, NOW-timedelta(minutes=5), "100", 3)])
    assert summary["prior_observation"]["premium_bps"] == "80"
    assert summary["change_24h"]["state"] == "AVAILABLE"
    assert summary["change_24h"]["change_bps"] == "50"
    assert summary["interpolation"] is False


def test_history_missing_baseline_stays_unavailable(tmp_path):
    p = policy()
    summary = history_summary(tmp_path, [point(p, NOW-timedelta(hours=26), "50", 1),
                                         point(p, NOW-timedelta(minutes=5), "100", 2)])
    assert summary["change_24h"]["state"] == "UNAVAILABLE"
    assert summary["change_24h"]["change_bps"] is None
    assert summary["interpolation"] is False


def test_api_exact_uid_only():
    from app.api.v1_1.r_live_public_router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1.1")
    client = TestClient(app)
    assert client.get("/api/v1.1/radar/rwa-basis/AAPL").json()["state"] == "UNBOUND"
    assert client.get(f"/api/v1.1/radar/rwa-basis/{AAPL_UID}").json()["state"] in {"AVAILABLE", "STALE", "UNAVAILABLE"}
    unknown = "0x" + "f" * 64
    assert client.get(f"/api/v1.1/radar/rwa-basis/{unknown}").json()["state"] == "UNBOUND"


def test_no_recommendation_vocabulary_and_no_action_path():
    root = Path(__file__).resolve().parents[1]
    template = (root / "app/templates/radar/rwa_basis.html").read_text().lower()
    module = (root / "app/radar_rwa/rwa_basis.py").read_text().lower()
    for word in ("cheap", "expensive", "undervalued", "overvalued", "arb opportunity"):
        assert word not in template
    assert "finco_radar.quotes" not in module and "wallet" not in module and "@router.post" not in module
