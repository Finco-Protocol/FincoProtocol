# Model V2 Persistence & Canonical Run Binding Contract (Workflow 07)

Status: ACTIVE (epic/model-saas-v2, Workflow 07)
Authority: `app/model_v2/persistence.py`
Persistence surface: `workspace_states.model_v2_working_state_json` (additive column)
Run binding surface: `workspace_states.last_runtime_identity_json["model_v2"]`

This document is the contract for turning the Model V2 composition contracts
(Workflow 02 `RevenuePlan`, Workflow 03 `CostTemplate` materialization,
Workflow 05 selection wrappers) from an in-memory architecture into a durable
run lifecycle. It preserves the fundamental product invariant:

    WORKING COPY != LAST RUN

A failed or incomplete run never overwrites the last successful run.

---

## 1. Persisted Working Copy V2 state

**Location.** The Model V2 selection state is persisted on the existing
`workspace_states` row (1:1 per `(user_id, project_id)`) in the new additive
column `model_v2_working_state_json TEXT NOT NULL DEFAULT ''`. There is no
second database and no ad-hoc JSON file store. The column is written through
the existing `app/persistence` authorities:

- `save_workspace_state(..., model_v2_working_state=None)` — `None` (the
  default for every legacy caller) **merge-preserves** the stored payload;
  legacy saves can never invent or erase V2 state.
- `set_workspace_model_v2_state(user_id, project_id, state)` — validates,
  binds, and replaces the payload via a narrow single-column UPDATE (no other
  column on the row is read or rewritten, so concurrent draft/row mutations
  can never be silently reverted by it).
- `clear_workspace_model_v2_state(user_id, project_id)` — explicitly returns
  the row to the exact legacy absence (`''`).
- `get_workspace_model_v2_state(user_id, project_id)` — decodes fail-closed;
  `None` means "no V2 selections" (the legacy state).

**Payload.** A versioned JSON document:

```json
{
  "_schema": "finco.model-v2.working-state",
  "schema_version": 1,
  "working_copy_ref": "<project_code of the owning workspace>",
  "revenue_plan_selection": null | {
      "source_ref": "...", "scenario_id": null,
      "plan": {"_schema": "finco.model-v2.revenue-plan", "schema_version": 1,
                "streams": [...], "allocation_groups": [...],
                "market_price": null | {...}}},
  "cost_template_selection": null | {
      "template_id": "...", "version": 3, "source_ref": "...",
      "materialization_plan": {"_schema": "finco.model-v2.materialization-plan",
                                "schema_version": 1, ...}}
}
```

Only economically authoritative Working Copy input is persisted: the selected
typed `RevenuePlan` payload and the Workflow 05 materialization plan with the
immutable `(template_id, version)` identity. Presentation copies of values the
canonical project state already owns are NOT duplicated; run outputs,
analytics, Last Run payloads and presentation metadata have no place here.

**Identity binding.** `working_copy_ref` must equal the workspace's
`project_code` — the working-copy identity the existing runtime semantics
already use. EVERY path that writes a supplied state enforces this
(`set_workspace_model_v2_state` AND `save_workspace_state(...,
model_v2_working_state=...)`); a foreign ref fails closed before any
mutation. A read whose stored ref no longer matches the row fails closed with
`MODEL_V2_WORKING_COPY_REF_MISMATCH` instead of composing another working
copy's economics. There is no alternate project identity system.

`project_code` is not contractually immutable, so a project_code change can
never silently retain a merge-preserved payload bound to the OLD identity:
`save_workspace_state` fails closed with
`MODEL_V2_WORKING_COPY_REF_REBIND_REQUIRED` unless the same save explicitly
clears the V2 payload or supplies an explicitly rebound state.

## 2. Serialization schema / version

- Deterministic canonical JSON: `sort_keys=True`, `ensure_ascii=True`,
  `allow_nan=False`, compact separators. Same state ⇒ same bytes.
- Explicit `_schema` + integer `schema_version` on every payload level
  (working state `1`, revenue plan `1`, materialization plan `1`, run binding `1`).
- The decoder accepts exactly the supported version. Unknown `_schema`,
  future `schema_version`, unknown keys at ANY object level, missing keys,
  non-JSON-native objects, NaN/Infinity tokens and malformed numerics all
  raise `ModelV2PersistenceError` (fail closed — never guessed, never
  defaulted).
