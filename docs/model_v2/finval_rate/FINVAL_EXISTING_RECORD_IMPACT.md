# FIN-VAL — existing-record impact and owner migration proposal

**No migration was run. No hosted/project database was inventoried or modified.** Evidence uses disposable local databases only. This is a source-path inventory and a proposal for a later owner-authorized read-only inventory/repair operation.

## Record classes and reliable detection

| Class | Acceptable provenance | Treatment |
|---|---|---|
| Verified canonical percentage | Explicit supported unit marker plus consistent immutable creation/save evidence | Read as human percent; validate finite range and actual typed authority |
| Verified historical ratio | Exact historical producer/source blob plus immutable creation payload and proof of no intervening rate edit | Candidate owner-approved conversion into a new working draft; never infer from value |
| Calibrated schedule authority | Complete valid typed non-flat vector or validated bankability rates_pct configuration, tied to project identity | Preserve schedule; auxiliary scalar is not permission to flatten it; any metadata repair remains separately reviewed |
| Ambiguous | No unit/version, mixed legacy/React edits, only template name or numeric magnitude available | Do not convert; owner resolves from source evidence or creates a fresh verified copy |
| Corrupted/invalid | Non-finite rate, malformed/mismatched unit/version/config, broken ownership or invalid typed schedule | Refuse; investigate corruption before repair |

Source factories store typed ratios; older `_compute_baseline_snapshot` and `main_web._project_baseline_snapshot` wrote ratio scalars. Reference clones copied source snapshots. Legacy/React V2 registry edits store human pct, but older records do not distinguish those edits from seed values with a version marker. Workbook imports map semantic registry fields and can have known percent intent at import time; an unversioned exported/imported snapshot alone does not prove that provenance. Historic migrations and manual DB changes require their immutable execution logs. New corrected clones are explicitly marked. No claim is made that every unversioned record has faulty economics.

## Exact proposed repair procedure — requires separate authorization

1. Select the intended environment explicitly and pause financial writes for a consistent inventory. Record code SHA/tree, schema, workbook version and immutable inventory time. Use a read-only DB connection initially.
2. Create a verified SQLite backup including WAL-consistent state; encrypt it, record SHA256, record count, schema and restore location. Perform a restore drill in isolation before any repair.
3. Export immutable evidence for each candidate: owner/project/workspace/scenario identity, exact raw saved/draft snapshot bytes and hashes, marker/config provenance, current composite hashes, full prior history row identities and hashes. Never record session/CSRF secrets.
4. Classify from source/event provenance, not magnitude. Owner signs the exact record set and proposed old/new human rate. Ambiguous records stay blocked or are replaced by fresh working copies.
5. In a separate diagnostic copy, calculate both explicitly documented economic interpretations through unchanged engine formulas. Compare first-period/annual interest, debt service, CFADS, debt size, Pure Equity IRR and Total Sponsor XIRR, including explicit refusal outcomes. Distinguish unchanged intent from deliberate corrections.
6. Proposed repair is a new draft revision with approved canonical percentage and unit marker committed atomically under owner/project/scenario CAS. Retain old bytes and classification evidence. Do not mutate saved committed evidence or prior Runs.
7. Require a deliberate new Run after repair. It creates a new history identity; prior Runs remain immutable and may be marked externally as originating from an earlier convention without editing their payloads.
8. Rollback uses a new compensating draft revision referencing the repair event; never delete/rewrite historical Runs or reuse a D-029 key. Stop on any unmatched hash or intervening write. Verify snapshot and history hashes after both repair and rollback drill.

## Activation blockers

The candidate deliberately blocks saved scalar materialization with missing/unsupported provenance. Existing data must therefore receive an explicit owner disposition before rollout. The additional unversioned legacy producer in `main_web.py` is outside the authorized source scope; it also needs a separately authorized correction, or an explicit decision to keep that route unavailable. Do not silently substitute factory pricing to avoid these gates. No deployment or activation is authorized by this investigation.
