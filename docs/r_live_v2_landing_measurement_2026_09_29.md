# R-LIVE landing request and timing audit — 2026-09-29

The public staging URL `https://staging.finco.hr/radar/r-live` was explicitly authorized for read-only measurement. It was not reachable from this execution environment (`net::ERR_NAME_NOT_RESOLVED` in the browser; read-only PowerShell GET returned `HttpRequestException`). No forms were submitted, no writes were made, and no staging timing is inferred.

| Metric | Before | After local change |
|---|---|---|
| Browser R-LIVE HTTP requests | 16 for 8 assets (one current and one history per asset), verified from the previous JS code path | 2 for 13 assets (one streamed current plus one read-only batch history/range), verified from the new JS code path and tests |
| Time to first populated row | Unavailable: staging network inaccessible | Unavailable: not deployed; streaming delivery tested structurally only |
| Time until all rows resolve | Unavailable | Unavailable |
| Median / slowest snapshot latency | Unavailable | Unavailable |
| History request latency | Unavailable | Unavailable |

The current endpoint reuses the existing exact-AssetKey per-asset authority without new price mathematics. It uses two request-local workers, no long-lived current-price cache, and yields each result as soon as its authority call completes. The browser renders a neutral LOADING state until a result arrives. STALE/UNAVAILABLE never inherit a historical value as current. The history/range endpoint is read-only; it does not create a writer. The complete bounded 24-hour range is derived from canonical B1.3 collection time, not a browser-truncated list. Live performance and public-RPC rate-limit behavior require staging verification before claiming a latency improvement.
