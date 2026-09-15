# finco_app

**FINCO Protocol v2 — Application Layer**

`finco_app` is the deployable application wrapper around `finco_core`. It provides an HTTP API, use-case orchestration, and persistence. It depends on `finco_core` and is independent of all UI code.

## Package Responsibilities

| Subpackage | Responsibility |
|------------|---------------|
| `api/` | FastAPI routes, request/response models, OpenAPI schema |
| `services/` | Use-case orchestration — calls engine, stores results, returns typed responses |
| `persistence/` | Projects, scenarios, runs, audit snapshots, exports (SQLAlchemy, SQLite/PostgreSQL) |

## Dependency Rule

`finco_app` depends on `finco_core`.  
`finco_app` does not depend on `finco_parity` or any UI package.  
`finco_core` never imports from `finco_app`.

## Extraction Status

| Milestone | Status |
|-----------|--------|
| V2-6 API Shell | Planned |
| V2-7 UI Shell | Planned (separate `finco_ui/` package) |
| V2-8 Persistence | Planned |
