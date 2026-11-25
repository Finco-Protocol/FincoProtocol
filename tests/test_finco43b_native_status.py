"""FINCO43B — operator readiness CLI ``tools/native_status.py`` distinguishes OFF / KILLED / INVALID_CONFIG / ENABLED /
ENABLED_LOADER_UNAVAILABLE / ENABLED_BUILD_PIN_MISMATCH from the same settings readers the web service uses."""
from __future__ import annotations

import pytest

from app.runtime import native_activation as na


def _env(tmp_path, **values):
    env = {na.ENV_KILL_SWITCH: str(tmp_path / "k10"), na.ENV_V11_KILL_SWITCH: str(tmp_path / "k11")}
    env.update(values)
    return env


def test_off_by_default(tmp_path):
    from tools.native_status import status
    out = status(_env(tmp_path))
    assert out["status"] == "OFF" and out["needed_kernels"] == []
    assert out["v10"]["reason"] == "SETTING_OFF" and out["v11"]["reason"] == "SETTING_OFF"


def test_invalid_setting_is_reported_and_fails_closed(tmp_path):
    from tools.native_status import status
    out = status(_env(tmp_path, **{na.ENV_V11_RUN: "yes"}))
    assert out["status"] == "INVALID_CONFIG" and out["v11"]["mode"] == "off"


def test_kill_switch_reported_as_killed(tmp_path):
    from tools.native_status import status
    (tmp_path / "k10").write_text("")
    out = status(_env(tmp_path, **{na.ENV_RUN: "stage1", na.ENV_V11_RUN: "on"}))
    assert out["status"] == "KILLED" and out["needed_kernels"] == []


def test_enabled_without_loadable_kernels_is_actionable(tmp_path, monkeypatch):
    from financial_engine.native_v11 import stage3
    from tools.native_status import status
    monkeypatch.setattr(stage3, "get_stage3", lambda *a, **k: (None, "LOADER_ARTIFACT_UNAVAILABLE:FileNotFoundError"))
    out = status(_env(tmp_path, **{na.ENV_V11_RUN: "on"}))
    assert out["status"] == "ENABLED_LOADER_UNAVAILABLE" and out["needed_kernels"] == ["stage3"]


@pytest.mark.usefixtures("stage3_artifacts")
def test_enabled_with_verified_kernels_and_pins(tmp_path):
    from tools import native_release as rel
    from tools.native_status import status
    s3 = rel._manifest(*rel.KERNELS[2][::2])["build_id"]
    out = status(_env(tmp_path, **{na.ENV_V11_RUN: "on", na.ENV_V11_BUILD_ID: s3}))
    assert out["status"] == "ENABLED" and out["kernels"]["stage3"]["matches_committed"] is True
    out = status(_env(tmp_path, **{na.ENV_V11_RUN: "on", na.ENV_V11_BUILD_ID: "0" * 64}))
    assert out["status"] == "ENABLED_BUILD_PIN_MISMATCH"
    out = status(_env(tmp_path, **{na.ENV_RUN: "stage1+2", na.ENV_V11_RUN: "on"}))
    assert out["status"] == "ENABLED" and out["needed_kernels"] == ["stage1", "stage2", "stage3"]
