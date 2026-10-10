# WF-07: Revenue V2 multi-stream authority

## Provenance and review scope

- Isolated branch: `feat/model-revenue-v2-multistream`.
- Implementation base: `0da9e50dc03431594fb820835662299623486fa1`.
- PR #239 is merged; the WF-04 numeric correction (#241) is included in this base.
- This is a consolidated Draft review checkpoint, not a deployment or approval.
- Exact candidate HEAD, PR URL and five workflow conclusions are recorded in the PR description after CI completes; this report does not self-reference its own commit SHA.

## Independent authority map

| Boundary | Existing authority | WF-07 integration |
| --- | --- | --- |
| Production | `finco_core/revenue/generation.py:full_generation_schedule` | Actual canonical production, unchanged |
| Allocation | `domain/revenue/plan.py`, `plan_engine.py` | Existing physical allocation and overlay validation |
| Price/index | `domain/revenue/revenue_config.py` | Existing PPA and Merchant price functions, operating-year clock |
| CfD | `CfDParams.cfd_payment_at_year` | Two-way strike minus referenced raw Merchant price, signed settlement only |
| Dates | Canonical operating period engine | Exact period boundaries; end exclusive; no invented proration |
| Working inputs | ProjectInputSet / registry / existing workspace store | Canonical JSON scalar and composite CAS |
| Scenarios | Existing scenario overrides and selection | Whole-book replacement; inherit removes the override |
| Run | Existing production authority / final Run CAS | Opt-in typed revenue carried into one canonical engine |
| History / export | Persisted Last Run inputs and immutable summary | Run-bound book validation and persisted stream audit; zero export engine calls |

The old aggregate revenue helpers for Capacity/Ancillary are not adequate production authorities: they do not establish a complete kEUR/quantity/activation contract. REC lacks a typed entitlement/ownership and volume-conservation boundary. Their presence in source code is not evidence of executable production support.

## Implemented capability matrix

| Stream | Active | Quantity / price authority | Limitations |
| --- | --- | --- | --- |
| Fixed PPA | YES | Explicit generation fraction; EUR/MWh | Solar/Wind, exact dated operating periods |
| Indexed PPA | YES | Same allocation; existing annual index formula | Operating/model year 1 price basis, not contract anniversary |
| Merchant | YES | Explicit fraction or one residual; price, index and capture | No invented curve or missing-volume backfill |
| CfD | YES | Explicit share of referenced Merchant generation; fixed strike | Two-way; raw market reference before capture; no indexed strike |
| Capacity availability | NO | Missing capacity, availability and settlement contract | Rejected, not exposed as working control |
| Ancillary services | NO | Missing service-unit, activation and settlement authority | Rejected; no guessed dispatch |
| REC / green certificates | NO | Missing entitlement, ownership and conservation contract | Rejected; legacy CO2/certificate input is not REC support |

Only SAME_PERIOD settlement is supported. Lagged receivables require an explicit working-capital authority and are rejected. No new tax policy or working-capital methodology is introduced. Existing tax receives changed canonical EBITDA and financing interest through its normal path.

## Typed payload and validation

Root keys: `version` (strict integer 1), `technology` (`solar`/`wind`), `indexation_basis` (`OPERATING_YEAR`), `streams` (1-24).

Each stream requires `id`, `type`, `start_date`, `end_date`, `volume_share`, `price_eur_mwh`, `indexation_rate`, `settlement`, `source_ref`. Only Merchant may have `volume_share=null` (residual), or `capture_rate`; only CfD has `reference_stream_id` (required). Rates/shares are fractions, not displayed percentages. Unknown and duplicate JSON keys, non-finite numbers, negative prices/rates, fractions above one, duplicate identities, invalid references, excess allocation/overlay coverage, mismatched technology and partial periods fail closed.

`source_ref` is an explicit user-declared evidence reference, not proof that FINCO verified a signed contract. Stream identity is stable in the book; project and scenario ownership remain external canonical authorities, never browser-supplied grants.

Empty workspace payload opts out to legacy pricing. An explicitly present malformed typed serialized authority cannot silently fall back. Opt-in subclasses preserve the exact legacy class, serialized shape and financial fingerprint when inactive.

## Save / scenario / Run / export

