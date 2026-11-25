"""FINCO45C (C3-E-11): ``deploy/scripts/smoke_test.sh`` checks the ACTUAL deployed route contract.

FINCO43C reported that the old script expected ``/`` and ``/health`` to answer 302, while the real app answers ``/`` with
200 + a provisioned demo session and ``/health`` with 401 JSON for anonymous callers. These tests run the script against
a real local uvicorn (synthetic temp DB, throwaway secrets, no VPS) and against a stub that violates the contract, so
the script can neither drift from the routes nor accept arbitrary statuses.
"""
from __future__ import annotations

import http.server
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "scripts" / "smoke_test.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("curl") is None,
                                reason="bash and curl are required to execute the deploy smoke script")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(base: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "FINCO_SMOKE_SESSION_COOKIE"}
    env.update(extra_env or {})
    return subprocess.run(["bash", str(SCRIPT), base], capture_output=True, text=True, timeout=120, env=env)


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("smoke")
    port = _free_port()
    env = dict(os.environ, FINCO_DB_PATH=str(tmp / "finco.db"), FINCO_SECRET_KEY=secrets.token_hex(32),
               FINCO_ADMIN_USER="smoke-admin", FINCO_ADMIN_PASSWORD=secrets.token_hex(16), FINCO_COOKIE_SECURE="false")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main_web:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("uvicorn did not start")
        yield base, env
    finally:
        proc.terminate()
        proc.wait(30)


def test_smoke_script_passes_against_real_app(live_server):
    base, _env = live_server
    out = _run(base)
    assert out.returncode == 0, out.stdout + out.stderr
    for line in ("/public-health → 200", "/readyz → 200", "/health → 401 unauthenticated", "/login → 200",
                 "/ → 200 with a provisioned demo session", "security headers present"):
        assert line in out.stdout


def test_authenticated_health_is_checked_without_printing_the_cookie(live_server):
    base, env = live_server
    code = ("import os; os.environ.update(" + repr({k: env[k] for k in ("FINCO_SECRET_KEY", "FINCO_ADMIN_USER")}) +
            "); from app.auth import create_session_token; print(create_session_token())")
    token = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                           env=env).stdout.strip()
    good = _run(base, {"FINCO_SMOKE_SESSION_COOKIE": token})
    assert good.returncode == 0 and "/health (authenticated) → 200 ok" in good.stdout
    assert token not in good.stdout and token not in good.stderr
    bad = _run(base, {"FINCO_SMOKE_SESSION_COOKIE": "not-a-session"})
    assert bad.returncode == 1 and "/health (authenticated) returned 401" in bad.stdout


class _Redirecting(http.server.BaseHTTPRequestHandler):
    """The OLD assumed contract (everything redirects to /login, /health public-ish) must now FAIL the script."""

    def do_GET(self):  # noqa: N802
        if self.path == "/public-health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/health":
            self.send_response(200)                 # a public private-health endpoint is a contract violation
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_smoke_script_rejects_a_server_violating_the_contract():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redirecting)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        out = _run(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
    assert out.returncode == 1
    assert "security headers missing" in out.stdout
    assert "/health returned 200 (expected 401 unauthenticated)" in out.stdout
    assert "/ returned 302" in out.stdout and "/readyz returned 302" in out.stdout


def test_smoke_script_fails_closed_when_unreachable():
    out = _run(f"http://127.0.0.1:{_free_port()}")
    assert out.returncode == 1 and "returned 000" in out.stdout
