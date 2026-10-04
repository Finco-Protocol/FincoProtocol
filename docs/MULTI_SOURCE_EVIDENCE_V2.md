# Multi-source evidence V2 — MARKET · OFFICIAL_REFERENCE · ORACLE

Invariant: **MARKET != OFFICIAL_REFERENCE != ORACLE.** Each leg owns its own state, value, source timestamp,
`collected_at`, typed reason and provenance. A fresh leg never makes another leg current, and one failing leg never erases
the other two.

| Role | Authority (reused / new) | Source |
|---|---|---|
| `MARKET` | existing R-LIVE on-chain observation (`RLiveResult.onchain`) | Uniswap V3 TWAP x Chainlink USDG/USD |
| `OFFICIAL_REFERENCE` | existing Robinhood bound reference (`RLiveResult.authority.underlying`) — **reused, not re-fetched** | `ROBINHOOD_STOCK_TOKEN_BOUND_PRICE` |
| `ORACLE` | new `stock_token_oracle.read_stock_token_oracle` | per-asset Chainlink Stock Token price feed |

## Oracle binding authority
`app/radar_rwa/data/stock_token_oracle_feeds.json` is the reviewed registry. A binding is added **only** after its proxy
address, description, decimals and heartbeat are verified against official authority (the Chainlink Robinhood price-feed
catalog / Robinhood Chain documentation). Third-party repositories are discovery hints only. The loader rejects: a token
contract that is not the reviewed deployment, the wrong chain, a non-official provenance source, a non-https reference, a
non-address proxy, a proxy shared by two assets. An asset without a binding is `ORACLE_FEED_NOT_REVIEWED` and never blocks
a bound asset.

**State of the shipped registry: 0 of 13 bindings.** No feed address could be verified against official authority from the
authoring environment (no network), so none was added. All 13 are `ORACLE_FEED_NOT_REVIEWED`. No sequencer proxy is
bound either (`"sequencer": null`); see "L2 sequencer authority" below for what that does and does not mean. Official coverage clues (AAPL, AMD, GOOGL, AMZN, INTC, META, MSFT, NVDA, TSLA, and a later `RHDELL / USD`) are leads
for the review, not authority. AVGO, NFLX and SNAP stay unbound until officially proven.

## Oracle checks (first failure wins, typed)
`ORACLE_FEED_NOT_REVIEWED` -> `ORACLE_HEARTBEAT_NOT_REVIEWED` -> `ORACLE_CHAIN_BLOCK_STALE` -> sequencer
(`ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE` / `_DOWN` / `_GRACE_PERIOD`) -> `oraclePaused()`
(`ORACLE_CORPORATE_ACTION_PAUSED`, `ORACLE_PAUSE_STATE_UNAVAILABLE`) -> description / `decimals()` read from the proxy
(never hard-coded) -> round sanity (`answer > 0`, `updatedAt > 0`, `answeredInRound >= roundId`) -> age against the
feed-specific reviewed heartbeat (`ORACLE_HEARTBEAT_EXCEEDED` => `STALE`). All reads are pinned to one block.
24/5 update availability is not a heartbeat; there is no generic oracle TTL.

Units: the Stock Token feed already returns `underlying share price x multiplier` (value of ONE Stock Token).
`uiMultiplier()` is never applied again. Robinhood REST `/prices` bid/ask are raw underlying-equity values and must not
be mixed with these units.

## L2 sequencer authority (typed)
`"sequencer": null` only means *no sequencer uptime feed proxy is source-proven*. Whether that absence was reviewed is a
separate, explicit record, `sequencer_authority`, with a stable vocabulary:

| State | Meaning | Oracle behaviour |
|---|---|---|
| `UNREVIEWED` (also: no record at all, or a bare `sequencer: null`) | nobody has reviewed the official catalogs | **fail closed** — `ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE`, the oracle can never be AVAILABLE |
| `SOURCE_PROVEN` | an official uptime feed proxy is bound in `sequencer` | the feed is queried at the pinned block; UP / DOWN / grace behaviour unchanged |
| `OFFICIAL_FEED_NOT_PUBLISHED` | the official Chainlink L2 Sequencer Uptime Feed catalog was reviewed and publishes no feed for this chain (not "not applicable": Robinhood Chain is an L2) | bounded fallback below |

