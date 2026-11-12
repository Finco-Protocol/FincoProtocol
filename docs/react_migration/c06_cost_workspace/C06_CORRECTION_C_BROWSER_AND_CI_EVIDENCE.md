# C06 Correction C — Browser & CI Evidence

## 1. Focused reproduction (local, isolated, synthetic data only)

- Exact test at the exact #444 HEAD `6eae95cd…`: reproduced FAILED locally on first run and
  PASSED on immediate re-runs → timing flake confirmed (same machine, same bytes).
- Hosted evidence: artifact `browser-mandatory-suite-evidence` (run `43242867598`) contains
  `wf1-desktop-overview.png` (last passing section) and no inputs screenshot — the failure
  hit between the overview and inputs captures. Hosted stdout shows the failure directly
  after `GET /v2/model-react/fields/revenue status=200` (the async editor's data landing).
- Instrumented hunts (12 iterations × 9 sections + Library; 100 ms in-page flash sampling;
  6× CPU throttling; inputs-window API delays): the transient reproduces only under editor
  latency, matching the hosted ordering; every observed occurrence maps to the
  `fields/revenue` help_text rendering path (see ROOT_CAUSE report).
- Data-path proof: every API the page calls was fetched and grepped on BOTH `main` and #444
  checkouts — `fields/revenue` is the only surface carrying `synthetic` (3 hits, byte-identical
  on both) — proving the violation is pre-existing at accepted `main`.

## 2. Fix verification (local, at the corrected tree)

- Steady-state inputs body (all async editors mounted, 7 s settle): `synthetic` count = **0**;
  15 Technical-note disclosures present; provenance text reachable behind the disclosure.
- Exact hosted-failing test after the fix: **PASSED** locally (twice), and the new
  both-timing-orders test pins the previously-flaky window.
- C1 geometry measurements (Playwright, computed styles + `getBoundingClientRect`):
  1440 → labels 195 px wide (max 2 lines), grid 2×591 px, no overflow; 768 → 234 px; 390 →
  302 px, single column, `scrollWidth == innerWidth`. `main` vs #444 byte-identical geometry
  before the fix (CSS untouched by #444 at that point); after the fix the computed
  `overflow-wrap` is `break-word` with a ≥100 px minimum label width (new regression test).
- C2: month-window navigation advances `scrollLeft` with the `M…–M… of M…` indicator; sticky
  Line/Amount columns (pre-existing ux-pr1 rules) hold; month headers/notes name the unit;
  cells remain the exact server text (no browser rounding); Expanded monthly view collapsed
  by default with Copy/CSV inside; no page-level horizontal overflow at 1440/768/390.
- React build: `npm ci` + `npm run build` (tsc + tsc.finco + vite) clean; rebuilt bundle
  byte-deterministic locally (two consecutive builds hashed equal); served assets updated.

## 3. Hosted gates at the final HEAD of this push

Recorded in this file after the hosted runs settle; the push itself is made per the owner's
standing instruction (CI is the arbiter; no local full-suite wait).

| workflow | run id | verdict at final HEAD |
|---|---|---|
| Governance Full History | pending | pending |
| Dependency Security Audit | pending | pending |
| PR Compile and Safety Gate | pending | pending |
| FIN-VAL F01 Financial Acceptance | pending | pending |
| Protocol UI Browser Acceptance | pending | pending |
| CI V4 PR | pending | pending |

Rule observed from the packet: no verdict is claimed green from a partial state. The final
verdict block below is updated only when all six workflows complete at this exact HEAD.

## 4. No hidden errors

The new/updated browser tests assert `errors == []` (pageerror + console.error capture) on
every instrumented page, per the existing mandatory-role convention.
