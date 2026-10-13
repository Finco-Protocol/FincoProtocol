# FINCO Revenue V2 — Correction B: protected financial authority review

**VERDICT: PROPOSED ONLY; independent financial authorization PENDING. NO MERGE.**

## Exact file and content identity

- Main baseline: `b47aa732f567e380cbe4c8e20b6c1a7dc0db9fbf`
- Protected file: `domain/revenue/multistream_runtime.py`
- Existing independently released WF07 pin (old Git blob): `94e1559472d0f3051fb7faccf3b67ce44337188f` (9,351 bytes)
- Proposed changed Git blob: `48465ce2a298fa1383a7eabcb921eb9fbe4610cb` (13,134 bytes)
- Governing map: `tests/model_v2_governance.py::WF07_REVENUE_AUTHORITIES`; exact released content required by `released_engine_authority_matches`
- `docs/model_v2/ACTIVE_EPIC_SCOPE.json` absent on current main; no phase-specific waiver active
- No engine/core/financing policy, baseline golden or currently approved release pins changed by Correction B

## Complete financial authority diff

This unified patch is the actual GitHub-returned change to the **only protected path** in this PR.

```diff
@@ -42,6 +42,8 @@ class DatedRevenueStream:
     start_date: date
     end_date: date  # exclusive, canonical boundary; no prorating inside a period
     source_ref: str
+    # Version-2 explicit nominal EUR/MWh points, exactly one per active operating period.
+    price_curve: tuple[tuple[date, float], ...] = ()
 
     def active(self, when):
         return self.start_date <= when < self.end_date
@@ -54,7 +56,29 @@ class MultiStreamRevenue:
     canonical_json: str
 
     def plan_at(self, when):
-        streams = tuple(replace(s.stream, enabled=s.active(when)) for s in self.streams)
+        # V1 keeps the exact historical code path and floating-point operations.
+        if not any(s.price_curve for s in self.streams):
+            streams = tuple(replace(s.stream, enabled=s.active(when)) for s in self.streams)
+        else:
+            adjusted = []
+            for dated in self.streams:
+                stream = replace(dated.stream, enabled=dated.active(when))
+                if stream.enabled and dated.price_curve:
+                    point = next((price for starts, price in dated.price_curve if starts == when), None)
+                    if point is None:
+                        raise ValueError("REVENUE_V2_CURVE_MISSING: no exact price for active operating period")
+                    if stream.stream_type is RevenueStreamType.PPA:
+                        stream = replace(stream, ppa=replace(stream.ppa,
+                            ppa_base_price_eur_mwh=point, ppa_price_index=0.0))
+                    elif stream.stream_type is RevenueStreamType.MERCHANT:
+                        # The existing Merchant price formula and CfD raw reference both
+                        # resolve this period's explicit nominal reference price.
+                        stream = replace(stream, merchant=replace(stream.merchant,
+                            base_price_eur_mwh=point, price_escalation_annual=0.0))
+                    else:
+                        raise ValueError("REVENUE_V2_CURVE_UNSUPPORTED: settlement overlays cannot have price curves")
+                adjusted.append(stream)
+            streams = tuple(adjusted)
         plan = RevenuePlan.create(streams)
         # CfD volume must be backed by the referenced physical merchant sale.
         for merchant in streams:
@@ -81,6 +105,12 @@ def validate_axis(self, periods):
         for dated in self.streams:
             if dated.start_date not in boundaries or dated.end_date not in boundaries:
                 raise ValueError("REVENUE_V2_AXIS: contract dates must match canonical operating boundaries")
+            if dated.price_curve:
+                expected = tuple(p.start_date for p in operating
+                                 if dated.start_date <= p.start_date < dated.end_date)
+                actual = tuple(point[0] for point in dated.price_curve)
+                if actual != expected:
+                    raise ValueError("REVENUE_V2_CURVE_AXIS: exactly one ordered price for every active operating period; no interpolation or extrapolation")
             for p in operating:
                 if dated.start_date < p.end_date and dated.end_date > p.start_date:
                     if not (dated.start_date <= p.start_date and p.end_date <= dated.end_date):
@@ -111,8 +141,8 @@ def parse_config(raw: str | None) -> MultiStreamRevenue | None:
     except (ValueError, TypeError) as exc:
         raise ValueError(f"REVENUE_V2_SCHEMA: {exc}") from exc
     _object(payload, {"version", "technology", "indexation_basis", "streams"}, "configuration")
-    if type(payload["version"]) is not int or payload["version"] != 1:
-        raise ValueError("REVENUE_V2_VERSION: expected version 1")
+    if type(payload["version"]) is not int or payload["version"] not in (1, 2):
+        raise ValueError("REVENUE_V2_VERSION: expected version 1 or 2")
     if payload["technology"] not in ("solar", "wind"):
         raise ValueError("REVENUE_V2_TECHNOLOGY: only Solar/Wind are supported")
     if payload["indexation_basis"] != "OPERATING_YEAR":
@@ -123,7 +153,7 @@ def parse_config(raw: str | None) -> MultiStreamRevenue | None:
     for row in payload["streams"]:
         _object(row, {"id", "type", "start_date", "end_date", "volume_share", "price_eur_mwh",
                       "indexation_rate", "settlement", "source_ref"}, "stream",
-                {"capture_rate", "reference_stream_id"})
+                {"capture_rate", "reference_stream_id", "price_curve"})
         if not isinstance(row["type"], str) or row["type"] not in SUPPORTED_TYPES:
             raise ValueError(f"REVENUE_V2_UNSUPPORTED_STREAM: {row['type']!r}")
         for key in ("id", "source_ref"):
@@ -141,6 +171,30 @@ def parse_config(raw: str | None) -> MultiStreamRevenue | None:
         index = _number(row["indexation_rate"], "indexation_rate", 1.0)
         share = None if row["volume_share"] is None else _number(row["volume_share"], "volume_share", 1.0)
         kind = RevenueStreamType(row["type"])
+        curve = ()
+        if "price_curve" in row:
+            if payload["version"] != 2 or kind not in (RevenueStreamType.PPA, RevenueStreamType.MERCHANT):
+                raise ValueError("REVENUE_V2_CURVE_UNSUPPORTED: curves require V2 physical PPA/Merchant")
+            if index != 0:
+                raise ValueError("REVENUE_V2_CURVE_INDEXATION: explicit prices cannot be additionally indexed")
+            raw_points = row["price_curve"]
+            if not isinstance(raw_points, list) or not raw_points or len(raw_points) > 600:
+                raise ValueError("REVENUE_V2_CURVE_POINTS: expected 1-600 explicit period prices")
+            parsed = []
+            for point in raw_points:
+                _object(point, {"period_start", "price_eur_mwh"}, "price point")
+                if not isinstance(point["period_start"], str) or len(point["period_start"]) != 10:
+                    raise ValueError("REVENUE_V2_CURVE_DATE: ISO operating period required")
+                try:
+                    when = date.fromisoformat(point["period_start"])
+                except ValueError as exc:
+                    raise ValueError("REVENUE_V2_CURVE_DATE: ISO operating period required") from exc
+                if when.isoformat() != point["period_start"] or not start <= when < end:
+                    raise ValueError("REVENUE_V2_CURVE_TENOR: price point outside contract tenor")
+                if parsed and when <= parsed[-1][0]:
+                    raise ValueError("REVENUE_V2_CURVE_ORDER: duplicate, unordered or overlapping points")
+                parsed.append((when, _number(point["price_eur_mwh"], "curve.price_eur_mwh")))
+            curve = tuple(parsed)
         options = {}
         if kind is RevenueStreamType.PPA:
             options["ppa"] = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=price,
@@ -161,7 +215,7 @@ def parse_config(raw: str | None) -> MultiStreamRevenue | None:
         if kind is not RevenueStreamType.CFD and "reference_stream_id" in row:
             raise ValueError("REVENUE_V2_SCHEMA: reference_stream_id belongs only to CfD")
         stream = RevenueStream(stream_id=row["id"], stream_type=kind, volume_share=share, **options)
-        dated_streams.append(DatedRevenueStream(stream, start, end, row["source_ref"]))
+        dated_streams.append(DatedRevenueStream(stream, start, end, row["source_ref"], curve))
     config = MultiStreamRevenue(payload["technology"], tuple(dated_streams),
                                 json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
     for when in sorted({s.start_date for s in dated_streams} | {s.end_date for s in dated_streams}):
```

