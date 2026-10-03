# FINCO Tokenized Markets live collector V1

This deployment unit activates the **separate one-shot Tokenized Markets collector**.
It is not part of the web request path.

Authority flow:

```
reviewed R-LIVE authority
  -> bounded exact-asset collector
  -> canonical MarketObservation
  -> append-only VenueMarketStore
  -> read-only Tokenized Markets intelligence/UI
```

## Safety and authority boundaries

- Exact reviewed Robinhood AssetKeys only; no ticker discovery or fuzzy matching.
- No wallet, custody, signing, transaction construction, broadcast, or automatic trading.
- No browser request can invoke this collector.
- Source timestamps and FINCO collection timestamps remain distinct.
- Repeated identical provider evidence deduplicates deterministically because
  `MarketObservation` digests exclude `collected_at`.
- Historical observations are append-only; the collector has no update/delete path.
- A per-asset acquisition failure does not suppress successful sibling assets.
- QUARANTINED evidence may be persisted for inspection but never becomes active pricing.
- Collector health is operational metadata only and cannot upgrade market authority.

## Cadence

The timer is intentionally bounded to **five minutes**. Runtime defaults:
two workers, one exact-asset retry, 250 ms initial retry backoff and a maximum
reviewed universe of 32 AssetKeys. These limits are configurable only inside the
bounded ranges enforced by `app.radar_rwa.tokenized_collect`.

## Shared storage requirement

The collector and web process **must use the same existing**
`FINCO_VENUE_DB_PATH`. Before enabling the timer, inspect/back up any existing
canonical venue history. Never start a second empty database while canonical
history exists elsewhere.

## Activation

1. Deploy the reviewed application revision.
2. Copy the environment example to the private host path and set the reviewed
   Robinhood Chain HTTPS RPC URL.
3. Confirm web and collector use the same `FINCO_VENUE_DB_PATH`.
4. Run the service once manually and inspect its typed JSON result and collector
   health.
5. Set `FINCO_TOKENIZED_COLLECTOR_ENABLED=1`.
6. Enable/start the timer.

Exit codes: 0 = complete, 3 = partial/degraded but valid observations persisted,
2 = runtime/persistence/health failure, 4 = disabled or configuration error,
75 = overlapping run rejected by `flock`.

This repository change prepares the runtime. It does **not** deploy or enable it.
