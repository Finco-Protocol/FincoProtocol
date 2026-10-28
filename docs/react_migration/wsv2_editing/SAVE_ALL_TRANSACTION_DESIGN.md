# Save All — transaction design (M-008)

**Verdict: genuine all-or-none Save All across sections is NOT shippable from unprotected paths. It is gated (client shows BLOCKED), not simulated.**

## 1. Canonical writers audited at `b1a58681`

| Section | Route / function | CAS | CSRF purpose | Transaction boundary |
|---|---|---|---|---|
| Scalar fields (Project, Tax, Debt scalars, Financing scalars) | `POST /v2/workbook/grid/save` → `WorkbookUpdateService.apply_batch_draft_update` → `workspace_repository.v2_atomic_batch_draft_update` | composite hash + `workbook_version` + `workspace_id` + active scenario | `grid-save` | **own connection, own `BEGIN EXCLUSIVE`**, ≤50 cells, all-or-none |
| Single scalar (legacy field editors) | `POST /v2/workbook/update` | same | `workbook-update` (+ bound financing token for `debt.financing.instruments`) | own transaction (`v2_atomic_draft_update`) |
| CAPEX/OPEX lines | `POST /v2/workbook/grid/cost-lines/save` → `cost_batch_commands.update_cost_lines_batch` | composite hash + per-row `row_version` | `grid-cost-lines-save` | own connection via `capex_commands._exclusive_tx`, ≤50 lines |
| Revenue contracts | `POST /v2/workbook/revenue/contracts` → `revenue_contracts_service.save_contracts` | composite hash, scenario-aware (writes scenario overrides for non-Base) | plain signed `generate_csrf_token()` | own connection, own `BEGIN EXCLUSIVE` |
| Financing collections (F3, `debt.financing.instruments`) | `/v2/workbook/update` only; the batch writer refuses it (`BATCH_F3_COLLECTION_EDITOR_ONLY`) | bound financing token | financing-bound token | own transaction |

Invariants common to all: protected-reference refusal, owner match, workbook-version check, composite-identity CAS before the first write, `dirty=1` + new composite hash committed with the data, no engine run, no Run-history write. Last Run becomes STALE through `resolve_runtime_freshness`.

## 2. Why sequencing is not Save All

Every writer re-hashes the *whole* workbook. After the first commit the composite hash has changed, so a second POST with the original hash is rejected by CAS, and one with the new hash silently accepts anything that landed in between. Four POSTs are four commits: a failure on the third leaves the first two persisted. This PR therefore never chains them, and `buildSaveAllRequest` produces one request for one endpoint.

## 3. Target design (needs Owner path authorisation)

One endpoint, `POST /v2/workbook/save-all` (name proposed), one `mutation_token(..., "save-all")`, one transaction:

1. Validate shape and size **before** opening a transaction (cells ≤ 50, lines ≤ 50, contracts document ≤ 200 KB; total cap proposed 200 items).
2. Resolve session → owner → project; protected reference / non-owner → refuse (no existence leak across users).
3. `BEGIN EXCLUSIVE`; load workspace; compare `workbook_version`, `workspace_id`, active scenario, and the **composite hash once**.
4. Apply, in this fixed order, the *same validators and mutators the section writers use*, now operating on the shared cursor: scalar candidate (`ProjectInputSet`, F3 / senior-authority / bankability checks), then revenue contracts (scenario-aware), then cost lines (row-version verified inside the transaction).
5. Compute the final composite identity **once** from the in-transaction state, write `draft_snapshot_json`, `draft_content_hash`, `dirty=1` in the same transaction, `COMMIT`.
6. Any exception → `ROLLBACK`; the response carries per-section, per-item verdicts. Nothing persisted, hash and Last Run unchanged.
7. Idempotency: `request_id` + a SHA-256 of the canonical request body. A replay returns the stored outcome; a replay with a different body is refused. Preferred storage: a small `save_all_requests` table written in the same transaction. Lower-risk alternative with no schema change: stateless reconciliation by comparing the saved state to the request (what the client already does for the per-section writers); weaker against a competing edit.

Financing: scalar `debt.*` fields ride in `cells` (same validators). **F3 collections stay out** (they keep their editor-only, bound-token authority); the drawer states this.

## 4. Why this needs protected paths

`v2_atomic_batch_draft_update`, `save_contracts` and `_exclusive_tx` each open their own connection; none can join an outer transaction. Re-implementing their validation in a new module would create a second validation authority (a "dual persistence layer"), which the assignment forbids. The honest minimal change is to split each into *body* (takes a cursor) and *wrapper* (opens/commits, behaviour byte-identical), then add a thin composing function. All of these files live under pinned `app/`. See `PROTECTED_PATH_REQUEST_SAVE_ALL.md`.

## 5. Draft survival (client)

Drafts live in `ChangesProvider` memory so they survive section navigation. Exit/reload is guarded by `beforeunload`. Restoring drafts from `localStorage`/server is **not** implemented: a restored draft would be applied against an unknown baseline and could violate CAS expectations or leak across users on a shared browser. If the Owner wants it, the safe design is a server-side per-user/per-project/per-hash draft that is dropped when the composite hash moves.

## 6. Test plan the endpoint must pass before it ships

≥ 50 changed cells across Project/PPA/CAPEX/OPEX/Financing in one request and exact read-back; one deliberately invalid field → zero persisted changes (hash, rows, snapshot, dirty flag identical); stale hash; two-tab race; replay with same `request_id`; section-specific validation; non-Base active scenario; wrong CSRF; another user's project id; protected reference; no Run triggered and Run history unchanged; Last Run reported STALE after commit. A failure-injection hook that raises after the 2nd of 3 sections must leave no partial state.
