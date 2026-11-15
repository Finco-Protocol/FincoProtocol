# CI V4 Lean B1 — central tamper evidence and warn-only test admission

**Status: additive evidence only.** B1 changes no selector, policy, aggregator, scheduler, workflow, timeout, product, financial or UI source. It selects,
deletes, skips, `xfail`s or moves no test. The accepted `main` trusted-base selector and policy still decide what this PR runs; every historical test
keeps its place and is still collected exactly as before. B2 (moving any test from PR to FULL) is **not** part of B1 and needs a separate owner decision.

## What B1 adds (the finite owned set — see `SOURCE_SUCCESSOR.json`)
| File | Purpose |
|---|---|
| `tests/test_ci_v4_lean_tamper_matrix.py` | ONE central negative matrix, one row per invariant class, driven through the real central gate (`tools/ci_v4_governance_gate.py`) in an isolated full-history clone |
| `tests/ci_v4_lean_report.py` (+ `tests/test_ci_v4_lean_report.py`) | opt-in measurement (wall / CPU / Git subprocess counts / collection digest), worker **SIMULATION**, weights **PROPOSAL**, **warn-only** admission report. Never imported by the CI V4 plan, selector, scheduler or aggregator |
| `tests/ci_v4_lean_b1_scope.py` (+ `tests/test_ci_v4_lean_b1_scope.py`) | the single finite exact-source successor of the accepted C06 cohort that makes the files above legal owned source; `FROZEN` pins every CI V4 control file to its accepted blob |

The successor edits only the shared governance paths a successor must (the composite registry, one forward hook in the C06 leaf, one discovery entry in
`tests/u1_scope.py`, the older exact-tail scope tests that accept one more reviewed state, and the eight current maps — only the registry and U1 keys move).

## How the matrix proves a control (A/B/A, not "any FAIL")
1. **A** pristine clone → gate `PASS`. 2. **B** exactly one injected change → gate `FAIL`, with attribution. 3. **A′** hard-reset → gate `PASS`.
Attribution is stated per row: `direct` (the injected path is the only implicated path), `cohort_named`, `exception` (names the file) or `pinned`
(the path is pinned; the gate revokes every signed sibling at once, so the A/B/A contrast is the causal evidence). Benign controls (mtime-only touch,
identical-byte rewrite, gitignored file) must keep `PASS`. Classes the CLI cannot express are driven through the real registry / aggregator / selector:
wrong ref/tree, memo across mutation, planned-versus-executed mismatch, selector self-narrowing. An invariant the matrix cannot demonstrate stays
`GAP_RETAIN_ON_PR`; nothing is demoted.

## Evidence labels (never mix them)
`MEASURED_LOCAL` · `SIMULATION` (LPT over recorded weights; never hosted truth) · `WARN_ONLY`. A local run is not hosted acceptance; a cancelled or
skipped job is never PASS.

```bash
python -m tests.ci_v4_lean_report measure-gate --output out/gate.json      # wall, CPU, Git subprocess count of one central gate pass
python -m tests.ci_v4_lean_report collect tests/test_ci_v4_aggregate.py     # exact collected node ids + sha256 digest (fresh pytest process)
python -m tests.ci_v4_lean_report simulate tests/test_a.py tests/test_b.py  # 3/4/5/6/8-worker LPT SIMULATION
python -m tests.ci_v4_lean_report admission tests/test_new_thing.py         # WARN-ONLY checklist observations (exit code always 0)
FINCO_LEAN_MATRIX_EVIDENCE=out/matrix.jsonl python -m pytest tests/test_ci_v4_lean_tamper_matrix.py   # opt-in evidence rows
```

## Test admission and retirement — PROPOSED, warn-only (not owner approved)
Baseline: Fable C3-A `05_TEST_ADMISSION_AND_RETIREMENT_POLICY_V1`. A new test should state, in its docstring or PR text:
1. the **named risk** it protects; 2. the **closest existing test** and why it is insufficient; 3. that it **fails without the code**;
4. its **tier / role** (finance, security, tenancy, Save/CAS tests are never replaced by source-text checks); 5. **measured cost** (node seconds and Git
subprocesses); 6. an **owner** (names pending an owner decision — none are invented here); 7. a **retirement event**;
8. no source-text / test-of-test assertion unless the text is an approved contract, and no copied tamper matrix per cohort or file.
`SKIPPED`, `NOT_SELECTED` and `CANCELLED` are never PASS; a PR's own change can never narrow its own selector.
Proposed budgets (**warnings only, not enforced, not approved**): node 60 / 120 / 300 s, module 5 / 10 / 15 min, critical path 35 / 45 / 60 min.
No blocking CI budget, policy gate or extra required workflow is introduced; the 150-minute ceiling is unchanged. A monthly report is a design only
(inputs: last accepted-main JUnit; `budgets` and `weights-proposal` commands above) and nothing is scheduled.

## Rollback
One `git revert` of the B1 merge removes every file above and restores the registry, the C06 leaf, `u1_scope.py`, the older scope tests and the eight
maps to their accepted-main bytes. No data, workflow or product state is involved.
