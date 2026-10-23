> Historical #344/#345 checkpoint. The final integration implements the reviewed technical correction in the same integration PR; owner approval and hosted/activation gates remain pending. See [final integration](../final/INTEGRATION.md).

# Separate product lifecycle correction proposal — not implemented or approved

`main_web._schedule_demo_cleanup` creates an unowned daemon on every startup, initially sleeping 300 seconds and later deleting expired demo data. There is no stop event/join. Repeated TestClient/application lifespans can accumulate same-named survivors and residual writes.

`RLiveSnapshotWarmer.stop()` signals an Event without joining an in-flight cycle. Web startup has no paired shutdown. The loop releases its SQLite lease and closes the connection in `finally` only after exit; acquisition may still write after stop returns. The cycle also owns a heartbeat with a bounded join. A two-name allowlist does not authorize the separately named heartbeat or constrain multiplicity/function identity.

Prefer explicit application-lifespan ownership of both services:

1. Retain service/thread ownership, prevent duplicate starts for the same live application, and replace long sleeps with interruptible waits.
2. Signal stop, bound acquisition/heartbeat completion and join, and release lease/database resources before reporting successful shutdown.
3. On join timeout preserve a shutdown failure; do not hide survivors, force PASS, or relax CI leak checks. Never stop a thread/resource not owned by this application instance.
4. Preserve demo TTL selection/deletion authority, R-LIVE acquisition/lease/freshness semantics, offline mock behavior and all financial assertions.

`tests/test_ci_v3_lifecycle_research.py` characterizes current behavior with no product edits: a repeated startup body creates multiple recording threads; actual owned warmer starts are idempotent while alive; stop returns during blocked acquisition; a residual write can precede manual join; and lease release/close occurs after that join. Tests always release/join their owned threads. These are gap characterizations, not acceptance tests for a corrected lifecycle.

A separately approved product workstream should add real lifespan integration tests for repeated startup/shutdown, immediate and in-flight shutdown, no residual writes after successful shutdown, lease takeover/release, heartbeat failure, resource closure and timeout rejection. Do not put knowingly failing future assertions into mandatory CI or grant a name-based exception while waiting.

After independent product review, normally merge that workstream into the integration branch; no cherry-pick/rebase/squash/force push. Recompute source applicability and rerun affected evidence. Until then the owner decision on survivors remains pending and admission remains closed.
