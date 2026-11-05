# POST_424_BLOCKER.md — exact-source integration blocker after merging main #424 (Correction D)

**Status: DRAFT_BLOCKED — narrow escalation to the integration/protected-source authority required.** Everything else in this PR (G10 Option A read-model, D8 copy, dedicated default-OFF gate, 21 G10/D8 tests, bundle rebuild) is implemented, tested (21/21 + 4/4 node) and preserved on this branch, including the ordinary merge of main `53e8dc76` (#424) as commit `705683d8` + follow-ups.

## First-failure causal table (official gate verdict at merged HEAD, tools.ci_v4_governance_gate)

| Layer | Check | Result at #423 merged HEAD | At main `53e8dc76` |
|---|---|---|---|
| 1 | `tests.fin_v2_3_scope.exact_blobs_ok` (first in registry order) | **FAIL** — 8 pins not admitted by `_wf06b_supersedes` (e.g. `tests/fin_v2_3_scope.py` tree `c8009fc3` vs pin `898d2c05`; identical blobs exist at main where supersedes=True) | PASS |
| 2 | `fin_v2_d01/r1/rcux/wf06a/int409/wsv2/wsv2v2/wf04/wf03/wf06b/u1/u2.exact_blobs_ok` | **FAIL** — cascade from 1 via the shared wf06b→u1→later admission chain | PASS |
| 3 | `fin_v2_cohorts.valid()` composite | **False** (15 inexact → all `matches()` fail-closed → F01's "22 unreviewed blob paths" incl. `app/library/router.py`, a file this PR never touched) | PASS |
| 4 | G10/D8 cohort (`tests.g10_d8_scope`) | **exact: True** (own manifest, bounded supersession, registration in registry/u1/u2) | n/a (new) |
| 5 | Product tests (G10/D8, OPEX Years, request-gate) | **21 PASS + 4 node PASS** | n/a |

## Proven root cause (evidence, not hypothesis)

1. **The triad manifests are immutable across the whole #419→#424 window** — byte-identical at `cd125b5e`, `a059635e`, `204b6040`, `53e8dc76` (verified by `git rev-parse` of all four refs). The triad (wsv2_core/wf04/wf03) is exact on main **without manifest edits**, through historical-maps/B1-seal/wf06b→u1→later hook machinery inside their modules.
2. **Correction A/B's broad re-pinning of those eight historical manifests was the regression** — U2's stage-8 (`_sibling_owns`) rejected them (proof: per-stage instrumentation, 8 unowned paths), and the gate/F01 cascade followed (`matches()` requires composite `valid()`). Restoring the manifests to main bytes (current state) fixed 8 of 11 broken cohorts: **18/21 exact at `ed946025`** (local full-registry validation log).
3. **The residual triad failure is NOT explicable by this PR's file delta**: e.g. `frontend/src/app/WorkspaceSidebar.tsx` is byte-identical between main and this branch (`git diff` empty) yet its wsv2 pin (`68294d5b`, the pre-#421 blob) does not match the merged-tree blob (`f9d28206`, introduced by #421/#424 on main) — and the triad is exact on main where the same stale pin + same drift exist. The admission therefore runs through internal machinery (`_historical_maps_ok`, `_b1_layer_ok`, `PREDECESSOR_MANIFESTS`/`WF04_SUCCESSOR_REPIN` repin maps, registered-later-cohort `historical_blobs` chains) whose exact reproduction for a side branch requires the #421-integration-level forensics that merged the triad-consistent state into main in the first place.
4. Ad-hoc stage probes on the triad modules proved unreliable (shared memo scopes; direct calls bypass and pollute cross-cohort memos) — per the escalation rule this is where implementation stops.

## Why the two candidate repairs need the integration authority (stop-and-document)

- **(a) Re-pin the triad manifests to the merged tree** — this is exactly what broke the gate before (violates the "no OLDER manifest edited" invariant that U2's tests enforce; the manifest bytes are Owner-keyed through #419's integration).
- **(b) Extend the triad modules' later-cohort enumerations/historical maps for the G10/D8 cohort** — the sanctioned pattern #419–#424 used for their own cohorts (commits `5fd6cf14`/`b83731d7`/`52e00f7d` "U1 historical_blobs reports a registered later cohort's git-verified BASE blob"; #421's "adapt the N closure tests to the registered later cohorts") — but it edits `tests/wsv2_core_scope.py`, `tests/wf03_lifecycle_scope.py`, `tests/wf04_scope.py`, `tests/wf06b_scope.py` internals, which are #419-integration-protected sources; the equivalent change was made by the integration agent inside #419, not by a product PR.

**Requested authority decision (narrow):** which of (a)/(b) — or a third integration-agent variant — is the sanctioned way to let a product PR's legitimately-merged shared-file delta (committed React bundle, registry union, RC-UX aggregator edit) remain exact under the triad. The branch already carries the honest union state; no masking, no skipped tests, no weakened checks.

## Preserved and green on this branch

- #421 O1/G7/G-U2-1/D7 features and their tests (merged, not enabled beyond main's state); #424 PR-A node-coverage infrastructure untouched (node split stays OFF); CI V4 trusted-base selector and policies untouched.
- G10/D8: 21/21 Python + 4/4 node checks PASS at merged HEAD (K1/K3/T2 corrected oracles incl. 411.324220800/553.588245560563/9700; NOT_RUN/NOT_AVAILABLE/503 typed; pass-through equality; immutability oracle; default-OFF `FINCO_G10_RUN_OPEX_PANEL`; request lifecycle gate with no cross-project flash).