The dedicated Revenue contract editor is a bounded JSON editor, not a cosmetic Add Revenue control. It validates real economics and saves under BEGIN EXCLUSIVE, rechecking owner/project/protected state, selected scenario and composite identity. It uses existing stores without schema migration. Base changes the draft; selected non-Base changes only that scenario's overrides. Duplicate/copy preserves its payload; restore removes it. Stale selection/hash and cross-owner writes are rejected without mutation.

Legacy PPA/Merchant editors are hidden while contracts are active and their direct writes are rejected, including scenario-only activation. Scalar tariff Goal Seek and legacy price sensitivity fail closed instead of pretending to change explicit contracts. Lender yield sizing still uses the same contract book with the canonical Bank production case; a competing legacy Bank price override is explicitly unsupported, not silently ignored.

Save refreshes composite controls and STALE surfaces. Scenario lifecycle refreshes ownership/book presentation. Run refreshes persisted contract audit through the existing coherent post-run OOB response; no extra engine call. Last Run remains immutable while new contracts are edited. Export validates the run-bound book and adds `Revenue_Streams` only for active persisted evidence. CfD settlement is separate from physical sale. Period totals repeat per contract and must not be summed as row totals. Capture and declared provenance are exported.

## Financial acceptance

Unmodified generic factory inputs, compared to the synthetic opt-in book: 60% PPA at 95 EUR/MWh, residual Merchant at 90 EUR/MWh, 40% fixed-strike two-way CfD at 100 EUR/MWh; zero contract index; original balancing/certificate policy retained. No target fitting.

| Metric | Solar legacy | Solar contracts | Wind legacy | Wind contracts |
| --- | ---: | ---: | ---: | ---: |
| Revenue kEUR | 159924.624683859 | 216068.572952273 | 282589.938836623 | 337012.320407671 |
| EBITDA kEUR | 147814.535446563 | 203958.483714977 | 263244.121585011 | 317666.503156059 |
| CFADS kEUR | 123782.829968381 | 164904.529572664 | 214323.653648909 | 254185.863086792 |
| Cash tax kEUR | 24031.705478183 | 39053.954142313 | 48920.467936102 | 63480.640069267 |
| Senior kEUR | 26983.331676477 | 28059.874817497 | 36505.157959484 | 37597.467072892 |
| Senior service kEUR | 36312.501847246 | 33066.386193302 | 47493.469216539 | 44377.423027410 |
| Minimum Base DSCR | 1.248648416040 | 1.261607034015 | 1.279992436419 | 1.295146748295 |
| Total sponsor XIRR | 0.166102003087 | 0.268549311045 | 0.187118310623 | 0.263625220017 |
| Binding constraint | GEARING | GEARING | GEARING | GEARING |
| Integrity | PASS | PASS | PASS | PASS |

Financing changes flow from existing Project Uses/construction interest and debt-sizing feedback, not a new Senior formula. Separate F3 two-Senior Solar/Wind tests prove aggregated principal equals funded Senior, final repayment, canonical EBITDA and Integrity PASS with active contracts. Independent Decimal checks cover positive/negative CfD settlement, allocation and capture/reference separation. Date tests cover expiry/delayed start with no hidden Merchant backfill.

## Inactive legacy parity

`tools/wf07_legacy_parity.py` executed in independent base and candidate worktrees. It recursively compares the entire production result (inputs, financial results, statements and audit), encoding every float with `float.hex`, not rounded KPI comparisons. Four full trees match exactly:

| Vertical | Matching SHA-256 |
| --- | --- |
| Solar | `3ce12efa7a2bd82a5f45e848afe53c493d58cf72084325c1314cd2bae8b4de5d` |
| Wind | `2e33912a2f0169ade9dcfc277196f8b6f44d69cd469e01f0f853967ac05be578` |
| Data Center | `bbd04a0afa805b4bd00f756a8da0dee2abd4aecbf7342f6dfe80598c96101f69` |
| EV | `98286b17176ba2cc6c4a4b1dec2adba4a499f9d691cb72340ec56b01f57f4104` |

No golden, baseline, calibration, financial tolerance, tax, debt, reserve, depreciation, distribution or project-factory change.

## Local tests and browser evidence

