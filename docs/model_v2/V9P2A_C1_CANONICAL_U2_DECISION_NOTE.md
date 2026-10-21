# Financial Owner decision note — C-1: canonical U2 cash-reserve + distribution-accounting waterfall mismatch

**Separate from OD-R. Nothing implemented. Decision requested.**

## Finding (reproduced on canonical code, real engine)

Configuration: `reference-wind` with `cash_reserve_interest_policy.enabled` **and** `distribution_accounting_policy.enabled`.

* The canonical waterfall returns the final U2 re-run financing (`_financing2`), not the financing whose gated SHL schedule
  was evaluated: 22 financing evaluations and 16 gated SHL schedules in one Run.
* The returned waterfall SHL rows match **none** of the 16 evaluated gated schedules; the difference is ≈ 11,670 kEUR, i.e.
  the entire SHL balance.
* Returned vs last-checked financing: SHL principal and Senior commitment identical; cash available for SHL differs by
  1.8e-8 kEUR.
* Run Integrity: **FAIL** (`SPONSOR_RETURN_INPUTS_RECONCILE`). `run_clean_production` still returns the result.

## Reachability (verified)

* No product factory, workbook field or `app/` module sets either policy.
* `finco_core.inputs.serialization.project_inputs_to_dict` does **not** serialise either policy; a persisted or imported
  project round-trips both to `None`. No persisted, imported, workbook or API Run can reach C-1 today.
* Reachable only by code constructing `ProjectInputs` in-process (tests, research tools).

The defect is real and economically material when triggered, but **latent** in the product today. It becomes a production
P1 the moment either policy is exposed through serialization, import or the workbook.

## Options

**A. Fail-closed admission restriction (recommended near term).** Refuse, at the production financial authority and before
any engine work, any project with both policies enabled (typed `CleanNotReady`/fail-closed reason), with a test that the
restriction cannot be bypassed by scenario overrides. Small, reviewable, no financial calculation change, prevents silent
exposure if serialization is ever extended. Under OD-R this configuration is already refused
(`ODR_UNSUPPORTED_FINANCING`).

**B. Full canonical U2 / waterfall reconciliation.** Recompute the gated SHL schedule (and dependent sponsor flows) for the
financing actually returned by the U2 final pass, prove Integrity PASS and statement / return reconciliation, in a
separately governed financial PR with its own exact-content approval. Required before the policies are ever productised.

## Recommendation

Adopt **A** now as a release gate (cheap, removes the latent exposure); schedule **B** only if cash-reserve interest with
distribution accounting is intended to become a product feature. Neither is implemented without separate authorisation.
