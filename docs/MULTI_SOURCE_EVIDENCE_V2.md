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
authoring environment (no network), so none was added. All 13 are `ORACLE_FEED_NOT_REVIEWED` and the sequencer authority is
unset. Official coverage clues (AAPL, AMD, GOOGL, AMZN, INTC, META, MSFT, NVDA, TSLA, and a later `RHDELL / USD`) are leads
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

## Persistence
`SourceEvidenceStore` (`source_evidence` table, default beside the venue DB, override `FINCO_SOURCE_EVIDENCE_DB_PATH`):
append-only, one series per `(canonical_id, evidence_role)` with `source_authority`, `source_instrument`, `value`,
`source_timestamp`, `collected_at`, `state`, `reason`, `digest`. A cycle that returns evidence identical to the LATEST row
of that asset+role is a no-op (the digest excludes `collected_at`); any change appends, including A -> B -> A. Unavailable
legs are stored with their typed reason and a NULL value (never zero). No updates, no deletes, no interpolation.

Read path: `GET /radar/r-live/{canonical_id}/evidence` reads the store only (read-only SQLite, never creates the DB, no
provider call) and the R-LIVE detail page renders it as a status-first "Source legs" panel.

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
