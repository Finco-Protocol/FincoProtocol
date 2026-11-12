# C06 Correction C1 — Revenue/Balancing label layout: root cause and scope decision

## 1. Screenshot-origin preflight

The two owner screenshots named in Addendum C1
(`screenshots/revenue-assumptions-ppa-commercial.png`, `screenshots/inputs-balancing-co2.png`)
were **not present in the delivered packet** (Downloads contains only the .md addenda; no
`screenshots/` directory). Their deployment SHA, route and surface therefore cannot be
established from evidence: **SCREENSHOT_SOURCE_UNVERIFIED**. Per the addendum, reproduction
was performed on deterministic local checkouts of both code versions instead.

## 2. Deterministic comparison: accepted `main` vs #444 HEAD

Playwright measurement harness (fresh seeded solar project, identical viewport/data/route,
steady state after all async editors mounted):

| width | surface | `main` label width | #444 label width | `main` gridCols | #444 gridCols | overflow |
|---|---|---|---|---|---|---|
| 1440 | Inputs assumptions grid | 195 px (39 px tall max) | 195 px (identical) | 591px 591px | 591px 591px | none |
| 768 | Inputs assumptions grid | 234 px | 234 px (identical) | 706px | 706px | none |
| 390 | Inputs assumptions grid | 302 px | 302 px (identical) | 328px | 328px | none |

`git diff main...HEAD -- frontend/src/styles/ static/react/finco-react.css` was **empty** —
#444 changed no CSS. Conclusion: the reported layout behaviour is **pre-existing on both**
versions, not a C06 regression. The React grid at the canonical widths renders readable
labels; the catastrophic one-character-per-line state in the screenshots requires an
additional squeezing condition that the deterministic checkouts do not reproduce.

## 3. Measured mechanism (the only CSS mechanism in the product that can produce letter-per-line labels)

`frontend/src/styles/rx-mvp-correction.css` (pre-existing on both versions):

```css
.rx-input-table { table-layout: fixed; width: 100%; min-width: 0; }
.rx-card .rx-input-table th, .rx-card .rx-input-table td { … white-space: normal; overflow-wrap: anywhere; }
```

`overflow-wrap: anywhere` changes the **min-content width** calculation: an element's
min-content becomes a single character. Combined with `table-layout: fixed; width: 100%;
min-width: 0`, ANY ancestor squeeze (flex/grid sibling with a large min-content, a hidden
host that fails `hidden` semantics, a future dense container) collapses every label column
to one character per line — exactly the owner-screenshot symptom. The codebase already
carries evidence of this class of bug: `compact-inputs.css` line 29 was previously added to
stop `months` breaking into `month / s` in the unit column (same root mechanism, patched
locally instead of at the contract).

## 4. Minimal fix (shared layout contract, not a one-off override)

- `rx-mvp-correction.css`: `.rx-card .rx-input-table th/td` → `overflow-wrap: break-word`.
  `break-word` keeps word-boundary wrapping and long-token wrapping **without** changing
  min-content sizing, so a squeezed ancestor can no longer collapse a label column to one
  character; narrow containers overflow into their existing scroll boxes instead.
- `compact-inputs.css`: `.ci-summary-table th[scope="row"]` same `anywhere → break-word`
  (same mechanism on the CAPEX/OPEX workbench summaries — same Inputs area, same risk).
- Automated regression added: `test_assumptions_labels_wrap_at_word_boundaries_never_one_character`
  (1440 + 390): computed `overflow-wrap == break-word`, `table-layout: fixed`, min label
  width ≥ 100 px, max label height ≤ 90 px, `scrollWidth - innerWidth ≤ 1`.

## 5. Preserved (Excel-first workflow)

No field ID, unit, editable/read-only semantics, indexation policy explanation, save-one-
field-at-a-time authority, CAPEX/OPEX C06 functionality, profile-only Save, CAS, staging
indicators, retired-line safety, server-authoritative validation, accessibility labels, or
tab order changed. The fix touches two `overflow-wrap` declarations and adds the regression
test; nothing else.

## 6. C1 verdict path

- The reported screens belong to the model-react product surface (not legacy, not a foreign
  deployment) — no `C1_SEPARATE_SURFACE` split is required.
- Screenshot origin: `SCREENSHOT_SOURCE_UNVERIFIED` (files not delivered) — recorded, not
  assumed.
- Fix: minimal, measured, mechanism-correct, with the required automated geometry regression.
- Whether the owner's exact screenshots reproduce byte-identically on their deployment
  remains open until the screenshots or their deployment SHA are provided; the mechanism and
  the fix cover the only letter-per-line production path in this surface.
