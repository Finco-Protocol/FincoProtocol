# Financial Owner decision note — C-1: canonical U2 cash-reserve + distribution-accounting waterfall mismatch

**Separate from OD-R. Nothing implemented. Option A is a recommendation, not an authorisation.**

## Finding (canonical code, real engine, reproducible: `scripts/u2probe.py` in the review package)

`reference-wind` with `cash_reserve_interest_policy.enabled` **and** `distribution_accounting_policy.enabled`:

* the canonical waterfall returns the final U2 re-run financing, not the financing whose gated SHL schedule was evaluated
  (22 financing evaluations, 16 gated SHL schedules in one Run);
* the returned waterfall SHL rows match **none** of the 16 evaluated schedules — difference ≈ 11,670 kEUR (the entire SHL
  balance); returned vs last-checked financing: identical SHL principal and Senior commitment, cash for SHL Δ 1.8e-8 kEUR;
* Run Integrity **FAIL** (`SPONSOR_RETURN_INPUTS_RECONCILE`), yet `run_clean_production` returns the result.

## Reachability boundary

Verified (no product path reaches C-1 today):

* no `app/`, `main_web.py`, `main_api.py`, `main_mcp.py` or `finco_app` module references either policy;
* no product factory or workbook field sets them; scenario overrides do not touch them;
* `finco_core.inputs.serialization` does not serialise them: a persisted or imported project (`project_inputs_to_dict` /
  `project_inputs_from_dict`) round-trips both to `None` (verified).

Not verified / residual exposure:

* any in-process caller constructing `ProjectInputs` directly (tests, research tools, future integrations);
* any future change that adds the policies to serialization, import or the workbook — C-1 then becomes a production P1.

Under OD-R this configuration is already refused (`ODR_UNSUPPORTED_FINANCING`).

## Options

**A — Fail-closed admission restriction (recommended near term).** Refuse, at the production financial authority and
before any engine work, a project with both policies enabled (typed fail-closed reason, not bypassable by scenario
overrides). No financial calculation change; removes the latent exposure.

**B — Full canonical U2 / waterfall reconciliation.** Recompute the gated SHL schedule and dependent sponsor flows for the
financing actually returned by the U2 final pass, prove Integrity PASS and statement / return reconciliation, in a separately
governed financial PR with its own exact-content approval. Required before these policies are ever productised.

**Recommendation:** A now as a release gate; B only if cash-reserve interest with distribution accounting is to become a
product feature. Neither is implemented without separate authorisation.
