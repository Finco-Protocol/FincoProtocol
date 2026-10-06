"""Governance contract for the Opus Finance Integrity stream (H-2 / H-1 / H-3 / H-4b) and M-6.

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
    # M-6 (explicitly approved engine stream): optional full-tenor sculpting for GEARING_CAP debt.
    # solver.py / models.py are already approved above; these three carry the typed policy option,
    # its validation, and its (non-default-only) provenance key.
    "financial_engine/senior_debt/policy.py",
    "financial_engine/senior_debt/validation.py",
    "financial_engine/provenance.py",
})

STRICTLY_FROZEN_PREFIXES = ("finco_core/", "finco_radar/")


def changed_paths_vs_main() -> list[str]:
    # CI parallel-stream correction: compare against the merge-base of
    # origin/main and HEAD, so unrelated changes that landed only on main
    # after this branch diverged are never reported as branch-side changes.
    # Fails closed (returns no paths) only when git itself is unavailable;
    # an unresolvable merge-base raises via check=True.
    base = subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO), check=True,
    ).stdout.strip()
    result = subprocess.run(
        ["git", "diff", base, "--name-only"],
        capture_output=True, text=True, cwd=str(REPO), check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def unapproved_engine_changes(changed: list[str] | None = None) -> list[str]:
    """financial_engine files changed vs main that are not on the allow-list.

    Narrow Model V2 reconciliation: while the ACTIVE Model V2 epic scope
    (tests/model_v2_governance.py / docs/model_v2/ACTIVE_EPIC_SCOPE.json) is
    present, its explicitly reviewed engine files are governed by the Model V2
    scope contract and do not falsely reject here. Every other engine module
    stays protected by this allow-list exactly as before, and the Model V2
    scope itself never approves finco_core/** or finco_radar/**, so
    strictly_frozen_changes() is unaffected.
    """
    from model_v2_governance import approved_by_active_model_v2_scope

    changed = changed_paths_vs_main() if changed is None else changed
    return sorted(
        f for f in changed
        if f.startswith("financial_engine/")
        and f not in APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS
        and not approved_by_active_model_v2_scope(f)
    )


def strictly_frozen_changes(changed: list[str] | None = None) -> list[str]:
    changed = changed_paths_vs_main() if changed is None else changed
    return sorted(f for f in changed if f.startswith(STRICTLY_FROZEN_PREFIXES))
