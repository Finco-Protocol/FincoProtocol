# MODEL ↔ MARKET BRIDGE V1 — Design & Contract Spike

Status: **DRAFT / EXPERIMENTAL — contract spike.** Not production. Creates
no production binding, promotes nothing to VERIFIED, and leaves
`PRODUCTION_VERIFIED_ASSET_COUNT` unchanged (= 0).

## A. Problem statement

FINCO has two mature halves that cannot yet vouch for each other:

- **Model** produces deterministic, committed calculations (Last Runs) for a
  *model asset* — a project instance or a canonical reference model.
- **Radar** observes *market evidence* for an **economic asset identity**
  (`economic_asset_uid`) on concrete **deployments** (chain + contract),
  e.g. the R-LIVE reviewed universe.

What is missing is the explicit, source-proven statement:

> this Model asset corresponds to this economic asset identity on this
> deployment, per this canonical market evidence.

Until that statement exists (and is auditable), no VERIFIED asset can exist.

## B. Why Model and Radar do not automatically meet

- Model identities are project instances / reference templates; Radar
  identities are on-chain economic assets and deployments. Nothing in the
  Model domain *is* a market identity, and vice versa.
- Display metadata (symbols, names) is not identity: the same symbol can
  wrap different contracts across chains/wrappers; names drift and collide.
- An attestation without provenance is a guess. FINCO does not ship guesses.

## C. Identity layers (kept strictly separate)

`IdentityLayer`: MODEL ≠ ECONOMIC_ASSET ≠ DEPLOYMENT ≠ MARKET_OBSERVATION.

| Layer | Contract | Notes |
| --- | --- | --- |
| Model asset | `ModelAssetIdentity` (`model_asset_uid`, `ModelAssetKind`) | `project:<project_id>` or `reference:<template_source>`; display name is inert metadata |
| Economic asset | `EconomicAssetIdentity` (`economic_asset_uid`) | reused verbatim from existing authority (R-LIVE / Verify namespace); never minted by the bridge |
| Deployment | `DeploymentIdentity` (`chain_id`, canonical contract, type, venue; `deployment_uid` deterministic) | one economic asset may have many deployments |
| Market observation | `MarketEvidenceReference` (authority, ref, observed_at) | referenced, never recalculated |

## D. Authority hierarchy

1. **Deployment authority** — pluggable read-only predicate; the production
   adapter is `r_live_deployment_authority()`, which reads the existing
   canonical R-LIVE approved registry (`APPROVED_BY_CANONICAL_ID`) verbatim.
   Unknown deployment → `DEPLOYMENT_UNKNOWN`.
2. **Economic-asset authority** — the existing canonical economic namespace;
   unknown uid → `ECONOMIC_ASSET_UNKNOWN`.
3. **Registry lifecycle** — ACTIVE / SUPERSEDED / REVOKED with deterministic
   binding UIDs (sha-256 over canonical immutable identity fields only).
4. **FINCO Verify** — a separate downstream authority. The bridge only ever
   exposes a *precondition seam* (below).

No external web search, no heuristic resolution, no machine inference exists
anywhere in the bridge (contract-tested).

## E. Schema — `MODEL_MARKET_BINDING_V1`

`ModelMarketBindingV1`: `schema_version`, `model_asset_uid`,
`model_asset_kind`, `economic_asset_uid`, `deployment` (→ `deployment_uid`),
`evidence` (authority / ref / observed_at), `provenance_type`,
`provenance_ref`, `status` (UNBOUND / CANDIDATE / SOURCE_PROVEN / STALE /
REVOKED), `lifecycle` (ACTIVE / SUPERSEDED / REVOKED), `supersedes_binding_uid`,
`created_at`.

`binding_uid` = sha-256 over canonical JSON of
`(schema, model_asset_uid, model_asset_kind, economic_asset_uid,
deployment_uid)` — immutable identity fields only. Same identity → same UID;
different deployment → different UID; display metadata never participates.

## F. Provenance requirements

