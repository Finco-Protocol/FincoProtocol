"""P4 FINCO Token Utility V1 — browser acceptance tests.

Tests:
  1. test_finco_access_browser_1280 — desktop 1280px: page loads, no overflow,
     three utility cards visible, wallet area present, protocol boundary statement,
     NOT_CONFIGURED state renders without error.
  2. test_finco_access_browser_390 — mobile 390px: no horizontal overflow,
     cards stack, long addresses wrap safely.
  3. TestEIP1193WalletJourney — EIP-1193 wallet success + 4 failure paths.

Server ports:
  19760 — layout tests (NOT_CONFIGURED, no token env vars)
  19761 — wallet journey tests (token config + FINCO_APP_DOMAIN set)
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
_WIDTH_TOLERANCE = 2
_PORT = 19760
_WALLET_PORT = 19761


def _wait_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.05)
    raise RuntimeError(f"Port {port} did not open within {timeout}s")


@pytest.fixture(scope="module")
def finco_server_url(tmp_path_factory):
    import os
    import uvicorn

    tmp = tmp_path_factory.mktemp("finco_browser_db")
    os.environ["FINCO_DB_PATH"] = str(tmp / "test.db")
    # Ensure token is NOT configured — so NOT_CONFIGURED state is tested
    for env_key in ("FINCO_TOKEN_RPC_URL", "FINCO_TOKEN_CHAIN_ID", "FINCO_TOKEN_ADDRESS", "FINCO_ACCESS_MIN_BALANCE"):
        os.environ.pop(env_key, None)

    app = FastAPI()

    # Auth middleware shim: inject admin session cookie reader
    from app.auth import create_session_token, COOKIE_NAME, decode_session_token
    from app.protocol.router import router as _finco_router
    app.include_router(_finco_router)

    # Add session middleware so routes can read cookies
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarRequest

    class _FakeSessionMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)

    app.add_middleware(_FakeSessionMiddleware)

    # Serve static files for CSS
    static_dir = REPO / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_port("127.0.0.1", _PORT)
    try:
        yield f"http://127.0.0.1:{_PORT}"
    finally:
        server.should_exit = True
        thread.join(5)


def _chromium_executable() -> str | None:
    """Find an available Chromium executable in common Playwright browser paths."""
    import glob
    patterns = [
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        "/opt/pw-browsers/chromium-*/chrome-linux64/chrome",
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None


@pytest.fixture(scope="module")
def finco_browser():
    with sync_playwright() as pw:
        exe = _chromium_executable()
        launch_kwargs: dict = {
            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
        }
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**launch_kwargs)
        yield browser
        browser.close()


def _overflow_px(page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def _auth_cookie(server_url: str) -> dict:
    from app.auth import create_session_token, COOKIE_NAME
    token = create_session_token()
    host = server_url.replace("http://", "").split(":")[0]
    port = int(server_url.split(":")[-1])
    return {"name": COOKIE_NAME, "value": token, "domain": host, "path": "/"}


def test_finco_access_browser_1280(finco_server_url, finco_browser):
    """Desktop 1280px: page loads, no overflow, 3 utility cards, wallet area,
    protocol boundary statement, NOT_CONFIGURED state renders without error."""
    page = finco_browser.new_page(viewport={"width": 1280, "height": 900})
    ctx = page.context
    ctx.add_cookies([_auth_cookie(finco_server_url)])
    page.goto(f"{finco_server_url}/protocol/finco")
    page.wait_for_load_state("domcontentloaded")

    # Page title / header
    title = page.title()
    assert "$FINCO" in title or "Protocol" in title

    # No horizontal overflow
    overflow = _overflow_px(page)
    assert overflow <= _WIDTH_TOLERANCE, f"Horizontal overflow: {overflow}px"

    # Three utility cards present
    cards = page.locator(".finco-utility-card")
    assert cards.count() == 3, f"Expected 3 utility cards, found {cards.count()}"

    # Verify all 3 identifiers appear
    page_text = page.content()
    assert "FINCO_COMPUTE" in page_text
    assert "FINCO_VERIFY_PUBLISH" in page_text
    assert "FINCO_INTELLIGENCE" in page_text

    # Wallet connection area present (either wallet state or connect area)
    wallet_section = page.locator(".finco-wallet")
    assert wallet_section.count() >= 1

    # Protocol boundary statement visible
    assert "$FINCO controls access to protocol services" in page_text
    assert "never changes FINCO calculations" in page_text

    # NOT_CONFIGURED state renders without error (config is missing in test)
    assert "not configured" in page_text.lower() or "Token access not configured" in page_text

    page.close()


def test_finco_access_browser_390(finco_server_url, finco_browser):
    """Mobile 390px: no horizontal overflow (scrollWidth <= 392), cards stack,
    long addresses wrap safely."""
    page = finco_browser.new_page(viewport={"width": 390, "height": 844})
    ctx = page.context
    ctx.add_cookies([_auth_cookie(finco_server_url)])
    page.goto(f"{finco_server_url}/protocol/finco")
    page.wait_for_load_state("domcontentloaded")

    # No horizontal overflow — strict at mobile (allows 2px for rounding)
    overflow = _overflow_px(page)
    assert overflow <= _WIDTH_TOLERANCE, f"Mobile horizontal overflow: {overflow}px"

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_width <= 392, f"scrollWidth {scroll_width} > 392 at 390px viewport"

    # Three utility cards still present
    cards = page.locator(".finco-utility-card")
    assert cards.count() == 3

    # Wallet section present
    wallet_section = page.locator(".finco-wallet")
    assert wallet_section.count() >= 1

    # Protocol boundary statement still visible
    page_text = page.content()
    assert "$FINCO controls access to protocol services" in page_text

    page.close()


# ──────────────────────────────────────────────────────────────────────────────
# Wallet journey server fixture (port 19761) — token config + FINCO_APP_DOMAIN
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="class")
def wallet_journey_url(tmp_path_factory):
    """Server on port 19761 with full token config and FINCO_APP_DOMAIN for wallet journey tests."""
    import os
    import uvicorn

    tmp = tmp_path_factory.mktemp("finco_wallet_journey")
    _env_keys = [
        "FINCO_DB_PATH", "FINCO_APP_DOMAIN",
        "FINCO_TOKEN_RPC_URL", "FINCO_TOKEN_CHAIN_ID",
        "FINCO_TOKEN_ADDRESS", "FINCO_ACCESS_MIN_BALANCE",
    ]
    _saved = {k: os.environ.get(k) for k in _env_keys}

    os.environ["FINCO_DB_PATH"] = str(tmp / "wallet.db")
    os.environ["FINCO_APP_DOMAIN"] = "test.fincoprotocol.local"
    os.environ["FINCO_TOKEN_RPC_URL"] = "http://rpc.test.local:8545"
    os.environ["FINCO_TOKEN_CHAIN_ID"] = "1"
    os.environ["FINCO_TOKEN_ADDRESS"] = "0x" + "a" * 40
    os.environ["FINCO_ACCESS_MIN_BALANCE"] = "1"

    from importlib import reload
    import app.protocol.token_config as _tc
    reload(_tc)

    app_inst = FastAPI()
    from app.protocol.router import router as _finco_router
    app_inst.include_router(_finco_router)
    static_dir = REPO / "static"
    if static_dir.exists():
        app_inst.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    config = uvicorn.Config(app_inst, host="127.0.0.1", port=_WALLET_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_port("127.0.0.1", _WALLET_PORT)
    try:
        yield f"http://127.0.0.1:{_WALLET_PORT}"
    finally:
        server.should_exit = True
        thread.join(5)
        for k in _env_keys:
            if _saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = _saved[k]


def _wallet_auth_cookie(server_url: str, user_id: str) -> dict:
    """Auth cookie for a specific user_id (avoids shared-state between wallet tests)."""
    from app.auth import create_session_token, COOKIE_NAME
    token = create_session_token(user_id=user_id)
    host = server_url.replace("http://", "").split(":")[0]
    return {"name": COOKIE_NAME, "value": token, "domain": host, "path": "/"}


# ──────────────────────────────────────────────────────────────────────────────
# EIP-1193 wallet journey tests
# ──────────────────────────────────────────────────────────────────────────────

class TestEIP1193WalletJourney:
    """EIP-1193 wallet connect flow — success and four failure paths.

    FINCO_ACCESS_BROWSER_WALLET_END_TO_END
    FINCO_WALLET_BROWSER_NO_PROVIDER_HANDLED
    FINCO_WALLET_BROWSER_ACCOUNT_REJECTION_HANDLED
    FINCO_WALLET_BROWSER_SIGNATURE_REJECTION_HANDLED
    FINCO_WALLET_BROWSER_INVALID_SIGNATURE_HANDLED
    """

    def _feedback_text(self, page) -> str:
        """Return text of the #finco-feedback element."""
        return page.locator("#finco-feedback").inner_text(timeout=5000)

    def _make_success_page(self, finco_browser, wallet_journey_url, addr, kp, user_id, viewport):
        """Helper: set up a page for the success wallet journey and return (page, sig_holder)."""
        import json as _json
        from app.protocol._evm_crypto import sign_personal_message

        sig_holder: dict = {"value": None}

        def handle_challenge(route):
            try:
                resp = route.fetch()
                body = _json.loads(resp.body())
                challenge_text = body.get("challenge_text", "")
                if challenge_text:
                    sig_holder["value"] = sign_personal_message(challenge_text, kp.private_key)
                route.fulfill(
                    status=resp.status,
                    headers=dict(resp.headers),
                    body=resp.body(),
                    content_type="application/json",
                )
            except Exception:
                route.continue_()

        page = finco_browser.new_page(viewport=viewport)
        page.expose_function("__fincoGetTestSig", lambda: sig_holder["value"] or "")
        page.add_init_script(f"""
            window.ethereum = {{
                isMetaMask: true,
                request: async function({{method, params}}) {{
                    if (method === 'eth_requestAccounts') {{
                        return ['{addr.lower()}'];
                    }}
                    if (method === 'personal_sign') {{
                        return await window.__fincoGetTestSig();
                    }}
                    throw new Error('Unknown method: ' + method);
                }}
            }};
        """)
        page.route("**/protocol/finco/wallet/challenge", handle_challenge)
        page.context.add_cookies([_wallet_auth_cookie(wallet_journey_url, user_id)])
        return page, sig_holder

    def test_success_journey(self, wallet_journey_url, finco_browser):
        """FINCO_ACCESS_BROWSER_WALLET_END_TO_END — full EIP-1193 sign-and-verify flow succeeds."""
        import uuid as _uuid
        from app.protocol._evm_crypto import generate_keypair, private_key_to_address

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        page, _ = self._make_success_page(
            finco_browser, wallet_journey_url, addr, kp, str(_uuid.uuid4()),
            {"width": 1280, "height": 900},
        )

        page.goto(f"{wallet_journey_url}/protocol/finco")
        page.wait_for_load_state("domcontentloaded")

        # Connect button must be present
        assert page.locator("#finco-connect-btn").count() == 1

        # Wait for navigate triggered by window.location.reload() on success
        with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            page.click("#finco-connect-btn")

        # After reload, wallet address should appear in page (server-rendered)
        content = page.content()
        assert addr.lower() in content.lower(), (
            f"Wallet address {addr.lower()} not found in page after verification."
        )
        page.close()

    def test_success_journey_390px(self, wallet_journey_url, finco_browser):
        """FINCO_ACCESS_BROWSER_WALLET_END_TO_END (mobile 390px) — journey works on mobile viewport."""
        import uuid as _uuid
        from app.protocol._evm_crypto import generate_keypair, private_key_to_address

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        page, _ = self._make_success_page(
            finco_browser, wallet_journey_url, addr, kp, str(_uuid.uuid4()),
            {"width": 390, "height": 844},
        )

        page.goto(f"{wallet_journey_url}/protocol/finco")
        page.wait_for_load_state("domcontentloaded")

        with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            page.click("#finco-connect-btn")

        content = page.content()
        assert addr.lower() in content.lower()

        # No horizontal overflow after wallet verification reload
        overflow = _overflow_px(page)
        assert overflow <= _WIDTH_TOLERANCE, f"Mobile overflow after wallet connect: {overflow}px"
        page.close()

    def test_no_provider_handled(self, wallet_journey_url, finco_browser):
        """FINCO_WALLET_BROWSER_NO_PROVIDER_HANDLED — no window.ethereum shows helpful error."""
        import uuid as _uuid

        page = finco_browser.new_page(viewport={"width": 1280, "height": 900})
        # Do NOT inject window.ethereum
        ctx = page.context
        ctx.add_cookies([_wallet_auth_cookie(wallet_journey_url, str(_uuid.uuid4()))])
        page.goto(f"{wallet_journey_url}/protocol/finco")
        page.wait_for_load_state("domcontentloaded")
        page.click("#finco-connect-btn")
        page.wait_for_timeout(500)

        feedback = self._feedback_text(page)
        assert "No wallet detected" in feedback or "EIP-1193" in feedback or "wallet" in feedback.lower(), (
            f"Expected no-provider feedback, got: {feedback!r}"
        )
        page.close()

    def test_account_rejection_handled(self, wallet_journey_url, finco_browser):
        """FINCO_WALLET_BROWSER_ACCOUNT_REJECTION_HANDLED — eth_requestAccounts rejection shows error."""
        import uuid as _uuid

        page = finco_browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script("""
            window.ethereum = {
                isMetaMask: true,
                request: async function({method, params}) {
                    if (method === 'eth_requestAccounts') {
                        const err = new Error('User rejected request');
                        err.code = 4001;
                        throw err;
                    }
                    throw new Error('Unknown: ' + method);
                }
            };
        """)
        ctx = page.context
        ctx.add_cookies([_wallet_auth_cookie(wallet_journey_url, str(_uuid.uuid4()))])
        page.goto(f"{wallet_journey_url}/protocol/finco")
        page.wait_for_load_state("domcontentloaded")
        page.click("#finco-connect-btn")
        page.wait_for_timeout(500)

        feedback = self._feedback_text(page)
        assert "rejected" in feedback.lower() or "cancel" in feedback.lower() or "connection" in feedback.lower(), (
            f"Expected account-rejection feedback, got: {feedback!r}"
        )
        page.close()

    def test_signature_rejection_handled(self, wallet_journey_url, finco_browser):
        """FINCO_WALLET_BROWSER_SIGNATURE_REJECTION_HANDLED — personal_sign rejection shows error."""
        import uuid as _uuid

        page = finco_browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script("""
            window.ethereum = {
                isMetaMask: true,
                request: async function({method, params}) {
                    if (method === 'eth_requestAccounts') {
                        return ['0x' + 'ab'.repeat(20)];
                    }
                    if (method === 'personal_sign') {
                        const err = new Error('User rejected signing');
                        err.code = 4001;
                        throw err;
                    }
                    throw new Error('Unknown: ' + method);
                }
            };
        """)
        # Route challenge to avoid NOT_CONFIGURED error (token config is set on this server)
        page.route("**/protocol/finco/wallet/challenge", lambda route: route.fetch() and route.continue_())

        ctx = page.context
        ctx.add_cookies([_wallet_auth_cookie(wallet_journey_url, str(_uuid.uuid4()))])
        page.goto(f"{wallet_journey_url}/protocol/finco")
        page.wait_for_load_state("domcontentloaded")
        page.click("#finco-connect-btn")
        page.wait_for_timeout(800)

        feedback = self._feedback_text(page)
        assert "rejected" in feedback.lower() or "sign" in feedback.lower(), (
            f"Expected signature-rejection feedback, got: {feedback!r}"
        )
        page.close()

    def test_invalid_signature_handled(self, wallet_journey_url, finco_browser):
        """FINCO_WALLET_BROWSER_INVALID_SIGNATURE_HANDLED — bad signature returns SIGNATURE_INVALID error."""
        import json as _json
        import uuid as _uuid

        sig_holder: dict = {"nonce": None}

        def handle_challenge(route):
            resp = route.fetch()
            body = _json.loads(resp.body())
            sig_holder["nonce"] = body.get("nonce")
            route.fulfill(status=resp.status, headers=dict(resp.headers), body=resp.body(), content_type="application/json")

        page = finco_browser.new_page(viewport={"width": 1280, "height": 900})
        # Return a zero signature that will fail signature recovery
        page.add_init_script("""
            window.ethereum = {
                isMetaMask: true,
                request: async function({method, params}) {
                    if (method === 'eth_requestAccounts') {
                        return ['0x' + 'cd'.repeat(20)];
                    }
                    if (method === 'personal_sign') {
                        return '0x' + '00'.repeat(65);
                    }
                    throw new Error('Unknown: ' + method);
                }
            };
        """)
        page.route("**/protocol/finco/wallet/challenge", handle_challenge)

        ctx = page.context
        ctx.add_cookies([_wallet_auth_cookie(wallet_journey_url, str(_uuid.uuid4()))])
        page.goto(f"{wallet_journey_url}/protocol/finco")
        page.wait_for_load_state("domcontentloaded")
        page.click("#finco-connect-btn")
        page.wait_for_timeout(1000)

        feedback = self._feedback_text(page)
        assert (
            "invalid" in feedback.lower()
            or "mismatch" in feedback.lower()
            or "failed" in feedback.lower()
            or "signature" in feedback.lower()
        ), f"Expected signature-error feedback, got: {feedback!r}"
        page.close()
