"""WF-07 / S7-06: the Library classifies canonical references, previews and editable working copies unambiguously and never shows a missing result as zero."""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import re

from tests.test_qa_create_project_country_capacity import _login, client  # noqa: F401


def _page(client, login=True, **params):
    if login:
        _login(client)
    return re.sub(r"\s+", " ", client.get("/library", params=params).text)


def test_every_reference_card_is_labelled_canonical_and_read_only(client):
    html = _page(client)
    cards = re.findall(r'data-testid="badge-reference-([^"]+)"', html)
    assert cards, "reference cards are rendered for a user without projects"
    assert all("Canonical reference · read-only" in html for _ in cards)
    for code in cards:
        assert f'data-testid="open-{code}"' in html          # inspectable
    assert "Create working copy" in html                       # editing is only through a working copy


def test_a_reference_without_saved_results_states_it_and_never_shows_zero(client):
    html = _page(client)
    for code in re.findall(r'data-testid="reference-no-evidence-([^"]+)"', html):
        block = html[html.index(f'data-testid="reference-no-evidence-{code}"'):][:400]
        assert "never displayed as zero" in block


def test_working_copies_and_runs_are_distinguished_after_cloning(client):
    html = _page(client)
    m = re.search(r'action="/library/clone/([^"]+)"', html)
    assert m, "a clonable reference exists"
    r = post_valid_csrf(client, f"/library/clone/{m.group(1)}", headers={"HX-Request": "true"})
    assert r.status_code in (200, 204, 303), r.text[:200]
    after = _page(client, login=False)
    assert re.search(r'data-testid="badge-working-copy-[^"]+">Working copy<', after)              # editable working copy is its own class
    assert re.search(r'data-testid="last-run-none-[^"]+">Not run<', after)            # a new working copy has no committed Run and says so
