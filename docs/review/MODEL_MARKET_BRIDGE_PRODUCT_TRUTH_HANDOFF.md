# MODEL ↔ MARKET BRIDGE V1 — Product Truth Handoff

For the Product Truth / staging stream (PR #147 lineage). Merge of this PR
introduces a new foundation surface; public wording should reflect it on
the next Product Truth pass.

## Suggested public status (if/when merged)

**MODEL ↔ MARKET BRIDGE = FOUNDATION / EXPERIMENTAL**

NOT:

- "SHIPPED VERIFIED-ASSET BINDING"
- anything implying production Verified assets exist

## Suggested wording

> The Model ↔ Market Bridge defines the source-proven identity contract
> between FINCO Model assets and canonical market evidence (economic asset
> identity + deployment). V1 is an experimental, fail-closed contract
> spike: read-only evaluation only, no production bindings, and no effect
> on FINCO Verify (production Verified assets remain 0).

## Where to update on next Product Truth pass

- `/roadmap` — "Model ↔ Market Bridge" card moves from NEXT to
  FOUNDATION / EXPERIMENTAL only after this PR merges.
- `docs/review/PRODUCT_TRUTH_RELEASE_MATRIX.md` — Yield-style row:
  status FOUNDATION / EXPERIMENTAL, source `app/model_market_bridge/`,
  authority = this PR, limitation "no production bindings; Verify seam
  designed but not activated".
- `/docs` Trust Stack — unchanged (the bridge is *not* a trust layer; it is
  a prerequisite for future Verify evidence).

## Hard invariants to preserve in copy

- `PRODUCTION_VERIFIED_ASSET_COUNT = 0` (unchanged by the bridge).
- `MODEL_MARKET_BINDING ≠ FINCO_VERIFIED_ASSET`; MODEL_ONLY never means
  VERIFIED.
- Binding requires explicit source-proven provenance; no display-metadata,
  heuristic or machine-inference identity.
- Signed Run ≠ binding truth; JEV never establishes identity; $FINCO never
  creates or strengthens bindings.
- Reference price ≠ executable price (bridge references evidence; it does
  not price anything).
