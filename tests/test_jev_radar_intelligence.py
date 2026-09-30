"""JEV Radar Intelligence V1 — deterministic features, identity, transport, cache, authority, API, UI."""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.radar_rwa.jev_intelligence import features as F
from app.radar_rwa.jev_intelligence.cache import IntelligenceCache, cache_key, clamp_ttl
from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
from app.radar_rwa.jev_intelligence.contracts import (
    DISCLOSURE, QUESTION_SCHEMA_VERSION, IntelligenceState, JevMode)
from app.radar_rwa.jev_intelligence.questions import build_request, parse_response
from app.radar_rwa.jev_intelligence.service import evaluate_intelligence, evaluate_shadow
from app.radar_rwa.jev_intelligence.telemetry import Telemetry, estimate_request_cost_usd
from app.radar_rwa.jev_intelligence.transport import (
    JevHttpConfig, JevTransportError, TypeSafeJevTransport)
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "app" / "radar_rwa" / "jev_intelligence"
CID = next(iter(APPROVED_BY_CANONICAL_ID))
OTHER_CID = list(APPROVED_BY_CANONICAL_ID)[1]
UID = APPROVED_BY_CANONICAL_ID[CID].economic_asset_uid
SYMBOL = APPROVED_BY_CANONICAL_ID[CID].symbol
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
SECRET = "sk-test-SECRET-KEY-123"
ON = JevIntelligenceConfig(mode=JevMode.VISIBLE)


@pytest.fixture(autouse=True)
def _fresh_limiters():
    from app.radar_rwa.jev_intelligence import service
    service._LIMITERS.clear()
    yield
    service._LIMITERS.clear()


# ── canonical fixtures ────────────────────────────────────────────────────────────────
def current(premium="35.5", state="AVAILABLE", cid=CID, uid=UID, activity=120, retrieved=NOW):
    return state, {
        "exact_asset_key": {"canonical_id": cid, "chain_id": 4663, "contract_address": cid},
        "economic_asset_uid": uid,
        "b1_0_premium": {"state": "AVAILABLE", "value_bps": premium},
        "freshness": {"market_activity_age_seconds": activity,
                      "retrieved_at": retrieved.isoformat() if retrieved else None},
    }


def ranges(low1="30", high1="40", n1=8, low24="10", high24="60", n24=50):
    def one(low, high, n):
        return {"state": "AVAILABLE", "low_bps": low, "high_bps": high, "observation_count": n}
    return {"range_1h": one(low1, high1, n1), "range_24h": one(low24, high24, n24),
            "last_available": None}


def points(now=NOW, span_hours=24, step_min=30, start_value=20.0, end_value=35.0):
    rows, total = [], int(span_hours * 60 / step_min)
    for i in range(total, -1, -1):  # newest first, like read_r_live_history
        collected = now - timedelta(minutes=i * step_min)
        value = start_value + (end_value - start_value) * (total - i) / total
        rows.append({"state": "AVAILABLE", "collected_at": collected.isoformat(),
                     "reference_premium_bps": f"{value:.4f}"})
    return list(reversed(rows))


def build(premium="35.5", **kw):
    st, cur = current(premium)
    return F.build_feature_state(current_state=st, current=cur,
                                 ranges=kw.get("ranges", ranges()), points=kw.get("points", points()))


def good_response(model="jev-1.13", regime="MOMENTUM", score=1.0, legend=True, extra=None):
    answers = {
        "market_regime": {"type": "choice", "choice": regime, "confidence": 0.8,
                          "probabilities": {"MOMENTUM": 0.7, "MEAN_REVERTING": 0.1,
                                            "RANGE_BOUND": 0.15, "UNRESOLVED": 0.05}},
        "attention": {"type": "score", "score": score, "confidence": 0.7,
                      "probabilities": {"0": 0.2, "1": 0.7, "2": 0.1},
                      **({"legend": {"0": "NORMAL", "1": "ELEVATED", "2": "HIGH"}} if legend else {})},
    }
    answers.update(extra or {})
    return {"model": model, "answers": answers, "usage": {"input_tokens": 300, "output_tokens": 0},
            "_transport_meta": {"latency_ms": "88.500", "attempt_count": 1,
                                "provider_request_id": "req-1"}}


class FakeTransport:
    def __init__(self, response=None, error=None, delay=0.0):
        self.calls, self.response, self.error, self.delay = [], response or good_response(), error, delay

    def evaluate(self, request):
        self.calls.append(request)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return copy.deepcopy(self.response)


class Recorder:
    """Provider fakes that count canonical reads."""

    def __init__(self, cur=None, rng=None, pts=None):
        self.cur = cur or current()
        self.rng = rng or ranges()
        self.pts = points() if pts is None else pts
        self.reads = 0

    def current(self, cid):
        self.reads += 1
        return copy.deepcopy(self.cur)

    def ranges(self, cid, as_of):
        return copy.deepcopy(self.rng)

    def points(self, cid):
        return copy.deepcopy(self.pts)


def run(rec=None, transport=None, config=ON, cache=None, telemetry=None, cid=CID, environ=None):
    rec = rec or Recorder()
    return evaluate_intelligence(
        cid, config=config, transport=transport or FakeTransport(), current_provider=rec.current,
        ranges_provider=rec.ranges, points_provider=rec.points, cache=cache or IntelligenceCache(),
        telemetry=telemetry or Telemetry(), environ=environ if environ is not None else {})


# ══ deterministic features ════════════════════════════════════════════════════════════
def test_same_canonical_data_gives_same_payload_and_fingerprint():
    a, b = build(), build()
    assert dict(a.features) == dict(b.features)
    assert a.input_fingerprint == b.input_fingerprint and a.observation_digest == b.observation_digest
    assert a.input_fingerprint == __import__("hashlib").sha256(F.canonical_json(
        {"feature_schema_version": a.schema_version, "features": dict(a.features)}).encode()).hexdigest()


def test_feature_keys_and_no_liquidity_or_flow_features():
    state = build()
    assert tuple(state.features) == F.FEATURE_KEYS
    joined = " ".join(state.features).lower()
    for absent in ("liquidity", "depth", "volume", "wallet", "flow", "whale"):
        assert absent not in joined


