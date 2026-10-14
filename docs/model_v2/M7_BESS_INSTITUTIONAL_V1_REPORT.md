# M7 standalone BESS V1: release-closed development candidate

## Disposition and provenance

This is an executable physical/merchant/lifecycle candidate, **not** an enabled
financial BESS vertical. Canonical financial promotion is BLOCKED. No financial
Save, scenario configuration persistence, Run, historical export or bankability
claim is made for this candidate.

- Branch: `feat/model-m7-bess-institutional-v1`.
- Verified RC-2 main/base: `6fc77de98bc0562fb51efdbf96e1803a29b5b148`.
- PR #278 merged at `2026-10-14T04:28:13Z`; source HEAD
  `2155a76bfff4acc3a4e15f7cf35012933ce1a10c` is an ancestor of the base.
- `RC2_INTEGRATION_MANIFEST.md` and the corrected M2/M3/M4/R3 code are present.
- Publication preflight found no competing Storage/BESS/Hybrid PR. Adjacent
  Diagnostics #281, valuation #282 and Radar #279/#280 remain separate owners.
- No changes to those workstreams, the 30 Model Quality identities, deployment,
  financial goldens, numerical tolerances or historical authorization maps.
- Exact candidate commit/tree and Draft URL are supplied in the PR handoff;
  this document does not manufacture self-referential commit identities.

## Authority inventory

| Existing path | Classification and observed boundary |
| --- | --- |
| `finco_core/inputs/bess.py`, `domain/revenue/bess.py` | LEGACY / UNSUPPORTED native model: annual cycles/spread and augmentation-cost heuristic, not chronological SoC or a replacement-asset authority. Unchanged. |
| `app/services/bess_service.py` | LEGACY analytics, not canonical finance evidence. Unchanged. |
| `app/project_factories.py` | EXISTING Storage reference: battery, initial CAPEX/OPEX. Saved COD is inconsistent with its derived construction calendar; a locally constructed soft CAPEX item is not wired into its returned structure. Neither issue is silently corrected here. |
| `app/services/project_library_service.py`, `app/v2/router.py` | REUSE fail-closed #63/#64 Storage handling. Normal clone/seed/Run guards remain; the only existing-code change registers a default-closed isolated review router. |
| `app/workbook/input_set.py`, `registry.py`, `workbook_identity.py`, `update_service.py` | REUSE owner/scenario/composite authority. Native BESS configuration Save serialization is MISSING and not invented as a persisted sidecar. |
| `app/persistence/run_history_repository.py`, `scenarios_repository.py` | REUSE immutable evidence/scenario authority. No writes or schema changes. |
| `finco_core/engine/period_engine.py` | REUSE canonical full financial axis, including construction rows, partial periods and existing COD-inclusive accrual metadata. |
| `financial_engine/inputs.py`, `adapters/project_inputs.py`, `orchestrator.py` | MISSING native operating seam: `TechnicalInput` conversion drops legacy BESS assumptions; operating assembly is not a native hourly storage schedule provider. |
| `financial_engine/book_basis.py` | MISSING dated post-COD commissioning/disposal and asset-basis integration for paid augmentation. Static/construction basis is not interchangeable with operating replacement. |
| `app/services/production_financial_authority.py` | REUSE classifier: current Storage reference is not promoted and has a clean-tax-policy readiness blocker. |
| `financial_engine/financial_statements/`, `senior_debt/`, tax and return authorities | REUSE future downstream finance only after reviewed native input/accounting integration. No alternative waterfall, tax, debt or IRR implemented. |
| `domain/revenue/advanced_products.py` | RELEASE-CLOSED Revenue V3 remains false; no BESS Capacity/Ancillary activation. |
| `app/workbook/junior_debt_config.py` | RELEASE-CLOSED Junior remains false. |

## Implemented capability matrix

