# V9-B1 Implementation and Measured Acceptance

**Disposition: V9-B1 IMPLEMENTED - FINANCIAL GOVERNANCE APPROVAL REQUIRED.**

Local candidate only. No push, PR, governance release, self-approval, merge, deployment or activation. Exact final commit/tree are recorded in the review package's provenance.json to avoid a self-referential commit identifier in this report.

## Provenance and Scope

- Baseline/main, independently fetched before development and refreshed after measurements: `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`.
- Research: `79270c9513cbd0ed7c0432733903482bc6528b93`; report reviewed, research monkeypatch/runtime-compilation code NOT transplanted.
- Branch: `feat/model-v9b1-g2a-capacity-deferral`, isolated from PR #320/#321/#322.
- Only production/protected change: `financial_engine/financing/project.py`.
- Released baseline blob: `30536cec8779fdb6a490d82fd80bfce2c09e16fe`.
- Final candidate blob: `61bd3e644b8e3159d1709c32b41aec12340c5e34`.
- No changed core/domain/solver/tax/statement formula, numerical tolerance, existing golden, financial pin, workflow, persistence, authorization or release-flag file.

The funded fixed point, seed, service-budget refinement, gearing/DSCR handshake and final funding/accounting checks are unchanged. The capacity-only model is evaluated on the exact accepted iteration's input, not a newly rounded/reconstructed principal. One private helper retains the original capacity-first path for a bounded named SHL-maturity re-decision. Unrelated programming errors propagate. No new financial kernel/cache/worker is introduced.

## Executed Financial Equivalence

| Cohort | Baseline execution | Candidate execution | Result |
| --- | --- | --- | --- |
| Original research matrix | 31 feasible + 18 rejected | 31 feasible + 18 rejected | All 49 full output/error digests identical; 509,024 tagged leaves compared |
| Four reference verticals + M6 | 5 feasible + 2 rejected | 5 feasible + 2 rejected | All seven full digests identical |
| Additional inner-boundary investigation | 32 canonical paths | 32 deferred paths | No feasibility flip; supplemental investigation, not a full-output/persistence proof |

Each baseline is a real run imported from the detached immutable main checkout, not a source-rewritten baseline in the candidate process. The result flattener retains type/structure and all IEEE-754 float bytes, including signed zero, with no diagnostic/hash exclusions. Successful `CleanProductionRun` outputs and Run Integrity reports are compared in full; rejected results compare complete exception class, reason and untruncated error text.

The matrix covers DSCR/gearing binding, construction/SHL/tax feedback, DSRA 0/6/12, tenors, leap/stub dates and genuine unpaid balances. M6 extended scenarios include one successful full production level-principal case and two baseline-rejected full-policy cases; those refusals are not presented as newly working products. Existing direct M6 orchestration regressions also pass.

No mathematical equivalence tolerance was introduced. No reference golden was refreshed. Review the finite-matrix and skipped-intermediate-refusal limitation in `V9B1_GOVERNANCE_AND_INTEGRATION.md`: a successful skipped failure outside tested inputs would remain NO GO, not an implicit OD-2 policy change.

## Local Regression Evidence

**282 unique focused pytest nodes passed across the recorded acceptance runs; zero skips or xfails in those accepted nodes.** This is not 282 distinct new tests and is not a full-repository CI claim.

| Run | Observed result |
| --- | --- |
| WF04 / M6 / H1 plus initial seven B1 tests | 84 passed, 1 temp-directory setup error; process rc=1. The errored workspace test later passed with explicit disposable basetemp. |
| B1 matrix/unit suite plus workspace retry | 58 passed, rc=0, normal exit |
| B1 four-vertical/M6 extended exact parity | 7 passed, rc=0, normal exit |
| Integrity, maturity rejection, API isolation and multi-Senior | 110 passed, rc=0, normal exit |
| Run History and historical export lineage | 30 passed, rc=0, normal exit |
| Public repository source scan | PASS; rerun on final source recorded in package |
| Python compilation / diff hygiene | PASS; final check recorded in package |

The first sandboxed API/Integrity attempt stopped making CPU progress and was terminated only after its own PID/command was verified. The same suites then completed outside the sandbox with per-test progress/stack diagnostics (110 PASS in 49.81 s). That interrupted attempt is not counted as acceptance. An early synthetic test-fixture missing-policy argument was corrected before acceptance; no production formula was altered to make it pass. The initial benchmark-driver relative output-path issue was corrected before the accepted paired run; its unpaired startup sample is not included.

Governance checks are deliberately not self-updated: post-commit results and exact blocker nodes are supplied separately in the review package. A new unapproved financial blob must be rejected by released-authority lookup. Existing historical pins and negative tests remain unchanged. No exact-head GitHub CI was triggered or claimed green because publication remains blocked.

