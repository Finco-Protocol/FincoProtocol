# P6 Architecture Audit — FINCO Protocol Corporate Staging

**Scope:** Multi-user public demo and staging readiness.
**Status:** P6 Correction B — final review blockers.
**Engine boundary:** FINCO Model deterministic engine only. FINCO Radar excluded.

---

## 1. Auth and Session Architecture

### 1.1 Admin session
- `app/auth.py` — `URLSafeTimedSerializer` with `SECRET_KEY`; `SESSION_MAX_AGE_HOURS` TTL.
- Admin gets `user_id="1"` (backward-compatible with production DB).
- Cookie: `finco_session`; `HttpOnly`, `Secure` (configurable), `SameSite=Lax`.

### 1.2 Demo session (P6.2)
- Auto-provisioned by `DemoSessionMiddleware` on first request with no session cookie.
- User ID: `demo_` + 32 cryptographically random URL-safe bytes — globally unique, not guessable.
- Signed with `URLSafeTimedSerializer` at a separate salt (`finco-demo-session`) — admin and demo tokens are cryptographically non-interchangeable.
- Cookie: `finco_demo`; same `HttpOnly`/`Secure`/`SameSite` flags.
- TTL: `FINCO_DEMO_TTL_HOURS` (default 24h).
- `SessionData.session_type` distinguishes `"admin"` from `"demo"`; `SessionData.is_demo` is a read-only property.

### 1.3 Session resolution order (get_current_user)
1. Admin session cookie (`finco_session`) — validated admin token.
2. Demo session cookie (`finco_demo`) — validated demo token.
3. Freshly provisioned token in `request.state.demo_session_token` (first visit — set by middleware within the same request).
4. `None` — only on login/logout/health endpoints that explicitly handle unauthenticated state.

### 1.4 Collision points fixed
- Previous: `create_session_token(user_id="1")` was called for all sessions → all users shared `user_id="1"` → complete data collision.
- Fixed: demo sessions receive unique `demo_*` user_ids; admin retains `"1"`.

---

## 2. Persistence Layer and Ownership

### 2.1 Per-user scoping
Most tables carry a `user_id` column. Every query in `app/persistence/projects_repository.py`, `runs_repository.py`, `scenarios_repository.py`, `workspace_repository.py` scopes by `user_id`. Cross-user data is not exposed through any service-layer function.

**Exception — sub-line tables:** `capex_sub_lines` and `opex_sub_lines` reference `project_id`, not `user_id` directly. Ownership chain:

```
capex_sub_lines.project_id → projects.project_id → projects.user_id
```

Demo TTL cleanup deletes sub-line rows via an explicit `DELETE ... WHERE project_id IN (SELECT project_id FROM projects WHERE user_id IN (...))` join, not by `user_id` directly. This is the correct deletion path; a direct `user_id` filter would not match these tables.

### 2.2 Canonical references
- `user_id = "__reference__"`, `project_role = "reference"`, `is_protected = 1`, `archived = 0`.
- `template_source IN ('generic_solar_reference', 'generic_wind_reference', 'generic_storage_reference')`.
- Global read access is intended: the Project Library exposes canonical references to all users via the `_canonical_reference_predicate()` predicate (Solar XA, Wind XB, Storage XC).
- Write/update/archive/delete on protected references raises `ProtectedProjectError` (HTTP 400).
- Working copies: `create_working_copy(user_id, source_reference_id)` creates a new row owned by the requesting user — canonical reference row is never modified.

### 2.3 Export IDOR
- `/download` (POST/GET): delegates to `execute_post_download_route` / `execute_get_download_route` which call `get_project_by_code(user.user_id, ...)` — project must be owned by the requesting user.
- `/exports/runtime-summary.csv` and `/exports/institutional-workbook.xlsx`: same `get_project_by_code(user.user_id, ...)` ownership check.
- Cross-session export access by ID guessing is structurally impossible; user_id is not attacker-controlled (it is embedded in the signed session cookie).

