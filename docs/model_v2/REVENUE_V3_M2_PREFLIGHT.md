# RC-2 / M2 Revenue V3 preflight

## Provenance and state

Verified live main: `5058c6b4935168241d6923676cb32955cb903185`.
Isolated branch: `feat/model-revenue-v3-advanced-products`.
The owner explicitly authorized candidate development in the three financial
paths below. This is NOT release approval: `ACTIVATION_ENABLED=False`, historical
pins and governance guards remain unchanged. Final commit/PR and exact-head CI
provenance are recorded in the Draft PR, not inferred from this document.

Live GitHub confirms #246 Revenue V2, #258 structured editor, #265 exact-period
curves/stress, #269 governance and #273 RC-1 are MERGED. Discovery found no
existing Revenue V3/M2 branch or overlapping open Model implementation PR.
M3/M4 overlap must be rechecked before publication; no ownership assumed.

## Existing / reuse / extend / unsupported matrix

| Surface | Status | Evidence / disposition |
| --- | --- | --- |
| PPA / Merchant / signed CfD | EXISTING / REUSE | `domain/revenue/multistream_runtime.py` explicitly supports only these types; preserve V1/V2 path and operations |
| Domain plan math | EXISTING / REUSE | `domain/revenue/plan.py`, `plan_engine.py`, `revenue_config.py`; physical allocation vs CfD overlay remains unchanged |
| Capacity / Ancillary | UNSUPPORTED / EXTEND | Reserved enum vocabulary cannot be instantiated as active streams; must not relabel MW as generation MWh |
| REC contract economics | UNSUPPORTED / EXTEND | No active REC type in the existing runtime; legacy certificate scalar is not an entitlement/ownership authority |
| Versioned typed input transport | EXISTING / REUSE | `finco_core/inputs/revenue_multistream.py`, `financial_engine/revenue_multistream.py`, existing serializers carry canonical JSON |
| Revenue composition | EXISTING / EXTEND | `finco_core/revenue/generation.py` currently composes energy, CfD, balancing and legacy certificate revenue; non-energy additions and REC collision checks required |
| Financial downstream | EXISTING / REUSE | Operating revenue feeds existing EBITDA/tax/CFADS/Senior/G2C/statements/returns; no second financial kernel |
| Contract persistence / scenarios | EXISTING / REUSE | `app/workbook/revenue_contracts_service.py` uses existing scalar/scenario stores, BEGIN EXCLUSIVE, composite CAS, atomic rollback and owner/protected rechecks |
| CSRF / Save route | EXISTING / REUSE | `/v2/workbook/revenue/contracts` validates signed CSRF before writer entry; no new mutation endpoint needed |
| Structured editor | EXISTING / EXTEND | Existing JS, CSS and `revenue_contracts.html`; add product-specific rows within this editor, not a second editor |
| Last Run / history evidence | EXISTING / REUSE | `app/api/project_runner.py` preserves canonical provenance notes as `revenue_multistream_audit`; no parallel ledger |
| Audit / XLSX dimensional display | PARTIAL / EXTEND | Existing stream rows assume `quantity_mwh` and `price_eur_mwh`; retain V1/V2 shape and add separately typed MW/certificate product evidence |
| Lagged settlement / FX / BESS dispatch / activation / penalties | UNSUPPORTED | Fail closed; no new working-capital, physical dispatch or hidden cash methodology |

## Exactly authorized protected candidate scope

1. `domain/revenue/multistream_runtime.py`: bounded V3 dispatch, leaving the
   V1/V2 parsing/evaluation path intact.
2. `domain/revenue/advanced_products.py` (new): immutable typed product contracts,
   explicit units/dated periods, ownership and overlap validation, product math,
   separate dimensional audit evidence and release-closed candidate boundary.
3. `finco_core/revenue/generation.py`: canonical composition of new components,
   no merchant balancing on non-energy revenue, and rejection of competing
   legacy certificate authority when REC is configured.

No proposed edits to `plan.py`, `plan_engine.py`, `financial_engine/**`, existing
input dataclasses/serializers, debt/tax/IRR kernels or financial tolerances.
Historical WF07 and Revenue V2 successor pins remain immutable. Candidate
blobs are not released merely because local tests pass; independent exact-content
review is required before a new release authorization.

The current runtime blob is `48465ce2a298fa1383a7eabcb921eb9fbe4610cb`.
The current generation blob is `e2502c6ba8557dd68d6bbcd44c1b55208f1942ed`.
`tests/test_wf07_revenue_governance.py` explicitly proves that further edits to
either path invalidate existing authorization. No self-pinning workaround.

## Candidate economic policy for bounded implementation review

These are implemented candidate constraints, not released economics.