- ENCODE SYMMETRY (Correction A): every encoder validates its input with the
  same strict rules the decoder applies — applicability/economic flags must
  be strict booleans (a string `"false"` is never coerced through
  `bool()`), numerics must be finite non-bool numbers, identity/label
  strings must be strings — so the encoder and decoder accept exactly the
  same valid domain and this boundary can never write a payload it could
  not read back.
- No raw pickle, no arbitrary Python object representations.
- **Migration seam.** A future schema change ships a new version constant and
  extends `working_state_from_payload` to accept the old and the new version
  explicitly (never a silent passthrough). Additive non-economic fields are
  only tolerated when a future contract explicitly justifies them; today the
  decoder is strictly exact-key-set.

## 3. MISSING vs ZERO and exact round-trip

Round-trip is exact for economically authoritative data:

- `None` stays `None` (residual merchant `volume_share`, unlimited
  `term_years`, absent contingency, `market_price`, …) — MISSING remains
  MISSING; it never becomes `0.0`.
- Explicit `0.0` stays legitimate ZERO (0% contingency active, zero floor,
  zero share) — ZERO never becomes MISSING.
- `False` stays `False` (strict booleans; SQLite/JSON coercion cannot
  smuggle `0`/`"false"` into applicability flags).
- Empty tuples stay empty tuples (`indexed_fit_index_factors=()` fails
  validation exactly as before — a lost `[]` cannot silently revalidate).
- Enum members restore to the same typed meaning; unknown values fail closed.
- Numeric representation is preserved **verbatim** (int stays int, float stays
  float): the Workflow 05 canonical plan JSON (`_plan_canonical_json`) is
  int/float-sensitive, so coercing `15` to `15.0` would silently change the
  composition identity. Decoding validates finiteness and rejects bools-as-
  numbers but never converts.
- Stream ordering is canonicalized to `ordered_streams()` (the Workflow 02
  identity order). Declaration order is not part of canonical identity; two
  economically identical plans serialize to the same bytes regardless of
  declaration order.
- `schedule_json` (JSON-inside-JSON) and `replay_metadata` / `scalar_metadata`
  / `lineage` dicts are carried verbatim; repeated decodes never share nested
  mutable objects.
- COST IDENTITY CONSISTENCY (Correction A): a `CostTemplateSelection` and its
  `MaterializationPlan` must name the SAME `(template_id, version)` on encode
  and on decode (`MODEL_V2_COST_IDENTITY_INCONSISTENT` otherwise) — a
  structurally contradictory cost authority is never persisted merely because
  Workflow 05 would reject it later.

## 4. Legacy absence semantics

A legacy project (no Model V2 state) opens normally, loads with no
`RevenuePlanSelection`, no `CostTemplateSelection`, and composition returns
`LEGACY_PASSTHROUGH` exactly as before. Save / re-save never materializes V2
selections (`''` is preserved, never defaulted to an invented state). Old
records remain readable — the column is additive with a default; there is no
destructive migration and no bulk back-fill.

## 5. Run identity relationship

The canonical run identity remains the EXISTING authority: `run_id`
(runs table), `last_runtime_snapshot_id`, workbook `composite_hash`
(`last_runtime_composite_hash`), `engine_version`, `scenario` binding.
Workflow 07 does NOT introduce a competing identity.

After a successful composition + canonical engine run,
`v2_atomic_run_commit(..., model_v2_run_binding=...)` embeds a validated
binding payload under the `"model_v2"` key of `last_runtime_identity_json`
INSIDE the same `BEGIN EXCLUSIVE` transaction:

```json
{"_schema": "finco.model-v2.run-binding", "schema_version": 1,
 "working_copy_ref": "...",
 "composition_hash": "<Workflow 05 composition identity, scenario-inclusive>",
 "economic_identity": "<selection_digest, scenario-independent>",
 "scenario_id": null | "...",
 "snapshot_id": "<the run's runtime_snapshot_id>"}
```

**Run correlation.** The binding carries the `snapshot_id` of the run that
committed it. `v2_atomic_run_commit` fails closed (`ROLLBACK`) when the
binding's `snapshot_id` or `working_copy_ref` does not match the run/row it
is committing. This correlation is what prevents misattributed provenance: a
later run that does not pass a binding forward (e.g. a legacy `/run` request)
replaces the Last Run evidence without touching `last_runtime_identity_json`,
and the stale binding then refers to an OLDER run — it must never be reported
as the provenance of the current Last Run.

