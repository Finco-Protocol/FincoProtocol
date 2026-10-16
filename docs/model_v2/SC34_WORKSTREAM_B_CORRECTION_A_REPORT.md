# Safe Core V3.4 Workstream B - Correction A

Existing Draft PR: #293. Branch: `feat/model-sc34-input-workflow-reliability`.
Base and live main at preflight: `540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`.
Starting HEAD: `dcd7d21368d669fbc8ef054f20bf4c92f556e60e` (5 ahead / 0 behind).

**Disposition: BLOCKED - PPA-01 FINANCIAL AUTHORITY APPROVAL REQUIRED. NO MERGE.**

This report records functional corrections, not independent financial release approval. Final exact HEAD and exact-head CI execution IDs belong to the PR handoff after publication. No other workstream is merged here; PR #289 remains separate and open.

## A1 - protected financial successor

The unchanged WF07 governance suite reproduces five failures because the PPA-01 runtime blob is not a released authority. See `PPA01_FINANCIAL_AUTHORITY_SUCCESSOR_PROPOSAL.md` for exact tests, historical hashes and proposed additive procedure. No historical map, protected-file guard, CI inventory, release flag or workflow is changed.

Proposed one-path candidate: `domain/revenue/multistream_runtime.py`, Git blob `e5e26082d670baa7adc91da4848959ab032ce2ad`. It supersedes the starting PR candidate `1cfdad8863041ba47e04f4f57b96e6c7ff7fcaaa` only as a candidate, not an approval. Current main's reviewed blob remains `83beda4eb296b02baf2ebd6659fec243ab196206`.

Independent acceptance must cover both exact bytes and the pricing-year/base convention. No additive authority map or new successor negative tests are released before that acceptance. Existing negative protections remain unchanged; their failures are not relabelled PASS.

## A2 - six browser regressions

All six original tests fail on BOTH exact clean main and exact starting PR HEAD at the hidden compatibility `#tab-revenue` button. This is a pre-existing navigation mismatch following #288, not proof that Revenue is unavailable to users. Screenshots and Playwright traces were captured against both immutable checkouts with original assertions.

| Existing case | Main / starting PR | Corrected |
|---|---|---|
| Scheduled PPA, Solar | hidden-tab timeout / hidden-tab timeout | PASS |
| Scheduled PPA, Wind | hidden-tab timeout / hidden-tab timeout | PASS |
| Scheduled Merchant, Solar | hidden-tab timeout / hidden-tab timeout | PASS |
| Scheduled Merchant, Wind | hidden-tab timeout / hidden-tab timeout | PASS |
| Fixed + annual-indexed PPA + Merchant, Solar | hidden-tab timeout / hidden-tab timeout | PASS |
| Fixed + annual-indexed PPA + Merchant, Wind | hidden-tab timeout / hidden-tab timeout | PASS |

Tests now reuse `tests.model_workspace_navigation.activate_destination`: visible Inputs area, visible Revenue destination, actual panel. No tab is force-shown or clicked through JavaScript. PPA-01 and SC-34 journey tests use the same visible navigation where corrected.

After that first blocker was removed, four scheduled tests incorrectly waited for a visible JSON textarea inside intentionally collapsed Technical details; the other two read empty pre-response JSON immediately after Save. They now wait for the real POST response and the `Saved Working Copy` state, then read the attached serialized field. All original price, index, curve, residual Merchant, reload and mobile-scroll assertions remain. An SC-08 journey also referenced a toolbar marker absent after the existing OOB response; it now checks the persistent `hybrid-last-run` text without dropping history/refusal/recovery assertions.

Final six-case Chromium run: **6 passed**, normal rc=0. Screenshots are generated under `reports/revenue_v2_advanced/` (ignored binary evidence), including Solar/Wind scheduled PPA/Merchant desktop/mobile and fixed/indexed/Merchant desktop. Full before/after traces are retained privately; no session data or binary artifacts are committed.

## A3 - pricing-year context

Before correction an active series returned base price 60.0 without a year while actual operating year 3 resolved to 63.6. `plan_at` now requires a positive integer canonical year whenever an indexed PPA is active. Missing, boolean, fractional, string, zero or negative context fails closed. A valid but uncovered year also fails closed. No fallback rate or interpolation is introduced.

