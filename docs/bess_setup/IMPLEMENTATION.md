# Standalone Storage setup preview

The New Project Wizard exposes an isolated Storage preview through the existing
authenticated options API. The Storage creation and template cards remain
disabled. A separate preview form accepts a complete, explicit native contract
and offers canonical battery fields for local editing. The shared native parser
validates every submission; duration is the server-derived usable DC MWh /
discharge MW ratio. No commercial assumptions are supplied.

`POST /v2/model-react/new-project/bess-preview` is authenticated, request/session
CSRF-bound, stream-bounded and non-persisting. It accepts no project or scenario
identity. Schema validity proves neither physical dispatch balance nor financial
horizon alignment. Source input and refusals stay in component memory; changed
input aborts and invalidates older replies. Hiding or changing the seeded setup
path retains input; leaving warns about its loss.

The server separately reports reference, preview, create, save and Run support.
Create/Save/Run are unavailable. Native activation remains False; the protected
Storage reference, seed service, creators, existing model math and Run/Save
authorities are unchanged. Hybrids and new revenue/financing/tax semantics are
outside this change.

On-demand local checks (not automatically collected or imported by CI):

```sh
python -m pytest tests/on_bess01_contract_checks.py -q
python -m pytest tests/on_bess01_governance_checks.py -q
python -m pytest tests/on_bess01_browser_checks.py -q
cd frontend
npm run typecheck
npm run build
cmp dist/finco-react.js ../static/react/finco-react.js
cmp dist/finco-react.css ../static/react/finco-react.css
```

## Closed source and integration dependency

`tests/on_bess01_scope.py` seals a literal finite source set against accepted
main `91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14`, tree
`e9573d7802b319deb943dab60667778a431370e4`. Its manifest records exact current
blobs and the original six moved blobs. Negative controls cover unsigned bytes,
foreign paths, mode changes, ancestry/schema and crossed pins. Historical pins,
manifests and CI policy are unchanged.

This own-source seal is not global governance admission. The latest protected
reference-registry cohort closes all later app/frontend/static changes and pins
the composite registry. Updating that workstream is outside this task's scope.
An owner-coordinated exact predecessor successor is an integration dependency;
the normal gate must continue to refuse until composed. Do not relax the gate
or interpret local preview tests as merge/release readiness.

Private readiness, research provenance, source coverage, screenshots and final
report are retained outside GitHub. No numerical parity or persisted BESS
financial acceptance is claimed. No CI jobs, selectors or browser imports were
added by this slice.
