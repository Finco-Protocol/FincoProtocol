"""Yield Intelligence V1 -- deterministic derived read model over canonical history.

Synthetic history fixtures only; no network.  Authority under test:

    source observation -> canonical history (YieldHistoryStore) -> intelligence
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from finco_yield.evidence_v1 import canonical_json
from finco_yield.history import ImmutableObservationRecord, YieldHistoryStore
from finco_yield.intelligence import (
    Coverage,
    DeltaState,
    Direction,
    IntelligenceError,
    IntelligenceStatus,
    build_intelligence,
)

REPO = Path(__file__).resolve().parents[1]
UID = "yld_" + "a" * 32
OTHER = "yld_" + "b" * 32
T = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)      # latest observation anchor
AS_OF = T + timedelta(minutes=5)


def _add(store, uid=UID, at=T, apy="0.04", tvl="1000000", authority="NATIVE_ENRICHED", **extra):
    payload = {"apy_total": apy, "tvl_usd": tvl}
    payload.update(extra)
    return store.append_idempotent(ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=at, source_authority=authority,
        source_uri="https://evidence.test", adapter_version="t", payload=payload))


@pytest.fixture()
def store(tmp_path):
    return YieldHistoryStore(tmp_path / "history.jsonl")


def _h(intel, name):
    horizon = intel.horizon(name)
    assert horizon is not None
    return horizon


# ── 1-2. absence of history ─────────────────────────────────────────────────

class TestAbsence:
    def test_no_history_is_typed_never_numeric(self, store):
        intel = build_intelligence(store, UID, as_of=AS_OF)
        assert intel.status == IntelligenceStatus.INSUFFICIENT_HISTORY
        assert intel.latest is None and intel.freshness is None and intel.horizons == ()
        assert intel.horizon("24h") is None

    def test_missing_history_file_is_not_an_error_and_not_zero(self, tmp_path):
        intel = build_intelligence(YieldHistoryStore(tmp_path / "nope.jsonl"), UID, as_of=AS_OF)
        assert intel.status == IntelligenceStatus.INSUFFICIENT_HISTORY and intel.latest is None

    def test_one_observation_only(self, store):
        _add(store)
        intel = build_intelligence(store, UID, as_of=AS_OF)
        assert intel.status == IntelligenceStatus.AVAILABLE
        assert intel.latest.apy_total == Decimal("0.04") and intel.latest.tvl_usd == Decimal("1000000")
        for name in ("24h", "7d"):
            h = _h(intel, name)
            assert h.coverage == Coverage.INSUFFICIENT_HISTORY and h.baseline is None
            assert h.apy_delta.state == DeltaState.NO_BASELINE and h.apy_delta.delta_bps is None
            assert h.tvl_delta.state == DeltaState.NO_BASELINE and h.tvl_delta.delta_usd is None
            assert h.apy_delta.direction == Direction.UNAVAILABLE
            assert h.observation_count == 1 and h.apy_window.minimum == h.apy_window.maximum == Decimal("0.04")


# ── 3-7. baseline selection ─────────────────────────────────────────────────

class TestBaseline:
    def test_exact_24h_baseline(self, store):
        _add(store, at=T - timedelta(hours=24), apy="0.04")
        _add(store, at=T, apy="0.0425")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        assert h.baseline.observed_at == T - timedelta(hours=24) and h.baseline_offset_seconds == 0
        assert h.coverage == Coverage.AVAILABLE and h.horizon_seconds == 86400

    def test_exact_7d_baseline(self, store):
        _add(store, at=T - timedelta(days=7), apy="0.03")
        _add(store, at=T, apy="0.0425")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "7d")
        assert h.baseline.observed_at == T - timedelta(days=7) and h.baseline_offset_seconds == 0
        assert h.horizon_seconds == 604800
        assert _h(build_intelligence(store, UID, as_of=AS_OF), "24h").baseline is not None  # older still qualifies

    def test_baseline_older_than_cutoff_is_selected_correctly(self, store):
        _add(store, at=T - timedelta(hours=40), apy="0.01")
        _add(store, at=T - timedelta(hours=30), apy="0.04")      # newest at/before the cutoff
        _add(store, at=T - timedelta(hours=20), apy="0.05")      # after cutoff: never baseline
        _add(store, at=T, apy="0.06")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        assert h.baseline.observed_at == T - timedelta(hours=30)
        assert h.baseline.apy_total == Decimal("0.04")
        assert h.baseline_offset_seconds == 6 * 3600
        assert h.apy_delta.delta_fraction == Decimal("0.02")

    def test_observation_after_cutoff_never_becomes_baseline(self, store):
        _add(store, at=T - timedelta(hours=23, minutes=59, seconds=59), apy="0.05")   # 1 s too recent
        _add(store, at=T, apy="0.06")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        assert h.baseline is None and h.coverage == Coverage.INSUFFICIENT_HISTORY
        assert h.apy_delta.state == DeltaState.NO_BASELINE and h.apy_delta.delta_bps is None

    def test_cutoff_boundary_is_microsecond_exact(self, store):
        cutoff = T - timedelta(hours=24)
        _add(store, at=cutoff + timedelta(microseconds=1), apy="0.05")
        _add(store, at=T, apy="0.06")
        assert _h(build_intelligence(store, UID, as_of=AS_OF), "24h").baseline is None
        _add(store, at=cutoff, apy="0.04")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        assert h.baseline.observed_at == cutoff

    def test_no_interpolation_between_observations(self, store):
        _add(store, at=T - timedelta(hours=30), apy="0.04")
        _add(store, at=T - timedelta(hours=18), apy="0.08")
        _add(store, at=T, apy="0.06")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        # the 30h-old point is used verbatim: not the mid-value of its neighbours
        assert h.baseline.apy_total == Decimal("0.04")
        assert h.apy_delta.delta_fraction == Decimal("0.02")
        assert h.apy_delta.delta_bps == Decimal("200")

    def test_other_opportunities_never_leak_in(self, store):
        _add(store, uid=OTHER, at=T - timedelta(hours=30), apy="0.99")
        _add(store, uid=OTHER, at=T + timedelta(minutes=1), apy="0.99")
        _add(store, at=T - timedelta(hours=30), apy="0.04")
        _add(store, at=T, apy="0.05")
        intel = build_intelligence(store, UID, as_of=AS_OF)
        assert intel.latest.apy_total == Decimal("0.05")
        assert _h(intel, "24h").baseline.apy_total == Decimal("0.04")
        assert _h(intel, "24h").observation_count == 1


# ── 8-12. APY deltas ────────────────────────────────────────────────────────

class TestApyDelta:
    def _pair(self, store, base, latest):
        _add(store, at=T - timedelta(hours=25), apy=base)
        _add(store, at=T, apy=latest)
        return _h(build_intelligence(store, UID, as_of=AS_OF), "24h").apy_delta

    def test_positive_is_25_bps(self, store):
        d = self._pair(store, "0.04", "0.0425")
        assert d.state == DeltaState.AVAILABLE
        assert d.delta_fraction == Decimal("0.0025") and d.delta_bps == Decimal("25")
        assert d.direction == Direction.UP

    def test_negative(self, store):
        d = self._pair(store, "0.0425", "0.04")
        assert d.delta_bps == Decimal("-25") and d.direction == Direction.DOWN

    def test_unchanged_is_a_real_zero(self, store):
        d = self._pair(store, "0.04", "0.04")
        assert d.state == DeltaState.AVAILABLE and d.delta_bps == Decimal("0")
        assert d.direction == Direction.UNCHANGED

    def test_factual_zero_apy_is_valid_data(self, store):
        d = self._pair(store, "0", "0.01")
        assert d.state == DeltaState.AVAILABLE and d.delta_bps == Decimal("100")
        s2 = YieldHistoryStore(store.path.with_name("h2.jsonl"))
        _add(s2, at=T - timedelta(hours=25), apy="0.02")
        _add(s2, at=T, apy="0")                                         # latest APY is a factual 0
        h = _h(build_intelligence(s2, UID, as_of=AS_OF), "24h")
        assert h.apy_delta.delta_bps == Decimal("-200") and h.apy_window.minimum == Decimal("0")

    def test_missing_latest_apy_is_unavailable_not_zero(self, store):
        d = self._pair(store, "0.04", None)
        assert d.state == DeltaState.LATEST_VALUE_MISSING
        assert d.delta_bps is None and d.delta_fraction is None and d.direction == Direction.UNAVAILABLE

    def test_missing_baseline_apy_is_unavailable_not_zero(self, store):
        d = self._pair(store, None, "0.04")
        assert d.state == DeltaState.BASELINE_VALUE_MISSING and d.delta_bps is None

    def test_bps_math_uses_decimal_not_float(self, store):
        d = self._pair(store, "0.0411", "0.0432")
        assert d.delta_bps == Decimal("21") and isinstance(d.delta_bps, Decimal)

    @pytest.mark.parametrize("bad", ["nan", "inf", "-Infinity", "abc", ""])
    def test_non_numeric_values_are_treated_as_missing(self, store, bad):
        d = self._pair(store, "0.04", bad)
        assert d.state == DeltaState.LATEST_VALUE_MISSING and d.delta_bps is None


# ── 13-16. TVL deltas ───────────────────────────────────────────────────────

class TestTvlDelta:
    def _pair(self, store, base, latest):
        _add(store, at=T - timedelta(hours=25), tvl=base)
        _add(store, at=T, tvl=latest)
        return _h(build_intelligence(store, UID, as_of=AS_OF), "24h").tvl_delta

    def test_positive(self, store):
        d = self._pair(store, "1000000", "1050000")
        assert d.delta_usd == Decimal("50000") and d.direction == Direction.UP
        assert d.fraction_state == DeltaState.AVAILABLE and d.delta_fraction == Decimal("0.05")

    def test_negative(self, store):
        d = self._pair(store, "1000000", "900000")
        assert d.delta_usd == Decimal("-100000") and d.direction == Direction.DOWN
        assert d.delta_fraction == Decimal("-0.1")

    def test_unchanged(self, store):
        d = self._pair(store, "1000000", "1000000")
        assert d.delta_usd == Decimal("0") and d.direction == Direction.UNCHANGED and d.delta_fraction == Decimal("0")

    def test_factual_zero_baseline_has_absolute_delta_but_no_percentage(self, store):
        d = self._pair(store, "0", "500000")
        assert d.state == DeltaState.AVAILABLE and d.delta_usd == Decimal("500000")
        assert d.fraction_state == DeltaState.UNDEFINED_ZERO_BASELINE and d.delta_fraction is None

    def test_missing_tvl_is_unavailable_not_zero(self, store):
        d = self._pair(store, "1000000", None)
        assert d.state == DeltaState.LATEST_VALUE_MISSING and d.delta_usd is None and d.delta_fraction is None
        s2 = YieldHistoryStore(store.path.with_name("h2.jsonl"))
        _add(s2, at=T - timedelta(hours=25), tvl=None)
        _add(s2, at=T, tvl="1000000")
        d2 = _h(build_intelligence(s2, UID, as_of=AS_OF), "24h").tvl_delta
        assert d2.state == DeltaState.BASELINE_VALUE_MISSING and d2.delta_usd is None

    def test_tvl_math_stays_decimal(self, store):
        d = self._pair(store, "3", "4")
        assert d.delta_fraction == Decimal(4) / Decimal(3) - 1 and isinstance(d.delta_fraction, Decimal)


# ── 17-20. windows and counts ───────────────────────────────────────────────

class TestWindows:
    def _series(self, store):
        _add(store, at=T - timedelta(days=8), apy="0.02", tvl="100")        # outside 7d, baseline for it
        _add(store, at=T - timedelta(days=3), apy="0.03", tvl="900")        # in 7d only
        _add(store, at=T - timedelta(hours=20), apy="0.05", tvl="1200")
        _add(store, at=T - timedelta(hours=10), apy="0.04", tvl="1100")
        _add(store, at=T, apy="0.045", tvl="1150")

    def test_apy_window_min_max_range(self, store):
        self._series(store)
        intel = build_intelligence(store, UID, as_of=AS_OF)
        w24, w7 = _h(intel, "24h").apy_window, _h(intel, "7d").apy_window
        assert (w24.minimum, w24.maximum, w24.range) == (Decimal("0.04"), Decimal("0.05"), Decimal("0.01"))
        assert (w7.minimum, w7.maximum, w7.range) == (Decimal("0.03"), Decimal("0.05"), Decimal("0.02"))

    def test_tvl_window_min_max_range(self, store):
        self._series(store)
        intel = build_intelligence(store, UID, as_of=AS_OF)
        w24, w7 = _h(intel, "24h").tvl_window, _h(intel, "7d").tvl_window
        assert (w24.minimum, w24.maximum, w24.range) == (Decimal("1100"), Decimal("1200"), Decimal("100"))
        assert (w7.minimum, w7.maximum, w7.range) == (Decimal("900"), Decimal("1200"), Decimal("300"))

    def test_observation_counts_are_exact_and_deterministic(self, store):
        self._series(store)
        a = build_intelligence(store, UID, as_of=AS_OF)
        b = build_intelligence(store, UID, as_of=AS_OF)
        assert a == b
        assert _h(a, "24h").observation_count == 3          # T-20h, T-10h, T   (cutoff T-24h has none)
        assert _h(a, "7d").observation_count == 4           # + T-3d

    def test_mixed_missing_and_present_preserves_missingness(self, store):
        _add(store, at=T - timedelta(hours=26), apy="0.04", tvl="1000")
        _add(store, at=T - timedelta(hours=12), apy=None, tvl="1100")
        _add(store, at=T - timedelta(hours=6), apy="0.05", tvl=None)
        _add(store, at=T, apy="0.06", tvl="1200")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        assert h.observation_count == 3
        assert h.apy_window.available_count == 2 and (h.apy_window.minimum, h.apy_window.maximum) == (Decimal("0.05"), Decimal("0.06"))
        assert h.tvl_window.available_count == 2 and (h.tvl_window.minimum, h.tvl_window.maximum) == (Decimal("1100"), Decimal("1200"))
        assert h.coverage == Coverage.AVAILABLE

    def test_no_numeric_values_gives_none_not_zero(self, store):
        _add(store, at=T - timedelta(hours=30), apy=None, tvl=None)
        _add(store, at=T, apy=None, tvl="1000")
        h = _h(build_intelligence(store, UID, as_of=AS_OF), "24h")
        assert h.apy_window.available_count == 0
        assert (h.apy_window.minimum, h.apy_window.maximum, h.apy_window.range) == (None, None, None)
        assert h.coverage == Coverage.NO_NUMERIC_APY

    def test_coverage_states(self, store):
        _add(store, at=T - timedelta(hours=30), apy="0.04", tvl=None)
        _add(store, at=T, apy="0.05", tvl=None)
        assert _h(build_intelligence(store, UID, as_of=AS_OF), "24h").coverage == Coverage.NO_NUMERIC_TVL
        assert _h(build_intelligence(store, UID, as_of=AS_OF), "7d").coverage == Coverage.INSUFFICIENT_HISTORY


# ── 21-24. freshness and the shared time anchor ─────────────────────────────

class TestFreshnessAndTime:
    def test_current_freshness_uses_canonical_evaluator(self, store):
        _add(store)
        intel = build_intelligence(store, UID, as_of=T + timedelta(minutes=10))
        assert intel.freshness.state == "CURRENT" and intel.freshness.age_seconds == 600

    def test_stale_latest_observation_is_stale(self, store):
        _add(store)
        intel = build_intelligence(store, UID, as_of=T + timedelta(hours=2))
        assert intel.freshness.state == "STALE" and intel.status == IntelligenceStatus.AVAILABLE
        assert intel.latest.apy_total == Decimal("0.04")                 # still shown, labelled STALE

    def test_source_observed_is_not_assumed_current(self, store):
        _add(store, at=T - timedelta(days=3))
        assert build_intelligence(store, UID, as_of=T).freshness.state == "STALE"

    def test_unknown_source_authority_is_not_labelled_current(self, store):
        _add(store, authority="SOMETHING_ELSE")
        assert build_intelligence(store, UID, as_of=AS_OF).freshness.state == "UNKNOWN"

    def test_future_timestamp_is_surfaced_by_canonical_freshness(self, store):
        _add(store, at=T + timedelta(hours=1))
        assert build_intelligence(store, UID, as_of=T).freshness.state == "FUTURE_TIMESTAMP"

    def test_one_shared_as_of_per_evaluation(self, store):
        _add(store)
        a = build_intelligence(store, UID, as_of=T + timedelta(minutes=1))
        b = build_intelligence(store, UID, as_of=T + timedelta(hours=3))
        assert a.as_of == T + timedelta(minutes=1) and b.as_of == T + timedelta(hours=3)
        assert (a.freshness.state, b.freshness.state) == ("CURRENT", "STALE")
        # metrics are anchored on the latest observation, so as_of only moves freshness
        assert a.latest == b.latest and a.horizons == b.horizons

    def test_naive_or_invalid_as_of_fails_closed(self, store):
        _add(store)
        for bad in (datetime(2026, 10, 10, 12, 0), "2026-10-10T12:00:00Z", None, 0):
            with pytest.raises(IntelligenceError):
                build_intelligence(store, UID, as_of=bad)

    def test_as_of_is_normalised_to_utc(self, store):
        _add(store)
        plus2 = timezone(timedelta(hours=2))
        intel = build_intelligence(store, UID, as_of=(T + timedelta(minutes=5)).astimezone(plus2))
        assert intel.as_of == T + timedelta(minutes=5) and intel.as_of.utcoffset() == timedelta(0)
        assert intel.freshness.age_seconds == 300

    def test_clock_is_never_read_inside_the_module(self):
        src = (REPO / "finco_yield" / "intelligence.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today"}, "no clock reads allowed"
        assert "time.time" not in src

    def test_empty_uid_and_wrong_store_fail_closed(self, store):
        with pytest.raises(IntelligenceError):
            build_intelligence(store, " ", as_of=AS_OF)
        with pytest.raises(IntelligenceError):
            build_intelligence(object(), UID, as_of=AS_OF)


# ── canonical-authority structure ───────────────────────────────────────────

class TestAuthorityBoundaries:
    def test_history_is_read_exactly_once_per_evaluation(self, store, monkeypatch):
        for hrs, apy in ((30, "0.04"), (10, "0.05"), (0, "0.06")):
            _add(store, at=T - timedelta(hours=hrs), apy=apy)
        calls = []
        real = YieldHistoryStore.read_all

        def counting(self):
            calls.append(1)
            return real(self)
        monkeypatch.setattr(YieldHistoryStore, "read_all", counting)
        build_intelligence(store, UID, as_of=AS_OF)
        assert len(calls) == 1

    def test_uses_only_canonical_read_interface(self):
        tree = ast.parse((REPO / "finco_yield" / "intelligence.py").read_text())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert {"latest", "prior", "window"} <= attrs
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "open" not in names and "json" not in names          # no manual JSONL parsing
        assert not (attrs & {"append", "append_idempotent", "for_opportunity", "write_text", "read_text"})

    def test_module_has_no_execution_or_collector_imports(self):
        tree = ast.parse((REPO / "finco_yield" / "intelligence.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        assert not {m for m in imported if any(x in m for x in ("execution", "collect_live", "snapshot", "onchain", "providers", "live_sources"))}

    def test_history_files_and_rows_are_never_mutated(self, store):
        _add(store, at=T - timedelta(hours=30), apy="0.04")
        _add(store, at=T, apy="0.05")
        before = store.path.read_bytes()
        rows_before = json.dumps(store.read_all(), sort_keys=True)
        for _ in range(3):
            build_intelligence(store, UID, as_of=AS_OF)
        assert store.path.read_bytes() == before
        assert json.dumps(store.read_all(), sort_keys=True) == rows_before

    def test_no_second_store_or_file_is_created(self, store, tmp_path):
        _add(store)
        build_intelligence(store, UID, as_of=AS_OF)
        assert sorted(p.name for p in tmp_path.iterdir() if not p.name.endswith(".lock")) == ["history.jsonl"]

    def test_corrupt_history_propagates_instead_of_becoming_zero(self, store):
        _add(store)
        with store.path.open("ab") as fh:
            fh.write(b'{"torn":')
        with pytest.raises(ValueError):
            build_intelligence(store, UID, as_of=AS_OF)


# ── 28. deterministic serialisation ─────────────────────────────────────────

class TestSerialisation:
    def _body(self, store):
        _add(store, at=T - timedelta(hours=30), apy="0.04", tvl="1000000")
        _add(store, at=T, apy="0.0425", tvl="1050000")
        return {"schema": "YIELD_INTELLIGENCE_V1", "uid": UID, "history_status": "AVAILABLE",
                "intelligence": build_intelligence(store, UID, as_of=AS_OF)}

    def test_canonical_json_is_deterministic_and_decimal_exact(self, store):
        body = self._body(store)
        a, b = canonical_json(body), canonical_json(body)
        assert a == b
        doc = json.loads(a)
        h24 = doc["intelligence"]["horizons"][0]
        assert h24["horizon"] == "24h" and h24["apy_delta"]["delta_bps"] == "25"
        assert h24["apy_delta"]["delta_fraction"] == "0.0025" and h24["tvl_delta"]["delta_usd"] == "50000"
        assert doc["intelligence"]["as_of"] == "2026-10-10T12:05:00.000000Z"
        assert doc["intelligence"]["freshness"]["state"] == "CURRENT"
        assert "e+" not in a.lower() and "nan" not in a.lower()

    def test_unavailable_values_serialise_as_null_never_zero(self, store):
        _add(store, at=T, apy=None, tvl=None)
        # an all-missing latest still serialises with explicit nulls
        doc = json.loads(canonical_json(build_intelligence(store, UID, as_of=AS_OF)))
        assert doc["latest"]["apy_total"] is None and doc["latest"]["tvl_usd"] is None
        h = doc["horizons"][0]
        assert h["apy_delta"]["delta_bps"] is None and h["apy_window"]["minimum"] is None
        assert h["coverage"] == "INSUFFICIENT_HISTORY"

    def test_no_recommendation_vocabulary_in_the_contract(self, store):
        text = canonical_json(self._body(store)).lower()
        for word in ("bullish", "bearish", "attractive", "recommend", "buy", "sell", "best", "safe"):
            assert word not in text


# ── 25-30. product surface ──────────────────────────────────────────────────

@pytest.fixture()
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "web.db"))
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_SNAPSHOT_PATH", raising=False)
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    hist = tmp_path / "web-history.jsonl"
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(hist))
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "web.db"))
    _db.init_db()
    from starlette.testclient import TestClient
    import main_web
    with TestClient(main_web.app, base_url="https://yield-intel.local", raise_server_exceptions=True) as client:
        yield client, monkeypatch, YieldHistoryStore(hist)


def _real_uid():
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry().all()[0].uid


def _fix_clock(monkeypatch, moment):
    import finco_yield.web as web_mod

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)
    monkeypatch.setattr(web_mod, "datetime", Fixed)


class TestWebSurface:
    def test_json_for_canonical_uid_is_deterministic(self, web):
        client, mp, hist = web
        uid = _real_uid()
        _add(hist, uid=uid, at=T - timedelta(hours=30), apy="0.04", tvl="1000000")
        _add(hist, uid=uid, at=T, apy="0.0425", tvl="1050000")
        _fix_clock(mp, AS_OF)
        a = client.get(f"/yield/{uid}/intelligence.json")
        b = client.get(f"/yield/{uid}/intelligence.json")
        assert a.status_code == 200 and a.content == b.content
        doc = a.json()
        assert doc["schema"] == "YIELD_INTELLIGENCE_V1" and doc["uid"] == uid and doc["history_status"] == "AVAILABLE"
        i = doc["intelligence"]
        assert i["uid"] == uid and i["as_of"] == "2026-10-10T12:05:00.000000Z"
        assert i["latest"]["observed_at"] == "2026-10-10T12:00:00.000000Z"
        assert i["freshness"]["state"] == "CURRENT"
        h24 = i["horizons"][0]
        assert h24["apy_delta"]["delta_bps"] == "25" and h24["coverage"] == "AVAILABLE"
        assert len(i["horizons"]) == 2

    def test_unknown_uid_is_404_and_tickers_never_resolve(self, web):
        client, _, hist = web
        _add(hist, uid="yld_" + "f" * 32)
        assert client.get("/yield/yld_" + "f" * 32 + "/intelligence.json").status_code == 404
        assert client.get("/yield/USDC/intelligence.json").status_code == 404
        assert client.get("/yield/0x7BfA7C4f149E7415b73bdeDfe609237e29CBF34A/intelligence.json").status_code == 404

    def test_history_not_configured_is_typed_not_zero(self, web):
        client, mp, _ = web
        mp.delenv("FINCO_YIELD_HISTORY_PATH")
        doc = client.get(f"/yield/{_real_uid()}/intelligence.json").json()
        assert doc["history_status"] == "HISTORY_NOT_CONFIGURED" and "intelligence" not in doc

    def test_corrupt_history_is_unavailable_not_zero(self, web):
        client, _, hist = web
        hist.path.write_bytes(b'{"opportunity_uid":"x"')
        doc = client.get(f"/yield/{_real_uid()}/intelligence.json").json()
        assert doc["history_status"] == "HISTORY_UNAVAILABLE" and "intelligence" not in doc

    def test_no_history_for_uid_is_insufficient_history(self, web):
        client, _, _ = web
        doc = client.get(f"/yield/{_real_uid()}/intelligence.json").json()
        assert doc["intelligence"]["status"] == "INSUFFICIENT_HISTORY" and doc["intelligence"]["latest"] is None

    def test_detail_page_renders_deltas_with_em_dash_for_unavailable(self, web):
        client, mp, hist = web
        uid = _real_uid()
        _add(hist, uid=uid, at=T - timedelta(hours=30), apy="0.04", tvl=None)      # TVL missing at baseline
        _add(hist, uid=uid, at=T, apy="0.0425", tvl="1050000")
        _fix_clock(mp, AS_OF)
        page = client.get(f"/yield/{uid}").text
        assert 'data-testid="yield-intelligence"' in page
        assert '+25.0 bps' in page and "UP" in page
        cell = page.split('data-testid="intel-tvl-delta-24h">')[1].split("</td>")[0]
        assert cell.strip() == "—"                                    # missing TVL baseline: em dash, not $0
        assert "7d Δ" in page and 'data-testid="intel-coverage-7d"' in page
        assert page.split('data-testid="intel-coverage-7d">')[1].startswith("INSUFFICIENT_HISTORY")
        section = page.split('data-testid="yield-intelligence"')[1].split("</section>")[0]
        assert "$0" not in section and "0.00%" not in section and "+0.0 bps" not in section

    def test_detail_page_with_no_history_shows_typed_state_not_zeros(self, web):
        client, _, _ = web
        page = client.get(f"/yield/{_real_uid()}").text
        assert 'data-testid="intel-insufficient"' in page
        section = page.split('data-testid="yield-intelligence"')[1].split("</section>")[0]
        assert "$0" not in section and "0.00%" not in section

    def test_detail_page_without_history_path_is_typed(self, web):
        client, mp, _ = web
        mp.delenv("FINCO_YIELD_HISTORY_PATH")
        assert 'data-testid="intel-not-configured"' in client.get(f"/yield/{_real_uid()}").text

    def test_stale_latest_is_labelled_stale_in_ui(self, web):
        client, mp, hist = web
        uid = _real_uid()
        _add(hist, uid=uid, at=T, apy="0.04")
        _fix_clock(mp, T + timedelta(hours=6))
        page = client.get(f"/yield/{uid}").text
        assert page.split('data-testid="intel-freshness">')[1].startswith("STALE")

    def test_entitlement_reuses_the_existing_history_decision(self, web):
        client, mp, hist = web
        uid = _real_uid()
        _add(hist, uid=uid, at=T - timedelta(hours=30), apy="0.04")
        _add(hist, uid=uid, at=T, apy="0.0425")
        import finco_yield.web as web_mod
        from finco_yield.access import YieldAccessDecision, YieldAccessState, YieldResource, resolve_yield_access

        seen = []

        async def deny(request, resource):
            seen.append(resource)
            return YieldAccessDecision(resource=resource, state=YieldAccessState.WALLET_UNVERIFIED,
                                       access_allowed=False, token_entitled=False, gate_active=True,
                                       reason="WALLET_UNVERIFIED")
        mp.setattr(web_mod, "resolve_yield_access", deny)
        resp = client.get(f"/yield/{uid}/intelligence.json")
        assert resp.status_code == 403 and "intelligence" not in resp.text
        page = client.get(f"/yield/{uid}").text
        assert 'data-testid="intel-restricted"' in page and "25.0 bps" not in page
        assert set(seen) == {YieldResource.HISTORY}                    # same resource as history.json
        assert resolve_yield_access is not None

    def test_history_endpoint_is_unchanged(self, web):
        client, _, hist = web
        uid = _real_uid()
        _add(hist, uid=uid)
        doc = client.get(f"/yield/{uid}/history.json").json()
        assert doc["schema"] == "YIELD_HISTORY_V1" and doc["status"] == "AVAILABLE" and len(doc["observations"]) == 1

    def test_requests_never_modify_history(self, web):
        client, mp, hist = web
        uid = _real_uid()
        _add(hist, uid=uid, at=T - timedelta(hours=30), apy="0.04")
        _add(hist, uid=uid, at=T, apy="0.05")
        before = hist.path.read_bytes()
        _fix_clock(mp, AS_OF)
        client.get(f"/yield/{uid}/intelligence.json")
        client.get(f"/yield/{uid}")
        assert hist.path.read_bytes() == before

    def test_execution_remains_off(self, web):
        client, _, hist = web
        from finco_yield.flags import execution_enabled
        uid = _real_uid()
        _add(hist, uid=uid)
        assert execution_enabled() is False
        client.get(f"/yield/{uid}")
        assert execution_enabled() is False
        resp = client.post(f"/yield/{uid}/transaction-plan", json={})
        assert resp.status_code in (400, 401, 403, 404, 405, 409, 422, 503)
        page = client.get(f"/yield/{uid}").text
        assert 'data-testid="yield-intelligence"' in page and "private key" not in page.lower()