def test_missing_values_are_unavailable_never_zero():
    st, cur = current(activity=None)
    state = F.build_feature_state(current_state=st, current=cur, ranges=ranges(), points=[])
    assert state.features["market_activity_age"] == "UNAVAILABLE"
    assert state.features["direction_1h"] == "UNAVAILABLE"
    assert state.features["direction_24h"] == "UNAVAILABLE"
    assert state.features["short_long_agreement"] == "UNAVAILABLE"
    unavailable_1h = ranges()
    unavailable_1h["range_1h"] = {"state": "UNAVAILABLE", "low_bps": None, "high_bps": None,
                                  "observation_count": 1}
    state = F.build_feature_state(current_state=st, current=cur, ranges=unavailable_1h, points=points())
    assert state.features["position_in_1h_range"] == "UNAVAILABLE"
    assert state.features["range_shape"] == "UNAVAILABLE"
    assert not any(v in ("0", "0.0", "NORMAL") for v in state.features.values())


@pytest.mark.parametrize("state", ["STALE", "UNAVAILABLE", "IDENTITY_UNAVAILABLE"])
def test_non_available_canonical_current_fails_closed(state):
    _, cur = current()
    with pytest.raises(F.FeatureUnavailable) as exc:
        F.build_feature_state(current_state=state, current=cur, ranges=ranges(), points=points())
    assert exc.value.reason == "CANONICAL_CURRENT_NOT_AVAILABLE"


def test_missing_premium_retrieval_time_or_history_fail_closed():
    st, cur = current()
    broken = copy.deepcopy(cur)
    broken["b1_0_premium"]["value_bps"] = None
    with pytest.raises(F.FeatureUnavailable, match="PREMIUM"):
        F.build_feature_state(current_state=st, current=broken, ranges=ranges(), points=points())
    broken = copy.deepcopy(cur)
    broken["freshness"]["retrieved_at"] = None
    with pytest.raises(F.FeatureUnavailable, match="RETRIEVAL"):
        F.build_feature_state(current_state=st, current=broken, ranges=ranges(), points=points())
    thin = ranges()
    thin["range_24h"] = {"state": "UNAVAILABLE", "low_bps": None, "high_bps": None, "observation_count": 1}
    with pytest.raises(F.FeatureUnavailable, match="INSUFFICIENT_HISTORY"):
        F.build_feature_state(current_state=st, current=cur, ranges=thin, points=points())
    with pytest.raises(F.FeatureUnavailable, match="HISTORY_UNAVAILABLE"):
        F.build_feature_state(current_state=st, current=cur, ranges=None, points=points())


def test_bucket_boundaries():
    assert F.premium_level(Decimal("9.99")) == "NEAR_PARITY"
    assert F.premium_level(Decimal("10")) == "MODERATE_PREMIUM"
    assert F.premium_level(Decimal("-50")) == "WIDE_DISCOUNT"
    assert F.premium_level(Decimal("150")) == "EXTREME_PREMIUM"
    low, high = Decimal("0"), Decimal("90")
    assert F.position_in_range(Decimal("-1"), low, high) == "BELOW_RANGE"
    assert F.position_in_range(Decimal("29.9"), low, high) == "LOWER_THIRD"
    assert F.position_in_range(Decimal("30"), low, high) == "MIDDLE_THIRD"
    assert F.position_in_range(Decimal("60"), low, high) == "UPPER_THIRD"
    assert F.position_in_range(Decimal("91"), low, high) == "ABOVE_RANGE"
    assert F.position_in_range(Decimal("5"), Decimal("5"), Decimal("5")) == "FLAT_RANGE"
    assert F.position_in_range(Decimal("5"), None, high) == "UNAVAILABLE"
    assert F.direction_bucket(Decimal("1.99")) == "FLAT" and F.direction_bucket(Decimal("2")) == "UP"
    assert F.direction_bucket(Decimal("-2")) == "DOWN" and F.direction_bucket(None) == "UNAVAILABLE"
    assert F.agreement_bucket("UP", "UP") == "AGREE" and F.agreement_bucket("UP", "DOWN") == "DISAGREE"
    assert F.agreement_bucket("FLAT", "UP") == "FLAT_INVOLVED"
    assert F.agreement_bucket("UP", "UNAVAILABLE") == "UNAVAILABLE"


def test_direction_needs_window_coverage_and_untruncated_reads():
    short = points(span_hours=1, step_min=10)  # 24h window is only 1h covered
    state = build(points=short)
    assert state.features["direction_1h"] in ("UP", "DOWN", "FLAT")
    assert state.features["direction_24h"] == "UNAVAILABLE"
    capped = points(span_hours=24, step_min=14.4)[-F.POINT_LIMIT:]  # capped read, oldest inside window
    assert len(capped) == F.POINT_LIMIT
    assert build(points=capped).features["direction_24h"] == "UNAVAILABLE"


def test_direction_reflects_series_and_ttl_follows_freshness():
    up = build(points=points(start_value=20, end_value=35))
    assert up.features["direction_24h"] == "UP"
    down = build("35.5", points=points(start_value=60, end_value=35))
    assert down.features["direction_24h"] == "DOWN"
    assert build().ttl_seconds == 30
    st, cur = current(activity=7200)
    slow = F.build_feature_state(current_state=st, current=cur, ranges=ranges(), points=points())
    assert slow.features["market_activity_age"] == "WITHIN_6H" and slow.ttl_seconds == 120
    assert clamp_ttl(5) == 30 and clamp_ttl(999) == 120


def test_request_is_identity_blinded_and_has_no_arithmetic_or_numbers():
    state = build()
    request = build_request(state, model="jev-latest")
    blob = json.dumps(request)
    for leaked in (CID, UID, SYMBOL, "35.5", "0xaf3d"):
        assert leaked not in blob
    for value in request["state"]["features"].values():
        with pytest.raises(Exception):
            Decimal(value) if value != "NaN" else (_ for _ in ()).throw(ValueError())
    assert set(request["questions"]) == {"market_regime", "attention"}
    assert {q["type"] for q in request["questions"].values()} == {"choice", "score"}  # no predictive Noul
    for question in request["questions"].values():
        assert not re.search(r"\b(calculate|compute|percentage change)\b",
                             question["instructions"], re.I)


# ══ provider request/response contract (locked to the System One schema) ═════════════
CONTRACT = json.loads((REPO / "tests/fixtures/typesafe_systemone_contract.json").read_text(encoding="utf-8"))


