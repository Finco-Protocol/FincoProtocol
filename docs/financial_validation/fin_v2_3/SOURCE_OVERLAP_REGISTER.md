# Parallel workstream overlap register

Inspected main: `128bf0c2b79af56985326543132cc806ff7f001c`.
FIN-V2-2 PR #390: `842fedadd57f33d87e73ed5d231f451977889bf8`.
RC-M PR #388: `248d9112f275626fe10ef7fe5615b2b00e38c887`.
FIN-V2-1: no matching open PR identified at the last inspection; reserved scope
remains sensitivity, rate shocks, lender adjustments and EV drivers.

| Path | Other ownership | FIN-V2-3 hunk and resolution |
|---|---|---|
| app/api/project_runner.py | FIN-V2-2, additive debt evidence | Three-line financial-core attachment beside financing_evidence. Preserve PR #390's senior-debt builder first, then call attach_financial_core. Never overwrite its result. |
| app/export/institutional_reporting_v3.py | FIN-V2-2 lender section | Preserve its `_write_senior_debt_evidence` and section call. Keep FIN-V2-3's independent append-only valuation section and Total Sponsor primary order. |
| app/services/sensitivity_execution.py | Shared candidate worker; FIN-V2-1 adjacent | Add `regime` alongside unchanged canonical `kpis` result. Preserve FIN-V2-1's candidate/driver changes; no shock logic is changed here. |
| app/v2/router.py | FIN-V2-1 one-driver route; RC-M adjacent | One Goal Seek target-unit conversion hunk. Preserve one-driver and React work; ratio targets divide by 100, DSCR/NPV targets do not. |
| app/services/goal_seek.py | Shared backend; RC-M consumes | Finite new metrics, declared units, canonical verification and regime guard. Preserve existing solver/evaluator authority and Save/Run boundaries. |
| app/input_adapter.py | Merged F01; shared input fold | Add financial-core config application after Developer Economics, before quarterly admission. F01 rate handling is unchanged. |
| app/workbook/registry.py, update_service.py | Shared configuration; RC-M | Add one versioned policy JSON field/validator; preserve all existing ownership/CSRF/CAS logic and F01 unit semantics. |
| app/services/clean_presentation_adapter.py | Shared persistence projection | Add sponsor contribution/date-axis/PIK/net fields and separate canonical SHL balance rows; preserve every old value. |
| app/export/run_evidence.py | Shared frozen export authority | Two read-only accessors. No digest algorithm, persistence or history rewrite. |
| tests/* governance successors | RC-M and other financial streams | Additive union of exact-blob cohorts and Owner-approved test successors; retain historical maps/negative controls. Renew combined exact-blob manifest after resolving source hunks. |

Integrate accepted FIN-V2-1 and FIN-V2-2 source work, then FIN-V2-3 consumers; apply
the runner hunk in debt-evidence-before-valuation order. RC-M consumes the typed
configuration/evidence/Goal Seek contracts after its branch is synchronized with
merged F01/main. The integration agent owns the final branch and cross-workstream
CI. This branch neither creates a competing RC nor pushes to another branch.

Until FIN-V2-2 is present, actual/contractual extended coverage and rolling LLCR
return `DEBT_EVIDENCE_NOT_AVAILABLE`; existing C2 first-opening LLCR and PLCR
remain separately available under a configured policy. The isolated tests use
canonical schedule fixtures; the spreadsheet uses exact-source test composition.
