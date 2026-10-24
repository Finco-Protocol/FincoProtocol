# Concept B NON-MODEL integration V1 — integration record

Status: integrated on an isolated branch, awaiting independent review. No merge,
deployment or staging activation is performed or authorized by this record.

## What was integrated

The owner-selected Concept B "Modern Crypto Terminal" NON-MODEL presentation
(public Landing, Radar overview + R-LIVE, Tokenized Markets, Stocks, Radar
Crypto, Economy, standalone Crypto preview, public Roadmap) from the handoff
archive `FINCO_CONCEPT_B_NON_MODEL_INTEGRATION.zip`.

- Archive SHA-256: `549a3ac34733c09fbd3d05e80b0c5efa70f9b52aeaa0fac8eca78b6df841df63` (verified).
- All 10 archive files verified against `FILE_MANIFEST.txt` per-file SHA-256.
- Source baseline (Replit): `4420ec8ac81fbbd89c51995719daa3c49a3ae523`.
- The archive is a scoped integration handoff, not a runnable app; it was
  integrated into the host application's existing React infrastructure.

## Base and dependency declaration

- Integration branch: `feat/nonmodel-concept-b-v1`.
- Base: `epic/model-react-frontend-v1` (NOT `main`).
- Dependency, explicitly: the host React application (`frontend/` Vite +
  TypeScript toolchain, FastAPI bundle serving, React contract/harvest guard
  tests) exists on the Model React epic branch and is not yet merged to
  `main`. `main` has no React application to integrate into. This integration
  therefore stacks on the epic base and the Draft PR targets the epic base so
  the diff shows exactly the NON-MODEL changes. The Model epic and this
  integration remain separately reviewable; neither merges the other without
  explicit authorization. No Model UI/UX file is modified by this work.

## Host integration shape

| Concern | Decision |
| --- | --- |
| Source location | `frontend/src/nonmodel/**` (isolated subtree; imported only by the surface switch in `frontend/src/App.tsx`). |
| Surface selection | `data-surface="non-model"` on the mount element; default (unset) keeps the Model React surface byte-for-byte. |
| Page route | `GET /v2/non-model` (`app/v2/nonmodel_router.py`, composed in `app/v2/router.py`), public, presentation-only, no session/CSRF/bootstrap/persistence. |
| Host page | `app/templates/v2/nonmodel_host.html` — same-origin assets only, data attributes only, modeled on the UX-01 React PoC host page. |
| In-experience navigation | URL hash routes (`#/`, `#/radar`, …) — the host React app's established in-app pattern; page-level routing stays FastAPI path-based. Direct entry, refresh and Back/Forward verified by the scoped check. |
| Dependencies | None added. The handoff's `lucide-react` import is replaced by an inlined icon set (`frontend/src/nonmodel/icons.tsx`, path data verbatim from lucide-react 0.544.0, ISC — see `THIRD_PARTY_NOTICES.md`). |
| Footer destinations | Verify → `/verify`, API → `/api`, Docs → `/docs`, Methodology → `/model/methodology`, Yield → `/yield`, $FINCO → `/protocol/finco` — all verified canonical host routes on the base branch. The Replit-only concept-gallery link is removed (no host route). |
| Canonical surfaces | `/radar/**` (app.radar_ui), `/crypto` (app.crypto_ui), `/roadmap` (app.protocol_ui), `/` — untouched and authoritative; this integration adds one additional same-origin page and no redirects. |

## Boundary preservation

- MARKET vs REFERENCE separation, 300-second per-leg/pair freshness and skew
  guard, stale/unavailable suppression (current values, premium/discount and
  charts), exact-identity joins, honest Economy empty state, simulated-only
  wallet/access controls with gated actions disabled, session-local watchlist
  and alert drafts (no scheduling/delivery), non-binding roadmap target
  labels, keyboard row isolation and reduced-motion behavior are unchanged
  from the handoff (`_shared/` sources byte-identical; manifest-pinned).
- No backend endpoint is invented or called: the tree contains no
  `fetch`/`XMLHttpRequest`/`WebSocket` usage (pytest-enforced). Future
  canonical wiring is recorded as typed `NOT_CONNECTED` placeholders with
  dependency notes in `frontend/src/nonmodel/adapter.ts`.
- No wallet connection, trading, entitlement, notification scheduling or
  market-data collection is introduced.

## Verification performed for this integration

- `npm run typecheck` (strict; host tsconfig) — see PR evidence.
- `npm run build` + committed bundle identity (CI re-verifies byte identity).
- `npm run check:nonmodel` — logic contract (ported 7/7) + static render for
  the 9 in-scope routes + unsupported-route fallback + footer destination
  contract (hash routes in-surface; canonical host links out).
- `python -m pytest -q tests/test_nonmodel_concept_b_v1.py` — provenance,
  dependency surface, data boundary, footer mapping, routing guards, page
  route contract.
- Existing guards re-run in CI unchanged: React PoC contract tests, harvest
  quarantine (dependency surface, module graph, bundle markers), compileall,
  public safety scan.

## Known limits

- All figures/curves are labelled synthetic fixtures; no canonical Radar
  service is consumed yet (adapter seams documented).
- `?fincoLegacy=1` from the Replit preview has no equivalent here: the
  canonical server-rendered surfaces remain directly reachable at their own
  paths and this experience never replaces them.
- Staging acceptance, canonical data wiring, entitlement and persistence are
  separate, separately authorized phases.
