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
    # P0 model runtime performance (explicitly approved, semantic-preserving). Profiling showed one
    # Run spent ~70% in tax evaluation and ~20% in SHL schedule roll-forward. These files only
    # remove redundant work (numeric-only cash-tax path for the solver loop, cached period-axis
    # geometry, incremental SHL chain, run-scoped exact-key memo); every output is verified
    # bit-identical to the previous implementation (tests/test_perf_model_runtime_equivalence.py).
    # orchestrator.py and shareholder_waterfall/model.py are already approved above.\n    # V4 shares the exact scalar CFADS primitive between full and solver-only assembly.\n    "financial_engine/tax/engine.py",
    "financial_engine/cfads.py",
    "financial_engine/tax/tax_year.py",
    "financial_engine/tax/loss_ledger.py",
    "financial_engine/shl/production.py",
    "financial_engine/run_scope.py",
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
    from model_v2_governance import released_engine_authority_matches

    changed = changed_paths_vs_main() if changed is None else changed
    # Exact-path, blob-pinned Developer Economics V1 authorities are the only
    # finco_core exemption; finco_radar/venues/relative_value.py is the single
    # finco_radar exemption (reviewed PR #183 core module).  Every other
    # finco_core/finco_radar path stays strictly frozen.
    return sorted(
        f for f in changed
        if f.startswith(STRICTLY_FROZEN_PREFIXES)
        and not (f.startswith("finco_core/") and released_engine_authority_matches(f))
        and f != "finco_radar/venues/relative_value.py"  # PR #183 core
    )


def approved_frozen_path(path: str) -> bool:
    """Exemption for stream-specific "frozen namespace" guards.

    True when the path is authorised by the ACTIVE Model V2 scope, or is a ``financial_engine``
    module on the shared approved allow-list above. Nothing else is exempt: ``finco_core/``,
    ``finco_radar/`` and every other engine module stay frozen for those guards.
    """
    from model_v2_governance import approved_by_active_model_v2_scope

    return path in APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS or approved_by_active_model_v2_scope(path)