## Performance Method

Windows 11 build 26200, AMD64 Family 25 Model 68, 12 logical CPUs, Python 3.12.10 64-bit. One fresh process per sample, cleared policy-result cache, identical factory inputs, alternating AB/BA order; no other financial test job from this workstream ran during accepted timings. Time covers `run_clean_production`, not imports, input construction, output flattening or a browser/HTTP route.

Five samples per arm for five representative performance workloads; not five samples for each of the 49 equivalence cases. Independent profiles follow timing and do not enter timing statistics. The nearest-rank p95 for n=5 is the observed maximum, not a statistically established service tail. No CPU-affinity/frequency isolation was imposed. Standard S50's 1.57% median change is within desktop noise and is not a credible broad speedup claim. S16/Wind savings are substantial across the paired samples.

| Case | Baseline median / p95 seconds | B1 median / p95 seconds | Median saving |
| --- | --- | --- | --- |
| S50 | 2.070 / 2.331 | 2.037 / 2.129 | 1.57% |
| S16 | 18.000 / 18.586 | 13.654 / 14.350 | 24.15% |
| W25r-dscr2.0 | 11.141 / 11.323 | 7.273 / 7.713 | 34.72% |
| DC | 1.115 / 1.169 | 0.952 / 1.122 | 14.62% |
| W25-dsra12 | 3.480 / 3.833 | 2.314 / 2.988 | 33.51% |

All 50 timed and 10 separately profiled outcome digests matched within their workload. Raw samples/profiles are included in the private review archive; committed sanitized summary is `V9B1_MEASUREMENTS.json`.

### Profiled Operation Counts: Baseline / B1

| Case | G2A iterations | Capacity passes | Funded Senior passes | Senior solves | Tax/CFADS calls | B1 fallbacks |
| --- | --- | --- | --- | --- | --- | --- |
| S50 | 34 / 34 | 34 / 17 | 35 / 35 | 279 / 262 | 1888 / 1701 | 0 |
| S16 | 166 / 166 | 166 / 19 | 299 / 299 | 2879 / 1978 | 17175 / 13143 | 0 |
| W25r-dscr2.0 | 121 / 121 | 121 / 12 | 143 / 143 | 1632 / 941 | 8854 / 5836 | 0 |
| DC | 22 / 22 | 22 / 11 | 22 / 22 | 198 / 187 | 682 / 627 | 0 |
| W25-dsra12 | 16 / 17 | 17 / 4 | 29 / 32 | 344 / 254 | 1703 / 1377 | 1 |

Feasible funded iterations/model inputs and published iteration evidence remain identical. Counts include existing outer IDC/DSRA evaluations and strict funded refinement, hence one capacity pass per completed inner solve is not one per whole Run. The rejected W25 DSRA case performs one canonical re-decision, with extra local funded work and the original exact refusal preserved. Other rejected inputs have equivalence coverage but not five-sample performance distributions.

### Peak Process Working Set, MiB (Maximum Across Five Timing Samples)

| Case | Baseline | B1 |
| --- | --- | --- |
| S50 | 113.23 | 107.30 |
| S16 | 116.39 | 115.39 |
| W25r-dscr2.0 | 129.48 | 128.59 |
| DC | 69.23 | 67.84 |
| W25-dsra12 | 122.39 | 112.84 |

OS process peaks include imports and result serialization, not just financial execution, and do not prove absence of a long-lived-service memory leak. No memory/execution failure occurred in accepted timed/profiled samples.

## Files and Review Package

The exact Git changed-file inventory, protected source bytes, baseline source, full patch, commit/tree/parent, JUnit, retained development/environment attempts, raw financial comparisons and benchmark records are supplied in the ZIP. Production change is 45 insertions / 6 deletions in one file; remaining files are focused tests, a new baseline fingerprint fixture, standalone tools and review documents. No unrelated branch was modified.

## Remaining Approvals Only

1. **Independent exact-content financial review + Financial Owner OD-5** for the final blob above, including failure-order preservation and the measured scope/limitations.
2. **Explicitly scoped additive exact-path/blob governance successor and any necessary historical guard alignment**, preserving every historical map and negative protection. No such authorization exists yet.
3. After those approvals: authorized normal publication as one Draft PR and complete mandatory exact-head GitHub CI, followed by independent final review. None of that has been executed or represented as approved.

Quarterly execution/integration is not claimed; #320 remains isolated/release-closed. The later normal-merge procedure and #322 interaction are documented separately. V9-B2 is design only, with OD-1/2/3/4/6 and the separate FD-1--FD-8 record unresolved; it is not an implemented optimization or a B1 release shortcut.
