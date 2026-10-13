# M3 two-driver sensitivity — RC Trust integration handoff

This is a handoff for the independent integration reviewer. **This feature branch does not change the RC-1 Trust
pins, tests, security controls, release manifests or CI workflows**, and the router registration is the plain,
visible hook below (it is not moved, wrapped or disguised to evade the guard). The RC-1 protected-scope successor in
`tests/test_trust_readiness_registry.py` therefore reports this PR as not part of the reviewed integration. That is a
governance authorisation boundary: an exact-content successor must be authorised on the future RC integration branch.

## 1. Exact content to authorise

New application modules (blob SHAs at the reviewed head of this change; recompute with `git hash-object`):

| Path | Git blob SHA-1 |
| --- | --- |
| `app/services/sensitivity_matrix.py` | `b0dadcda8d7da65562b6ab4562300c1d2da6ab64` |
| `app/v2/sensitivity_matrix_projection.py` | `d6aa0d80d4222619053f07f25beaa429481f4ca0` |
| `app/v2/sensitivity_matrix_router.py` | `15c77bbc84b7443c4f716185ccf9161720d40d68` |

Router change in `app/v2/router.py` — module-level statements added after `router.include_router(f4_router)`; no
function is added, removed or modified (the changed-function sets stay empty):

```python
# M3 two-driver sensitivity matrix: one isolated read-only route (integration hook only).
from app.v2.sensitivity_matrix_router import router as sensitivity_matrix_router
router.include_router(sensitivity_matrix_router)
from app.v2.sensitivity_matrix_router import register_template_globals
register_template_globals()
```

AST view: four new top-level statements (two `ImportFrom`, one `Expr(Call include_router)`, one `Expr(Call
register_template_globals)`); the existing module-level statements are byte-identical. Also changed, all under
already-free prefixes: `app/templates/v2/partials/sheet_sensitivity.html` (hosts the form; the stale "matrices are not
available" sentence replaced), two new partials, `static/css/sensitivity_matrix.css`, `static/js/sensitivity_matrix.js`,
tests and docs. Nothing under `financial_engine/`, `finco_core/`, `domain/`, `.github/`, governance tests, tolerances,
goldens or release maps is touched (asserted by `test_no_engine_or_financial_authority_files_are_touched`).

## 2. Security behaviour (as built, stated without embellishment)

The single new route is `POST /v2/workbook/sensitivity/matrix/run`.

* Authentication: `resolve_request_session` (same as every V2 route); unauthenticated → 401 before any work.
* Ownership: `resolve_accessible_project(user_id, project)`; another user's or unknown project → 404; scenario ids are
  resolved through the owner-scoped scenario repository and must belong to the project and not be archived → 404.
* Feature gate: `Depends(require_v2_active)`; protected reference models → 409.
* **CSRF: this route does not validate a CSRF token.** It is outside `RC1_ROUTER_CSRF_FUNCTIONS` and, like the existing
  one-driver `v2_scenario_sensitivity_run` and `v2_workbook_goal_seek_run` POST routes (neither validates CSRF), it
  relies on the session cookie's SameSite policy. Because it writes nothing, a forged request can at most consume
  bounded model capacity; the bounded executor (one admitted batch, ≤ 26 evaluations, 429 when busy) limits that. If
  the integration reviewer wants CSRF on analysis routes, that is a separate, repo-wide decision for all three routes.
* Concurrency/DoS bounds: 3–5 levels per axis, per-driver magnitude bounds, ≤ 26 evaluations (< existing ceiling 49),
  one executor submission per request, `Retry-After` on busy, no per-cell HTTP requests, no process fan-out.
* Output safety: user-supplied strings are HTML-escaped (error fragments) or rendered by Jinja autoescape; engine error
  text is truncated and internal exception detail is not leaked.

## 3. Why the route is read-only and introduces no financial writer

* It performs reads only: workspace/scenario/project reads, in-memory construction of typed `ProjectInputs`, and the
  existing `run_project` calls in the bounded model executor. It imports no persistence writer and calls no
  `save_*`, `apply_*update*`, `commit_*` or Run History function; the route test
  (`test_no_persistence_and_no_last_run_mutation`) proves the Working Copy draft, Last Run fields, row version,
  active scenario and Run History are identical before and after a run.
* Results are marked `EPHEMERAL`, never CURRENT, carry `Cache-Control: no-store`, and are discarded with a 409 if the
  workspace changed during the batch (`PostRunRequestContext.validate_current`).
* No financial formula, solver, tolerance, KPI definition or catalog is added or changed; shocks use the existing
  `ProjectInputSet.with_value` and `sensitivity_service._apply_shock` mechanisms; metrics use the existing catalog and
  source-key mapping; the new worker only calls `run_project` and re-reads summary fields already present in its result.

## 4. Evidence (focused tests)

* `tests/test_m3_two_driver_sensitivity.py` (pure, route, security, failure, no-persistence, real Solar/Wind/Data
  Center parity against independently constructed combined-shock runs, metric support / unsupported / unavailable
  paths, typed interest-rate unit contract) and `tests/test_m3_two_driver_sensitivity_browser.py` (authenticated
  Chromium, 3 tests).
* Adverse cases: unauthenticated, other user, unknown scenario, duplicate / unsupported driver, EV Charging, oversized
  grid, bad levels / metric / threshold / grid size, unsupported metric, busy, timeout, executor error, stale context,
  calibrated rate schedule, bankability-owned rate, unapplied shock.

## 5. Required exact-content successor authorisation (to be performed on the RC integration branch)

1. Authorise exactly the three paths and blob SHAs of section 1 (any later byte change re-opens review).
2. Authorise exactly the four module-level router statements of section 1, keeping the existing assertions that no
   router function is added/removed/modified, the CSRF handler set is unchanged, and no state-changing verb is added to
   a function in the protected set.
3. Keep every historical Trust assertion and mutation-negative test effective; the successor must be additive and
   exact-content, never a path or prefix wildcard.
4. Decision on the CSRF posture of read-only analysis routes (section 2) — recorded either way.

Until that successor exists, `tests/test_trust_readiness_registry.py` is expected to fail on this branch (6 failed,
16 errors observed in CI run 38446738455); it is unrelated to numerical or UX behaviour.
