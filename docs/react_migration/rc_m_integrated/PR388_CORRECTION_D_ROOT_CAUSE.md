# PR #388 — Correction D: root causes

## RC-1 — worker-0 failure on `248d9112` (run 40513286161): SQLite migration order — **CLOSED**

* Failing node: `tests/test_persistence_schema_once.py::test_legacy_database_is_migrated_on_its_first_connection` → `sqlite3.OperationalError: no such column: replay_metadata_json`.
* Cause: `_init_schema` (`app/persistence/db.py`) created the partial unique index `ux_projects_user_create_request` (it reads `projects.replay_metadata_json`) immediately after the `projects` table's legacy index, i.e. **before** `_ensure_column(projects, replay_metadata_json)`. A database created before that column existed could not complete its first connection.
* Fix (commit `05bf0722`): the same statement, byte for byte, now follows `_ensure_column(projects, replay_metadata_json)` and `full_inputs_json`. A conflict in existing data (rows already sharing one `(user_id, request id)`) raises a `RuntimeError` with a query that lists the duplicates;
  nothing is dropped or rewritten and the schema is never recorded as ready (commit `9ac495c8`).
* Evidence: previously failing node passes; `tests/test_persistence_schema_once.py` (21) + `tests/test_persistence_create_request_index_migration.py` (14) = 35 passed; restoring the old order fails six of them including the original node (negative control);
  **hosted exact-head evidence: worker-0 of run 40522709690 (head `9ac495c8`) executed its 5,190 original nodes with pytest exit 0.** The historical failure is closed.

## RC-2 — workers 1 and 3 on `9ac495c8` (run 40522709690): hosted cold-start readiness refusal — **NOT a defect of this PR; unresolved at the CI-contract level**

See `PR388_CALIBRATION_EVIDENCE.md`: exit 124 returned by the calibration gate before pytest started; first cold sample 0.802 s / 0.704 s versus the 0.600 s maximum; the probe's inputs are byte-identical to `main`.
Not mislabelled as a pytest failure or a runner timeout.

## RC-3 — `aggregate`, `tests`, `mandatory-evidence` on `9ac495c8`

Consequence of RC-2 ("fail on any selected worker failure"). Each of the other five workflow runs on the head is green (see `09_…`).
