# UX-PR2c — atomic CAPEX amount + monthly profile save (Draft, stacked on unmerged #428)

Stacked on unmerged #428 at `96d04d25cf79b14011cdee18258820aeb4cd4f74` (tree `9403b402f7299f7f75e9177c933563c270f2108f`). ONE Draft PR, base = PR2b's head branch; never merged automatically. Product activation OFF: `FINCO_SAVE_ALL_PROFILE_ENABLED` stays `0` in repository defaults — OD-B2 pending; test-scoped opt-in only proves the path.

Scope: ONE combined Save All request carrying staged existing CAPEX line amount edits plus the related monthly profile document, reusing the EXISTING D7 transaction authority (`app/v2/save_all_commands.py` — unchanged). New server surface (both OD-B2 gated, OFF keeps payloads byte-identical):

- `GET /v2/model-react/capex/profiles` → `save.save_all_combined = {available, url, profile_base_token}` (the D7 read echo).
- `GET /v2/model-react/workspace` → `save_all.sections += ["profile"]` while the flag is on.

Client: `pendingEdits.ts` gains a `profile` whole-document section (O1 document + base-token pattern, same as PPA); `saveAll.ts` emits `profile_json` + `profile_base_token` only with a real profile mutation, for the identity the document was authored against, and refuses document-without-token; `ProfileDraftProvider.tsx` publishes the dirty draft into the pending store when (and only when) the combined capability is advertised, verifies a committed combined save by full read-back, and keeps the PR2b two-writer behavior when the capability is absent; `wsv2Extensions.tsx` maps the `capex-profile` dirty key to the store section for discard bridging.

Failure semantics (unchanged from D7): 400/403/409/422 leave every raw input staged with the authoritative message; UNKNOWN outcomes keep the same `request_id` and identical body for reconciliation; success alone is not trusted — consistent read-back of amounts AND the full profile is required before drafts clear; a changed or unverified readback stays locked.

Out of scope (unchanged): line creation/deletion, user-added-line profile lifecycle (PR2d/D-13), OPEX editing/D-09, Revenue/Financing PR3, engine calculations, spreadsheets, F3 collections, Run side effects, bundle activation.

Governance: this cohort (`tests/ux_pr2c_scope.py`) supersedes exactly the paths it changed from UX-PR2b, post413-O1/R1, RC-UX completion and the U1/U2 workbenches; the sibling manifests' moved pins move to these same bytes (nothing else in them changes); the registry and U1 LATER / U2 SIBLING chains are extended by one entry.

## Correction A (PR #429 review, 2026-11-06)

Re-anchored to post-#428 `main` (`f0ead1687bafd41db7472e4009234d0410451210`) by ordinary merge; retargeted to `main`.

Governance root cause of `composite=False (23)`: the sibling manifests' moved pins for the shared files (`tests/fin_v2_cohorts.py`, `tests/u1_scope.py`, `tests/u2_scope.py`, `static/react/finco-react.js`, `pendingEdits.ts`, `saveAll.ts`, `react_workspace_router.py`, …) were never moved to the PR2c blobs. The governed repair is the designed moved-pin admission: each sibling manifest's pin of an `ux_pr2c`-owned path moves to exactly the cohort's pin (nothing else in those manifests changes). `tests/ux_pr2a_scope.py` gets the same successor-tip extension the other chain members already have (`_pr2c` pins in `effective_pins`/sibling admission) — its historical manifest stays untouched.

Functional corrections (both found in review, both code + tests):

- **Completion observer lifecycle** — the staged-alive ref is now tracked on BOTH edges (false → true → false); the `true → false` edge classifies the disappearance through the pure machine `profilePublish.ts::decideDisappearance` against a fresh authoritative read: `committed` (rows match exactly what was published), `reverted` (same composite hash in the authored scope), `unstaged` (identity advanced, saved profile unchanged — draft retained, no lock), `unknown` (lock for reconciliation, never retry). A capability flip with the edit still staged is not a disappearance.
- **Remove-all rides the combined path** — `profileD7Document` serialises the canonical EMPTY document `{"version":1,"profiles":[]}` for a real removal (verified against the saved baseline); the server parser accepts it and its canonical form removes the saved profile document inside the same transaction (base token still CAS-verified). Serialization errors and "nothing to save" stay `null` — never confused with a legitimate empty document.
- **Author identity binding** — one authoring session per dirty period; the staged document is bound to the identity + token it was authored under and is never re-stamped when the shell identity advances; Save All then refuses it honestly ("older saved version") instead of silently rebasing a whole document.
- **Provider context** — the pending store is optional (`useOptionalChanges`): standalone routes without a ChangesProvider keep the exact PR2b behavior instead of throwing.
- **Profile-only save/reset** clears any staged combined mirror on verified completion.

Mounted-provider behavior is covered by the pure decision machine tests plus static render smoke (`pr2cCombinedSave.test.mjs`); the provider's read-back remains authoritative — a successful HTTP result alone never clears the draft.
