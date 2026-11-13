# R04 Phase 2 preparatory candidate — accepted C06, UI dependency pending

This isolated package continues on the existing branch after the ordinary
accepted C06 #444 main sync. Shared UI integration awaits accepted #446. It changes no accepted writer, engine, governance map, UI or bundle.
There is no production Save/Run admission or completed annual contract policy.

`contracts.parse_annual_document` defines bounded, strict annual-quantity syntax:
explicit ABSOLUTE_ANNUAL mode, positive finite decimal-string amount and MWh/GWh
unit, dates and independent pricing-reference provenance. Unknown/mixed keys,
duplicate IDs/keys and implicit numeric coercions refuse. V1/V2 share documents
remain owned by their unchanged existing parser. A pricing reference does not
approve or calculate price/indexation. `require_production_contract` always
refuses: parsing alone never promotes a candidate.

`period_review.source_from_inputs` reads the existing canonical adapter,
PeriodEngine and full_generation_schedule for the supplied effective typed
Solar/Wind inputs. It does not derive another forecast, resolve ownership or
infer a scenario. Only the exact admitted P50/P90-10y case names are supported;
unknown cases cannot reach the core generator's P50 fallback. Full typed input,
explicit context and every actual period bind a content-only source identity.
Changing a source row, case, input fingerprint or context changes that identity.
It is not a signed approval, workspace CAS or committed Run identity.

`review_declared_deliveries` compares explicitly supplied deliveries against
that period source with exact rational arithmetic. Every active contract-period
pair must be supplied, including an explicit zero. Missing is not zero. Nothing
is silently clipped. Off-boundary dates refuse; no day/seasonal/anniversary
allocation is generated. A refused row's negative uncontracted amount is an
oversubscription diagnostic, never an actual negative merchant delivery.

A WITHIN_LIMIT result proves ONLY the submitted period quantities fit the
submitted source. **It does not prove that those rows fulfil the annual quantity
in the document.** Annual clock, delivery shape, partial dates, business
precision/tolerance and shortfall economics remain unresolved. The review
reports annual_semantics_verified/pricing_verified/production_supported false,
also on cap refusals. No prices, indexation, CfD settlement, purchase costs,
Revenue or financial outcomes are calculated here. Merchant/UNSOLD is an
unpriced residual; an overlay is not a supported candidate delivery type.

Exact result amounts contain numerator/denominator strings with units. Display
rounding never decides acceptance. Existing share epsilon is not borrowed as a
MWh/GWh business tolerance. HTTP tests against the unchanged canonical stack
must distinguish legacy successes and new-format fail-closed rollback from
future absolute-quantity positive endpoint/Run/History acceptance.

Before final production integration: verify and ordinarily merge accepted #446
main/source/bundle/flags, preserving accepted C06, complete a reviewed finite production
successor, close required policy, connect the same canonical final effective
candidate validation to Direct Save/atomic Save All/Run, and prove actual sealed
History and browser behavior. Do not use this preparatory branch as a completed
production feature or a reason to weaken the parent's red governance checks.

The separate `frontend/src/app/workflow/r04Candidate/` component is unmounted.
It edits decimal text and unit only, displays supplied server period facts, and
always explains the closed annual-production gate. It has no Save/Run controls,
forecast, unit conversion or cap calculation. Its isolated render/syntax checks
run via `node src/app/workflow/r04Candidate/candidate.test.mjs` from frontend;
these are not real-browser, served-bundle or final UI acceptance. Typechecking
must pass; final build/wiring waits for accepted parent source and policy.

Source scalar admission follows the existing operating engine's finite,
nonnegative capacity/hour and [0,1] availability domains, selected P90 positive
hours, and core [0,1] degradation constraint. Negative factors cannot cancel
into an apparently valid positive forecast. Zero source generation can be
reviewed without claiming full financial-input validity or annual delivery
approval; a full financial validator has additional independent conditions.
This does not modify technical, pricing or accounting policy in the engines.


Period reports use start_boundary_label/end_boundary_label, never an unsupported
end_exclusive claim. Canonical source records also preserve actual engine
days_in_period/day_fraction and bind them into content identity. The released
semiannual axis has an inclusive-day exception; quarterly axes can differ. No
calendar normalization, day shift or owner annual convention is chosen here.
calendar_delivery_interval_verified remains false even when boundary labels
match. The unmounted frontend is unchanged until the #446 integration phase.
