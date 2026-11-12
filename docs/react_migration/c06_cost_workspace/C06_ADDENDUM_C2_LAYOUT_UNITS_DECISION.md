# C06 Addendum C2 — CAPEX units, month navigation, consolidated monthly preview: decision

## 1. What the actual defect was (units) — reproduce first, no ×1000

The canonical/API path was traced end-to-end before any change:
`GET capex/profiles` → `GET capex/preview` (server plan, kEUR) → `savedTimeline.ts`
(verbatim server strings, "the browser sums nothing") → `CostLinesGridView.timelineTd`
(raw `<td>` text) — with the grid's `CostUnitSelect`/`showKeur` conversions applying ONLY to
the Amount/per-MW/totals columns, never to the month columns, and **no unit label on any
month column or note**.

Verdict against the owner's three candidate causes (with the Wind Turbines 30,000 kEUR →
M1 2,857.143 example):

1. **No wrong EUR/kEUR factor exists** — the month values are numerically consistent with
   kEUR schedules (the addendum's own analysis agrees); the server plan's reconciles flag
   proves allocation totals equal the line amounts on the canonical basis.
2. **Actual defect: unlabelled units** — Amount/totals follow the selected display unit while
   month cells are exact kEUR server text with no unit marker anywhere in the view.
3. **Precision difference** — months carry full server precision text; the Amount column
   renders at Report precision (0 decimals by default). That display difference is labelled,
   never reconciled away, and never presented as a financial error.

**Fix (labels only, no value conversion):** the CAPEX timeline note now reads
"Monthly cash outflow in **kEUR** — months M1…Mn, exact server text that the browser never
re-rounds…"; every month header names its unit (`title="Month N cash outflow — exact server
value in kEUR"`); the OPEX years note names the selected display unit (`{unit}`). The month
cells deliberately remain the exact server text — converting them in the browser would
violate the shipped PR2B contract (server-authoritative strings, pinned by
`test_rcux_capex…`/PR2B assertions) and would double-round. Existing supported unit control
(`CostUnitSelect`) stays for Amount/per-MW/totals. No stored value is ever reformatted, no
cash-flow math touched, no ×1000 applied.

## 2. Horizontal month navigation (native scroll retained)

- Sticky Line + Amount columns already shipped by ux-pr1 (`position: sticky; left: 0/288px`)
  remain the row-identity mechanism (`scroll-padding-left: 410px`).
- New above-the-grid navigation bar (`data-tl-nav`): `⇤ First` / `‹ Previous months` /
  live `M1–M7 of M20`-style indicator (`data-tl-range`, aria-live) / `Next months ›` /
  `Last ⇥`, driving the SAME single grid's native horizontal scroll (scrollBy ±6×88 px,
  smooth). The indicator is measured from the rendered month header boxes (sticky-column
  offset 410 px accounted), updates on scroll/resize, and never re-renders a second grid —
  no divergent copies, no dual save streams.
- Narrow screens keep the deliberate inspector layout (months per line in the line dialog),
  per the shipped mobile design; the timeline columns simply do not render there.

## 3. Duplicated Monthly preview consolidated (no second data copy)

The separate large per-month matrix (screenshot 02) with Copy table / Download CSV,
Total/Cumulative/Remaining is moved under a collapsed `<details data-capex-expanded-monthly>`
— "Expanded monthly view — per-month table with Copy / CSV (N months, kEUR)" — on the SAME
`plan` object (one canonical server source, zero duplicated state), with `Total (kEUR)` /
`Cumulative (kEUR)` / `Remaining (kEUR)` headers and the explicit note: amounts are exact
server text; with 0-decimal Report precision the sum of rounded visible cells can differ
slightly from the unrounded canonical total; stored values are never changed for display.
The compact per-item allocation status table stays on the default path. The Monthly schedule
tab itself remains the profile editor with its own Save (no functionality removed).

## 4. Preserved guardrails (verified, unchanged)

Profile-only Save (never runs the model), CSRF + composite CAS + readback verification,
100 %-weight validation, explicit/milestone count refusals, undo/redo/discard,
unknown-outcome lock, orphan/retired-profile Run refusal, staged amount vs saved profile
separation, `FINCO_SAVE_ALL_PROFILE_ENABLED=OFF` (no Save All anywhere), OPEX yearly editor
untouched (canonical writer still missing), no R04 Phase 2 scope. The updated
`test_rcux_capex…` assertions additionally now pin that the large matrix is **collapsed by
default** (`open` attribute absent) and open on demand.

## 5. Negative cases retained

99.9 % weight refusals and wrong month counts remain fail-closed through the existing
server validation tests (`CAPEX_PROFILE_WEIGHT_SUM_INVALID` flow in
`test_rcux_capex_explicit_weights_are_validated_by_the_server_never_normalised`, the C06
replay suite, and the profile document validators) — none relaxed.

## 6. Policy boundary

No canonical writer/schema change, no OD-B2 Save All opening, no OPEX yearly writer, no
financial-math change: fully inside the UX-only envelope; nothing is deferred to a
`C06_C2_UX_PARTIAL_POLICY_BLOCKED` state.
