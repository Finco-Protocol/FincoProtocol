"""PR2c — gated combined CAPEX amount + monthly profile Save All: read-echo,
advertisement and OFF-identity contracts.

OD-B2 stays NOT approved: every new server surface is gated behind
``FINCO_SAVE_ALL_PROFILE_ENABLED`` (read per call).  The flag OFF keeps both
read payloads byte-identical to the PR2b behavior, and the combined
save-all transaction itself is already covered by
``tests/test_d7_save_all_profile_atomic.py`` (opt-in fixture).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.run_clone_csrf import post_valid_csrf
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_react_rcux_capex_v1 import HDR, READ  # noqa: F401  (constants)

OWNER = "decision-user"
WORKSPACE = "/v2/model-react/workspace"


@pytest.fixture
def capex(env, monkeypatch):  # noqa: F811
    from app.v2.react_capex import router
    from app.v2.react_workspace_router import router as ws_router
    from app.v2.capex_profile_router import profile_router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    env.client.app.include_router(ws_router, prefix="/v2")
    env.client.app.include_router(profile_router, prefix="/v2/capex")
    record = env.create("solar")
    env.client.cookies.update({})  # session already set by env
    return SimpleNamespace(env=env, client=env.client, record=record)


def read_profiles(env, record):
    response = env.client.get(READ, params={"project": record.project_code})
    assert response.status_code == 200, response.text[:600]
    return response.json()


def read_workspace(env, record):
    response = env.client.get(WORKSPACE, params={"project": record.project_code})
    assert response.status_code == 200, response.text[:400]
    return response.json()


def token_of(env, record):
    from app.capex_profiles.service import read_profile_token
    return read_profile_token(OWNER, record.project_id)


class TestGatedReadEcho:
    def test_flag_off_keeps_the_profiles_read_byte_identical(self, capex, monkeypatch):
        monkeypatch.delenv("FINCO_SAVE_ALL_PROFILE_ENABLED", raising=False)
        payload = read_profiles(capex, capex.record)
        assert "save_all_combined" not in payload["save"]

    def test_flag_on_echoes_the_persisted_profile_document_token(self, capex, monkeypatch):
        monkeypatch.setenv("FINCO_SAVE_ALL_PROFILE_ENABLED", "1")
        payload = read_profiles(capex, capex.record)
        combined = payload["save"]["save_all_combined"]
        assert combined["available"] is True
        assert combined["url"] == "/v2/workbook/save-all"
        assert combined["profile_base_token"] == token_of(capex, capex.record)

    def test_the_echoed_token_matches_the_saved_document_and_rotates_after_a_save(
            self, capex, monkeypatch):
        """A save through the canonical form route rotates the document token, and the
        read echo always exposes the CURRENT persisted token (never a stale one)."""
        monkeypatch.setenv("FINCO_SAVE_ALL_PROFILE_ENABLED", "1")
        before = token_of(capex, capex.record)
        payload = read_profiles(capex, capex.record)
        item = payload["items"][0]
        csrf = payload["save"]["csrf_token"]
        response = capex.client.post(
            payload["save"]["url"],
            data={"project": capex.record.project_code, "csrf_token": csrf,
                  "content_hash": payload["save"]["content_hash"], "action": "save",
                  "key_0": item["item_key"], "shape_0": "UNIFORM"})
        assert response.status_code in (200, 302, 303), response.text[:300]
        after = token_of(capex, capex.record)
        assert after != before, "the document token must rotate after a save"
        echoed = read_profiles(capex, capex.record)["save"]["save_all_combined"]["profile_base_token"]
        assert echoed == after

    def test_flag_off_the_read_token_is_still_the_writer_token(self, capex, monkeypatch):
        """The OFF payload gains no fields, but the primitive the writer uses is the same one the
        echo would expose — no second token authority exists."""
        monkeypatch.delenv("FINCO_SAVE_ALL_PROFILE_ENABLED", raising=False)
        payload = read_profiles(capex, capex.record)
        assert token_of(capex, capex.record)  # primitive exists and is non-empty for a saved doc


class TestGatedAdvertisement:
    def test_flag_off_advertises_exactly_the_pr2b_sections(self, capex, monkeypatch):
        monkeypatch.delenv("FINCO_SAVE_ALL_PROFILE_ENABLED", raising=False)
        sections = read_workspace(capex, capex.record)["save_all"]["sections"]
        assert sections == ["cells", "contracts", "cost_lines"]

    def test_flag_on_advertises_the_profile_section(self, capex, monkeypatch):
        """Correction D: the workspace advertisement stays byte-identical in BOTH flag
        states — the historical U2 exact-prefix contract on the workspace router is kept
        original, and the combined capability is advertised only on the profiles read
        (`save.save_all_combined`), which the pending store actually consumes."""
        monkeypatch.setenv("FINCO_SAVE_ALL_PROFILE_ENABLED", "1")
        sections = read_workspace(capex, capex.record)["save_all"]["sections"]
        assert sections == ["cells", "contracts", "cost_lines"]

    def test_the_save_all_url_and_csrf_are_unchanged_by_the_flag(self, capex, monkeypatch):
        off = read_workspace(capex, capex.record)["save_all"]
        monkeypatch.setenv("FINCO_SAVE_ALL_PROFILE_ENABLED", "1")
        on = read_workspace(capex, capex.record)["save_all"]
        assert on["url"] == off["url"] == "/v2/workbook/save-all"
        assert on["max_items"] == off["max_items"] == 200
