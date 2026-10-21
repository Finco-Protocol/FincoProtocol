# Performance V8-A Correction B - concurrent first boot and WAL switch

## Root cause (reproduced, not assumed)
The two failing CI tests (`test_concurrent_threads_do_not_duplicate_initialization`, `test_two_processes_concurrent_first_boot`) failed at
`conn.execute("PRAGMA journal_mode=WAL")` with `database is locked`, before the schema guard's `BEGIN IMMEDIATE`. On a 4-core machine they do not
fail when idle, so they were reproduced under CPU load with a barrier-synchronised stress script: 17 of 200 eight-thread first boots and 7 of 25
six-process first boots failed, always at that statement. `PRAGMA journal_mode=WAL` is the first write-like statement of every new connection
and needs an exclusive lock for the switch; during a simultaneous first boot SQLite can return SQLITE_BUSY at once. Raising a timeout does
not help because it is not consulted in that case.

## Correction (`app/persistence/db.py`)
`PRAGMA busy_timeout` is set first. `_ensure_wal` READS the journal mode and returns when it is already WAL (WAL is persistent, so only the first
connection ever switches). Otherwise it attempts the switch and, only on a transient `locked`/`busy` error, re-reads the mode (another booting
connection may have won) and retries with a short bounded backoff until a fixed 30 s deadline. Any other error, or the deadline, is re-raised
unchanged; it returns only once the database reports `wal`. No infinite retry, no broad exception handling, no arbitrary long sleep, WAL stays
mandatory. All Correction A properties are untouched (no `_finco_schema_state` table, no Trust registry exemption, per-database incarnation,
external-change/restore detection, transactional migrations with rollback, fresh connections, per-connection foreign keys and busy timeout).

## Evidence
- Same stress after the fix, same load: 0 of 300 thread boots and 0 of 40 six-process boots failed (was 17/200 and 7/25).
- New tests: scripted-connection unit tests (already WAL performs no write; transient lock retried; another connection winning ends the retry
  without a second write; non-lock errors and the deadline are not swallowed) and a loaded eight-thread x 25-round fresh-file test that also asserts
  the file reports WAL. Against the pre-fix `db.py` under load the loaded test fails 3 of 3 runs; with the fix the whole schema-guard module passes
  5 of 5 repeated loaded runs and 3 of 3 idle runs (16 tests).
- Ring: schema guard, execution profile, request reads, Trust registry/claims/controls/routes, persistence, CI acceptance, finance-integrity
  governance, post-run context and Runtime V2 performance: 521 passed, 1 skipped.
- Four-vertical (Solar, Wind, Data Center, EV Charging) full canonical result, input identity, cache key and fingerprint vs `origin/main`:
  bit-identical, maximum difference 0 (`PERFORMANCE_V8A_CORRECTION_B_PARITY.json`).
- SQLite-only paired benchmark (60 connections x 2 sessions, isolated databases): median connection 0.48 ms guarded vs 4.09 ms historical;
  SQL statements per connection 5 vs 60.

## Not done (stated, not claimed)
Actual uncached HTTP Run benchmarks for Solar, Wind and Data Center with two before/after sessions, workbook GET timing and connection counts
under real requests were not produced here; the SQLite-only benchmark is NOT a substitute for them. Performance acceptance of V8-A is
therefore incomplete.
