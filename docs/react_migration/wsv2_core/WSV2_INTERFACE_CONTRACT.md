# WS1 / WS2 interface contract

Status: reconciled by WS1 against PR #397 exact HEAD cc48391b4ce7c83ef615455a38e329787410b3b9 (live reverified); WS2 reciprocal acknowledgement pending. Integration order WS1 then WS2 after independent review and Owner-authorized merge. No WS2 implementation is delegated by this branch.

WS1 owns WorkspaceView, navigation, global wsv2-core CSS, Overview and Run reconciliation. WS2 owns financial grids, CostLinesView internals, PPAEditorView, isolated pending-edit and atomic-save modules. api.ts and all backend writers remain read-only in WS1. No second canonical state store.

The exported WorkspaceExtensionContext (frontend/src/app/workspaceExtensions.ts) is a read-only shell handoff: projectId is the canonical project code already authorized by server, workbookVersion and contentHash are the current server CAS pair, activeScenario is the canonical id (string|null); activeScenarioName is separate metadata, lastRunSnapshotId is immutable Last Run identity. Dirty registry remains the sole existing pending-count authority; WS2 may supply a drawer as ReactNode via WorkspaceExtensions, not a parallel editable workbook. PendingChangeSummary is a structural read-only subset of WS2 PendingEdit: id, section, key, label, unit, baseline, value, canonical and error. WS2 remains owner of full PendingEdit, including rowVersion/conflict/meta/order. Unit/provenance metadata must remain explicit in the eventual WS2 integration. No fields or numbers are synthesized.

Validation and draft state are partner-provided read-only metadata. onCommitted only invalidates canonical projections, never runs. onRefetch requests read reconciliation. Scenario changes invalidate scope-bound drafts only through the existing leave guard. A cross-section Save All has no released writer: the extension does not claim one exists. The partner must prove a single transaction, CAS/CSRF, rollback and history invariants or leave Save All blocked.

Run callback carries confirmed historyId, snapshotId and original runIntentId. Both shell and statements must match the confirmed exact snapshot before results are shown. Lost-response UNKNOWN remains under existing runIntent/api authority. Post-run reads never post another Run. No forced editor remount on success; existing draft/CAS reconciliation remains responsible for keeping edits.

No shared-file overwrites, force pushes or implicit forward merge. Partner supplies a small integration patch for shell owner to apply after acknowledgement. Drawer must be labelled, keyboard accessible and fit mobile. Canonical drafts cannot silently move between projects/scenarios.

## PR #397 reconciliation (2026-10-28)

Live HEAD cc48391b4ce7c83ef615455a38e329787410b3b9, base b1a58681, Draft, 19 paths. Read its WSV2_INTERFACE_CONTRACT.md (blob ead940641f9355ffaa5e49e5c17fe0ef2e29e99a) and SHARED_FILE_INTEGRATION.md (blob a2a9fc5a0cfe33a82cfee76d71176b6ae3d72de8). No editing/** or PPA code is copied or imported.

WorkspaceEditIdentity exactly matches the structural EditIdentity shape. WorkspaceExtensions.wrapWorkspace(context, content) provides the stable provider mount around editors, while renderChanges supplies a drawer slot under that provider. No pending changes are stored by the shell. The existing DirtyProvider remains the leave/Run guard authority; WS2 must bridge its count/conflicts/unresolved status into it. WS2 provides latest baselines to rebase(), never shell guesses. Drafts during Run resume stay mounted when the DirtyProvider reports them.

After WS1 acceptance/authorized merge: mount ChangesProvider through wrapWorkspace, supply ChangesDrawer with capability=null until the server publishes a real atomic capability, replace CostLinesView with CostLinesGridView using same props. Do not remove the old CostLinesView implementation or requestNonce guard merely to silence unused imports. The existing exported component may stay for historical source acceptance. Rebuild/reseal bundle only after governed integration. Repeat exact-head browser and CI checks; no reuse of WS1-only screenshots as WS2 acceptance.

## Shared display formatting addendum

WS1 exports `reportFormatting.ts` and the session-only `ReportPrecisionProvider` / `useReportPrecision`. Default amount/quantity precision is 0; `ReportPrecisionControl` changes 0/1/2/3 without saving or running. Dedicated ratio/rate text retains canonical precision with at least two decimals; sub-unit ratio breaches and tiny nonzero ratios are not rounded to a false 1x/0x. Units/row metadata remains authoritative. `units.ts` is the existing exact-decimal shift/rounding authority, extended only to recognize explicit quantity units; no economics.

WS2 consumes `reportAmount(rawNumber, precision)` or `reportUnitText(canonicalDisplay, explicitUnit, precision)` for read-only summaries. Never use a rounded string as PendingEdit.baseline/value/canonical or in SaveAllRequest. Editor inputs and TSV paste retain raw stored precision; copy behaviour must state whether raw or display values are copied. PPA ratio↔human-percent conversion remains entirely WS2-owned and does not use amount precision. Provider is above the live app, so workspace section changes and Run reconciliation retain the preference. No account settings or persisted preference are invented. WS2 integration must test 0→2→0 without dirty-state/hash/history/payload changes.

Later WS2 checkpoint: PR #397 advanced to 44621e0044f48c1fec32e491e35f879664b1cd61 while WS1 worked. Both contract document blobs were independently re-read and unchanged; WS1 source paths have zero overlap with its 29 changed paths at that checkpoint. Partner backend changes are not a WS1 dependency or an authority grant.
