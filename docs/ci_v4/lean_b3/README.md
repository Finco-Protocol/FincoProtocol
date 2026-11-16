# CI V4 Lean B3 — WARN-ONLY test-admission report (B3 + B4 status)

**Scope:** ONE finite exact-source successor of the accepted B2 cohort (BASE `523a9eb2`, merged #451) carrying the machine-readable
**test-admission report** (`python -m tests.ci_v4_lean_report test-admission --base ... --head ... [--plan ...] [--junit ...]`): added/removed/renamed/changed test
modules and function-name deltas over the trusted-base diff (read from Git objects at the supplied refs, never the working tree), selected/NOT_SELECTED status
from a supplied plan, admission metadata with UNKNOWN-for-missing, duplicate CANDIDATES (a normalized-AST heuristic only), skip/xfail marker lines labelled
NEW_VS_BASE or PRE_EXISTING, budget warnings and the plan's predicted critical path. Every number carries an evidence label; exit code is always 0; there is no
workflow and no recursion into governance tests. Function-name deltas are never reported as collected pytest node ids: exact ids stay UNKNOWN without a
SHA-bound `pytest --collect-only` of both states, and a supplied JUnit is `UNVERIFIED_INPUT` (it carries no commit identity).

**Registry tail:** exactly `C06 -> B1 -> B2 -> B3`. B3 hands off the C06 and B1 tuple acceptance (one more reviewed state) and the B2 forward hooks (the accepted
C06 -> B1 -> B2 pattern); any permutation, duplicate, extra cohort or truncation of that tail is rejected by every layer.

**Not in this change:** no scheduling-weight refresh (`docs/ci_v4/module_weights.json` stays FROZEN to accepted-main bytes), no selector, policy, workflow, timeout,
product, financial or UI change; no test selected, deleted, skipped, moved or demoted.

**B4: ZERO demotions proposed (`B4_PROOF_BLOCKED_ZERO_DEMOTIONS`).** No node-level same-SHA replacement proof exists for the 177 NOT_RETIRABLE and 711 GAP_RETAIN_ON_PR
nodes, and the owner has not approved any demotion; they all stay on the PR path.

**Rollback:** `git revert` of the B3 commits restores B2's state exactly (the successor chain is acyclic and the B2 cohort stays exact at the revert).
