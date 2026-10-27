# Final PR / CI report — React Institutional Model MVP correction (Overnight B)

Verdict: **READY FOR INDEPENDENT REACT REVIEW** (exact-head CI green on `052252f1`, §6). No merge, deployment, release activation or self-approval.

## 1. Identity

| Item | Value |
|---|---|
| Repository / branch | `Finco-Protocol/FincoProtocol` · `claude/wonderful-clarke-tiswep` (one integrated correction branch) |
| Baseline | main `6f10f3927b33a5715ac6313da200d0f96c023524`, tree `62e70c3bfda7a91280c8c16acc89eeef9f780d6b` (unchanged `origin/main` at PR time) |
| PR tested head / tree | `052252f1f335f10b7801a50110a7b4ad61d434b5` / `3f0cdd1dce8c87470115103dd8f59200b0c3ed4d` (§6); a later documentation-only commit records these numbers |
| History rules | no rebase, squash, cherry-pick or force push; one normal forward merge of `origin/main` was needed late (PR #387, §6) |
| Coordination with Overnight A | at start and before the push no Overnight A branch existed on the remote (no branch ahead of main touching React/financing); `app/v2/router.py` is untouched, so no conflict is possible |
| Open PRs at start | 17, none touching `frontend/`, `static/react`, `react_workspace_router.py` or the React tests (dependabot, performance V8/V9, RC-7, yield) |

## 2. Bundle identity

`frontend/` `npm ci --ignore-scripts && npm run typecheck && npm run build` (one canonical build after all component corrections), copied to `static/react/`:

| File | sha256 |
|---|---|
| `static/react/finco-react.js` | `09abafa9de8a0e0f7480ec93d25da004ff7c0cbc7885834a4970369ca6825428` |
| `static/react/finco-react.css` | `477a5debb4d7e983c9aa1cc41d3cfff6988f46ad38e1e81ca0c1052b607e96bc` |

At baseline a clean build reproduced the committed bundle byte-for-byte (`5e18dd63…98e`, `c85745c4…3844`), so the diff is exactly the source change.

## 3. Protected-source evidence

Twelve pinned paths changed; each is admitted by the additive `REACT_MVP_CORRECTION_SUCCESSORS` layer (git blob SHA-1):

| Path | Baseline blob (main) | Successor blob (this PR) |
|---|---|---|
| `app/v2/react_workspace_router.py` | `aee8e13815cc02f3e7ae43c57925aa6679515719` | `db088accc730f3364dad347d1bb523e2463e1bbe` |
| `frontend/src/app/FinancialResults.tsx` | `99126471e6e8f9ea8cee8030b11ffe09673821f1` | `69b7123f25d511f57797bba76004c653bcdaeab4` |
| `frontend/src/app/WorkspaceView.tsx` | `5e14876224a9444151aa57b243291dbb98b2891e` | `eed73f37765f55ada26fe4bcb937c857d6e92dda` |
| `frontend/src/app/types.ts` | `d5077405dd2c316fe3ee006250287d11835382f4` | `0a4eff084f0d49e4e9eb2608c687f11c00c11060` |
| `frontend/src/app/workflow/ModelExportView.tsx` | `0f86be3903b0086bbcd297de7edc9e9efd40f528` | `d4534de001d7d3cf89206905156c519d8b51c4b5` |
| `frontend/src/app/workflow/ScenarioWorkspace.tsx` | `324922d117639cce8c7ec94cd7129ec67b15f5fb` | `7ec94910f41d3e727084671823c5739d480700da` |
| `frontend/src/app/workflow/workflowShared.tsx` | `52f1aa62c4a19091cc5d868aa3bd5c55f7206c54` | `6de23ad7c469c0ba197697dda10afe494426751a` |
| `static/react/finco-react.css` | `b260d8d0fda3b271efbd29d48ed8ee442e7a6d2a` | `adbc32f079ee5a77cf3bf1228a8b46d76f0245dd` |
| `static/react/finco-react.js` | `907cfa53e07c78e03cd12dd537a806832dfeb7e8` | `0f85e69fd9b3a398d82d61b95243ccfd46d4b9d2` |
| `tests/model_react_mvp_acceptance.py` | `525dce2ca34c5fa8744f5d7e4e63100b1611af48` | `10885eab163fa556c42e4f27fb3814e0bd442640` |
| `tests/model_react_wf2_browser_acceptance.py` | `34a1be8ae3e3fbd165115ff13a2888b2fb602c39` | `ce6d7f5e2c5fc6f4fe9a985b2b4724011889511f` |
| `tests/test_model_workspace_consolidation_browser.py` | `f1a762a4f7bbfca34e8e93c74fbba3042d970665` | `6f91b8c9376ba65c27aab34ea39651cef351b2e9` |

* The original 112 pins at `1800bf6092af650f18aa6ae70e9df221797090fd`, the FIN-VAL B2/C1 layer and the D-029 layer are unchanged and still individually admitted (`test_every_earlier_admitted_blob_remains_individually_admitted`).
* `app/v2/router.py`, `app/workbook/mutation_csrf.py`, `app/v2/react_poc_router.py`, `app/input_adapter.py`, `app/persistence/projects_repository.py`,
  `app/runtime/model_execution.py`, the financial engine, Run endpoint, history writers, D-029 modules, CI workflows are **not** in the diff
  (`test_the_correction_changes_no_protected_financial_path_since_the_baseline`).
* Authorization basis: the Financial Owner scope in the Overnight B task statement §0; recorded as *relayed, not independently verified*.
  This is an owner/independent-reviewer confirmation item (§8).

## 4. Test counts (local, exact)

| Suite | Result |
|---|---|
| Mandatory consolidation browser file | **106 passed** (80 existing + 26 new), 0 failed/skipped, 533 s |
| New browser nodes | 26 `test_onb_*` (4 identity verticals + hostile query + switching + fail-visible + two-Runs + comparison + save-scope + scalar save + 4 compact-Inputs + protected + navigation + 3 typography + 4 truth + boundary + themes) |
| New Python tests | `test_model_react_overnight_b_v1.py` (19: Run-identity contract incl. Python↔TypeScript parity, label/unit, source rules, vertical scope, lender metrics) and `test_model_react_overnight_b_governance.py` (successor layer, drift negatives, scope guard) |
| React/router/governance Python batch | 642 passed, 2 skipped (+ the exceptions below) |
| Trust-readiness suites | 180 passed (full-history clone); identical failures on unmodified main with a shallow clone |
| `tests/test_model_react_poc_browser_acceptance.py` | 2 failed — **identical on unmodified main** (canonical Run "Draft changed since page loaded"); not in any CI browser role |
| Public safety scan | `PUBLIC_REPOSITORY_SAFETY_SCAN_PASS` |

## 5. Known limitations (see `REACT_MVP_CORRECTION_IMPLEMENTATION.md` §4)

Financing interest-rate representation pending Overnight A (F01); Data Center/EV Charging are previews, BESS closed, Solar/Wind are pilot
*candidates* only; NPV/LLCR/PLCR often unavailable; D-029 policies unapproved and its router flag inert; stale-bundle cache prerequisite;
audit archives not available; two pre-existing test issues recorded above; no live-server verification.

## 6. Exact-head CI

Final tested head: **`052252f1f335f10b7801a50110a7b4ad61d434b5`**, tree **`3f0cdd1dce8c87470115103dd8f59200b0c3ed4d`** (PR
[Finco-Protocol/FincoProtocol#386](https://github.com/Finco-Protocol/FincoProtocol/pull/386), draft), which includes a **normal forward merge of
`origin/main` `8d9cccc7` (PR #387, executor recovery)**; no rebase, squash or force push. A later commit adds only this section's final
numbers (documentation).

| Workflow on `052252f1` | Result |
|---|---|
| Protocol UI Browser Acceptance → `mandatory-browser-evidence` (six isolated roles; consolidation role 106 nodes) | **success** |
| Public Safety and Model Smoke (`40456108383`) → source-safety, route, plan, worker-0…4, aggregate, tests, mandatory-evidence (`sequential` skipped by design) | **success** |
| PR Compile and Safety Gate | **success** |
| Governance Full History | **success** |
| Dependency Security Audit | **success** |

Head history and what each run showed (nothing skipped, disabled, quarantined or re-run to obtain green; no empty commit; no CI file changed):

| Head | Result | Cause and fix |
|---|---|---|
| `77920b6b` (first PR head) | Browser Acceptance **failed** (1 node); Public Safety superseded | `test_d029_react_run_intent_acceptance[check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit]`: a null-unsafe wait in the D-029 test helper racing the post-Run page reload (also failed once on unmodified main locally). Fixed by null-safe waits (same semantics) |
| `37a9d291` (+ `8f9753b3` docs) | all five workflows **green** | — |
| `70638f3b` (independent-review fixes, §6b) | Browser Acceptance **failed** (4 nodes, the new compact-Inputs check) | a *new test step* read the staged-edit badge synchronously (passes locally, races on the runner). Fixed by polling (`wait_for`) |
| `6f0c5b61` | all five workflows **green** | superseded only because main moved |
| `5f832314` (docs-only) | Browser Acceptance **failed**: `MERGE_TREE_GATE_FAILED: DIFFERENT TREES … normal main synchronization and fresh exact-head CI are required` | `main` had advanced (PR #387, executor recovery), so the head tree no longer equalled the merge-result tree. Fixed by a normal forward merge of `origin/main` (disjoint paths, no conflicts) and fresh exact-head CI; the protected-path scope guard now diffs from the merge-base so main's reviewed changes are not attributed to this branch |
| `052252f1` (merge + guard fix) | all five workflows **green** | final tested head |

## 6b. Independent review of the diff (`/code-review high`, forked reviewer, 10 findings) and dispositions

| # | Finding | Disposition |
|---|---|---|
| 1 | CAPEX/OPEX jump request replayed on every Inputs re-mount (`lastRequest` started at 0) | **Fixed** (`useRef(requestNonce)`); asserted in `check_inputs_are_compact…` (jump OPEX → Statements → Inputs reopens on CAPEX) |
| 2 | Lender NPV cards ignored the unit/precision controls | **Fixed** (`metricDisplay`); asserted with `mEUR` selection + source guard |
| 3 | Vertical tier hardcoded in the router; substring matching (`solar_storage` ⇒ solar) | **Match fixed**: exact normalised type / `generic_<key>_reference` only, otherwise `UNCLASSIFIED` (new test). The pilot-tier map stays in the router **on purpose**: it is the Financial Owner's stated posture, not a registry fact, and `app/product_capability.py` is outside the authorized scope — listed as an owner decision |
| 4 | `serializ\b` regex never matched | **Fixed** (`serializ\w*`) |
| 5 | Unavailable metric card shows the source text | **Kept**: for an unavailable metric the backend's `source` *is* the reason ("Not persisted by the canonical clean sponsor schedule") and an existing pinned-intent test asserts it; the provenance list under "Technical source" is a separate disclosure |
| 6 | Vertical banner only on Overview/Results | **Fixed**: also on Statements and Analysis (asserted for every vertical) |
| 7 | Reference-project snapshot ids (`canonical_last_run__<template>__<ts>Z`) printed raw; Run picker lost the time | **Fixed**: parser accepts that stamp (Python↔TypeScript parity test includes it); Run picker falls back to `ran_at` for unparseable ids |
| 8 | Staged grid edits could be hidden by collapsing a section | **Fixed**: a section with unsaved edits cannot collapse and its summary shows "N unsaved edits" (asserted) |
| 9 | Successor layer is self-attested; the validator and earlier asserts were relaxed | **Acknowledged, not changed**: this is the repository's established successor mechanism (FIN-VAL, D-029 did the same); the relaxation is exactly "current blob ∈ admitted layers", every earlier blob stays individually admitted, original pins are untouched. It needs a security-owner confirmation (owner decision #1) |
| 10 | Export "Historical Runs" repeated the time | **Fixed** (column removed; asserted) |

The fixes were pushed in a follow-up commit; the successor-layer blobs were regenerated for the changed pinned files and the governance suite re-run (182 passed); the exact-head CI results are in §6.

## 7. Reviewer guide (fast path)

1. `docs/react_migration/overnight_b/REACT_MVP_CORRECTION_IMPLEMENTATION.md`, then the four focused documents.
2. Source: `frontend/src/app/runIdentity.tsx`, `InputsGuide.tsx`, `VerticalScope.tsx`, `CanonicalInputGrid.tsx`, `WorkspaceNav.tsx`, `StatementWorkbook.tsx` (identity), router helpers `_vertical_scope` / `_lender_metrics`.
3. Governance: `tests/model_mutation_security_successor.py` (layer) and the two new test files.
4. Rebuild: `cd frontend && npm ci --ignore-scripts --no-audit --no-fund && npm run typecheck && npm run build` and compare the two sha256 values above to `dist/`.

## 8. Outstanding owner decisions

Listed in `REACT_MVP_CORRECTION_IMPLEMENTATION.md` §5 and `D029_RELEASE_TRUTH_RECONCILIATION.md` §4/§6: approve/amend the successor layer and its
relayed authorization; static-asset version/cache policy before the pilot; D-029 policies and documentation; PPA-01 and multi-senior pilot
status; F01 dependency; Data Center / EV Charging in the pilot.