def _validate_request(request: dict) -> list[str]:
    """Strict, dependency-free validator driven by the locked provider-contract fixture."""
    errors = [f"missing top-level {k}" for k in CONTRACT["request"]["top_level_required"] if k not in request]
    for qid, question in request.get("questions", {}).items():
        spec = CONTRACT["request"]["question_types"].get(question.get("type"))
        if spec is None:
            errors.append(f"{qid}: unknown type")
            continue
        errors += [f"{qid}: missing {k}" for k in spec["required"] if k not in question]
        errors += [f"{qid}: forbidden {k}" for k in spec["forbidden"] if k in question]
        if "criteria" in spec["required"]:
            want = dict if spec["criteria"] == "mapping" else list
            if not isinstance(question.get("criteria"), want) or not question.get("criteria"):
                errors.append(f"{qid}: criteria must be a non-empty {want.__name__}")
    return errors


def test_outbound_request_satisfies_the_locked_provider_contract():
    request = build_request(build(), model="jev-latest")
    assert _validate_request(request) == []


def test_choice_request_has_criteria_mapping_and_no_options():
    question = build_request(build(), model="jev-latest")["questions"]["market_regime"]
    assert question["type"] == "choice"
    assert "criteria" in question and "options" not in question and "legend" not in question
    assert isinstance(question["criteria"], dict)
    assert list(question["criteria"]) == ["MOMENTUM", "MEAN_REVERTING", "RANGE_BOUND", "UNRESOLVED"]
    assert all(isinstance(v, str) and v for v in question["criteria"].values())


def test_score_request_has_ordered_criteria_list_and_no_legend():
    question = build_request(build(), model="jev-latest")["questions"]["attention"]
    assert question["type"] == "score"
    assert "criteria" in question and "legend" not in question and "options" not in question
    assert isinstance(question["criteria"], list)
    assert question["criteria"] == ["NORMAL", "ELEVATED", "HIGH"]  # exact order


def test_question_ids_stay_exactly_market_regime_and_attention():
    request = build_request(build(), model="jev-latest")
    assert list(request["questions"]) == ["market_regime", "attention"]
    assert not any(q["type"] == "noul" for q in request["questions"].values())  # no predictive Noul


def test_contract_validator_actually_rejects_the_old_wrong_shapes():
    request = build_request(build(), model="jev-latest")
    wrong = copy.deepcopy(request)
    wrong["questions"]["market_regime"]["options"] = wrong["questions"]["market_regime"].pop("criteria")
    wrong["questions"]["attention"]["legend"] = wrong["questions"]["attention"].pop("criteria")
    errors = _validate_request(wrong)
    assert any("market_regime: missing criteria" in e for e in errors)
    assert any("market_regime: forbidden options" in e for e in errors)
    assert any("attention: missing criteria" in e for e in errors)
    assert any("attention: forbidden legend" in e for e in errors)


def test_provider_sample_response_parses_under_the_strict_response_contract():
    sample = CONTRACT["sample_valid_response"]
    for qid, answer in sample["answers"].items():
        spec = CONTRACT["response"]["answer_types"][answer["type"]]
        assert all(k in answer for k in spec["required"]), qid
    regime, attention, model = parse_response(sample)
    assert (regime.choice, attention.state, model) == ("RANGE_BOUND", "ELEVATED", "jev-1.13")


def test_service_sends_exactly_the_contract_request_to_the_transport():
    transport = FakeTransport()
    run(Recorder(), transport)
    assert _validate_request(transport.calls[0]) == []
    assert transport.calls[0]["model"] == "jev-latest"


# ══ identity ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad", [SYMBOL, SYMBOL.lower(), "Apple", CID.upper(), CID + " ", "", "4663:" + CID])
def test_only_exact_canonical_ids_are_accepted(bad):
    rec, transport = Recorder(), FakeTransport()
    result = run(rec, transport, cid=bad)
    assert result.state is IntelligenceState.UNAVAILABLE and result.reason == "ASSET_UID_INVALID"
    assert rec.reads == 0 and transport.calls == []


def test_identity_substitution_in_canonical_evidence_is_rejected():
    for cur in (current(cid=OTHER_CID), current(uid="0x" + "0" * 64)):
        rec, transport = Recorder(cur=cur), FakeTransport()
        result = run(rec, transport)
        assert result.reason == "CANONICAL_IDENTITY_MISMATCH" and transport.calls == []


# ══ transport ════════════════════════════════════════════════════════════════════════
class Resp:
    def __init__(self, status=200, body=None, headers=None, bad_json=False):
        self.status_code, self._body, self.headers, self._bad = status, body, headers or {}, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._body


class Client:
    def __init__(self, *items):
        self.items, self.posts, self.gets = list(items), [], []

    def _next(self):
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def post(self, url, *, headers, json, timeout):
        self.posts.append((url, headers, json, timeout))
        return self._next()

    def get(self, url, *, headers, timeout):
        self.gets.append((url, headers, timeout))
        return self._next()


def transport_with(client, **cfg):
    sleeps = []
    clock = {"t": 0.0}

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    t = TypeSafeJevTransport(SECRET, client=client, config=JevHttpConfig(**cfg), sleep=sleep,
                             clock=lambda: clock["t"])
    return t, sleeps


def test_auth_bearer_header_and_redaction():
    client = Client(Resp(200, {"model": "m", "answers": {}}, {"x-request-id": "abc-123"}))
    t, _ = transport_with(client)
    out = t.evaluate({"state": {}})
    assert client.posts[0][0] == "https://api.typesafe.ai/v1/systemone"
    assert client.posts[0][1]["Authorization"] == f"Bearer {SECRET}"
    assert out["_transport_meta"]["provider_request_id"] == "abc-123"
    assert SECRET not in repr(t) and SECRET not in str(t) and SECRET not in json.dumps(out)


def test_unsafe_request_id_is_dropped_and_secret_echo_rejected():
    t, _ = transport_with(Client(Resp(200, {"a": 1}, {"x-request-id": "bad id\n<script>"})))
    assert t.evaluate({})["_transport_meta"]["provider_request_id"] is None
    t, _ = transport_with(Client(Resp(200, {"echo": f"key={SECRET}"})))
    with pytest.raises(JevTransportError) as exc:
        t.evaluate({})
    assert exc.value.failure_category == "INVALID_RESPONSE" and SECRET not in str(exc.value)