**Atomic V2-state CAS (Correction A).** The V2 Working Copy payload is NOT
part of the workbook composite hash, so a concurrent V2 edit during the
engine run would pass the legacy composite CAS silently. Inside the SAME
`BEGIN EXCLUSIVE` transaction, whenever a binding is supplied the commit
additionally: decodes the CURRENT persisted `model_v2_working_state_json`,
requires it to exist and be readable, requires its `working_copy_ref` to
match the row, and requires its `selection_digest()` to equal the binding's
`economic_identity`. Any mismatch raises the typed
`V2RunCommitConflictError` (`MODEL_V2_RUN_COMMIT_STALE_V2_STATE` /
`_V2_STATE_MISSING` / `_V2_STATE_UNREADABLE`) and rolls the whole commit
back — a run is never committed against stale V2 state.

**Scenario binding (Correction A).** The binding's `scenario_id` must equal
the scenario the commit actually persists for the Last Run — the existing
`last_runtime_scenario_id` authority with its `active_scenario_id` fallback.
A scenario binding on a base run, or a base binding on a scenario run, fails
closed (`MODEL_V2_RUN_BINDING_SCENARIO_MISMATCH`, full rollback). No new
scenario naming convention is invented.

**Legacy-passthrough binding rejection (Correction A).**
`build_run_binding_payload` fails closed on a selection-less state — a
legacy-passthrough run is represented by the ABSENCE of a `model_v2`
binding, never by an empty one.

The relationship is therefore: Last Run → identifies the exact canonical run
(snapshot id / composite hash / engine version) → identifies the composed V2
input state (composition hash + economic identity) → comparable against the
CURRENT Working Copy for staleness.

**`composition_hash` is not the run identity.** It identifies the composed
input state; the run is identified by the existing run/snapshot identity. The
workbook composite hash is likewise never overwritten by the V2 composition
hash. A legacy-passthrough run carries NO `model_v2` binding (there is no V2
economic state to prove).

## 6. Last Run atomicity

The only writer of the V2 binding is `v2_atomic_run_commit` — the existing
atomic successful-run path (single `BEGIN EXCLUSIVE`, final composite-hash
CAS). Required eligibility is unchanged: composition success + engine success
+ run evidence success ⇒ eligible to commit. Any earlier failure
(composition failure — which raises and never produces inputs; unsupported
revenue bridge; invalid cost materialization; engine exception; timeout;
validation failure; run-evidence failure; persistence failure) leaves the
prior successful Last Run untouched. The commit itself validates the binding
payload, its `working_copy_ref`, its `snapshot_id`, its `scenario_id`
against the row/commit, AND the current persisted V2 state's economic
identity (Correction A) inside the same exclusive transaction; any of those
checks failing aborts the whole transaction (rollback — no partial Last Run,
no clearing of the old evidence). The complete proven failure matrix: legacy
workbook CAS conflict, concurrent Model V2 economic edit, corrupt binding,
foreign working_copy_ref, snapshot mismatch, scenario mismatch, and
persistence/decode failure — after each, the prior Last Run, its identity,
and the current Working Copy V2 state are unchanged. The commit never writes the V2 Working Copy
payload column — promotion of draft→saved applies to the legacy snapshot
only; V2 selections are independent Working Copy state.

## 7. Stale-state semantics

The workspace-level authority is
`resolve_workspace_model_v2_staleness(workspace_record, current_state)`: it
first verifies the binding still describes the CURRENT Last Run
(`binding["snapshot_id"] == last_runtime_snapshot_id`); if the binding
belongs to an older run (a legacy run replaced the Last Run evidence), the
result is `NOT_APPLICABLE` — the legacy freshness authorities govern that
run. Only a correlated binding is compared economically. `current_state`
semantics: OMITTED → the persisted payload is decoded through the canonical
decoder (ref verified against the row, fail closed) and the answer comes
from the PERSISTED state; explicit `None` → the selections are treated as
removed; an explicit state is used verbatim. The omitted form and the
explicitly decoded form always agree.

The pure comparison,
`resolve_model_v2_staleness(current_state, run_binding)`, is deterministic
and reuses the existing canonical authority
`ModelV2WorkingState.selection_digest()` as the comparison basis:

