# FIN-VAL — authoritative rate-unit contract

Financial Owner authorized a targeted F01 correction in `app/input_adapter.py`, `app/persistence/projects_repository.py`, `app/v2/router.py`, then explicitly added `app/services/project_library_service.py` and `app/workbook/update_service.py`. Application changes remain within these five paths. This authorizes engineering review, not release activation or historical migration.

| Intended rate | UI/scalar snapshot | Typed annual ratio |
|---|---:|---:|
| 0.056% | 0.056 | 0.00056 |
| 0.56% | 0.56 | 0.0056 |
| 5.60% | 5.6 | 0.056 |
| 9.00% | 9.0 | 0.09 |

Every new canonical scalar rate is explicitly identified by `_finval_interest_rate_unit: human_percent_v1`. A version marker is required for saved scalar materialization. Missing, boolean, ratio-labelled, unsupported-version and forged unit values fail closed. The scalar schema path's semantic pct field already states human percent. Values must be finite, non-boolean and between 0 and 20, matching the existing registry range; no new business cap is introduced.

Display is `value%`, with significant precision sufficient to retain 0.056%; no interest-rate magnitude heuristic is permitted. Other unrelated percentage fields retain their existing presentation in this narrowly scoped PR.

The only scalar percent-to-ratio conversion is `_set_financing_interest_rate(value / 100)`. An exact economically identical flat rate preserves the original typed schedule and auxiliary base/margin state. A non-flat calibrated schedule is not flattened. Existing bankability ownership rejects competing scalar edits and its explicit percentage vector remains authoritative.

## Atomicity and existing provenance

New copy construction places rate and unit in the same snapshot before independent workspace/base-case creation. The source reference is never updated. Individual Save requires verified provenance and preserves the marker through the existing atomic CAS writer. Batch Save validates the same provenance through `apply_field_to_pis`; only the approved rate key changes, while the verified unit marker remains in the same transactional snapshot. No post-commit metadata write or second save is used.

A Save is not permission to invent historical provenance. Untagged existing records require explicit owner classification/repair; they are not converted just because a number looks like a ratio. This is a safe fail-closed candidate, not a migration or universal backwards-compatibility claim.

## Security and economics

Authentication, ownership, CSRF, composite hash, workbook version, scenario scope, reference refusal and D-029 original binding/fencing/replay remain unchanged. Unit metadata participates in the existing snapshot/composite identity; it cannot be set via a user-editable registry field. No engine formula, solver, tolerance, IRR economics, protected reference or committed historical Run is changed.

Re-saving identical economic inputs must preserve typed financing exactly and the canonical engine's numerical identity. Intentionally changing 5.5% to 0.056%, 0.56%, 5.6% or 9% changes economics: interest, debt sizing, cash flows and returns may differ or the model may legitimately fail closed. These cases must never be reported as bit-identical.