| Capability | Status |
| --- | --- |
| Versioned standalone grid BESS contract | IMPLEMENTED candidate, immutable parsed dataclasses, strict keys and provenance |
| Power, installed/usable energy, duration, SoC, efficiencies, auxiliary grid draw | IMPLEMENTED candidate; MW/MWh and EUR/MWh/kEUR explicit |
| Hourly user chronology / fixed daily UTC plan | IMPLEMENTED candidate; no price-aware optimizer or hindsight optimization |
| Purchase/sale/import/export cost separation | IMPLEMENTED candidate interval evidence, not financial posting |
| Calendar/cycle degradation, useful life, paid augmentation/replacement | IMPLEMENTED physical/cost evidence; tax/book/funding policy unresolved |
| Full canonical financial-period aggregation | IMPLEMENTED proposals only, requires exact full horizon and canonical axis |
| Existing CAPEX/OPEX inspection | READ-ONLY source inventory, not new cost persistence or financial calculation |
| BESS operating-review form | IMPLEMENTED stateless candidate; default `CANDIDATE_UI_ENABLED=False` returns 404 |
| Owner/protected/CSRF/composite-context isolation | IMPLEMENTED/tested for ephemeral validation only |
| Canonical financial Run, Save, scenario input bridge, STALE/CURRENT, immutable BESS history | BLOCKED; existing financial Storage guards retained |
| Hybrid, optimizer, quarter-hour/DST, signed negative market prices, decommissioning, Capacity/Ancillary | UNSUPPORTED, no financial backfill |

## Physical and commercial policy

One-hour UTC intervals are `[start,end)`. Missing/duplicate/reordered hours,
offsets, DST ambiguity, invalid dimensions, nonfinite/negative numbers,
simultaneous charge/discharge, power/grid/SoC breaches and terminal mismatch
fail closed. Prices must explicitly use `EUR_PER_MWH`; changing unit labels is
rejected, not silently scaled. Numeric prices alone cannot prove their source
unit: source provenance still needs independent review.

For AC charging C, delivered discharge D, grid auxiliary A and efficiencies:

```text
E_close = E_open + C * eta_charge - D / eta_discharge
charge_loss = C - C * eta_charge
discharge_loss = D / eta_discharge - D
grid_import = C + A; grid_export = D
EFC = (C * eta_charge + D / eta_discharge) / (2 * nominal usable MWh)
cohort SoH = 1 - calendar_loss * age_hours / 8760 - cycle_loss * cohort_EFC
merchant contribution = gross sale - charging purchase - auxiliary purchase
                        - grid import charge - grid export charge
```

RTE must equal the product of efficiencies; usable MWh / discharge MW must
match declared duration. Calendar degradation uses ACT/365 elapsed hours,
including leap years. Physical life is calendar-year commissioning plus life.
Cycle throughput is allocated proportionally over the declared aggregate DC
pool. This is not a cell-specific thermal, network or heterogeneous-aging model.

Outages suspend only the declared fixed plan under its explicit policy; an
explicit hourly dispatch during an unavailable interval is rejected. Neither
policy repairs a subsequent invalid SoC. Auxiliary grid draw remains explicit.

Augmentation creates a paid, empty capacity cohort; it does not create energy.
Replacement requires zero inventory and a positive explicit cost. Positive
minimum-SoC augmentation has no commissioning-energy authority and is rejected.
Lifecycle CAPEX is a separate dated evidence vector, never netted into merchant
receipts or expenses. Book/tax policy is explicitly `UNRESOLVED`.

The full existing FINCO axis is validated before settlement proposals. Actual
UTC physical hours are distinct from `canonical_accrual_days`: the first
COD-inclusive financial period can have span-days + 1 accrual day. That extra
accrual day does not manufacture 24 hours of generation. Candidate amounts
aggregate to actual period end dates without padding or changing day counts.

## Independent numerical evidence

Original synthetic 48-hour plan: charge 1 MW at UTC 02, discharge 0.81 MW at
UTC 20, efficiencies 0.9 each, auxiliary 0.01 MW, buy 40 and sell 100 EUR/MWh,
import charge 2 and export charge 1 EUR/MWh.

| Evidence | Value |
| --- | ---: |
| Purchased import | 2.48 MWh |
| Delivered export | 1.62 MWh |
| Gross sale | 0.162 kEUR |
| Charging purchase | 0.080 kEUR |
| Auxiliary purchase | 0.0192 kEUR |
| Import charges | 0.00496 kEUR |
| Export charges | 0.00162 kEUR |
| Net merchant contribution | 0.05622 kEUR |
| DC throughput / EFC | 3.6 MWh / 0.9 |
| Maximum actual energy residual | 0 MWh |
| Initial / terminal inventory | 0 / 0 MWh |

An independent exact rational `Fraction` oracle checks every hourly energy and
commercial component against Decimal runtime results. Zero volume, leap-year
8784 hours, explicit-vs-daily equivalence, degradation and paid lifecycle events
are covered. Changing the UI sale price to 120 gives 0.08862 kEUR contribution;
adding 100 kEUR augmentation leaves it separate from merchant contribution.
No existing financial golden or tolerance is changed.

