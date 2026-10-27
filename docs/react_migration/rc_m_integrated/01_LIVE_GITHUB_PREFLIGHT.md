# Live GitHub preflight

Verified live through the GitHub API at the start of this session (2026-10-27) and again before the push.

| Item | Value |
|---|---|
| `main` HEAD | `cf7056de4078ca66afcf52265a9bacafe35586f7` (merge of PR #386) |
| `main` tree | `ba03a27692ca7bf47fb0170fd4fd5822f34ae4aa` |
| PR #386 | **merged** into main (head `0d405b274bfcc6d8ab37fc68b405b50762395ce2`, base `8d9cccc7…`, merged 2026-10-27T06:53:42Z) — it is no longer Draft; the prompt's "still Draft" premise was out of date, so no candidate-merge of an unreviewed #386 was needed |
| PR #387 | merged: `main` carries `8d9cccc7 Merge PR #387: V11 P0-B generation-aware executor recovery` |
| FIN-VAL **F01** (interest-rate) PR | not found at the original preflight; later opened as #389 and merged — see the Correction C section below |
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

## Correction B preflight (live, 2026-10-27)

| Item | Value |
|---|---|
| `main` | unchanged: HEAD `cf7056de4078ca66afcf52265a9bacafe35586f7`, tree `ba03a27692ca7bf47fb0170fd4fd5822f34ae4aa` |
| PR #388 | open **Draft**, remote head `634fdf609e1309ed0959f9b21502fefd68f43f43`, base `cf7056de`, 72 changed files at that head, `mergeable_state: unstable` (red checks), no reviews, no review threads |
| PR #389 (FIN-VAL F01) | open **Draft**, head `d53400a634bbaed8013c545dfa74b35991b9f436`, 234 changed files, **not merged**; it changes `projects_repository.py`, `project_library_service.py`, `app/v2/router.py`, `update_service.py`, `input_adapter.py` and pins their exact blobs in `tests/finval_f01_scope.py` |
| Confirmed red checks on `634fdf60` | `compile-and-safety`, `source-safety`, `safety-and-smoke / plan` and the dependent `aggregate`, `tests`, `mandatory-evidence`; green: `route`, `mandatory-browser-evidence`, `authoritative-history`, `dependency-audit` |
| Correction commits | local, not yet pushed at the time of writing; the pushed head and its exact-head CI are in `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md` |

## Correction C preflight (live, 2026-10-27)

| Item | Value |
|---|---|
| `main` | `128bf0c2b79af56985326543132cc806ff7f001c`, tree `459d67a89c8c204f03d364dbba2242c168dea5bf` — PR #389 (FIN-VAL F01) merged (`Merge pull request #389 from Finco-Protocol/fix/finval-f01-complete`) |
| PR #388 before the sync | remote head `0ee2f5eca9673a8625bf0ceb6cd4262e4642b7e7`, Draft, no reviews or review threads; merge-base `cf7056de…`, 13 behind `main` |
| Exact-head CI on `0ee2f5ec` | green: compile-and-safety, source-safety, plan (collection governance), route, dependency-audit, authoritative-history, workers 0 and 1. Red: workers 2, 3, 4 (four governance tests: Trust-scope reconciliation, CI V3 tool-import separation, CAPEX-folding classification, native-activation inventory), mandatory-browser-evidence (3 of 165 nodes), and the dependent aggregate / tests / mandatory-evidence jobs |
| Sync | ordinary merge of `main` into the branch; conflicts only in `tests/model_mutation_security_successor.py`, `tests/test_model_mutation_security_successor.py`, `tests/test_model_react_overnight_b_governance.py`, resolved by keeping both layers |

Exact-head CI for the final PR head is recorded in `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md`.