- No binding on the Last Run → `NOT_APPLICABLE` (legacy freshness authorities
  remain the only truth; V2 adds nothing).
- Binding present + no current V2 selections → `STALE` (the selections that
  produced the run were removed — removal is an economic change).
- Otherwise → `CURRENT` iff `selection_digest(current) == binding
  ["economic_identity"]`, else `STALE`.

Presentation-only metadata that the canonical identity excludes (cost plan
labels, parent codes, sub-line granules, contingency lineage, eligible basis
— via `economic_cost_payload`) cannot create a false STALE. Plan-level
metadata the Workflow 02 canonical plan JSON includes (stream `name`,
`counterparty`, `lender_eligible`) is treated as input authority by the
existing identity and therefore participates in staleness — Workflow 07 does
not re-litigate that merged authority. The workbook composite hash and its
`resolve_runtime_freshness` authority are unchanged and remain responsible
for non-V2 input freshness.

## 8. Failed-run preservation (proven)

Acceptance sequence (`tests/test_model_v2_run_binding.py`):

1. Run A succeeds → Last Run = A, binding = A's composition identity.
2. Working Copy changes to W2 → Last Run remains A, staleness = STALE.
3. Run B fails during **composition** (unsupported stream raises) → nothing
   is committed; Last Run remains A.
4. Run B' fails during the **commit window** (CAS conflict or corrupt
   binding) → `BEGIN EXCLUSIVE` rollback; Last Run remains A; no partial
   state.
5. Run C fails during **engine execution** → the pipeline only reaches the
   commit after engine success, so nothing is written; Last Run remains A.
6. Run D succeeds → Last Run atomically becomes D (snapshot id, composite
   hash, binding all replaced in one transaction); staleness = CURRENT.

Historical runs remain reconstructible through the existing `runs` /
run-history semantics; Workflow 07 adds no new run-history store.

## 9. Scenario distinction

A scenario run carries its scenario id inside the binding payload, and the
Workflow 05 composition hash includes the carried scenario context — so a
scenario run is always distinguishable from the base-case run while the
scenario-independent economic identity stays comparable for base-case
staleness. Scenario overrides ride the per-run composition context only and
are never persisted back into the base Working Copy state; a scenario
execution cannot silently overwrite base Working Copy V2 state.

## 10. Save As / clone behavior

Reusing the existing product contract exactly: Save As / working-copy clone
creates a NEW project id and a FRESH workspace (draft=saved=baseline,
identity-sanitized), and never inherits workspace-scoped state. Therefore:

- the clone receives its own (empty) V2 state — selections are NOT cloned
  (they are working-copy edits, like CAPEX/OPEX sub-line edits, which Save As
  also does not copy);
- no Last Run evidence and no V2 run binding is inherited;
- immutable `(template_id, version)` identity is only ever present where a
  selection was explicitly re-made on the clone;
- editing the clone never mutates the source project's V2 state;
- restored V2 objects never share mutable nested references with the stored
  payload or with other decodes.

## 11. Future Workflow 05B compatibility

Workflow 07 persists the CURRENT typed `RevenuePlan` faithfully and
unconditionally — a valid typed plan is saveable even when some stream types
currently fail closed at runtime composition (forward-compatible Working Copy
semantics). When Workflow 05B extends runtime support, no persisted payload
changes are required: the same schema version continues to decode; new
runtime behavior changes economics only through composition, not through
persistence. `domain/revenue/**` and `app/services/model_v2_composition/**`
were NOT modified by Workflow 07 (the codec reads their public typed
contracts).

## 12. Explicit out of scope

Analytics is derived RUN OUTPUT, not Working Copy input. Workflow 07 does not
persist a `CanonicalAnalyticsSnapshot` (Workflow 06 owns that contract, being
developed in parallel), and no analytics/output persistence exists in this
branch. Developer Economics, Working Capital, Goal Seek, Compare, UI, XLSX
extensions, new public API surface, quarterly periods, Storage and US tax are
out of scope.

## 13. Security / data hygiene

No secrets, API keys, signing secrets, external credentials or runtime
session tokens are persisted in the V2 payload. Arbitrary exception internals
are never embedded in persisted failure records. The payload encoder refuses
non-JSON-native objects, closing the pickle/object-injection surface.