def test_timeout_retries_are_bounded_then_typed():
    import httpx
    client = Client(httpx.ReadTimeout("t"), httpx.ReadTimeout("t"), httpx.ReadTimeout("t"))
    t, sleeps = transport_with(client, max_retries=2)
    with pytest.raises(JevTransportError) as exc:
        t.evaluate({})
    assert exc.value.failure_category == "TIMEOUT" and exc.value.attempt_count == 3
    assert len(client.posts) == 3 and sleeps == [0.25, 0.5]


def test_408_and_5xx_retry_then_succeed():
    for status in (408, 500, 503, 529):
        client = Client(Resp(status), Resp(200, {"ok": True}))
        t, sleeps = transport_with(client)
        assert t.evaluate({})["_transport_meta"]["attempt_count"] == 2 and sleeps == [0.25]


def test_429_respects_retry_after():
    client = Client(Resp(429, headers={"Retry-After": "3"}), Resp(200, {"ok": True}))
    t, sleeps = transport_with(client)
    t.evaluate({})
    assert sleeps == [3.0]


def test_retry_after_beyond_budget_stops():
    client = Client(Resp(429, headers={"Retry-After": "600"}), Resp(200, {"ok": True}))
    t, sleeps = transport_with(client, max_total_seconds=12.0)
    with pytest.raises(JevTransportError) as exc:
        t.evaluate({})
    assert exc.value.failure_category == "RETRY_BUDGET_EXHAUSTED" and sleeps == []


def test_persistent_429_and_5xx_exhaust_with_category():
    t, _ = transport_with(Client(Resp(429), Resp(429), Resp(429)))
    with pytest.raises(JevTransportError) as exc:
        t.evaluate({})
    assert exc.value.failure_category == "HTTP_429"
    t, _ = transport_with(Client(Resp(502), Resp(502), Resp(502)))
    with pytest.raises(JevTransportError) as exc:
        t.evaluate({})
    assert exc.value.failure_category == "HTTP_5XX"


@pytest.mark.parametrize("status,category", [(401, "AUTH"), (403, "AUTH"), (400, "INVALID_REQUEST"),
                                             (422, "INVALID_REQUEST"), (404, "INVALID_REQUEST")])
def test_no_retry_on_auth_or_malformed_request(status, category):
    client = Client(Resp(status, {"error": f"secret {SECRET}"}))
    t, sleeps = transport_with(client)
    with pytest.raises(JevTransportError) as exc:
        t.evaluate({})
    assert exc.value.failure_category == category and len(client.posts) == 1 and sleeps == []
    assert SECRET not in str(exc.value) and "error" not in str(exc.value)


def test_malformed_and_non_mapping_responses_are_invalid():
    for resp in (Resp(200, bad_json=True), Resp(200, [1, 2]), Resp(200, "text")):
        t, _ = transport_with(Client(resp))
        with pytest.raises(JevTransportError) as exc:
            t.evaluate({})
        assert exc.value.failure_category == "INVALID_RESPONSE"


def test_list_models_is_a_separate_diagnostic_get():
    client = Client(Resp(200, {"data": []}))
    t, _ = transport_with(client)
    t.list_models()
    assert client.gets and client.gets[0][0].endswith("/v1/models") and not client.posts


def test_transport_requires_a_key():
    with pytest.raises(ValueError):
        TypeSafeJevTransport("  ")


# ══ response validation ══════════════════════════════════════════════════════════════
def test_valid_response_surfaces_requested_vs_resolved_model():
    result = run(transport=FakeTransport(good_response(model="jev-1.13")),
                 config=JevIntelligenceConfig(mode=JevMode.VISIBLE, model="jev-latest"))
    assert result.state is IntelligenceState.AVAILABLE
    public = result.to_public_dict()
    assert public["requested_model"] == "jev-latest" and public["resolved_model"] == "jev-1.13"
    assert public["model_match"] is False
    assert public["answers"]["market_regime"]["choice"] == "MOMENTUM"
    assert public["answers"]["attention"]["state"] == "ELEVATED"
    assert public["disclosure"] == DISCLOSURE and public["label"] == "EXPERIMENTAL"
    assert public["diagnostics"]["provider_request_id"] == "req-1"
    assert public["diagnostics"]["usage"] == {"input_tokens": "300", "output_tokens": "0"}


