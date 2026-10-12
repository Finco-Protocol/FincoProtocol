# Revenue V2 Advanced — Exact-Period Price Curves & Commercial Case V1

**Baseline:** main \`1152dd2d98b5da8b41cea52ce9867619a3e85fba\`.
**Scope:** one Draft PR. Proposed sensitive financial authority changes are NOT approved
for production until independent financial governance review and exact-head CI.

## Preimplementation capability inventory

| Capability | Decision | Existing authority / proposed change |
| --- | --- | --- |
| Two PPAs, fixed/indexed PPA | EXISTING | Revenue V2 \`parse_config\`, \`PPAParams\`, \`RevenuePlan\` |
| Merchant, residual volume, capture | EXISTING | \`MerchantParams\` + canonical allocation |
| Fixed two-way CfD | EXISTING | \`CfDParams\`, Merchant raw reference (before capture) |
| Dated activation, conservation | EXISTING | \`MultiStreamRevenue.validate_axis\`, \`plan_at\` |
| Scenario override/inherit, CSRF/CAS | REUSABLE | existing Revenue POST + \`save_contracts\` |
| Canonical financial runner, sensitivity KPIs | REUSABLE | \`app.services.sensitivity_service._run_once\` |
| Immutable Run/History/export | REUSABLE | existing \`multistream_config_json\` persisted on successful Run |
| Legacy Merchant annual curve | EXISTING (DIFFERENT AUTHORITY) | \`static/js/model_merchant_curve.js\`: scalar calendar-year field, NOT contract price |
| Demo merchant curves | EXISTING (NON-AUTHORITY) | \`app/merchant_curves.py\`: synthetic demos only |
| Exact contract PPA/Merchant curves | EXTEND | V2 \`price_curve\` on individual physical streams; period-price binding |
| UI curve paste/edit; read-only price stress | EXTEND | existing structured editor, existing canonical sensitivity seam |
| New CfD strike curves | UNSUPPORTED | CfD strike stays fixed, existing signed settlement |
| Curve interpolation/hold-last/extrapolation | UNSUPPORTED | no inferred prices |
| Lender-specific pricing, bank debt-policy overrides | UNSUPPORTED | \`bank_case_status=UNAVAILABLE\`, no new solver |
| Capacity, ancillary, REC, lagged settlement | UNSUPPORTED | existing rejection retained |
| Data Center / EV advanced revenue | UNSUPPORTED | Solar/Wind only, legacy other verticals unchanged |

## Versioned contract semantics — financial review required

**V1 remains unchanged**: root \`version:1\`, exact original field schema, unchanged
PPA annual indexation, Merchant escalated base, capture and fixed CfD settlement.
No migration or rewriting of stored V1 payloads.

**V2 opt-in**: root \`version:2\`. A physical PPA or Merchant stream may add
\`price_curve\` with 1–600 rows of:
\`\`\`json
{"period_start":"2031-01-01","price_eur_mwh":55.0}
\`\`\`

Each point is nominal EUR/MWh for one **exact canonical operating period start**
and is associated with its immutable contract ID. Each active operating period
must have **exactly one** point. Dates must be ISO, strictly increasing and inside
\`[start_date,end_date)\`, with the last active period price explicitly supplied.
No partial periods, duplicate points, out-of-tenor rows, inferred missing prices,
interpolation, carry-forward, or extrapolation. Source refs remain required at
contract level. Step-up/down is explicit change in adjacent period point values.

**Precedence:** if \`price_curve\` exists on a physical contract, its exact
period price is the sole nominal price input; \`indexation_rate\` must equal 0.
For the active period only, the existing domain PPA/Merchant object is copied
with the explicit price and index/escalation disabled. Existing \`RevenuePlan\`
physical-share, capture and CfD reference/settlement formulas perform all
economic calculations; the browser never computes revenues. A flat scalar
\`price_eur_mwh\` remains structurally required for backward shape compatibility
but **is not an additional economic term** while a curve is active. V2 without
a curve retains V1 price math. CfD never accepts a curve on its strike.

The exact-period binding is proposed in
\`domain/revenue/multistream_runtime.py\`. This is a **protected financial
authority integration change**, not a new calculator: independent financial
approval is MANDATORY before merge/release. Existing \`domain/revenue/plan_engine.py\`,
\`domain/revenue/revenue_config.py\`, financing, tax, returns, core and
numerical tolerances are unchanged.

## Commercial price stress and bank-case boundary

One authenticated, signed-CSRF, composite-CAS POST at
\`/v2/workbook/revenue/stress\` reads the current authorized Working Copy and
active scenario. It uses the existing sensitivity/production waterfall runner
for two **ephemeral** input snapshots:

- Base commercial contract book as currently selected.
- Merchant down/up percentage, PPA price down percentage, or an explicitly dated
  earlier PPA expiry where exactly one PPA is covered and an existing residual
  Merchant takes the uncontracted volume.

Stress magnitude must be supplied by the user (0–100%), not silently calibrated.
Merchant stress shifts **raw reference price**; the existing capture factor still
applies to physical Merchant sales, whereas existing CfD uses the raw reference.
PPA expiry reassigns physical volume only when an existing residual Merchant
provides the authority. Scenario creation, selection, storage, debt-method
override and Last Run promotion do not happen. The workbook identity is
revalidated after the comparison to discard results from stale selection.

Canonical sensitivity KPIs include revenue, EBITDA, CFADS, tax, debt service,
coverage, project/equity IRR, distribution and NPV when supported. Missing
metrics remain unavailable. The displayed \`bank_case_status=UNAVAILABLE\`
means a **lender-authorised price/debt haircut/discount basis is NOT
established**: this preview is a hypothetical commercial comparison using
the existing canonical financing methodology, not a bank-certified case.

## Governance, privacy and acceptance

Exact review scope:

- **Sensitive authority proposal:** \`domain/revenue/multistream_runtime.py\`.
  Requires independent financial reviewer to confirm precedence, curve dates,
  price/capture/reference separation, fixed CfD, and V1 bit-exact parity.
- **Read-only financial wrapper:** \`app/workbook/revenue_commercial_stress.py\`.
  Reviewer must verify single existing runner, no persistence or scenario fork.
- **Authenticated route:** \`app/v2/router.py\` (one new route; CSRF, ownership,
  protected Reference, composite CAS and post-compute identity recheck).
- **Presentation:** existing Revenue editor template, JS, CSS, one stress-result
  partial. No new editor or JSON second writer.
- **Tests:** new synthetic exact-period/numerical/negative and authenticated
  route tests. Existing WF07, #252, F0, F3/F3.8, Run History and legacy parity
  tests are retained unchanged.

No new financial goldens, tolerated differences, loan policies, price or FX
assumptions, protected release pins, or export-time financial engine Run. Current
V1 Run-bound \`multistream_config_json\` carries V2 pricing verbatim to immutable
Last Run and \`Revenue_Streams\` audit without a separate export computation.

Execute focused tests and full exact-head CI including unsharded Public Safety
pytest rc=0 and supervisor exit=0, six browser roles, Governance, Security and
Compile. Obtain genuine Solar/Wind Run numerical reports, before/after
desktop/mobile screenshots, scenario save/reload, and historical export checks.
**NO SELF-APPROVAL / MERGE / DEPLOY** until reviewed.
