# React pilot deployment readiness package — `app.finco.one` (READ-ONLY, NO DEPLOY)

Nothing in this workflow restarts a service, changes an environment variable, migrates a database or deploys. No SSH
access was available, so **nothing below claims to have verified the live server**. "Repo" means verified from files in
this repository; "NOT VERIFIED" means it needs someone with server access to check it.

## 1. Pinned deployment identity

| Item | Value |
|---|---|
| Baseline main at start | `6f10f3927b33a5715ac6313da200d0f96c023524`, tree `62e70c3bfda7a91280c8c16acc89eeef9f780d6b` |
| Deployment SHA | **The merge commit of the independently approved PR** (not this branch head). Record it as a 40-character SHA; deploy that, never a branch name |
| Bundle identity (this PR) | see `REACT_FINAL_PR_CI_REPORT.md` (sha256 of `static/react/finco-react.js` / `.css`; reproducible from `frontend/` with `npm ci --ignore-scripts && npm run build`) |
| Reproducibility proof | At baseline, a clean `npm run build` produced `finco-react.js` sha256 `5e18dd63…98e` and `finco-react.css` `c85745c4…533844`, byte-identical to the committed `static/react/` files |

## 2. Bundle / backend compatibility (Repo)

All backend changes are additive presentation fields in `app/v2/react_workspace_router.py`:
`workspace.vertical`, `statements.results.lender_metrics`, `statements.project.project_type`,
`scenarios.override_capability`, `scenario-compare.differences[].label/unit`, `library.*.vertical`; and two value changes:
`statements.status.runId` and `library.*.last_run.snapshot_id` now carry the **full** canonical snapshot id (formerly cut to 12 characters).

| Pair | Behaviour |
|---|---|
| new bundle + new backend | intended |
| new bundle + **old** backend | degrades safely: absent `vertical` / `lender_metrics` / `override_capability` render nothing; a 12-character `runId` is not a canonical identifier so it is shown verbatim (the old, ambiguous text), never invented |
| **old** bundle + new backend | works: the old bundle printed `runId` / `snapshot_id` as plain text and ignores unknown fields |

Rollback is therefore safe in both directions. Deploy backend and bundle together anyway.

## 3. PREREQUISITE FOUND — stale-bundle risk (needs an owner decision; not changed here)

* `app/v2/react_poc_router.py:47` sets `REACT_ASSET_VERSION = "rc-sec-mutation-v1"`; the host page requests
  `/static/react/finco-react.js?v=rc-sec-mutation-v1`.
* `deploy/nginx/app.conf` serves `/static/` with `expires 7d; Cache-Control "public, immutable"`.
* `git log -S'rc-sec-mutation-v1'` shows the constant was set in commit `ceab974`; the bundle has been rebuilt in
  `0bc14d4`, `8422adb` and `1800bf6` since, **without** a new value.

Consequence: a browser (or CDN) that already holds the old bundle under that URL may keep running it for up to 7 days
after deployment, i.e. the corrections in this PR would not reach those users. `react_poc_router.py` is a pinned file and not
in this PR's authorized scope, so it is **not edited**. Before the pilot: bump `REACT_ASSET_VERSION` through an approved,
pinned-source change (and its governance successor), or purge/bypass the static cache for `/static/react/` at deployment.
Verify with `curl -sI https://app.finco.one/static/react/finco-react.js?v=…` (NOT VERIFIED here).

## 4. Feature flag (Repo)

`FINCO_MODEL_REACT_V1` is read per request (`react_poc_enabled`, default OFF). Preview routes: `/v2/model-react/` and
`/v2/model-react/{project_code}`; the legacy `/v2/workbook` stays the functional fallback. Enabling the flag is an
environment change and is **not performed**. Pilot owners must decide whether to enable it for the whole host or only
behind an internal-account gate (the code has no per-user gate; NOT a recommendation to add one here).

## 5. D-029 runtime truth

See `D029_RELEASE_TRUTH_RECONCILIATION.md`: merged and active for any client that sends a `run_intent_id` (both do);
policies unapproved; `RELEASE_POLICY.enabled` is not a kill switch.

## 6. Database isolation, backups, rollback

| Item | Repo evidence | Needs server check |
|---|---|---|
| Separate databases | `deploy/env.example` `FINCO_DB_PATH=/opt/finco_protocol/storage/finco.db`; `deploy/staging.env.example` `/opt/finco_staging/storage/finco_staging.db` | that production and staging really use different files, and that pilot accounts do not share a project with real users |
| Backup | `deploy/scripts/backup.sh` (SQLite `.backup`, xz, 30-day retention) | a backup taken immediately before the deployment; restore rehearsed with `deploy/scripts/restore.sh` |
| Rollback | the bundle is a git-tracked static file; previous SHA restores the previous bundle. Backend changes are additive, no migration | confirm the deploy procedure keeps the previous release directory; invalidate cached static assets (section 3) |
| Migrations | none in this PR. D-029 ledger schema installs additively at startup (already on main) | — |

## 7. Legacy / staging separation (Repo)

`deploy/nginx/app.conf` (`server_name app.finco.one`) and `deploy/nginx/staging.conf` (`staging.finco.one`) are separate
server blocks with separate env examples. Whether staging currently serves legacy-only is NOT VERIFIED. This PR makes no
staging change.

## 8. Protected references, accounts, disposable data

* Protected references stay read-only in every editor (acceptance: `test_wf2_protected_reference_workspace_is_read_only_in_every_editor`,
  `test_onb_protected_reference_inputs_stay_visible_and_read_only`, grid/Scenario/Run refusal tests).
* Internal testing accounts: NOT VERIFIED (account provisioning is outside the repository). Use accounts that own only
  disposable projects.
* Synthetic/disposable acceptance: every browser test in this PR creates its own project through
  `create_reference_seeded_project` in a temporary database; none touches a deployed database.

## 9. Acceptance plan for the pilot window (to be executed by someone with access)

1. Take a backup; record the previous deployed SHA and `sha256sum static/react/finco-react.*`.
2. Deploy the approved merge SHA; confirm the served bundle hash equals the PR's recorded hash (and is not a cached copy).
3. With a disposable internal account: clone one Solar and one Wind reference; Save one scalar field; Run; check
   Results/Statements show the cloned project's own name and type, a Run label with seconds + suffix, "Not available" for
   NPV/LLCR/PLCR when the Run does not publish them, and the preview banner on Data Center / EV Charging.
4. At 390 px open Inputs and the later destinations (Scenarios, Analysis) from the navigation.
5. Create a scenario, override one listed assumption, run, compare two Runs by label.
6. Roll back rehearsal in staging only.

## 10. Remaining financial dependency — F01 (Overnight A)

The Financing section still displays and saves the senior interest rate with its **current** value representation
(`debt.senior.interest_rate_pct`, percent). That representation is the subject of Overnight A's F01 correction, which owns
`app/v2/router.py` and the financial path. This PR deliberately does **not** touch the representation or its tests; only
the surrounding help text now says "the interest rate is controlled by the detailed financing schedule". **Pilot
acceptance of any financing number must wait for F01** to be merged and re-verified; if F01 changes the stored unit, the
React Financing field label/validation must be re-checked against it. At the time of this work no Overnight A branch was
visible on the remote (no branch ahead of main touching the React or financing path), so there is no merge conflict to
coordinate yet.