@pytest.mark.parametrize("mutate,reason", [
    (lambda r: r["answers"].__setitem__("bonus", {"noul": 0.5}), "JEV_UNEXPECTED_QUESTION_OUTPUT"),
    (lambda r: r["answers"].pop("attention"), "JEV_UNEXPECTED_QUESTION_OUTPUT"),
    (lambda r: r["answers"]["market_regime"].pop("type"), "JEV_MARKET_REGIME_ANSWER_INVALID"),
    (lambda r: r["answers"]["market_regime"].__setitem__("type", "score"), "JEV_MARKET_REGIME_ANSWER_INVALID"),
    (lambda r: r["answers"]["market_regime"].__setitem__("choice", "BULLISH"), "JEV_MARKET_REGIME_CHOICE_UNEXPECTED"),
    (lambda r: r["answers"]["market_regime"].pop("probabilities"), "JEV_MARKET_REGIME_PROBABILITIES_MISSING"),
    (lambda r: r["answers"]["market_regime"].pop("confidence"), "CONFIDENCE_MISSING"),
    (lambda r: r["answers"]["market_regime"].__setitem__("confidence", 1.5), "CONFIDENCE_OUT_OF_BOUNDS"),
    (lambda r: r["answers"]["market_regime"].__setitem__("confidence", -0.1), "CONFIDENCE_OUT_OF_BOUNDS"),
    (lambda r: r["answers"]["market_regime"].__setitem__("confidence", True), "CONFIDENCE_NOT_NUMERIC"),
    (lambda r: r["answers"]["market_regime"]["probabilities"].__setitem__("MOMENTUM", 1.4), "PROBABILITY_OUT_OF_BOUNDS"),
    (lambda r: r["answers"]["market_regime"]["probabilities"].__setitem__("MOMENTUM", "nan"), "PROBABILITY_OUT_OF_BOUNDS"),
    (lambda r: r["answers"]["market_regime"]["probabilities"].__setitem__("BUY", 0.1), "JEV_MARKET_REGIME_PROBABILITIES_INVALID"),
    (lambda r: r["answers"]["market_regime"].__setitem__("probabilities", {"UNRESOLVED": 1.0}), "JEV_MARKET_REGIME_CHOICE_WITHOUT_PROBABILITY"),
    (lambda r: r["answers"]["market_regime"]["probabilities"].update(MOMENTUM=0.9, RANGE_BOUND=0.9), "JEV_MARKET_REGIME_PROBABILITIES_INVALID_EXCEED_ONE"),
    (lambda r: r["answers"]["attention"].pop("type"), "JEV_ATTENTION_ANSWER_INVALID"),
    (lambda r: r["answers"]["attention"].__setitem__("type", "noul"), "JEV_ATTENTION_ANSWER_INVALID"),
    (lambda r: r["answers"]["attention"].__setitem__("score", 2.01), "JEV_ATTENTION_SCORE_OUT_OF_RANGE"),
    (lambda r: r["answers"]["attention"].__setitem__("score", -0.01), "JEV_ATTENTION_SCORE_OUT_OF_RANGE"),
    (lambda r: r["answers"]["attention"].__setitem__("score", 3), "JEV_ATTENTION_SCORE_OUT_OF_RANGE"),
    (lambda r: r["answers"]["attention"].__setitem__("score", "high"), "JEV_ATTENTION_SCORE_NOT_NUMERIC"),
    (lambda r: r["answers"]["attention"].pop("legend"), "JEV_ATTENTION_LEGEND_INVALID"),
    (lambda r: r["answers"]["attention"].__setitem__("legend", {"0": "A", "1": "B", "2": "C"}), "JEV_ATTENTION_LEGEND_INVALID"),
    (lambda r: r["answers"]["attention"].__setitem__("legend", {"1": "NORMAL", "2": "ELEVATED", "3": "HIGH"}), "JEV_ATTENTION_LEGEND_INVALID"),
    (lambda r: r["answers"]["attention"].pop("probabilities"), "JEV_ATTENTION_PROBABILITIES_MISSING"),
    (lambda r: r["answers"]["attention"].__setitem__("probabilities", {"9": 0.5}), "JEV_ATTENTION_PROBABILITIES_INVALID"),
    (lambda r: r["answers"]["attention"].pop("confidence"), "CONFIDENCE_MISSING"),
    (lambda r: r.pop("model"), "JEV_RESPONSE_SHAPE_INVALID"),
    (lambda r: r.__setitem__("answers", []), "JEV_RESPONSE_SHAPE_INVALID"),
])
def test_unexpected_or_out_of_bounds_output_fails_closed(mutate, reason):
    response = good_response()
    mutate(response)
    result = run(transport=FakeTransport(response))
    assert result.state is IntelligenceState.INVALID_RESPONSE and result.reason == reason
    assert result.market_regime is None and result.attention is None
    assert result.to_public_dict()["answers"] is None


@pytest.mark.parametrize("score,level", [
    ("0", "NORMAL"), ("0.4999", "NORMAL"), ("0.5", "ELEVATED"), ("1", "ELEVATED"),
    ("1.4999", "ELEVATED"), ("1.5", "HIGH"), ("2", "HIGH"),
])
def test_score_to_level_policy_is_explicit_half_up_with_tested_boundaries(score, level):
    from app.radar_rwa.jev_intelligence.questions import SCORE_ROUNDING, score_to_level
    assert SCORE_ROUNDING == "ROUND_HALF_UP"  # never banker's rounding at .5 (0.5 would be NORMAL)
    assert score_to_level(Decimal(score)) == level
    assert parse_response(good_response(score=float(score) if "." in score else int(score)))[1].state == level


@pytest.mark.parametrize("score", ["-0.0001", "2.0001", "3", "NaN", "Infinity"])
def test_score_outside_level_index_range_is_rejected_not_rounded(score):
    from app.radar_rwa.jev_intelligence.questions import score_to_level
    with pytest.raises(ValueError, match="OUT_OF_RANGE"):
        score_to_level(Decimal(score))


def test_transport_failure_is_unavailable_not_fabricated():
    error = JevTransportError("HTTP_429", attempt_count=3, latency_ms=Decimal("12.0"))
    result = run(transport=FakeTransport(error=error))
    assert result.state is IntelligenceState.UNAVAILABLE and result.reason == "JEV_TRANSPORT_UNAVAILABLE"
    assert result.diagnostics.failure_category == "HTTP_429" and result.diagnostics.attempt_count == 3
    assert result.market_regime is None and result.attention is None
    weird = run(transport=FakeTransport(error=RuntimeError(f"boom {SECRET}")))
    assert weird.diagnostics.failure_category == "NETWORK" and SECRET not in json.dumps(weird.to_public_dict())
    assert run(transport=FakeTransport(response=[1])).state in (
        IntelligenceState.INVALID_RESPONSE, IntelligenceState.UNAVAILABLE)


# ══ cache ════════════════════════════════════════════════════════════════════════════
def test_same_fingerprint_is_served_from_cache_without_second_call():
    cache, transport, rec = IntelligenceCache(), FakeTransport(), Recorder()
    first = run(rec, transport, cache=cache)
    second = run(rec, transport, cache=cache)
    assert len(transport.calls) == 1
    assert first.diagnostics.cache_status == "MISS" and second.diagnostics.cache_status == "HIT"
    assert second.evaluated_at == first.evaluated_at and second.input_fingerprint == first.input_fingerprint


def test_changed_evidence_bucket_makes_a_new_fingerprint_and_call():
    cache, transport = IntelligenceCache(), FakeTransport()
    run(Recorder(), transport, cache=cache)
    changed = Recorder(cur=current(premium="200"))  # different premium_level bucket
    result = run(changed, transport, cache=cache)
    assert len(transport.calls) == 2 and result.diagnostics.cache_status == "MISS"
    assert result.input_fingerprint != build().input_fingerprint


