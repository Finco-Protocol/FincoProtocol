# D-029 release-truth reconciliation (G01)

Scope: read-only truth report. It does **not** activate, disable, rewrite or approve D-029, and it does not edit any
existing D-029 document (those files are outside the authorized correction scope; the stale text is registered in
section 8 for an owner-authorized edit). Every statement below was checked against source at main
`6f10f3927b33a5715ac6313da200d0f96c023524` or against GitHub; anything not verifiable is marked **NOT VERIFIED**.

## 1. One-line truth

D-029 is **implemented, merged, and technically reachable by any client that submits a `run_intent_id`**. Both shipped
clients (React and Legacy/HTMX) submit one on every deliberate Run. The repository's D-029 documents still describe it as
"RELEASE CLOSED / nothing merged / `RELEASE_POLICY.enabled` is false"; that flag is **not read by any code path**, so it
is documentation of intent, not a control. No Financial Owner approval of the pending policies exists in the repository.

## 2. Status matrix

| Question | Answer | Evidence |
|---|---|---|
| Implemented | Yes | `app/services/run_intent_service.py`, `app/persistence/run_intent_repository.py`, route wiring in `app/v2/router.py` (`v2_workbook_run`, `if run_intent_id.strip():`, line 2999) |
| Merged | **Yes** — PR #384 merged into `main` 2026-10-26T20:27:27Z by the repository owner account `FincoProtocol`; merge commit `6c642adcd193691818f1413bf5273885470c8ef9` (parents `36edeeb5…`, `e49dff36…`) | GitHub `pull_request_read` #384: `state=closed, merged=true`; `git cat-file -p 6c642ad` |
| Runtime behaviour | A request **with** `run_intent_id` runs the full lifecycle (validate → protected-reference refusal → ledger lookup → reserve → engine → atomic commit). A request **without** one is the released non-idempotent path | `v2_workbook_run`; `run_intent_service.decide` |
| Controlled by `RELEASE_POLICY.enabled`? | **No.** `RELEASE_POLICY = RunIntentPolicy()` has `enabled=False`, but `grep -rn "RELEASE_POLICY\|\.enabled"` finds no reader of it. It is not a route kill switch | `app/services/run_intent_service.py:36-44`; repository-wide grep |
| React client | Sends a UUIDv4 on every deliberate Run; resumes with the original binding | `frontend/src/app/runIntent.ts`, `api.ts`, `workflow/WorkflowBar.tsx`; Chromium cases `test_d029_react_run_intent_acceptance` (4) |
| Legacy client | Sends one id across queue / lost response / OOB / reload | `static/js/workbook_v2.js`; Chromium cases for Legacy (3) |
| Owner approval in repository | **None for the policies.** Only an authorization to touch pinned paths, "relayed in the PR thread" and recorded as *relayed, not verified* | `docs/model_v2/d029/D029_EXECUTIVE_REVIEW.md` ("Open items" 3); `tests/model_mutation_security_successor.py` D-029 comment |
| Activated / deployed | **NOT VERIFIED.** Nothing in the repository proves what `app.finco.one` runs; no SSH evidence was available to this workflow | see `REACT_PILOT_DEPLOYMENT_READINESS.md` |
| Missing approval records | Every row of `D029_OWNER_DECISION_REGISTER.md` is `PENDING` (12 rows) | that register |
| Retention / cleanup | No automatic deletion; a DB trigger (`model_run_intents_no_delete`) refuses DELETE; inventoried as `data.run_intents` in trust-readiness. **No retention period or tombstone policy is approved.** The ledger therefore grows without bound | `run_intent_repository.py` lines 130-150; `trust_readiness/registry.py:622` |
| Expiry / recovery | Lease = (900+120) s. An expired active attempt returns typed `EXPIRED` and fails closed. `recover()` exists but **no route calls it** (`grep "recover("` finds only the definition). So an expired intent stays expired until an owner-approved recovery path exists | `run_intent_service.py` (`LEASE_MS`, `_decide_existing`); `run_intent_repository.recover` |
| Shared-project actor / key space | Ledger `actor_id` is the workspace **owner**, not the signed-in user: collaborators on a shared project share the owner's key space (a key submitted by one collaborator is visible as replay to another). Documented trade-off, not approved | `v2_workbook_run` `actor_id=workspace_owner`; register row "Ledger actor for shared projects" |
| Security / availability restrictions that remain | (a) An intent id is never authorization: auth → project → ownership → Run CSRF precede the ledger; protected references never reach it. (b) A corrupted ledger schema raises `RUN_INTENT_SCHEMA_INVALID` at startup and on every ledger call, so the application **refuses to start** until repaired (availability vs strictness trade-off, unapproved). (c) Failed attempts are terminal per key (new key needed). (d) In-progress returns immediately (409); no waiting | `D029_SECURITY_AND_CAS_ORDERING.md`; `run_intent_repository.py:174-205` |

## 3. What "release closed" can and cannot mean today

* It cannot mean "the route is off": the route engages whenever a key is posted, and both clients post one.
* It can still mean "the owner has not approved the policy decisions" — true, and unchanged.
* The honest product statement is: *Run retry protection (D-029) is built and in use by the browser clients; its owner
  policies (retention, recovery of expired runs, key scope on shared projects, strictness on a damaged ledger) are
  pending decisions.* The React workspace does not currently state any of this to users; it only shows the typed Run
  outcomes (COMMITTED / REPLAYED / IN_PROGRESS / FAILED / UNKNOWN …). No product copy in this PR claims D-029 is
  approved or released.

