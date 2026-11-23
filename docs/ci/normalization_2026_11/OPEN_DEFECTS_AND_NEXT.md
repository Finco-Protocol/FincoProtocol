# Open defects, findings and next steps (CI normalization, 2026-11-23)

## Blockers that need the owner (no agent permission)

| # | Blocker | Evidence | Owner action |
|---|---|---|---|
| B1 | Branch protection on Model `main` cannot be read or changed by the agent token | `GET /repos/Finco-Protocol/FincoProtocol/branches/main/protection` → 403 "Resource not accessible by integration" | Follow `CI_CUTOVER_AND_ROLLBACK.md` steps 1–7 (switch required check to `required`, review + merge Finco-Protocol/FincoProtocol#476) |
| B2 | **Radar Actions never start**: every Radar run since the repository was created fails in ~2 s with no runner (`runner_id 0`, steps `[]`) | Check-run annotation on job 137305019146 (run 45053968953): *"The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings"*. Radar is a **private** repo (Actions minutes are billed); Model is public (free) and runs normally | Organization **Finco-Protocol → Settings → Billing and plans**: fix the payment method or raise the Actions spending limit (or make Radar public). Then re-run the Radar PR #1 workflow (Actions → Radar Independent CI & Release Gate → Re-run all jobs) |
| B3 | Tag `ci-governance-v4-final` could not be pushed (agent git proxy refuses tag pushes) | push error "unexpected disconnect" for refs/tags only; branch pushes succeed | Optional: `git tag -a ci-governance-v4-final 707e68b2 -m "last CI V4/V5 main" && git push origin ci-governance-v4-final` |

## Known baseline defects (deselected from required groups, red in `model_known_defects.yml`)

`tests/known_defects.txt`, 26 nodes, each failing identically on accepted main `707e68b2` with Playwright 1.63.0 / Chromium 157:

* 10 legacy-workbook / Radar browser tests (cost batch/grid stage toggle and CSRF-less scenario POST, data-center HTMX
  KPIs and navigation, golden flows A/B/C hidden tabs, Radar N04 refresh button).
* 16 nodes of browser roles that had never run on hosted CI (only in the parked V5 candidate): U1 (10), U2 (2) and
  WF-06B (4) — 404 assets / superseded layouts after later UX PRs.

Each needs a product decision: either the UI regressed (fix the product, separate PR + review) or the harness is
stale (update the test against the current, reviewed UI). Removing a line is part of the fixing PR.

## Findings from the negative-control matrix (`NEGATIVE_MATRIX.csv`)

* **Finance coverage gap (N01, N01b):** dropping SHL interest from `PeriodInterest.total_interest_keur` and scaling
  `senior_debt/interest.py` by 1.01 were **not** detected by the F01 / rate-contract / FIN-V2.3 contract modules
  (CFADS +1 % was detected, N01c). Full-suite detection was not measured. Recommend adding an exact, independent
  golden case with non-zero SHL interest and a senior-interest identity check to the Fable finance backlog (no
  change to financial policy in this CI task).
* **Forged same-named check (N12):** GitHub matches required checks by name; a PR could add a workflow with a job
  named `required`. Mitigated by CODEOWNERS on `.github/` (owner review) and by the genuine `required` still failing;
  fully closed only by organization-level required workflows/rulesets (plan-dependent).
* `test_ci_v4_p0_scope::test_forged_source_manifest_is_rejected[pin]` (FINCO33 potential weakness): the manifest
  admission it guarded no longer exists; no replacement needed beyond CODEOWNERS + required `Model CI / required`.

## Test-harness defects fixed in this PR

* `tests/test_f08_opex_mobile_ux.py` set `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` process-wide (an agent sandbox
  path), breaking every later Chromium launch in the same pytest process; `tests/test_model_trust_pack_browser.py`
  hard-coded that executable. Both now use the Playwright-managed browser unless the local path exists.
* `tests/test_project_lifecycle_browser.py` (fixture-only) is collected normally (0 nodes, no error) — the FINCO33
  shard-1 abort cannot recur.

## Next (in order)

1. Owner: B1 cutover (merge #476), B2 Radar billing.
2. #475: merge new `main` into `arch/radar-service-boundary-20261122` (prepared locally: normalization tree + exactly
   the 5 boundary files; Correction E and the m2b successor cohort dropped as obsolete), hosted Model CI green, owner
   review, merge.
3. Radar #1: hosted gate green after B2 (local isolated-wheel gate at `4655bc3`: 1225/1225 passed), merge after #475.
4. Known defects triage (26 nodes), finance coverage gap (above).
5. Product roadmap resumes: #462 security exposure review first, then #463/#464, Fable P1 items, R04, React #446.
