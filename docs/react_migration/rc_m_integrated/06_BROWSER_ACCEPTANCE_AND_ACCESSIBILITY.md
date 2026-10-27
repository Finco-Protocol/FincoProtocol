# Browser acceptance, responsive layout and accessibility (real Chromium)

## How it is mandatory

The five RC-M Chromium suites are **non-collected acceptance modules** (`tests/model_react_rcm_{new_project,analysis,financing,investors,themes}_acceptance.py`,
exports listed in each module's `__all__`) imported at the tail of `tests/test_model_workspace_consolidation_browser.py` — the **existing mandatory `consolidation`
role** of `.github/workflows/protocol_ui_browser.yml`. They therefore run under that role's fail-closed verifier (`tools/ci_browser_job.py::validate_consolidation`: every
collected node executed and passed, JUnit equals collection, screenshots present) with **no workflow, inventory or threshold change**, and no module-level skip exists in
any RC-M test module (`tests/test_rcm_governance.py`, `tests/test_rcm_ci_v3_collection_governance.py`). Collection became 106 → 165 nodes (59 new); in the plan
environment, where Chromium is unavailable, the collection-skip inventory is identical to `main`.

Local run of the whole role, Python 3.12, real Chromium, thread execution mode as in CI: **165 passed, 0 failed, 0 skipped in 781 s** (the 106 pre-existing nodes included),
and `validate_consolidation` accepts the resulting inventory/JUnit/screenshots. Exact-head hosted results are in `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md`.

## What the 59 new nodes prove

| Surface | Nodes | Proven in the browser against the real server |
|---|---|---|
| New Project wizard | 19 | Library + global-navigation entry; Solar/Wind create one NOT RUN working copy; wizard-created and directly created projects have identical effective inputs; Preview verticals need an explicit acknowledgement; double-click creates one project; lost response reconciles without a second project; lost request fails closed with no retry control and survives reload; expired security token refuses and creates nothing; keyboard-only flow to review; every step fits 320/390/768/1440 with ≥ 44 px touch targets; every selectable theme |
| Analysis (Sensitivity, matrix, Goal Seek) | 17 | hub keeps the Last Run view; 5-point strip equals the adapter's canonical read and writes nothing; CSV equals the displayed table; 3×3 and 5×5 matrices; busy engine reported once, never retried; Cancel shows no result; reference models refused; Goal Seek PREVIEW → Apply → STALE → deliberate Run; unreachable/invalid targets typed with no Apply; lost Apply response is *unknown*, never retried, applied once; stale binding refused and the Working Copy kept; 320/390/768/1440 |
| Financing | 13 | six sections with authority and closed structures stated; **React and Legacy bankability editors send byte-identical configuration documents**; Save → Reload → Run makes the Last Run STALE without running; obviously invalid input stopped client-side while the server still validates; changed Working Copy refused, nothing overwritten; lost Save response unknown and applied once; reference models read-only; period grid arrow/paste; Senior facilities and Sources & Uses show canonical evidence; every tab fits every viewport |
| Investors & sponsor | 9 | **byte-identical agreement documents vs Legacy F4**; Save → Reload → Run gives Run-bound evidence equal to the adapter; ownership ≠ 100 % refused by the server; lost Save unknown and committed once; reference read-only; fits every viewport |
| Themes | 1 | every new surface keeps WCAG-AA text contrast (≥ 4.5:1, disabled controls exempt) and no page overflow in every selectable theme |

Every test fails on an unexpected page error or console error (`unexpected(errors)`), compares displayed figures with the adapter's own canonical read, and never asserts a
hard-coded financial value.

## Accessibility and responsive behaviour

**Asserted by the Chromium tests:** the wizard reaches review by keyboard alone; touch targets ≥ 44 px on every wizard step; WCAG-AA text contrast (≥ 4.5:1) of the
sampled text and controls in every selectable theme (the only failure ever found — a navigation link at 1.13:1 — was fixed by inheriting the theme colours); no document-level
horizontal scroll at 320 / 390 / 768 / 1440 px for any step or tab; the financing period grid supports arrow navigation.

**Implemented but not separately asserted:** status/alert regions (`role="status"` / `role="alert"`) for unknown outcomes and refusals, `aria-busy` on pending actions, a stated
reason on disabled controls, a two-step confirm for Apply, and focus order following the visual order.

## Screenshots

Each lane writes `rcm-*.png` (wizard steps and states, Goal Seek preview/applied-STALE, strip and matrix, bankability/overview/facilities/sources-uses at the four widths, investors).
They go to `$RCM_SCREENSHOT_DIR` when set, otherwise to the role's own `WF05_SCREENSHOT_DIR`, which CI already uploads as the `model-workspace-consolidation-browser` artifact.
A local run produced 72 images (≈ 9.7 MB); they are not committed.

## Not claimed

No visual-regression baseline, no assistive-technology (screen-reader) session, no cross-browser run beyond Chromium, and no mobile-device run were performed.
