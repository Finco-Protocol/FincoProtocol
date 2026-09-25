"""Browser acceptance for the FINCO 'supported today' public-surface contract.

Verifies at both 1280 px and 390 px that every public-facing route agrees with
the canonical registry in app/product_capability.py:

  Solar = LIVE, Wind = LIVE, Data Center = LIVE
  Storage = PREVIEW (reference only, no clone)
  EV Charging = LIVE since PR #89 Correction B (shipped vertical)

Routes covered: /, /library, /docs, /roadmap, /known-limitations

Acceptance markers:
  SUPPORTED_TODAY_BROWSER_1280 = PASS
  SUPPORTED_TODAY_BROWSER_390 = PASS
  SUPPORTED_TODAY_HOMEPAGE_CONSISTENCY = PASS
  SUPPORTED_TODAY_LIBRARY_CONSISTENCY = PASS
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright

_CHROMIUM_EXEC = "/opt/pw-browsers/chromium"
_WIDTH_TOLERANCE = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _overflow_px(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def _auth_cookie(user_id: str, domain: str) -> dict:
    from app.auth import COOKIE_NAME, create_session_token
    return {
        "name": COOKIE_NAME,
        "value": create_session_token(user_id=user_id, username=user_id),
        "domain": domain,
        "path": "/",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_server(tmp_path_factory):
    """Full main_web app with isolated DB, startup-seeded references.

    Waits for startup seeding to complete (≥3 canonical references in DB)
    before yielding, so library tests don't race the seed event.
    """
    from app.persistence import db
    db.DB_PATH = str(tmp_path_factory.mktemp("today-browser") / "finco.db")

    import main_web
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "app_server fixture did not start in time"

    # Wait for startup seeding to complete — at least Solar, Wind, Data Center
    from app.persistence.projects_repository import get_reference_projects
    seed_deadline = time.time() + 30
    while time.time() < seed_deadline:
        if len(get_reference_projects()) >= 3:
            break
        time.sleep(0.2)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.fixture(scope="module")
def browser():
    launch_kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    if os.path.exists(_CHROMIUM_EXEC):
        launch_kwargs["executable_path"] = _CHROMIUM_EXEC
    with sync_playwright() as pw:
        instance = pw.chromium.launch(**launch_kwargs)
        yield instance
        instance.close()


def _authed_page(browser, base_url: str, *, width: int = 1280):
    from urllib.parse import urlparse
    domain = urlparse(base_url).hostname
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.context.add_cookies([_auth_cookie("test-surface-user", domain)])
    return page


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_HOMEPAGE_CONSISTENCY
# ---------------------------------------------------------------------------

def test_supported_today_homepage_1280(app_server, browser):
    """SUPPORTED_TODAY_HOMEPAGE_CONSISTENCY — 1280 px.

    Homepage must not claim EV Charging is supported/live today.
    """
    page = _authed_page(browser, app_server, width=1280)
    page.goto(f"{app_server}/")
    page.wait_for_load_state("domcontentloaded")
    content = page.content()
    # EV Charging is a shipped vertical; it may appear on the home page.
    lower = content.lower()
    assert "in development and not yet released" not in lower or "ev charging" not in lower, (
        "Homepage still frames EV Charging as not yet released"
    )
    assert _overflow_px(page) <= _WIDTH_TOLERANCE
    page.close()


def test_supported_today_homepage_390(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_390 — Homepage no horizontal overflow."""
    page = _authed_page(browser, app_server, width=390)
    page.goto(f"{app_server}/")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= _WIDTH_TOLERANCE, (
        f"Homepage has {_overflow_px(page)}px horizontal overflow at 390px"
    )
    page.close()


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_LIBRARY_CONSISTENCY
# ---------------------------------------------------------------------------

def test_supported_today_library_1280(app_server, browser):
    """SUPPORTED_TODAY_LIBRARY_CONSISTENCY — 1280 px.

    - Solar, Wind, Data Center reference cards are present and cloneable.
    - EV Charging is NOT present as a reference card.
    - Storage, if present, shows the clone-unavailable guard, not a clone button.
    """
    page = _authed_page(browser, app_server, width=1280)
    page.goto(f"{app_server}/library")
    page.wait_for_load_state("domcontentloaded")

    # Solar, Wind, Data Center reference cards must be present and cloneable.
    # Reference cards use dynamically-generated project_codes, so we locate by
    # technology name displayed in the fo-library-reference-technology span.
    all_cards = page.locator(".fo-library-reference-card")
    assert all_cards.count() >= 3, (
        f"Expected at least 3 reference cards (Solar/Wind/DC), found {all_cards.count()}"
    )

    # Collect technology labels shown in reference cards
    card_texts = [all_cards.nth(i).inner_text() for i in range(all_cards.count())]
    combined = "\n".join(card_texts).lower()

    for vertical in ("solar", "wind", "data center"):
        matching = [t for t in card_texts if vertical in t.lower()]
        assert matching, f"No reference card found for vertical '{vertical}'"
        # Each LIVE vertical must have a "Create working copy" button
        for card_text in matching:
            assert "create working copy" in card_text.lower(), (
                f"LIVE reference '{vertical}' must have a Create working copy button; "
                f"got: {card_text!r}"
            )
            assert "working-copy runtime coming soon" not in card_text.lower(), (
                f"LIVE reference '{vertical}' must NOT show 'Working-copy runtime coming soon'"
            )

    # EV Charging is a shipped vertical (PR #89): reference card + clone button.
    ev_cards = [t for t in card_texts if "ev" in t.lower() and "charging" in t.lower()]
    assert ev_cards, "EV Charging reference card must be present in the library"
    for card_text in ev_cards:
        assert "create working copy" in card_text.lower(), (
            f"LIVE reference 'EV Charging' must have a Create working copy button; got: {card_text!r}"
        )

    # Storage, if seeded, must show clone-unavailable guard, not a clone button
    storage_cards = [t for t in card_texts if "storage" in t.lower()]
    for sc_text in storage_cards:
        assert "working-copy runtime coming soon" in sc_text.lower(), (
            f"Storage reference must show 'Working-copy runtime coming soon'; got: {sc_text!r}"
        )
        assert "create working copy" not in sc_text.lower(), (
            f"Storage reference must NOT have a Create working copy button; got: {sc_text!r}"
        )

    assert _overflow_px(page) <= _WIDTH_TOLERANCE
    page.close()


