# FINCO Radar V1 — Frozen Release Limitations

**Release state:** DEV CLOSEOUT / DRAFT / NOT STAGING ACCEPTED.

This document distinguishes supported factual evidence from non-authorized economic claims. It does not change any market authority, entitlement, CI gate or financial output.

## Supported, evidence-qualified statements

- **Last canonical price** is the latest previously observed actual token-market price, accompanied by its **original** source evidence timestamp/age. Its display does not make it current.
- **Current basis** exists only when the actual MARKET and official underlying REFERENCE inputs are eligible under the original clock, freshness and 300-second source-clock skew rules. Stored basis without valid source evidence is not current basis.
- **Historical Relative Value** is a descriptive distribution computed only from a representation's **own** usable history: at least 8 usable observations across at least 3600 seconds. Historical distribution may exist while the current market is stale.
- **Dislocation persistence** is an observed interval when canonical evidence proves continuity. Sign reversals restart an episode; missing evidence or unknown prehistory prevents claiming a start.
- **Deepstate NVDA** provides audited executed historical market fills quoted in USDG/NVDA. USDG is **not implicitly USD**. No approved current Deepstate freshness or executable cross-venue quote authority exists.
- **Signal lifecycle** is a record of observed descriptive changes, not financial advice. **Alert readiness is not notification delivery**.

## Unsupported or blocked assertions

| Claim | Product state and reason |
|---|---|
| Live, executable Deepstate NVDA/USD price | NOT APPROVED — separate conversion and source-specific freshness authority missing |
| Current Robinhood/Deepstate executable arbitrage | UNAVAILABLE — historical pairing is not an executable quote |
| Universal Chainlink per-token oracle coverage | UNVERIFIED — exact per-token proxy, heartbeat and sequencer binding not proven for full universe |
| Synthetic history / interpolated percentage rank | PROHIBITED |
| Provider transport collected_at substituted for market ts | PROHIBITED |
| Current market premium from a stale historic value | PROHIBITED |
| Historical distribution as a forward-looking return or trade recommendation | UNSUPPORTED |
| Observed lifecycle event as delivered user notification | NOT IMPLEMENTED AS A CLAIM |
| Temporary audit database as additional production market history | PROHIBITED |
| Radar V1 production/staging acceptance | NOT ESTABLISHED by code-only closeout |

## Store and audit restrictions

The audit accepts an existing **checkpointed** SQLite source (or an operator-supplied consistent offline copy). It must never:

- initialize the schema in the source DB;
- delete, update, backfill or reset observations;
- poll providers, construct new prices or start collectors;
- ignore nonempty WAL material that would cause historical evidence omission;
- infer market eligibility from a parsed price when source/normalization/reference policy denies it;
- silently fill unknown historical start time or percentage denominators.

The audit refuses missing/corrupted/unsafe source evidence with explicit status and does not claim release success. Its default 512 MiB snapshot size limit is an operational safety bound, not a minimum required market coverage. Use a separately authorized offline mirror for larger datasets; document its origin and any resulting representativeness limits.

## Freeze outstanding conditions

1. Independent exact-head code review and all mandatory CI gates PASS.
2. Independent source scope verification: no changes to frozen Radar price, collector, market, financing or entitlement authorities.
3. Operations establishes actual staging build identity, collector cadence and persisted real source timestamps.
4. Real staging acceptance matrix is performed and evidence-backed; every mandatory row PASS or separately justified N/A.
5. R6 Signal Feed (Workstream A) is integrated/reviewed before its staging acceptance row can be closed.
6. Data readiness is evaluated from a genuine operator snapshot, not synthetic benchmark fixtures.
7. Security checks confirm owner, entitlement, historical redaction and API envelope behavior across roles.
8. No remaining blocker to historical/clock truth, no unexplained read/write access, and no unsupported live claims.

**State after this Workstream B documentation:** AWAITING INDEPENDENT REVIEW AND REAL-DATA ACCEPTANCE. No merge or deployment approval is asserted.
