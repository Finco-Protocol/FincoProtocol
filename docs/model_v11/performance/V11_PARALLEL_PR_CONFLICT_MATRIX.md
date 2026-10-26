# V11 — Parallel PR conflict matrix (live, 2026-10-26)

`main` HEAD 8944aca351ef89c81a8a9bf715ab352629c35624, tree 3448aeb245ff118fde0907541dfe40ace42a86d8.

| PR | State | HEAD | Behind main | Touches P2a file (`run_history_repository.py`) | Touches `model_execution.py` | Other overlap |
|---|---|---|---|---|---|---|
| #381 SEC-01/02 | merged, ancestor of main | 787aa5ca | — | — | — | — |
| #382 FIN-VAL B1 | merged, ancestor of main | e7bdb9f6 | — | — | — | — |
| #383 FIN-VAL B2/C1 | open, draft, mergeable_state `unstable` | dfc1a585 (was 8422adbe at session start; re-checked at push) | 0 | no | no | `app/v2/router.py` (not edited by this PR) |
| #384 D-029 | open, draft, `unstable` | 5b05cc8d (was e8e33afb at session start; re-checked at push) | 0 | no (adds `run_intent_repository.py`, `run_intent_service.py`) | no | future Run History write integration may touch the shared file |
| #321, #328 (old drafts) | draft | — | — | no | **yes** (`model_execution.py`) | stale performance branches; relevant to P1 sequencing only |

Rules followed: no edits to #383/#384 files or branches; no changes to `v2_atomic_run_commit`, reservation tables, retry/replay policy or History append; P2a is a read-only decoder change. If #384 later changes `run_history_repository.py`, stop and integrate explicitly. Plain merge only; no rebase/squash/cherry-pick/force-push.
