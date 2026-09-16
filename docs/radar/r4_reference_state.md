# FINCO Radar R4 — REFERENCE STATE

## Scope

R4 owns **reference-state classification**: it answers

> What state is the official reference actually in, and is its apparent freshness or staleness economically explainable?

R4 builds on the frozen R0/R1/R2/R3 authorities and adds a typed state layer on top. It is read-only. It does not submit transactions, sign wallets, custody assets, approve tokens, create signals, rank assets, produce scores, or decide whether a GAP is attractive.

`on-chain tradability != underlying reference freshness` — the Stock Token may trade 24/7 on-chain while the underlying official reference behaves differently.

`old != stale` — an old reference is only *unexpectedly* stale when a source-proven OPEN session says an update should have happened.

`old + closed session may be expected-static only with source-backed session evidence` — never from nighttime, weekends-by-weekday-math, or server timezones.

`fresh != usable` — a fresh reference is still unusable when the asset is halted or inactive, when a multiplier transition is overdue/unresolved, or when corporate-action evidence is unresolved.

## What R4 owns — and what it does not

Owned: asset lifecycle, halt state, reference freshness, market/session state dimension, corporate-action state, multiplier-transition interpretation, typed reference usability.

Not owned: GAP economics (R2), liquidity evidence (R3), any signal interpretation (R5), any terminal surface (R6). Every snapshot declares:

```
referenceStateAuthority = R4_APPLIED
signalAuthority = R5_NOT_YET_APPLIED
terminalAuthority = R6_NOT_YET_APPLIED
```

`REFERENCE_EXPECTED_STATIC + GAP = 350 bps` is still not `ARBITRAGE`, `BUY` or an `OPPORTUNITY` — that decision belongs to R5.

## State dimensions

R4 models state as separate typed dimensions, never one vague string:

| Dimension | Values | Source |
|---|---|---|
| Asset lifecycle | `ACTIVE` / `INACTIVE` / `UNSPECIFIED` | official R1 `/assets` status |
| Halt | `NOT_HALTED` / `TRADING_HALTED` | official `isTradingHalt` from `/prices` |
| Freshness | `CURRENT` / `EXPECTED_STATIC` / `STALE_UNEXPECTED` / `UNRESOLVED` | computed from age + policy + session evidence |
| Market/session | `OPEN` / `CLOSED` / `UNRESOLVED` | caller-supplied evidence only (see below) |
| Corporate action | `NONE` / `IN_PROGRESS` / `COMPLETED` / `UNRESOLVED` | R4 `/corporate-actions` adapter |
| Multiplier | `CURRENT` / `PENDING_FUTURE` / `TRANSITION_DUE_UNRESOLVED` / `INCONSISTENT` | R1 multiplier pair interpreted by R4 |

## Freshness policy — no hidden magic

`ReferenceStatePolicy` is mandatory and caller-supplied; the engine has no default thresholds and no universal "120 seconds means current" rule:

- `max_live_reference_age_seconds` — age at or below which the reference is `CURRENT`;
- `max_session_evidence_age_seconds` — OPEN/CLOSED session evidence older than this cannot classify freshness and downgrades to `UNRESOLVED`;
- `max_clock_skew_seconds` — tolerated negative age (clock skew); anything more negative fails closed with `EVIDENCE_TIME_MISMATCH`.

`reference_age = as_of − reference.generated_at`. All timestamps must be timezone-aware. The live proof declares its own explicit thresholds and the artifact records the actual policy used.

## EXPECTED_STATIC is a reserved state — currently unreachable

`old != stale`, and **point-in-time CLOSED ≠ proof that an old reference was expected to remain static**. A single CLOSED observation proves only that the session is closed at that instant; it cannot prove the reference was expected to stay unchanged during the whole interval in which it aged. A reference that silently aged while the session was provably OPEN is `STALE_UNEXPECTED`; a reference that aged without interval-capable session evidence is `UNRESOLVED` and blocks usability with `MARKET_SESSION_UNRESOLVED`.

`EXPECTED_STATIC` is therefore **reserved and currently unreachable**: it may become reachable only after a future source-backed session authority proves the relevant non-updating interval / session-close boundary (for example an authoritative close timestamp covering the staleness period). Until then:

`R4_MARKET_SESSION_AUTHORITY_REQUIRED`

No nighttime, weekday, UTC, DST or holiday heuristic may be introduced to reach it. Deterministic tests pin the adversarial counterexample (reference generated at 12:00, stale during an OPEN session, CLOSED evidence at 18:01, evaluation at 18:02 → `UNRESOLVED`, never `EXPECTED_STATIC`). The Stock Token trading 24/7 on-chain is never evidence that the underlying equity reference updates 24/7.

## Session-source authority boundary

The official surfaces consumed here expose `tradingCapabilities` — what sessions an underlier *supports*. **Capability is not current-session state.** No machine-readable "market open/closed now" authority exists on this source surface, so R4 carries an explicit typed boundary:

`R4_MARKET_SESSION_AUTHORITY_REQUIRED`

The engine accepts caller-supplied `MarketSessionEvidence` (OPEN/CLOSED with provenance and a fresh `observedAt`, or UNRESOLVED). Deterministic tests use clearly-labelled synthetic evidence; the live proof evaluates with UNRESOLVED and honestly reports the blocker instead of weakening the semantics. A `CURRENT` reference needs no session authority to explain its age and may be usable with an unresolved session; an old one without session authority blocks usability.

