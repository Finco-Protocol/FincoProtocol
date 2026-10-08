# MODEL SCENARIO SWITCH COHERENCE — P1 STAGING CORRECTION

## A. Authority and scope

- Repository: `Finco-Protocol/FincoProtocol`
- Verified baseline main (2026-10-08): `5de76e5b944350a57dff1121c80f77d3afbe23da`.
- Separate feature branch: `fix/model-v2-scenario-switch-coherence`, created exactly at baseline main.
- Initial implementation commit: `7bf4edf06b82f59c242f816641538861dadc72d2`.
- Concurrent PR #222: **OPEN DRAFT**, initial checked HEAD `fd0647c9873883a1c4cf2bc2681e0a7afb3ec738`; NOT modified, NOT merged.
- PR #222 touches `app/v2/router.py` for CAPEX/OPEX, but this fix deliberately leaves `app/v2/router.py` unchanged.
- No deploy, DB reset, forced push, rebase, financial or token-layer change.

## B. Defects and reproduction evidence

Acceptance input: `FINCO_MODEL_POST220_STAGING_ACCEPTANCE_REPORT.md`, Section O, screenshots `O_*` (reported by staging acceptance owner; original binary evidence was **not accessible in this execution environment**).

- D-1 P1 reported sequence: Base Run A → create/select Scenario X via HTMX → edit revenue tariff → first Save without manual reload → 409 `StaleContentError`. Expected: one successful Save and correctly STALE Last Run state.
- D-2 P2 reported: top navigation Scenario label trails the actual selected scenario by one selection.
- These staging observations are NOT represented here as independently reproduced in a live browser. Exact recorded old/new hashes, HTTP traces and O_* screenshots were not available.

## C. Source-proven root cause

- `app/persistence/scenarios_repository.py::select_scenario` writes active scenario ID/name and restores/clears the scenario-scoped Last Run in an exclusive transaction; it intentionally preserves the project-level shared draft.
- `app/workbook/workbook_identity.py` includes active scenario ID and effective overrides in the **composite** CAS identity. Thus `H(Base)` and `H(Scenario X)` generally differ even if scalar Working Copy values match.
- `app/v2/router.py::v2_scenario_select` responds with the updated scenario sheet plus `_scenario_authority_oob`.
- `app/v2/post_run_ui.py::build_post_save_ui_state` refreshed canonical Run controls, banner, toolbar runtime state and workspace header, but **not the hidden `content_hash` inputs on every existing editable sheet**.
- `static/js/workbook_v2.js` previously synchronised all those inputs on `workbook-field-saved` events only, not on scenario selection.
- `app/templates/v2/workbook.html` rendered a separate top-bar scenario button once at initial GET; no matching OOB replacement existed. The workspace header did get OOB refreshed, explaining the one-step discrepancy.
- Genuine concurrent edits may ALSO cause 409 by design. This change deliberately does not suppress them.

## D. Correction

1. Initial workbook GET includes a server-issued, hidden `#v2-scenario-edit-authority` containing composite hash, workbook version, and active scenario identity.
2. Following a successful HTMX scenario mutation, `build_post_save_ui_state` sends a matching OOB replacement built from the same canonical PIS already used for Run controls and status.
3. A tightly scoped `htmx:afterSettle` handler handles successful scenario create/select/archive/override responses only. It copies this **server-issued** hash/version to all existing hidden editable/Run forms and the workbook shell; never sends a request and never constructs a hash on the client.
4. The top-bar scenario button now uses one shared template and is OOB swapped on scenario mutation, alongside the already-updated persistent workspace header.
5. Scenario sheet copy clarifies: editable sheets share one project Working Copy; scenario overrides are managed separately in the Scenarios sheet.
6. No CAS bypass, no automatic economic write retry, no duplicate form submit, and no independent per-scenario drafts.

## E. Identity transition — observed vs expected

