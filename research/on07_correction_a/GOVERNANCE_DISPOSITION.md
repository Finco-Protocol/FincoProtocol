# ON-07 research - governance disposition after #404 (supersedes the `BLOCKED_SOURCE_GOVERNANCE` status of `SOURCE_GOVERNANCE_DECISION.md`)

Status of the ON-07 material: **research evidence only** (`PARTIAL`). It is **not** financial authority, **not** a `COMMITTED_RUN`, **not** `LIVE_UI_PARITY`, and `PRODUCTION_READY=false`.

## Why it is admitted and how (finite, path-limited)
The repository's exact-source governance is a closed world over changed paths (see `SOURCE_GOVERNANCE_DECISION.md`, root cause proven there). The Owner's post-#404 instruction authorises a *narrow, auditable, path-limited research admission*. It is implemented as one additive layer of the WF-03 exact-source successor:

- `tests/wf03_lifecycle_scope.py::RESEARCH_PATHS` lists every admitted file literally (the two directories `research/on07_baseline_post399/` and `research/on07_correction_a/` only).
- `docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json` pins each file by exact Git blob and records a ledger entry (before blob `null`: new file).
- Any added, deleted or modified byte under those directories, and any other path under `research/`, fails closed; no wildcard, no extension allowlist, no `.github/` exception, no change to a historical pin, F01 validator or financial/security test.

## Content rules kept
Synthetic, non-sensitive data only; no credentials, no private outputs, no competitor content; no `finmodels.io` parity claim. Owner decisions OD-1..OD-7 stay `UNRESOLVED` (see `README_FIRST.md` and the limitation ledgers); WND-02 (original) stays refused on SHL maturity and WND-02-R stays an unaccepted replacement.
