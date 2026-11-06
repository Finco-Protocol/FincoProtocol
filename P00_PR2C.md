# P00_PR2C — Contract Audit: Atomic CAPEX Amount + Monthly Profile Save (PR2c)

Audited at: branch `feat/ux-pr2b-inline-profile-editing` @ `96d04d25cf79b14011cdee18258820aeb4cd4f74` (tree `9403b402f7299f7f75e9177c933563c270f2108f`), PR #428 base `main` `79887ef7a83a06a96d401e6a38135839e3551763`. All paths are repo-relative. Source-referenced only; no client names, no live values.

## 1. Authority map (what exists, verified)

| Authority | Location | Notes |
|---|---|---|
| Combined atomic save (server) | `app/v2/save_all_commands.py::save_all` / `SaveAllInput(profile_json, profile_base_token, cost_lines, cells, contracts_json, …)` | ONE `BEGIN EXCLUSIVE`; composite identity CAS; scenario check; per-document token check **inside the tx before any mutation**; fixed body order cells → contracts → cost lines → profile LAST ("proved bindable against the final, uncommitted lines and cells"); idempotency ledger (`save_all_requests`, same-id+same-sha replay, same-id+different-sha refused); full rollback. |
| HTTP route | `app/v2/grid_router.py::workbook_save_all` → `POST /v2/workbook/save-all` | CSRF purpose `model-save-all-v1`; session + project access; owner mismatch 403; typed HTTP mapping per error class. `SaveAllBody.profile_json` (≤70k) + `profile_base_token` accepted. |
| Opt-in flag | `save_all_commands.profile_enabled()` ← env `FINCO_SAVE_ALL_PROFILE_ENABLED` (default `0`), read per call | OFF ⇒ `_validate_shape` raises `SaveAllProfileNotEnabled` (`SAVE_ALL_PROFILE_NOT_ENABLED`, 422) **before** the connection/ledger: zero writes, request id not burned. OD-B2 NOT approved. |
| CAPEX line amounts in the same tx | `app/v2/cost_batch_commands.py::apply_cost_lines_in_tx` + `validate_cost_line_edits` (also used standalone by `POST /v2/workbook/grid/cost-lines/save`) | Per-row `row_version` CAS; all rows verified before the first write; caller owns the transaction. |
| Profile document contract | `app/capex_profiles/contract.py` — shapes UNIFORM/FRONT_LOADED/BACK_LOADED/EXPLICIT/MILESTONE; `check_months` 1..60; EXPLICIT exact-n + sum≈1 (1e-9); MILESTONE 1..n | Server-authoritative; Save All re-proves bindability via `save_profiles_in_tx`. |
| Profile-only writer (PR2b today) | `POST /v2/capex/spending-profiles/save` (`app/v2/capex_profile_router.py`) ← `ProfileDraftProvider.save()` → `saveCapexProfile()` form POST | Composite-hash CAS only; Base-case-only; **no per-document token** (form route predates D7). |
| Token primitives | `app/capex_profiles/service.py::profile_document_token / stored_profile_text_in_tx / read_profile_token` | `read_profile_token` exists but is called by **no route** — the client cannot obtain a `profile_base_token` today. |
| Capability advertisement | `app/v2/react_workspace_router.py` → `GET /v2/model-react/workspace` → `save_all.sections = ["cells","contracts","cost_lines"]` (hard-coded) | No "profile" entry; flag state not advertised anywhere; frontend `SaveAllCapability.sections` declared but unused. |
| Profiles read (React studio) | `GET /v2/model-react/capex/profiles` (`app/v2/react_capex.py`) → `save: {url, csrf_token, content_hash, scenario_id}` | No token, no save-all reference. |
| Frontend Save All builder | `frontend/src/app/editing/saveAll.ts::buildSaveAllRequest` | Builds cells + merged cost lines + PPA document (`contracts_json`/`contracts_base_token` via the O1 `documentSources` pattern). **No profile fields.** |
| Pending store | `frontend/src/app/editing/pendingEdits.ts` | `EditSection = inputs|ppa|capex|opex|financing` — **no "profile"**; whole-document sections use `documents` + `documentSources[].baseToken` (PPA precedent). |
| HTTP classifier | `frontend/src/app/editing/saveAllApi.ts::postSaveAll` | 409+`reload:true` → `stale`; other codes → `rejected{code,message}` (profile codes land here generically — message still authoritative). |
| Save CTA | `wsv2Extensions.tsx::Ws2Drawer` + `ChangesDrawer.tsx` + `saveAllBridge.ts` (WorkflowBar) | Gated on advertised capability; UNKNOWN keeps the identical request for retry; `saved` → `changes.committed(ids, newIdentity)`. |
| Profile draft owner | `frontend/src/app/capex/ProfileDraftProvider.tsx` (own reducer: draft/history/future, verify-by-read-back, UNKNOWN lock) | Blocks its own save when other sections are pending; today reports dirty under key `capex-profile` which `sectionsOfDirtyKey` does NOT map → the drawer cannot see profile changes. |

