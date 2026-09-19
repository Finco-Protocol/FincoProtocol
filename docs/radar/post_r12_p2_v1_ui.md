# FINCO Radar v1 UI + Evidence Inspector (Post-R12 P2)

Narrow, read-only product surface over the frozen R0–R12 authority and
the canonical P1 acquisition runtime.

Core product rule:

> **one refresh → one P1 immutable snapshot_id → all visible Radar panels
> + Evidence Inspector reference that exact snapshot.**

Not R13.  No deploy.  No trading/signing/custody.  BUY/SELL is quote
direction only; the surface is labelled `READ-ONLY`.

## Composition (P1 inspection summary)

- **Frozen authority surfaces used (public only)** —
  `RobinhoodAssetRegistryAdapter` (R1 registry/bound-reference rows),
  `build_bound_reference_price` (R2/R7 reference engine),
  `LifiExecutionQuoteAdapter` (R0 quote authority),
  `compute_directional_gap` (R2 GAP engine).  These are composed inside
  the P1 provider callable at acquisition time; the UI never recomputes
  them.
- **P1 runtime** — `AcquisitionService` + `SnapshotStore` provide the
  immutable snapshot and the network-free read path.
- **Private `live_proof` helpers are never called** from browser
  routes or composition; the frozen USDG settlement parser is
  deliberately not duplicated — settlement is an injectable one-line
  composition parameter until a settlement adapter is promoted, and the
  execution/gap panels report explicitly `UNAVAILABLE`
  (`SETTLEMENT_RESOLVER_NOT_WIRED`) without it.

## Routes

| Route | Behaviour |
| --- | --- |
| `GET /radar` | page shell: identity, controls, panels area (no acquisition) |
| `POST /radar/refresh` | ONE `acquire()` → ONE `snapshot_id`; returns the panel fragment |
| `GET /radar/snapshot/{snapshot_id}` | re-render panels from the persisted snapshot (network-free) |
| `GET /radar/inspector/{snapshot_id}/{field}` | Evidence Inspector lineage fragment (network-free) |

## Configured asset (P3)

Exactly one canonical asset in this PR: `AAPL` on chain `4663`,
deployment `0xaaaa…aa` (env-overridable via `RADAR_V1_ASSET_*`), uid
`AAPL`.  Identity is chain + contract + UID — never ticker alone.

## Controls (P4)

BUY / SELL and `$100` / `$1,000` only — the sizes already supported by
the frozen reviewed Radar path.  Direction/size are part of the
acquisition request, so they are bound by the P1 request fingerprint.

## Evidence Inspector (P6)

`NUMBER → SOURCE → DERIVATION → LINEAGE → EVIDENCE → VERIFICATION`,
always read from the exact referenced snapshot: displayed value, owning
authority phase, provider + provider state, `snapshot_id`, request
fingerprint, `observedAt`, evidence digest, preserved provider evidence,
gaps/unavailability reasons with safe internal codes, and the
verification state — which reports `UNAVAILABLE` honestly because the P1
acquisition snapshot does not carry R11 verification.  Nothing is
invented.

## Correction B — final UI contract closure

- **HTMX licensing** — the vendored `htmx.min.js` (v1.9.12) carries the
  correct upstream `0BSD` license metadata (`htmx.min.js.LICENSE`);
  version identity is test-pinned.
- **Uniform Inspector-link contract** — every `.inspector-link` is
  rendered by one shared template macro with identical `href`, `hx-get`
  (equal to `href`), `hx-target="#radar-inspector"` and
  `hx-swap="innerHTML"`; an exhaustive attribute-level test follows every
  link and proves zero reacquisition.
- **Section vs field availability** — the Inspector separates section
  availability from field-value availability: a non-OK execution quote
  still shows its frozen `status` (e.g. `INSUFFICIENT_LIQUIDITY`) in the
  NUMBER stage, while the exact `unavailableReason` is preserved in the
  GAPS stage.  A missing field value renders `UNAVAILABLE` and is never
  synthesized.

## Read-only safety (P11)

No wallet connect, approve, swap, order submission, signing or custody
anywhere in the surface; the only mutation-style control is the Refresh
button posting to `/radar/refresh`, which acquires observations and
writes nothing but P1 snapshots.

## Governance (P13)

CI gates: zero diff on `finco_radar/**`, `financial_engine/**`,
`finco_core/**`, `finco_protocol/**` vs the frozen authority anchor
`1045a343cbe3c21c8b0cb7070582d8d9a9533362`; zero diff on
`app/radar_runtime/**` vs the P1 merge `d8c471b9e5a591db52a78837a788f8e53647bb53`
(P1 semantics frozen); focused UI tests; P1 runtime regression; full
repository suite; compileall; public safety.
