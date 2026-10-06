# Model V2 Cost Template Contract

Status: Workflow 03 domain/service foundation. No runtime wiring, no
ProjectInputs integration, no UI. The canonical financial engine never learns
that a template existed.

## 1. Existing authority inventory (independently verified)

| Authority | Location | Contract essentials |
|---|---|---|
| `CapexItem` | `finco_core/inputs/_models.py` | `name, amount_keur, y0_share, spending_profile, asset_class, useful_life_override, is_depreciable` |
| `CapexStructure` | `finco_core/inputs/_models.py` | 15 named `CapexItem` fields (C.01–C.16 economic; C.13 contingency; C.15 acquisition/development; C.16 rights) + 9 scalar fields (`idc_keur`, `commitment_fees_keur`, `bank_fees_keur`, `other_financial_keur`, `vat_costs_keur`, `vat_facility_idc_keur`, `vat_facility_commitment_fee_keur`, `reserve_accounts_keur`, `other_financial_keur`) — C.17 Financing Costs / C.18 Reserve Accounts are these RUNTIME-DERIVED scalars |
| C-code map | `app/persistence/capex_sub_lines.py` (`CAPEX_CATEGORY_TO_FIELD`) | C.NN ↔ CapexStructure field, with the intentional C.08/C.11 alias (C.11 non-owning alias folds into `audit_legal`) |
| CAPEX child taxonomy | `app/reference_detail_catalog.py` (`PUBLIC_GENERIC_DETAIL_V1`) | per-technology children `C.NN.NN` with integer weights → deterministic shares; no amounts of its own |
| `CapexSubLine` | `app/persistence/capex_sub_lines.py` | `sub_line_id, parent_category_code, business_code (C.NN.U### user / C.NN.NN reference-detail), display_order, label, amount_keur, schedule_json, scalar_metadata, source ("user"|"reference_seed"), replay_metadata, is_active` (soft delete) |
| CAPEX fold | `fold_sub_lines_into_capex` + `_fold_user_sub_lines_replacing_base` | pure; Correction B authority: sub-lines are a BREAKDOWN/REPLACEMENT of the canonical field (zero base + fold) — ALL active sub-lines including C.NN.U### user rows participate; unknown category raises; active-only |
| `OpexItem` | `finco_core/inputs/_models.py` | `name, y1_amount_keur, annual_inflation, step_changes ((year, amount)…), percentage_of_opex` (mutually exclusive with steps) |
| OPEX taxonomy | `app/reference_detail_catalog.py` | children `B.NN.NN` per technology (B.01 Technical Management: B.01.01 Asset Management Contract … B.01.06 SCADA / Monitoring Platform) |
| `OpexSubLine` | `app/persistence/opex_sub_lines.py` | `parent_group_code, business_code (B.NN.U###), label, amount_keur (Y1), inflation_pct, source, replay_metadata, is_active` |
| Contingency | `app/contingency_authority.py` | percentage + eligible basis + `ContingencyLineage` persisted in replay metadata; `apply_capex_contingency` / `apply_opex_contingency` |
| Reference seed (Template V0) | `app/services/reference_seed_service.py` | `ScalingMode` (PER_MW/FIXED/PERCENTAGE/RATE/RATIO/DURATION/REFERENCE_LOCKED/DERIVED); `seed_profile v3` with per-line `unit_rate_keur_per_mw`; sub-line `replay_metadata` carries `unit_rate_keur_per_mw + canonical_key + scaling_mode`; rescale rule: **rescale untouched `reference_seed` PER_MW lines, never user overrides**; explicit reset authority |
| Depreciation classes | `finco_core/inputs/_models.py` | `AssetClass` enum + `ASSET_CLASS_USEFUL_LIFE` defaults; per-item `useful_life_override` / `is_depreciable` |

## 2. Reuse / Adapt / Net-new matrix

