# P1 Institutional Trust Pack — Review Dossier

Branch: `feat/p1-institutional-trust-pack`

Initial audited base: `a03104300df00f6c4e3b9c46cbdc00ac73c54e71` (main after PR #149).

PR #150 merged while this stream was in progress; current main was merged into the branch once, with no rebase, as required by the stream CI strategy.

This dossier is the independent-review entry point for the P1 methodology + worked Solar + reconciliation master stream.

## 1. Scope disposition

The master audit found that P1 is not a greenfield stream. Current `main` already contains substantial institutional trust work:

- P1.1 — machine-readable methodology / metric authority registry and methodology UI;
- P1.2 — institutional XLSX with Returns, Run Identity and two-sided Reconciliation;
- P1.3 — institutional validation / clean statement, debt, return and persisted Last Run reconciliation;
- Model Trust Pack UX V1 — Last Run, KPIs, Reference Regression Check, FINCO Verify, export, methodology, Run Integrity and Signed Run evidence composition;
- Finance Integrity rebaseline — corrected Total Project Uses / construction financing, sculpting infeasibility and return terminology.

The master stream therefore consolidates the existing authorities rather than recreating them.

## 2. Gap audit

| Area | Audit classification | Master-stream action |
|---|---|---|
| Methodology docs | PARTIAL | Consolidated actual runtime behavior in `docs/trust/FINCO_MODEL_METHODOLOGY.md`; machine registry remains source of truth |
| Model Trust Pack | DONE | Existing V2 Trust Pack reused; no parallel UI |
| XLSX export | DONE for inputs/returns/identity/reconciliation; PARTIAL for clean statement serialization | Existing exporter reused; clean statement binding limitation explicitly disclosed |
| Worked examples | PARTIAL | One canonical Solar case consolidated in `docs/trust/FINCO_WORKED_SOLAR_RECONCILIATION.md` |
| Reconciliation tests | DONE for S&U/OPEX/returns/BS/cash/debt/lineage; DSRA strengthened here | Existing P1.2/P1.3 suites reused; master DSRA reconciliation guard added |
| Finance conventions | DONE / dispersed | Consolidated narrative points to `app/model_methodology_registry.py` and actual runtime modules |
| Run identity | DONE | Existing persisted composite hash / snapshot / engine-version / run-id separation documented |
| Last Run provenance | DONE | P1.3 same-project mutation proof reused |
| Debt sculpting | DONE | Correct fail-closed feasibility invariant documented; no engine changes |
| DSRA | PARTIAL in older prose | Corrected wording and added canonical Solar funding/roll-forward reconciliation guard |
| Shareholder loans | DONE | Share capital / SHL / aggregate sponsor funding and return bases separated |
| Tax conventions | PARTIAL by design | Current model mechanics documented; jurisdiction-specific rules explicitly not claimed |
| IRR/XIRR | DONE | Project / share-capital / total sponsor dated-return semantics consolidated |
| Annual vs period outputs | PARTIAL / dispersed | Standard semestrial model axis, annual tax mapping and native construction grain documented |
| Sources & Uses | DONE | Current Total Project Uses authority and no-residual senior debt proof reused |
| Financial statements | DONE on clean runtime; PARTIAL in XLSX presentation | P1.3/C3 runtime evidence is authoritative; XLSX clean statement serialization remains unavailable |
| Cash waterfall | DONE on clean runtime | P1.3 cash identity + C3 cash-flow authority reused |
| Balance Sheet reconciliation | DONE on clean runtime | P1.3 Solar balance-sheet identity + C3 status gate reused |

## 3. Files added / updated by this stream

Master candidate changes:

- `docs/trust/FINCO_MODEL_METHODOLOGY.md` — canonical institutional narrative and authority map;
- `docs/trust/FINCO_WORKED_SOLAR_RECONCILIATION.md` — canonical synthetic Solar worked case and evidence matrix;
- `docs/review/P1_INSTITUTIONAL_TRUST_PACK.md` — this review dossier / gap audit;
- `tests/test_p1_institutional_trust_pack_master.py` — fast authority guards plus deterministic Solar DSRA reconciliation.

No financial-engine or finco-core file is owned by this stream.

## 4. Canonical worked model

Identifier: `generic_solar_reference`

Protected reference:

- project name `Generic Solar Reference`;
- code `REF-SOLAR-A`;
- 64 MW;
- synthetic sponsor / market code only;
- 25-year horizon;
- 14-month construction;
- semestrial model periods;
- Base scenario for canonical regression evidence.

No client data is used.

## 5. Run identity / Last Run evidence

Persisted Last Run authority is existing product functionality, not introduced here.

The canonical persisted journey used by P1.3 binds:

- committed snapshot identity;
- committed composite/input hash;
- run-bound engine version;
- scenario identity where available;
- persisted summary values;
- canonical Last Run export lineage.

`run_id` remains distinct from `last_runtime_snapshot_id`. A snapshot identifier is never promoted to a UUID merely for presentation.

A post-run Working Copy edit does not mutate historical Last Run evidence.

## 6. Reconciliation table

| Gate | Current evidence | Disposition |
|---|---|---|
| Sources & Uses | P1.2 authoritative senior debt + Total Project Uses; no residual plug | PASS |
| CAPEX detail | P1.2 serialized/detail check where available | PASS for Solar reference |
| OPEX | Serialized sheet readback vs runtime + corruption guard | PASS |
| Revenue | Period/detail vs runtime where available | PASS for supported reference evidence |
| Debt roll-forward | P1.3 Solar opening/principal/closing schedule identity | PASS |
| Project return | Serialized Returns cell vs runtime Project IRR | PASS |
| Share-capital return | Serialized Returns cell vs runtime equity-only XIRR | PASS |
| Total Sponsor XIRR | Serialized Returns cell vs runtime sponsor XIRR | PASS |
| Cash reconciliation | P1.3 clean PF cash-waterfall identity; C3 cash-flow status authority | PASS |
| Balance Sheet reconciliation | P1.3 Solar operating-period balance residual check; C3 completeness/identity gate | PASS |
| DSRA reconciliation | Master Solar guard: Project Uses ↔ policy evidence ↔ COD funding + per-period DSRA balance identity | PASS when exact-head master guard is green |
| Working Copy / Last Run separation | P1.3 real same-project mutation journey | PASS |
| XLSX same-run composite identity | P1.3 committed hash / engine-version binding | PASS |
| Run-identity corruption detection | P1.3 cross-run Solar/Wind guard | PASS |
| Clean statements serialized into institutional XLSX | Current clean workbook bundle intentionally leaves statement package unavailable | NOT_AVAILABLE — presentation limitation |

## 7. Sources & Uses check — Solar

Current protected-reference Finance Integrity evidence:

- Total Project Uses ≈ 35,977.78 kEUR;
- senior debt ≈ 26,983.33 kEUR;
- share capital = 500.00 kEUR;
- derived SHL ≈ 8,494.44 kEUR.

P1.2 explicitly verifies that senior debt comes from the runtime financing authority, not `hard CAPEX - sponsor funding`. If the senior-debt authority is absent, the workbook reports `NOT_AVAILABLE` rather than forcing balance.

`SOURCES_USES_RECONCILIATION = PASS`

## 8. Debt check

The master stream does not introduce debt arithmetic.

Existing P1.3 runtime evidence checks the canonical Solar debt roll-forward, while the underlying clean authority owns:

- opening senior balance;
- draw;
- ACT/360 interest under the generic clean schedule;
- principal;
- closing balance;
- target / realised DSCR;
- typed infeasible state.

The Finance Integrity baseline corrected false convergence and the gearing basis. Current Solar evidence is gearing-bound on Total Project Uses and records first senior interest of approximately 498.82 kEUR.

`DEBT_RECONCILIATION = PASS`

## 9. DSRA check

Current truth:

- `CASH_DSRA`: resolved reserve requirement is included in Project Uses and becomes opening cash-DSRA requirement;
- the same amount is exposed by clean financing-policy evidence and the non-construction FC/COD funding row;
- funding is through the canonical project funding stack; do not describe it generically as a separately sponsor-funded line without run-specific evidence;
- each G2C operating-period reserve movement obeys `opening + top-up - draw - release = closing` and the closing balance carries into the next period;
- `DSRF`: no cash reserve at close; sufficiency support is separate; actual LoC draws are not modelled.

The new master test verifies these invariants on the canonical Solar case without changing reserve economics.

`DSRA_RECONCILIATION = PASS` only after that exact-head test is green.

## 10. Statements / cash / Balance Sheet check

The clean production authority already assembles exactly one C3 `financial_statements_result`. Existing P1.3 coverage uses the clean runtime presentation to prove:

- canonical Solar PF cash identity across statement periods;
- canonical Solar Balance Sheet residual within the explicit tolerance for every populated operating period;
- separate senior debt roll-forward reconciliation.

The C3 assembler reports Balance Sheet OK only after applicable-period coverage and the real Assets − Liabilities/Equity identity pass. There is no balancing plug.

Accordingly the master gate is:

`CASH_RECONCILIATION = PASS`

`BALANCE_SHEET_RECONCILIATION = PASS`

A narrower presentation limitation remains: `app/export/institutional_workbook.py` does not currently bind the already-existing clean C3 statement result into the clean workbook bundle. Its Tax/P&L/PF Cash Flow/Balance Sheet worksheets therefore show unavailable state on that path. That limitation is tracked as:

`XLSX_STATEMENT_VALUE_TRACE = PASS` / `XLSX_STATEMENT_RUN_BINDING = BY_CONSTRUCTION` / `XLSX_CROSS_RUN_SOURCE_PROVENANCE = NOT_AVAILABLE` (closed by P1 Model Completeness: clean C3 statements bound through the app-layer serialization adapter verbatim; same-execution use is by construction; no independent source-package digest exists in V1)

It does not downgrade the clean runtime reconciliation gates and must not be “fixed” with independent spreadsheet maths.

## 11. Returns check

Canonical terminology and basis:

- Project IRR = unlevered dated Project XIRR;
- Share-capital IRR = pure legal equity XIRR, SHL excluded;
- Total Sponsor XIRR = combined equity + SHL sponsor cash-flow XIRR.

Current protected Solar regression snapshot:

- Project IRR ≈ 11.768%;
- Share-capital IRR ≈ 45.953%;
- Total Sponsor XIRR ≈ 16.610%.

P1.2 reads the serialized Returns cells back and compares them to runtime authority; corruption tests prove the check is not tautological.

`PROJECT_RETURN_TRACE = PASS`

`SPONSOR_RETURN_TRACE = PASS`

## 12. XLSX reconciliation

The master stream uses the existing institutional workbook. No independent Excel model is created.

The canonical Last Run path is historical and fails closed if a committed run is missing. Factory references are classified separately as `FACTORY_REFERENCE`. Preview/Working Copy export behavior remains separately labelled.

The same-run invariant is already proved in P1.3 for persisted Solar Last Run evidence: workbook composite hash and run-bound engine version match the persisted committed identity, and a post-run Working Copy edit does not switch the export to draft values.

`WORKING_COPY_LAST_RUN_SEPARATION = PASS`

`XLSX_SAME_RUN_IDENTITY = PASS`

`XLSX_MODEL_RECONCILIATION = PASS` for the current XLSX-supported reconciliation quantities. Clean statement worksheet serialization is now bound (P1 Model Completeness); typed NOT_AVAILABLE rows remain only for quantities the clean runtime does not publish.

## 13. Browser / Trust Pack discoverability

Existing Model Trust Pack UX already exposes the relevant institutional evidence without a new documentation application:

- Last Run Identity;
- Core KPIs;
- Reference Regression Check (explicit / deferred);
- Run Integrity;
- FINCO Verify;
- Institutional Export;
- Methodology page link / metric convention rows;
- Signed Run Certificate (explicit / deferred).

The master stream therefore does not redesign navigation. The existing Trust Pack and `/model/methodology` remain the user-facing discovery surfaces; the new Markdown pack is the repository/reviewer narrative.

## 14. Authority boundaries / frozen namespaces

Required final diff gates:

- `financial_engine/**` semantic diff = ZERO;
- `finco_core/**` semantic diff = ZERO;
- `finco_radar/authority/**` = ZERO;
- `app/model_market_bridge/**` = ZERO;
- Signed Run cryptography = ZERO;
- FINCO Verify authority = ZERO;
- Yield economics = ZERO;
- token authority / utility = ZERO.

PR #150 Model↔Market Bridge was merged into current main once during this stream and remains unchanged by the P1 diff.

## 15. Known limitations

1. Canonical institutional XLSX does not currently serialize the clean C3 statement package on its clean path.
2. DSRF actual draw mechanics are not modelled.
3. Country/jurisdiction-specific tax engines are not claimed.
4. Average DSCR on the Solar reference is a simple arithmetic mean and can be influenced by a short payoff period; minimum DSCR remains the more decision-relevant covenant statistic.
5. Factory reference evidence is not a persisted Last Run identity.

## 16. Deferred model-policy decisions

Explicitly deferred:

- DSRA funding-policy change;
- full jurisdiction-specific tax engines;
- institutional XLSX clean C3 statement serialization/binding;
- engine performance optimisation;
- Data Center sensitivity redesign;
- multitenancy;
- Model↔Market production Verify activation;
- token metering;
- final Product Truth release reconciliation.

## 17. Review status

The branch can be marked complete only after the final exact-head checks confirm the new master guard and the unchanged P1.1/P1.2/P1.3 / full regression suite required by this stream.

The XLSX clean-statement presentation limitation is explicit and deferred; it is not a missing financial-engine authority and does not require an engine/core diff in this PR.
