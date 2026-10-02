# FINCO Yield — Monitoring Automation V1

Status: **draft implementation, not deployed, timer not enabled.** Yield
execution remains OFF. No email / Telegram / Discord / push delivery exists or is
claimed; alerts remain in-app on `/crypto`.

```
systemd timer (prepared, not enabled)
  -> python -m finco_yield.evaluate_alerts            (one-shot, default DISABLED)
  -> users with canonical yield_watchlist items       (watchlist.list_watchlist_user_ids)
  -> YieldAlertsGateway.evaluate_user                 (THE shared core)
       -> alerts_eval.evaluate_watchlist_alerts       (existing evaluator)
            -> YieldHistoryStore / evaluate_freshness (existing)
       -> alerts_store.commit_alert_state             (existing, atomic, deterministic ids)
  -> existing /crypto alert read model
```

Nothing new is a second authority: no second watchlist, evaluator, history store
or freshness classifier. The runner is orchestration only.

## Config

| Variable | Default | Purpose |
|---|---|---|
| `FINCO_YIELD_ALERT_AUTOMATION_ENABLED` | `0` | must be truthy for any run |
| `FINCO_YIELD_HISTORY_PATH` | required | canonical history (same variable web/collector use) |
| `FINCO_DB_PATH` | existing | watchlist + alert DB |
| `FINCO_YIELD_ALERT_LOCK_PATH` | `<history>.alerts-eval.lock` | run lock |

No secrets are read or printed.

## Exit codes / report

`0` OK · `2` FAILED · `3` PARTIAL · `4` DISABLED / CONFIG_ERROR · `75` LOCKED.
One JSON line (`YIELD_ALERT_EVALUATION_REPORT_V1`) with counts and
`failures[{user_ref, reason}]`; `user_ref` is a sha256 prefix, never a user id,
path or exception text. Unavailable history / registry / watchlist is FAILED,
never OK. No watchlist users is OK.

## Scheduler contract

`deploy/yield_alert_automation_v1/`: oneshot service (no `[Install]`, `flock -n
-E 75`, `SuccessExitStatus=3`) plus a timer at `:03/10` (after the collector).
Neither is enabled; activation is a manual operator step (see its README) and
requires the flag. No Celery/Redis/queue; no loop in web workers.

## Locking contract

An exclusive non-blocking `flock` on the lock file; a second concurrent run
exits `LOCKED` (75) without touching state. The lock is released when the
process ends or the run fails.

## Determinism and parity

One evaluation instant is read per run and shared by all users. Manual Refresh
(`YieldAlertsGateway.refresh`) and the background runner both call
`YieldAlertsGateway.evaluate_user`, so for equal history / watchlist /
checkpoint / registry / evaluation time they produce identical alerts (same
deterministic `alert_id`s) and checkpoints — proven by
`TestManualParity` (baseline, transition, and missing-value steps compared
across two independent stores). Baseline-on-first-evaluation, no replay,
atomic checkpoints and retry idempotency are inherited from the existing
store/evaluator and re-asserted in tests.

## UX

`/crypto` states only whether automated monitoring is *enabled by
configuration* (in-app only) vs Manual Refresh only. It does not assert that the
timer is running.

## Limitations

In-app only; no external delivery; scheduler not enabled; one run evaluates all
users sequentially.
