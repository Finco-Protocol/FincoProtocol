# Model V2 Runtime Composition Contract (Workflow 05)

Status: pure orchestration layer connecting the reviewed Model V2 contracts
to the existing runtime. The canonical FINCO engine remains the one
calculation authority; composition resolves inputs BEFORE engine execution.

## Modules

| Module | Owns |
|---|---|
| `app/services/model_v2_composition/contracts.py` | `ModelV2WorkingState`, `ModelV2CompositionContext`, `ModelV2CompositionResult`, `RevenuePlanSelection`, `CostTemplateSelection`, status/error enums, composition digest |
| `app/services/model_v2_composition/compose.py` | `compose_project_inputs(...)` — precedence application, RevenuePlan bridge, CostTemplate bridge, scenario isolation, failure codes |

## Precedence (deterministic, applied in this order)

1. **Base ProjectInputs** — canonical inputs from the existing authorities
   (factories, reference-seed, working-copy). This already carries the
   system/technology/jurisdiction/client-template/project layers.
2. **CostTemplate materialization plan** (when a selection exists) —
   replaces canonical `CapexStructure` field items and `OpexItem` values
   with the reconciled Workflow 03 plan (decomposition already
   presence/active reconciled; contingency delegated to its authority).
3. **RevenuePlan** (when a selection exists) — bridges engine-expressible
   streams onto canonical `RevenueParams` fields.
4. **Scenario overrides** — CARRIED in the per-run composition context
   (and recorded in the result diagnostics). Workflow 05 does NOT
   interpret or apply their financial mathematics: the downstream
   canonical scenario authority owns their application. They never mutate
   the base Working Copy or the base ProjectInputs.

## Revenue bridge (fail-closed)

- Engine-expressible today: ONE enabled PPA stream (base tariff / term /
  index / production share) and merchant sales (price curve expanded
  through the existing `MerchantParams.price_at_year` authority for the
  project horizon; custom curves honored; missing custom curve fails
  closed).
- Not engine-expressible yet: CfD, FiT (fixed/premium), indexed FiT,
  auction-awarded tariff streams → `REVENUE_PLAN_STREAM_UNSUPPORTED`
  (composition refuses to approximate their economics). Reserved Storage
  stream types fail closed at the Workflow 02 contract boundary already.
- No PPA mathematics duplicated: PPAParams fields are copied onto
  `RevenueParams` verbatim.

## Cost bridge (fail-closed)

- Field plans replace canonical `CapexStructure` items (amount, y0 share,
  spending profile, asset class, useful-life override, depreciable flag).
- OPEX item plans replace canonical `OpexItem` values (Y1, per-line
  inflation, step changes, percentage-of-OPEX).
- Unknown CapexStructure fields, unknown depreciation asset classes,
  non-finite values → fail closed.
- Decomposition is already reconciled by Workflow 03 (parent = sum of
  active children); the bridge applies field-level economics only.
- **Plan identity** — the materialization plan MUST expose `template_id`
  and `template_version`, and both must equal the selection exactly. An
  absent or mismatched identity fails closed (`COST_TEMPLATE_UNRESOLVED`);
  identity is never defaulted from the selection wrapper.
- **Contingency** — the configured percentages are validated in their
  ORIGINAL type through `app.contingency_authority.validate_pct` (bool,
  str, NaN, ±Inf, out-of-range → `COST_TEMPLATE_VALUE_INVALID`) even when
  the contingency is inactive; `capex_active` / `opex_active` must be
  strict `bool`. Only after validation does an inactive contingency
  resolve to an effective 0.0 (configured value retained in the plan); an
  active one is applied through the existing contingency authority.

## Composition identity

`composition_hash` = deterministic SHA-256 over: schema marker,
`working_copy_ref`, the canonical RevenuePlan payload (ordered streams),
the **economic CostTemplate materialization payload**, scenario id and
the scenario overrides carried in the context.

The economic cost payload binds exactly what the cost bridge consumes:
template identity; per CAPEX field the canonical field identity, amount,
y0 share, spending profile, asset class, useful-life override, depreciable
flag and applicability; per OPEX item the canonical identity (name), Y1
amount, inflation, step changes, percentage-of-OPEX and applicability; the
configured contingency percentages and active flags. Configured values of
inactive rows remain bound. Presentation-only and non-consumed metadata
(labels, parent codes, sub-line persistence granules, contingency lineage,
eligible-basis metadata) is excluded. Same economics → same hash; any
economically relevant V2 state change → different hash.

## Legacy passthrough

No V2 selections → `LEGACY_PASSTHROUGH`: base ProjectInputs returned
untouched (exact legacy economics, including Solar/Wind reference
parity). No default V2 revenue or cost structure is invented.

## Scenario isolation

Scenario overrides ride the composition CONTEXT (per-run). A scenario
composition never mutates the base `ModelV2WorkingState`, never mutates
the base ProjectInputs, and is never persisted back into the Working
Copy. "Apply to Working Copy" is a separate future user action.

## Fail-closed

Composition errors raise typed errors (RevenuePlanBridgeError /
CostBridgeError / ValueError) with stable codes BEFORE engine execution —
a failed composition can never produce a Last Run input. Working Copy vs
Last Run separation is unchanged: composition runs from the Working Copy;
Last Run identity/evidence remains governed by the existing atomic run
commit.
