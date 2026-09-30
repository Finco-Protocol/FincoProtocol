"""Governance contract for the Opus Finance Integrity stream (H-2 / H-1 / H-3 / H-4b).

Before this stream every guard asserted "financial_engine/** has ZERO diff from main". The
stream is an explicitly approved finance correction, so that blanket rule is replaced by
an allow-list: only the engine modules the stream is authorised to change may differ from
main, every other engine module stays frozen, and finco_core/** and finco_radar/** remain
strictly frozen (no exception). A change to any path outside the allow-list fails.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The complete set of financial_engine files the Finance Integrity stream may change.
APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS = frozenset({
    # H-2: DSCR sculpting feasibility / no false CONVERGED
    "financial_engine/senior_debt/solver.py",
    "financial_engine/senior_debt/models.py",
    # H-1: generic product financing policy (IDC, commitment fee, structuring fee, DSRA)
    "financial_engine/financing/generic_product_policy.py",
    "financial_engine/dsra/target.py",
    "financial_engine/dsra/contracts.py",
    "financial_engine/dsra/model.py",
    "financial_engine/orchestrator.py",
    "financial_engine/adapters/project_inputs.py",
    # H-3: typed construction periods carry their canonical dates into sponsor flows
    "financial_engine/shareholder_waterfall/model.py",
})

STRICTLY_FROZEN_PREFIXES = ("finco_core/", "finco_radar/")


def changed_paths_vs_main() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "origin/main", "--name-only"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    return [line for line in result.stdout.strip().splitlines() if line.strip()]


def unapproved_engine_changes(changed: list[str] | None = None) -> list[str]:
    """financial_engine files changed vs main that are not on the allow-list."""
    changed = changed_paths_vs_main() if changed is None else changed
    return sorted(
        f for f in changed
        if f.startswith("financial_engine/") and f not in APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS
    )


def strictly_frozen_changes(changed: list[str] | None = None) -> list[str]:
    changed = changed_paths_vs_main() if changed is None else changed
    return sorted(f for f in changed if f.startswith(STRICTLY_FROZEN_PREFIXES))
