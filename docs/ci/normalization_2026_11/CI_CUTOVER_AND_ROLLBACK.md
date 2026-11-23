# CI cutover and rollback (Model repository)

## Fixed references

| Item | Value |
|---|---|
| Last main with CI V3/V4/V5 active | `707e68b290694c57b470f4a112c190abb3d02ac9` (tree `0d4e8961c33e7bab7aa94077ee4fe9b561061ba2`) |
| Preserved reference | that commit is permanent `main` history. Optional tag (the agent's git proxy refused tag pushes): `git tag -a ci-governance-v4-final 707e68b2 -m 'last CI V4/V5 main' && git push origin ci-governance-v4-final` |
| Normalization PR | Finco-Protocol/FincoProtocol#476 (branch `claude/bold-heisenberg-fofrq0`) |
| New required context | **`Model CI / required`** (check run name `required`, app GitHub Actions) |

## Why an owner step is needed (the expected bootstrap deadlock)

Branch protection on `main` cannot be read with the agent's token (`GET .../branches/main/protection` → HTTP 403
"Resource not accessible by integration"), so the agent cannot change it either. #476 deletes the old workflows in its own
head, so the old required checks never report on it, and the old `pull_request_target` V5 gate (runs from main) keeps
failing. `main`'s current CODEOWNERS names only `@FincoProtocol`, which is also the PR author, so a code-owner review
cannot be satisfied by anyone else until #476 lands. These are exactly the old-system rejections the mandate
anticipated; they are not failures of the new gate.

Required checks observed on recent PRs (verify the exact list on the settings page before removing anything):
`CI V4 gate` (CI V4 PR), `rate-contract-native-and-browser` (FIN-VAL F01), `dependency-audit`, `compile-and-safety`,
`authoritative-history` (Governance Full History), `mandatory-browser-evidence` (Protocol UI Browser), commit status
`CI Performance Budget`, possibly `V5 gate (trusted base)`.

## Owner steps (copy-ready)

1. **Freeze.** No other merges to `main` and no deploys until step 6 is done.
2. **Backup.** Settings → Branches → `main` rule (or Settings → Rules → Rulesets) → screenshot or export the full
   configuration, and save it with the evidence package. Commit `707e68b2` preserves the code side.
3. **Confirm the new gate on #476.** On Finco-Protocol/FincoProtocol#476, check that the latest commit shows **`required` ✓** (Model CI)
   with all 16 `tests (n/16)`, `static`, `boot-smoke`, `finance` and `acceptance` green. `known-defects` is expected red
   (advisory, 26 listed baseline defects).
4. **Switch required checks** (same settings page, *Require status checks to pass before merging*):
   - add **`required`** (pick the one from *GitHub Actions*; it is produced by workflow *Model CI*),
   - remove the old contexts listed above,
   - keep *Require branches to be up to date* if it was on,
   - leave admin enforcement and force-push/deletion protection as they were.
   Under *Require a pull request before merging*, keep *Require review from Code Owners* on.
5. **Review and merge #476.** Approve #476 as `@xofisamba` (an authentic review; an agent comment is not a review). If the
   code-owner requirement still blocks because main's CODEOWNERS names only `@FincoProtocol`, use a single
   documented *bypass* for this PR only (record actor, time, reason "CI normalization bootstrap, #476", proof = green
   `required`), merge with **Create a merge commit**, then confirm bypass is not left enabled for anyone else.
6. **Post-merge verification.** On `main`: the push run of *Model CI* is green; open a trivial docs PR and check that
   only `required` is requested and that it goes green; check that no old status is still expected.
7. **Environment for releases.** Settings → Environments → New environment `production` → *Required reviewers*:
   `xofisamba`. `release_gate.yml` waits on it.
8. **Radar** (separate repository): see `docs/ci/normalization_2026_11/OPEN_DEFECTS_AND_NEXT.md` (billing blocker).

## Rollback

If the new gate misbehaves after cutover:

1. Freeze merges and deploys.
2. Restore the saved branch-protection configuration (step 2 backup) so the old contexts are required again.
3. Revert the merge commit of #476 with an ordinary `git revert -m 1 <merge-sha>` PR (no reset, no force push). That
   restores the old workflows, tools and tests byte-for-byte from history.
4. Re-run the old checks on the revert PR and merge it under the restored rules.

No step requires deleting history; the archive and commit `707e68b2` keep every original byte.
