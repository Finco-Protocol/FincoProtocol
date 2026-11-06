# PR3b-1 source handoff

Owner Addendum A controls the information architecture: one Financing workspace, no parallel Studio destination and no five-tab replacement. Structure & Terms holds transitional links to the existing scalar/bankability editors; Facilities / Funding holds facility and investor links. Sources & Uses and Repayment, Coverage & Covenants retain Last Run provenance. Returns/valuation links to the existing `#results` home. Quality remains three distinct panels. No existing navigation has been removed; exhaustive before/after inventory and private acceptance are required before retirement.

These are isolated read-only modules, deliberately absent from the production entry point until PR #429 merges. Do not copy the preview bundle into `static/`, change shared governance or mount a second writer while #429 owns integration.

`FinancingReadLayer` takes `{scope: {project, scenarioId, historyId?}, reloadKey?}`. Supply the actual active scenario ID from the existing workspace (including explicit `null` for a proven base scope). A scope change remounts the reader; reload hides prior evidence until the six GET requests finish. It uses workspace and credit bookends around Studio and Debt fields. Debt metrics come from the selected credit Run, not a new endpoint. Existing editor transitions remain links, without mounting duplicate editors or changing drafts. Historical selection remains available, but dependent zones are hidden when it is not Studio's Last Run. Legacy links preserve the existing `financing=` selectors and `#financing` anchor; verify them at the final existing mount.

`FinancingOverview` also accepts an already assembled `Evidence` object for isolated presentation tests. `checkRunEvidence` is the mandatory gate inside the component. It compares raw numeric totals exactly, rejects missing values, verifies project/scenario, freshness and read identities, and checks the current hash. STALE requires the same workspace Last Run snapshot/hash/time anchor. This mitigates cross-read mixing but **does not prove Studio snapshot identity**: the API lacks snapshot_id. Diagnostics retain `MITIGATED_NOT_PROVEN`. No API or finance semantics were changed.

Mappings:

| UI | Existing source |
| --- | --- |
| Requested gearing, Last Run | credit structure.requested_gearing, server display |
| Requested gearing, Working Copy | Debt field debt.senior.gearing_pct, separate units/display |
| Senior commitment (sized) | credit capacity.final_commitment; Studio supplies actual S&U Senior row independently |
| Committed | unavailable distinct record; never a copy of Sized |
| Drawn | construction_rows[].fields array, exact Senior draw label, one value per period |
| Outstanding | debt_metrics.periods[].senior_opening_keur / senior_closing_keur |
| Sources, uses, totals, residual, balance | Studio sources_uses.view, no sums or Working reconstruction |
| Coverage, covenant, EoD, lock-up | existing debt_metrics evaluation, contract_terms and period markers |
| Integrity | credit integrity status and original failure reasons |
| Financial Bankability | credit capacity min/avg DSCR, target, aggregate binding; DSRA evidence |
| Terms / fee availability | Studio senior_detail_rows, bankability.fees_editable, senior_lock_reason |

Finding classifications and metrics are preserved. The requested named categories are grouped only when returned exactly; current responses may instead use OBSERVED_FINANCIAL_RESULT or CONTRACTUAL_COVENANT. Unmatched findings remain discoverable under their original classifications. No new threshold, score or inferred severity is added. Below-one coverage does not overwrite the server's Integrity status in either direction.

Validation from repository root:

```sh
npm --prefix frontend ci
npm --prefix frontend run typecheck
node --test --test-isolation=none frontend/src/app/financing/pr3b1/__tests__/readLayer.test.mjs
npm --prefix frontend run build -- --outDir /tmp/pr3b1-main-build
```

The browser harness under `__tests__/browserHarness.mjs` is synthetic only. Bundle it with the existing esbuild and serve the output in a temporary directory; it imports and bundles the otherwise unmounted modules. It supports Current/Stale/mismatch/two-Senior preview states, plus `?loader=1` for GET interception tests. No production route imports the harness.

After #429 merges: ordinary merge actual main (no rebase/force); integrate at the narrow existing Financing entry point without discarding legacy editor state or deep links; build the shared artifact once; add a closed exact-source PR3b successor and genuinely moved pins; run required exact-head checks; open one Draft PR. Per-block writer lifecycle remains PR3b-2. No merge/deploy authorization.
