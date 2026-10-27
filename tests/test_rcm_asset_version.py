"""RC-M — the React bundle cache-buster is derived from the shipped bytes (``/static/`` is served ``immutable`` by nginx).

A browser keeps an immutable URL for up to seven days.  The host page is ``no-store`` and requests ``finco-react.{js,css}?v=<version>``;
the version must therefore change whenever the bundle changes, or a user could run an obsolete bundle against the new backend contracts.
"""
import hashlib
import re
from pathlib import Path

import pytest

from app.v2 import react_poc_router as router

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "static" / "react"


def _write(folder: Path, js: bytes, css: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "finco-react.js").write_bytes(js)
    (folder / "finco-react.css").write_bytes(css)
    return folder


def test_the_shipped_version_is_the_hash_of_the_committed_bundle_bytes():
    digest = hashlib.sha256()
    for name in ("finco-react.js", "finco-react.css"):
        digest.update(name.encode() + b"\0" + (BUNDLE / name).read_bytes())
    assert router.REACT_ASSET_VERSION == f"rc-sec-mutation-v1-{digest.hexdigest()[:12]}"
    assert re.fullmatch(r"rc-sec-mutation-v1-[0-9a-f]{12}", router.REACT_ASSET_VERSION)


def test_any_change_to_either_file_changes_the_version(tmp_path):
    base = router.bundle_version(str(_write(tmp_path / "a", b"js-1", b"css-1")))
    assert router.bundle_version(str(_write(tmp_path / "same", b"js-1", b"css-1"))) == base
    assert router.bundle_version(str(_write(tmp_path / "js", b"js-2", b"css-1"))) != base
    assert router.bundle_version(str(_write(tmp_path / "css", b"js-1", b"css-2"))) != base
    assert router.bundle_version(str(_write(tmp_path / "swap", b"css-1", b"js-1"))) != base      # bytes are bound to their file name


def test_an_unreadable_bundle_never_collides_with_a_readable_one(tmp_path):
    readable = router.bundle_version(str(_write(tmp_path / "ok", b"", b"")))
    assert router.bundle_version(str(tmp_path / "missing")) != readable


def test_the_host_and_fallback_pages_request_both_assets_with_the_current_version(monkeypatch):
    monkeypatch.setattr(router, "REACT_ASSET_VERSION", "rc-sec-mutation-v1-test0000test")
    host = router._render_host("some-project").body.decode()
    assert "/static/react/finco-react.js?v=rc-sec-mutation-v1-test0000test" in host
    assert "/static/react/finco-react.css?v=rc-sec-mutation-v1-test0000test" in host
    assert 'data-asset-version="rc-sec-mutation-v1-test0000test"' in host
    assert router._render_host("x").headers["Cache-Control"] == "no-store"                      # the page that names the version is never cached


def test_every_template_reference_to_the_react_bundle_carries_the_version_query():
    seen = 0
    for template in (ROOT / "app" / "templates").rglob("*.html"):
        for query in re.findall(r'(?:href|src)="/static/react/finco-react\.(?:js|css)([^"]*)"', template.read_text(encoding="utf-8")):
            seen += 1
            assert query == "?v={{ asset_version }}", (template.name, query)
    assert seen >= 3


def test_the_static_location_is_immutable_so_the_url_is_the_only_cache_key():
    conf = (ROOT / "deploy" / "nginx" / "app.conf").read_text(encoding="utf-8")
    block = conf[conf.index("location /static/"):]
    assert "immutable" in block[:300]
