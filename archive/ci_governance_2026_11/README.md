# Archived CI governance (CI V3 / V4 / V5), retired 2026-11 by owner decision (FINCO33)

FROZEN. Nothing here is collected by pytest (`testpaths = tests`), executed by a workflow (only
`.github/workflows/` runs) or imported by active code. It is kept so the history stays readable in place.

| Directory | Original location | Content |
|---|---|---|
| `workflows/` | `.github/workflows/` | the 42 workflow files active on main `707e68b290694c57b470f4a112c190abb3d02ac9` |
| `tools/` | `tools/` | `ci_*` (V3/V4/V5 selectors, node plugins, aggregators, attestations, perf guard, epoch) and `governance_history_gate.py` |
| `tests/` | `tests/` | governance helper modules (exact-source cohorts, successor registries, scope proofs) and test modules whose every node checked that machinery |
| `tests_mixed_originals/` | `tests/` | original bytes of modules from which only governance-bound nodes were removed; the functional nodes stay active in `tests/` |

Last commit on which all of this was active: `707e68b290694c57b470f4a112c190abb3d02ac9`
(tree `0d4e8961c33e7bab7aa94077ee4fe9b561061ba2`). To run a historical check, use a detached worktree of that commit:
`git worktree add --detach /tmp/finco-707e68b2 707e68b2 && cd /tmp/finco-707e68b2 && python -m pytest <module>`.

Disposition of every archived module and removed node group: `docs/ci/normalization_2026_11/CONTROL_DISPOSITION.csv`.
