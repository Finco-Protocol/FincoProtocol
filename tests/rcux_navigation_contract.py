"""RC-UX Addendum A — the pure, browser-independent navigation contract.

The single definition of what counts as a Legacy / classic / external navigation target, shared by the real-Chromium acceptance
(``tests/model_react_rcux_navigation_acceptance.py``, mandatory browser role) and the source-only test (``tests/test_rcux_navigation_source.py``,
collected by CI V3).  It imports nothing but the standard library: ordinary pytest collection must never depend on Playwright or on a browser
acceptance module.

Acceptance rule: ZERO links, forms, frames or navigations from the React Model to a Legacy/classic screen — ``staging.finco.one`` and EVERY
same-host route outside ``/v2/model-react`` fail, not only a text search for the staging host.  A Run export is a file download (an attachment,
the page does not leave): only the two export endpoints are allowed for that.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

__all__ = ("DOWNLOAD_PATHS", "REACT_PREFIX", "TARGETS_JS", "violation")

REACT_PREFIX = "/v2/model-react"
#: File downloads (an attachment: the page stays where it is) are not screens.  Nothing else outside ``/v2/model-react`` is allowed.
DOWNLOAD_PATHS = ("/v2/workbook/export", "/v2/workbook/run-history/export")

#: Every user-visible navigation target of the current DOM.
TARGETS_JS = """() => {
  const out = [];
  const add = (kind, el, target) => out.push({kind, target: target || '', text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 60),
                                              download: el.hasAttribute('download'), blank: el.getAttribute('target') || ''});
  document.querySelectorAll('a[href]').forEach(el => add('a', el, el.getAttribute('href')));
  document.querySelectorAll('area[href]').forEach(el => add('area', el, el.getAttribute('href')));
  document.querySelectorAll('form[action]').forEach(el => add('form', el, el.getAttribute('action')));
  document.querySelectorAll('button[formaction], input[formaction]').forEach(el => add('formaction', el, el.getAttribute('formaction')));
  document.querySelectorAll('iframe[src], frame[src], embed[src], object[data]').forEach(el => add('frame', el, el.getAttribute('src') || el.getAttribute('data')));
  document.querySelectorAll('[data-href], [data-url], [data-link]').forEach(el => add('data', el, el.getAttribute('data-href') || el.getAttribute('data-url') || el.getAttribute('data-link')));
  document.querySelectorAll('meta[http-equiv]').forEach(el => { if (/refresh/i.test(el.getAttribute('http-equiv'))) add('meta-refresh', el, el.getAttribute('content')); });
  return out;
}"""


def violation(target: str, *, page_url: str, download: bool = False) -> str | None:
    """Why this target is a Legacy / classic / external navigation, or None if it stays inside React."""
    raw = (target or "").strip()
    if not raw or raw.startswith("#"):
        return None
    parsed = urlparse(urljoin(page_url, raw))
    here = urlparse(page_url)
    if parsed.scheme in ("mailto", "tel"):
        return None
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme or '?'}: {raw}"
    if "staging.finco.one" in parsed.netloc.lower() or "staging.finco.one" in raw.lower():
        return f"staging host: {raw}"
    if parsed.netloc != here.netloc:
        return f"external host: {raw}"
    path = parsed.path
    if path == REACT_PREFIX or path.startswith(REACT_PREFIX + "/"):
        return None
    if path in DOWNLOAD_PATHS:
        return None
    return f"same-host classic route {path}: {raw}"
