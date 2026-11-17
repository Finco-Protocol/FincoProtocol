# P1: activation procedure for the U1 node split and the CI Performance Budget guard

## States (exactly one applies at any time; projections never move a state)

| State | Definition | Evidence required |
|---|---|---|
| `PREPARED` | The P1 Draft PR contains the policy, weights, guard code, workflow and tests; all local tests pass. Nothing runs on GitHub yet: the scheduler and the guard read the **trusted base** (`main`), which does not contain P1. | This PR, its local test logs, the simulation. |
| `ACTIVE` | P1 is merged by the owner **and** the owner has added the status check `CI Performance Budget` to the required checks of `main` (step 3). From then on every PR is scheduled with the U1 split and is blocked unless the guard writes `success`. | Branch-protection screenshot or API output listing the context; first guard status on a PR. |
| `VERIFIED` | A benign PR opened after `ACTIVE` has all six required workflows green **and** a guard `success` with end-to-end ≤ 2,400 s, measured by the guard from GitHub timestamps. | The PR's commit-status page and the guard run summary (top-20 nodes, shard durations). |

`ACTIVE` without `VERIFIED` means the controls exist, not that the target is met. If the first benign PR is over budget, the label is
`PERFORMANCE_TARGET_NOT_MET` and the guard has done its job by blocking it.

## Prerequisite (V4 governance): resolved in Correction A

`99b8661b` was rejected by 44 cohorts. Correction A admits the P1 paths through finite literal handoffs inside the existing P0 terminal (no 49th cohort):
- the FROZEN predicates of B1, B2, B3, V5 bootstrap, V5-2B, V5-3 and FULL recovery, and their tests, accept `node_split_policy.json` / `node_weights.json` **only** at the exact P0 pin;
- the CI V4 cohort admits **only** `P0.CI_PATHS` (`ci_perf_guard.yml`, `ci_perf_guard.py`).

The central governance gate is PASS with 48/48 cohorts exact. Every other path, blob, mode or prefix is still rejected (negative tests in `tests/test_ci_v4_p0_scope.py`).

V4 trusts the terminal manifest `docs/ci_v4/p0_40min/SOURCE_SUCCESSOR.json`: a change that re-pins it consistently is accepted by self-consistency alone. This was already true before P1, and owner review of that file is the control.

## Owner steps after the merge (in order)

1. **Confirm the guard runs.** On the next PR, open *Actions → CI performance budget guard*. One run per completed required workflow. The commit-status list of the PR head shows `CI Performance Budget` as `pending`, then `success` or `failure`.
2. **Confirm the split is scheduled.** In that PR's *CI V4 PR → plan* artifact, `ci-v4-plan.json` must contain a `node_split.modules["tests/test_u1_scope.py"]` entry with `parts: 3`, and `schedule.workers` must be 4.
3. **Make the guard required.** Settings → Branches → the `main` protection rule (or the ruleset) → *Require status checks to pass* → add **`CI Performance Budget`**. Keep every existing required check. Where the ruleset offers it, restrict the expected source to the **GitHub Actions** app; otherwise "any". The sweep re-verifies every `success` within 15 minutes, and V4 rejects any new `.github/` path, so a status forged by another workflow does not survive.
   API equivalent, admin token only, run by the owner:
   ```
   gh api repos/Finco-Protocol/FincoProtocol/branches/main/protection/required_status_checks/contexts -X POST -f 'contexts[]=CI Performance Budget'
   ```
   This adds one context and removes nothing.
4. **Verify.** Open one benign PR, such as a documentation typo that still needs its own exact-source admission. Record the guard's verdict and summary. Only an end-to-end ≤ 2,400 s `success` there makes the state `VERIFIED`.

## Operational notes

- **"Re-run failed jobs"** mixes attempts → `PERFORMANCE_UNVERIFIED` (fail-closed). Use a full re-run or push a new commit.
- **Reopening a PR on an old head:** the clock starts at the first run's creation, so the result is `OVER_BUDGET`. Push a new commit.
- **A transient GitHub API error** (429/5xx/rate-limit): no status is written and the guard run is red; the next event or sweep re-judges. It is never `success`.

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