### 2.4 list_projects_paged bug (P6.7 — fixed in Correction A)
- `_canonical_reference_predicate()` generates `IN (?, ?, ?)` (3 slots for Solar, Wind, Storage).
- Prior code bound only 2 templates — Storage XC was absent from params, causing `sqlite3.ProgrammingError` when the library page was rendered with role_filter or search.
- **Fixed:** all 3 `CANONICAL_REFERENCE_TEMPLATES` are now bound in `params`.

---

## 3. SQLite Pilot Review

### 3.1 Configuration
- WAL journal mode (`PRAGMA journal_mode=WAL`) — multiple readers, single writer.
- `busy_timeout = 30000` ms — writer blocks up to 30 s before raising `sqlite3.OperationalError`.
- `foreign_keys = ON` — referential integrity enforced.
- DB path: `FINCO_DB_PATH` env var (default `app/data/finco_runs.db`).

### 3.2 Write contention under load
- Multiple demo sessions writing concurrently → SQLite serializes writes via WAL writer lock.
- 30 s busy timeout means simultaneous writes queue for up to 30 s before failing.
- For 40 browsing VUs (mostly reads) + 10–15 concurrent model runs (writes on completion): WAL handles this well; contention is expected only at scenario-save / workspace-state-save points, not during engine computation.
- Mitigation: model run concurrency bounded by `FINCO_MAX_CONCURRENT_RUNS` semaphore — reduces simultaneous DB writes.

### 3.3 Instrumentation
- DB lock events should be logged at WARNING level when `busy_timeout` is hit.
- See `app/observability.py` for request/error/capacity counters.

---

## 4. Gunicorn and In-Process Semaphore

### 4.1 Effective concurrency
- `asyncio.Semaphore(_MAX_CONCURRENT_RUNS)` is per-process, not cross-process.
- With Gunicorn: `effective_limit = FINCO_MAX_CONCURRENT_RUNS × num_workers`.
- Staging recommendation: `FINCO_MAX_CONCURRENT_RUNS=3`, `--workers=2` → effective 6 concurrent runs.
- With uvicorn single worker: `FINCO_MAX_CONCURRENT_RUNS=8` → 8 concurrent.

### 4.2 Demo rate limiting
- `check_demo_rate_limit()` is similarly in-process (per-worker with Gunicorn).
- For a pilot with 1–2 workers and 40 VUs this is acceptable; each worker independently tracks its own bucket. A Redis-backed shared limiter is a post-P6 improvement if needed.
- Documented in `app/auth.py` docstring.

---

## 5. Demo Session TTL Cleanup

### 5.1 TTL authority
- **`MAX(updated_at / created_at)`** across **all five session-owned tables** for a `demo_*` user_id:
  - `projects.updated_at`
  - `scenarios.updated_at`
  - `workspace_states.updated_at`
  - `runs.created_at`
  - `scenario_exports.created_at`
- A demo session is expired only when the most-recent activity across **all** of these tables is older than `FINCO_DEMO_TTL_HOURS`. Fresh activity in any single table keeps the entire session intact.
- `capex_sub_lines` and `opex_sub_lines` are **excluded** from TTL authority: their mutations always occur within a project-save or workspace-save code path that updates the parent `projects.updated_at` or `workspace_states.updated_at`, so they are always redundant in the TTL query.
- Implementation (SQL authority — UNION across 5 tables):
  ```sql
  SELECT user_id
  FROM (
      SELECT user_id, MAX(last_activity) AS last_activity
      FROM (
          SELECT user_id, updated_at AS last_activity FROM projects         WHERE user_id LIKE 'demo_%'
          UNION ALL
          SELECT user_id, updated_at AS last_activity FROM scenarios        WHERE user_id LIKE 'demo_%'
          UNION ALL
          SELECT user_id, updated_at AS last_activity FROM workspace_states WHERE user_id LIKE 'demo_%'
          UNION ALL
          SELECT user_id, created_at AS last_activity FROM runs             WHERE user_id LIKE 'demo_%'
          UNION ALL
          SELECT user_id, created_at AS last_activity FROM scenario_exports WHERE user_id LIKE 'demo_%'
      )
      GROUP BY user_id
  )
  WHERE last_activity < :cutoff
  ```
