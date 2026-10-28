# Prompt for the next agent (paste as the first message)

You are continuing **FINCO — RC-UX Completion V1** (including **Addendum A: React-only navigation** and **Addendum B: product-facing UX**) in `Finco-Protocol/FincoProtocol`.
Work ONLY on the existing integration branch `integration/rc-ux-completion-v1` / draft PR **#394**. Do not open another PR. No self-approval, no merge to main, no deploy, no feature activation, no force-push, no rebase of this branch.

Start by reading, in this order, from the branch:
1. `docs/react_migration/rc_ux_completion/handover/HANDOVER.md` (state, architecture, rules, pitfalls)
2. `docs/react_migration/rc_ux_completion/handover/REMAINING_WORK.md` (ordered plan)
3. `docs/react_migration/rc_ux_completion/RC_UX_MASTER_GAP_REGISTER.csv` (stale statuses — HANDOVER §5 has the true ones) and `audit_inputs/` (Audit A GAP-R1…R28, Audit B F01–F06/G01/U01–U03 are the source of truth)
4. `06_ADDENDUM_B_PRODUCT_UX.md`, `01_PREFLIGHT.md`, `03_FINANCIAL_DEPENDENCY_MAP.md`

Immediate steps:
1. Clone/fetch the repo, check out the branch (head should be ≥ `2a49d51`). Install with `pip install -c constraints.txt -r requirements*.txt` and `cd frontend && npm ci`.
2. `main` moved to `70bcf69` (FIN-V2 Integration RC) and PR #394 is conflicted. **Merge `origin/main` into the branch** (merge commit), resolve the three governance-test conflicts keeping both sides' pins, rebuild the bundle (`npm run build`, copy `dist/finco-react.{js,css}` to `static/react/`), run `handover/tools/refresh_pins.py`, rerun the governance suites. Commit and push.
3. Finish and verify the Excel/CSV import adapter/UI (HANDOVER §4), then triage the full browser role (`tests/test_model_workspace_consolidation_browser.py`).
4. Execute Addendum A (navigation map + React Trust view + the navigation browser test rejecting staging and same-host Legacy routes), then the remaining audit gaps in REMAINING_WORK.md.
5. After each checkpoint: COMMIT → PUSH → UPDATE PR #394 body; watch GitHub Actions on the exact head and fix failures on the same PR.

Hard rules: never edit `financial_engine/`, `finco_core/`, `app/api/project_runner.py`, `app/input_adapter.py`, `app/v2/router.py`, `app/workbook/*`, `app/capex_profiles/*`, `app/export/*` (and treat FIN-V2 files merged from main as read-only); no financial arithmetic or duplicated logic in the frontend; preserve CSRF, composite-hash CAS, Save≠Run and immutable Run history; never skip/weaken/quarantine a protected test; governance changes only as narrow exact successors (`RC_UX_SUCCESSORS` + `test_rcux_governance.py`); previews are never Runs; unavailable ≠ zero; no Legacy fallback may close an audit gap. Do not edit the pinned CSRF adapters `react_new_project.py` / `react_goal_seek.py`.

Report honestly: if tests fail, say so with output. Finish with the line `READY FOR INDEPENDENT CHATGPT REVIEW — NO SELF-MERGE` ONLY when every definition-of-done condition in REMAINING_WORK.md holds; otherwise list the remaining gaps.
