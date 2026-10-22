# frontend/src/finco — harvested Replit FINCO Model design source (UX-01B)

Source of truth: `finco-react-transfer-rc1.zip` (Replit "GoldenNiceConsultant"
project, workspace revision `26ade41`), transferred under
`docs/react_migration/replit_source/` (handoff reports preserved verbatim).

## What this tree is

The accepted FINCO Model React UI/UX design source: `fm-*` components with a
self-contained plain-CSS design system (`_group.css` defines the `--navy`,
`--surface`, `--line`, `--ink`, `--muted`, `--paper`, `--blue`, `--sw-*`
tokens; no Tailwind, no external runtime UI library — the subtree's only
external import is `react`, and every hook used is React-18 compatible).

**Boundary status (as supplied — verified during intake):** these components
are presentation-complete but still coupled to the sandbox's browser-local
demo state (sessionStorage sessions, fixed synthetic fixtures, URL-owned
navigation). They contain NO server contract, NO canonical field IDs, NO
financial authority. The package's own
`docs/react_migration/replit_source/INTEGRATION_READINESS.md` marks every
server obligation `NEEDS_GITHUB_VERIFICATION`.

## Import-graph quarantine (enforced by test)

- The production React app (`frontend/src/main.tsx` → PoC views) does **not**
  import anything from `src/finco/`. The served bundle
  (`static/react/finco-react.js`) must never contain the demo fixtures or
  synthetic financial data from this tree —
  `tests/test_model_react_source_harvest_v1.py` pins this.
- Demo-coupled modules (`_shared/demoAdapter.ts`, `demoSession*.ts`,
  `demoWorkingCopies*`, `demoProjectFixtures.ts`, `motion.ts`) stay in place so
  the supplied tree compiles exactly as transferred; they are candidates for
  deletion/replacement (not adaptation) when a domain is wired to canonical
  adapters.
- `frontend/transfer/` is the dev-only preview harness (its own Vite config,
  never served by FastAPI). `npm run build:transfer` builds it for design
  review; it is not wired into CI.

## Integration rule (from the owner brief)

Do not independently recreate what this source already implements well. When a
domain is migrated, replace the corresponding PoC view with the harvested
component adapted to the typed canonical adapters (`frontend/src/api/`), per
`docs/react_migration/ux01b_source_harvest.md`.
