# Lane B — Run history & compare (Audit A GAP-R13)

**What exists at base:** WF-REACT-3 insights (`/model-react/insights[/history]`, max 3 Runs) are mounted in Analysis and Scenarios; Results lists Runs.
**What RC-UX adds (no competing implementation — the insights authority is imported, not copied):**

| Piece | Path | Notes |
|---|---|---|
| Compare adapter (read-only GET) | `app/v2/react_compare.py`, mounted via `app/v2/react_rcux.py` | `/v2/model-react/compare?project&run=…` (2–3 distinct committed Runs). Reuses `react_insights_router._context/_validated_json/_state`, `validate_entry`, `build_compare_rows`. |
| KPI rows | same | Persisted KPIs + persisted evidence rows (equity/SHL contributed, distributions, senior contractual maturity vs actual payoff). Absolute delta = Legacy `build_compare_rows` delta; relative change `(v−ref)/|ref|` computed server-side, undefined (“—”) for a missing or zero reference. PLCR is explicitly unavailable. |
| Cash-flow comparison | same | Period-aligned persisted series (waterfall, debt, sponsor). Totals = plain sums; ratios never summed; a missing period is empty, never zero; calendar mismatch flagged. |
| Assumption differences | same | Only what the immutable Run identity persists: composite hash, scenario overrides, CAPEX/OPEX line amounts. The limitation is stated in the response and UI. |
| UI | `frontend/src/app/runs/` (+ tab in `analysis/AnalysisTools.tsx`) | History table with search, scenario/state filters, sort, CURRENT/STALE/HISTORICAL chips, “matches Working Copy” label (hash equality only), provenance disclosure, XLSX export link, selection capped at 3; compare with Absolute/Percent/Both toggle, CSV/TSV copy, cash-flow series selector. |

**Not built (honest limits):** historical statements still open the classic Run-history statements page (new tab); per-input assumption diff of historical Runs is impossible (full inputs are not persisted per Run); scenario Save/Run lifecycle stays in the existing Scenarios section.

**Evidence:** `tests/test_model_react_rcux_compare_v1.py` (18 tests over real Solar Runs: persisted equality, Legacy-compare equality, no-write DB-dump equality, model execution forbidden, auth/foreign/protected/flag/limits), `tests/model_react_rcux_runs_acceptance.py` (8 Chromium nodes, GET-only network assertion, viewports 320/390/768/1440, reference-model refusal), `tests/test_rcux_governance.py` (12).