| Target | Classification |
|---|---|
| CAPEX hierarchy (C.NN → C.NN.NN) | **REUSE DIRECTLY** (`reference_detail_catalog`) |
| CAPEX child identity (presentation code vs business code) | **REUSE DIRECTLY** (`C.NN.NN` presentation vs `C.NN.U###` persistent user identity) |
| CAPEX amount semantics | **REUSE DIRECTLY** (`CapexItem.amount_keur`) |
| CAPEX PER_MW scaling | **REUSE DIRECTLY** (seed `unit_rate_keur_per_mw` + rescale rule) |
| CAPEX schedule (y0_share / spending_profile / schedule_json) | **REUSE DIRECTLY** (roundtripped by the template) |
| Construction timing / IDC / fees | **DERIVED — REMAINS OUTSIDE TEMPLATE** (financing authority owns it) |
| Contingency | **ADAPT** (template stores percentage + basis + lineage; materialization delegates to `contingency_authority`) |
| Depreciation class / useful life / depreciable | **REUSE DIRECTLY** (roundtripped metadata; no new depreciation math) |
| VAT/WHT / financing / reserve scalars | **DERIVED — REMAINS OUTSIDE TEMPLATE** (C.17/C.18 `DERIVED_RUNTIME` metadata only) |
| OPEX hierarchy (B.NN → B.NN.NN) | **REUSE DIRECTLY** |
| OPEX Y1 amount / line inflation / step changes | **REUSE DIRECTLY** (exact roundtrip) |
| OPEX percentage_of_opex (B.13) | **ADAPT** (percentage driver preserved, not frozen amount) |
| Reference-seed lineage / override preservation / rescale | **ADAPT** (generalized: template lineage + template-derived vs overridden classification) |
| Generic Solar/Wind taxonomy + reference economics | **REUSE DIRECTLY** (factories + catalog; zero numerical change) |
| CostTemplate envelope, versioning, client extraction, driver surface | **NET-NEW** (this workflow) |
| Scenario targeting of cost rows | **DERIVED — REMAINS OUTSIDE TEMPLATE** (scenario authority mutates materialized inputs) |

**MODEL_V2_COST_TEMPLATE_REUSE_MAP_COMPLETE**

## 3. Contract

`app/services/cost_template/` (pure; no DB, no engine calls):

- `contracts.py` — `CostTemplate` (immutable envelope: `template_id`,
  `version`, `name`, `technology`, `kind` GENERIC|CLIENT, `status`,
  `capex_items`, `opex_items`, provenance, `created_at`,
  `reference_capacity_mw` / `source_project_ref`), `CapexTemplateItem`,
  `OpexTemplateItem`, `CostDriver`, `ScalingBasis`, `ItemClassification`
  (ACTIVE | DERIVED_RUNTIME). Fail-closed validation: duplicate item ids,
  unknown parent codes, non-finite/negative economics, driver/class
  combinations, C.17/C.18 never editable items.
- `generic.py` — deterministic Generic Solar/Wind template builders from the
  canonical reference factories + `PUBLIC_GENERIC_DETAIL_V1` children.
- `client_extract.py` — `CostProjectState` (pure capture of project cost
  truth) + `extract_client_cost_template` (exact-snapshot by default; scaling
  never inferred from `amount/capacity`).
- `materialize.py` — `MaterializationContext` (capacity, eligible basis),
  `resolve_cost_template`, `build_materialization_plan` →
  `CapexSubLinePlan` / `OpexSubLinePlan` / field-level updates /
  contingency-percentage entries. Deterministic, order-independent.
- `serialize.py` — canonical deterministic JSON (sorted keys, explicit
  schema/version stamp); identical template → identical bytes.

## 4. Driver matrix

**Active (map exactly to existing authority):**

| Driver | Surface | Materialization |
|---|---|---|
| `EUR_PER_MW` | CAPEX + OPEX | amount = rate × context capacity (the seed V0 behavior) |
| `ABSOLUTE_KEUR` | CAPEX + OPEX | amount as-is (client exact snapshot) |
| `PERCENT_OF_ELIGIBLE_CAPEX` | C.13 | delegated to `contingency_authority` (pct + basis + lineage) |
| `PERCENT_OF_OPEX` | B.13 | `OpexItem.percentage_of_opex` semantics |

**Reserved (fail closed / metadata only):**

| Driver | Reason |
|---|---|
| `EUR_PER_MWH` (variable O&M) | no existing authority resolves a generation-dependent OPEX Y1 without runtime recalculation — future runtime capability |
| `EUR_PER_KW_YEAR` presentation | display-only alias of `EUR_PER_MW` — not a separate driver |
| `DERIVED_RUNTIME` | C.17/C.18 and DC-style derived lines — metadata only, never materialized as inputs |

## 5. Materialization, overrides, versioning

- **One-way materialization**: template → project-owned rows. No live
  inheritance; editing a template never mutates existing projects.
- **Versions immutable**: any change creates a new `version`; lineage records
  `(template_id, version)` per materialized row (`replay_metadata`).
- **Override rule (generalized seed V0)**: rows carry
  `template-derived | user-override`; rescale/reapply touches only
  `template-derived` rows; overrides are never silently overwritten.
- **Identity**: template `item_id` is stable across versions; project rows
  keep their persistent business codes (`C.NN.U###` / `B.NN.U###` never
  renumbered); presentation codes never become financial identity.
- **Removed/deactivated rows**: represented with `active=False`
  (soft-delete semantics preserved end-to-end).
- **Heterogeneous OPEX inflation**: preserved per child line; a parent may
  display "mixed" but the template stores child rates individually.

## 6. Roundtrip (the core correctness proof)

