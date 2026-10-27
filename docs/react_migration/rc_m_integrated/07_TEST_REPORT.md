# Test report (local, Python 3.12 virtualenv matching CI; real Chromium for the browser role)

Exact-head hosted CI is **not** in this file; it is in `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md`. Everything below is local evidence on the commits named there.

## Python suites added or changed by RC-M

| Suite | Tests | What it proves |
|---|---|---|
| `test_model_react_rcm_new_project_v1.py` | 33 | options/preview/create contract, release posture per vertical, CSRF order, bounded validation, preview ≡ canonical service, wizard twin ≡ direct create, unknown outcomes |
| `test_model_react_rcm_new_project_fence_v1.py` | 17 | the durable claim ledger (one winner among concurrent claims, scoping, never reclaimed, atomic demo budget) and the handler's reaction to every claim state, failure injection, cross-user |
| `test_model_react_rcm_new_project_multiprocess_v1.py` | 8 | **three real uvicorn processes on one database**: simultaneous same-id POSTs → one project; process killed (`os._exit`) after the write; replay after a lost response; users isolated; CSRF 403 never claims; demo budget across processes; closed/unknown technologies and extra source fields create nothing |
| `test_model_react_rcm_sensitivity_v1.py` | 23 | access order, bounded budgets, strip/3×3 matrix parity with the Legacy routes, rate-lock refusal |
| `test_model_react_rcm_goal_seek_v1.py` | 27 | solve and Apply parity with Legacy, candidate-bound CSRF, writer barriers behind a validly signed forged candidate, owner scoping, protected reference |
| `test_model_react_rcm_goal_seek_review_v1.py` | 15 | stale candidate refused after a Working Copy edit / scenario switch / contract-owned price; preview side-effect-free; heavy GETs refuse before any engine capacity; busy engine → one 429, no server retry |
| `test_model_react_rcm_financing_v1.py` | 28 | studio view ≡ `build_view`, typed configuration round-trip, rate-schedule lock, STALE without Run |
| `test_model_react_rcm_investors_v1.py` | 17 | investor evidence ≡ Legacy workspace, 60/40 split, CAS |
| `test_rcm_governance.py` | 28 | six-path additive successor layer, exact-change proof for the asset router, consolidation import tail, acceptance modules not collected / no skip / unique names, protected-path guard |
| `test_rcm_adapter_csrf_successor.py` | 28 | exact-blob + AST proof of the two CSRF-bound POST modules incl. fence-then-claim-then-write order and candidate-bound token; structural negatives |
| `test_rcm_asset_version.py` | 6 | content-derived cache-buster (see `08` item 4) |
| `test_rcm_ci_v3_collection_governance.py` | 6 | the CI V3 reconciliation gate still refuses added/removed/changed collection skips and removed nodes; no RC-M module has a collection-time skip |
| `test_rcm_atomic_create_patch.py` | 3 | the prepared atomic-create patch still applies; release gate closed |

Focused run of these plus the pinned governance suites (`test_model_mutation_security_successor`, `test_model_react_overnight_b_governance`, `test_trust_readiness_controls`, `test_ci_acceptance`,
`test_model_workspace_consolidation`, `test_model_react_poc_v1`): **619 passed, 0 failed** (11 warnings, none new).

## Browser (mandatory consolidation role)

**165 passed, 0 failed, 0 skipped** (106 pre-existing + 59 RC-M nodes), 781 s; CI's `validate_consolidation` accepts the inventory, JUnit and screenshots. See `06_…`.

## Mutation checks (the tests must fail when the protection is removed)

* Interim ledger: forcing every claim to win makes **5 of 8** multi-process tests fail (race, both crash tests, isolation, demo budget).
* Prepared atomic create: a non-unique request index fails the two-worker test and the direct-INSERT test; removing the seed transaction fails 12 atomic tests.

* Prepared atomic create (not applied; `atomic_create/README.md`): regression of the 132 test files that reference the creation authority on the patched tree — 3,863 passed, 3 skipped, 4 failed; one failure is
  pre-existing on `main`, one is an artefact of the main-based guard (attributed through the F01 scope pin on a tree carrying #389), and two exposed a real defect of the first draft (the unkeyed seeded path bypassed the public
  `create_working_copy`), which was fixed and re-tested (75 passed in the affected files).

## Collection governance

Collecting the whole `tests/` tree with Chromium's driver blocked (as in the CI plan environment): `main` 20,085 tests / 66 collection skips; this branch 20,306 tests / **66 collection skips, identical list**.

## Public safety

`python tools/public_safety_scan.py` on the whole tracked tree: `PUBLIC_REPOSITORY_SAFETY_SCAN_PASS` (scanner and allowlist unchanged).

## Bundle

`npm run build` in `frontend/` reproduces `static/react/finco-react.{js,css}` byte for byte (git blobs `b99bf91a…` / `add7ddc5…`).

## Not run / not claimed

No deployed environment was touched; no rate-dependent parity (F01 unmerged); no cross-browser, screen-reader or visual-regression run; the Python 3.13 sandbox default is not CI's interpreter (four
governance AST pins fail under 3.13 on unmodified `main`), so every number above is from 3.12.