## Focused validation and limits

- `test_m7_bess_physics.py`: 40 PASS.
- `test_m7_bess_financial_boundary.py`: 7 PASS.
- `test_m7_bess_candidate_workspace.py`: 14 PASS, including missing/forged/expired
  signed CSRF, owner/reference, stale identity, concurrent edit and actual
  scenario selection; all financial/persistence evidence remains unchanged.
- Existing `test_storage_working_copy_contract.py`: 34 PASS after router hookup.
- Combined numerical/boundary/workspace/Storage: **95 PASS**, rc=0, normal exit.
- `test_m7_bess_candidate_browser.py`: **2 PASS**, real Chromium at light/1440
  and dark/390, horizontal scroll/fit, actual price/event inputs, server evidence,
  reopen loses unsaved assumptions, protected scope, zero JS errors, server exit.
- Screenshots captured externally: `bess-light-1440.png`, `bess-dark-390.png`.
  Optional `M7_SCREENSHOT_DIR` reruns this evidence; binaries are not committed.
- Existing Trust inventory test: **1 FAIL**, precisely because the new signed
  CSRF validator is not in its exact approved module inventory. The existing
  assertion, Trust registry and release maps are unchanged. It requires a
  separately authorized exact-content inventory alignment, not a broad exemption.
- Full local public pytest and broad four-vertical parity campaign deliberately
  not run. Source ZERO DIFF is not represented as new full financial parity.
- Full source safety, compilation and final diff results are recorded in the
  publication handoff. Exact-head CI is a development checkpoint, not released
  acceptance; complete green CI is required before future integration/merge.

## Candidate protected-domain manifest (NOT release pins)

These are Git blob identities of original candidate source, submitted for
independent financial/architectural review. No self-authorization map is added.

| Path | Candidate Git blob |
| --- | --- |
| `domain/bess/__init__.py` | `1905167cfb38bebb69f5f8b24f4100adf2b71f3d` |
| `domain/bess/contracts.py` | `1143dced2b27e3b7ed16754ccd3a17f6982d9f98` |
| `domain/bess/dispatch.py` | `ff2a9d2be76c2b1be308c596c42e32fe4276a9bc` |
| `domain/bess/settlement.py` | `e10829563e359f1766c6d8f98542e43107dac0dd` |
| `domain/bess/synthetic.py` | `427ad4589f9726c07e7c3723c2ff7ceed68c38ae` |

Existing `financial_engine/**`, `finco_core/**`, legacy domain modules,
project factories, tax/debt/IRR authorities, persistence/schema, deployment,
export/report implementations and historical governance pins have ZERO DIFF.
Domain additions above are candidate calculations, not existing released finance.

## Required next authorization and integration decisions

1. Independently review native battery policy and candidate blobs. Their pure
   execution is not authorization for production financial promotion.
2. Approve the smallest typed native operating successor: likely
   `financial_engine/inputs.py`, `financial_engine/adapters/project_inputs.py`,
   `financial_engine/orchestrator.py` and relevant core input/revenue authority.
   Specify gross sales vs charging/aux/grid OPEX, lender sizing and cash-tax
   ownership before implementation. Those files are unchanged here.
3. Define dated post-COD asset commissioning, disposal, tax/book basis and
   funding through existing `financial_engine/book_basis.py`, statement and
   return authorities. Do not disguise replacements as construction assets,
   recurring OPEX or negative revenue. Preserve unlevered financing independence.
4. Review Storage reference construction/COD, real hard/soft CAPEX and tax
   readiness independently, without blanket factory or tax changes.
5. Add reviewed ProjectInputSet/registry/adapter serialization and scenario CAS
   only after native authority is available. Then prove full immutable Run,
   stale/current, history and failure-atomicity lifecycle before enabling clone.
6. Authorize narrow new CSRF inventory/Trust alignment and exact-content
   successor rules for new candidate paths. Existing guards remain fail closed.

No toggle alone can release this handoff: `require_canonical_financial_run`
unconditionally rejects even a caller-forged ready object. Default candidate UI,
M7 financial activation, Revenue V3 and Junior activation all remain false.

**M7 BLOCKED - native canonical operating input, charging expense and post-COD
asset/funding authorities are not released.** One coherent Draft candidate is
provided for review; no merge, deployment, staging, exports or fake runnable BESS.
