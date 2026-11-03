# D13 Q1(A) — dormant profile: implementation contract (NOT implemented)

Status: `CONTRACT_BLOCKED_OWNER_Q1`. This document specifies the change so that an owner decision on Q1 can be implemented and verified
independently. U2 does not implement it.

## Q1 (owner question)
When a profiled line is retired, should the Run (A) treat its stored profile as **dormant**, ignored with a disclosure, or (B) keep refusing until the
user acts, which is today's behaviour?

## Q1(A) semantics
1. The stored document is never edited by retire or reactivate (unchanged).
2. Binding: a stored item whose leaf is inactive and has `amount_keur = 0` in the fold is **dormant**. It is excluded from the weights, and every
   other item binds exactly as today.
3. A stored item whose key names no line at all (never existed, or hard-deleted) still refuses with `CAPEX_PROFILE_LEAF_UNKNOWN`.
4. Run evidence lists dormant keys (`capex_profile.dormant_keys`). The Run economics equal those of a Run with the item removed from the document.
5. Reactivation makes the item active again with no user step. The next Run equals a Run with the same document before the retire.
6. Save profile still refuses unknown keys. Dormant keys are preserved when the Studio saves (it must send them through unchanged).

## Oracle (to be written with the implementation)
* O1: Run(retired, dormant) economics == Run(document without that item), to the cent, for solar / wind / data_center / ev_charging.
* O2: Run(reactivated) == Run(before retire) for the same document.
* O3: the document bytes are identical before retire, after retire and after reactivation.

## Negatives
* N1: an unknown key (never a line) → refused, no history row.
* N2: a dormant key whose line is reactivated with a different amount → the weights apply to the new amount; no stale cache.
* N3: scenario-bound projects keep `CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED`.
* N4: historical Runs are byte-identical before and after the change (no back-fill).

## Files that would change (each sealed; needs its own reviewed successor)
`app/capex_profiles/binding.py`, `app/capex_profiles/runtime.py` (the engine-adjacent binding), the Studio save payload, and the protected test L2,
which flips from "refused" to "dormant". This is a change of signed Run semantics and therefore needs the Financial Owner.
