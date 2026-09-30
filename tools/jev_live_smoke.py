"""Bounded, operator-run live validation of the TypeSafe System One contract (SHADOW use only).

Makes at most ONE model-discovery request and ONE synthetic evaluation. The evaluation uses a
fixed, representative bucket state (no canonical FINCO data, no identity), so it costs one small
request and touches nothing. Prints only closed summary fields: never the API key, the
Authorization header or raw provider payloads. Without ``TYPESAFE_API_KEY`` it prints
``LIVE_PROVIDER_SMOKE = SKIPPED_NO_KEY`` and exits 0. Not part of CI.

    TYPESAFE_API_KEY=... python tools/jev_live_smoke.py
"""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from typing import Callable, Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.radar_rwa.jev_intelligence.config import DEFAULT_MODEL, MODEL_ENV, api_key  # noqa: E402
from app.radar_rwa.jev_intelligence.contracts import FeatureState  # noqa: E402
from app.radar_rwa.jev_intelligence.questions import build_request, parse_response  # noqa: E402
from app.radar_rwa.jev_intelligence.service import _meta, build_transport  # noqa: E402

_SYNTHETIC_FEATURES = {
    "premium_level": "MODERATE_PREMIUM", "position_in_1h_range": "MIDDLE_THIRD",
    "position_in_24h_range": "UPPER_THIRD", "direction_1h": "UP", "direction_24h": "UP",
    "short_long_agreement": "AGREE", "range_shape": "INTERMEDIATE", "range_width_24h": "MODERATE",
    "observation_density_1h": "MODERATE", "observation_density_24h": "MODERATE",
    "market_activity_age": "WITHIN_5M",
}


def run_smoke(environ: Mapping[str, str] | None = None,
              transport_factory: Callable[[str], object] = build_transport,
              emit: Callable[[str], None] = print) -> int:
    env = os.environ if environ is None else environ
    key = api_key(env)
    if key is None:
        emit("LIVE_PROVIDER_SMOKE = SKIPPED_NO_KEY")
        return 0
    model = str(env.get(MODEL_ENV, DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    transport = transport_factory(key)
    emit(f"requested_model = {model}")

    try:  # at most one discovery request; informational only
        models = transport.list_models()  # type: ignore[attr-defined]
        listed = models.get("data") if isinstance(models, Mapping) else None
        ids = {m.get("id") for m in listed if isinstance(m, Mapping)} if isinstance(listed, list) else set()
        emit("model_discovery = " + ("LISTED" if model in ids else "REACHED_MODEL_NOT_LISTED"
                                     if ids else "REACHED_NO_MODEL_LIST"))
    except Exception as exc:  # noqa: BLE001
        emit(f"model_discovery = UNAVAILABLE({getattr(exc, 'failure_category', 'NETWORK')})")

    state = FeatureState(
        features=_SYNTHETIC_FEATURES, input_fingerprint=hashlib.sha256(b"smoke").hexdigest(),
        observation_digest=hashlib.sha256(b"smoke").hexdigest(),
        as_of=datetime.now(timezone.utc), sources=("SYNTHETIC_SMOKE_STATE",), ttl_seconds=30)
    try:
        response = transport.evaluate(build_request(state, model=model))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        emit(f"http_success = NO({getattr(exc, 'failure_category', 'NETWORK')})")
        emit("LIVE_PROVIDER_SMOKE = FAIL")
        return 1
    emit("http_success = YES")
    latency, attempts, _request_id, usage = _meta(response)
    try:
        regime, attention, resolved = parse_response(response)
    except (ValueError, TypeError) as exc:
        emit(f"response_contract = FAIL({str(exc)[:80]})")
        emit("LIVE_PROVIDER_SMOKE = FAIL")
        return 1
    emit("response_contract = PASS")
    emit(f"resolved_model = {resolved}")
    emit(f"latency_ms = {latency}")
    emit(f"attempts = {attempts}")
    emit("usage = " + (", ".join(f"{k}={v}" for k, v in usage) or "NOT_SUPPLIED"))
    emit(f"answers = market_regime:{regime.choice} attention:{attention.state}")
    emit("LIVE_PROVIDER_SMOKE = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_smoke())
