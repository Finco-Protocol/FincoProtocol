"""WF-07 / S7-06: the Library classifies canonical references, previews and editable working copies unambiguously and never shows a missing result as zero."""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import re

from tests.test_qa_create_project_country_capacity import _login, client  # noqa: F401

import pytest


def _lib(client, login=True, **params):
    if login:
        _login(client)
    resp = client.get("/v2/model-react/library", params=params)
    assert resp.status_code == 200, resp.text[:200]
    return resp.json()


def test_every_reference_card_is_labelled_canonical_and_read_only(client):
    payload = _lib(client)
    refs = payload["references"]
    assert refs, "reference cards are returned for a user without projects"
    assert all(r["protected_reference"] is True and r["reference"] is True for r in refs)
    assert any(r["vertical"]["pilot_tier"] != "RELEASE_CLOSED" for r in refs)


def test_a_reference_without_saved_results_states_it_and_never_shows_zero(client):
    payload = _lib(client)
    storage = [r for r in payload["references"] if not r["last_run"]["available"]]
    assert storage, "release-closed preview reference without runs is explicitly unavailable"
    for ref in storage:
        assert ref["last_run"]["freshness"] == "NOT_RUN" and ref["last_run"]["snapshot_id"] == ""


def test_working_copies_and_runs_are_distinguished_after_cloning(client):
    payload = _lib(client)
    clonable = next(r for r in payload["references"] if r["vertical"]["pilot_tier"] != "RELEASE_CLOSED")
    r = client.post(f"/library/clone/{clonable['project_id']}", data={"csrf_token": payload["csrf_token"]}, follow_redirects=False)
    assert r.status_code in (200, 204, 303), r.text[:200]
    after = _lib(client, login=False)
    assert after["projects"], "cloned working copy appears in projects"
    copy = after["projects"][0]
    assert copy["protected_reference"] is False and copy["reference"] is False
    assert copy["last_run"]["available"] is False and copy["last_run"]["freshness"] == "NOT_RUN"
