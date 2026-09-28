from decimal import Decimal

from app.radar_rwa.reflex import InterpretationState, JevReflexConfig, build_jev_request, interpret_reflex_with_jev, reflex_input_fingerprint
from tests.rwa_reflex_helpers import state


class SpyTransport:
    def __init__(self, responder=None):
        self.responder = responder
        self.calls = []
    def evaluate(self, request):
        self.calls.append(request)
        if self.responder is None:
            raise AssertionError("transport should not have been called")
        return self.responder(request)


def valid_response(_request):
    return {
        "id": "req_test_1",
        "model": "jev-1.13.0",
        "answers": {"likely_transient": {"type": "noul", "noul": 0.73}},
        "usage": {"input_tokens": 400},
        "_transport_meta": {"latency_ms": "12.5", "attempt_count": 2},
    }


def test_jev_disabled_by_default():
    transport = SpyTransport()
    result = interpret_reflex_with_jev(state(), transport)
    assert result.state is InterpretationState.DISABLED
    assert transport.calls == []


def test_reduced_question_set_and_blinded_outbound_allowlist():
    s = state()
    request = build_jev_request(s, config=JevReflexConfig(enabled=True))
    assert set(request["questions"]) == {"likely_transient"}
    features = request["state"]["features"]
    assert set(features) == {"schema_version", "market_session", "deviation_bucket", "depth_bucket"}
    serialized = repr(request)
    for forbidden in (s.economic_asset_uid, s.canonical_token.contract_address, s.canonical_token.canonical_id,
                      "underlying_reference_usd", "token_reference_usd", "context_warnings", "wallet", "entitlement", "workspace"):
        assert forbidden not in serialized


def test_valid_forecast_preserves_resolved_model_and_transport_metadata():
    transport = SpyTransport(valid_response)
    result = interpret_reflex_with_jev(state(), transport, config=JevReflexConfig(enabled=True, model="jev-latest"))
    assert result.state is InterpretationState.AVAILABLE
    assert result.likely_transient_probability == Decimal("0.73")
    assert result.requested_model == "jev-latest"
    assert result.resolved_model == "jev-1.13.0"
    assert result.provider_request_id == "req_test_1"
    assert result.latency_ms == Decimal("12.5")
    assert result.attempt_count == 2
    assert dict(result.usage) == {"input_tokens": "400"}


def test_extra_jev_questions_are_rejected():
    def extra(request):
        response = valid_response(request)
        response["answers"]["regime"] = {"type": "choice", "choice": "NORMAL"}
        return response
    result = interpret_reflex_with_jev(state(), SpyTransport(extra), config=JevReflexConfig(enabled=True))
    assert result.state is InterpretationState.INVALID_RESPONSE
    assert result.reason == "JEV_UNEXPECTED_QUESTION_OUTPUT"


def test_out_of_range_probability_fails_closed():
    def bad(request):
        response = valid_response(request)
        response["answers"]["likely_transient"]["noul"] = 1.2
        return response
    result = interpret_reflex_with_jev(state(), SpyTransport(bad), config=JevReflexConfig(enabled=True))
    assert result.state is InterpretationState.INVALID_RESPONSE


def test_provenance_changes_fingerprint_even_when_derived_numbers_match():
    a = state(history_source="CANONICAL_HISTORY_A")
    b = state(history_source="CANONICAL_HISTORY_B")
    assert a.reference_premium_bps == b.reference_premium_bps
    assert a.basis_z_score == b.basis_z_score
    assert a.premium_deviation_bps == b.premium_deviation_bps
    assert reflex_input_fingerprint(a) != reflex_input_fingerprint(b)


def test_transport_exception_text_is_not_exposed():
    class Broken:
        def evaluate(self, request):
            raise RuntimeError("SECRET_SHOULD_NOT_ESCAPE")
    result = interpret_reflex_with_jev(state(), Broken(), config=JevReflexConfig(enabled=True))
    assert result.state is InterpretationState.UNAVAILABLE
    assert "SECRET_SHOULD_NOT_ESCAPE" not in (result.reason or "")
