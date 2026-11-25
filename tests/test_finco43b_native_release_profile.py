"""FINCO43B — reviewed native release PROFILES (deploy-time only; nothing is activated by this test).

``full`` (default, unchanged accepted behaviour) = V10 Stage 1 + experimental Stage 2 + V11 Stage 3; ``stage3`` = V11
Stage 3 only, so an operator can release the measured-exact configuration WITHOUT the experimental Stage 2 and keep
Stage 2 a separate owner decision. Unknown profiles refuse; ``verify`` accepts only an exact reviewed profile text; the
activation is parsed through the real production settings readers.
"""
from __future__ import annotations

import pytest

from app.runtime import native_activation as na
from tests.test_native_v11_activation import _faithful_build, _release_sandbox


def _env_of(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))


def test_default_profile_is_the_unchanged_full_activation(monkeypatch):
    from tools import native_release as rel
    monkeypatch.delenv(rel.ENV_PROFILE, raising=False)
    assert rel._profile() == "full" and rel.activation_text() == rel.activation_text("full")
    env = _env_of(rel.activation_text())
    assert na.setting(env)[0] == "stage1+2" and na.v11_setting(env)[0] == "on"


def test_stage3_profile_is_v11_only_and_pinned(tmp_path):
    from tools import native_release as rel
    env = _env_of(rel.activation_text("stage3"))
    env.update({na.ENV_KILL_SWITCH: str(tmp_path / "k10"), na.ENV_V11_KILL_SWITCH: str(tmp_path / "k11")})
    assert na.setting(env) == ("off", "SETTING_OFF")
    assert na.v11_setting(env) == ("on", None)
    cfg = na.v11_run_config(env)
    assert cfg.require_build_id == rel._manifest(*rel.KERNELS[2][::2])["build_id"]
    assert na.run_config(env) is None and na.ENV_BUILD_ID not in env


@pytest.mark.parametrize("bad", ["stage1+2", "", "FULL ", "on", "stage2"])
def test_unknown_profile_refuses(bad, monkeypatch):
    from tools import native_release as rel
    if bad.strip().lower() in rel.PROFILES:
        assert rel._profile(bad) == bad.strip().lower()
        return
    with pytest.raises(ValueError, match="unknown native release profile"):
        rel._profile(bad)


def test_install_stage3_profile_writes_exactly_that_activation_and_verify_accepts_it(tmp_path, monkeypatch, capsys):
    rel = _release_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(rel, "_build", _faithful_build(rel))
    monkeypatch.setattr(rel, "verify", lambda: {"self_test": {"identical": True}})
    monkeypatch.setattr(rel, "unit_loads_activation", lambda: None)
    assert rel.install("stage3") == 0
    assert rel.ACTIVATION_FILE.read_text() == rel.activation_text("stage3")
    assert rel.installed_profile() == "stage3" and rel.check() == 0
    assert rel.check("stage3") == 0 and rel.check("full") == 1          # verify can assert the exact profile
    rel.ACTIVATION_FILE.write_text(rel.activation_text("stage3").replace("V10_RUN=off", "V10_RUN=stage1+2"))
    assert rel.installed_profile() is None and rel.check() == 1          # an edited activation is not verified
    monkeypatch.setenv(rel.ENV_PROFILE, "full")
    assert rel.install() == 0 and rel.installed_profile() == "full"     # env selection, default text unchanged


def test_install_with_unknown_env_profile_refuses_and_leaves_nothing(tmp_path, monkeypatch, capsys):
    rel = _release_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(rel, "_build", _faithful_build(rel))
    monkeypatch.setattr(rel, "verify", lambda: {"self_test": {"identical": True}})
    monkeypatch.setattr(rel, "unit_loads_activation", lambda: None)
    monkeypatch.setenv(rel.ENV_PROFILE, "everything")
    assert rel.install() == 1
    assert not rel.ACTIVATION_FILE.exists() and not any(p.exists() for p in rel._artifacts())


def test_release_script_passes_every_argument_through():
    """Review finding: `release_native.sh install --profile stage3` must not silently install `full`."""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy/scripts/release_native.sh").read_text()
    shim = script.replace('exec "$PYTHON_BIN" -m tools.native_release "$@"', 'printf "%s|" "$@"; exit 0')
    shim = shim.replace('if [[ ! -x "$PYTHON_BIN" ]]; then', 'if false; then')
    for args, expected in (([], "install|"), (["install", "--profile", "stage3"], "install|--profile|stage3|"),
                           (["verify"], "verify|")):
        out = subprocess.run(["bash", "-c", shim, "release_native.sh", *args], capture_output=True, text=True,
                             cwd=root / "deploy/scripts", check=True).stdout
        assert out == expected, (args, out)


def test_cli_profile_flag(monkeypatch):
    from tools import native_release as rel
    seen = {}
    monkeypatch.setattr(rel, "install", lambda profile=None: seen.setdefault("profile", profile) and 0)
    rel.main(["install", "--profile", "stage3"])
    assert seen["profile"] == "stage3"
    monkeypatch.setattr(rel, "check", lambda profile=None: seen.setdefault("verify", profile) and 0)
    rel.main(["verify", "--profile", "full"])
    assert seen["verify"] == "full"
    with pytest.raises(SystemExit):
        rel.main(["remove", "--profile", "stage3"])
    with pytest.raises(SystemExit):
        rel.main(["install", "--profile", "everything"])
