# P00 baseline receipt — WS-2 Editing & Save All

Recorded 2026-10-28 from the live repository, not from an agent report.

| Fact | Value |
|---|---|
| Repository | `Finco-Protocol/FincoProtocol` |
| `main` HEAD | `b1a58681e41af9f1b4d52b176f0001725720b15c` (Merge PR #396), 2026-10-28T12:46+01:00 |
| `main` tree | `d86732d7b7e187d14e01be5f0b65c663feeca8bd` |
| Working branch | `claude/new-session-85uo4c` (the branch this session is bound to; the assignment's suggested name was not used) |
| Merge base with `main` | `b1a58681…` (branch started at `main` HEAD, 0 ahead / 0 behind before this work) |
| Merged inputs | #394 (RC-UX Completion V1) and #396 (staging F1–F10) — both merged, confirmed |
| WS-1 (GPT-6) PR | **None open at check time.** No overlap exists yet; the interface contract is published here first. |
| Other open PRs | #328 #327 #324 #322 #321 #318 #184 (model performance / RC-7 / yield drafts) and dependabot bumps. None touches `frontend/src/app/{editing,workflow,capex}` or the CAPEX/OPEX/PPA editors. #318 (RC-7 integration) is large and touches financial source; not an overlap with this PR's files. |
| Exact-head CI | This PR's own exact-head CI is reported in the PR, not here. `main` is at the merge of #396. |

## Source facts that decide the design

* `app/` is a **protected exact-source tree** (`tests/fin_v2_rcux_scope.py::PROTECTED`). Any added/changed file under `app/` fails closed unless an Owner-authorised cohort pins its blob. `frontend/src/**/*.{ts,tsx,css,mjs}` and RC-UX docs are admitted by pattern.
* Four independent canonical writers exist, each with its own transaction and CSRF contract (`SAVE_ALL_TRANSACTION_DESIGN.md`). **No endpoint writes more than one section atomically.**
* Each writer opens its own connection and `BEGIN EXCLUSIVE`; none accepts an outer cursor. Composing them in one transaction therefore requires editing protected persistence sources.
* The pinned browser acceptance modules (`tests/model_react_wf2_browser_acceptance.py`, `tests/model_react_mvp_acceptance.py`) fill PPA fields with the old decimal-ratio UI ("Contracted volume share" = `0.8`). They are byte-pinned and are not edited here; see `WSV2_GAP_COVERAGE_SONNET.md` §Known follow-ups.

## Not verified here

Live browser acceptance on `app.finco.one` / staging, SSH/deployment state and release flags were not accessible from this session; nothing in this PR claims them.