- Financial/workspace/WF-04/F3/scenario tariff focused regression ring: **137 passed**, normal exit.
- Final WF-07 financial/workspace/authenticated browser ring: **66 passed**, normal exit (54 financial, 10 workspace, 2 browser).
- Browser covers real Save/reload, scenario creation/ownership, first-click Run, CURRENT, persisted audit, desktop and 390px narrow layout, with zero page errors.
- Screenshots: `reports/wf07_validation/solar-contracts-desktop.png`, `solar-contracts-narrow.png`, `wind-contracts-desktop.png`, `wind-contracts-narrow.png`; taken and visually inspected, ignored binary evidence is not committed.
- Generated base/candidate whole-tree evidence: `reports/wf07_validation/legacy_base.json`, `legacy_candidate.json`; ignored, not replacement goldens.
- Focused governance, full pytest and exact-head five workflow results are added to the PR delivery after execution. A focused pass alone is not full acceptance.

## Governance and remaining review

Seven exact path/Git-blob authorities are added in `tests/model_v2_governance.py`: the clean input adapter, orchestrator, new clean opt-in input class, new core opt-in revenue class, core serialization, core generation and new dated domain wrapper. Every one has a negative tamper test; all other frozen files remain blocked. Historical pins and assertions remain intact. No wildcard financial-engine exemption or workflow relaxation.

No solver, schema, execution-worker, factory or unrelated module redesign. Upstream follow-ups needed: explicit capacity/availability settlement; ancillary units/activation; REC ownership/conservation; lagged settlement/working capital; contract-level price curves and Bank price stress; a structured editor replacing JSON only after this economic authority is independently accepted.

Disposition: DRAFT, independent financial review and exact-head CI required. Three supported stream families, not six.

## Correction A: write security and main integration

Reviewed starting head: `2fe5ec8ad59d0929a7c27fc6e889a8cbbfb0f0f9`. Current main `5a183b8a9d723ed651e93bef2cc8cd17c8269937` was integrated by normal merge `eb874644af9efaccdc792ae72233b97e2b54e8ac`, with no conflicts. This includes #242 Statements/Debt; #244 Trust and #245 Hybrid Inputs were still OPEN at integration, not silently treated as merged. No rebase, squash, force push or deployment.

The actual contract-editing form now receives a signed token from `app.auth.generate_csrf_token` through `revenue_contracts_csrf_token`. POST authenticates first, then validates with `app.auth.validate_csrf_token` before project resolution or the atomic writer. Missing, forged and expired tokens return 403 without workspace/scenario mutation. A valid token is not an owner or protected-reference authorization grant. The canonical writer and all economic contracts are unchanged.

`tests/test_wf07_revenue_csrf.py` covers missing/forged/expired/valid tokens, anonymous and cross-owner access, real protected-reference flags, form/reload/HTMX issuance, and zero financial execution on GET/Save. Expiry uses a genuinely old signed timestamp, not a mocked validation result. Solar/Wind browser forms submit their real token through HTMX.

The original exact-head Public Safety run `38077948385` finished with **19 failed, 9460 passed, 56 skipped**. Pytest and interpreter returned rc=1 normally; evidence upload succeeded. These are not the base's earlier shutdown timeout. One context fixture omitted the workspace's scenario fields; it now uses the real workspace. One dense-layout registry test omitted the two additive WF07 grouped-editor entries; original DOM hashes remain locked. Seventeen export tests exposed the new audit accessor's unnecessary dependency on an incomplete workspace fixture. Revenue export audit now comes from the already reconstructed persisted RuntimeResult adapter used by the same workbook; there is no additional workspace read or engine call. Historical export/zero-engine assertions are retained.

The integrated main's Public Safety run `38078341068` is SUCCESS. Correction A revalidation includes the actual signed-CfD/F3/scenario/history/export ring, the seven unchanged exact blob pins and their negative tests, and independent four-vertical complete financial-tree bit-exact comparison. Final focused counts and exact new-head workflow evidence are recorded in the PR description after execution; pending CI must not be presented as acceptance.

Final local Correction A rings: **318 passed** (CSRF, WF07 financial/workspace/browser, decision workspace, dense-layout contract, U2.1 export, post-run context, merged Statements/Debt) and **172 passed** (seven pins/negative governance, released authorities, F3, WF04, scenario tariff and prior Revenue regressions). Both returned rc=0 normally. Compilation and diff hygiene PASS. The complete inactive four-vertical financial fingerprints remain exactly those recorded above. These focused results do not replace exact-head full Public Safety acceptance.