## 2. State machine (before → after, one combined request)

| # | Before | Action | After (flag ON, capability advertised) |
|---|---|---|---|
| S1 | staged line edits + dirty profile draft | Save All (one POST) | 200: amounts + full profile committed in one tx; response `content_hash` advances; run STALE; both drafts cleared after verified read-back identity |
| S2 | profile draft only (no line edits) | Save All | 200: profile committed alone (cost_lines empty); same guarantees |
| S2b | draft clears the final/only profile (real removal) | Save All | 200: the canonical EMPTY document `{"version":1,"profiles":[]}` removes the saved profile document inside the same tx (parser accepts it; canonical form `""`; base token CAS-verified first); no mutation emits no profile fields |
| S3 | line edits only (no profile change) | Save All | 200: exactly today's behavior; `profile_json` omitted (never manufactured) |
| S4 | stale line `row_version` | Save All | 409 per-line verdicts; **nothing** written (profile incl.); edits stay staged |
| S5 | stale/missing/counterfeit `profile_base_token` | Save All | 409 `STALE_PROFILE_DOCUMENT` / `PROFILE_DOCUMENT_TOKEN_REQUIRED`; nothing written (cells/lines NOT applied) |
| S6 | mismatched composite `content_hash` / changed scope / non-Base scenario for the profile | Save All | 409 `STALE_CONTENT` / `SAVE_ALL_SCENARIO_MISMATCH` / (in-tx) `CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED` → full rollback |
| S7 | unbindable profile vs final uncommitted lines | Save All | 422 `CAPEX_PROFILE_*`; byte-identical rollback (proven by D7 fault-injection tests) |
| S8 | flag OFF, profile supplied | Save All | 422 `SAVE_ALL_PROFILE_NOT_ENABLED`; zero writes; request id NOT burned; staged drafts retained |
| S9 | network loss / unreadable answer | Save All | UNKNOWN: attempt kept, same `request_id` + identical body on retry; reconciliation read-only; no new idempotency key |
| S10 | duplicate `request_id`, identical body | Save All | stored outcome replayed (`replayed: true`), no second write |
| S11 | duplicate `request_id`, different body | Save All | 409 `SAVE_ALL_REQUEST_ID_REUSED`; nothing written |
| S12 | Base Case unsupported (scenario selected) for the profile | Save All | in-tx refusal → full rollback; profile stays editable only in Base (existing rule preserved) |

Unsupported/never-claimed: two-call "atomic" sequences; client-side derivation of saved monthly EUR; silent retry with a new idempotency key; clearing one draft independently; Run side effects.

## 3. Truth table — capability advertisement

| `FINCO_SAVE_ALL_PROFILE_ENABLED` | workspace `save_all.sections` | profiles read `save_all_combined` | Drawer CTA behavior | Profile editor Save button |
|---|---|---|---|---|
| OFF (default) | `["cells","contracts","cost_lines"]` (unchanged bytes) | key absent (unchanged bytes) | today's behavior; profile changes invisible to the drawer | profile-only save (today's semantics, honest copy) |
| ON | `[…, "profile"]` | `{available, url, profile_base_token}` | Save All carries a dirty profile draft atomically | profile-only Save disabled with honest copy ("Save All will save the profile together with staged line amounts"); Reset unchanged (profile-only writer) |

## 4. Verdict

The existing server contract **does safely support** combined CAPEX line + profile save (transaction, CAS, tokens, idempotency, rollback — implemented and green-tested by `tests/test_d7_save_all_profile_atomic.py`). The gaps are wiring-only and all flag-gated:

