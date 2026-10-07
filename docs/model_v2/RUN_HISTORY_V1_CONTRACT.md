# Model V2 Run History V1 — Append-Only Canonical Successful-Run Ledger

Status: ACTIVE backend-only workstream on `epic/model-saas-v2`. Authority:
`app/persistence/run_history_repository.py` over the additive SQLite table
`model_run_history` (schema in `app/persistence/db.py`). Last Run semantics
are unchanged and remain the only authority for current visible successful
output, staleness and Working Copy vs Last Run. Run History V1 adds
historical evidence and must not replace or weaken Last Run.

## Model

    Working Copy
        ↓ successful canonical run
    atomic Last Run promotion  +  append immutable history row

Failed runs never create a history row: only the successful commit paths
reach the append.

## Append-only semantics

Rows are immutable after insertion. There is no update method, no
delete/restore surface, no overwrite-by-project and no "latest replaces
old". A second successful run appends a second row:

    Run A success  → History A
    Working Copy changes → History A unchanged
    Run B fails    → no History B row
    Run C succeeds → History A + History C; Last Run points to C

## Transaction atomicity

The append executes INSIDE the existing canonical run-commit transactions —
never a second commit path:

- V2 path: `v2_atomic_run_commit` appends via
  `append_run_history_cursor` inside its `BEGIN EXCLUSIVE` transaction,
  after the workspace UPDATE and before COMMIT.
- Legacy path: `record_workspace_runtime` prepares a validated payload and
  passes it to `save_workspace_state(run_history_payload=...)`, which
  appends inside the save's transaction. Because the shared persistence
  connection runs in autocommit mode, a history-bearing save opens an
  explicit `BEGIN IMMEDIATE` so the promotion and the append commit or
  roll back together.

If the history insert fails, the whole transaction — including the Last
Run promotion — rolls back. "Last Run = C but History C missing" and
"History C without its Last Run promotion" are unrepresentable.

## Record contract

One row per successful canonical run capturing the canonical evidence that
already exists at commit time: `history_id` (immutable uuid hex),
`user_id`, `project_id`, `project_code`, `runtime_snapshot_id`,
`runtime_origin`, `ran_at`, `engine_version`, `workbook_version`,
`active_scenario_id`, `active_scenario_name`,
`last_runtime_scenario_id`, `composite_hash`,
`last_runtime_identity_json` (verbatim Workflow 07 identity payload —
including the `model_v2` binding when present), the five runtime schedule
snapshots (financial statements, debt, tax, distribution, sponsor) by
value as canonical JSON, `integrity_evidence_json`,
`replay_metadata_json`, `created_at`. No new finance outputs are invented;
structured payloads follow the repository's canonical JSON conventions
(`sort_keys`, ASCII, no NaN, compact separators) — no pickle.

## Run identity correlation (fail closed before commit)

`prepare_run_history_payload` validates, before the commit:

- `binding.snapshot_id == runtime_snapshot_id`
- `binding.working_copy_ref == project_code`
- `binding.scenario_id == last_runtime_scenario_id` (the scenario the
  commit actually persists)

using the same Workflow 07 binding the commit validates. Mismatch raises
typed `RUN_HISTORY_BINDING_{SNAPSHOT|REF|SCENARIO}_MISMATCH` and nothing
is written.

## Legacy vs V2

A legacy canonical run history row has NO invented Model V2 binding and no
captured composite identity (both contractually absent); engine/workbook
versions come from the canonical version authorities at commit time. A V2
row preserves the exact Workflow 07 binding verbatim. An older V2 binding
is never attached to a later legacy run: each row carries only the
identity of the run that actually executed.

## Scenario distinction

Base and scenario runs produce distinct rows with distinct canonical
scenario identity (`last_runtime_scenario_id` and the binding's
`scenario_id`); scenario is never inferred from display text.

## Payload immutability

Snapshots are persisted by value at commit time. Later Working Copy edits,
scenario edits or project renames never mutate historical rows; a
historical run's identity/evidence stays reconstructible from its record.

## Ordering / retention / reads

Reads order by `ran_at DESC` with the immutable `history_id` as the
deterministic tie-breaker; incidental SQLite ordering is never relied on.
Read surface: `get_run_history`, `get_run_history_entry`,
`get_latest_history_entry` (fail-closed decode — malformed stored rows
raise `RUN_HISTORY_PAYLOAD_MALFORMED` rather than half-decoding). V1 does
not prune, expire or auto-delete anything; storage policy is a future
reviewed feature.

## Explicit no-restore scope

Run History V1 is READ-ONLY historical evidence. Restore Working Copy,
Revert Project, Clone from Run and Promote-old-run-to-Last-Run are later
workflows. No UI, no public API endpoints, no raw SQL outside the
persistence layer in V1. Existing workspaces open unchanged; history
starts prospectively — nothing is back-filled or synthesized from the
current Last Run.
