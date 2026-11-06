# UX-PR2a — inline CAPEX months / OPEX years (Draft, stacked on UX-PR1 #426)

Delivered (read-only, server-authoritative): an optional **Months** / **Years** toggle in the dense desktop Lines grid.
- CAPEX: `Σ %` and `M1…Mn` per line = the canonical server preview (`GET capex/preview`) of the SAVED profile document. No browser allocation, rounding or summing.
- OPEX: `Y1…Yn` per saved line = the existing server saved-line projection (`GET opex-projection/lines`). Not Last Run all-in OPEX (G10 stays its own default-OFF panel).
- Unavailable is a dash with the reason (never 0): model-default timing, added lines (D-13), inactive lines, preview failure. Staged edits are flagged as NOT reflected until saved.
- Off by default; PR1's compact grid and its 25-row acceptance are unchanged. Mobile keeps the inspector (no timeline columns).

DEFERRED (exact reasons): inline profile selector / Monthly-% cells (needs one shared profile draft with CapexStudio; a second draft state could drift; profile Save stays separate),
model-default monthly amounts (no server read model), annual OPEX editing (D-09), atomic amount+profile Save (PR2c/D-01), profiles on added lines (PR2d/D-13).
Governance successor for the changed shared files is NOT included: UX-PR1's closed cohort rejects any path outside its literal set, so a later cohort needs a bounded hook in that Opus-owned module.