project cost state → `extract_client_cost_template` →
`resolve_cost_template` → `build_materialization_plan` → economically
identical project cost state, for supported structures: exact amounts,
per-line inflation, step changes, CAPEX timing profiles, depreciation
metadata, contingency percentage + basis, user-added row identities.

## 7. DEVEX future seam

C.15 Project Acquisition / Development stays a normal CAPEX field in this
workflow (zero economic change). `CapexTemplateItem` carries an optional
`devex_candidate` classification flag (inactive) recording the future
Development-Costs migration seam; no DEVEX engine is built here.

## 7b. Hardening conventions (Corrections A-F, consolidated)

The sections below document the CURRENT executable semantics of the
materialization layer; earlier per-correction section text that diverged
from the code has been consolidated here to keep documentation equal to
implementation.

- **Authority precedence on decomposed OPEX parents (Correction G)**:
  decomposition is evaluated FIRST, keyed by the canonical OpexItem
  identity (`canonical_parent_key`, falling back to the item label for
  generic builders - never the B.NN group code). When decomposition exists,
  `parent amount = sum(active children)` and
  `parent is_active = any(active child)` - including the empty-active-set
  case (all children OFF -> parent 0 AND inactive, assumptions retained).
  Parent-level `default_active` is NOT an independent economic authority
  once decomposition exists and can never short-circuit it; the result is
  identical for parent items flagged active or inactive. Non-decomposed
  parents keep the Correction C behavior: `default_active=False` retains
  the stored amount/inflation/steps with `is_active=False`.
- **CAPEX breakdown/replacement**: EVERY active CAPEX sub-line under a
  canonical field - `C.NN.NN` detail rows AND user `C.NN.U###` rows -
  participates in the existing replacing-base fold (zero base + fold).
  Reconciliation is keyed by the CANONICAL CapexStructure field through
  `CAPEX_CATEGORY_TO_FIELD`, so the C.08/C.11 alias collapses into one
  `audit_legal` authority (summed exactly once).
- **OPEX replacement provenance**: decomposition rows carry the exact
  runtime fold vocabulary - `reference_seed=True`,
  `canonical_key=<canonical OpexItem name>`, `detail_code`, `scaling_mode`
  and template lineage - and the ORIGINAL persisted runtime row source
  (`persisted_source`: reference_seed | user_override | user). A
  `replaces_parent` item must set `reference_seed=True` and a
  `persisted_source` of reference_seed/user_override; any runtime-
  incompatible combination fails closed at the contract boundary. User
  `B.NN.U###` rows remain additive with `persisted_source=user`.
- **Percentage units**: template contingency drivers use canonical FINCO
  PERCENT POINTS (6.0 = 6%, strict 0..100); the core
  `OpexItem.percentage_of_opex` remains a FRACTION (0.06); conversion
  happens exactly once at each boundary. `PERCENT_OF_OPEX` requires an
  explicit `driver_value` (None fails closed; 0 is an explicit zero).
- **Typed contingency authority is primary**: when
  `ContingencyState.opex_pct`/`capex_pct` exists, C.13/B.13 become
  PERCENT authorities with that exact value regardless of the active
  flag; item `default_active` mirrors the active flag; the template
  envelope flags are serialized MIRRORS validated to equal the item
  applicability (divergence fails closed with
  COST_TEMPLATE_CONTINGENCY_AUTHORITY_DIVERGENT).
- **Applicability strictness**: `default_active`, the envelope contingency
  flags and all pure-state `is_active` fields accept only strict
  True/False; 0/1/strings/None fail closed. MISSING != ZERO != INACTIVE.
- **Scalar metadata immutability**: CAPEX scalar metadata is sanitized
  with the existing FINCO authority and snapshotted at item construction
  into an immutable MappingProxyType; external mutation cannot leak in,
  direct mutation raises, and the sanitizer re-validates at every
  consumption boundary.
- **Rescale reconciliation**: after row-level scaling/override decisions,
  canonical parents are RECOMPUTED from the final active child set (CAPEX
  by canonical field, OPEX by canonical key). Inactive rows keep their
  latent template-derived values updated with capacity but never enter
  the subtotal and never reactivate implicitly; overridden rows keep
  their project-owned amounts.

## 8. Persistence

Version-payload persistence (`cost_template` / `cost_template_version`
tables) is deliberately **deferred** to a later integration step: the
contract, deterministic serializer and roundtrip services are complete and
pure; the immutable JSON version payload produced by `serialize.py` is the
direct persistence artifact. This avoids touching central persistence
choke points in Workflow 03.

## 9. Non-goals

No second CAPEX/OPEX engine, no flattened universal CostItem, no revenue
runtime bridge, no ProjectInputs integration, no UI/API/XLSX, no Development
Economics, no new tax/depreciation formulas, no quarterly engine, no main
merge.
