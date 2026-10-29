# Request: Financial Owner path authorisation for atomic Save All

Not a financial-methodology change: no formula, engine, SHL/CAPACITY, DSCR, GEARING_CAP, Run Integrity, golden or native path is touched. It composes existing validators in one transaction.

| Path (all under pinned `app/`) | Minimal change |
|---|---|
| `app/persistence/workspace_repository.py` | Split `v2_atomic_batch_draft_update` into `_apply_scalar_batch(cur, …)` (the existing body between `BEGIN` and `COMMIT`, unchanged) and the existing function as a wrapper with identical behaviour. |
| `app/workbook/revenue_contracts_service.py` | Same split for `save_contracts` (`_save_contracts_in_tx(cur, …)`). |
| `app/v2/cost_batch_commands.py` / `app/v2/capex_commands.py` | Expose the loop in `update_cost_lines_batch` as `apply_cost_lines_in_tx(cur, …)`; `_exclusive_tx` remains the wrapper. |
| `app/v2/save_all_commands.py` (new) | `save_all(...)`: one `BEGIN EXCLUSIVE`, one CAS, the three bodies in fixed order, one final identity, one commit; per-item verdicts. |
| `app/v2/grid_router.py` | One route `POST /workbook/save-all` (JSON, `mutation_token(..., "save-all")`, session + owner checks identical to `_resolve`). |
| `app/v2/react_workspace_router.py` | Publish `save_all` capability (`available`, `url`, `csrf_token`, `sections`) in the workspace projection. |
| `app/persistence/db.py` (optional) | `save_all_requests(request_id, user_id, project_id, body_sha256, outcome_json, created_at)` for idempotent replay. |
| `tests/` exact-source cohort + `docs/react_migration/**/SOURCE_SUCCESSOR.json` | Successor pins for the blobs above with negative-drift controls, following the PR #396 pattern. |

Requested decisions: (1) authorise exactly these paths; (2) idempotency by table or by reconciliation; (3) total item cap; (4) confirm Financing collections (F3) stay outside Save All.

Until then the client reports Save All as **BLOCKED** and every section keeps its own all-or-none Save.
