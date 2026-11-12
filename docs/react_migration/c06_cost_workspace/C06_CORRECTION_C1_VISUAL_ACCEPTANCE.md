# C06 Correction C1 — Visual acceptance evidence

All screenshots in this report were produced by the deterministic local checkouts (fresh
seeded synthetic project, real Chromium, `full_page=True`), since the owner screenshots were
not delivered (`SCREENSHOT_SOURCE_UNVERIFIED` — see the ROOT CAUSE report).

## 1. Before (both `main` and #444 — byte-identical CSS, identical geometry)

- `evidence/c1/pr444/inputs-1440.png` / `evidence/c1/main/inputs-1440.png` — 1440 px:
  two-column assumptions grid, labels wrap at word boundaries with a 195 px label column;
  long labels wrap onto two lines ("Merchant Balancing (% of spot sales)"); status notes
  wrap mid-phrase ("Choice / text field — edit on the Revenue sheet").
- `evidence/c1/{pr444,main}/inputs-768.png`, `inputs-390.png` — single column, 234/302 px
  labels, no overflow. `geometry.json` holds the full measured records for both checkouts.

## 2. After (Correction C1 fix, this branch)

- Same three widths re-measured on the corrected tree: computed `overflow-wrap` on
  `.rx-input-table` cells is `break-word`; label widths unchanged at the canonical widths
  (the fix changes the collapse mechanism, not the comfortable-width layout); the new
  browser regression asserts width ≥ 100 px / height ≤ 90 px / no page overflow and passes.
- Screenshot set from the regression test at 1440 and 390 (`C06_SCREENSHOT_DIR`), plus the
  C2 CAPEX screenshot (`c06-c2-capex-months.png`).

## 3. Other Inputs screens smoke coverage

- 1440/768/390 page-level overflow asserted `scrollWidth - innerWidth ≤ 1` in the new tests
  and in the existing `test_rcux_capex_studio_fits_every_viewport` (320/390/768/1440) and
  the WF03 visible-archive matrix (320/390/768/1440 × 4 templates × themes) — all executed
  by the hosted browser role at the final HEAD.
- Project/Technical/PPA/Balancing/Tax sections all render through the same
  `.rx-input-table` contract — the single shared fix covers them; the compact-density
  variant keeps its existing explicit `word-break: normal` unit-column exception.

## 4. Mobile (390 px)

Deliberate stacked layout: the assumptions grid collapses to one column (328 px content,
302 px labels), CAPEX month columns are not rendered on narrow screens (the line inspector
carries per-line months, per the shipped PR2B design), and no horizontal page overflow is
permitted — asserted, not assumed.

## 5. Hosted gates

See `C06_CORRECTION_C_BROWSER_AND_CI_EVIDENCE.md` for the six hosted workflow verdicts at
the final HEAD; the Browser role's consolidated PNG/CRC/junit verifier runs unchanged.
