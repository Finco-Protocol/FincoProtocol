"""Yield Historical Risk & Persistence V2 — deterministic read-model tests.

Covers the PR #184 test matrix: distribution/percentile determinism and tie
policy, eligibility gates, missing-evidence isolation, peak compression,
TVL drawdown, reward share, persistence labelling, sigma reuse, no write
path, no provider/network, malformed-row safety, no score output.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from finco_yield.history import YieldHistoryStore
from finco_yield.intelligence import build_intelligence
import json

from finco_yield.risk import (MIN_HISTORY_SPAN_SECONDS,
                              MIN_USABLE_OBSERVATIONS,
                              RiskError, RiskState,
                              build_historical_risk,
                              _midrank_percentile, _nearest_rank)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _record(store, uid, observed_at, apy=None, tvl=None, base=None,
            rewards=None, extra_payload=None):
    payload = {}
    if apy is not None:
        payload["apy_total"] = apy
    if tvl is not None:
        payload["tvl_usd"] = tvl
    if base is not None:
        payload["apy_base"] = base
    if rewards is not None:
        payload["apy_rewards"] = rewards
    if extra_payload:
        payload.update(extra_payload)
    store.append(ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=observed_at,
        source_authority="NATIVE_ENRICHED", source_uri="https://test",
        adapter_version="test", payload=payload))


from finco_yield.observation import ImmutableObservationRecord


@pytest.fixture()
def store(tmp_path):
    return YieldHistoryStore(tmp_path / "risk_history.jsonl")


def _seed_window(store, uid, *, count=12, apy_fn=None, tvl_fn=None,
                 end=NOW, step_hours=6, base=None, rewards=None):
    apy_fn = apy_fn or (lambda i: "0.0400")
    for i in range(count):
        moment = end - timedelta(hours=(count - 1 - i) * step_hours)
        _record(store, uid, moment,
                apy=apy_fn(i), tvl=tvl_fn(i) if tvl_fn else None,
                base=base, rewards=rewards)


# ── V1 authorities unchanged ────────────────────────────────────────────────

def test_existing_apy_delta_mathematics_unchanged(store):
    """V1 intelligence deltas must be byte-identical with/without V2 present:
    4.00% -> 4.40% over 24h => +40 bps UP."""
    _seed_window(store, "yld_a", apy_fn=lambda i: "0.0400" if i < 11 else "0.0440")
    intel = build_intelligence(store, "yld_a", as_of=NOW)
    h24 = intel.horizon("24h")
    assert h24.apy_delta.delta_bps == Decimal("40.0")
    assert h24.apy_delta.direction.value == "UP"


def test_sigma_authority_is_reused_not_reimplemented(store):
    """The V2 canonical_sigma is the EXISTING intelligence sigma object value
    (FINCO_HISTORICAL, 30d) — composed, never a second stdev implementation."""
    _seed_window(store, "yld_a", count=12,
                 apy_fn=lambda i: str(Decimal("0.04") + Decimal(i) * Decimal("0.0001")))
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    intel = build_intelligence(store, "yld_a", as_of=NOW)
    h30 = intel.horizon("30d")
    assert h30.apy_sigma is not None
    assert risk.apy_context.canonical_sigma == h30.apy_sigma
    assert risk.apy_context.canonical_sigma_source == "FINCO_HISTORICAL"


# ── percentile + quartiles ──────────────────────────────────────────────────

def test_percentile_and_quartiles_deterministic(store):
    _seed_window(store, "yld_a", count=12,
                 apy_fn=lambda i: str(Decimal("0.04") + Decimal(i) * Decimal("0.0001")))
    a = build_historical_risk(store, "yld_a", as_of=NOW)
    b = build_historical_risk(store, "yld_a", as_of=NOW)
    d = a.apy_distribution
    assert d == b.apy_distribution, "distribution must be deterministic"
    values = sorted(Decimal("0.04") + Decimal(i) * Decimal("0.0001")
                    for i in range(12))
    assert d.min == values[0] and d.max == values[-1]
    # nearest-rank q25 on n=12: index ceil(0.25*12)-1 = 2
    assert d.q25 == values[2]
    # median: index ceil(0.5*12)-1 = 5 (upper-middle, documented)
    assert d.median == values[5]
    # q75: index ceil(0.75*12)-1 = 8
    assert d.q75 == values[8]


def test_percentile_tie_semantics_deterministic():
    """Midrank ties: equal values share the halfway rank."""
    values = [Decimal("0.04")] * 5
    # current equal to all -> (0 below + 0.5*5)/5 = 0.5
    assert _midrank_percentile(values, Decimal("0.04")) == Decimal("0.5")
    # below every value -> 0
    assert _midrank_percentile(values, Decimal("0.01")) == Decimal("0")
    # above every value -> 1
    assert _midrank_percentile(values, Decimal("0.09")) == Decimal("1")
    # mixed: 2 below, 3 equal -> (2 + 1.5)/5 = 0.7
    mixed = [Decimal("0.01"), Decimal("0.01"), Decimal("0.04"),
             Decimal("0.04"), Decimal("0.04")]
    assert _midrank_percentile(mixed, Decimal("0.04")) == Decimal("0.7")


def test_percentile_of_current_within_pool_history(store):
    """Percentile is the rank WITHIN the same pool's usable window history:
    current 0.0450 is the max of the seeded series -> 1."""
    _seed_window(store, "yld_a", count=12,
                 apy_fn=lambda i: str(Decimal("0.04") + Decimal(i) * Decimal("0.0001")))
    _record(store, "yld_a", NOW, apy="0.0450")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    # midrank counts the current observation itself in the equal bucket:
    # (12 below + 0.5 self) / 13
    assert risk.apy_distribution.percentile ==         (Decimal("12.5") / Decimal(13)).quantize(Decimal("0.000001"))
    assert risk.apy_distribution.percentile_policy == \
        "MIDRANK_WITHIN_POOL_USABLE_OBSERVATIONS"


# ── eligibility gates ───────────────────────────────────────────────────────

def test_insufficient_point_count_fails_closed(store):
    for i in range(MIN_USABLE_OBSERVATIONS - 1):
        _record(store, "yld_a", NOW - timedelta(hours=(MIN_USABLE_OBSERVATIONS - i)),
                apy="0.04")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.state in (RiskState.INSUFFICIENT_HISTORY, RiskState.PARTIAL)
    assert risk.apy_distribution.percentile is None


def test_insufficient_history_span_fails_closed(store):
    """12 points over ~5 minutes: count met, span gate fails -> PARTIAL with
    percentile withheld (a burst is not history)."""
    for i in range(12):
        _record(store, "yld_a", NOW - timedelta(minutes=(12 - i)), apy="0.04")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.history.observation_count == 12
    assert risk.history.history_span_seconds < MIN_HISTORY_SPAN_SECONDS
    assert risk.state == RiskState.PARTIAL
    assert risk.reason == "HISTORY_SPAN_BELOW_POLICY"
    assert risk.apy_distribution.percentile is None
    assert risk.apy_distribution.q25 is not None  # quartiles still factual


def test_both_gates_met_available(store):
    _seed_window(store, "yld_a", count=12, step_hours=6)  # ~3 days span
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.state == RiskState.AVAILABLE
    assert risk.history.observation_count >= MIN_USABLE_OBSERVATIONS
    assert risk.history.history_span_seconds >= MIN_HISTORY_SPAN_SECONDS


# ── missing != zero ─────────────────────────────────────────────────────────

def test_missing_apy_never_becomes_zero(store):
    for i in range(20):
        _record(store, "yld_a", NOW - timedelta(hours=(20 - i)),
                apy="0.04" if i % 2 == 0 else None, tvl="5000000")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    # only the 10 APY-bearing observations participate; None never coerced
    assert risk.history.observation_count == 10
    assert risk.apy_distribution.min == Decimal("0.04")
    assert risk.apy_distribution.max == Decimal("0.04")
    assert risk.apy_distribution.q25 is not None


def test_no_observations_unavailable(store):
    risk = build_historical_risk(store, "yld_empty", as_of=NOW)
    assert risk.state == RiskState.UNAVAILABLE
    assert risk.reason == "NO_USABLE_OBSERVATIONS"
    assert risk.apy_distribution.percentile is None
    assert risk.tvl_context.current_tvl is None
    assert risk.reward_context.reward_apy_share is None


# ── APY peak compression ────────────────────────────────────────────────────

def test_peak_compression_arithmetic(store):
    """current 4.00% vs trailing peak 5.00% -> -100 bps."""
    def apy(i):
        return "0.0500" if i == 3 else "0.0400"
    _seed_window(store, "yld_a", count=12, apy_fn=apy)
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.apy_context.trailing_peak_apy == Decimal("0.0500")
    assert risk.apy_context.current_apy == Decimal("0.0400")
    assert risk.apy_context.current_vs_peak_delta_bps == Decimal("-100.0000")


# ── TVL context / drawdown ──────────────────────────────────────────────────

def test_tvl_context_and_drawdown(store):
    tvls = ["8000000", "5000000", "5000000", "4000000"]
    for i in range(12):
        _record(store, "yld_a", NOW - timedelta(hours=(12 - i) * 2),
                apy="0.04", tvl=tvls[min(i // 3, 3)])
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.tvl_context.current_tvl == Decimal("4000000")
    assert risk.tvl_context.trailing_min_tvl == Decimal("4000000")
    assert risk.tvl_context.trailing_max_tvl == Decimal("8000000")
    assert risk.tvl_context.tvl_drawdown_fraction == Decimal("-0.5")
    assert risk.tvl_context.tvl_observation_count == 12


def test_tvl_drawdown_requires_positive_trailing_max(store):
    for i in range(11):
        _record(store, "yld_a", NOW - timedelta(hours=(20 - i)),
                apy="0.04", tvl="0")
    _record(store, "yld_a", NOW - timedelta(hours=1), apy="0.04", tvl="0")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.tvl_context.trailing_max_tvl == Decimal("0")
    assert risk.tvl_context.tvl_drawdown_fraction is None, (
        "drawdown is undefined against a zero trailing max — never computed")


def test_missing_tvl_does_not_suppress_apy_metrics(store):
    _seed_window(store, "yld_a", count=12)   # APY only, no TVL at all
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.tvl_context.current_tvl is None
    assert risk.tvl_context.tvl_observation_count == 0
    # APY evidence fully available
    assert risk.state == RiskState.AVAILABLE
    assert risk.apy_distribution.q25 is not None
    assert risk.apy_context.trailing_peak_apy is not None


# ── reward dependency ───────────────────────────────────────────────────────

def test_reward_share_requires_valid_components(store):
    _record(store, "yld_a", NOW - timedelta(hours=1),
            apy="0.04", base="0.03", rewards="0.01")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.reward_context.base_apy == Decimal("0.03")
    assert risk.reward_context.rewards_apy == Decimal("0.01")
    assert risk.reward_context.total_apy == Decimal("0.04")
    assert risk.reward_context.reward_apy_share == Decimal("0.25")


def test_missing_reward_component_does_not_infer_zero(store):
    _record(store, "yld_a", NOW - timedelta(hours=1), apy="0.04", base="0.03")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.reward_context.rewards_apy is None
    assert risk.reward_context.reward_apy_share is None, (
        "share must not be inferred (e.g. total - base) when a component is absent")


def test_reward_share_undefined_for_zero_total(store):
    _record(store, "yld_a", NOW - timedelta(hours=1),
            apy="0", base="0", rewards="0")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    # factual zero APY is data; the share stays undefined (0/0)
    assert risk.reward_context.total_apy == Decimal("0")
    assert risk.reward_context.reward_apy_share is None


# ── persistence labelling ────────────────────────────────────────────────────

def test_persistence_is_explicitly_observation_based(store):
    _seed_window(store, "yld_a", count=12,
                 apy_fn=lambda i: "0.0400" if i % 2 == 0 else "0.0402")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.persistence.methodology == "OBSERVATION_BASED"
    assert risk.persistence.fraction_within_10pct_of_median == Decimal("1")
    assert risk.persistence.usable_observation_count == 12
    # fraction above the window median is a factual count, 0..1
    assert Decimal("0") <= risk.persistence.fraction_above_window_median <= Decimal("1")


# ── Treasury boundary ────────────────────────────────────────────────────────

def test_current_treasury_is_not_applied_historically(store):
    """The V2 context carries NO historical Treasury series and no
    treasury-adjusted historical values — only the existing current metric
    lives elsewhere; here nothing Treasury-derived appears at all."""
    _seed_window(store, "yld_a", count=12)
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    payload = risk.to_dict()
    for section in (payload["history"], payload["apy_distribution"],
                    payload["apy_context"], payload["tvl_context"],
                    payload["reward_context"], payload["persistence"]):
        assert not any("treasury" in key.lower() for key in section)


# ── purity: no writes, no network, malformed rows ───────────────────────────

def test_read_model_performs_no_store_writes(store, tmp_path):
    path = store.path
    before = path.read_bytes() if path.exists() else b""
    _seed_window(store, "yld_a", count=12)
    before = path.read_bytes()
    build_historical_risk(store, "yld_a", as_of=NOW)
    build_historical_risk(store, "yld_a", as_of=NOW)
    assert path.read_bytes() == before, "risk read model must never write history"


def test_malformed_observation_does_not_fabricate_evidence(store):
    for i in range(10):
        _record(store, "yld_a", NOW - timedelta(hours=(12 - i)),
                apy="0.0400" if i < 5 else "0.0410")
    # a row whose payload simply lacks APY/TVL is unusable, never fabricated
    _record(store, "yld_a", NOW - timedelta(minutes=30),
            extra_payload={"note": "no metrics"})
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.history.observation_count == 10
    assert risk.apy_distribution.min == Decimal("0.0400")
    assert risk.apy_distribution.max == Decimal("0.0410")


def test_no_provider_or_network_module_imported():
    source = open("finco_yield/risk.py", encoding="utf-8").read()
    for forbidden in ("httpx", "requests", "urllib", "socket", "ZeroX",
                      "defillama", "coingecko"):
        assert forbidden.lower() not in source.lower()


def test_no_score_rating_or_recommendation_output(store):
    _seed_window(store, "yld_a", count=12)
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    payload = risk.to_dict()
    flattened = str(payload).lower()
    for forbidden in ("score", "sharpe", "grade", "rating", "recommend",
                      "safest", "quality_score", "forecast"):
        assert forbidden not in flattened, forbidden


def test_failure_isolation_missing_rewards_keeps_distribution(store):
    _seed_window(store, "yld_a", count=12)
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.reward_context.rewards_apy is None
    assert risk.apy_distribution.q25 is not None
    assert risk.apy_distribution.percentile is not None


# ── Correction A: current-evidence truth ─────────────────────────────────────

def test_current_apy_comes_from_latest_canonical_row_only(store):
    """Latest canonical row has NO APY (TVL only) -> current_apy is None,
    percentile None, peak delta None; the older APY stays an explicitly
    labelled last-observed fact; historical distribution remains available;
    state is not fully AVAILABLE."""
    _seed_window(store, "yld_a", count=12,
                 apy_fn=lambda i: str(Decimal("0.04") + Decimal(i) * Decimal("0.0001")))
    _record(store, "yld_a", NOW, tvl="5000000")   # newest row: no APY
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.apy_context.current_apy is None, (
        "an older APY must never be promoted to current")
    assert risk.apy_distribution.percentile is None
    assert risk.apy_context.current_vs_peak_delta_bps is None
    # the historical distribution remains factual
    assert risk.apy_distribution.q25 is not None
    assert risk.apy_distribution.max == Decimal("0.0411")
    # last-observed semantics are explicit and correctly bound
    assert risk.apy_context.last_observed_apy == Decimal("0.0411")
    assert risk.apy_context.last_observed_apy_at is not None
    # state must not be fully AVAILABLE
    assert risk.state == RiskState.PARTIAL
    assert risk.reason == "LATEST_APY_UNAVAILABLE"


def test_current_tvl_comes_from_latest_canonical_row_only(store):
    """OPTION A: a newer TVL-missing row never promotes an older TVL to
    current; the newest TVL-bearing observation stays explicitly last-
    observed with its timestamp."""
    _seed_window(store, "yld_a", count=12, tvl_fn=lambda i: "5000000")
    _record(store, "yld_a", NOW, apy="0.0450")   # newest row: no TVL
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.tvl_context.current_tvl is None
    assert risk.tvl_context.last_observed_tvl == Decimal("5000000")
    assert risk.tvl_context.last_observed_tvl_at is not None
    # trailing min/max remain historical facts
    assert risk.tvl_context.trailing_max_tvl == Decimal("5000000")


def test_current_freshness_does_not_promote_old_apy(store):
    """Latest row CURRENT but missing APY -> old APY still not promoted."""
    _seed_window(store, "yld_a", count=12, step_hours=6,
                 end=NOW - timedelta(hours=1))
    _record(store, "yld_a", NOW - timedelta(minutes=1), tvl="5000000")
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.apy_context.current_apy is None
    assert risk.apy_distribution.percentile is None
    assert risk.apy_context.current_vs_peak_delta_bps is None


def _seed_with_latest_freshness(store, uid, *, freshness):
    """Seed a window whose LATEST row produces the requested canonical
    freshness state."""
    if freshness == "CURRENT":
        _seed_window(store, uid, count=12, step_hours=6)
        return
    if freshness == "STALE":
        _seed_window(store, uid, count=12, step_hours=6,
                     end=NOW - timedelta(hours=2))
        return
    if freshness == "FUTURE_TIMESTAMP":
        # the canonical window read (until=as_of) structurally excludes
        # future-dated rows, so this state is exercised at the freshness
        # classifier level (see test below) plus the exclusion behaviour.
        _seed_window(store, uid, count=12, step_hours=6,
                     end=NOW - timedelta(hours=2))
        from finco_yield.observation import ImmutableObservationRecord as R
        store.append(R(opportunity_uid=uid, observed_at=NOW + timedelta(hours=2),
                       source_authority="NATIVE_ENRICHED",
                       source_uri="https://test", adapter_version="test",
                       payload={"apy_total": "0.0450"}))
        return
    from finco_yield.observation import ImmutableObservationRecord as R
    if freshness == "UNKNOWN":
        _seed_window(store, uid, count=12, step_hours=6,
                     end=NOW - timedelta(minutes=10))
        store.append(R(opportunity_uid=uid, observed_at=NOW,
                       source_authority="MADE_UP_AUTHORITY",
                       source_uri="https://test", adapter_version="test",
                       payload={"apy_total": "0.0450"}))
        return
    if freshness == "INVALID":
        _seed_window(store, uid, count=12, step_hours=6,
                     end=NOW - timedelta(minutes=10))
        store.append(R(opportunity_uid=uid, observed_at=NOW,
                       source_authority="DIRECT_ONCHAIN",
                       source_uri="https://test", adapter_version="test",
                       payload={"apy_total": "0.0450"}))
        return
    raise ValueError(freshness)


@pytest.mark.parametrize("freshness", ["STALE", "UNKNOWN", "INVALID",
                                       "FUTURE_TIMESTAMP"])
def test_non_current_freshness_states_do_not_collapse(store, freshness):
    """Every non-CURRENT canonical freshness state is preserved verbatim and
    fails the context closed (PARTIAL) — INVALID/FUTURE/UNKNOWN are not
    collapsed into STALE."""
    _seed_with_latest_freshness(store, "yld_a", freshness=freshness)
    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    if freshness == "FUTURE_TIMESTAMP":
        # a future-dated row lies beyond the evaluation window (until=as_of)
        # and is excluded: the context fails closed on the remaining evidence
        assert risk.freshness == "STALE"   # the last IN-WINDOW observation
        assert risk.state == RiskState.STALE
        # classifier-level: the future row itself preserves the canonical
        # FUTURE_TIMESTAMP string verbatim (never collapsed to STALE)
        from finco_yield.alerts_eval import _source_ref_from_row
        from finco_yield.freshness import evaluate_freshness
        future_row = {"observed_at": (NOW + timedelta(hours=2)).isoformat(),
                      "source_authority": "NATIVE_ENRICHED",
                      "source_uri": "https://test", "adapter_version": "test"}
        result = evaluate_freshness(_source_ref_from_row(future_row), now=NOW)
        assert result.state == "FUTURE_TIMESTAMP"
        return
    assert risk.freshness == freshness, "exact canonical string preserved"
    if freshness == "STALE":
        assert risk.state == RiskState.STALE
    else:
        assert risk.state == RiskState.PARTIAL
        assert risk.reason.startswith("LATEST_FRESHNESS_")
    assert risk.state != RiskState.AVAILABLE


def test_zero_and_negative_window_rejected(store):
    _seed_window(store, "yld_a", count=3)
    for bad in (timedelta(0), timedelta(hours=-1)):
        with pytest.raises(RiskError):
            build_historical_risk(store, "yld_a", as_of=NOW, window=bad)


def test_non_30d_window_does_not_label_30d_sigma(store):
    """A 24h window maps to the 24h horizon; an unsupported window gets NO
    sigma — a 30d sigma is never silently presented as same-horizon."""
    _seed_window(store, "yld_a", count=12, step_hours=1)
    risk_24h = build_historical_risk(store, "yld_a", as_of=NOW,
                                     window=timedelta(hours=24))
    assert risk_24h.apy_context.canonical_sigma_horizon == "24h"
    risk_30d = build_historical_risk(store, "yld_a", as_of=NOW,
                                     window=timedelta(days=30))
    assert risk_30d.apy_context.canonical_sigma_horizon == "30d"
    risk_5d = build_historical_risk(store, "yld_a", as_of=NOW,
                                    window=timedelta(days=5))
    assert risk_5d.apy_context.canonical_sigma is None
    assert risk_5d.apy_context.canonical_sigma_horizon is None


def test_malformed_non_dict_latest_payload_does_not_crash(store):
    """A parseable history row with a non-dict payload must not crash the
    reward context — reward unavailable, APY context intact."""
    import hashlib
    from finco_yield.observation import ImmutableObservationRecord
    _seed_window(store, "yld_a", count=12)
    store.append(ImmutableObservationRecord(
        opportunity_uid="yld_a", observed_at=NOW,
        source_authority="NATIVE_ENRICHED", source_uri="https://test",
        adapter_version="test", payload={"apy_total": "0.0450"}))
    lines = store.path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[-1])
    row["payload"] = "0.0450-not-a-dict"
    digest = hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode()).hexdigest()
    row["observation_hash"] = digest
    lines[-1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    store.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    risk = build_historical_risk(store, "yld_a", as_of=NOW)
    assert risk.reward_context.rewards_apy is None
    assert risk.reward_context.base_apy is None
    assert risk.history.observation_count >= 10
