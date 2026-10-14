# RC-3 / M6 — Institutional Valuation & Acquisition (release-closed candidate)

## Integration boundary
- Base: verified main `6fc77de98bc0562fb51efdbf96e1803a29b5b148` (RC-2 #278 merged).
- Branch: `feat/model-m6-institutional-valuation-v1`.
- Delivery: ONE Draft PR, target main. No merge/deploy/self-approval.
- All new M6 metrics carry `CANDIDATE_NOT_AUTHORIZED`; `ACTIVATION_ENABLED = False` is a source literal.
- The workspace never calls `evaluate()` or a project-finance Run on GET.
- Optional **explicit POST-only** financial candidate preview is closed by default, requires `FINCO_M6_CANDIDATE_REVIEW=1`, `development/internal` app mode, non-demo admin session, owner-scoped saved case and signed CSRF. It returns labelled `CANDIDATE_NOT_AUTHORIZED` JSON with no-store, never a canonical KPI and never enabled in pilot/production.
- Revenue V3/F4-P2 activation and original project/debt/tax math remain unchanged.

## Financial authority / source inventory

| Source | Existing authority | M6 behavior |
|---|---|---|
| Project NPV | `financial_engine/valuation/model.py`, C1 unlevered cashflows | Reuse without claiming automatic Enterprise Value. NPV may be NOT_CONFIGURED, pre-valuation dates unsupported in existing ACT/365 primitive. |
| XIRR/XNPV | `finco_core.sponsor.xirr`, `finco_core.sponsor.xnpv` | Reuse existing ACT/365 dated calculations; only acquisition-specific vectors and explicit bid root added. |
| Gross/WHT/net equity | `g2c_result.waterfall_periods` | Exact full-precision values, no derived gross/net, no F4 allocation needed |
| SHL principal/interest | G2C actual SHL receipt fields | Captured separately and EXCLUDED from ordinary-share buyer receipts |
| Equity funding | G2C actual four legal equity contribution fields | Post-closing calls negative for buyer; preclosing sponsor funding NOT repeated |
| Project unlevered C1 cashflows | `g2c.return_summary.project.cashflows` | Saved separately from legal dividend evidence, not used as equity buyer cashflow |
| Run identity | V2 existing atomic Run commit, append-only history | Source bound to owner/project/snapshot/composite/scenario before existing atomic commit |
| WACC | AUTHORITY_MISSING | Never manufacture/label a user discount rate as WACC |
| Debt and unrestricted/restricted cash | BS period-end and debt schedules | No closing-date interpolation. Candidate permits explicit labelled closing assumptions only; no canonical exact-balance claim |
| Acquisition price/returns/bridge | NEW, financial policy not approved | Separate release-closed typed candidate only |

### Before/after persistence capability

Previously, the history snapshot preserved sponsor legal-equity distributions but standard sponsor schedules did not guarantee complete full-precision gross / withholding tax / net receipts. F4 opt-in captured some receipt evidence only with an investor agreement.

New M6 `runtime_summary.acquisition_source_candidate_v1` is optional on successful V2 Runs, with exact G2C gross/WHT/net, legal equity calls, SHL interest/principal and SHL contributions, plus separate C1 project cashflows and full Run binding. It is **not** a new finance authority, payment obligation or extra Run History writer.

The acquisition case is saved to isolated `model_m6_acquisition_cases` with append-only immutable `model_m6_acquisition_revisions`.

**M6 schema lifecycle (targeted persistence correction):** Both tables and their index are initialized only inside the acquisition Save's `BEGIN IMMEDIATE` transaction (never in read paths). The first unauthorized/failed Save rolls back the M6 DDL together with any data changes. `read_case()` and `list_cases()` use a dedicated SQLite `mode=ro`, `query_only=ON` connection; they never call the global schema-initializing connection factory. Absent SQLite DB or an absent M6 case table returns `None` / `[]` without creating any file or table. Read and write connections close deterministically, including on errors. Focused tests compare `sqlite_master`, `schema_version`, immutable financial history/project rows, and acquisition revisions before/after first and repeated reads, and exercise in-process FastAPI GET and CSRF/protected POST rejection. Saves use BEGIN IMMEDIATE, strict owner/project, protected-reference denial, source Run identity and revision CAS, with rollback on any failure. Editing cases NEVER changes Working Copy hash, Last Run or scenario state. A newer Run marks an older case SOURCE_OUTDATED, without rewriting its immutable source link. Legacy history remains unaltered and returns EVIDENCE_UNAVAILABLE.

## V1 contract
Transaction: **100% ordinary share acquisition**, cash purchase, no automatic refinancing.
- Buyer paid purchase price and explicit fees/closing adjustment are closing-date cash outflows.
- Buyer receives only net legal equity dividends after closing and funds source-proven subsequent legal equity calls. Existing sponsor contributions before closing are excluded.
- SHL is an independent lender claim. M6 V1 excludes SHL lender rights and their cashflows from buyer ordinary equity. No automatic SHL acquisition, resale or refinancing.
- Optional explicit exit proceeds only at an explicit postclosing date **within the committed evidence horizon**. A closing date at/after the last committed receipt date is unsupported. Material dividend or capital-call events exactly on the closing date cause `CLOSING_DATE_ENTITLEMENT_ORDER_AMBIGUOUS` (no invented intraday ordering).
- No assumed hidden capital calls, tax leakage, debt pay-off, release of restricted cash or WACC.
- An enterprise/equity bridge, where configured, uses **EXPLICIT_USER_UNDERWRITING** inputs only and excludes restricted cash from free cash. The balance date must be the exact closing date.
- Existing project cashflows remain independent of acquisition date. Buyer discounting uses dates after closing only (plus closing outflow). No reset of old sponsor funding.

## Candidate numerical methodology
- Buyer cashflow: negative equity purchase, fees and explicit signed closing adjustment at closing; after closing source-proven net dividends less actual equity calls, plus optional stated exit.
- Date axis sorted, same-day components retained separately for correct MOIC.
- XIRR: existing `robust_xirr`. Multiple sign alternations are conservatively unsupported, instead of presenting an ambiguous return. The buyer IRR is not Sponsor IRR.
- NPV: existing `xnpv`, anchored to acquisition closing date, ACT/365, explicit user rate.
- Bid ceiling: deterministic 100-iteration bisection of buyer XNPV at target IRR versus equity purchase price, only inside declared lower/upper price bounds. No extrapolation, fake closed-form financial equivalence, or artificial WACC.
- Enterprise/equity: explicit enterprise assumption minus senior/debt-like/SHL liabilities plus unrestricted cash and separately signed underwriting adjustments. Restricted cash excluded.
- All figures are calculated in a testable **candidate** module, not FINCO canonical analytics; the production-facing workspace shows source facts and input assumptions, not unapproved outputs.

## User experience
`/v2/valuation-acquisition?project=<code>` entered through Developer Economics / Investment Decision:
1. Select immutable committed Run.
2. Inspect Run binding and exact gross/net/WHT/SHL evidence.
3. Create and Save own versioned acquisition case (signed CSRF).
4. Reload and revision-CAS edit without mutating Last Run.
5. View explicit closing bridge assumptions and SOURCE_OUTDATED status.
6. Compare case source/date compatibility; actual acquisition return comparison remains closed.
7. See `CANDIDATE_NOT_AUTHORIZED` rather than production KPI/BUY-SELL recommendation.
8. An explicit, signed, owner-scoped admin-only DEV POST can expose unapproved candidate figures for review when separately opted in. The production UI stays locked.

## Exact-path successor proposal for independent reviewer
Protected/shared modified paths, for **content-specific approval only**:
- `app/api/project_runner.py`: optional full-precision source extraction from completed G2C, independent of F4.
- `app/v2/router.py`: additive binding into existing atomic summary commit.
- `main_web.py`: additive M6 router mount.
- `app/templates/v2/developer_decision.html`: one additive navigation link.

New scoped files:
- `app/model_v2/acquisition/__init__.py`
- `app/model_v2/acquisition/evidence.py`
- `app/model_v2/acquisition/economics.py`
- `app/persistence/acquisition_repository.py`
- `app/v2/acquisition_router.py`
- `app/templates/v2/acquisition.html`
- `tests/test_m6_institutional_acquisition_candidate.py`
- `docs/model_v2/M6_INSTITUTIONAL_ACQUISITION_CANDIDATE.md`

The reviewer must independently capture exact git blob SHAs for every protected/shared path from the final PR HEAD and decide the narrow governance successor. No broad waivers or changes to CI guards in this PR.

## Explicit open financial-policy decisions
1. Authorize/deny shareholder net equity cashflow interpretation under change of ownership and post-close G2C projected legal equity calls.
2. Approve future legal-equity funding obligations, any tax leakage beyond source WHT, transaction fee classification, and signed closing adjustment semantics.
3. Approve project Enterprise Value methodology and exact balance-date debt, cash, DSRA, SHL and working capital bridge rules (V1 does not infer EV or interpolate).
4. Approve buyer IRR/MOIC conventions, root ambiguity handling, bid bounds, explicit exit recognition and corporate acquisition taxation.
5. Decide whether buyer can acquire separately priced SHL and whether refinancing/asset acquisition are later supported structures.
6. Only after reviewed exact-content tests and finance-policy approvals may a separate, governed activation PR modify the hard-coded release gate.

**CURRENT: CANDIDATE_NOT_AUTHORIZED. NO MERGE. NO DEPLOY.**
