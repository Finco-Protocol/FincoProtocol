# Parallel workstream overlap register

Inspected main: `128bf0c2b79af56985326543132cc806ff7f001c`.
FIN-V2-2 PR #390: `842fedadd57f33d87e73ed5d231f451977889bf8`.
RC-M PR #388: last rechecked OPEN/DRAFT at
`425b6f397b6b8ca24670cae002ac6b1b4dbfdee5` (advanced from the initially inspected
`248d9112f275626fe10ef7fe5615b2b00e38c887`). Exact current path overlaps are
`tests/finval_f01_scope.py`, `tests/model_mutation_security_successor.py`,
`tests/test_model_mutation_security_successor.py` and
`tests/test_model_react_overnight_b_governance.py`. Union both reviewed cohorts
and their negative controls; do not overwrite either authority.
FIN-V2-1: no matching open PR identified at the last inspection; reserved scope
remains sensitivity, rate shocks, lender adjustments and EV drivers.

| Path | Other ownership | FIN-V2-3 hunk and resolution |
|---|---|---|
| app/api/project_runner.py | FIN-V2-2, additive debt evidence | Three-line financial-core attachment beside financing_evidence. Preserve PR #390's senior-debt builder first, then call attach_financial_core. Never overwrite its result. |
| app/export/institutional_reporting_v3.py | FIN-V2-2 lender section | Preserve its `_write_senior_debt_evidence` and section call. Keep FIN-V2-3's independent append-only valuation section and Total Sponsor primary order. |
| app/services/sensitivity_execution.py | Shared candidate worker; FIN-V2-1 adjacent | Add `regime` alongside unchanged canonical `kpis` result. Preserve FIN-V2-1's candidate/driver changes; no shock logic is changed here. |
| app/v2/router.py | FIN-V2-1 one-driver route; RC-M adjacent | One Goal Seek target-unit conversion hunk. Preserve one-driver and React work; ratio targets divide by 100, DSCR/NPV targets do not. |
| app/services/goal_seek.py | Shared backend; RC-M consumes | Finite new metrics, declared units, canonical verification and regime guard. Preserve existing solver/evaluator authority and Save/Run boundaries. |
| app/input_adapter.py | Merged F01; shared input fold | Add financial-core config application after Developer Economics, before quarterly admission. F01 rate handling is unchanged. |
| app/workbook/registry.py, update_service.py | Shared configuration; RC-M | Add one versioned policy JSON field/validator; preserve all existing ownership/CSRF/CAS logic and F01 unit semantics. |
| app/services/clean_presentation_adapter.py | Shared persistence projection | Add sponsor contribution/date-axis/PIK/net fields and separate canonical SHL balance rows; preserve every old value. |
| app/export/run_evidence.py | Shared frozen export authority | Two read-only accessors. No digest algorithm, persistence or history rewrite. |
| tests/* governance successors | RC-M and other financial streams | Additive union of exact-blob cohorts and Owner-approved test successors; retain historical maps/negative controls. Renew combined exact-blob manifest after resolving source hunks. |

Integrate accepted FIN-V2-1 and FIN-V2-2 source work, then FIN-V2-3 consumers; apply
the runner hunk in debt-evidence-before-valuation order. RC-M consumes the typed
configuration/evidence/Goal Seek contracts after its branch is synchronized with
merged F01/main. The integration agent owns the final branch and cross-workstream
CI. This branch neither creates a competing RC nor pushes to another branch.

Until FIN-V2-2 is present, actual/contractual extended coverage and rolling LLCR
return `DEBT_EVIDENCE_NOT_AVAILABLE`; existing C2 first-opening LLCR and PLCR
remain separately available under a configured policy. The isolated tests use
canonical schedule fixtures; the spreadsheet uses exact-source test composition.


## Correction A integration reconciliation (27 October 2026)

Accepted FIN-V2-2 / #390 main `1f25903e7ed0bb8142f4e9f40d7eade58a746bf5` is a merge parent. Both overlapping paths have explicit combined semantics: `project_runner.py` records `senior_debt_evidence` FIRST, then calls `attach_financial_core` (which consumes the recorded loan-life candidates); `institutional_reporting_v3.py` writes both the #390 lender evidence and FIN-V2-3 valuation. All seven other #390 additions are verified exact-blobs, with a one-byte/missing-path negative test and rejection of unreviewed extra sources. The original F01 ancestor and historical FIN-V2-3 parent blob inventory are unchanged; manifest pins for the four intentionally modified source/test files are updated. #388/#392 are not integrated. Hosted verification is PENDING.


## Correction C — integrated #388 and post-#390 lifecycle evidence (2026-10-27)

Main advanced to `f79e251903621c1a5c88501d51d6971960b612d3` through approved PR #388. Prior exact HEAD `8835385565529335b56c0cbe5a9769578af61b44` had all mandatory checks GREEN except Public Safety CI V3 (`40543293268`), where worker 0 executed 3,518 original test cases: 3,510 PASS / 8 FAIL / 71 skipped; every failing node was a FIN-V2-3 lifecycle `single`/`batch` for Solar, Wind, Data Center or EV Charging. The test expected `DEBT_EVIDENCE_NOT_AVAILABLE`, a true *pre-#390 isolated-source* result, but after the accepted #390 Senior evidence was attached first, the actual persisted coverage result was `OK`. This is a real test contract that must evolve, not a reason to hide tests or change engine math.

The lifecycle test now verifies the Senior evidence is canonical/RECORDED with the exact maturity/payoff index/date sources, coverage `OK` and consistent ratios/horizons/rolling minimum, preserved Run History and report binding. Added four explicit counterfactual negative cases across the four verticals: absent evidence stays `DEBT_EVIDENCE_NOT_AVAILABLE`, tampered payoff date returns `DEBT_EVIDENCE_MISMATCH`. Historical economic oracles are unchanged.

RC-M #388 immutable main is integrated by ordinary merge ancestry and the exact reviewed main tree. Four shared governance sources keep RC-M's six exact pinned presentation successors, F01 atomic-create pins, and FIN-V2-3's finite source successor fallback. No arbitrary financial paths are exempt: RC-M protected source test admits only FIN-V2-3 exact owner-blobs, and FIN-V2-3 scope diffs the accepted main tree, requiring all non-owned main paths to remain inherited byte-for-byte. Original historical BASE stays `128bf0c2...`. The RC-M guard becomes FIN-V2-3's fifty-first protected owned source; source manifest records its original main blob and all corrected source hashes. The seven independently pinned #390 dependency blobs remain unchanged.

**Tests pending on this integrated source:** new exact-head F01, browser, FIN-V2-3 Oracle, strict numerical/identity, Governance Full History, 5-worker Public Safety. Previous success cannot be inherited. No release, merge, activation or deploy authorization.