- Solar/Wind only; explicit user-provided contract/source evidence is not an
  independently verified market eligibility or environmental certification claim.
- Capacity: explicit eligible MW and contracted capacity basis, derating and
  availability factors; EUR/kW/year or EUR/MW/year with explicit annual day-count
  convention and canonical period boundaries. Never infer MW from installed
  capacity, generation MWh or storage dispatch.
- Ancillary: explicit service/entitlement identity, committed MW, unit-specific
  price and exact operating-period settlement schedule. Availability-only
  contracted economics; dispatch/utilisation, activation energy, sharing, caps
  and penalties remain unsupported unless separately proved and authorized.
- REC: explicit retained, unbundled entitlement, certified eligible MWh and
  1-certificate-per-MWh price basis. Exact period quantities cannot exceed proven
  generated energy or the untransferred environmental attribute entitlement.
  PPA-bundled or already-transferred attributes cannot be resold.
- Duplicate IDs/source claims and overcommitted shared capacity/environmental
  entitlement fail closed. Separate energy sales, financial overlays and
  non-energy products are never combined into a physical allocation pool.
- SAME_PERIOD only; no implicit lag, currency conversion, extrapolation or
  undisclosed default. Explicit indexation or exact period prices, not both.
- Missing proof is unavailable/rejected, not estimated zero. All candidate
  activation remains closed pending independent financial approval.

## App-layer integration envelope after financial-path approval

Reuse the dedicated writer and existing ProjectInputSet/Run path. Expected
extensions are the Revenue workspace bridge, existing router context, existing
contract template/JS/CSS, dimensional institutional audit export and isolated
tests/docs. No new persistence tables, stores, Run CAS, history writer or security
inventory exceptions are proposed at this checkpoint.

Commercial stress must preserve non-energy contracts unchanged or explicitly
reject unsupported product shocks; it must not reinterpret them as PPA/CfD.
Legacy historical Runs retain their original shape and are not reconstructed
from current Working Copy.

## Required acceptance before publication

- Independent Decimal period math, exact dates and unit conversions.
- Allocation/entitlement conservation, REC/legacy collision and duplicate claims.
- Negative malformed/missing/nonfinite/sector/settlement/ownership tests.
- Complete inactive four-vertical and active V1/V2 parity.
- Actual controlled canonical Revenue/EBITDA/CFADS/financing/tax/returns runs.
- Save/reload/scenario/CAS/CSRF/Reference/owner isolation and immutable exports.
- Explicit real Chromium tests for this editor, plus mandatory browser CI.
- Candidate blob manifest and independent content review; no golden refresh,
  generic governance exemptions, activation or deployment.

Baseline focused pytest: **112 passed, 0 skipped, rc=0**, normal process exit
after 114.53 seconds on Python 3.12.10. Suites: WF07 runtime/governance/CSRF,
Revenue V2 advanced curves and structured editor. External JUnit:
`../m2-revenue-v3-baseline.xml`. Candidate acceptance and release boundary follow.

## Candidate implementation and evidence

- Version 3 delegates its energy book to the unchanged V2 authority. Three
  immutable product contracts produce separate dimensional evidence; existing
  net revenue composition alone feeds the canonical downstream financial run.
- Capacity: contracted eligible MW, explicit pool, derating/availability/performance,
  EUR/kW/year or EUR/MW/year, ACT/365 fixed, exact period-end settlement.
- Ancillary: availability-only EUR/MW/period with explicit service/pool authority.
  Mixed capacity/ancillary reuse of the same pool is rejected conservatively.
- REC: explicit certified MWh per operating period, retained unbundled rights
  for every physical energy sale, bounded by allocated backing energy. Legacy
  certificate enablement with REC fails closed at Save and Run; it is never cleared.
- All quantities, prices, factors, source/eligibility and ownership references are
  explicit. User declarations are not external verification. Uncontracted income,
  dispatch, storage, penalties/caps/sharing, lag/FX and differentiated tax treatment
  are unsupported. Products inherit the existing project tax policy, not a new tax engine.
- The SAME structured editor/form uses the existing CSRF, owner/protected checks,
  transaction, scenario store and composite CAS. Product controls are absent while
  activation is closed. Only isolated test fixtures enable candidate economics.
- Period dates are copied from backend authority on explicit user action; REC
  quantities are not autofilled. JavaScript serializes inputs, never calculates revenue.
- `Revenue_Products` exports persisted Last Run evidence with MW/certificate and
  price units. `Revenue_Streams` and historical V1/V2 evidence retain their shape.
  GET and export do not run the financial engine; later edits do not alter old Runs.

Local Windows Python 3.12.10 evidence (normal process exit):

