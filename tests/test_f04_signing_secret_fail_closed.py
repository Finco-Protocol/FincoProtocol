"""F04 — signing-secret fail-closed contract tests.

Every case exercises the actual startup configuration authority: a fresh
subprocess that imports ``app.auth`` with a controlled environment. Nothing
here inspects a helper in isolation — a startup that should fail closed must
actually fail, and one that should start must actually start.

All secret values in this file are obvious fake fixtures; none is a real
credential, and no test asserts against a real deployment secret.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Obvious fake fixtures — safe to commit.
VALID_SECRET_A = "f04-fake-fixture-3f9a1c7e5b2d4860a1e4c9b7d6f3e2a1c"
VALID_SECRET_B = "f04-fake-fixture-77b2d9e4a1c640f8b3e5d2a7c9f1b6d4"
VALID_OPERATOR_PASSPHRASE = "f04-fake-fixture-operator-passphrase-9c4e7a1b"
PLACEHOLDER_SECRET = "changeme_generate_a_real_secret_key_here"
DEV_FALLBACK_SECRET = "dev-secret-please-change-in-production"

_PROBE = "import app.auth; print('F04_STARTUP_OK')"


def _run_startup(finco_env: dict) -> subprocess.CompletedProcess:
    """Import app.auth in a fresh subprocess under a controlled FINCO_* env."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("FINCO_")}
    env.update(finco_env)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )


def _assert_started(proc: subprocess.CompletedProcess, context: str) -> None:
    assert proc.returncode == 0, (
        f"{context}: startup must succeed.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "F04_STARTUP_OK" in proc.stdout, (
        f"{context}: startup marker missing.\nstderr: {proc.stderr}"
    )


def _assert_failed(proc: subprocess.CompletedProcess, context: str, *needles: str) -> None:
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"{context}: startup must FAIL CLOSED, but it succeeded.\nstdout: {proc.stdout}"
    )
    assert "F04_STARTUP_OK" not in proc.stdout, (
        f"{context}: startup marker present despite expected failure."
    )
    for needle in needles:
        assert needle in combined, (
            f"{context}: failure output must name {needle!r}.\noutput: {combined}"
        )


def _assert_no_secret_values(proc: subprocess.CompletedProcess) -> None:
    combined = proc.stdout + proc.stderr
    for value in (VALID_SECRET_A, VALID_SECRET_B, VALID_OPERATOR_PASSPHRASE,
                  PLACEHOLDER_SECRET, DEV_FALLBACK_SECRET):
        assert value not in combined, (
            f"startup output must never echo a secret value (leaked: {value[:20]}...)"
        )


# ── pilot (the mode staging/production deploys actually use) ─────────────────


def test_pilot_missing_secret_fails_closed():
    proc = _run_startup({"FINCO_APP_MODE": "pilot"})
    _assert_failed(proc, "pilot + missing secret", "FINCO_SECRET_KEY")
    _assert_no_secret_values(proc)


def test_pilot_placeholder_secret_fails_closed():
    proc = _run_startup({
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": PLACEHOLDER_SECRET,
    })
    _assert_failed(proc, "pilot + placeholder secret", "placeholder")
    _assert_no_secret_values(proc)


def test_pilot_dev_fallback_value_as_explicit_secret_fails_closed():
    proc = _run_startup({
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": DEV_FALLBACK_SECRET,
    })
    _assert_failed(proc, "pilot + dev fallback value", "placeholder")
    _assert_no_secret_values(proc)


def test_pilot_valid_secret_starts():
    # pilot mode also enforces the pre-existing admin-password contract, so a
    # (fake) operator credential is configured to isolate the secret behavior.
    proc = _run_startup({
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": VALID_SECRET_A,
        "FINCO_ADMIN_PASSWORD": VALID_OPERATOR_PASSPHRASE,
    })
    _assert_started(proc, "pilot + valid secret")
    _assert_no_secret_values(proc)


