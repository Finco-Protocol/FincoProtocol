"""PR #75 Featured board fail-closed presentation guard."""
from pathlib import Path


def test_featured_row_requires_canonical_uid_before_becoming_visible():
    """A symbol-only market row must never unhide an unresolved Featured identity."""
    root = Path(__file__).resolve().parents[1]
    poller = (root / "static/radar/market-poll.js").read_text()

    assert "const hasCanonicalIdentity = !!(node.dataset.marketUid || '').trim();" in poller
    assert "const usableReference = hasCanonicalIdentity &&" in poller
    assert "node.hidden = !usableReference" in poller
