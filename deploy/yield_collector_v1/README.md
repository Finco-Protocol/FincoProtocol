# FINCO Yield live collector (Y-LIVE V1) — prepared, not deployed

External one-shot scheduler wiring for `python -m finco_yield.collect_live`.
**Do not install or enable the timer as part of a code PR.** Deployment needs
separate approval and a verified target host. The collector is read-only: no
wallet, signing, custody, transaction or token logic, and **no secret is
required** (the Morpho API used by V1 is public). Yield execution stays off
(`FINCO_YIELD_EXECUTION_ENABLED=0`).

```
SOURCE (Morpho GraphQL) -> normalized observation -> append-only history
                                                  -> current snapshot -> Yield UI
```

## Files

| File | Purpose |
|---|---|
| `finco-yield-collector.service` / `.timer` | production-layout one-shot unit + 10-minute timer |
| `yield-collector.env.example` | private env template (`FINCO_YIELD_COLLECTOR_ENABLED=0`) |
| `staging/…` | same, for `/opt/finco_staging` (`finco-staging` identity) |

The service has no `[Install]` section: only the timer or a manual start runs it.
`flock -n -E 75` prevents overlap; `SuccessExitStatus=3` keeps a PARTIAL run
(some vaults failed, valid observations persisted) from marking the unit failed.

## Exit codes

| Code | Status | Meaning |
|---|---|---|
| 0 | OK | all attempted targets accepted; snapshot + history updated |
| 2 | FAILED | nothing usable persisted; previous snapshot untouched |
| 3 | PARTIAL | ≥1 accepted and snapshot updated, but some targets/providers failed, were rejected, or history failed |
| 4 | DISABLED / CONFIG_ERROR | `FINCO_YIELD_COLLECTOR_ENABLED` off, or paths missing |
| 75 | LOCKED | another run holds the lock |

The JSON report on stdout contains no secrets and no environment values.

## Staging activation checklist (operator, later)

1. `install -d -o finco-staging -g finco-staging -m 0750 /opt/finco_staging/storage/yield`
2. Copy `staging/yield-collector.staging.env.example` to
   `/opt/finco_staging/.env.yield-collector` (mode 0600) and set
   `FINCO_YIELD_COLLECTOR_ENABLED=1`.
3. In `/opt/finco_staging/.env.staging` set **the same two paths** for the web
   process: `FINCO_YIELD_SNAPSHOT_PATH` and `FINCO_YIELD_HISTORY_PATH`
   (web reads only; it never writes them). A collector writing elsewhere would
   leave the UI on the labelled reference sample.
4. Run once by hand: `systemctl start finco-staging-yield-collector.service`,
   then read `journalctl -u finco-staging-yield-collector` (one JSON report).
5. Only then enable the timer.
6. Back up `yield_history.jsonl` (append-only audit trail); never truncate or
   rewrite it. The snapshot is derived and replaceable.

## Verification note

Reachability of `api.morpho.org` from the target host and the exact live
response shape have **not** been verified in CI (CI is network-free). Treat the
first manual run's report as the integration check.