Parser validation calls `validate_structure_at`, which checks dates/activity/allocation/overlays and returns no financial plan. This intentionally works before the full operating axis exists. `validate_axis` separately checks exact period boundaries and supplied year coverage. Canonical evaluation passes the period's actual `year_index`.

The key is the existing canonical model operating-year index, including partial initial periods, not calendar year or contract anniversary. First supplied observation is the explicit base. Late-starting contracts can retain an earlier base or explicitly begin the base at their first priced year. OBSERVED/FORECAST are supplied evidence labels, not an automated verification of a provider feed. The independent financial decision remains open.

## A4 - confirmed consistency defects

- Blank canonical tariff keys were labelled saved even when a legacy/template value actually applied. Numeric presence now distinguishes blank/absent from explicitly entered zero.
- Selected scenario tariffs, including zero, could display the base tariff as the next Run input. The display now reuses the existing admitted `bind_scenario_tariff` authority. Invalid values are unavailable, not replaced by a base tariff; other owners/projects are not read.
- Balancing input zero remains visible as an entered zero. The Pricing Basis reports the actual effective template fallback (for the controlled Wind case, 8 EUR/MWh), and the provenance explicitly discloses the zero-to-template behavior. No balancing/revenue equation changes.
- An ignored/zero-row project-record rename UPDATE could commit the Working Copy while leaving the record name unchanged. The existing mirror now requires exactly one affected owned row and raises the existing conflict exception otherwise. The encompassing transaction rolls back; no schema or new persistence authority is introduced.

FK-enabled tests cover ignored/aborted updates, missing or differently owned project records, stale CAS, the scalar and atomic-batch paths, unrelated field writes and immutable historical rows. No foreign keys are disabled.

## Numerical and local acceptance

| Scope | Result |
|---|---|
| PPA-01 + existing advanced-curve numerical checks | 73 passed |
| PPA-01 + legacy WF07 numerical contracts | 117 passed |
| Scoped pricing, Save/scenario/Run/history, effective inputs, project identity, Run refusal and atomic batch | 217 passed |
| Existing six advanced Revenue V2 Chromium workflows | 6 passed |
| PPA-01 / draft retention / dates / SC-34 journeys, final visible navigation | 26 passed |

Counts overlap and are not a full-suite total. Later narrowly added A4 cases are rerun separately and recorded in the final handoff. No skips/xfails or financial tolerances/goldens were added to obtain these results.

Twenty cases execute complete canonical legacy revenue schedules against the immutable pre-PPA-01 runtime: Solar/Wind, normal/non-calendar COD, fixed/annual-indexed/scheduled PPA, scheduled Merchant and signed CfD. Results compare exactly, with no tolerance or golden refresh. Existing Decimal price, allocated quantity, floor/cap and conservation assertions remain. Save/Run tests protect previous Last Run and history after invalid requests.

Browser acceptance uses real Chromium and disposable local projects, not staging. The 26 cases comprise 10 PPA-01, 3 rejected-draft, 8 date and 5 integrated-journey cases. Public Safety's optional-dependency skip behavior and the mandatory six-role browser CI are unchanged; six-role CI success is not substituted for these specific local browser results.

## Frozen boundaries and CI

ZERO additional Correction A changes in `financial_engine/`, `finco_core/`, unrelated domain files, activation flags, historical financial maps, workflow definitions, tolerances or goldens. Only the already-candidate Revenue runtime is modified in the protected domain scope. Existing PPA-01 frontend economics and SC-04 through SC-10 functionality are preserved.

At starting HEAD the six-role Browser, Governance Full History, Security, Compile, Atomic Batch, Q4 and source-safety job were SUCCESS; full Public Safety was still running. That is not a complete green result. Five local WF07 content-authority failures were independently reproduced. Fresh exact-head CI after the correction must be reported honestly; no workflow is weakened and no approval is inferred from historical-governance success.

The PR remains OPEN/DRAFT. There is no merge, deployment, rebase, squash, force push, Junior/V3 activation or self-approval. The RC coordinator owns later accepted-workstream integration. Until precise independent successor acceptance exists, the required final classification is **CORRECTION A BLOCKED - NO MERGE**.
