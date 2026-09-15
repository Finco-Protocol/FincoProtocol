"""Phase D2 — Depreciation Flag Discipline.

Single source of truth for the four canonical / tax-bridge /
book-pnl depreciation flags that control whether the active
runtime path promotes the canonical DepreciationEngine or any
of the canonical tax-bridge / book-pnl bridges.

The flags are:

- ``use_depreciation_canonical_engine``: route the waterfall
  through the canonical DepreciationEngine (instead of the
  legacy half-year book schedule).
- ``use_canonical_tax_depreciation_bridge``: route the
  tax-depreciation calculation through the canonical
  tax-depreciation bridge.
- ``use_tax_bridge_engine``: route the waterfall through the
  canonical tax-bridge engine.
- ``use_book_depreciation_for_pnl``: route the P&L book
  depreciation line through the canonical book-depreciation
  bridge.

This module is read-only. The active runtime path does NOT
promote the canonical engine; the four flags are False on the
factory default projects (Generic Wind Reference, Generic Solar Reference, Generic Solar,
Generic Wind). D2 is discipline-only: it documents the flag
inventory, exposes read-only summary helpers, and offers a
PermissionError-raising guard helper for tests and future
controlled-enablement PRs. The guard helper is NOT wired into
the live waterfall path; it is exported for tests and for
future controlled-enablement PRs to call explicitly.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Single source of truth flag inventory
# ---------------------------------------------------------------------------

DEPRECIATION_FLAG_NAMES: tuple[str, ...] = (
    "use_depreciation_canonical_engine",
    "use_canonical_tax_depreciation_bridge",
    "use_tax_bridge_engine",
    "use_book_depreciation_for_pnl",
)

#: Human-readable label for each flag. Used by the discipline
#: summary and the audit sheet row.
DEPRECIATION_FLAG_LABELS: dict[str, str] = {
    "use_depreciation_canonical_engine": (
        "Canonical Depreciation Engine"
    ),
    "use_canonical_tax_depreciation_bridge": (
        "Canonical Tax Depreciation Bridge"
    ),
    "use_tax_bridge_engine": "Tax Bridge Engine",
    "use_book_depreciation_for_pnl": (
        "Book Depreciation P&L Bridge"
    ),
}


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def list_depreciation_flag_names() -> tuple[str, ...]:
    """Return the canonical flag-name tuple."""
    return DEPRECIATION_FLAG_NAMES


def _flag_value(project_inputs: Any, name: str) -> bool:
    """Read a single flag value from the project inputs
    (defensive against missing attribute)."""
    info = getattr(project_inputs, "info", None)
    if info is None:
        return False
    return bool(getattr(info, name, False))


def is_canonical_promotion_active(project_inputs: Any) -> bool:
    """Return True if ANY of the four canonical /
    tax-bridge / book-pnl depreciation flags is True on the
    project inputs."""
    return any(
        _flag_value(project_inputs, name)
        for name in DEPRECIATION_FLAG_NAMES
    )


def get_depreciation_flag_discipline_summary(
    project_inputs: Any,
) -> dict[str, dict[str, Any]]:
    """Return a per-flag discipline summary, one entry per
    flag in ``DEPRECIATION_FLAG_NAMES``.

    Each entry is::

        {
            "name": str,
            "label": str,
            "value": bool,
            "would_block": bool,  # always True for these
            "                  # four flags
        }

    The summary is JSON-friendly.
    """
    summary: dict[str, dict[str, Any]] = {}
    for name in DEPRECIATION_FLAG_NAMES:
        value = _flag_value(project_inputs, name)
        summary[name] = {
            "name": name,
            "label": DEPRECIATION_FLAG_LABELS[name],
            "value": value,
            "would_block": True,
        }
    return summary


def assert_no_canonical_depreciation_runtime_promotion(
    project_inputs: Any,
) -> None:
    """Discipline guard: raise PermissionError if any of
    the four canonical / tax-bridge / book-pnl depreciation
    flags is True on the project inputs.

    This helper is NOT wired into production runtime. It
    is exported for tests and for future
    controlled-enablement PRs to call explicitly. The D2
    sheet disclosure is the only export/audit surface
    addition in this phase; there is no
    ``runtime_flag_snapshot`` WARN log in this redo and
    ``app/persistence/`` remains untouched.
    """
    enabled = [
        name
        for name in DEPRECIATION_FLAG_NAMES
        if _flag_value(project_inputs, name)
    ]
    if enabled:
        enabled_str = ", ".join(
            "{0!s}={1!r}".format(name, True) for name in enabled
        )
        raise PermissionError(
            "Phase D2 discipline: canonical / tax-bridge / "
            "book-pnl depreciation promotion is BLOCKED. "
            "The following flag(s) are enabled on the "
            "project inputs: {0}. D2 is discipline-only; "
            "runtime enablement requires a future "
            "controlled-enablement PR.".format(enabled_str)
        )
