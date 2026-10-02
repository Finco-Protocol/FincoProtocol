# FINCO Yield alert automation (Monitoring Automation V1) — prepared, not deployed

External one-shot scheduler wiring for `python -m finco_yield.evaluate_alerts`.
**Do not install or enable the timer as part of a code PR.** Deployment needs
separate approval and a verified target host.

```
timer -> enumerate users with canonical watchlist items
      -> the SAME per-user evaluator manual "Refresh alerts" calls
      -> existing alert store (deterministic ids, atomic checkpoints)
      -> existing in-app /crypto alerts
```

In-app alerts only. **Nothing is sent externally** (no email, Telegram, Discord
or push), there is no recipient database, no queue/Celery/Redis and no loop in a
web worker. The evaluator adds no calculation: transitions, baselines, freshness
degradation, support-state changes and deterministic alert ids are unchanged.

## Files

| File | Purpose |
|---|---|
| `finco-yield-alert-evaluator.service` / `.timer` | production-layout one-shot unit + 10-minute timer (`*:03/10`, 3 min after the collector) |
| `yield-alert-evaluator.env.example` | env template (`FINCO_YIELD_ALERT_AUTOMATION_ENABLED=0`) |
| `staging/…` | same, for `/opt/finco_staging` (`finco-staging` identity) |

The service has no `[Install]` section: only the timer or a manual start runs it.
`flock -n -E 75` plus an in-process `flock` on `FINCO_YIELD_ALERT_LOCK_PATH`
(default `<history path>.alerts-eval.lock`) prevent two evaluator runs from
overlapping; a second run exits `75` (`LOCKED`). `SuccessExitStatus=3` keeps a
PARTIAL run from marking the unit failed.

## Exit codes

| Code | Status | Meaning |
|---|---|---|
| 0 | OK | every discovered user evaluated (or no user has a watchlist) |
| 2 | FAILED | canonical inputs (history/registry) or watchlist unavailable, or every user failed |
| 3 | PARTIAL | some users evaluated, some failed (listed by pseudonymous `user_ref`) |
| 4 | DISABLED / CONFIG_ERROR | automation not enabled, history path missing, lock dir unwritable |
| 75 | LOCKED | another evaluator run holds the lock |

The JSON report (one line on stdout) contains counts, one shared `evaluated_at`,
typed reasons and `failures[{user_ref, reason}]` where `user_ref` is a 12-hex
SHA-256 prefix of the user id. No alert content, user id, path or secret is printed.

## Staging activation checklist (operator, later)

1. The web process, the Y-LIVE collector and this evaluator must use the **same**
   `FINCO_YIELD_HISTORY_PATH` and the **same** `FINCO_DB_PATH`.
2. `install -d -o finco-staging -g finco-staging -m 0750 /opt/finco_staging/storage/yield`
3. Copy `staging/yield-alert-evaluator.staging.env.example` to
   `/opt/finco_staging/.env.yield-alert-evaluator` (mode 0600) and set
   `FINCO_YIELD_ALERT_AUTOMATION_ENABLED=1`.
4. Run once by hand: `systemctl start finco-staging-yield-alert-evaluator.service`
   and read the single JSON report in `journalctl`.
5. Only then enable the timer. Never enable it before the collector writes history.
