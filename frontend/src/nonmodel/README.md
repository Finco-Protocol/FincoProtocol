# frontend/src/nonmodel — Concept B NON-MODEL experience (GitHub integration V1)

Integrated host copy of the owner-selected **Concept B "Modern Crypto
Terminal"** presentation for the public Landing, Radar, Crypto and Roadmap
surfaces. This is the FINCO host application's own React tree: it is built by
the host toolchain (`frontend/`), served by the host from the same-origin
bundle, and mounted through the canonical FastAPI route table.

## Handoff provenance

- Archive: `FINCO_CONCEPT_B_NON_MODEL_INTEGRATION.zip`
  (SHA-256 `549a3ac34733c09fbd3d05e80b0c5efa70f9b52aeaa0fac8eca78b6df841df63`,
  10 files; manifest SHA-256 values verified per file).
- Source baseline (Replit): `4420ec8ac81fbbd89c51995719daa3c49a3ae523`
  (worktree clean; export recorded at `2026-10-24T08:27:15Z`).
- Prior handoff evidence (not re-run for the export): logic 7/7 PASS; scoped
  render 9 routes + fallback PASS; scoped strict TypeScript PASS; Chromium
  19/19 at 1440×900 and 390×844; full build NOT RUN (integration handoff).

## Layout

| File | Role |
| --- | --- |
| `FincoNonModelExperience.tsx` | Concept B page composition, hash navigation, filters, detail, simulated access, session-local watchlist and alert drafts. |
| `concept-b.css` | Scoped dark terminal design (all selectors under `.finco-b-app`; no global leakage). |
| `_shared/fixtures.ts` | Deterministic local instrument/source fixtures (unchanged, byte-identical). |
| `_shared/non-model-logic.ts` | Evidence freshness, pair eligibility, chart seed, filters, keyboard isolation, watchlist/alert helpers (unchanged, byte-identical). |
| `icons.tsx` | Local inline-SVG icon set replacing the handoff's `lucide-react` import (path data verbatim from lucide-react 0.544.0, ISC). |
| `adapter.ts` | Typed canonical-wiring boundary: every not-yet-authorized capability is recorded `NOT_CONNECTED` with its dependency. No endpoint is invented. |
| `_checks/nonmodel-check.mjs` | Combined logic + static-render integration check (`npm run check:nonmodel`). |

## Documented adaptations (the only deltas from the handoff)

1. **Icons.** `lucide-react` → `./icons`. The host pins the production React
   dependency surface to `react` + `react-dom` only
   (`tests/test_model_react_source_harvest_v1.py`); adding a runtime icon
   dependency would break that governance test, so the exact 22 icon path
   datasets are inlined with the same rendering contract. Recorded in
   `THIRD_PARTY_NOTICES.md`.
2. **Footer destinations.** The standalone preview had to present Verify, API,
   Docs, Methodology, Yield and `$FINCO` as host-only text and linked a
   Replit-only concept gallery. Inside the host each label has a verified
   canonical destination — `/verify`, `/api`, `/docs`, `/model/methodology`,
   `/yield`, `/protocol/finco` — rendered as real same-origin links; the
   concept-gallery link has no host route and is not rendered. In-surface
   navigation (Landing / Radar / Crypto / Roadmap) stays on hash links.

Everything else, including all display guards (300-second per-leg/pair
freshness, MARKET vs REFERENCE separation, stale/unavailable suppression,
exact-identity joins, honest Economy empty state, gated-action disabling,
non-binding roadmap targets), is unchanged.

## Routing integration

- Page-level routing uses the canonical FastAPI route table: `GET /v2/non-model`
  (`app/v2/nonmodel_router.py`) serves the host page
  (`app/templates/v2/nonmodel_host.html`), which mounts the bundle with
  `data-surface="non-model"`. No authentication is involved; the surface makes
  no request and holds no authority.
- Within the experience, navigation uses URL hash routes (`#/`, `#/radar`,
  `#/radar/r-live`, `#/radar/tokenized`, `#/radar/stocks`, `#/radar/crypto`,
  `#/radar/economy`, `#/crypto`, `#/roadmap`). This mirrors the host React
  application's own in-app navigation ("sections live in the URL hash, so
  Back/Forward and direct refresh work") — direct entry, refresh and browser
  Back/Forward resolve inside the component; unsupported hashes render an
  explicit ROUTE NOT FOUND fallback.
- The canonical server-rendered surfaces (`/radar/**`, `/crypto`, `/roadmap`,
  `/`) are untouched and remain authoritative; hash routes under `/v2/non-model`
  never shadow them.

## Canonical data wiring

Not connected — by contract and by construction. `_shared/fixtures.ts` supplies
deterministic synthetic fixtures labelled in the UI; no backend call exists in
this tree (`tests/test_nonmodel_concept_b_v1.py` enforces this). The typed seam
for future authorized wiring is `adapter.ts`; see its `CANONICAL_WIRING`
register for the per-surface dependency notes.
