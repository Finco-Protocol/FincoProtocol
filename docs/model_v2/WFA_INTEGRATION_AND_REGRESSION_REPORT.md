# WF-A integration and regression report

Base `origin/main` `03e2b9638e9324bb18ea8420ce8f9823f4f0a676` merged into the branch with a normal merge commit (no rebase, squash or force push).

## Boundary assertions
* `git diff origin/main -- financial_engine finco_core domain app templates static` is empty (asserted by `test_release_closed_features_and_engine_boundary_unchanged`; `app/v2/router.py` and `post_run_ui.py` untouched).
* No tolerance, golden, release pin or CI workflow changed. RC-UX Phase 2 owns PPA editing UX; no browser test duplicated.
* No private or external source material is present in the repository.

## Local results (exact run on this branch)
| Suite | Result |
|---|---|
| `tests/test_wfa_credit_validation.py` + `tests/test_wfa_impact_validation.py` | 48 passed |
| Regression ring: F3.9 (`test_f39_*`), P0-B3, numerical V1 synthetic, F3.5b numerical / release-closed, F3.7 instrument S&U, F4 P1 and workspace, Revenue V2 multistream / workspace / governance, WF05-WF07 integration | 330 passed |
| `tests/wfa_generate_reports.py` (opt-in) | matrices regenerated, 0 identity FAIL |

Mandatory CI is run once on the exact final head (see the PR); no extra CI cycle was spent on the addendum.

## Notes
* Data-center and EV stress coverage is reduced: most CAPEX/OPEX stresses on those verticals fail closed by the product's own integrity checks, so those cases are recorded as *fail-closed with typed reason*, not as validated (**FUNCTIONALLY EXECUTED — NUMERICAL VALIDATION INCOMPLETE** for stress behaviour; base identities are VALIDATED).
* The F3.9 identities were reused, not duplicated; WF-A adds `CR-*` (credit) and `FT-*` / `IV-*` / `RC-*` (impact) identities.
