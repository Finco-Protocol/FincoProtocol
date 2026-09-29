# R-LIVE V2 multi-asset collector operations (prepared, not deployed)

This is an external scheduler for the already-merged, one-shot command
`python -m app.radar_rwa.r_live_collect`. It does not change AssetKey, the
reviewed per-asset USDG V3 pools, 300-second TWAP, Chainlink USDG/USD, B1.0 premium,
or the existing B1.3 append-only ledger. No web-process loop, wallet, trade,
or signing service is added. **Do not install or enable this timer as part of
the PR.** Deployment requires separate approval and a verified target host.

With no `--asset-key`, the command serially collects every policy in the
canonical `APPROVED_BY_CANONICAL_ID` registry, using one B1.3 store. Each
approved identity gets an independent AVAILABLE/STALE/UNAVAILABLE result;
one unavailable market does not suppress the others. An explicit
`--asset-key 4663:<exact approved contract>` restricts a manual diagnostic
to one asset. Symbols are display metadata, never a CLI identity selector.

## Host prerequisites and configuration

- Linux systemd host with `/usr/bin/flock`, the `finco` user/group, checked-out
  application at `/opt/finco_protocol`, and Python dependencies in
  `/opt/finco_protocol/.venv`. The service runs with that working directory
  and non-root identity. Confirm these paths/user against the actual host
  before installation; do not infer them from this template alone.
- Copy `r-live-collector.env.example` to `/etc/finco/r-live-collector.env` as
  root; set ownership `root:root`, mode `0600`. Add the approved HTTPS
  `ROBINHOOD_RPC_URL` in the private copy only. Never commit it, put it in a
  command argument, display it with `systemctl show`, or include it in logs.
- `RADAR_BNB_INTELLIGENCE_DB_PATH` defaults in this example to
  `/var/lib/finco/radar/radar_bnb_intelligence.db`. `StateDirectory=finco/radar`
  creates the durable parent with the service identity. This is the **same
  B1.3 ledger** the web/history read surface must use; configure the web
  service with the identical path before enabling collection. A separate
  collector database would silently split history and is not acceptable.
- Before moving an existing ledger, inspect its effective path and back it up
  using SQLite's online backup facility while writes are quiesced. Preserve
  all existing rows and WAL-consistent state; never delete, truncate, rotate,
  or overwrite canonical history. Verify row counts and a known digest in the
  destination before pointing either process at it. Back up the durable DB
  regularly with SQLite's online backup API or equivalent consistent snapshot;
  include restoration testing and retention in the host backup plan.

## Schedule and latency

The default is a wall-clock five-minute grid (`*:00/5:00`) with
`AccuracySec=1s` and zero randomized delay. The 300-second TWAP remains a
price-authority window, **not** a collection-cadence override. `Persistent=true`
causes one catch-up activation after timer downtime, not a replay of every
missed interval. The service is one-shot and has a 540-second start timeout
for bounded serial acquisition of the reviewed registry; a slow run may skip
the next five-minute tick rather than overlap;
`Restart=no` leaves a failed run visible and the next timer tick attempts again.

Five-minute sampling has effectively **zero margin** for #119's experimental
T+60m to T+65m eligibility window: a tick near its end plus scheduler/RPC
latency, timeout, host outage, or source-effective timestamp lag can miss it.
For an operational SLO tied to that narrow window, recommend a separately
reviewed **2-minute** timer override after measuring p95/p99 acquisition
latency and source timestamps. It provides multiple attempts without changing
the scientific eligibility rule, but cannot guarantee eligibility during
outages or stale source evidence. Do not silently change the default or infer
that a more frequent schedule changes B1.0/#119 authority.

To configure another cadence during the separate deployment step, create a
systemd timer drop-in with an empty `OnCalendar=` reset and a reviewed new
calendar expression (for example `OnCalendar=*-*-* *:00/2:00`), then run
`systemd-analyze calendar` and `systemctl daemon-reload`. Keep
`RandomizedDelaySec=0`; do not schedule faster than the measured need.

## Overlap, failure and logging

The timer targets a single non-template service; the service also obtains a
nonblocking OS `flock` on `/var/lib/finco/radar/r-live-collector.lock`. A
concurrent manual/job invocation through the same service cannot overlap a
collector run. Lock contention exits **75** and writes no history. Do not
launch the Python module directly from a second scheduler outside this lock.
SQLite B1.3 evidence digest/idempotency remains the authority for retries.

The collector writes one credential-free JSON batch status line to stdout,
captured by journald. Batch exit **0** means the approved registry was fully
attempted without an operational/runtime failure; individual canonical markets
may legitimately be AVAILABLE, STALE or UNAVAILABLE. Exit **1** means a
process/configuration defect, including missing RPC configuration, a failed
read-only Robinhood Chain 4663 RPC preflight, an acquisition exception, registry
failure, or history initialization, persistence or close failure. An exception
does not stop attempts for the remaining approved assets; the JSON reports a
typed `process_error` without exception text or credentials. In explicit one-asset
diagnostic mode, exit **0** still requires
AVAILABLE and exit **1** reports a typed non-available result. No
STALE/UNAVAILABLE numeric premium is appended. `flock` exit **75** means overlapping execution was
rejected; systemd timeout/failure uses its own nonzero status. `Restart=no`
avoids immediate retry storms; alert on repeated failed units or a missing
recent AVAILABLE point. Do not enable shell tracing, log the environment file,
or forward a credential-bearing exception/URL to monitoring. The web service
does not depend on this unit and remains available if collection fails.

## Separate deployment procedure (not executed by this PR)

1. Confirm live host, service user, checkout/venv, `flock`, existing B1.3 DB
   path, permissions, and backup/restore plan. Align web and collector on one
   durable DB path before proceeding.
2. Install the two unit files under `/etc/systemd/system/` and the private
   environment file under `/etc/finco/`; verify owner/mode. Run
   `systemd-analyze verify` on both installed units and
   `systemd-analyze calendar '*-*-* *:00/5:00'`.
3. `sudo systemctl daemon-reload`; run a single manual test with
   `sudo systemctl start finco-r-live-collector.service`. Inspect
   `systemctl status finco-r-live-collector.service --no-pager` and
   `journalctl -u finco-r-live-collector.service -n 30 --no-pager` (never dump
   the environment). Verify an AVAILABLE digest in the shared B1.3 ledger or
   the typed nonzero reason; a currently STALE source is a legitimate
   fail-closed result, not a reason to weaken freshness policy.
4. Only after approval, enable collection with
   `sudo systemctl enable --now finco-r-live-collector.timer`. Inspect
   `systemctl list-timers finco-r-live-collector.timer --all` and
   `systemctl status finco-r-live-collector.timer --no-pager`.

The separate staging-ready unit/env templates and host preflight are in
[`staging/README.md`](staging/README.md); do not install these production-path
units on staging.

For an update, keep the same DB and private environment file, replace reviewed
unit files, run `systemd-analyze verify`, `systemctl daemon-reload`, then
restart **the timer only** after checking no collector run is active. For
removal, `sudo systemctl disable --now finco-r-live-collector.timer`, wait for
any active one-shot service to finish, and remove the unit files only after
that. Retain the DB and backups. Do not use `reset-failed` to erase incident
evidence before recording the reason. No command here restarts FINCO web or
deploys code automatically.
