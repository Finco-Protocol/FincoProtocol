# P1 Institutional Trust Pack — Review Dossier

Branch: `feat/p1-institutional-trust-pack`

Base audited at stream start: `a03104300df00f6c4e3b9c46cbdc00ac73c54e71` (main after PR #149).

This dossier is the independent-review entry point for the P1 methodology + worked Solar + reconciliation master stream.

## 1. Scope disposition

The master audit found that P1 is not a greenfield stream. Current `main` already contains substantial institutional trust work:

- P1.1 — machine-readable methodology / metric authority registry and methodology UI;
- P1.2 — institutional XLSX with Returns, Run Identity and two-sided Reconciliation;
- P1.3 — institutional validation / real persisted Last Run reconciliation;
- Model Trust Pack UX V1 — Last Run, KPIs, Reference Regression Check, FINCO Verify, export, methodology, Run Integrity and Signed Run evidence composition;
- Finance Integrity rebaseline — corrected Total Project Uses / construction financing, sculpting infeasibility and return terminology.

The master stream therefore consolidates the existing authorities rather than recreating them.

## 2. Gap audit

| Area | Audit classification | Master-stream action |
|---|---|---|
| Methodology docs | PARTIAL | Consolidated actual runtime behavior in `docs/trust/FINCO_MODEL_METHODOLOGY.md`; machine registry remains source of truth |
| Model Trust Pack | DONE | Existing V2 Trust Pack reused; no parallel UI |
| XLSX export | DONE for core inputs/returns/identity/reconciliation; PARTIAL for clean statements | Existing exporter reused; clean statement binding gap explicitly disclosed |
| Worked examples | PARTIAL | One canonical Solar case consolidated in `docs/trust/FINCO_WORKED_SOLAR_RECONCILIATION.md` |
| Reconciliation tests | DONE for S&U/OPEX/returns/lineage; PARTIAL for statement/DSRA movement evidence | Existing P1.2/P1.3 suites reused; false-PASS guard added |
| Finance conventions | DONE / dispersed | Consolidated narrative points to `app/model_methodology_registry.py` and actual runtime modules |
| Run identity | DONE | Existing persisted composite hash / snapshot / engine-version / run-id separation documented |
| Last Run provenance | DONE | P1.3 same-project mutation proof reused |
| Debt sculpting | DONE | Correct fail-closed feasibility invariant documented; no engine changes |
| DSRA | PARTIAL in older prose | Corrected wording: cash DSRA is a Project Use funded through canonical funding stack; DSRF no-cash-reserve semantics documented |
| Shareholder loans | DONE | Share capital / SHL / aggregate sponsor funding and return bases separated |
| Tax conventions | PARTIAL by design | Current model mechanics documented; jurisdiction-specific rules explicitly not claimed |
| IRR/XIRR | DONE | Project / share-capital / total sponsor dated-return semantics consolidated |
| Annual vs period outputs | PARTIAL / dispersed | Standard semestrial model axis, annual tax mapping and native construction grain documented |
| Sources & Uses | DONE | Current Total Project Uses authority and no-residual senior debt proof reused |
| Financial statements | PARTIAL | Clean C3 result exists, but institutional XLSX clean path does not bind it |
| Cash waterfall | DONE in clean G2C/C3; PARTIAL in XLSX | Economic authority exists; current canonical XLSX statement surface is unavailable on clean path |
| Balance Sheet reconciliation | NOT DONE on canonical XLSX | Must not be marked PASS until existing C3 result is bound and reconciled in export |

## 3. Files added / updated by this stream

Expected master candidate changes:

- `docs/trust/FINCO_MODEL_METHODOLOGY.md` — canonical institutional narrative and authority map;
- `docs/trust/FINCO_WORKED_SOLAR_RECONCILIATION.md` — canonical synthetic Solar worked case and evidence matrix;
- `docs/review/P1_INSTITUTIONAL_TRUST_PACK.md` — this review dossier / gap audit;
- `tests/test_p1_institutional_trust_pack_master.py` — fast guard for identity, authority reuse and truthful non-PASS statement status.

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
| Debt-service total | Period debt table vs runtime total where available | PASS where authority available |
| Project return | Serialized Returns cell vs runtime Project IRR | PASS |
| Share-capital return | Serialized Returns cell vs runtime equity-only XIRR | PASS |
| Total Sponsor XIRR | Serialized Returns cell vs runtime sponsor XIRR | PASS |
| Working Copy / Last Run separation | P1.3 real same-project mutation journey | PASS |
| XLSX same-run composite identity | P1.3 committed hash / engine-version binding | PASS |
| Run-identity corruption detection | P1.3 cross-run Solar/Wind guard | PASS |
| Cash-statement reconciliation | Clean C3 exists but is not bound into current institutional XLSX clean path | PARTIAL / XLSX NOT_AVAILABLE |
| Balance Sheet reconciliation | Current institutional XLSX clean path intentionally lacks bound statements | NOT_AVAILABLE |
| Dedicated DSRA movement XLSX reconciliation | DSRA authority exists but no dedicated two-sided institutional XLSX movement check is claimed | PARTIAL |

## 7. Sources & Uses check — Solar

Current protected-reference Finance Integrity evidence:

- Total Project Uses ≈ 35,977.78 kEUR;
- senior debt ≈ 26,983.33 kEUR;
- share capital = 500.00 kEUR;
- derived SHL ≈ 8,494.44 kEUR.

P1.2 explicitly verifies that senior debt comes from the runtime financing authority, not `hard CAPEX - sponsor funding`. If the senior-debt authority is absent, the workbook reports `NOT_AVAILABLE` rather than forcing balance.

## 8. Debt check

The master stream does not introduce debt arithmetic.

Existing authority owns:

- opening senior balance;
- draw;
- ACT/360 interest under the generic clean schedule;
- principal;
- closing balance;
- target / realised DSCR;
- typed infeasible state.

The Finance Integrity baseline corrected false convergence and the gearing basis. Current Solar evidence is gearing-bound on Total Project Uses and records first senior interest of approximately 498.82 kEUR.

## 9. DSRA check

Current truth:

- `CASH_DSRA`: resolved reserve requirement is included in Project Uses and becomes opening cash-DSRA requirement;
- funding is through the canonical project funding stack; do not describe it generically as a separately sponsor-funded line without run-specific evidence;
- `DSRF`: no cash reserve at close; sufficiency support is separate; actual LoC draws are not modelled.

Dedicated two-sided DSRA movement reconciliation in the institutional XLSX is not currently proven; status remains PARTIAL.

## 10. Statements check

A significant audit finding prevents a false COMPLETE marker at this base SHA:

- `run_clean_production()` already assembles one `financial_statements_result` through the clean C3 authority;
- `app/export/institutional_workbook.py` currently sets clean-path `statements` unavailable instead of binding that existing result;
- Tax, P&L, PF Cash Flow and Balance Sheet writers therefore render unavailable for clean G2C institutional exports;
- the clean statements contract itself may also carry typed unavailable sub-statuses when an accounting authority is unresolved.

This is not repaired with a duplicated spreadsheet calculation. A future app-layer binding correction may expose the existing clean result, but it must preserve typed unavailable status and add real reconciliation evidence before this gate is called PASS.

Current review disposition:

`BALANCE_SHEET_RECONCILIATION = NOT_AVAILABLE`

`CASH_RECONCILIATION = PARTIAL / XLSX NOT_AVAILABLE`

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

## 12. XLSX reconciliation

The master stream uses the existing institutional workbook. No independent Excel model is created.

The canonical Last Run path is historical and fails closed if a committed run is missing. Factory references are classified separately as `FACTORY_REFERENCE`. Preview/Working Copy export behavior remains separately labelled.

The same-run invariant is already proved in P1.3 for persisted Solar Last Run evidence: workbook composite hash and run-bound engine version match the persisted committed identity, and a post-run Working Copy edit does not switch the export to draft values.

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

PR #150 Model↔Market Bridge remains a separate stream and is not imported into this PR.

## 15. Known limitations

1. Canonical institutional XLSX does not currently bind the clean C3 statements result on the clean path.
2. Therefore Balance Sheet and full cash-statement reconciliation cannot truthfully be reported PASS in this master branch as initially specified.
3. Dedicated institutional XLSX DSRA movement reconciliation is not currently a proven two-sided check.
4. DSRF actual draw mechanics are not modelled.
5. Country/jurisdiction-specific tax engines are not claimed.
6. Average DSCR on the Solar reference is a simple arithmetic mean and can be influenced by a short payoff period; minimum DSCR remains the more decision-relevant covenant statistic.
7. Factory reference evidence is not a persisted Last Run identity.

## 16. Deferred model-policy decisions

Explicitly deferred:

- DSRA funding-policy change;
- full jurisdiction-specific tax engines;
- accounting-policy completion for currently unresolved clean statement lines;
- clean C3 -> institutional XLSX binding and statement reconciliation closure;
- engine performance optimisation;
- Data Center sensitivity redesign;
- multitenancy;
- Model↔Market production Verify activation;
- token metering;
- final Product Truth release reconciliation.

## 17. Review status

This branch is suitable for an **OPEN DRAFT** review, but the master stream must not emit `FINCO_P1_INSTITUTIONAL_TRUST_PACK_COMPLETE` while the explicitly requested Balance Sheet/Cash reconciliation gates remain unavailable.

Expected honest marker at this candidate until that separate binding/evidence gap is closed:

`FINCO_P1_INSTITUTIONAL_TRUST_PACK_REVIEW_READY_WITH_STATEMENT_GAP`
