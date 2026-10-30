# PR #400 CI V3: stale run-attempt artifact selected by the eight workers. Root cause

Scope: CI transport/provenance only. No financial calculation, pricing, lifecycle semantics, production data, auth/tenant
behaviour, endpoint policy, coverage, accepted-source provenance or protected expected value is changed by this repair.

## 1. Evidence ledger (live GitHub API, 2026-10-30)

| Item | Value |
|---|---|
| PR | #400, branch `codex/wf03-project-lifecycle`, HEAD `2ed3653b62720bb490c048ab58cac6410d279fd2` (tree `b3800b6c705329a8a66045ba1cd24ed86f2d2721`), base `db504f6408cb456c617c9342a1ffa202ee455283` |
| Run | `41099667692` (Public Safety and Model Smoke, run_attempt 2, conclusion failure); synthetic merge `233804888a172e29b80f9a08cd31a98e00d418fa` |
| Attempt 1 plan job | `124214958826`: step 6 (`tools.ci_v3_production plan`) failed at 17:36:17 with `ContractError: GitHub GET failed: 502` inside `authenticate_reference` (`/actions/runs/{rid}/attempts/{attempt}/jobs`), i.e. a transient GitHub API 502 |
| Attempt 1 uploads | `if: always()` uploaded the partial `plan/` (22 files, `baseline/` only) as **`public-ci-v3-plan` → artifact 12999360429** (2,336,444 B, `sha256:3c59ecb4…63e1`) and `runtime-image.tar.gz` as **`ci-v3-runtime` → 12998306825** (`sha256:72611b28…547a`) |
| Attempt 2 | "Re-run failed jobs": `route` and `source-safety` carried over from attempt 1; plan job `124221146894` succeeded and uploaded **`public-ci-v3-plan` → 12998263477** (5,394,667 B, `sha256:75ea1b16…a3d9`, created 17:58:51, includes `plan.json` with run 41099667692 / attempt 2 / 8 workers / 668 owned modules) and **`ci-v3-runtime` → 13000105279** (`sha256:499244e1…6d47`) |
| Attempt 2 workers | e.g. worker-2 job `124224201720`: `download-artifact name: public-ci-v3-plan` downloaded digest `3c59ecb4…63e1` (= **12999360429**, attempt 1); `name: ci-v3-runtime` downloaded **13000105279** (attempt 2). `production_plan()` then raised `FileNotFoundError …/evidence/public-ci-v3-plan/plan.json` → `ContractError: unreadable or truncated JSON evidence` within 1 s, before `docker load` |
| Downstream | `aggregate` (`124225052791`), `tests` (`124225145053`), `mandatory-evidence` (`124225207262`) failed only because of the worker failures: no financial or test verdict was produced |

## 2. Why the stale artifact won

1. GitHub keeps all attempts' artifacts in one run, and a later attempt can reuse a name. Within one attempt a name is unique.
2. The pinned `actions/download-artifact@d3f86a10` resolves `name:` through `@actions/artifact` `getArtifact`. When several artifacts
   share the name, it sorts by **numeric artifact ID, descending**, and takes the first ("returning newest").
3. Artifact IDs are **not creation-ordered**. Attempt 2's plan, created 22 minutes later, received ID 12998263477, which is lower
   than attempt 1's 12999360429. So "newest" picked the attempt-1 baseline-only diagnostic.
4. The same download resolved `ci-v3-runtime` to the attempt-2 archive (13000105279 > 12998306825). Even with a correct plan the
   worker would have mixed attempts. Only the runtime sha256 check in `worker()` would then have stopped it.
5. `download-artifact` reported success, and its digest check only verifies the archive *it* selected. A mismatch is only a warning.
6. Selecting by ID alone does **not** fix this. `artifact-ids:` lists the run with `latest: true`, which keeps one artifact per name
   (the highest ID) *before* filtering by ID. Attempt 2's lower-ID plan would have been dropped ("None of the provided artifact IDs were
   found"). Missing IDs are only a warning.
7. The attempt-1 artifact was published under the authoritative name only because the plan upload step was `if: always()`.
8. `authenticate_current()` required exactly one artifact per fixed name across the whole run. On any rerun that would have failed
   on the historical duplicates even if the worker had downloaded the right one. "Take first/latest" would have been equally wrong.
9. The same by-name rule also affected the aggregate (`pattern: public-ci-v3-*`, `latest: true`) and the accepted-source reference
   authenticator (`tools/ci_v3_source_reference.py`). Once main produced per-attempt names, the authenticator would have found no
   `public-ci-v3-plan` and fallen back to sequential.

## 3. Failure dependency graph (run 41099667692)

```
attempt 1: plan ──(GitHub API 502)──> FAIL ──always()──> public-ci-v3-plan#12999360429 (baseline only)
                                                 └──────> ci-v3-runtime#12998306825
attempt 2 (re-run failed): plan OK ──> public-ci-v3-plan#12998263477 (complete) + ci-v3-runtime#13000105279
        worker-0..7 ──download name=public-ci-v3-plan──> max(id) = 12999360429 (attempt 1)  ✗ no plan.json
                    ──download name=ci-v3-runtime──────> max(id) = 13000105279 (attempt 2)  (attempt mix)
        worker FAIL (1 s, before Docker) ─> aggregate FAIL ─> tests FAIL ─> mandatory-evidence FAIL
```