1. **Token read-echo** — expose `profile_base_token` on the profiles read, gated on `profile_enabled()` (the D7 combined contract itself lists this as the pending client step).
2. **Capability advertisement** — `sections += ["profile"]` gated on the same flag (OFF ⇒ byte-identical payloads).
3. **Frontend builder** — `saveAll.ts`/`pendingEdits.ts` profile section via the existing O1 document+baseToken pattern; profile-typed outcome mapping.
4. **Provider integration** — the PR2b draft publishes into the pending store when (and only when) the combined capability is advertised; profile-only Save remains the default-OFF path.

**Verdict: PROCEED** (not `PR2C_P00_CONTRACT_BLOCKED`). Nothing requires financially unsafe semantics; OD-B2 remains OFF; the combined path is proven only with test-scoped opt-in.

## 5. Request/response examples (synthetic values)

Request `POST /v2/workbook/save-all` (combined, flag ON):
```json
{"project": "demo-project", "csrf_token": "<bound-token>", "workbook_version": "<v>",
 "content_hash": "<composite>", "scenario_id": null, "request_id": "pr2c-20261106-a1b2c3d4",
 "cells": [], "contracts_json": null,
 "cost_lines": [{"kind": "capex", "sub_line_id": "c-12", "label": "Modules",
                 "amount_keur": "1200.000", "row_version": "<row-updated-at>"}],
 "profile_json": "{\"version\":1,\"profiles\":[{\"item_key\":\"c-12\",\"shape\":\"FRONT_LOADED\"}]}",
 "profile_base_token": "<profile-document-token>"}
```
Success: `{"ok": true, "replayed": false, "saved": {"cells": 0, "contracts": 0, "cost_lines": 1, "profile": 1}, "content_hash": "<new-composite>", "workbook_version": "<v>", "scenario_id": null, "run_state": "STALE", "model_executed": false}`.
Flag-OFF refusal: 422 `{"ok": false, "code": "SAVE_ALL_PROFILE_NOT_ENABLED", "message": "Saving the CAPEX profile together with other sections is not enabled; save the profile in the CAPEX planner."}`.

## 6. Governance surface (verified pins at this HEAD)

| File to change | Current exact-source owner |
|---|---|
| `app/v2/react_capex.py` | rc_ux_completion |
| `app/v2/react_workspace_router.py` | u2_workbench |
| `app/v2/save_all_commands.py` — **not changed** (input/route already accept the fields) | post413_o1 |
| `frontend/src/app/editing/pendingEdits.ts` | post413_r1 (+ presence in post413_o1) |
| `frontend/src/app/editing/saveAll.ts` | post413_r1 |
| `frontend/src/app/capex/ProfileDraftProvider.tsx` | ux_pr2b |
| `frontend/src/app/capex/api.ts` | unpinned (presence-listed in post413_o1) |
| `static/react/finco-react.js` (bundle) | ux_pr2b + post413_o1/r1/r17/r18/u2 (SHARED_REVIEWED-style signing) |
| `tests/fin_v2_cohorts.py` (registry += ux_pr2c) | ux_pr2b + post413_r17/r18/r1/u2 (signed identically by the four) |

PR2c therefore adds: `tests/ux_pr2c_scope.py` (new closed cohort; BASE = `96d04d25`), `docs/react_migration/ux_pr2c/UX_PR2C_EXACT_SOURCE.json`, a one-line registry addition in `tests/fin_v2_cohorts.py`, and moved-pin updates in the sibling manifests that pin changed bytes (post413_o1, post413_r1, ux_pr2b, u2_workbench, rc_ux_completion + the r17/r18 shared signers for the two SHARED_REVIEWED paths). PR2b's `FORBIDDEN_PATHS`/`FORBIDDEN_PREFIXES` are respected: PR2b's own cohort never touches these files — the PR2c cohort supersedes them through the documented `supersedes`/`INTEGRATION_MANIFESTS` hooks.

Known upstream failure on the stacked base: `tests/test_u2_scope.py::test_the_u1_successor_assertion_admits_only_a_registered_exact_u2` (CI V4 shard-1) — owned by PR #428 Correction E. PR2c neither causes nor fixes it; upstream/regression are reported separately.
