# FINCO MODEL V2 — F1 Sources & Uses acceptance / authority report

Status: **Draft implementation for review; not merged, not deployed**.

## Scope and verified starting state

- Repository: `Finco-Protocol/FincoProtocol`.
- Verified main on 2026-10-09: `1977033da8967a93d581d6407337798dc0a44aad`.
- Feature branch: `feat/model-v2-financing-f1-sources-uses`, based directly on that SHA.
- PRs #224, #225, #226, #227 and #228: GitHub reports merged.
- GitHub open PR scan: no F2 Senior Debt Bankability / F3 Multi-Tranche PR at the scan time.
- Draft PR: record GitHub URL and exact head from final PR state; do not assume report text is live commit authority.
- No engine, finco_core, domain, Radar, Yield or Crypto edits are intended.

## Actual persistence evidence inventory

| Desired evidence | Repo authority | Available to F1 now | Classification |
| --- | --- | --- | --- |
| Hard CAPEX, financing costs, reserve, developer uses, total uses | `ProjectUses` in `financial_engine/financing/contracts.py` | Typed during engine execution; no signed-off `RuntimeResult` serialized bridge | ENGINE-ONLY, NOT PERSISTED |
| Full sources, funding reconciliation, residual | `SourcesAndUses` via `build_sources_and_uses`; `ConstructionFundingResult` audit | Not included in `RuntimeResult`'s six persisted payloads | ENGINE-ONLY, NOT PERSISTED |
| Sized Senior amount | `RuntimeResult.runtime_summary.senior_debt_keur` | When numeric and finite | PERSISTED CANONICAL RESULT |
| Actual gearing / gearing cap | `RuntimeResult.runtime_summary.actual_gearing_pct / gearing_cap_pct` | When numeric and finite | PERSISTED CANONICAL RESULT |
| Minimum DSCR, LLCR, target DSCR | `RuntimeResult.debt_schedule.summary` | When present; otherwise unavailable | PERSISTED CANONICAL RESULT |
| SHL cash contributed | `RuntimeResult.sponsor_schedule.summary.total_shl_cash_contributed_keur` | When numeric and finite; **not** full sponsor sources | PERSISTED CANONICAL RESULT |
| Run Integrity | `WorkspaceStateRecord.last_integrity_evidence` / `RunHistoryEntry.integrity_evidence` | Existing persisted checks and verdict | PERSISTED CANONICAL RESULT |
| Legal equity / SHL commitment configurations, requested gearing | `ProjectInputs.financing` via authorized Working Copy snapshot | Displayed independently; not actual draw results | CURRENT WORKING INPUT |
| DSCR/gearing capacities, binding constraint, fixed-point solver verdict | `ProjectFinancingResult` | No approved persisted bridge in runtime result | ENGINE-ONLY, NOT PERSISTED |
| Run-history evidence | `get_run_history_entry(user_id, project_id, history_id)` | Immutable, scoped per owner/project | PERSISTED CANONICAL RESULT |

**Critical conclusion:** Available financing-stack arithmetic exists in the engine but cannot be reproduced from these partially persisted values. A fully numerically reconciled Sources & Uses grid, including total sources, total uses, residual and construction funding waterfall, is **not claimable yet**. The page marks those values `Unavailable`, not zero, and names the missing bridge.

## Implemented F1 boundary

1. Independent read-only `GET /v2/financing/sources-uses?project=<code>`, registered in `main_web.py`, linked from the Investor sheet.
2. Authorization via `resolve_accessible_project` and the owner/project-scoped `PostRunRequestContext.capture`; final `validate_current` guards concurrent Working Copy edits.
3. Last Run and immutable historical-run selection (query `history_id`), using only scoped Run History persistence; no current input substituted into a historical Run.
4. Persisted sized Senior, SHL contributions and numeric coverage indicators where actually available; clear financial integrity versus input freshness distinction.
5. Current typed configuration shown separately from historical Last Run cash evidence, with `kEUR` and ratio/% distinctions.
6. Professional compact responsive sources, uses, bankability and evidence tables; unavailable decomposition and reconciliation are explicitly shown.
7. Real reconciliation write disabled, **without an inert fake action**.
8. No new endpoint that changes project finance assumptions; no run-model execution on a GET.

## F1-C Balance S&U gate decision

**Do not enable Apply.** The current approved write path is not an atomic financing-stack balancing transaction with a preview, mode-aware allocations (SHARE_CAPITAL_THEN_SHL / EQUITY_ONLY), owner/protected-reference checks, per-scenario composite CAS, typed persistence, stale marking and subsequent canonical reconciliation. Building one would intrude into the registry, input adapter, update service and F2/F3-owned work.

Proposed reviewed integration contract:
- `FinancingBalanceProposal`: owner/project/scenario/composite-hash binding, current `ProjectUses`, true engine sources, options by funding mode, senior/gearing cap, proposed typed source changes and unresolved residual.
- Explicit user's selected proposal and authorization.
- Existing canonical owner/scenario/CAS write service persists complete typed funding changes atomically and marks Working Copy stale.
- Last Run and Run History remain unchanged until a new Run.
- New Run commits an auditable typed `SourcesAndUses` serialized result and residual; UI reads that result directly with typed integrity and failure status.

## Required upstream authority bridge for full F1 totals

In the **Run** boundary (not in this PR), create a reviewed, versioned serializer for the engine's already produced `SourcesAndUses` / `ProjectFinancingResult` / `ConstructionFundingResult`, with unambiguous kEUR units, typed UNAVAILABLE, matching Run snapshot + scenario/composite identity, frozen history copy, and export parity. Once persisted, F1 can show correct total-uses, audited total-sources and residual without any Jinja/JavaScript arithmetic.

## Test and review status

- New focused tests: numeric-zero/missing, malformed fail-closed, current/stale/historical isolation, run integrity != S&U balance, owner authorization, read-only GET, Solar/Wind real `/v2/workbook/run` followed by scoped Run History verification.
- Tests are committed to the Draft branch, **not yet locally executed** in this connector-only environment.
- Browser screenshots: **not performed** in this environment. Real authenticated browser acceptance is still required before a merge approval.
- Workflow status: review the five workflows on **exact final PR HEAD** before any merge decision; this report does not pre-certify CI.
- Required regression suites: `tests/test_model_financing_bankability.py`, `tests/test_model_v2_governance.py`, `tests/test_model_v2_run_history.py`, `tests/test_financing_f1_sources_uses.py`.
- Compile, Public Safety, frozen namespace diff and F2/F3 overlap: must be verified on final branch head. Intended frozen namespaces modified: **none**.
- Recommended disposition: **DRAFT ONLY — NOT MERGE-READY** pending automated and browser acceptance plus upstream persistence-bridge decision.

This F1 delivery is economically truthful to the verified persisted authority boundary, not a fabricated balanced S&U calculator.