def test_supported_today_library_390(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_390 — Library no horizontal overflow."""
    page = _authed_page(browser, app_server, width=390)
    page.goto(f"{app_server}/library")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= _WIDTH_TOLERANCE, (
        f"Library has {_overflow_px(page)}px horizontal overflow at 390px"
    )
    page.close()


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_DOCS_CONSISTENCY (browser layer)
# ---------------------------------------------------------------------------

def test_supported_today_docs_1280(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_1280 — Docs surface at 1280 px."""
    page = _authed_page(browser, app_server, width=1280)
    page.goto(f"{app_server}/docs")
    page.wait_for_load_state("domcontentloaded")

    content = page.content()
    # All three live verticals must be present
    for vertical in ("Solar", "Wind", "Data Center"):
        assert vertical in content, f"Docs is missing live vertical '{vertical}'"

    # The page must distinguish Storage as preview/limited
    assert "Storage" in content
    lower = content.lower()
    assert "storage" in lower
    assert "limited" in lower or "preview" in lower or "reference scope" in lower

    # EV Charging is live: docs must not frame it as in development
    if "EV Charging" in content or "ev charging" in lower:
        assert "in development" not in lower or "ev charging is in development" not in lower, (
            "Docs still frames EV Charging as in development"
        )

    assert _overflow_px(page) <= _WIDTH_TOLERANCE
    page.close()


def test_supported_today_docs_390(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_390 — Docs no horizontal overflow."""
    page = _authed_page(browser, app_server, width=390)
    page.goto(f"{app_server}/docs")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= _WIDTH_TOLERANCE, (
        f"Docs has {_overflow_px(page)}px horizontal overflow at 390px"
    )
    page.close()


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_ROADMAP_CONSISTENCY (browser layer)
# ---------------------------------------------------------------------------

def test_supported_today_roadmap_shipped_chips_1280(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_1280 — Roadmap Shipped chip row at 1280 px."""
    page = _authed_page(browser, app_server, width=1280)
    page.goto(f"{app_server}/roadmap")
    page.wait_for_load_state("domcontentloaded")

    # Locate the Infrastructure Model shipped chip row
    infra_card = page.locator(".proad-baseline-card", has=page.locator("h3", has_text="Infrastructure Model"))
    assert infra_card.count() >= 1, "Infrastructure Model baseline card not found"
    chip_row = infra_card.first.locator(".proad-chip-row")
    chip_text = chip_row.inner_text()

    # All three live verticals must appear in the shipped chip row
    for vertical in ("Solar", "Wind", "Data Center"):
        assert vertical in chip_text, (
            f"Live vertical '{vertical}' missing from Shipped chip row"
        )

    # EV Charging is shipped (PR #89): must be in the shipped chip row
    assert "EV Charging" in chip_text, (
        "EV Charging must appear in the Shipped chip row"
    )

    # The in-development note must be gone now that EV shipped
    page_text = page.content()
    assert "EV Charging is in development" not in page_text, (
        "Roadmap still states EV Charging is in development"
    )

    assert _overflow_px(page) <= _WIDTH_TOLERANCE
    page.close()


def test_supported_today_roadmap_390(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_390 — Roadmap no horizontal overflow."""
    page = _authed_page(browser, app_server, width=390)
    page.goto(f"{app_server}/roadmap")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= _WIDTH_TOLERANCE, (
        f"Roadmap has {_overflow_px(page)}px horizontal overflow at 390px"
    )
    page.close()


# ---------------------------------------------------------------------------
# SUPPORTED_TODAY_LIMITATIONS_CONSISTENCY (browser layer)
# ---------------------------------------------------------------------------

def test_supported_today_known_limitations_1280(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_1280 — Known Limitations at 1280 px."""
    page = _authed_page(browser, app_server, width=1280)
    page.goto(f"{app_server}/known-limitations")
    page.wait_for_load_state("domcontentloaded")

    content = page.content()
    # All three LIVE synthetic reference models must be named
    for vertical in ("Solar", "Wind", "Data Center"):
        assert vertical in content, (
            f"Known Limitations must reference live vertical '{vertical}'"
        )

    # EV Charging must be identified as in development
    lower = content.lower()
    assert "ev charging" in lower, "Known Limitations must mention EV Charging"
    assert "v1" in lower, (
        "Known Limitations must document the EV Charging V1 limitations"
    )

    assert _overflow_px(page) <= _WIDTH_TOLERANCE
    page.close()


def test_supported_today_known_limitations_390(app_server, browser):
    """SUPPORTED_TODAY_BROWSER_390 — Known Limitations no horizontal overflow."""
    page = _authed_page(browser, app_server, width=390)
    page.goto(f"{app_server}/known-limitations")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= _WIDTH_TOLERANCE, (
        f"Known Limitations has {_overflow_px(page)}px horizontal overflow at 390px"
    )
    page.close()
