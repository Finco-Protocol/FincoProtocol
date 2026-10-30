# PR #403 exact-source governance decision (2026-10-30) - status `BLOCKED_SOURCE_GOVERNANCE`

## Exact refs (GitHub, read 2026-10-30 ~14:50Z; heads move, re-read before use)
| Ref | SHA / tree |
|---|---|
| main | `db504f6408cb456c617c9342a1ffa202ee455283`, tree `9b96717bae39a4dbb496879c7e6c028e675492d3` |
| #403 head | `da783b35f8dbd98c011cba00889e22283b30a88b`, tree `5f91ae22ec79182c7cec71cdaec961b326b301cf`; single commit; merge-base = main; diff vs main = 57 added files, all under `research/on07_*` (11 + 46), +105,084 lines, **zero** changes to any other path |
| #400 | Draft, head `e66b734685c78da96326ab3e535d310efab6d7a3` at last read (sixth distinct head today); not touched |
| #402 | Draft, `9e776252086a28e8bd295c155903cc07b221784b`, BLOCKED_EXACT_SCOPE; not touched |
CI at #403 `da783b35` (run ids 41042817xxx): browser evidence, Governance Full History, Security, Compile, dependency audit PASS; F01 `41042817474` FAIL; Public Safety eight-worker `41042817438` worker 0 PASS, workers 1-7 FAIL, aggregate + mandatory-evidence FAIL.

## Root cause - proven, not assumed
The failures are **not** an ON-07 regression and **not** a `research/`-specific allowlist gap. The repository's exact-source governance is a **closed world over changed paths**:
1. `tests/fin_v2_cohorts.py::valid()` requires every path changed since the accepted parent `f79e2519...` to be allowed (`allowed_path`) by at least one registered cohort; `tests/wf04_scope.py::exact_blobs_ok` (and `wsv2_core_scope`) additionally reject any path changed since their `APPROVED_MAIN` that is not in the cohort's `OWNED_PATHS`/manifest.
2. `tests/finval_f01_scope.py::valid()` falls back to `fin_v2_cohorts.matches` for the five F01-pinned files whose current main blobs are cohort successors; when the composite is invalid, that fallback returns False, so F01 scope, fixture-integrity and rate-successor fail.
**Experiments (isolated worktrees, never pushed):**
- On #403's tree: 57 changed paths rejected by all 9 cohorts; `wsv2_core_scope` and `wf04_scope` `exact_blobs_ok` False; composite and F01 scope False. Protected source blobs are byte-identical to main.
- On unmodified main: all True. On main + **one** harmless file at `research/probe/one.txt`, `docs/probe_note.md` or the repo-root `PROBE_NOTE.md`: identical result (the same two cohorts fail; composite and F01 invalid). Path location is irrelevant.
- Guard-dependent suite (23 modules, 1,392 tests, `governance_probe/`): unmodified main 1,382 pass / 6 fail / 4 error; main + one harmless file 1,167 pass / 221 fail / 4 error. **215 tests newly fail** (65 `fin_v2_3_scope`, 27 `wf04_scope`, 23 `fin_v2_r1_scope`, 23 `fin_v2_wsv2_scope`, 22 `fin_v2_rcux_scope`, 18 `fin_v2_d01_scope`, 9 `wsv2_core_scope`, 6 `fin_v2_pr394_corr_scope`, 6 `model_mutation_security_successor`, 5 `fin_v2_ci_scope`, 3 `rcux_governance`, 2 `overnight_b_governance`, 1 each `finv2_d01_governance`, `rcm_governance`, `model_workspace_productivity_v1` and the three F01 modules named in CI). The 10 failures present on unmodified main in this local environment (`FAILING_ON_UNMODIFIED_MAIN_LOCAL_ENV.txt`; hosted CI passes them on main) are identical with and without the file and are excluded from the 215.
Limits of this proof: the seven failed-worker native XMLs (CI artifacts) could not be downloaded with the available tools; the CI log tails retrieved contain only artifact-upload lines. The local reproduction covers the same guard family and the three F01 modules named in the CI failure; it does not itemise each worker's ~40 failures. "Why #403 specifically" is therefore proven for the mechanism, not worker-by-worker.

## Consequences
- No change to a `research/` file can green these checks; only an admitted cohort/successor that lists the new paths can. That means editing `tests/fin_v2_cohorts.py` (registration), a new cohort module and manifest - protected governance code. This study does **not** do that (no historic pin, F01 validator, source manifest, `.github/` or financial/security test is edited).
- Post-#400 (not testable now): #400's finite successor manifest admits its own owned paths only; nothing indicates it would admit `research/**`. Re-test after #400 genuinely merges, with no product edits; do not merge #400 Draft into #403.
- Shipping option (preferred if this is hand-over data only): distribute `FINCO_ON07_RESEARCH_DELIVERABLE_2026-10-30.zip` (portable `research/on07_*` + SHA256 manifest + this report) without merging #403.

## Owner decision packet (no action taken)
| ID | Decision | Recommendation |
|---|---|---|
| G-1 | Keep #403 Draft/BLOCKED and distribute the ZIP only | **recommended** (data handover, no governance change) |
| G-2 | Authorise a finite, append-only research-admission cohort with independent review | only if repository history of research artefacts is required; touches protected governance, needs its own PR/owner approval |
| G-3 | Close #403 | owner decision only; not done here |
Financial open items remain in `OWNER_DECISION_REGISTER.md` (OD-1..OD-7). OD-1 (SHL index policy) is a later financially-authorised project; nothing in `financial_engine/`, `finco_core/`, `app/input_adapter.py` or `app/generic_shl_policy.py` is touched here.
