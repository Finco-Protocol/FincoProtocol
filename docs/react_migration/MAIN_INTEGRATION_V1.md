# React main integration V1 — release closed

## Exact intake and preservation

Main: 0397d9af2ea87bc2930218faa2e2d5adb503234f,
tree e54ebe91b6b9090ca698066da2dc84db653fc1fd.
Epic: bd91603de4e35fa546fde08d19bd088b3a13e29d,
tree 073adbdc9dd7f80bba42c711b19fb3310c6c549d.
Before integration main had 3 unique commits, Epic 63. Main's unique commits are
WF09A's two source commits and merge #362. A normal merge from a new branch based
on main preserves both parents, without conflict or manual replacement of source.
The merge parent IDs, merge-base, trees, complete inventory and tested HEAD are
recorded in the integration PR evidence. No Epic source is dropped: main-only
additions are the isolated costing module, its methodology and tests. V10/V11,
financial_engine and finco_core are byte-identical to main. No owner records,
source pins or approved native configuration are modified.

Epic post-merge Public Safety run 40133886851 and browser run 40133886766 were
still in progress at intake. Five real workers were visible, with successful
route/plan/source-safety. Their results remain Epic-source evidence only, not
integration-source acceptance. Release readiness requires successful completion
of both Epic acceptance and all exact integration-head mandatory checks.

## Phase A — both UIs in main, defaults OFF

Existing entrypoints are sufficient for this integration; no default host redirect
or new public routing authority is necessary. FINCO_MODEL_REACT_V1 and
FINCO_NONMODEL_PREVIEW remain absent/false by default. They are request-time gates,
not approvals. Model preview is /v2/model-react and /v2/model-react/{project_code};
Concept B is /v2/non-model. Canonical /v2/workbook and its Save, Run, History,
scenario/CAS and statement services remain in place, including when previews are
explicitly enabled in isolated tests. No public Radar or Crypto URL is replaced.
Legacy remains the functional fallback rather than a second financial engine.

The React projections reuse canonical backend authorities; mutations use existing
canonical writers, ownership, sessions and CSRF. Rejected writes and ambiguous
outcomes must remain failures/UNKNOWN. No frontend recomputation may manufacture
financial results. Shared statement evidence, run certificates, protected reference
rules and native rollback controls are preserved.

## Capability boundaries

Use current source and tests, not the older PoC parity table alone. UX04–08 provide
field/input projections, cost editors, financing, explicit Run and History,
diagnostics/Trust, scenario management and a revenue contract editor. The
canonical endpoints remain financial and persistence authority. In particular:

- Scenario Compare reports assumption differences; KPI comparison is unavailable
  rather than computed in the browser.
- Revenue editing uses canonical streams/products JSON; a guided PPA form remains
  a legacy capability, not a completed React feature.
- Existing legacy import/export and advanced workflows remain fallback paths;
  this PR does not claim universal UI parity or staging acceptance.
- Concept B landing/Radar/Crypto/Roadmap are labelled synthetic preview surfaces.
  No canonical market data, entitlement, trading or new persistence authority is
  connected. Model and Non-Model have separate entrypoints and JS/CSS bundles;
  their dependency/bundle provenance and quarantine guards remain mandatory.

The existing reports react_migration_ux040506_integration.md and
nonmodel/concept_b_integration_v1.md document finer contract boundaries. Feature
presence is not independent product or financial acceptance.

## Builds and local acceptance

From frontend: npm ci --ignore-scripts --no-audit --no-fund; npm run typecheck;
npm run build; npm run build:nonmodel; npm run check:nonmodel. Regenerated Model
and Non-Model JS/CSS must match their committed static/react counterparts; no
older bundle is substituted. Package manifests and runtime input pins stay Epic's
accepted bytes. Browser coverage extends Model responsiveness to 320px and checks
the real Non-Model page at 1440/900/390/320, with isolated test-only preview flags.
The PR evidence records actual results, including any unresolved failures; these
commands alone do not imply PASS.

## Phase B — separately authorized production React / staging legacy

Nothing here deploys or changes either host. Current external deployment revision,
active environment values, databases and secrets cannot be authenticated from
repository examples. GitHub's recent deployment records describe CI environments,
not proof of live app.finco.one/staging.finco.one state. Reading main branch
protection returned HTTP 403 (Resource not accessible by integration); no protection
claim is inferred.

Before a later release an authorized operator must independently record both live
revision/tree and artifact digests, deployment branch automation, database paths
and schema compatibility, secret custody and accepted browser results. Production
and staging need isolated revisions, databases and secrets. Disable staging's
follow-main automation and pin its independently verified legacy-compatible
revision; do not change it as a side effect of main admission. Never copy financial
records to staging without a separately approved handling procedure.

Future React-default production routing is a separate reviewed release action.
Use the existing gated preview entrypoints first; any host/root route change must
preserve canonical legacy URLs and accepted public Radar/Crypto behavior. Enable
only the explicitly accepted feature, not both previews indiscriminately. Record
revision, flags and route map before/after; verify canonical backend parity and
all four browser sizes. A green integration PR is not activation authority.

## Rollback and Phase C

Proposed pre-transition source checkpoint: main
0397d9af2ea87bc2930218faa2e2d5adb503234f (contains accepted WF09A/V11, no React
intake). It is a source candidate, NOT proof of the current live legacy deployment.
The operator must choose and authenticate the actual accepted legacy runtime
checkpoint before release, retain built artifacts and dependencies, and prove
schema compatibility against its own backed-up database.

Immediate frontend rollback disables the relevant preview flag and restores the
accepted route map while keeping canonical services and legacy /v2/workbook
available. If necessary redeploy the authenticated compatible legacy artifact.
A Git checkout is not a database rollback: retain WAL-consistent snapshots, schema
version records, recovery procedure and replay/write reconciliation as separately
approved operations. Do not overwrite production data to restore an old UI.

Only after independent functional and financial acceptance may a separate cleanup
PR create archive/legacy-ui and an immutable tag at the exact approved checkpoint,
then remove obsolete UI-only code. Shared canonical services must remain. No
archive branch/tag, template removal, deployment, environment change or production
database operation is performed by this integration.

## Runtime transition admission correction

The main accepted runtime contract predates the Epic frontend inputs. Even though
the new source pins are internally consistent, this does not prove reference
software comparability. Router preflight now compares the authenticated reference
source runtime manifest with current input bytes and fails closed to sequential
when they differ. No coverage, collection-skip, nonpass or aggregate guard is
relaxed. A successful new accepted checkpoint permits later eligible parallel
runs under the existing contract. This integration's initial route may therefore
be sequential; no five-worker activation is claimed from configuration alone.
