# Financial Owner decision register

Nothing below is implemented. Each item changes, or could change, financial numbers or methodology and therefore needs a Financial Owner decision before any engineering.

| ID | Topic | Observed (evidence) | Options | Engineering recommendation |
|---|---|---|---|---|
| FO-1 | Scalar OPEX vs seeded OPEX lines | A scalar `opex.lines.*` value for a group whose seeded lines replace it reaches `ProjectInputs` (adapter) but is removed by `fold_opex_with_provenance` before the engine; 4 groups on Solar/Wind, 6–8 groups on Data Center/EV, plus B.08 on DC/EV (matrix) | (a) scalar wins; (b) scalar adds to lines; (c) keep lines authoritative and retire/lock the scalar | (c) — already what the Run does; B2/C1 shows the cell read-only without changing any number |
| FO-2 | Append-at-default-inflation branch | `build_effective_draft_opex` appends a canonical-named item at 2 % inflation when the base has no item for the group | keep / require explicit inflation / remove | Decide with FO-1; no change now |
| FO-3 | Additive double-count risk for appended groups | An appended group could be added **in addition** to seeded lines of the same canonical name if the fold did not drop it; the fold currently drops it (shadowing) | confirm the fold is the contract; add an invariant test | Financial Owner to confirm |
| FO-4 | API Save of a shadowed field is still accepted | `POST /v2/workbook/update` for a shadowed field returns success although the Run ignores it | refuse with an explicit message / accept and label | Prefer refuse-with-reason; needs owner sign-off because it changes API behaviour |
| FO-5 | OPEX non-negative floor (E-class) | Engine clamps negative OPEX with `max(0.0, …)`; negative Save was silently ignored | accept clamp / refuse at Save | **Implemented as refuse at Save** (`min_value=0`, 11 fields), consistent with the engine and the CAPEX contract; flagged here because it narrows an accepted input |
| FO-6 | CAPEX scalar fields are decorative in seeded copies | All 14 scalar edits changed no Run total on any technology; sub-lines replace category bases | lock cells / map scalar to a line / keep | Owner decision; B1 already added non-negative bounds only |
| FO-7 | Display vs Run for unfolded inputs | The legacy page shows the adapter view; the Run uses the folded view | align display to the folded view | Owner decision; B2/C1 only labels read-only cells |
| FO-8 | D-028 economic warning/limit policy | Finite but absurd capacities (1e305 MW) are accepted | warning / soft limit / hard business cap | Not an engineering choice; no cap implemented |
| FO-9 | N-1 / N-2 IRR status propagation | Out of scope for B2/C1 | — | Deferred |
| FO-10 | D-029 Run reservation / idempotency / fencing / history | Out of scope; no change to the canonical Run endpoint | — | Deferred to its own mission |
