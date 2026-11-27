"""Opt-in negative controls for the reviewed Correction A handoff."""
import ast
import json
import os
import subprocess
from contextlib import contextmanager

import pytest

from tests.on_bess01_router_review import violations
from tests.test_on_bess01_contract_checks import client, payload


@pytest.mark.parametrize('fault', ['expired', 'purpose', 'session'])
def test_signed_tokens_refuse_expiry_wrong_purpose_and_same_actor_new_session(client, fault):
    import time
    from itsdangerous import URLSafeTimedSerializer, TimestampSigner
    from starlette.requests import Request
    from app import auth
    from app.workbook import financing_csrf as F
    from app.v2.bess_setup_router import PURPOSE
    body = payload(client)
    cookie = client.cookies.get(auth.COOKIE_NAME)
    request = Request({'type': 'http', 'headers': [(b'cookie', (auth.COOKIE_NAME + '=' + cookie).encode())]})
    if fault == 'purpose':
        body['csrf_token'] = F.issue_token(request, body['request_id'], purpose='new-project-create')
    elif fault == 'expired':
        class ExpiredSigner(TimestampSigner):
            def get_timestamp(self):
                return int(time.time()) - 90_000
        old = URLSafeTimedSerializer(auth.CSRF_SECRET, signer=ExpiredSigner).dumps('a' * 48)
        binding = F._session_binding(request, body['request_id'])
        body['csrf_token'] = old + '.' + F._digest(binding, old, PURPOSE)
    else:
        client.cookies.set(auth.COOKIE_NAME, auth.create_session_token(user_id='synthetic-bess-owner', username='renewed-session'))
    assert client.post('/v2/model-react/new-project/bess-preview', json=body).status_code == 403


def test_flag_zero_keeps_both_routes_enabled(client, monkeypatch):
    body = payload(client)
    monkeypatch.setenv('FINCO_MODEL_REACT_V1', '0')
    assert client.get('/v2/model-react/new-project/bess-options').status_code == 200
    assert client.post('/v2/model-react/new-project/bess-preview', json=body).status_code != 404


def test_options_requires_an_authenticated_session(client):
    client.cookies.clear()
    assert client.get('/v2/model-react/new-project/bess-options').status_code == 401


def test_availability_is_rechecked_after_native_parsing(client, monkeypatch):
    from app.v2 import bess_setup_router as R
    from app.services.bess_setup_preview import capability
    body = payload(client)
    answers = iter([capability(), {**capability(), 'preview_supported': False}])
    monkeypatch.setattr(R, 'capability', lambda: next(answers))
    response = client.post('/v2/model-react/new-project/bess-preview', json=body)
    assert response.status_code == 409
    assert response.json()['persisted'] is False


