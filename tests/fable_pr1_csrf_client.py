"""FABLE-SEC-01 (C1-Q-07): positive client helper for legacy /projects/create.

Since the two legacy mutating routes enforce the session+operation-bound CSRF
token (Fable D07b/D07c fix), test clients must supply the token exactly like a
browser does: fetch the rendered create form and post its hidden token back.
This helper changes ONLY the call mechanics — every assertion and expected
financial value of the adapting tests is unchanged.
"""
from __future__ import annotations

import re

_CREATE_TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]*)"')


def fetch_create_csrf_token(client) -> str:
    """Return the bound token the server rendered into the create form."""
    page = client.get("/projects/new")
    assert page.status_code == 200, page.status_code
    m = _CREATE_TOKEN_RE.search(page.text)
    assert m, "create form must render the bound csrf_token"
    return m.group(1)


def post_create(client, data: dict, **kwargs):
    """POST /projects/create with the rendered bound token included."""
    return client.post("/projects/create", data={**data, "csrf_token": fetch_create_csrf_token(client)}, **kwargs)
