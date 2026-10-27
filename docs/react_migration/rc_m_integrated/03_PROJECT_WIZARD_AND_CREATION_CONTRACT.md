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
| `POST …/create` | the only write. Order: flag → session → JSON shape (400) → **CSRF (403)** → demo rate limit → per-request lock → durable replay check → validation → preview acknowledgement (409) → `create_reference_seeded_project` → idempotency stamp |
| `GET …/status` | reconciles a `request_id`: `created`/`conclusive`, owner-scoped |

Samples with real synthetic responses: `api_contracts/new_project_*.json`.

## Duplicate and unknown-outcome handling

* **Double submit / replay:** the request id is stamped into the new project's `replay_metadata` through the canonical
  `update_project_record`; a replay (same id) returns the existing project with `replayed: true` and creates nothing. Tested sequentially, with
  4 parallel threads (one writer wins), and in Chromium with a double-click (exactly one POST, one project).
* **Lost response:** the client never retries. It performs one read-only reconciliation by request id; if the project exists it proceeds,
  otherwise it shows **"Result unknown — refresh the Library"** with *no* retry control. The request identity lives in the URL hash
  (`#new-project:<id>`) — **not** in browser storage, which a pinned product test forbids in the production bundle — so a reload shows
  the same reconciliation notice. A server failure after a possible partial write returns `CREATE_OUTCOME_UNKNOWN` (500), never "not created".
* **Documented limit:** the stamp is written *after* the create by a second canonical write. A crash between the two leaves a project without
  a stamp; that outcome is reported as unknown, never as "not created", and an atomic idempotent create needs a change to the protected
  creation writers — **owner-gated** (`08_OPEN_OWNER_AUTHORIZATIONS.md` item 3).

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