## Halt semantics

`isTradingHalt = true` is explicit official evidence and is never inferred from timestamps. `fresh + halted != normal current reference`: freshness and halt are preserved as separate dimensions and usability blocks on the halt.

## Asset lifecycle semantics

The official R1 `ASSET_STATUS_*` wins. An inactive asset is never upgraded to active because quotes, routes or `/prices` rows still exist.

## Corporate-action authority

The R4-owned adapter reads `/corporate-actions` (top-level `corpActions` list). Verified live wire shape: each row carries `id` (the **canonical asset UID** — all observed rows matched `/assets` ids), `type` (`CORPORATE_ACTION_TYPE_*`), `status` (`CORPORATE_ACTION_STATUS_IN_PROGRESS` / `..._COMPLETED`), `processDate` (structured `{year, month, day}` — a calendar date with no time zone), `tokenSymbol`, `deployments`, and a typed `details` variant (e.g. `cashDividend: {underlyingSymbol, rate}`).

Rules:

- rows bind by official UID + exact deployment; matching ticker with foreign UID fails closed (`REFERENCE_IDENTITY_MISMATCH`); a canonical deployment under a foreign UID fails closed; malformed rows fail typed closed (`CORPORATE_ACTION_EVIDENCE_INVALID`);
- unknown/forward action types and statuses are preserved verbatim and classified conservatively: an unsupported IN-PROGRESS action yields `UNRESOLVED` (blocking), never `NONE`;
- multiple historical rows per asset are valid and retained in deterministic source order; an IN_PROGRESS row is never dropped because a newer COMPLETED row exists;
- known-type actions (e.g. routine IN-PROGRESS cash dividends) are classified and preserved as evidence without automatically blocking an otherwise usable reference; the multiplier dimension independently guards real transitions.

## Multiplier-transition semantics

R1's `currentMultiplier` remains the only multiplier authority used by R2; R4 interprets state and never substitutes `pendingMultiplier`, never re-derives multipliers from corporate-action details (no reinvestment math, no split arithmetic):

- no pending multiplier → `CURRENT`;
- pending with future effective time → `PENDING_FUTURE` (evidence preserved; does not block by itself);
- `as_of >= pending_multiplier_effective_at` while still pending → `TRANSITION_DUE_UNRESOLVED`, blocking — this prevents using the old multiplier across an effective corporate-action boundary;
- pending without effective time (unreachable via the frozen R1 parser; defensive) → `INCONSISTENT`, blocking.

## Source precedence

Official `/assets` status is the lifecycle authority; official `isTradingHalt` is the halt authority; official `currentMultiplier` is the multiplier authority; `/corporate-actions` explains transitions but never authorizes new economics. Ticker is discovery metadata only and may never repair an identity mismatch. Evidence is never stitched across candidates.

## Typed statuses

Two deliberate vocabularies exist and must not be confused (Correction A4):

- **`ReferenceStateStatus`** is the computation/boundary outcome family. Members are thrown as `ReferenceStateError` (or carried on computation results) when classification itself cannot proceed: `REFERENCE_STATE_OK`, `REFERENCE_IDENTITY_MISMATCH`, `REFERENCE_EVIDENCE_INVALID`, `MARKET_SESSION_UNRESOLVED`, `REFERENCE_STALE_UNEXPECTED`, `CORPORATE_ACTION_EVIDENCE_INVALID`, `CORPORATE_ACTION_UNRESOLVED`, `MULTIPLIER_TRANSITION_UNRESOLVED`, `EVIDENCE_TIME_MISMATCH`. Some members mirror blocking reasons; they are retained as vocabulary for boundaries that may throw in the future (for example a richer session authority) and are deliberately not thrown merely because a reference is unusable.
- **`ReferenceStateReason`** is the classified-usability vocabulary: reasons attached to a *successful* classification whose outcome is an unusable reference. A successful R4 computation may therefore return `status = REFERENCE_STATE_OK`, `reference_usable = false`, `blocking_reasons = (...)` — this is intentional.

Infrastructure/network failures serialize separately as `INFRASTRUCTURE_ERROR` at the live-proof boundary — never collapsed into a generic `BLOCKED`, and never used for source-evidence corruption (which is typed by the R4 contract).

Blocking reasons (usability is reconstructible: `reference_usable` is true exactly when the typed `blocking_reasons` tuple is empty, in deterministic precedence order): `ASSET_INACTIVE`, `TRADING_HALTED`, `REFERENCE_STALE_UNEXPECTED`, `MARKET_SESSION_UNRESOLVED`, `MULTIPLIER_TRANSITION_UNRESOLVED`, `MULTIPLIER_STATE_INCONSISTENT`, `CORPORATE_ACTION_UNRESOLVED`.

## Evidence provenance

Every snapshot preserves: asset UID/key/symbol, reference source and `generatedAt`, raw BID/ASK and currency, current/pending multiplier with effective time, `isTradingHalt`, registry observed time, corporate-action `observedAt`, evaluation `asOf`, reference age, per-row raw corporate-action payloads, the session-evidence claim with provenance, and the exact policy values. No secrets or credentials are ever recorded.