A record is honoured only with official provenance (official source, https URL, review date, reviewer); a bound proxy always
wins, and a record that contradicts the binding (`OFFICIAL_FEED_NOT_PUBLISHED` with a proxy, `SOURCE_PROVEN` without one) is
rejected at load.

**Review result recorded on 2026-10-04.** Robinhood's official documentation
(`docs.robinhood.com/chain/oracles-and-price-feeds/`) recommends checking a Chainlink L2 Sequencer Uptime Feed. Chainlink's
current official L2 Sequencer Uptime Feed documentation (`docs.chain.link/data-feeds/l2-sequencer-feeds`) lists its supported
networks and **does not list Robinhood Chain**; it also states Chainlink is no longer expanding these feeds to additional
networks. **No Robinhood Chain sequencer feed proxy has been source-proven and none has been inferred** (not from GitHub,
explorers, third-party protocols, search snippets or community documentation). The official pages were not reachable from the
authoring sandbox, so this record is the reviewer-supplied review result, marked as such in the registry.

### Bounded fallback (read-only intelligence only)
With `OFFICIAL_FEED_NOT_PUBLISHED` the Stock Token oracle read continues **without pretending a sequencer check occurred**.
Successful (and stale) oracle evidence states the fact: `sequencerAuthorityState = OFFICIAL_FEED_NOT_PUBLISHED`,
`sequencerChecked = false`, `l2LivenessGuard = PINNED_BLOCK_FRESHNESS_ONLY`, `sequencerGraceProtection = false`; there is no
"sequencer OK" status. Every other check still applies in full: exact binding, reviewed heartbeat, pinned canonical block,
`MAX_BLOCK_AGE_SECONDS` (`ORACLE_CHAIN_BLOCK_STALE` if the chain stops producing fresh blocks), exact-tag hash/reorg
verification, `oraclePaused()`, `description()`, `decimals()`, `latestRoundData()`, positive answer, valid `updatedAt`,
feed-specific heartbeat freshness.

**Limitation (explicit):** pinned-block freshness gives bounded current-chain-state protection. It is *not* a Chainlink
sequencer uptime feed. Without one FINCO cannot prove that a post-outage grace period has elapsed, and it does not fabricate a
grace period or a recovery time from block timestamps, feed `updatedAt` or elapsed time. Oracle-feed freshness is never
presented as L2 sequencer assurance. This is acceptable only because this leg is read-only market intelligence: it does not
execute, trade, liquidate, move funds, sign or custody. Any fund-moving use must be separately reviewed and does not inherit
this exception.

Robinhood Stock Token feeds are 24/5 and may hold the last published value in off-hours. That is not a heartbeat; there is no
generic weekend TTL, and the feed-specific reviewed heartbeat contract is unchanged until a later policy review based on real
observations.

## One pinned block per oracle cycle
`pin_oracle_block` reads `latest` exactly once and validates canonical block freshness once, producing an immutable
`OracleBlockContext` (number, exact hex tag, hash, timestamp). The L2 sequencer is evaluated at that tag, then for every bound
asset `oraclePaused()`, `description()`, `decimals()` and `latestRoundData()` are read at the same tag — `latest` is never read
again. After the reads the pinned block is re-read BY EXACT TAG and its hash must still match, otherwise
`ORACLE_BLOCK_REORG_OR_MISMATCH` and no leg becomes AVAILABLE. A sequencer reading taken at a different block is rejected
(`ORACLE_SEQUENCER_BLOCK_MISMATCH`). `collect_multi_source_once` pins once for the whole cycle; `read_stock_token_oracle`
called alone pins its own block and still evaluates sequencer and feed at the same block.

## Persistence
`SourceEvidenceStore` (`source_evidence` table, default beside the venue DB, override `FINCO_SOURCE_EVIDENCE_DB_PATH`):
append-only, one series per `(canonical_id, evidence_role)` with `source_authority`, `source_instrument`, `value`,
`source_timestamp`, `collected_at`, `state`, `reason`, `digest`. A cycle that returns evidence identical to the LATEST row
of that asset+role is a no-op (the digest excludes `collected_at`); any change appends, including A -> B -> A. Unavailable
legs are stored with their typed reason and a NULL value (never zero). No updates, no deletes, no interpolation.

