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
| `POST …/create` | the only write. Order: flag → session → JSON shape (400) → **CSRF (403)** → validation (422) → preview acknowledgement (409) → demo limiter (429) → `create_reference_seeded_project_once` (request-keyed, atomic identity) |
| `GET …/status` | reconciles a `request_id`, owner-scoped: `created: true, conclusive: true` only when a project is recorded; otherwise `created: false, conclusive: false, state: NONE / IN_FLIGHT_OR_UNKNOWN / FAILED` |

Samples with real synthetic responses: `api_contracts/new_project_*.json`.

## Duplicate and unknown-outcome handling

Creation is idempotent per `(user, request id)` through the canonical creation authority (full description and proof: `atomic_create/README.md`).

* **Atomic identity.** The request id is committed by the SAME INSERT that creates the project row (partial unique index `ux_projects_user_create_request`); a second project for one user and request id is impossible for any number of
  workers. The project becomes `COMPLETE` only inside the transaction that writes its CAPEX/OPEX seed lines.
* **What every later request with the same id sees:** `COMPLETE` → `200 replayed: true` with the same project; being created or interrupted (less than the 300 s lease) → `503 CREATE_IN_FLIGHT_OR_UNKNOWN`, nothing written;
  interrupted past the lease → archived `ABANDONED`, the id stays consumed (`503 REQUEST_ID_CONSUMED`); the same id with other inputs → `409 REQUEST_ID_REUSED`. 503 makes the unchanged client treat the outcome as *unknown*
  (one read-only status check, then no retry control). Status: `created: true, conclusive: true` only for a `COMPLETE` project; otherwise `state: NONE | IN_FLIGHT_OR_UNKNOWN | ABANDONED`.
* **Order:** refusals (CSRF, shape, validation, preview acknowledgement, demo limiter) happen before the writer, so they never burn a request id.
* **Lost response:** the client never retries; it performs one read-only reconciliation by request id and otherwise shows **"Result unknown — refresh the Library"** with no retry control. The request identity lives in the URL hash
  (`#new-project:<id>`), not in browser storage.
* **Cross-user isolation:** the token is bound to the session and the request id; another user's cookie gets `403`, and the status of someone else's id is `NONE` without a project.
* **Rates:** the new Working Copy carries F01's `human_percent_v1` contract (see `08` item 7); the wizard shows no rate and converts nothing.

Limits: the canonical seeded create is still several SQLite writes (detectable and fenced, not one transaction); the unkeyed Legacy `/projects/create` is not keyed. **Not a production authorization**; the flag is default OFF.

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