`ProvenanceType` is a deliberately closed enum: `ISSUER_DOCUMENT`,
`CANONICAL_REGISTRY_RECORD`, `DEPLOYMENT_RECORD`, `CONTROLLED_METADATA`,
`REVIEWED_EVIDENCE_PACKAGE`. Every binding carries a `provenance_ref` that
points at the auditable source. There is no provenance member for
resemblance scoring, heuristics, search engines or machine inference, and
none can be added without a contract change.

## G. Conflict handling — fail closed

Typed reasons (`ReasonCode`): `MODEL_UID_UNKNOWN`, `ECONOMIC_ASSET_UNKNOWN`,
`DEPLOYMENT_UNKNOWN`, `BINDING_NOT_SOURCE_PROVEN`, `IDENTITY_CONFLICT`,
`DEPLOYMENT_CONFLICT`, `EVIDENCE_UNAVAILABLE`, `EVIDENCE_STALE`,
`BINDING_REVOKED`, `BINDING_SUPERSEDED`, `MALFORMED_BINDING`.

- duplicate canonical binding UID with differing identity fields →
  `IDENTITY_CONFLICT` (registry construction fails)
- one deployment source-proven bound to two economic assets →
  `DEPLOYMENT_CONFLICT` (registry construction fails)
- one model asset with two active proven bindings → `IDENTITY_CONFLICT`
  (evaluation)
- future-dated evidence → `MALFORMED_BINDING`

No conflict is ever resolved by priority guess.

## H. Stale / revoked semantics

- `EVIDENCE_STALE` (evidence older than the configured window): the binding
  remains *evidence of past state* and is typed STALE; it never silently
  becomes current identity authority.
- `BINDING_REVOKED`: unusable.
- `BINDING_SUPERSEDED`: historical only; corrections supersede rather than
  rewrite history. `supersedes_binding_uid` is carried by the replacement.

## I. Future FINCO Verify seam

`BridgeRegistry.verify_evaluation_seam(binding)` returns a
`VerifySeamResult`: `eligible_for_verify_evaluation` (SOURCE_PROVEN + ACTIVE
+ FRESH) plus the precondition dict. **Eligibility is not verification.**
The seam never calls `app.verified` mutation logic, never increments
counts, and never creates VERIFIED records. Future Verify integration must
apply its own source-attested evidence requirements on top.

## J. Signed Run relation

A Signed Run certificate attests the exact committed Model run. A future
certificate version MAY reference a `binding_uid`; that would tie the
attested run to the attested identity. Signed Run ≠ binding truth, and a
binding ≠ Signed Run. This PR changes no Signed Run cryptography or M-2
contract.

## K. JEV relation

JEV interprets; it never establishes identity. The bridge does not use JEV
to select an `economic_asset_uid`, choose a deployment, resolve conflicts,
or approve bindings. No JEV code or authority changed.

## L. Token relation

`$FINCO` ownership never creates a binding, never strengthens provenance,
never resolves conflicts, and never improves Verify state. Token may gate
access to tools later; never truth.

## M. Examples

See `tests/test_model_market_bridge.py` — cases A–K: exact source-proven
acceptance; wrong economic asset / wrong deployment / wrong chain / wrong
contract / unknown deployment rejections; fail-closed conflicts; stale,
revoked, superseded handling; deterministic duplicate identity. The
experimental read-only API spike
(`/api/v1.1/model-market-bindings/{model_asset_uid}` and
`/model-market-bindings/validate`) evaluates a synthetic fixture registry —
GET on the fixture model returns SOURCE_PROVEN/OK/FRESH; unknown model
returns MODEL_UID_UNKNOWN; validate is structural only.

## N. Explicit non-goals

No production bindings. No Verify promotion. No model-math change. No
R-LIVE pricing/TWAP/freshness change. No second market authority. No admin
CRUD. No JEV/token involvement. No multi-tenancy.

## O. Production activation requirements

1. An operational process that records source-proven bindings with auditable
   provenance references (registry/issuer documents or reviewed packages).
2. A persisted registry store with lifecycle transitions and audit history.
3. Explicit deployment + economic-asset authority configuration.
4. Freshness policy sign-off.
5. Separate FINCO Verify integration review (the seam stays closed until
   then).

`PRODUCTION_VERIFIED_ASSET_COUNT` remains **0**; this PR does not change it.