## 4. Decisions only the Financial Owner can take (none taken here)

1. Keep the browser clients sending keys (current reality) **or** gate them behind a real, tested switch. A real switch
   needs a router change (`app/v2/router.py`, owned by Overnight A) plus the pinned-source successor layer.
2. Retention period / tombstone policy for `model_run_intents`.
3. Recovery policy for expired attempts (and whether `recover()` is routed).
4. Collaborator key space on shared projects (owner vs per-user actor).
5. Startup behaviour on a damaged ledger (fail the whole app vs degrade to keyless Runs).
6. Whether D-029 documentation should be rewritten to the post-merge truth (see section 8).

## 5. What this PR does about D-029

Nothing functional. The React workspace is unchanged in how it Runs, sends keys, resumes or reconciles. The seven D-029
Chromium cases (`test_d029_react_run_intent_acceptance` ×4, legacy ×3) are executed unchanged in this PR's browser run
(results in `REACT_BROWSER_ACCEPTANCE.md`). One of them,
`test_d029_react_run_intent_acceptance[check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit]`, failed once in an
ordered full-file run on **unmodified main** (`Page.wait_for_function: … reading 'disabled'` on the Run button) and
passed 4/4 when run alone on the same tree; that is a pre-existing ordering race in the test helper, recorded, not
introduced or hidden here.

## 6. PPA-01 and multi-senior release-gate discrepancies (for a *separate* owner decision)

This workflow does not change those financial products. Observations only, from repository text:

* **PPA-01 (contractual PPA indexation / rounding).** Code and tests are present on main (`domain/revenue/revenue_config.py`,
  `tests/test_ppa01_*`, `tests/rc3_authority_states.py` lists an `INTEGRATED_RELEASE_CLOSED_CANDIDATE` state, and
  `tests/test_ppa01_post_merge_authority.py` pins a merged-main identity). The governing documents say the owner approved
  *scope* but exact-content acceptance is **pending** ("NOT a release approval",
  `docs/model_v2/PPA01_FINANCIAL_AUTHORITY_SUCCESSOR_PROPOSAL.md`; "NOT APPROVED",
  `PPA01_CONTRACTUAL_INDEXATION_CANDIDATE_REPORT.md`). Discrepancy to resolve: merged code with a documented
  not-yet-approved release state — what is the intended product status of PPA-01 in the pilot, and is the React PPA contract
  editor allowed to expose it?
* **Multi-senior (two-Senior financing).** `debt.financing.instruments` ("Two-Senior configuration") exists in the workbook
  registry; the F3 acceptance report states financial and browser gates must pass *before activation is released* and that
  independent financial review is required ("restricted working vertical slice … not a claim that all F3 roadmap financing
  modes are complete"). The React Financing section shows the field **read-only** with a pointer to the legacy editor.
  Discrepancy to resolve: whether two-Senior is in or out of the pilot scope, so that React copy and pilot documentation
  agree. This PR leaves the field read-only and unchanged.
* Related (not a discrepancy but a pilot caveat): V11 Stage 3 / V10 are covered by a separate Financial Owner release
  decision (`docs/model_v11/FINANCIAL_OWNER_RELEASE_DECISION_2026-10-24_V11_STAGE3.md`); it is not touched here.

## 7. Evidence not available to this workflow

* Live `app.finco.one` / staging state, environment values, database contents (no SSH, no deployment records).
* Branch-protection settings (HTTP 403 for the integration token, same as noted in `docs/react_migration/MAIN_INTEGRATION_V1.md`).
* Any Financial Owner statement approving D-029 policies.

## 8. Stale pre-merge descriptive text (registered, **not edited**)

Edit only with explicit authorization for these exact files; each is factually superseded by the merge:

| File | Text | Why stale |
|---|---|---|
| `docs/model_v2/d029/*.md` (10 files; e.g. `D029_EXECUTIVE_REVIEW.md:49-53`, `D029_OWNER_DECISION_REGISTER.md:25-29`) | "Status boundary … nothing is deployed **or merged**" | PR #384 is merged. "Not deployed/activated" cannot be proven either way from the repository |
| `D029_EXECUTIVE_REVIEW.md:33` and `:39-42` | wrappers "no (see Open items)", "local evidence, not CI evidence. Prepared patch is not applied" | The seven wrappers are in `tests/test_model_workspace_consolidation_browser.py` on main and ran in the mandatory browser role (PR #384 body: exact-head CI green incl. 7 D-029 Chromium cases) |
| `D029_EXECUTIVE_REVIEW.md:3` | "READY_FOR_INDEPENDENT_REVIEW" | Review/merge already happened |
| `D029_OWNER_DECISION_REGISTER.md:3` | "The feature remains release-closed" | Accurate only for *owner approval*; inaccurate as a runtime description (section 2) |
| `app/services/run_intent_service.py:8-11,35-37` (module docstring / comment) | "only engaged when a caller submits a `run_intent_id` … Enabling is intentionally not an environment variable" | Accurate, but `RELEASE_POLICY.enabled` reads like a switch and is unused |
| PR #384 title on GitHub | "durable Run intent ledger and fencing foundation" | Narrower than the merged scope (full route integration + both clients) |

Do **not** read this table as a claim that any policy was approved.
