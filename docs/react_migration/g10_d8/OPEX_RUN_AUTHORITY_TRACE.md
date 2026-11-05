# OPEX_RUN_AUTHORITY_TRACE.md (sanitized) — the committed-Run OPEX data chain

All anchors verified at `main` `cd125b5e08302ea1db7169e172fec288aa7acea5`. Synthetic evidence only; no client/workbook data. Labels per contract.

## Chain (write side — unchanged by this PR)

| Step | Anchor | What happens | Label |
|---|---|---|---|
| W1 | `app/api/project_runner.py:164` `run_project` | canonical engine run; OPEX economics computed by the engine from the effective inputs (folded lines + bases + drivers + B.13) | REPO_VERIFIED |
| W2 | `app/api/project_runner.py:355` | `_serialize_financial_statements(fs)` — the engine's `FinancialStatementsResult` P&L serialized read-only; per period: `operating_expenses_keur` = the engine's own all-in OPEX for that financial period (construction periods 0.0; partial operating years prorated by the engine's day_fraction) | REPO_VERIFIED |
| W3 | `app/persistence/workspace_repository.py` `v2_atomic_run_commit` | the payload, incl. `financial_statements_json`, is written into the append-only `model_run_history` row inside the same transaction that promotes Last Run (CAS, run-history append) | REPO_VERIFIED |
| W4 | `app/persistence/run_history_repository.py:184/338` | `prepare_run_history_payload` / `append_run_history_cursor` — canonical JSON, immutable row | REPO_VERIFIED |

## Chain (read side — what this PR adds)

| Step | Anchor | What happens | Label |
|---|---|---|---|
| R1 | `app/v2/react_opex_run_projection.py` `build_run_opex_projection` | `get_latest_history_entry(user_id, project_id)` → latest committed row; no Run ⇒ `status: NOT_RUN`, `run: null`, `periods: []` (never zeros) | REPO_VERIFIED (test: `test_g10_no_run_is_not_run_never_zero`) |
| R2 | same | freshness via `resolve_runtime_freshness(ws, current_composite_hash=assemble_consistent_for_get(...).composite_hash)` — CURRENT / STALE shown as-is | REPO_VERIFIED (test asserts CURRENT immediately after a Run) |
| R3 | same | `entry.financial_statements["pnl"]["periods"][*].operating_expenses_keur` passed through cell-by-cell; missing/NaN ⇒ `null`; missing P&L ⇒ `status: OPEX_STATEMENT_UNAVAILABLE` (typed, fail closed) | REPO_VERIFIED (pass-through equality test vs the persisted row) |
| R4 | `frontend/src/app/projection/OpexRunProjection.tsx` | read-only table; NOT_RUN/NOT_AVAILABLE rendered as explicit states; kEUR display via the approved `showKeur` convention; no browser arithmetic | REPO_VERIFIED (module has no writer surface; typecheck in build) |

## What the figure is — and is not

- **Is:** the committed Run's all-in OPEX per financial period, exactly as the engine computed it (lines + bases + drivers + B.13 as applied by the Run; construction 0.0; partial-year proration engine-owned). Period identity = the Run's own `period` index + `period end` date; calendar-year vs operating-year and partial-COD distinctions are carried by the persisted period dates and the basis string, not re-derived.
- **Is not:** the draft/working-copy projection (`react_opex_projection`, labeled "not a Run result"), U2's per-line Years view, a calendar-year sum, or any browser-computed aggregation. No scalar-base double counting is possible: nothing here sums bases with replacement lines — the engine's own cell is shown verbatim.

## Traceability to the G10 oracle

- T1-vs-T2 qualification honored: no test equates a persisted first-period value to a full-year figure; the pass-through test asserts equality to the **persisted evidence**, and the full-year T2 constants (380.0 / 411.324220800 / 553.588245560563; DC fixed 9700) are asserted only at the T2 tier on the factory inputs (SYNTHETIC_ONLY).
- D1–D6 divergences are not silently equated anywhere; the endpoint's basis string names the period semantics explicitly.