## Economic interpretation and independent verification requirements

**V1 parity:** Version 1 books (no `price_curve`) take the existing `plan_at` code path, without changing fixed/indexed PPA, Merchant or CfD semantics. A V2 book without a curve also uses the unchanged calculation path. Existing V1 fixed/indexed, legacy inactive Solar/Wind/DC/EV and historical Run results must remain identical.

**V2 nominal prices:** Each physical PPA/Merchant contract can declare sorted exact operating period start/date and nonnegative nominal EUR/MWh. Exactly one point per active period. Price points override the scalar for the active period; simultaneous indexation is forbidden, never compounded. Missing, duplicate, overlapping, unordered, nonfinite, and out-of-tenor points fail closed; interpolation/hold-last/extrapolation are unsupported. No new settlement formula is introduced.

**Shares and settlement, independently calculated:** Synthetic primary shares PPA alpha=45%, PPA beta=35%, residual Merchant=20%, physical total=100%. An additional CfD 20% is an **overlay, not another MWh allocation**. PPA alpha is 55 EUR/MWh for first two periods and 47 thereafter; beta is fixed 70 EUR/MWh. Merchant raw reference is 40 (first two periods), 95 (later), capture=80%; CfD strike=65; settlement two-way signed. On G generating MWh:

- Physical Merchant cash [kEUR] = G × 0.20 × raw_price × 0.80 / 1000.
- CfD cash [kEUR] = G × 0.20 × (65 − raw_price) / 1000.
- Total cash sums the physical primary legs **once** and adds only the CfD settlement; the CfD reference is raw, not capture-adjusted.
- If price falls 10% at raw=40, combined Merchant+CfD before is 6.4+5=11.4 EUR/G MWh; after is 5.76+5.8=11.56, +0.16.
- If price falls 10% at raw=95, combined before is 15.2−6=9.2 EUR/G MWh; after is 13.68−4.1=9.58, +0.38.
- If unhedged, downside effects are −0.64 EUR/G MWh at raw=40, and −1.52 at raw=95. This reversal is caused by capture < 100% on the physical sale and a CfD referencing raw price; do not change CfD signs to satisfy a monotonicity assertion.

