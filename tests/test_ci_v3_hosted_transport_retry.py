"""Bounded retry of transient GitHub API HTTP 5xx in the hosted transport, and nothing else (Correction A, PR #405)."""
import io
import urllib.error

import pytest

from tools import ci_v3_hosted_transport as module
from tools.ci_v3_hosted_transport import GitHub
from tools.ci_v3_schema import ContractError

PATH = '/repos/owner/project/actions/runs/1'


class Response:
    def __init__(self, data): self.data = data; self.headers = {}
    def read(self, n): return self.data[:n]
    def __enter__(self): return self
    def __exit__(self, *args): pass


class Scripted:
    """Answers the scripted statuses in order (200 = JSON body); records every request."""
    def __init__(self, statuses, redirect='https://fixture.blob.core.windows.net/archive'):
        self.statuses, self.redirect, self.requests = list(statuses), redirect, []

    def open(self, request, timeout):
        self.requests.append(request)
        if request.full_url.startswith('https://api.github.com'):
            status = self.statuses[min(len(self.requests) - 1, len(self.statuses) - 1)] if self.statuses else 200
            if status == 200:
                return Response(b'{"ok": true}')
            headers = {'Location': self.redirect} if status == 302 else {}
            raise urllib.error.HTTPError(request.full_url, status, 'x', headers, io.BytesIO(b''))
        return Response(b'archive fixture')


@pytest.fixture
def waits(monkeypatch):
    seen = []
    monkeypatch.setattr(module.time, 'sleep', seen.append)
    return seen


def client(statuses, **kw):
    api = GitHub(token='fixture-not-a-credential')
    api.opener = Scripted(statuses, **kw)
    return api


@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_transient_5xx_then_success_retries_the_identical_request(status, waits):
    api = client([status, 200])
    assert api.get(PATH) == {'ok': True}
    first, second = api.opener.requests
    assert len(api.opener.requests) == 2 and api.transient_retries == 1 and waits == [1]
    assert (first.full_url, first.get_method(), dict(first.header_items())) == (second.full_url, second.get_method(), dict(second.header_items()))
    assert first.full_url.startswith('https://api.github.com/repos/') and second.get_header('Authorization') == 'Bearer fixture-not-a-credential'


def test_two_transient_failures_then_success_uses_the_whole_bounded_budget(waits):
    api = client([502, 503, 200])
    assert api.get(PATH) == {'ok': True} and len(api.opener.requests) == 3 and waits == [1, 2]


def test_persistent_502_keeps_the_existing_failure_and_never_substitutes_evidence(waits):
    api = client([502])
    with pytest.raises(ContractError, match='GitHub GET failed: 502'):
        api.get(PATH)
    assert len(api.opener.requests) == module.API_ATTEMPTS == 3 and waits == [1, 2] and api.transient_retries == 2


@pytest.mark.parametrize('status', [301, 304, 400, 401, 403, 404, 409, 410, 422, 429])
def test_non_transient_statuses_are_never_retried(status, waits):
    api = client([status])
    with pytest.raises(ContractError, match='GitHub GET failed: ' + str(status)):
        api.get(PATH)
    assert len(api.opener.requests) == 1 and waits == [] and api.transient_retries == 0


def test_only_http_5xx_is_retried_not_transport_errors_or_bad_payloads(waits):
    class Boom:
        calls = 0
        def open(self, request, timeout):
            Boom.calls += 1
            raise urllib.error.URLError('connection reset')
    api = GitHub(); api.opener = Boom()
    with pytest.raises(urllib.error.URLError):
        api.get(PATH)
    assert Boom.calls == 1 and waits == []
    class Bad:
        def open(self, request, timeout): return Response(b'not json')
    api.opener = Bad()
    with pytest.raises(ValueError):
        api.get(PATH)


def test_the_retry_budget_is_small_and_deterministic():
    assert module.TRANSIENT_STATUS == frozenset({500, 502, 503, 504}) and module.API_ATTEMPTS == 3
    assert module.API_BACKOFF_SECONDS == (1, 2) and sum(module.API_BACKOFF_SECONDS) <= 3


def test_secure_artifact_redirect_still_works_after_a_transient_5xx_and_forwards_no_credential(waits):
    api = client([503, 302])
    assert api.raw('/repos/owner/project/actions/artifacts/12/zip', archive=True) == b'archive fixture'
    api_requests = [r for r in api.opener.requests if r.full_url.startswith('https://api.github.com')]
    storage = [r for r in api.opener.requests if not r.full_url.startswith('https://api.github.com')]
    assert len(api_requests) == 2 and len(storage) == 1 and storage[0].get_header('Authorization') is None
    assert all(r.get_method() == 'GET' for r in api.opener.requests) and waits == [1]


@pytest.mark.parametrize('url', ['http://fixture.blob.core.windows.net/a', 'https://evil.invalid/a', 'https://user' + '@fixture.blob.core.windows.net/a'])
def test_untrusted_redirects_are_still_rejected_and_never_retried(url, waits):
    api = client([302], redirect=url)
    with pytest.raises(ContractError, match='redirect'):
        api.raw('/repos/owner/project/actions/artifacts/12/zip', archive=True)
    assert len(api.opener.requests) == 1 and waits == []


def test_a_storage_5xx_is_not_retried_and_the_unsafe_route_check_still_precedes_any_request(waits):
    api = client([302])
    original = api.opener.open
    def storage_5xx(request, timeout):
        if not request.full_url.startswith('https://api.github.com'):
            api.opener.requests.append(request)
            raise urllib.error.HTTPError(request.full_url, 502, 'x', {}, io.BytesIO(b''))
        return original(request, timeout)
    api.opener.open = storage_5xx
    with pytest.raises(urllib.error.HTTPError):
        api.raw('/repos/owner/project/actions/artifacts/12/zip', archive=True)
    assert waits == []                                              # the storage request is deliberately not part of the retry
    fresh = client([200])
    with pytest.raises(ContractError, match='unsafe'):
        fresh.raw('/etc/passwd')
    assert fresh.opener.requests == []