## 4. Permanent prevention (implemented)

| Edge | Before | After |
|---|---|---|
| plan → artifact | `if: always()` under the authoritative name | `seal` step validates the complete `plan.json` (schema, inventory, partition, context) and that the runtime archive is the one the plan names. It then writes `attempt-seal.json` (run/attempt/source, plan sha256, image, runtime sha256, sha256 of every payload file). Authoritative uploads are `if: success()` only. Partial output goes to `ci-v3-diagnostic-plan-attempt-N` (never matches `public-*`) |
| names | `public-ci-v3-plan`, `ci-v3-runtime`, `public-ci-v3-worker-i`, `public-ci-v3-aggregate` | same names with suffix `-attempt-${{ github.run_attempt }}` (the real GitHub attempt; unique within the run) |
| plan → workers | download by non-unique name | `needs.plan.result == 'success'` explicitly. The first step refuses a plan from another attempt (`plan_attempt` vs `github.run_attempt`) before any download. Download is by the plan job's immutable `artifact-id` outputs (unique names, so `latest:` cannot drop them) |
| worker preflight | `production_plan` plus runtime sha | `preflight()`: seal present and bound to the current run/attempt/source; payload byte manifest equal; plan valid; runtime sha256 equal. All before `docker load`. After load, the image ID must equal the plan's |
| worker → aggregate | `pattern: public-ci-v3-*`, `if: always()` upload | success-only `public-ci-v3-worker-i-attempt-N` (failure → `ci-v3-diagnostic-worker-…`). Aggregate downloads `public-ci-v3-*-attempt-N` and requires `plan_attempt == run_attempt` |
| independent verifier | exactly one per fixed name over all attempts | `authenticate_current()` considers only the current attempt's names. Exactly one non-expired artifact each (plan, runtime, every worker). `workflow_run` id/head bound. Producer job in `/attempts/N/jobs` completed/success. Service archive sha256 equal to the API digest and byte-equal to the download. Seal re-verified. Artifact IDs/digests written to `current-attempt-artifacts.json` and printed. Other attempts' artifacts are never counted or selected |
| accepted reference | fixed names | the reference run's final attempt's scoped names, extracted under the logical folders for that source's own verifier. Legacy unsuffixed runs keep the original rule |
| reruns | undefined | **Re-run all jobs**: fully supported (fresh plan, runtime and workers under the new attempt). **Re-run failed jobs after a successful plan**: the reused plan belongs to an older attempt, so workers fail at the first step (seconds, no download/Docker) with an explicit message, and the verifier also rejects it. Attempts are never mixed |

## 5. Why earlier governance/timeout patches did not address this

The CI-200M/CI-340M budget work (Correction E) and the RC-5/F01 governance corrections (Correction F) changed limits and test
identities. None of them touched artifact identity. The trigger here was a transient API 502 plus a partial rerun, and that path had
never been exercised. A longer timeout cannot fix a wrong artifact selection.

## 6. Additional genuine failure found in Gate 1 (same head, independent of transport)

`tests/test_rc3_integration_inventory.py` failed on `2ed3653b` (13 nodes; reproduced on the untouched head). Correction E moved
`.github/workflows/ci_public_job.yml` to the CI-340M blob `248c1e4e…`. The RC-3 facts whitelist (`post_merge_protected_delta`)
and two test bodies still accepted only RC-5/CI-200M as the *current* worktree. With transport fixed, these would have turned the
8-worker run red. The repair mirrors Correction F for RC-5: the node IDs are unchanged, and the historical CI-200M contract is
judged on the CI-200M text derived from the pinned RC-5 reference. The worktree must be an exact member of the content-verified
RC-3 → RC-5 → CI-200M → CI-340M chain. No negative was removed; every CI-200M mutation case still has to be rejected.

## 7. Separate, unresolved: slow/hung workers (not today's cause)

The earlier 90-minute worker-2/worker-3 timeouts (older head, run 41076288645) are a **separate performance incident**. They are not
the missing `plan.json` failure and are **not** resolved here. The owner-approved doubled budgets stay as safeguards only. Follow-up
proposal (not blocking this repair): from the first green attempt-scoped run, compare per-module elapsed time in
`execution/child/adapter.json` phase durations against the planner's `weights.json` / `timing-provenance.json` critical path.
Identify modules whose measured time exceeds the prediction (shared fixtures, browser/subprocess-heavy modules, resource contention
under 8 parallel runners). Propose a reviewed repartition or fixture fix in a separate protected patch, with no test removal or
deselection.

## 8. Residual risk recorded, not changed

The sequential control path (`ci_public_job.yml`, RC-5/F01-governed, not modified) and `mandatory-evidence` still download
`public-source-safety` / `public-verification-results` / `public-shadow-proof` by name. On a rerun the highest-ID artifact wins
there too. `ci_single_gate.verify_control` binds the exact head, so a stale same-head artifact can only cause a false red, never a
false green. Changing those historical names needs its own RC-5-governed successor.
