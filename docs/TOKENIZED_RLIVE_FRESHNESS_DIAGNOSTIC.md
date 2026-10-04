# Diagnostic — R-LIVE "Market age" vs Tokenized collector freshness (NVDA path)

Status: code-level trace on canonical main `2f963a7`. No staging data, logs or RPC access were available when this was written,
so anything that depends on live evidence is marked **not determined**.

## Data path

1. `collect_r_live` / `collect_r_live_batch` → `format_r_live_result` (`app/radar_rwa/r_live_service.py`) builds
   `token_reference`, `robinhood_basis`, `b1_0_premium` and `freshness`.
2. `token_reference.observed_at` is the on-chain observation's **effective evidence time**
   (`finco_radar/authority/r_live_onchain.py`): `min(block time, Chainlink USDG/USD `updatedAt`, last pool swap time)`.
   It is the age of the **oldest** leg, not of the most recent one.
3. R-LIVE composite state is `AVAILABLE` only if on-chain, token, underlying and premium layers are all `AVAILABLE`.
   The token layer is tested against `max_reference_age_seconds = MAX_QUOTE_AGE_SECONDS = 86400` (Chainlink heartbeat),
   the snapshot re-evaluation uses per-leg ceilings: block 120 s, pool activity 300 s (TWAP window), quote 86400 s.
4. Tokenized collector: `market_observation_from_r_live` persists only `state == "AVAILABLE"` rows. The observation's
   `ts` is `token_reference.observed_at` (effective evidence time) and `collected_at` is the collection clock.
5. Tokenized read-time freshness (`finco_radar/venues/intelligence.effective_observation_state`) compares `ts` with a single
   ceiling (`FINCO_TOKENIZED_MARKET_MAX_AGE_SECONDS`, default 900 s, staging example 900).

## Are "Market age" and Tokenized freshness the same evidence leg?

**No.**

| Label | What it measures | Ceiling |
|---|---|---|
| R-LIVE "Market" | age of the last Uniswap pool swap (`lastPoolActivityAt`) | 300 s |
| R-LIVE "Oracle" | age of the Chainlink USDG/USD update (`quoteUpdatedAt`) | 86400 s |
| Tokenized observation `ts` | token reference **effective evidence time** = oldest of block / quote / pool leg | 900 s |

So a minutes-old market leg next to a 19 h-old oracle leg is fully consistent: R-LIVE is `AVAILABLE` (every leg inside its own
reviewed ceiling) while the Tokenized observation clock is ~19 h old and reads `STALE` under the 900 s ceiling, so "priced now" is 0.
This is a **policy difference between two reviewed freshness definitions**, not a wiring defect: the collector uses the
canonical R-LIVE payload exactly as emitted and never re-derives or alters any R-LIVE value. The semantic is pinned by
`tests/test_radar_crypto_surface_coherence.py::test_tokenized_observation_clock_is_the_token_reference_effective_time_not_pool_activity_age`.

## Other path to "0 priced"

If the collector's own acquisition cycle returns R-LIVE `STALE` or `UNAVAILABLE` for an asset (for example the independent
token reference is outside its max age, or no recent pool swap), `market_observation_from_r_live` returns `None` and nothing is
persisted. That is the correct fail-closed behavior. Which of the two paths applied on staging per asset is **not determined here**;
the collector's per-asset report (state, reason) answers it.

## Oct 1 15:39 → Oct 4 gap

Not determined from the repository. The code shows what would produce such a gap, and which evidence discriminates:

| Candidate cause | Discriminating evidence |
|---|---|
| No pool swaps (illiquid / market closed) | `lastPoolActivityAt` in the stored snapshot payloads and on-chain `Swap` logs after Oct 1; `POOL_ACTIVITY_STALE` reasons |
| Oracle not updating (heartbeat/market hours) | `quoteUpdatedAt` history; `QUOTE_FEED_STALE` reasons |
| Collection not operating | R-LIVE snapshot `collected_at` series; collector health `last_attempt_at` / `last_success_at` |
| Source/history incomplete | gaps in digest-verified B1.3 history vs. snapshot rows |
| Tokenized observations never persisted | collector per-asset report: `available` vs `stale` vs `unavailable`, `persisted` |

An explanation must not be asserted without that evidence. It informs the multi-source PR: if a single 900 s ceiling over the
oldest leg is the wrong policy for tokenized equities (market-hours effects), that is a reviewed decision to make there, not a
presentation change.
