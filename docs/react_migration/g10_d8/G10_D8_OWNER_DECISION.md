# G10_D8_OWNER_DECISION.md — what is built, what is gated, what needs ratification

**Draft status: built behind clear labels; NOTHING here ratifies a financial interpretation.** The two implemented behaviors follow the *recommended* options from the accepted G10/D8 research, and remain reversible without touching signed-Run economics.

## G10 — Option A (implemented, read-only, draft)

- New read-only adapter `GET /v2/model-react/opex-run-projection` (own module `app/v2/react_opex_run_projection.py`, registered in the U2-marked section of `react_workspace_router.py`).
- Reads ONLY the committed immutable Run (`model_run_history`): the engine's own per-period `operating_expenses_keur` cells, with run identity, scenario label (as persisted — never guessed), engine/workbook versions, and the runtime-authority freshness verdict (CURRENT/STALE).
- States: no Run ⇒ `NOT_RUN` (never zeros); row without a P&L ⇒ `OPEX_STATEMENT_UNAVAILABLE`; adapter failure ⇒ 503 typed `OPEX_RUN_PROJECTION_UNAVAILABLE`. No sums, no draft mixing, no calendar-year reconstruction.
- UI: "Last Run — all-in OPEX by period" panel in Inputs › OPEX › Years view, below the existing projection and per-line years panels; explicit basis string distinguishes Run economics from the draft projection.
- **Owner decision still open:** ratify Option A as the product behavior (and its basis wording), or choose B/C. Option B (engine-owned preview) remains unimplemented by design — it requires the signed consumption-rule contract from the oracle spec §7.

## D8 — Option 1 (implemented as copy truth; no new input)

- No project-wide OPEX escalation input was added; engine treatment of line inflation / step changes / factory 2% / 0% user-line default / seeded scalar displacement / DC & EV driver rows is untouched (no engine diff in this PR).
- The false copy "The base amount follows **the project's OPEX escalation**" (CostLinesGridView base rows) is replaced by the truthful statement: no project-wide input exists; each base escalates at its factory item's own yearly rate (2% on solar/wind items; driver-derived rows at their driver rate); the projection lists each row's rate.
- `CostLineManager`'s existing correct copy ("A new line starts at 0 % inflation: no project-wide OPEX escalation is saved…") is pinned by test and unchanged.
- Rate-source labels beyond this (per-base "factory rate / driver / flat-2% convention" chips) are Option-3 display work, deliberately NOT built here — needs owner wording approval (display contract).
- **Owner decision still open:** ratify Option 1 (recommended), or choose Option 2 (global default — requires a signed precedence chain + no-op-sentinel migration; +20.3660492275% Y20 materiality at 3% on solar) or the Option-3 display slice.

## Explicitly NOT done (blocked / out of scope)

- No Excel parity claim of any kind (UNSUPPORTED until the independent oracle runs on authenticated Runs).
- No BESS/storage OPEX claims (gated feature).
- No change to `save_all_commands.py`, R1 files, CI workflows (incl. CI V4), CAPEX writers, engine, schema.
- No frontend financial arithmetic (the panel renders server numbers only).

## Sign-off checklist for the owner

1. Ratify/adjust G10 Option A basis wording (period semantics sentence).
2. Ratify/adjust the D8 base-row tooltip wording.
3. Decide whether the panel ships enabled or behind a flag at merge time (it is behind the existing `FINCO_MODEL_REACT_V1` React-surface flag today, like the rest of the React workspace).
