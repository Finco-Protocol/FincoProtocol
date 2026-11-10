# BESS02 explicit standalone candidate

`app/services/bess_standalone_candidate.py` is an unmounted, pure preparation
boundary for an independently reviewed native merchant BESS input. It does not
create a user project, save a draft, invoke finance, publish a result or grant a
capability. The protected reference remains unchanged. The authenticated Storage preview
now adds a bounded declared-input review without granting a lifecycle.
The existing `app/workbook/bess_config.py` activation literal remains false.

A caller must supply a complete typed `ProjectInputs`, a strict native battery
contract, and a bounded versioned cost declaration. The declaration pins the
entire base input fingerprint, canonical native document, discharge MW,
installed/usable MWh, every existing CAPEX item including explicit zeros, asset
classes, spending profile, depreciability and explicit book useful lives.
Manual kEUR amounts are read from those supplied inputs; no €/MW or €/MWh cost
model, factory fallback, tax jurisdiction, depreciation policy or lender case is
selected. User-provided policy references are provenance only. They cannot
represent an owner's approval or a verified statutory tax opinion.

The read-only review exposes the actual recorded capitalization, legal-reserve
and cash-interest authorities, including `UNRESOLVED`, plus whether the supplied
country tax policy ID is recorded or absent. A recorded ID or a user reference
that says "approved" never changes `owner_approval=NOT_PROVEN` or grants a
capability. These details locate the missing financial contracts; they do not
choose or implement a policy and do not invoke a financial calculation.

Preparation rejects legacy BESS economics, hybrid yield inputs, concurrent
PPA/multistream/CO2 revenue, post-COD events, nonzero energy inventory, implicit
or floating interest rates, incomplete cost declarations, changed cost/power
basis and an incomplete or unsupported financial axis. Only the existing
semiannual clean axis with at least two operating years is eligible. Native
start/end must cover that complete axis. Hour counts use actual boundaries,
including leap years. The native parser validates schema but preparation does
not evaluate dispatch physics; independent physical proof remains necessary.

The resulting immutable envelope contains existing native typed inputs and a
content-only review fingerprint. It is not a workspace CAS hash, project ID,
scenario identity, persisted Run snapshot or financial readiness certificate.
Any isolated numerical comparison must use the existing native operating and
canonical financial engines as subjects, with independent expected arithmetic.
The application production authority continues to refuse BESS at the closed
activation gate. No test-only writer or alternative financial calculator is
introduced here.

`create_standalone_project` always refuses before any persistence, reference
lookup or clone operation. Caller payloads, environment variables and forged
readiness do not change that behavior. `capability()` reports Create/Save/Run
false. The new-user Create→Save→Reload→Scenario→Run→History lifecycle remains
NOT_PROVEN for this candidate. A later owner-controlled implementation must
approve project-store authority, tax/depreciation/funding semantics, merchant
case and reserve policy, then prove transactional ownership/CSRF/CAS/idempotency
and immutable run identities. It must never enable the protected Storage
reference or infer readiness from successful engine-only numerical tests.


Private candidate document transport is an unmounted string-to-string API.
`export_candidate_document` checks that every original base dataclass field and
its complete fingerprint survive the existing core serializer. The native
contract and declaration travel separately because the core serializer does
not represent native technical subclasses. `import_candidate_document` refuses
unknown or omitted serialized fields, duplicate keys, nonfinite numbers,
oversized documents, changed content hashes and forged approval fields, then
repeats the complete preparation checks. These content hashes are not signed
approval: a new explicit declaration can describe a different candidate.
This local document roundtrip is not canonical Save/Reload, project storage,
workspace ownership or Run History evidence. Prepared native input cannot be
silently flattened through the base serializer.

The existing authenticated preview response now appends `declared_terms` with
Battery, Dispatch & prices, Costs, Financing, Review and Notes groups. It shows
at most 24 declared dispatch rows with total count, truncation and explicit
units, omitting private source references. Variable O&M preserves a real zero;
absent CAPEX, fixed OPEX, funding, debt, DSCR and tax remain null with
NOT_AVAILABLE. No revenues or financial results are inferred. Schema review
does not prove physics or the complete financial horizon. Existing validation
and Create/Save/Run refusals remain in force.

React rendering of these groups is deferred: concurrent PR #438 owns the
shared Financing bundle. This PR changes no React source or compiled bundle;
the new server response field is additive and the existing client ignores it.
The declared-input response is a bounded backend handoff, not completion of the
requested compact editor or viewport/keyboard acceptance for new controls.
