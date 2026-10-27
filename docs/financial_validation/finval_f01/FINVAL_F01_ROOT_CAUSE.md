# FIN-VAL F01 root cause and verified boundaries

The unmodified live-main source `cf7056de4078ca66afcf52265a9bacafe35586f7` was executed with a disposable database. Solar clone initially stored `0.055`, displayed `5.50%`, and materialized ratio `0.055`. Posting `0.056` stored `0.056`, displayed **5.60%**, but materialized ratio **0.0005600000000000001**. That is the observed 100× display/meaning mismatch. [Raw reproduction](evidence/live-main-reproduction.json), [executable script](evidence/reproduce_live_main.py). This is local exact-source reproduction; no claim of production browser inspection is made.

## Call graph and authority

`projects_repository._compute_baseline_snapshot` and `main_web._project_baseline_snapshot` serialize known factory financing → reference hydration → `project_library_service.create_working_copy` copies reference saved/base snapshot → `ProjectInputSet` retains snapshot-origin keys and hashes them → `router._build_sheet_fields` projects legacy/React data → `WorkbookUpdateService.apply_draft_update` or `apply_batch_draft_update` validates human percentage and senior authority → workspace atomic CAS commits the value and unchanged unit/origin in one JSON update → reload → input adapter materialization → `_set_financing_interest_rate` converts percent /100 once → existing calibrated/bankability/clean engine → atomic Run and immutable history.

Legacy additional boundaries: full forms go through `_collect_form_snapshot` → `save_workspace_state`; under its writer transaction, a verified stored unit/lineage is retained, contradictory lineage refused, and historical unlabeled rows cannot be upgraded by a client marker. The inputs and Senior Debt partials previously rounded low rates; they now retain percentage precision. The EV legacy generic fallback used Wind's rate; only its rate authority now uses the identified EV factory.

## Producer inventory

Solar, Wind, Data Center, EV Charging and storage reference serializers in projects repository emit human percentages plus `human_percent_v1`. Main-web Solar/Wind/Data Center/storage/fallback serializers do likewise; EV fallback takes its own factory rate. Generic standalone Solar/Wind creation consumes the same corrected callback. Reference-seeded creation delegates to the corrected clone authority. Storage stays release-closed; no feature is enabled. No RC-M service/component change is needed.

## Trusted-unit decision table

| Stored class | Action |
|---|---|
| Explicit `human_percent_v1` | Preserve exact human rate; validate finite 0..20; materialize once |
| Canonical protected reference with verified factory identity, reference replay metadata and exact historical producer value | Create a **new** canonical copy from the identified factory contract; record source lineage; leave source unchanged |
| Unlabeled existing user copy, low percentage or ratio of unknown origin | Typed `RATE_UNIT_PROVENANCE_AMBIGUOUS`; safe projections remain readable; create verified copy or owner-reviewed repair |
| Contradictory/unsupported marker or forged lineage | Refuse before financial write |
| Non-uniform calibrated senior schedule | Preserve typed schedule; scalar Save refused |
| Bankability-owned rates | Keep authority and refuse scalar overwrite |

Magnitude never proves units. Exact factory-value equality is used only inside a closed, identified historical producer contract, never as a general numerical classifier. No migration, source-reference rewrite or historical Run edit occurs.

The old resolver's percent-or-ratio identity shortcut is removed. The setter may preserve the exact same typed object only **after** known human percent is converted once and equals the existing uniform typed ratio. This preserves unchanged factory auxiliary state without accepting a second unit. `margin_bps`, bankability percentage curves and engine ratio vectors retain their distinct contracts.

Before/after exact blobs and scope reasons: [manifest](FINANCIAL_OWNER_SCOPE_MANIFEST.md). Numeric engine policy, equations, native kernels, golden outputs and CSRF/CAS/ownership/Run intent controls are unchanged.

Correction A additionally proves and closes the supplied-hash reconciliation defect and direct saved-snapshot converter unit bypass. See [Correction A](FINVAL_F01_CORRECTION_A.md) for red/green tests, invariants, non-root native recovery and RC-M boundaries.
