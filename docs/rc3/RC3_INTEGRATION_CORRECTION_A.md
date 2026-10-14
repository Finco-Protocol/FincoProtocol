# RC-3 integration - Correction A (PR #284)

Status: **REVIEW PROPOSAL. NOTHING HERE IS A FINANCIAL APPROVAL. M7 `release_approved:false`, `ACTIVATION_ENABLED = False`.**

Base `main` `6fc77de98bc0562fb51efdbf96e1803a29b5b148`. Sources (merge order): #280 `8378e5d`, #279 `9f93dc8`, #281 `5c69638`,
#282 `63f1ded`, #283 `62424a8`. Ancestry and ordered `--no-ff` merges are proven by `tests/test_rc3_integration_inventory.py`.

## 1. Two different questions

| Question | Where it is answered | State |
| --- | --- | --- |
| **Historical stream scope** - did an original stream (Crypto, Radar R4/R5, Opus, Staging, P-series, cost templates, M3 ...) change financial authority? | The stream's own zero-diff guards, now evaluated at the immutable pre-M7 integration tip `f2a1e38` through `tests/rc3_historical_anchor.py`. The anchor falls back to plain `HEAD` on any uncertainty and permanently once `f2a1e38` is contained in `origin/main`. | Green, and meaningful: `f2a1e38` changes no frozen namespace (asserted in the inventory). |
| **Current integration authority** - are the M7 financial changes independently accepted and exactly protected? | (a) The owner gates, unchanged and still red: `tests/test_finance_integrity_governance.py` (3), `tests/test_wf07_revenue_governance.py` (3), `tests/test_ci_acceptance.py::test_frozen_financial_namespaces_unmodified`. (b) `tests/test_rc3_integration_inventory.py`: exact paths and exact blobs of every frozen-namespace change, the eleven manifest blobs, protected workflows/selection/tolerances/goldens, closed flags. | (a) **red = approval required**; (b) green = content is bound, not approved. |

No central governance file or release pin map was edited (`tests/model_v2_governance.py`, `tests/finance_integrity_governance.py`
and every `*_AUTHORITIES` map are byte-identical to `main`). No M7 blob was registered as approved.

## 2. Re-anchored historical guards (technical regressions, not approvals)

crypto roadmap, Data Center A3.1 (2), P1.3 (2), P0a, P3, public product truth (2), staging product truth (2), tokenized markets (2),
cost templates (2, via `branch_side_only`), revenue runtime parity, M3 two-driver, Radar R4, Radar R5. Each keeps its assertion
unchanged and only changes which commit the diff is taken to.

## 3. Shared-file resolutions

Auto-merged (independently re-derived with `git merge-file` in the inventory): `app/api/project_runner.py` (M6 acquisition evidence +
M7 `bess_operating_audit`), `app/v2/router.py` (M6 Run binding + M7 routers), `app/templates/v2/workbook.html` (Diagnostics V2 + BESS
assets). Hand-resolved (reviewed literal pins + markers): `tests/test_rc2_integration_manifest.py` (anchored historical verifier from
#280; #279's duplicate-status rule; R4 successor anchored to its head), `tests/test_trust_readiness_controls.py` and
`tests/test_trust_readiness_registry.py` (both the M6 and the M7 exact-content successor must hold).

## 4. M7 financial candidate - evidence for the independent reviewer

Eleven protected blobs in `docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json` are pinned by the inventory. Executable evidence
(local, Python 3.12; counts in the PR description): physical-to-financial settlement, signed revenue/OPEX/EBITDA/CFADS, canonical
cash tax and depreciation, senior financing and coverage, project and sponsor IRR, Run Integrity, legacy Storage admission boundary,
CSRF/ownership/CAS and committed Run semantics (`tests/test_m7_bess_*`), Solar/Wind/DC/EV invariants (`test_perf_model_runtime_v2`,
`test_ev_charging_*`, `test_model_v2_revenue_runtime_parity`).

**Unresolved approvals (what is still needed):**
1. An independent financial acceptance of the exact eleven M7 blobs. Until one is cited, the owner gates above remain red.
2. Separate production-activation approval for BESS (`ACTIVATION_ENABLED`), M6, Junior and Revenue V3 - all stay closed.
3. Independent review of the hand-resolved governance files and of the two self-referencing files that cannot pin themselves
   (`tests/test_rc3_integration_inventory.py`, `tests/rc3_historical_anchor.py`).
