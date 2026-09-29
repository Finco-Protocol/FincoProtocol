# Staging R-LIVE V2 collector package — not deployed

These separate systemd units use `/opt/finco_staging` exclusively, not the
production checkout, environment file or `/var/lib/finco` ledger. Their
no-argument one-shot command collects all exact approved registry AssetKeys.
The five-minute timer is external to the web process; it never changes market
authority or schedules work inside FastAPI. Installing/enabling it requires a
separate staging-host approval and the verified exact deployed SHA.

## Preflight before any host change

1. Positively identify the isolated staging host, checkout, web service,
   Python venv and service user. The template uses the existing `finco`
   service identity; confirm it can read the checkout and write only staging
   storage. Do not install if the actual identity or paths differ.
2. Verify the staging checkout and `FINCO_DEPLOY_SHA` match the reviewed main.
   Run `tools/staging_preflight.py` with the existing private staging env.
3. Inspect any existing `radar_bnb_intelligence.db` under staging storage
   read-only (row count and exact UID/AssetKey identities). Preserve and back
   up the canonical ledger using SQLite online backup. Never create a second
   empty ledger or point staging at `/var/lib/finco` production history.
4. Set the identical `RADAR_BNB_INTELLIGENCE_DB_PATH` in the private web
   `.env.staging` and collector `.env.r-live-collector`. Set the approved
   Robinhood Chain 4663 HTTPS `ROBINHOOD_RPC_URL` privately in **both**.
   Use root ownership and mode 0600; never echo the URL or environment files.
   The collector-specific file contains no web/admin secrets.

## Separate operator activation

Install the two `finco-staging-r-live-collector.*` files under
`/etc/systemd/system/` only after confirming the paths and user above.
Run `systemd-analyze verify` on both installed units and
`systemd-analyze calendar '*-*-* *:00/5:00'`, then `systemctl daemon-reload`.
First run a single manual one-shot with
`systemctl start finco-staging-r-live-collector.service`. Inspect
`systemctl status finco-staging-r-live-collector.service --no-pager` and
`journalctl -u finco-staging-r-live-collector.service -n 30 --no-pager`.
The JSON output contains only exact AssetKeys, typed market states/reasons and
history digests. STALE/UNAVAILABLE asset states are truthful, not a process
failure. A missing RPC or unusable ledger is a nonzero process failure.

Only after checking the shared ledger, exact-identity history readback,
web GET zero-write behavior and web process environment presence, run
`systemctl enable --now finco-staging-r-live-collector.timer`. Inspect
`systemctl list-timers finco-staging-r-live-collector.timer --all` and the
timer status. A 540-second one-shot timeout bounds a slow eight-asset batch;
if it exceeds the five-minute grid, systemd does not start overlapping runs
and `flock` adds a second nonblocking guard (exit 75). Investigate latency,
not price thresholds. Keep the 300-second TWAP/Swap-activity policy unchanged.

For removal, disable/stop only the **staging** timer after recording incident
evidence. Retain the staging ledger and backups. No production service,
database, timer, wallet, transaction or deployment is touched by this package.