| Boundary | Before fix | With patch (intended) |
|---|---|---|
| Initial Base GET | Editable hash `H(Base)`; active Base | Unchanged |
| Select Scenario X | Server Run controls `H(X)`, other sheet forms **still `H(Base)`** | OOB marker supplies `H(X)`; after-settle sync updates ALL displayed tokens |
| First revenue Save | Submitted `H(Base)` vs authoritative `H(X)` → 409 | Submitted `H(X)` vs authoritative `H(X)` → successful CAS unless concurrent edit |
| Save commit | Not reached | New post-save `H(X, edit)`, stale Last Run presentation (existing authority) |
| Return to Base | Other forms may still carry `H(X)` | New marker and all forms carry `H(Base, edit)` |
| Other tab edits meanwhile | Legitimate hash mismatch | **Still 409**, no silent overwrite |

Above are identity relationships, **not numeric hashes from staging**. Exact submitted/authoritative staging hashes, workbook_version and actual HTTP results remain to be captured in authenticated staging acceptance.

## F. Regression and browser matrix

| Acceptance case | Current evidence |
|---|---|
| Base → X → first Save 200 exactly once (Solar) | NOT RUN — requires authenticated staging/browser |
| X → Base → first Save 200 exactly once (Solar) | NOT RUN |
| Base → X → Base → X and first Save (Wind) | NOT RUN |
| Top-bar scenario = workspace header = active Scenario row | Source inspection and OOB template; live screenshot NOT RUN |
| Canonical Run form and all editable-sheet hashes identical | Source inspection and JS handler; browser DOM proof NOT RUN |
| Real stale second-tab edit remains 409 | Unmodified transaction CAS; concurrency browser proof NOT RUN |
| Goal Seek Apply avoids a false 409 | Code path not modified; regression NOT RUN |
| Base Run A / Scenario X Run B / Last Run restoration | Persistence untouched; regression NOT RUN |
| Owner and project isolation | Persistence and scoped selectors untouched; regression NOT RUN |

A focused unit test file was added: `tests/test_model_scenario_switch_coherence.py`, covering OOB authority, Base(None), HTML attribute escaping, top-bar scenario rendering, and no client-side economic retry. Local pytest/real Chromium were **not executable**: this environment has GitHub API connector access but no repository checkout, staging browser, or cloned application dependencies. Before the first remote commit, limited static change-boundary checks passed (six intended paths, one authority marker, one shared label template, one listener; zero frozen namespace changes). **This is not a substitute for the required pre-push focused pytest.**

## G. Files and isolation

- `app/templates/v2/workbook.html`
- `app/templates/v2/partials/_v2_toolbar_scenario.html` (new)
- `app/templates/v2/partials/sheet_scenarios.html`
- `app/v2/post_run_ui.py`
- `static/js/workbook_v2.js`
- `tests/test_model_scenario_switch_coherence.py` (new)

Frozen directories `financial_engine/**`, `finco_core/**`, Radar, Yield, Crypto, entitlements and deployment: **zero modified files**.

## H. Merge/deploy policy and open gates

- This is a **DRAFT PR** for independent review. No automatic merge and no deploy.
- Five exact-head GitHub workflows must finish **GREEN** before merge consideration.
- Required before READY: execute local focused tests; capture original 409 and corrected 200 with synthetic Solar and Wind; verify one save, no false CAS; verify two-tab genuine 409; verify Goal Seek and Last Run; attach browser screenshots `O_*` and exact original/corrected hashes/versions; independently review HTMX after-settle/OOB timing.
- If PR #222 merges first, **normal merge** current main into this branch, resolve only actual conflicts, rerun focused tests and exact-head CI. No rebase/squash/force push.
- Final exact-head SHA and CI status must be read live from the draft PR; no prior CI is merge authority.

## I. Outcome

**MODEL_SCENARIO_COHERENCE_BLOCKED**

The source-level correction and regression scaffolding exist, but required real-browser Solar/Wind acceptance, transaction-conflict proof, original staging evidence and five exact-head green CI workflows have not yet been established. No acceptance PASS or production readiness is claimed.
