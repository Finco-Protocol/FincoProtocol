# Post-R12 Acquisition Runtime — one acquisition, one immutable snapshot

Productization layer (P1 of the post-R12 roadmap).  It closes the
production gap where provider acquisition was coupled to proof/runtime
paths and repeated refresh/render actions could reacquire or reconstruct
data independently.

Core invariant:

> **one user/runtime refresh operation = at most one acquisition
> snapshot → one `snapshot_id` → all later reads/rendering reuse that
> exact snapshot.**

This is NOT R13 and adds no financial authority: every R0–R12 package
remains frozen and untouched.

## P1 inventory (what existed before this layer)

- **Genuine reusable acquisition interfaces** — the frozen provider
  adapters (e.g. `finco_radar.quotes.adapters.lifi.LifiExecutionQuoteAdapter.quote`)
  are the authoritative provider parsers and stay untouched; the runtime
  invokes them through composition-time callables without re-parsing.
- **Proof-only helpers** — `finco_radar.r*/live_proof.py` orchestrations
  are evidence-generation pipelines for CI, not product architecture.
  The runtime does NOT depend on them.
- **The coupling gap** — `finco_radar.terminal.runtime` builds live
  terminal snapshots by constructing adapters and calling providers
  inside a presentation builder, so every render can reacquire.  That
  package is frozen; this layer provides the replacement architecture
  the UI will consume next.
- **Persistence standard** — SQLite with WAL + busy_timeout
  (`app.persistence.db`); the snapshot store follows the same idioms in
  a dedicated database.
- **Config conventions** — `RADAR_*` / `FINCO_*` environment variables.
- **Caching** — `app.cache` is a Streamlit-facing decorator cache, not
  suitable for acquisition identity; a purpose-built TTL cache is
  provided instead.

## Architecture

```
app/radar_runtime/
  contracts.py       # AcquisitionRequest, ProviderResult, AcquisitionSnapshot
  service.py         # AcquisitionService: acquire / get_snapshot, single-flight
  snapshot_store.py  # durable append-only SQLite snapshot ledger
  cache.py           # runtime TTL cache keyed by request fingerprint
  observability.py   # whitelisted structured events, correlation_id
```

- **Request fingerprint (P3)** — `acq-req:<sha256>` over the canonical
  JSON of the request payload (schema, exact `chainId`,
  `contractAddress`, direction, purpose, sorted provider set, exact raw
  amount/notional, optional economic asset uid, provider config).
  Any authority-relevant difference changes the fingerprint.
- **Snapshot identity (P4)** — `acq-snap:<sha256>` over the canonical
  immutable payload (request binding, identity, started/completed
  timestamps, verbatim provider evidence, per-provider result states and
  `observedAt`, runtime metadata incl. `correlationId`).  Content
  addressed — never a mutable "latest" pointer.
- **Store (P8)** — append-only SQLite ledger; duplicate identical insert
  idempotent; same id with different payload is a hard conflict; reads
  are by exact id and re-verify content addressing.
- **Cache (P9)** — TTL keyed by fingerprint; a HIT returns the persisted
  snapshot with its ORIGINAL provider timestamps.  Cache TTL is runtime
  optimization only and can never turn stale evidence fresh (R4/R5/R7/R11
  freshness authority untouched).
- **Single-flight (P7)** — identical concurrent requests share one
  provider acquisition and one snapshot_id; correctness never depends on
  it.
- **Bounds (P10/P11)** — explicit per-provider timeout, total acquisition
  budget and bounded provider pool; typed `TIMEOUT`/`TRANSPORT_ERROR`/
  `PROVIDER_ERROR`/`INVALID_RESPONSE` states; partial acquisition stays
  honest (`PARTIAL`/`UNAVAILABLE`), never fabricated `COMPLETE`.
- **Observability (P13)** — fixed whitelist fields only; provider
  payloads, secrets and credentials are structurally excluded; records
  are diagnostics, not authority evidence.
- **Read path (P14)** — `get_snapshot(snapshot_id)` performs zero
  network/provider calls; read models render entirely from the persisted
  immutable snapshot.

## Configuration (runtime-only, no authority semantics)

| Variable | Default | Meaning |
| --- | --- | --- |
| `RADAR_RUNTIME_PROVIDER_TIMEOUT_SECONDS` | `10` | per-provider call bound |
| `RADAR_RUNTIME_TOTAL_BUDGET_SECONDS` | `25` | total acquisition budget |
| `RADAR_RUNTIME_MAX_CONCURRENT_PROVIDERS` | `8` | bounded provider pool |
| `RADAR_RUNTIME_CACHE_TTL_SECONDS` | `30` | runtime cache TTL (optimization only) |
| `RADAR_RUNTIME_DB_PATH` | `app/data/radar_runtime.db` | snapshot ledger location |

## Provider wiring

Provider callables receive the immutable `AcquisitionRequest` and return
`{"evidence": <Mapping>, "observedAt": <str|None>}` (or
`{"error": "<typed provider failure>"}`).  Wiring to the frozen R0–R12
adapters happens in the composition root at integration time; this
package imports zero `finco_radar` modules (enforced by test).
