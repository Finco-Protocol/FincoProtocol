# C06 Correction C — Root Cause: `'synthetic' found in section inputs`

**PR:** #444 · **Base:** `b1c08e2d00fe9933565d253d5cee6e5849b143e1` · **Correction C branch state:** this commit
**Hosted failing run:** Protocol UI Browser Acceptance `43242867598`, job `131268169263` (`mandatory-browser-evidence`)

## 1. Exact failing assertion

```
tests/test_model_workspace_consolidation_browser.py::test_product_truth_no_prototype_or_synthetic_content_in_any_section
tests/model_react_wf1_browser_acceptance.py:116
AssertionError: 'synthetic' found in section inputs
```

The test seeds a canonical solar Working Copy (`create_reference_seeded_project(template_source="generic_solar_reference")`),
runs the canonical Run, walks all nine sections and scans `page.inner_text("body")` for the FORBIDDEN token list.

## 2. Exact visible string and its origin

The `fields/revenue` projection (`GET /v2/model-react/fields/revenue`) carries, for two
"Balancing & CO2" fields, the registry `description` verbatim as `help_text`:

| field_id | help_text (registry `app/workbook/registry.py`) |
|---|---|
| `revenue.balancing.merchant_pct` | "Balancing cost as a fraction of gross merchant electricity revenue. Applied only to spot sales (not PPA revenue). Excel CF row 40. **Synthetic reference assumption.**" |
| `revenue.balancing.co2_price_eur_mwh` | "CO2 / GoO certificate revenue per MWh of generation. NOT EUR/tCO2 — applied as EUR/MWh to total production (Excel CF row 46). **Synthetic reference assumption.**" |
| `revenue.merchant.price_curve_json` | "Calendar-year merchant price schedule as JSON array… **Synthetic illustrative schedule; no external workbook source is embedded.**" |

`SheetFieldsEditor` renders each editable field's help through `plainFieldHelp`
(`frontend/src/app/plainCopy.ts`). These texts matched neither `PLAIN_BY_FIELD` nor the
`TECHNICAL_SIGNS` engineer-marker regex, so the raw registry text — including the word
"synthetic" — became the **visible on-screen hint** (`<small class="wf-hint">`) of a live
canonical field. `page.inner_text("body")` therefore contained a contiguous `synthetic`
whenever the editor had mounted at assert time.

## 3. Why the failure was intermittent (navigation/loading race, category C timing)

`open_section()` waits only for "Loading the persisted…" / "Loading the canonical input grid…"
to disappear; it does **not** wait for the asynchronously mounted Revenue-assumptions
fields editor (`wf-inputs-revenue`). Both timing orders were reproduced deterministically
on this checkout:

- **Editor not yet mounted at capture** → body shows "Loading revenue assumptions…" →
  no `synthetic` → PASS (observed: repeated local runs, e.g. `evidence/c/diag-out/it00-inputs.txt` line 152).
- **Editor mounted at capture** → the visible hint carries the wording → FAIL. The hosted
  run's captured stdout shows the failure exactly as `fields/revenue` completed (200) as
  the last read before the assert.

## 4. Baseline comparison (pristine accepted `main` vs #444)

- `git show main:app/workbook/registry.py` contains the identical two
  "Synthetic reference assumption." descriptions (lines 694/733 at main).
- API payload grep on a pristine `main` checkout (`repo/main-wt`) shows the same 3
  `synthetic` hits in `fields/revenue` — byte-identical to #444 (`evidence/c/apigrep-main.log`).
- The same product-truth test exists at `main` and passes/flakes under the same timing.
  **The forbidden text existed at baseline; #444 did not newly introduce it** — the hosted
  #444 run hit the unlucky timing order of a pre-existing latent product-truth violation.

## 5. Root-cause category and remedy (packet §2)

**Category A** (prototype/demonstration language presented to users) with a category C
timing mask: the responsible user-facing boundary is the *presentation layer* of the help
text, not the guard that caught it. Per `plainCopy.ts`'s own documented contract
("help_text written for engineers … stays available behind a Technical-note disclosure;
the visible hint is plain language"), the fix routes any help copy carrying
prototype/demo/synthetic wording — and the `Excel CF row NN` provenance marker — to the
**Technical-note disclosure** (user-reachable, collapsed by default) instead of the visible
hint. No registry data, label, unit, value, validation or save path changed; the disclosed
text preserves the provenance caveats exactly.

**Changed file:** `frontend/src/app/plainCopy.ts` (`PRODUCT_TRUTH_SIGNS` + `Excel CF row`
in `TECHNICAL_SIGNS`), rebuilt served bundle `static/react/finco-react.js`.

**Steady-state verification (all editors mounted):** `synthetic` count in the inputs body
= **0**; Technical-note disclosures render (15 on the seeded solar project); the disclosed
text remains available on demand. The test now passes in **both** timing orders, and the
new source-bound browser test
`test_inputs_product_truth_holds_in_both_editor_timing_orders` pins it.

## 6. What was explicitly NOT done

- No forbidden-token list change, no skip/xfail, no test deletion, no CSS hiding of product
  truth, no stdout suppression.
- `app/workbook/registry.py` was **reverted** to its exact `main` bytes: rewriting the
  canonical registry descriptions would move a financial-validation-governance path
  (`fin_v2_3`/`wf04` manifests), outside this correction's finite scope. The presentation
  boundary is the sanctioned user-facing source for this remedy.
