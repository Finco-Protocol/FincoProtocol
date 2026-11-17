# P1: activation procedure for the U1 node split and the CI Performance Budget guard

## States (exactly one applies at any time; projections never move a state)

| State | Definition | Evidence required |
|---|---|---|
| `PREPARED` | The P1 Draft PR contains the policy, weights, guard code, workflow and tests; all local tests pass. Nothing runs on GitHub yet: the scheduler and the guard read the **trusted base** (`main`), which does not contain P1. | This PR, its local test logs, the simulation. |
| `ACTIVE` | P1 is merged by the owner **and** the owner has added the status check `CI Performance Budget` to the required checks of `main` (step 3). From then on every PR is scheduled with the U1 split and is blocked unless the guard writes `success`. | Branch-protection screenshot or API output listing the context; first guard status on a PR. |
| `VERIFIED` | A benign PR opened after `ACTIVE` has all six required workflows green **and** a guard `success` with end-to-end ≤ 2,400 s, measured by the guard from GitHub timestamps. | The PR's commit-status page and the guard run summary (top-20 nodes, shard durations). |

`ACTIVE` without `VERIFIED` means the controls exist, not that the target is met. If the first benign PR is over budget, the label is
`PERFORMANCE_TARGET_NOT_MET` and the guard has done its job by blocking it.

## Prerequisite (V4 governance)

On `main` d32f4987, V4 governance rejects this PR's control paths (measured, see `00_EXECUTIVE_VERDICT_HR.md`):

- `docs/ci_v4/node_split_policy.json` and `docs/ci_v4/node_weights.json`: 44 cohorts reject them, because B1, B2, B3, V5 bootstrap, V5-2B, V5-3, FULL-recovery and P0 each hold an unconditional FROZEN equality to their BASE blob.
- `.github/workflows/ci_perf_guard.yml` and `tools/ci_perf_guard.py`: 17 early cohorts reject any new `.github/` or `tools/` path.

The owner must decide between:
- (a) an owner-authorised governance successor that teaches those FROZEN predicates and the CI-path hook to accept exactly these literal pins; or
- (b) merging P1 with the V4 governance check red, explicitly overriding it once.

The guard and the split cannot become `ACTIVE` before one of these happens.

## Owner steps after the merge (in order)

1. **Confirm the guard runs.** On the next PR, open *Actions → CI performance budget guard*. One run per completed required workflow. The commit-status list of the PR head shows `CI Performance Budget` as `pending`, then `success` or `failure`.
2. **Confirm the split is scheduled.** In that PR's *CI V4 PR → plan* artifact, `ci-v4-plan.json` must contain a `node_split.modules["tests/test_u1_scope.py"]` entry with `parts: 3`, and `schedule.workers` must be 4.
3. **Make the guard required.** Settings → Branches → the `main` protection rule (or the ruleset) → *Require status checks to pass* → add **`CI Performance Budget`**. Choose the source "any" (it is a commit status, not a check run) and keep every existing required check.
   API equivalent, admin token only, run by the owner:
   ```
   gh api repos/Finco-Protocol/FincoProtocol/branches/main/protection/required_status_checks/contexts -X POST -f 'contexts[]=CI Performance Budget'
   ```
   This adds one context and removes nothing.
4. **Verify.** Open one benign PR, such as a documentation typo that still needs its own exact-source admission. Record the guard's verdict and summary. Only an end-to-end ≤ 2,400 s `success` there makes the state `VERIFIED`.

## Rollback

Remove the context `CI Performance Budget` from the required checks. The guard keeps writing an informative status. To stop it completely, delete `.github/workflows/ci_perf_guard.yml` on `main`. To undo the split, move U1 back to `not_split` in `node_split_policy.json`. Every rollback is one reviewed commit; no test, timeout or required check is touched.

## Terminal conditions of the guard (why it can never hang or block itself)

- **Triggers.** It runs on `workflow_run: completed` of the six required workflows and on a 15-minute sweep. It is never part of its own required list, and its verdict is a commit status written by the API, not its own job conclusion.
- **One evaluation per run.** A run makes a single evaluation and never sleeps or polls; `timeout-minutes: 10`.
- **PENDING** only while a required run is missing or unfinished, and less than 2,400 s have passed since the first required run's `created_at`.
- **FAILURE** in every other incomplete situation, including a missing run, an unfinished run after the budget, missing or forged artifacts, or JUnit that disagrees with GitHub's step durations. The sweep turns a stale pending into FAILURE after the budget.
- **SUCCESS** only on complete, digest-verified evidence within every limit.

## Trust model of `workflow_run`

- GitHub runs a `workflow_run` / `schedule` workflow from the **default branch**. A PR cannot change the guard, its policy or its baseline for its own judgement. The job also refuses any `github.ref` other than the default branch.
- It checks out `github.sha` (the default-branch commit) with `persist-credentials: false`. It never checks out, imports or executes the PR head. PR artifacts are downloaded through the API as data, size-capped, digest-verified and parsed without DTD/entities.
- Token: `actions: read`, `contents: read`, `pull-requests: read`, `statuses: write`. No secret is exposed to PR code, because no PR code runs in this job.
- PR code writes the JUnit, so per-node times are attestations. The decisive budgets (end-to-end, shard duration) come from GitHub's own run and job timestamps. JUnit whose summed time differs from GitHub's test-step duration by more than −20 % / +3 % is rejected.