- Example (TTL=24h): demo_X has Project A (updated 30h ago) and Scenario B (updated 5 min ago). `last_activity = 5 min ago` — not expired; all data kept. demo_Y has only Project C (updated 30h ago, no other state). `last_activity = 30h ago < cutoff` — expired; all data deleted.

### 5.2 Scheduling
- `_schedule_demo_cleanup()` startup hook starts a daemon thread.
- Thread: 5-minute initial delay (startup I/O settles), then cleanup, then sleep for `max(3600, DEMO_TTL_HOURS × 3600)`, then repeat.
- Recurring loop ensures long-lived staging processes clean up without operator intervention.
- Never deletes `user_id = "1"` or `user_id = "__reference__"` data.

### 5.3 Sub-line cleanup ordering
Sub-line tables (`capex_sub_lines`, `opex_sub_lines`) are cleaned before `projects` to avoid orphaned rows. See §2.1 for ownership chain.

---

## 6. Privacy-Safe Observability

### 6.1 Structured log events
`app/observability.py` exposes structured log helpers used throughout `main_web.py`:

| Event | Logger level | Keys |
|-------|-------------|------|
| HTTP error (4xx/5xx route) | WARNING | `event`, `status_code`, `path`, `method` |
| Model run started | INFO | `event`, `user_id_prefix` (first 12 chars only) |
| Model run completed | INFO | `event`, `duration_ms`, `status` |
| Model run failed | ERROR | `event`, `error_type` |
| Capacity-busy (503) | WARNING | `event`, `max_slots` |
| SQLite lock (`OperationalError`) | WARNING | `event`, `table` |

### 6.2 What is never logged
- Session tokens or cookie values
- `FINCO_SECRET_KEY`, `FINCO_ADMIN_PASSWORD`, or any environment secret
- Full request/response payloads
- User-supplied financial inputs (capex, tariff, etc.)
- Full `user_id` beyond the first 12 characters (prevents session enumeration)

### 6.3 Health and readiness endpoints
- `GET /public-health` — unauthenticated, returns `{status, app, mode}` only. No model run. No DB query.
- `GET /readyz` — unauthenticated, delegates to `get_app_health_status()`. Checks DB directory reachability (not content). Returns HTTP 200 (ok/degraded) or HTTP 503 (error). Does not expose secret values.
- `GET /health` — requires admin auth. Returns `{status: ok}` only.

---

## 7. Remaining Gaps (Post-P6 Roadmap)

| Gap | Priority | Note |
|-----|----------|------|
| CSP `unsafe-inline` | Medium | Inline workspace init scripts must be migrated to `data-attribute` reads before CSP can be tightened. Target: phase16-csp-clean-apply. |
| Cross-process rate limiting | Low | Per-worker buckets acceptable for pilot; Redis shared limiter for production. |
| Session token rotation | Low | Sessions should be rotated on privilege escalation. |
| PostgreSQL migration | Future | SQLite is appropriate for the current scale. |
| FINCO Radar | Out of scope | Token-market, wallet, DEX, and chain logic are architecturally separate. |

---

## 8. Staging Configuration

See `deploy/staging.env.example` for environment variable documentation.

`FINCO_STORAGE_PATH` is defined in `deploy/staging.env.example` as a reserved variable for a future export-storage directory feature. It is not consumed by any current code path — the application writes exports using the default directory derived from `FINCO_DB_PATH`. Operators may set it in anticipation of the feature; it has no effect until the export-storage service is wired up.