Read path: `GET /radar/r-live/{canonical_id}/evidence` reads the store only (read-only SQLite, never creates the DB, no
provider call, exact AssetKey only) and the R-LIVE detail page renders it as a status-first "Source legs" panel. The panel
script is gated only on an approved asset — never on JEV visibility.

### Read-time effective status
Persisted rows are immutable and keep the collector's `persisted_state`. The server evaluates the user-facing `state` at READ
time (no browser clock), degrade-only: it may preserve or lower the persisted status, never raise it, and never uses
`collected_at` as evidence time. Only existing policy is reused:

| Role | Read-time rule |
|---|---|
| `MARKET` | the existing R-LIVE snapshot re-evaluation (`reevaluate_snapshot_row`): block <= 120 s, pool activity <= per-asset window (300 s), USDG/USD quote <= 86400 s, from the stored evidence timestamps; incomplete evidence -> UNAVAILABLE |
| `OFFICIAL_REFERENCE` | the R-LIVE authority `max_reference_age_seconds` through the authority engine's own age test; missing timestamp -> UNAVAILABLE |
| `ORACLE` | the CURRENT reviewed registry binding's heartbeat: no binding -> `ORACLE_FEED_NOT_REVIEWED`, no heartbeat -> `ORACLE_HEARTBEAT_NOT_REVIEWED`, no source timestamp -> `ORACLE_SOURCE_TIMESTAMP_UNAVAILABLE`, older than heartbeat -> `STALE` / `ORACLE_HEARTBEAT_EXCEEDED` |

Each leg returns `state` (effective), `persisted_state`, `reason`, `persisted_reason`, `value`, `source_timestamp`,
`collected_at`, `age_seconds`, `source_authority`, `source_instrument` and, for the oracle, the current `heartbeat_seconds`.
The UI shows a number only while the effective status is AVAILABLE; with 0 reviewed bindings the oracle row reads
"NOT REVIEWED", never a spinner or a zero.

## Staging runbook — 13-asset live matrix (bounded, one-shot)
Run on staging (has Robinhood/RPC connectivity). Nothing is scheduled; nothing is printed except evidence (no secrets).

```bash
cd /opt/finco_staging
set -a; . ./.env.tokenized-market-collector; set +a     # provides ROBINHOOD_RPC_URL (not printed)
.venv/bin/python -m app.radar_rwa.multi_source_collect > /tmp/multi_source_matrix.json      # read-only
.venv/bin/python -m app.radar_rwa.multi_source_collect --persist > /tmp/multi_source_matrix.json   # + append-only rows
```

Output: for each of the 13 reviewed assets — `symbol`, `canonical_id`, `oracle_binding`, and the three cells `MARKET`,
`OFFICIAL_REFERENCE`, `ORACLE` (`state`, `value`, `source_timestamp`, `age_seconds`, `reason`, `source_authority`,
`source_instrument`), plus `comparisons` (`basis_bps` and `time_skew_seconds` only when both legs are AVAILABLE, otherwise a
typed reason). Review the JSON before deciding anything about freshness policy.

### Source-proving an oracle binding (operator, one asset at a time)
1. In the official Chainlink Robinhood price-feed catalog find the feed for the exact reviewed Stock Token; record the
   proxy address, pair description, decimals and heartbeat.
2. Verify on chain 4663: `description()` equals the catalog pair, `decimals()` equals the catalog value,
   `latestRoundData()` is sane, and the proxy is not reused by another asset.
3. Add the binding (with `CHAINLINK_OFFICIAL_FEED_CATALOG` or `ROBINHOOD_CHAIN_OFFICIAL_DOCS` provenance, URL, date,
   reviewer) and the chain's official L2 Sequencer Uptime Feed + grace period; the loader and tests enforce the contract.

## Tokenized Markets freshness policy (not changed here)
The 900 s Tokenized observation ceiling over the oldest compound leg is unchanged. Whether it is still right once
independent MARKET / REFERENCE / ORACLE series exist cannot be decided without the live matrix above; collect it first.