def test_pilot_placeholder_csrf_secret_fails_closed():
    proc = _run_startup({
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": VALID_SECRET_A,
        "FINCO_ADMIN_PASSWORD": VALID_OPERATOR_PASSPHRASE,
        "FINCO_CSRF_SECRET": PLACEHOLDER_SECRET,
    })
    _assert_failed(proc, "pilot + placeholder CSRF secret", "FINCO_CSRF_SECRET")
    _assert_no_secret_values(proc)


def test_pilot_valid_csrf_secret_starts():
    proc = _run_startup({
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": VALID_SECRET_A,
        "FINCO_ADMIN_PASSWORD": VALID_OPERATOR_PASSPHRASE,
        "FINCO_CSRF_SECRET": VALID_SECRET_B,
    })
    _assert_started(proc, "pilot + valid CSRF secret")
    _assert_no_secret_values(proc)


# ── unrecognized deployment modes must not inherit development semantics ─────


def test_unrecognized_mode_missing_secret_fails_closed():
    # "production" is not a value this app recognizes — it must still fail closed.
    proc = _run_startup({"FINCO_APP_MODE": "production"})
    _assert_failed(proc, "unrecognized mode + missing secret", "FINCO_SECRET_KEY")
    _assert_no_secret_values(proc)


def test_unrecognized_mode_missing_secret_does_not_take_dev_path():
    proc = _run_startup({"FINCO_APP_MODE": "prod"})
    _assert_failed(proc, "unrecognized mode + missing secret (prod)", "FINCO_SECRET_KEY")
    _assert_no_secret_values(proc)


def test_unrecognized_mode_with_valid_secret_starts():
    proc = _run_startup({
        "FINCO_APP_MODE": "production",
        "FINCO_SECRET_KEY": VALID_SECRET_A,
    })
    _assert_started(proc, "unrecognized mode + valid secret")
    _assert_no_secret_values(proc)


# ── explicit development / internal modes keep the documented dev workflow ────


def test_development_missing_secret_starts_with_warning():
    proc = _run_startup({"FINCO_APP_MODE": "development"})
    _assert_started(proc, "development + missing secret")
    combined = proc.stdout + proc.stderr
    assert "WARNING" in combined and "FINCO_SECRET_KEY" in combined
    _assert_no_secret_values(proc)


def test_mode_unset_defaults_to_development_workflow():
    proc = _run_startup({})
    _assert_started(proc, "mode unset + missing secret")
    combined = proc.stdout + proc.stderr
    assert "WARNING" in combined, "unset mode still must warn about the dev fallback"
    _assert_no_secret_values(proc)


def test_development_placeholder_secret_starts_with_warning():
    proc = _run_startup({
        "FINCO_APP_MODE": "development",
        "FINCO_SECRET_KEY": PLACEHOLDER_SECRET,
    })
    _assert_started(proc, "development + placeholder secret")
    _assert_no_secret_values(proc)


def test_internal_missing_secret_starts_with_warning():
    # 'internal' is a documented dev-grade mode; placeholder use must at least warn.
    proc = _run_startup({"FINCO_APP_MODE": "internal"})
    _assert_started(proc, "internal + missing secret")
    combined = proc.stdout + proc.stderr
    assert "WARNING" in combined and "FINCO_SECRET_KEY" in combined
    _assert_no_secret_values(proc)


def test_development_valid_secret_starts_clean():
    proc = _run_startup({
        "FINCO_APP_MODE": "development",
        "FINCO_SECRET_KEY": VALID_SECRET_A,
    })
    _assert_started(proc, "development + valid secret")
    _assert_no_secret_values(proc)


# ── deploy/staging.env.example-shaped configuration must fail closed ─────────


def test_staging_env_example_placeholder_pair_fails_closed():
    # Mirrors deploy/staging.env.example defaults (pilot + changeme secret).
    proc = _run_startup({
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": "changeme_generate_a_separate_staging_secret_key_here",
    })
    _assert_failed(proc, "staging example config", "placeholder")
    _assert_no_secret_values(proc)
