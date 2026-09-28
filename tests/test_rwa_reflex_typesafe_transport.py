import pytest

from app.radar_rwa.reflex import TypeSafeJevHttpConfig, TypeSafeJevHttpTransport, TypeSafeJevTransportError
from app.radar_rwa.reflex.typesafe_transport import TYPESAFE_SYSTEMONE_URL

SECRET = "SYNTHETIC_SECRET_MARKER_7d2f"


class Response:
    def __init__(self, status_code, payload=None, *, headers=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}
        self.json_error = json_error
    def json(self):
        if self.json_error is not None: raise self.json_error
        return self.payload


class Client:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
    def post(self, url, *, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if self.error is not None: raise self.error
        return self.responses.pop(0)


def request():
    return {"state": {"request_schema_version": "RWA_REFLEX_JEV_REQUEST_V2", "features": {
        "schema_version": "RWA_REFLEX_FEATURES_V2", "market_session": "OPEN",
        "deviation_bucket": "100_TO_199_BPS", "depth_bucket": "25K_TO_99K_USD"}},
        "model": "jev-latest", "questions": {"likely_transient": {"type": "noul", "instructions": "forecast"}}}


def test_success_adds_attempt_and_latency_metadata_without_key_in_payload():
    client = Client([Response(200, {"model": "jev-1", "answers": {}, "usage": {}})])
    transport = TypeSafeJevHttpTransport(SECRET, client=client, clock=lambda: 0.0)
    result = transport.evaluate(request())
    assert client.calls[0]["url"] == TYPESAFE_SYSTEMONE_URL
    assert client.calls[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in repr(client.calls[0]["json"])
    assert result["_transport_meta"] == {"latency_ms": "0.000", "attempt_count": 1}
    assert SECRET not in repr(result)
    assert SECRET not in repr(transport)


def test_408_429_and_5xx_retry_and_retry_after_is_honored():
    client = Client([
        Response(408, {}, headers={"Retry-After": "0.4"}),
        Response(429, {}),
        Response(503, {}),
        Response(200, {"model": "jev-1", "answers": {}}),
    ])
    delays = []
    transport = TypeSafeJevHttpTransport(
        SECRET, client=client,
        config=TypeSafeJevHttpConfig(max_retries=3, initial_backoff_seconds=0.25, max_total_seconds=10),
        sleep=delays.append, clock=lambda: 0.0,
    )
    result = transport.evaluate(request())
    assert result["_transport_meta"]["attempt_count"] == 4
    assert delays == [0.4, 0.5, 1.0]


@pytest.mark.parametrize("status,code", [
    (400, "TYPESAFE_BAD_REQUEST"), (401, "TYPESAFE_UNAUTHORIZED"), (403, "TYPESAFE_FORBIDDEN"),
    (404, "TYPESAFE_NOT_FOUND"), (422, "TYPESAFE_REQUEST_INVALID"),
])
def test_request_and_auth_errors_never_retry(status, code):
    client = Client([Response(status, {"detail": SECRET})])
    transport = TypeSafeJevHttpTransport(SECRET, client=client)
    with pytest.raises(TypeSafeJevTransportError) as exc:
        transport.evaluate(request())
    assert str(exc.value) == code
    assert SECRET not in str(exc.value)
    assert len(client.calls) == 1


def test_synthetic_secret_never_escapes_client_exception_or_retry_failure():
    transport = TypeSafeJevHttpTransport(SECRET, client=Client(error=RuntimeError(f"provider blew up {SECRET}")))
    with pytest.raises(TypeSafeJevTransportError) as exc:
        transport.evaluate(request())
    assert str(exc.value) == "TYPESAFE_CLIENT_ERROR"
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value)
    # RWA_REFLEX_TYPESAFE_SECRET_NEVER_PERSISTS


def test_invalid_json_and_shape_are_sanitized():
    bad_json = TypeSafeJevHttpTransport(SECRET, client=Client([Response(200, json_error=ValueError(SECRET))]))
    with pytest.raises(TypeSafeJevTransportError, match="^TYPESAFE_RESPONSE_JSON_INVALID$"):
        bad_json.evaluate(request())
    bad_shape = TypeSafeJevHttpTransport(SECRET, client=Client([Response(200, [SECRET])]))
    with pytest.raises(TypeSafeJevTransportError, match="^TYPESAFE_RESPONSE_SHAPE_INVALID$"):
        bad_shape.evaluate(request())
