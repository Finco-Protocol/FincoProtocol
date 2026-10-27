# Test report (local, Python 3.12 virtualenv matching CI; real Chromium for the browser role)

Exact-head hosted CI is **not** in this file; it is in `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md`. Everything below is local evidence on the commits named there.

## Python suites added or changed by RC-M

| Suite | Tests | What it proves |
|---|---|---|
| `test_model_react_rcm_new_project_v1.py` | 33 | options/preview/create contract, release posture per vertical, CSRF order, bounded validation, preview ≡ canonical service, wizard twin ≡ direct create, unknown outcomes |
| `test_model_react_rcm_new_project_atomic_v1.py` | 20 | request-keyed creation through the canonical authority: crash injected at every step, single-row identity, abandon CAS, two-worker race fenced only by the request index, demo budget read from the database, legacy-database column order |
| `test_model_react_rcm_new_project_multiprocess_v1.py` | 10 | **three real uvicorn processes on one database**: simultaneous same-id POSTs → one project; process killed after the row / inside the seed transaction / before the response; replay after a lost response; users isolated; CSRF 403 never creates; demo budget across processes; closed/unknown technologies and extra source fields create nothing |
| `test_model_react_rcm_f01_rate_matrix_v1.py` | 22 | Wizard → Create → Open → Financing → Save → Reload → Run for four verticals at 0.056 / 0.56 / 5.60 / 9.00 % (effective 0.00056 / 0.0056 / 0.056 / 0.09 read from F01's `senior_rate_authority`); previews never write a Run, history or Working Copy change |
| `test_model_react_rcm_capex_profile_v1.py` | 3 | Goal Seek binds the same CAPEX profile as Legacy |
| `test_model_react_rcm_sensitivity_v1.py` | 23 | access order, bounded budgets, strip/3×3 matrix parity with the Legacy routes, rate-lock refusal |
| `test_model_react_rcm_goal_seek_v1.py` | 27 | solve and Apply parity with Legacy, candidate-bound CSRF, writer barriers behind a validly signed forged candidate, owner scoping, protected reference |
| `test_model_react_rcm_goal_seek_review_v1.py` | 15 | stale candidate refused after a Working Copy edit / scenario switch / contract-owned price; preview side-effect-free; heavy GETs refuse before any engine capacity; busy engine → one 429, no server retry |
| `test_model_react_rcm_financing_v1.py` | 28 | studio view ≡ `build_view`, typed configuration round-trip, rate-schedule lock, STALE without Run |
| `test_model_react_rcm_investors_v1.py` | 17 | investor evidence ≡ Legacy workspace, 60/40 split, CAS |
| `test_persistence_create_request_index_migration.py` | 14 | fresh / legacy database migration order (column first, index second), exact index SQL, preserved rows and historical metadata, idempotent re-run, database-level one-project-per-(user, request), concurrent processes, malformed/NULL metadata, duplicate identities fail closed with a diagnostic and are never recorded as migrated, lock contention, interrupted migration + retry |
| `test_persistence_schema_once.py` (existing) | 21 | schema initialisation once per file and schema version, incl. the legacy-database migration that Correction D repaired |
| `test_rcm_governance.py` | 30 | six-path additive successor layer, exact-change proof for the asset router, consolidation import tail, acceptance modules not collected / no skip / unique names, protected-path guard, analysis-activation shape proof |
| `test_rcm_adapter_csrf_successor.py` | 28 | exact-blob + AST proof of the CSRF-bound POST modules incl. order `_validate → check_demo_rate_limit → create_reference_seeded_project_once` and candidate-bound token; structural negatives |
| `test_rcm_asset_version.py` | 6 | content-derived cache-buster (see `08` item 4) |
| `test_ci_v3_rcm_collection_governance.py` | 6 | the CI V3 reconciliation gate still refuses added/removed/changed collection skips and removed nodes; no RC-M module has a collection-time skip |
| `test_ci_v3_outcome_reconciliation.py` (extended) | 36 | exact-blob Trust-scope reviewed entry and its negatives |

Local sequence required by Correction D (Python 3.12 virtualenv): atomic-create + multi-process + wizard + F01 (`test_finval_f01_*`, `test_finval_rate_*`) + rate matrix + `test_model_v2_persistence` + RC-M governance + CSRF successor —
**367 passed, 0 failed** (12 min). Schema suites: 35 passed (`test_persistence_create_request_index_migration.py` + `test_persistence_schema_once.py`).

Broad regression of the 211 files that reference the creation authority, the baseline comparison, F01 and CI V3 tools: **5,876 passed, 15 skipped, 4 failed**. The four failures reproduce identically on unmodified `main` (`cf7056de`) and are
not caused by this branch: three CI V3 tests refuse to run as the sandbox's root user ("test containers require a non-root host identity"; CI runners are non-root) and `test_api_b04_placeholders_not_links` (a navigation assertion).

## Browser (mandatory consolidation role)

**165 passed, 0 failed, 0 skipped** (106 pre-existing + 59 RC-M nodes), 781 s; CI's `validate_consolidation` accepts the inventory, JUnit and screenshots. See `06_…`.

## Mutation checks (the tests must fail when the protection is removed)

* Atomic create: a non-unique request index fails the two-worker test and the direct-INSERT test; removing the seed transaction fails the atomic tests.
* Migration order (Correction D): restoring the index creation to its old position (before `replay_metadata_json` is ensured) fails six tests, including the original `test_legacy_database_is_migrated_on_its_first_connection`.

## Collection governance

Collecting the whole `tests/` tree with Chromium's driver blocked (as in the CI plan environment), measured at the Correction B head: `main` 20,085 tests / 66 collection skips; this branch 20,306 tests / **66 collection skips, identical list**. Later commits only add tests; the hosted plan job re-runs the authenticated collection and reconciliation on every head (see `09`).

## Public safety

`python tools/public_safety_scan.py` on the whole tracked tree: `PUBLIC_REPOSITORY_SAFETY_SCAN_PASS` (scanner and allowlist unchanged).

## Bundle

`npm run build` in `frontend/` reproduces `static/react/finco-react.{js,css}` byte for byte (git blobs `b99bf91a…` / `add7ddc5…`).

## Not run / not claimed

No deployed environment was touched; no rate-dependent parity (F01 unmerged); no cross-browser, screen-reader or visual-regression run; the Python 3.13 sandbox default is not CI's interpreter (four
governance AST pins fail under 3.13 on unmodified `main`), so every number above is from 3.12.
