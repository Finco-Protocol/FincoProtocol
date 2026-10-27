# Live GitHub preflight

Verified live through the GitHub API at the start of this session (2026-10-27) and again before the push.

| Item | Value |
|---|---|
| `main` HEAD | `cf7056de4078ca66afcf52265a9bacafe35586f7` (merge of PR #386) |
| `main` tree | `ba03a27692ca7bf47fb0170fd4fd5822f34ae4aa` |
| PR #386 | **merged** into main (head `0d405b274bfcc6d8ab37fc68b405b50762395ce2`, base `8d9cccc7…`, merged 2026-10-27T06:53:42Z) — it is no longer Draft; the prompt's "still Draft" premise was out of date, so no candidate-merge of an unreviewed #386 was needed |
| PR #387 | merged: `main` carries `8d9cccc7 Merge PR #387: V11 P0-B generation-aware executor recovery` |
| FIN-VAL **F01** (interest-rate) PR | **not found** (searched all PRs for "F01 interest rate"; only #386's text mentions it). Treated as **unmerged**: no rate default, rate-contract repair or rate-dependent financial parity is claimed |
| Open PRs touching React / `frontend/` / `static/react` / the workspace router | none (open PRs are dependabot, performance V8/V9, RC-7 and yield branches) |
| RC-M branch | `claude/new-session-6o4z8l`, created from `main` `cf7056de`; ahead 4 / behind 0 at the time of the push (before this documentation commit) |
| Merge-base with `main` | `cf7056de4078ca66afcf52265a9bacafe35586f7` |
| History rules | ordinary commits only; no rebase, squash, cherry-pick or force push |

## Environment facts that affected verification

* The checkout started **shallow**; `git fetch --unshallow` was run so the immutable-ancestry governance tests could be evaluated.
* CI runs **Python 3.12** and several governance pins hash an AST; four governance tests fail on *unmodified main* under Python 3.13 (this
  sandbox's default). All verification below therefore used a Python 3.12 virtualenv with `requirements.txt` + `constraints.txt` and
  `playwright==1.63.0`, matching the CI browser job.
* The two audit archives and the previous React evidence named in the task were **not available in this environment** (only the task
  statement was supplied); findings were therefore reproduced against the live code and in real Chromium. `GAP-R*` rows not named in the
  task text cannot be re-derived here — see the register.

Exact-head CI for the final PR head is recorded in `09_RC_M_INTEGRATION_CI_AND_FINAL_REVIEW.md`.