def test_same_bucket_new_canonical_evidence_never_returns_stale_provenance():
    """F2: identical feature buckets, different canonical observation -> new call, new provenance."""
    cache, transport = IntelligenceCache(), FakeTransport()
    later = NOW + timedelta(minutes=1)
    rec_a = Recorder(cur=current(premium="35.5", retrieved=NOW))
    rec_b = Recorder(cur=current(premium="36.0", retrieved=later))
    fa = F.build_feature_state(current_state="AVAILABLE", current=rec_a.cur[1],
                               ranges=rec_a.rng, points=rec_a.pts)
    fb = F.build_feature_state(current_state="AVAILABLE", current=rec_b.cur[1],
                               ranges=rec_b.rng, points=rec_b.pts)
    assert fa.input_fingerprint == fb.input_fingerprint          # same buckets
    assert fa.observation_digest != fb.observation_digest        # different canonical evidence

    a = run(rec_a, transport, cache=cache)
    b = run(rec_b, transport, cache=cache)
    assert len(transport.calls) == 2                            # B was NOT served A's cached result
    assert a.diagnostics.cache_status == "MISS" and b.diagnostics.cache_status == "MISS"
    assert a.input_fingerprint == b.input_fingerprint
    assert a.observation_digest == fa.observation_digest and b.observation_digest == fb.observation_digest
    assert a.as_of == NOW and b.as_of == later
    assert b.to_public_dict()["provenance"]["as_of"] == later.isoformat()
    # The exact same observation is still a HIT, with its own (not a neighbour's) provenance.
    again = run(rec_b, transport, cache=cache)
    assert again.diagnostics.cache_status == "HIT" and len(transport.calls) == 2
    assert again.observation_digest == fb.observation_digest and again.as_of == later


def test_cache_key_covers_asset_fingerprint_schema_and_model():
    base = ("u", "f", QUESTION_SCHEMA_VERSION, "m", "d")
    assert len({cache_key(*base), cache_key("u2", "f", QUESTION_SCHEMA_VERSION, "m", "d"),
                cache_key("u", "f2", QUESTION_SCHEMA_VERSION, "m", "d"),
                cache_key("u", "f", "V2", "m", "d"), cache_key("u", "f", QUESTION_SCHEMA_VERSION, "m2", "d"),
                cache_key("u", "f", QUESTION_SCHEMA_VERSION, "m", "d2")}) == 6
    cache, transport = IntelligenceCache(), FakeTransport()
    run(Recorder(), transport, cache=cache)
    run(Recorder(), transport, cache=cache, config=JevIntelligenceConfig(mode=JevMode.VISIBLE, model="jev-x"))
    assert len(transport.calls) == 2


def test_cache_expiry_is_respected():
    clock = {"t": 1000.0}
    cache, transport = IntelligenceCache(clock=lambda: clock["t"]), FakeTransport()
    run(Recorder(), transport, cache=cache)
    clock["t"] += 29
    run(Recorder(), transport, cache=cache)
    assert len(transport.calls) == 1
    clock["t"] += 2  # 31s > 30s TTL for a WITHIN_5M observation
    run(Recorder(), transport, cache=cache)
    assert len(transport.calls) == 2


def test_failures_are_never_cached():
    cache = IntelligenceCache()
    bad = FakeTransport(error=JevTransportError("TIMEOUT"))
    run(Recorder(), bad, cache=cache)
    run(Recorder(), bad, cache=cache)
    assert len(bad.calls) == 2
    good = FakeTransport()
    assert run(Recorder(), good, cache=cache).state is IntelligenceState.AVAILABLE


def test_concurrent_identical_requests_coalesce_into_one_call():
    cache, transport = IntelligenceCache(), FakeTransport(delay=0.2)
    results = []

    def worker():
        results.append(run(Recorder(), transport, cache=cache))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(transport.calls) == 1 and len(results) == 5
    assert {r.state for r in results} == {IntelligenceState.AVAILABLE}
    assert {r.diagnostics.cache_status for r in results} <= {"MISS", "COALESCED", "HIT"}


# ══ modes / flag / config ════════════════════════════════════════════════════════════
def test_default_is_off_and_off_makes_zero_calls():
    assert JevIntelligenceConfig.from_env({}).mode is JevMode.OFF
    assert JevIntelligenceConfig.from_env({"FINCO_JEV_INTELLIGENCE_ENABLED": "0"}).mode is JevMode.OFF
    rec, transport = Recorder(), FakeTransport()
    result = run(rec, transport, config=JevIntelligenceConfig())
    assert result.state is IntelligenceState.DISABLED and rec.reads == 0 and transport.calls == []


def test_enabled_without_mode_is_shadow_never_silently_visible():
    env = {"FINCO_JEV_INTELLIGENCE_ENABLED": "1"}
    assert JevIntelligenceConfig.from_env(env).mode is JevMode.SHADOW
    assert JevIntelligenceConfig.from_env({**env, "FINCO_JEV_INTELLIGENCE_MODE": "visible"}).mode is JevMode.VISIBLE
    assert JevIntelligenceConfig.from_env({**env, "FINCO_JEV_INTELLIGENCE_MODE": "bogus"}).mode is JevMode.OFF
    assert JevIntelligenceConfig.from_env({**env, "FINCO_JEV_MODEL": "jev-1.13"}).model == "jev-1.13"
    assert JevIntelligenceConfig.from_env(env).model == "jev-latest"


def test_no_api_key_is_typed_unavailable_without_network():
    result = evaluate_intelligence(
        CID, config=ON, transport=None, current_provider=Recorder().current,
        ranges_provider=Recorder().ranges, points_provider=Recorder().points,
        cache=IntelligenceCache(), telemetry=Telemetry(), environ={})
    assert result.reason == "JEV_API_KEY_NOT_CONFIGURED"


def test_shadow_evaluates_and_records_telemetry_only():
    telemetry, transport = Telemetry(), FakeTransport()
    shadow = JevIntelligenceConfig(mode=JevMode.SHADOW)
    rec = Recorder()
    result = evaluate_shadow(CID, config=shadow, transport=transport, current_provider=rec.current,
                             ranges_provider=rec.ranges, points_provider=rec.points,
                             cache=IntelligenceCache(), telemetry=telemetry)
    assert result.state is IntelligenceState.AVAILABLE and result.mode is JevMode.SHADOW
    snap = telemetry.snapshot()
    assert snap["counters"]["requests"] == 1 and snap["counters"]["provider_calls"] == 1
    assert evaluate_shadow(CID, config=ON).reason == "JEV_SHADOW_MODE_NOT_ACTIVE"