| Acceptance | Result |
| --- | --- |
| M2 product/Decimal negatives, canonical single/two-Senior, workbook/scenario/export | 39 passed (37 full-ring plus 2 explicit legacy CO2 preservation checks) |
| Explicit real Chromium Solar/Wind product entry, Save/reload, scenario first Save, two Runs | 2 passed |
| Existing unchanged Revenue runtime/workspace/CSRF/editor/curves regression | 107 passed |
| Public repository safety scan, compilation, diff hygiene | PASS |
| Maximum actual Decimal product revenue residual, every operating period | 1.005055102704e-14 kEUR, Solar and Wind |
| Isolated exact-base full G2C + financial statements comparison | 8/8 bit-exact |

Full canonical comparison used separate detached base and candidate executions,
identical factory inputs and contracts, **all** G2C/result/statement dataclass
fields. Floats are encoded using `float.hex()` (including legitimate infinite
coverage ratios); no rounding, tolerances, dropped fields or golden refresh.

| Case | Identical baseline/candidate SHA-256 |
| --- | --- |
| Inactive Solar | 4b59cb9c8f947e0e63f321264528f14a58c0992c8c8376fec06b0d2fe66c0e0d |
| Inactive Wind | 38f57af52f12209da2d9ec9c3884456ac80a03f88eae090124141be1c2d550a5 |
| Inactive Data Center | 583ea08029f926715fbfe19a0da8ca6cecd18af82e2b7d0cbe9a2bea3fce8733 |
| Inactive EV | 292dad6dfb57547aadc784773f5b6ea4fe7b9f13ee4845fac4fd252c1fca7488 |
| V1 Solar | 3a39eb674d924f66da99477f49b9f4a0d37f31037c5e68f415789d45efacc961 |
| V1 Wind | 8db3303c70f741ef8bf04d5c54945df13af6708d9c288d0def14f69d36633345 |
| V2 Solar | b28e0e60f04dc51bd31d8fb27b4d7f2a2d7700616d5a1c85d256f47c90d9c025 |
| V2 Wind | 9427bec2bae263fb9022a86e03e6dab5ffdde44fcb1411f846cd98d10e9888ba |

Synthetic canonical results (horizon totals kEUR; returns as fractions):

| Case | Revenue V2 -> V3 | Senior V2 -> V3 | Sponsor XIRR V2 -> V3 |
| --- | --- | --- | --- |
| Solar, sized Senior | 216068.57295227252 -> 216916.07692680438 | 28059.874817497257 -> 28069.458876943376 | .26854931104515 -> .26938661936659897 |
| Wind, sized Senior | 337012.3204076712 -> 337937.4039131678 | 37597.4670728915 -> 37606.94243398858 | .26362522001700517 -> .26415951542567956 |
| Solar, two contractual Senior | same revenue pair | 3300 -> 3300 | .18895981319174504 -> .18963901014550208 |
| Wind, two contractual Senior | same revenue pair | 4300 -> 4300 | .18181961132132754 -> .1822365790058728 |

All four candidate executions have Integrity PASS. Actual tax/CFADS/Project XIRR
change; contractual facility schedules remain identical, while their actual Base
DSCR changes. No duplicate financing/tax/return engine or calibration.

External evidence: `../m2-focused.xml`, `../m2-browser.xml`,
`../m2-parity-base.json`, `../m2-parity-candidate.json`,
`../m2_revenue_v3_evidence/{solar,wind}-{desktop,narrow}.png`.
Screenshots/SQLite/generated workbooks are not committed.

## Independent financial release gate

Candidate Git blob manifest (NOT release pins):

| Approved candidate path | Candidate Git blob |
| --- | --- |
| `domain/revenue/multistream_runtime.py` | 83beda4eb296b02baf2ebd6659fec243ab196206 |
| `domain/revenue/advanced_products.py` | d4ab263422aac5571e52bee4925fe36588e853cc |
| `finco_core/revenue/generation.py` | 35670dc7b5ab4ce01177f9df817a4776c10569ab |

The three candidate blobs require independent exact-content review. No financial
release map is added here; existing HEAD-content guards will reject unreviewed
successors after commit. A pre-commit guard result reads the old Git HEAD and is
NOT candidate financial authorization. Exact-head CI outcomes belong in the PR.
Do not repair that expected release gate by repinning, changing baselines or
weakening tests. No production enablement, deployment, self-approval or merge.

M3 Draft #274 exists on the same base. Only shared file overlap is
`app/v2/router.py`: M3 registers its isolated sensitivity router, M2 adds Revenue
editor context. No shared financial edits; normal RC integration must preserve both.
No M4 implementation was found at publication preflight.
