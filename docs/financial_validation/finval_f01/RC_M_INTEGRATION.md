# RC-M integration contract

Consume [rc_m_rate_contract.json](rc_m_rate_contract.json). F01 owns backend Clone/Save unit authority; RC-M retains wizard, library and financing components. No React sources/bundle or project-create service is changed. This file and PR are the integration handoff; no separate agent message or release-readiness claim is implied.

Render both `0.056` and `5.60` as human percentages. Do not multiply a sub-one value by 100. Read the server's field `rate_contract`; `AMBIGUOUS` must not be presented as a verified editable rate. Preserve existing CSRF, content hash, workbook version and scenario identity. Save succeeds through the existing envelope and never Run. Refetch to verify; stale Save requires resolution rather than silent new-hash retry. Existing legacy single-cell failure uses its HTML/HX envelope plus `X-Finco-Error-Code`; batch failure retains JSON with the typed code. Do not expect a new universal JSON envelope.

New create/clone calls use the existing server adapter, then fetch canonical fields. Never manufacture a unit marker to repair an old user copy. `human_percent_v1` describes a verified snapshot contract; source lineage is server-owned and hash-bound. An owner must review any genuine historical repair separately.

Staged joint acceptance: consume F01 after acceptance; repeat new wizard → clone/create → edit 0.056 → Save/reload → Run, then 5.60, on four allowed verticals; assert typed ratios, status/hash freshness, diagnostics and immutable history. Current automated Chromium acceptance executes the existing financing editor with real server Save/reload for both rates across four disposable projects. RC-M's upcoming wizard is not claimed tested or released.