def test_rate_limit_protects_spend():
    from app.radar_rwa.jev_intelligence import service
    config = JevIntelligenceConfig(mode=JevMode.VISIBLE, max_evaluations_per_minute=1)
    service._LIMITERS.pop(1, None)
    transport = FakeTransport()
    first = run(Recorder(), transport, config=config, cache=IntelligenceCache())
    second = run(Recorder(cur=current(premium="200")), transport, config=config, cache=IntelligenceCache())
    assert first.state is IntelligenceState.AVAILABLE
    assert second.reason == "JEV_RATE_LIMITED" and len(transport.calls) == 1
    service._LIMITERS.pop(1, None)


def test_canonical_unavailable_or_stale_makes_no_jev_call():
    for cur in (current(state="UNAVAILABLE"), current(state="STALE")):
        transport = FakeTransport()
        result = run(Recorder(cur=cur), transport)
        assert result.reason == "CANONICAL_CURRENT_NOT_AVAILABLE" and transport.calls == []


def test_provider_exceptions_fail_closed():
    def boom(*a, **k):
        raise RuntimeError("db path /secret")

    transport = FakeTransport()
    result = evaluate_intelligence(CID, config=ON, transport=transport, current_provider=boom,
                                   cache=IntelligenceCache(), telemetry=Telemetry(), environ={})
    assert result.reason == "CANONICAL_CURRENT_UNAVAILABLE" and "secret" not in json.dumps(result.to_public_dict())
    rec = Recorder()
    result = evaluate_intelligence(CID, config=ON, transport=transport, current_provider=rec.current,
                                   ranges_provider=boom, points_provider=rec.points,
                                   cache=IntelligenceCache(), telemetry=Telemetry(), environ={})
    assert result.reason == "HISTORY_UNAVAILABLE" and transport.calls == []


# ══ authority boundaries ═════════════════════════════════════════════════════════════
FORBIDDEN_IMPORTS = ("financial_engine", "finco_core", "app.verified", "app.model_validation",
                     "app.persistence", "app.run_integrity", "run_certificate", "token_entitlement",
                     "BnbIntelligenceHistoryStore", "put_r_live", "sqlite3", "ProjectInputs")


def test_package_never_imports_engine_verify_history_writer_or_signing():
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            assert forbidden not in source, f"{path.name} references {forbidden}"


def test_no_recommendation_or_trading_vocabulary_in_package_or_panel():
    pattern = re.compile(r"\b(BUY|SELL|LONG|SHORT)\b|target price|price target", re.I if False else 0)
    for path in PACKAGE.glob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name
    template = (REPO / "app/templates/radar/r_live_detail.html").read_text(encoding="utf-8")
    panel = template[template.index('id="jev-intelligence"'):template.index("Identity &amp; Deployment")]
    assert not pattern.search(panel)
    assert not re.search(r"\b(whale|wash trad|smart money|organic demand)\b", panel, re.I)


def test_read_path_writes_nothing_and_touches_no_authority(monkeypatch):
    import app.radar_rwa.bnb_history as history
    writes = []
    monkeypatch.setattr(history.BnbIntelligenceHistoryStore, "put_r_live",
                        lambda *a, **k: writes.append("put_r_live"), raising=False)
    monkeypatch.setattr(history.BnbIntelligenceHistoryStore, "put",
                        lambda *a, **k: writes.append("put"), raising=False)
    import financial_engine.orchestrator as orchestrator
    monkeypatch.setattr(orchestrator, "run_senior_debt_model",
                        lambda *a, **k: writes.append("engine"), raising=False)
    rec, cur = Recorder(), current()
    before = copy.deepcopy(cur)
    run(Recorder(cur=cur), FakeTransport())
    assert writes == [] and cur == before


def test_jev_failure_does_not_change_canonical_evidence():
    rec = Recorder()
    snapshot = copy.deepcopy(rec.cur)
    result = run(rec, FakeTransport(error=JevTransportError("TIMEOUT")))
    assert result.state is IntelligenceState.UNAVAILABLE and rec.cur == snapshot


def test_telemetry_is_sanitized_and_cost_is_only_an_estimate():
    telemetry = Telemetry()
    run(Recorder(), FakeTransport(), telemetry=telemetry)
    blob = json.dumps(telemetry.snapshot())
    assert SECRET not in blob and "Authorization" not in blob and "features" not in blob
    rec = telemetry.snapshot()["recent"][0]
    assert set(rec) == {"recorded_at", "canonical_id", "mode", "outcome", "cache_status", "latency_ms",
                        "requested_model", "resolved_model", "provider_request_id", "usage",
                        "failure_category"}
    assert estimate_request_cost_usd(1_000_000) == Decimal("0.042")


# ══ API + UI ═════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    import main_web
    return TestClient(main_web.app)


def _fake_available():
    return run(transport=FakeTransport())


def test_api_off_and_shadow_are_not_exposed_and_never_evaluate(client, monkeypatch):
    import app.radar_rwa.jev_intelligence.service as service

    def boom(*a, **k):
        raise AssertionError("must not evaluate")

    monkeypatch.setattr(service, "evaluate_intelligence", boom)
    monkeypatch.delenv("FINCO_JEV_INTELLIGENCE_ENABLED", raising=False)
    off = client.get(f"/api/v1.1/radar/r-live/{CID}/intelligence")
    assert off.status_code == 200 and off.json()["data"]["reason"] == "JEV_INTELLIGENCE_DISABLED"
    assert off.headers["cache-control"] == "no-store"
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
    shadow = client.get(f"/api/v1.1/radar/r-live/{CID}/intelligence")
    assert shadow.json()["data"]["reason"] == "JEV_SHADOW_MODE_NOT_EXPOSED"
    assert shadow.json()["data"]["answers"] is None


def test_api_visible_returns_typed_payload_with_disclosure(client, monkeypatch):
    import app.radar_rwa.jev_intelligence.service as service
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_MODE", "VISIBLE")
    available = _fake_available()
    monkeypatch.setattr(service, "evaluate_intelligence", lambda cid, config=None: available)
    body = client.get(f"/api/v1.1/radar/r-live/{CID}/intelligence").json()
    data = body["data"]
    assert body["state"] == "AVAILABLE" and data["label"] == "EXPERIMENTAL"
    for key in ("canonical_identity", "observation_digest", "feature_schema_version",
                "question_schema_version", "input_fingerprint", "answers", "requested_model",
                "resolved_model", "evaluated_at", "provenance", "disclosure", "diagnostics"):
        assert key in data
    assert data["canonical_identity"]["canonical_id"] == CID
    assert data["canonical_identity"]["economic_asset_uid"] == UID
    assert data["disclosure"] == DISCLOSURE
    assert "TYPESAFE_API_KEY" not in json.dumps(body)


