# GAP-R1 — New Project wizard and creation contract

## Flow (React `NewProjectWizard`, reachable from the Library `+ New Project` CTA and the global Model navigation)

1. **Technology** — cards come from the product-capability registry: Solar and Wind `PILOT CANDIDATE`; Data Center and EV Charging
   `PREVIEW` with their registry limitations and a required explicit acknowledgement; Storage/BESS shown but **not selectable**
   (`NOT RELEASED`). No card exists without the server declaring it creatable.
2. **Project details** — name, country/market (the canonical `COUNTRY_OPTIONS`; location metadata only, same Generic Tax Template),
   capacity (technology-specific label; canonical registry minimum 0.1 MW, adapter sanity maximum 10,000 MW — *not* an economic limit).
   *Next* calls the server preview, so validation is the server's.
3. **Timeline** — financial close, construction period, COD and horizon of the canonical reference, **read-only**. The canonical create
   service does not accept these; advanced inputs are edited in Inputs after creation (the brief's "no fragile duplication of engine defaults").
4. **Review & create** — the server-computed effective assumptions (capacity, scale vs the reference, scaled CAPEX and Year-1 OPEX in kEUR,
   tax template, `NOT RUN` initial status). *Create project* is one POST; success navigates to the new workspace (`NOT RUN`).

Responsive: single column ≤ 820 px, step indicator collapses to "Step n of 4", ≥ 44 px touch targets, no document-level horizontal scroll at
320/390/768/1440 px (asserted in Chromium).

## Endpoints (`app/v2/react_new_project.py`)

| Route | Purpose |
|---|---|
| `GET /v2/model-react/new-project/options` | technologies (+ tier, limitations, defaults from the reference factory), countries, bounds, a fresh `request_id` and a CSRF token **signed over session + `request_id`** under the purpose `react-new-project-v1` |
| `GET …/preview` | field-level validation (422 with `errors[]`) and the effective assumptions; writes nothing |
| `POST …/create` | the only write. Order: flag → session → JSON shape (400) → **CSRF (403)** → read-only fence check (an already-claimed id never reaches the writer) → validation (422) → preview acknowledgement (409) → demo limiter (429) → **durable claim** → `create_reference_seeded_project` → claim finished → secondary stamp |
| `GET …/status` | reconciles a `request_id`, owner-scoped: `created: true, conclusive: true` only when a project is recorded; otherwise `created: false, conclusive: false, state: NONE / IN_FLIGHT_OR_UNKNOWN / FAILED` |

Samples with real synthetic responses: `api_contracts/new_project_*.json`.

## Duplicate and unknown-outcome handling

**Status: NOT production-ready.** The fence below removes the duplicate risk *between server workers for this React create*; it does not make the
canonical creator exactly-once (see "Known limits" and `08_OPEN_OWNER_AUTHORIZATIONS.md` item 3).

* **Durable fence.** `app/v2/react_request_claims.py` keeps a ledger keyed on `(user_id, request_id, purpose)` in the shared database. `claim` is one atomic
  `INSERT OR IGNORE`: exactly one caller — across threads **and across separate OS processes** — wins and may call the canonical creator. The winner then
  records the project code (`DONE`); a clean failure is recorded as `FAILED`. A row is **never reclaimed, overwritten, expired or retried automatically**.
* **What every later request with the same id sees:** `DONE` → `200 replayed: true` with the same project (body ignored); `CLAIMED` (in flight, or the
  claimant died) → `503 CREATE_IN_FLIGHT_OR_UNKNOWN`, nothing created; `FAILED` → `503 REQUEST_ID_CONSUMED`; unreadable ledger → `503 CREATE_UNAVAILABLE` before any write.
  503 makes the unchanged client treat the outcome as *unknown* (one read-only status check, then no retry control). A claimed-but-unfinished id whose project
  carries the secondary `replay_metadata` stamp is reconciled as created.
* **Order matters and is pinned:** refusals (CSRF, shape, validation, preview acknowledgement, demo limiter) happen **before** the claim so they never burn a request
  id; the claim happens **before** the writer. `tests/rcm_adapter_csrf_successor.py` fails closed if that order changes.
* **Demo budget** (`project_create`: 5 per hour) is additionally enforced inside the same atomic claim statement, so it holds across workers; replays cost nothing.
* **Lost response:** the client never retries. It performs one read-only reconciliation by request id; if the project exists it proceeds, otherwise it shows
  **"Result unknown — refresh the Library"** with *no* retry control. The request identity lives in the URL hash (`#new-project:<id>`) — **not** in browser storage,
  which a pinned product test forbids in the production bundle.
* **Cross-user isolation:** the token is bound to the session cookie and the request id; another user's cookie gets `403` and the status of someone else's id
  is `NONE` with no project.

### Evidence

`tests/test_model_react_rcm_new_project_fence_v1.py` (ledger contract, every claim state, failure injection) and
`tests/test_model_react_rcm_new_project_multiprocess_v1.py` (three real uvicorn processes on one database): simultaneous same-id POSTs → exactly one project and one
non-replay response; crash after the write and before finishing the claim (`os._exit`) → claim stays `CLAIMED`, replay storm creates nothing, a *new* request id is a
deliberate separate create; crash after finishing → replay returns the project; replay after a lost response from another process; cross-user isolation; 403 CSRF
(tampered/empty/foreign-session token) never claims; demo budget across processes; Storage/unknown technologies and an extra source-project field create nothing.
A mutation check (claim forced to always win) makes five of the eight multi-process tests fail, so they do detect the original single-process-lock weakness.

### Known limits (stated, not hidden)

* The project rows and the claim are two writes, not one transaction. A crash between them orphans a project and leaves that request id permanently *unknown*
  (safe against duplicates; the user reconciles in the Library and starts a new request).
* The canonical seeded creation is itself several writes; a crash inside it can leave a partially seeded working copy (pre-existing; Legacy `/projects/create` is unfenced).
* Exactly-once at the writer needs a change to protected creation writers, one of which F01 owns — an exact patch request is in `08` item 3; **not applied**.

## Parity proofs

* The effective CAPEX/OPEX shown in the preview equal the values the canonical service persists (asserted against a directly-created oracle for
  Solar and Wind).
* A wizard-created project and a directly-created project with the same inputs have **identical** `draft_snapshot` apart from
  name/code/`_reference_seed_profile` (Python and Chromium).
* Stamping preserves `project_role`, protection, origin, template, type and the full seed snapshot.

* **Same-runtime Run parity:** for Solar and Wind a wizard-created project and a directly-created twin (same name-independent inputs) were each Run
  through the canonical Run route in one process; every Last Run metric (Project IRR, Pure Equity IRR, Total Sponsor IRR, …) is identical.

Not done: a comparison against a Legacy-created twin on a *deployed* pinned environment (no deployment was touched), a full "Save → Reload → Run →
Results/Statements/History" Chromium journey for the wizard's two technologies on the final bundle (the Save/Run chain is covered per lane in the
Goal Seek and Financing journeys), and any F01-dependent interest-rate persisted-snapshot proof (F01 unmerged).