**Downstream:** Revenue/EBITDA/CFADS, income tax, debt service coverage and investor returns must be reconciled through real Solar/Wind canonical Runs. The read-only stress service uses the existing runner and returns a comparative projection without modifying Working Copy, Last Run, Run History or saved scenario. Actual numeric residuals have not been independently measured as zero on this Correction B HEAD.

## Release authorization — no self-approved pin update

The exact WF07 released blob remains `94e1559472d0f3051fb7faccf3b67ce44337188f`, so the five observed protected-governance failures are **expected and correct** while proposed blob `48465ce2a298fa1383a7eabcb921eb9fbe4610cb` is unapproved.

The existing mechanism is exact-content release authorization, not a namespace waiver. Narrowest acceptable proposal: an independent financial reviewer signs the **exact new blob**, examines V1 parity and V2 per-period economic residuals including CfD and CFADS/tax/debt/returns, and an authorized governance/release owner then carries out a separately reviewed exact-content WF07 pin acceptance / release-gate action while retaining historical provenance and rejection of every unreviewed modification. The old pin cannot be silently replaced merely because tests passed. Active scope is absent, and broad `domain/revenue/` bypasses are forbidden.

**No author of this draft may self-approve the content pin.** The negative regression `test_every_further_edit_invalidates_authorization` must keep proving that even a one-byte unauthorised edit fails. Unrelated protected paths must remain forbidden.

## CI provenance

Original full Public Safety on HEAD `04cab75ae778498b1167b2b1314288dc417c229c` (run #38316517720) was **11 failed, 10312 passed, 66 skipped**, pytest rc=1, supervisor child exit=1. Source-safety succeeded, but mandatory evidence could not approve a failed control run.

Correction B updates only the supported editor type list, truthful CSRF inventory, synthetic negative fixtures, and independent Decimal stress accounting tests. It does **not** edit this protected runtime or any financial release pin. Until a new exact-head suite is completed and external financial authority is granted, **NO MERGE**.
