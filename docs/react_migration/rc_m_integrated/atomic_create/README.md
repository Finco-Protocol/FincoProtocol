# Atomic, request-keyed project creation — prepared, tested, held until FIN-VAL F01 (#389) merges

**Status: PREPARED AND TESTED, NOT APPLIED.** The creation authority files overlap #389 (which pins their exact blobs). Applying this change before #389 merges would race that branch,
so it is stored as `ATOMIC_CREATE_AFTER_F01.patch` and applied afterwards. Until then the React New Project create is fenced by the adapter-level ledger and the surface is **not
production-ready**; the release gate (`FINCO_MODEL_REACT_V1`, default OFF) stays closed.

## What the patch does

* `app/persistence/db.py` — partial unique index `ux_projects_user_create_request` on `(user_id, request id)` where the request id is read from the project row's own `replay_metadata`
  (malformed legacy metadata is ignored by `json_valid`).
* `app/persistence/projects_repository.py` — `find_project_by_create_request`, `abandon_stale_create` (compare-and-set), `save_project(insert_only=True)` (a keyed create can never upsert onto an
  existing `(user, project_code)` row — the pre-existing upsert let two concurrent same-name creates overwrite each other).
* `app/services/project_library_service.py` — `_create_working_copy(…, create_request)`: the request identity is written by the **same single INSERT** as the project row; replay /
  in-progress / abandoned / conflict outcomes; re-planning on a project-code race. `create_working_copy` keeps its signature and behaviour.
* `app/services/reference_seed_service.py` — `create_reference_seeded_project_once(…, create_request_id)`; the seed lines and the `COMPLETE` flag are written in **one `BEGIN IMMEDIATE`
  transaction**, so a finished request is never a partially seeded project. `create_reference_seeded_project` keeps its signature and behaviour.
* `app/v2/react_new_project.py` — calls the keyed creator; the interim ledger module is removed. Outcomes: `created`/`replayed` → 200; in flight or interrupted → 503 (nothing written);
  interrupted past the 300 s lease → archived `ABANDONED`, the id stays consumed (503); same id with other inputs → 409.
* tests — single-process (crash injected at every step; abandon CAS; two workers that both saw "no request"), three real server processes (`os._exit` after the row, inside the seed
  transaction, after completion), adapter outcome mapping, the successor spec (`create_reference_seeded_project_once` is the only writer, reviewed order), the RC-M guard.

## Proof (local, Python 3.12)

* On the RC-M tree + patch: 62 New Project tests (33 contract + 19 atomic + 10 multi-process) pass; mutation checks: a non-unique request index fails the two-worker test and the direct-INSERT test; removing
  the seed transaction fails 12 atomic tests.
* The creation-related regression (132 test files that reference the creation authority, 3,867 tests) on the patched tree: 3,863 passed, 3 skipped, 4 failed. Of the four, `test_api_b04_placeholders_not_links` also fails on
  unmodified `main` (not RC-M's); `test_clone_unexpected_error_{htmx,non_htmx}_returns_500_with_safe_body` caught a real defect of the first patch draft (the keyed refactor made the unkeyed seeded path bypass the public
  `create_working_copy` that those tests replace) — fixed: the unkeyed path calls the public service exactly as before, and both tests pass; `test_the_correction_changes_no_protected_financial_path_since_the_baseline` fails only
  on the main-based tree because the patch changes `projects_repository.py`, which that Overnight B guard lists — on a tree that carries #389 the same guard attributes the file through `finval_f01_scope` (admitted by step 3 below),
  which is how the scratch merge passed it.
* On **#389 head `d53400a6`**: the four source hunks `git apply --check` cleanly; a merge of the RC-M branch onto that head conflicts only in three pinned-governance files
  (`tests/model_mutation_security_successor.py`, `tests/test_model_mutation_security_successor.py`, `tests/test_model_react_overnight_b_governance.py`; resolved mechanically by keeping both
  successor layers); with the patch applied, F01's own scope/creation/complete/fixture/hash tests, the RC-M governance and the 62 New Project tests pass — **except** four governance
  tests that already fail on the unmodified #389 head in this environment (`tests/test_u2_2_returns_surface.py: unreviewed blob`), which are #389's, not attributable to RC-M.

## Integration steps after #389 merges (owner-authorized scope, no further approval needed)

1. Merge verified new `main` into the RC-M branch (ordinary merge commit). Resolve the three governance-layer conflicts by keeping both layers (RC-M and F01 successors).
2. `git apply docs/react_migration/rc_m_integrated/atomic_create/ATOMIC_CREATE_AFTER_F01.patch`.
3. Admit the two F01-pinned files' new blobs: in `tests/finval_f01_scope.py` add `ATOMIC_CREATE_SUCCESSORS = {path: git hash-object <path>}` for
   `app/persistence/projects_repository.py` and `app/services/project_library_service.py` and accept `got in {expected, ATOMIC_CREATE_SUCCESSORS.get(path)}` (exact alternatives only; any other drift still fails).
4. Re-pin `tests/rcm_adapter_csrf_successor.py` (`app/v2/react_new_project.py` blob) and run: the patch's own tests, the F01 suites, RC-M governance, the full consolidation role, then adopt
   `human_percent_v1` checks (0.056 %, 0.56 %, 5.60 %, 9.00 %): Wizard → Working Copy → Financing → Save → Reload → Run, then Sensitivity and Goal Seek against that financing authority.
5. Remove this folder's patch and `tests/test_rcm_atomic_create_patch.py` (its tripwire then checks the integrated state with `git apply -R`).

`tests/test_rcm_atomic_create_patch.py` fails if the stored patch stops applying to the current sources (so the preparation cannot rot) and confirms the release gate is closed.