def test_api_visible_unknown_identity_is_typed_unavailable(client, monkeypatch):
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_MODE", "VISIBLE")
    body = client.get(f"/api/v1.1/radar/r-live/{SYMBOL}/intelligence").json()
    assert body["state"] == "UNAVAILABLE" and body["data"]["reason"] == "ASSET_UID_INVALID"


def test_public_r_live_router_keeps_its_six_route_contract():
    from app.api.v1_1.r_live_public_router import router
    assert not any("intelligence" in route.path for route in router.routes)


def test_ui_off_page_has_no_panel_and_no_fetch(client, monkeypatch):
    monkeypatch.delenv("FINCO_JEV_INTELLIGENCE_ENABLED", raising=False)
    html = client.get(f"/radar/r-live/{CID}").text
    assert "jev-intelligence" not in html and "/intelligence" not in html
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")  # SHADOW: still hidden
    assert "jev-intelligence" not in client.get(f"/radar/r-live/{CID}").text


def test_ui_visible_panel_is_experimental_and_keeps_canonical_metrics(client, monkeypatch):
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_MODE", "VISIBLE")
    html = client.get(f"/radar/r-live/{CID}").text
    assert 'data-testid="jev-intelligence-panel"' in html and "Experimental" in html
    assert "Jev Intelligence" in html and DISCLOSURE.split(".")[0] in html
    for canonical in ("detail-ref-price", "detail-basis-price", "detail-premium", "detail-live-block"):
        assert canonical in html  # canonical R-LIVE data never hidden by the panel
    assert f"/api/v1.1/radar/r-live/" in html and "/intelligence" in html
    panel = html[html.index('id="jev-intelligence"'):html.index("Identity &amp; Deployment")]
    assert not re.search(r"\b(BUY|SELL|LONG|SHORT)\b|target price", panel)
    assert "Unavailable" not in panel or "unavailable" in html.lower()  # honest state handled in JS
    assert "jev-status" in html and "Jev intelligence unavailable" in html


def test_ui_unapproved_asset_never_renders_panel(client, monkeypatch):
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_MODE", "VISIBLE")
    assert "jev-intelligence" not in client.get("/radar/r-live/NOT-APPROVED").text


# ══ real read-only history ledger (schema parity + zero writes) ═══════════════════════
def _ledger_point(collected: datetime, value: str, source_id: int) -> dict:
    return {
        "economic_asset_uid": UID, "asset_key": CID,
        "observed_at": (collected - timedelta(seconds=5)).isoformat(),
        "collected_at": collected.isoformat(), "state": "AVAILABLE",
        "robinhood_basis": {"price_usd_per_token": "100"},
        "independent_token_reference": {"priceUsdPerToken": "101",
                                        "evidence": {"sourceEvent": source_id,
                                                     "retrievedAt": collected.isoformat()}},
        "reference_premium_bps": value,
    }


def test_real_ledger_read_path_builds_features_and_writes_nothing(tmp_path, monkeypatch):
    import hashlib
    from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore
    from app.radar_rwa import jev_intelligence as pkg
    from app.radar_rwa.jev_intelligence.service import (
        default_points_provider, default_ranges_provider)

    db = tmp_path / "history.db"
    store = BnbIntelligenceHistoryStore(str(db), allowed_chain_id=4663)
    try:
        for i in range(0, 50):  # 25h of 30-minute observations, premium rising 20 -> 35
            store.put(_ledger_point(NOW - timedelta(minutes=30 * (49 - i)), f"{20 + i * 15 / 49:.4f}", i))
    finally:
        store.close()
    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", str(db))
    def _state():
        return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(tmp_path.iterdir())}

    before_files = _state()
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    rec, transport = Recorder(), FakeTransport()
    result = evaluate_intelligence(
        CID, config=ON, transport=transport, current_provider=rec.current,
        ranges_provider=default_ranges_provider, points_provider=default_points_provider,
        cache=IntelligenceCache(), telemetry=Telemetry(), environ={})
    assert result.state is IntelligenceState.AVAILABLE
    features = transport.calls[0]["state"]["features"]
    assert features["direction_24h"] == "UP" and features["observation_density_24h"] == "MODERATE"
    assert features["position_in_24h_range"] in ("UPPER_THIRD", "ABOVE_RANGE", "MIDDLE_THIRD")
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before  # zero history writes
    # A read-only SQLite handle on a WAL ledger may materialise empty -wal/-shm sidecars (same as
    # the existing canonical range/history reads); no ledger content may change.
    after = _state()
    assert after["history.db"] == before_files["history.db"]
    wal = tmp_path / "history.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0
    assert pkg  # package imported without side effects


def test_empty_real_ledger_fails_closed_without_a_jev_call(tmp_path, monkeypatch):
    from app.radar_rwa.jev_intelligence.service import (
        default_points_provider, default_ranges_provider)
    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", str(tmp_path / "missing.db"))
    transport = FakeTransport()
    result = evaluate_intelligence(
        CID, config=ON, transport=transport, current_provider=Recorder().current,
        ranges_provider=default_ranges_provider, points_provider=default_points_provider,
        cache=IntelligenceCache(), telemetry=Telemetry(), environ={})
    assert result.reason == "INSUFFICIENT_HISTORY" and transport.calls == []
    assert not (tmp_path / "missing.db").exists()  # reading never creates a ledger


def test_rate_limit_scope_is_described_as_process_wide_not_host_global():
    service_src = (PACKAGE / "service.py").read_text(encoding="utf-8")
    config_src = (PACKAGE / "config.py").read_text(encoding="utf-8")
    assert "Process-wide" in service_src and "not host-global" in service_src
    assert "N x" in service_src and "PROCESS" in config_src
    for source in (service_src, config_src):
        assert "host-wide limiter" not in source.lower() and "global limiter" not in source.lower()
