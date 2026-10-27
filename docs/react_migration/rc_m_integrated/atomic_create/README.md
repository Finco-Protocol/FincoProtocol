# Atomic, request-keyed project creation — APPLIED after FIN-VAL F01 (#389) merged

**Status: integrated in this PR** (merge of `main` `128bf0c2`, then the reviewed change set that had been prepared and tested against the #389 head). New Project is still behind the
`FINCO_MODEL_REACT_V1` flag (default OFF) and nothing here authorizes production use; the release decision remains with independent review.

## What changed (through the canonical creation authority — no second project writer)

* `app/persistence/db.py` — partial unique index `ux_projects_user_create_request` on `(user_id, request id)`; the request id is read from the project row's own `replay_metadata`
  (`json_valid` guards malformed legacy metadata).
* `app/persistence/projects_repository.py` — `find_project_by_create_request`, `abandon_stale_create` (compare-and-set), `save_project(insert_only=True)` so a keyed create can never upsert onto an
  existing `(user, project_code)` row (the pre-existing upsert let two concurrent same-name creates overwrite each other).
* `app/services/project_library_service.py` — `_create_working_copy(…, create_request)`: the request identity is written by the **same single INSERT** as the project row; outcomes `created` |
  `replayed` | `in_progress` | `abandoned`; project-code races are re-planned. `create_working_copy` keeps its signature and behaviour; F01's rate-provenance normalisation is untouched.
* `app/services/reference_seed_service.py` — `create_reference_seeded_project_once(…, create_request_id)`; the seed lines and the `COMPLETE` flag are written in **one `BEGIN IMMEDIATE` transaction**.
  The unkeyed `create_reference_seeded_project` calls the public service exactly as before.
* `app/v2/react_new_project.py` — calls the keyed creator (the interim ledger module is removed). Finished request → 200 replay; in flight or interrupted → 503, nothing written; interrupted past the
  300 s lease → archived `ABANDONED` and the id stays consumed (503); same id with other inputs → 409; nothing is retried automatically.
* `tests/finval_f01_scope.py` — `ATOMIC_CREATE_SUCCESSORS`: the exact blobs of the two F01-pinned creation files, admitted ONLY as alternatives to F01's own blobs (any other drift still fails).

## Proof

* Single process, a crash injected at every step (row, workspace, scenario, seed snapshot, workspace save, CAPEX line, OPEX line): one `CREATING` project, no seed lines, a retry writes nothing, the stale one is archived and
  its id stays consumed, a complete one can never be abandoned; two workers that both saw "no request" create exactly one project (the request index is the only fence there — mutation-checked).
* Three real uvicorn processes on one database: simultaneous same-id POSTs → one project; process killed after the row / inside the seed transaction / after completion; replay after a lost response; users isolated;
  demo budget read from the database by every process; closed/unknown technologies and extra source fields create nothing.
* F01: the wizard-created Working Copy carries `human_percent_v1`; Wizard → Create → Open → Financing → Save → Reload → Run for Solar, Wind, Data Center and EV Charging at 0.056 / 0.56 / 5.60 / 9.00 %
  (`tests/test_model_react_rcm_f01_rate_matrix_v1.py`), and F01's own suites pass on the integrated tree.
* Regression: the creation-related files (132) pass on the patched tree except one failure that also occurs on unmodified `main` (`test_api_b04_placeholders_not_links`); the two clone tests it initially
  broke exposed a real defect of the first draft (the unkeyed path bypassed `create_working_copy`), now fixed.

## Legacy database migration order (Correction D)

`ux_projects_user_create_request` reads `projects.replay_metadata_json`, so `_init_schema` (`app/persistence/db.py`) now creates it **after** `_ensure_column(projects, replay_metadata_json)` and `full_inputs_json`
(it previously sat right after `idx_projects_user_code`, which broke the first connection to a database created before that column existed: `no such column: replay_metadata_json`). The statement itself is
unchanged byte for byte (same partial unique expression, same predicate). A conflict in pre-existing data — two rows already sharing one `(user_id, create_request.request_id)` — fails closed: nothing is dropped
or rewritten, the schema is not recorded as ready, every connection raises a `RuntimeError` with a query that lists the duplicates, and the retry succeeds once an operator resolves them.
Tests: `tests/test_persistence_create_request_index_migration.py` (fresh DB / legacy DB / idempotency / database-level atomicity incl. concurrent processes / negatives: malformed and NULL metadata, duplicate identities,
lock contention, interrupted migration + retry) and `tests/test_persistence_schema_once.py`; reverting the ordering fails six of them, including the original failing test.

## Known limits

The canonical seeded create remains several writes in SQLite (the keyed path makes them detectable and fenced, not one transaction); the unkeyed Legacy `/projects/create` is not keyed; the demo budget is a
read-then-create check, so simultaneous creates by one demo user can overshoot it by the concurrency level.
