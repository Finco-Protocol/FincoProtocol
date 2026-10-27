"""Evidence-bound FIN-V2-3 report rows; contains no financial calculator."""
from app.export.run_evidence import number


def write_financial_core(wb, ev, ledger, rows, executive_sheet, lender_sheet):
    from app.export import institutional_reporting_v2 as V2
    from app.export.reporting_common import KEUR_FORMAT, MULTIPLE_FORMAT
    core = ev.financial_core
    status = core.get("status", "NOT_PERSISTED")
    source = "runtime_summary.financing_evidence.financial_core_v1"
    for sheet in (executive_sheet, lender_sheet):
        # Append a cursor without rewriting the existing report's title/binding.
        cur = object.__new__(V2._Cursor)
        cur.sheet, cur.ev, cur.row = wb[sheet], ev, wb[sheet].max_row + 3
        cur.section("FIN-V2-3 explicit valuation and sponsor authority")
        items = [("Financial core evidence status", status, source, "Old Runs are never back-filled", None),
                 ("Generic tax policy", core.get("tax_policy_classification"), source,
                  "GENERIC_MVP_POLICY; jurisdictional statutory compliance is not assessed", None),
                 ("Formal covenant assessment", "CONTRACTUAL_ASSESSMENT_NOT_AVAILABLE", source,
                  "No lender covenant contract, default-event conclusion or investment recommendation", None)]
        if status == "PERSISTED":
            coverage = core["loan_life_coverage"]
            metric_policy = core["sponsor_metric_policy"]
            metric_keys = (("Total Sponsor NPV", "sponsor_npv_keur", KEUR_FORMAT),
                           ("Contractual-maturity LLCR", "llcr_contractual_maturity", MULTIPLE_FORMAT),
                           ("Actual-repayment LLCR", "llcr_actual_repayment", MULTIPLE_FORMAT),
                           ("LLCR at first Senior opening", "llcr_at_first_senior_opening", MULTIPLE_FORMAT),
                           ("Minimum rolling LLCR", "min_rolling_llcr", MULTIPLE_FORMAT),
                           ("Project-life coverage ratio", "plcr", MULTIPLE_FORMAT))
            for label, key, fmt in metric_keys:
                calculation_status = (core["sponsor_npv"]["status"] if key == "sponsor_npv_keur"
                                      else core["valuation_summary"]["lender_coverage"]["llcr" if key == "llcr_at_first_senior_opening" else "plcr"]["status"]
                                      if key in ("llcr_at_first_senior_opening", "plcr") else coverage["status"])
                items.append((label, number(core.get(key)), source + "." + key,
                              f"Status: {calculation_status}; configured policy below", fmt))
            import json
            items.extend([
                ("Valuation policy version", core.get("valuation_policy_version"), source, "Absent policies: NOT_CONFIGURED", None),
                ("Valuation policy", json.dumps(core["valuation_policy"], sort_keys=True), source,
                 "Rates are typed ratios. ACT/365 annual; periodic rate is quoted per model period", None),
                ("Rolling loan-life convention", core.get("rolling_loan_life"), source, "Historical min_llcr meaning preserved", None),
                ("Rolling minimum observation", (coverage.get("minimum") or {}).get("observation_date"), source,
                 "Observation-level ratios and discounted flows are retained with the Run", None),
                ("Primary Sponsor metric", metric_policy["primary"], source, "Total equity + SHL contributions and receipts", None),
                ("Secondary Sponsor metric", metric_policy["secondary"], source, "Pure Equity excludes SHL funding and receipts", None),
                ("Sponsor funding dates", metric_policy["funding_date_convention"], source, "Financial-close lump funding; actual dated flows persisted", None),
                ("Entered SHL amount", metric_policy["entered_shl_amount"], source, "Actual funding is engine-derived Sources & Uses", None),
                ("SHL timing contract", json.dumps(core["shl_timing"], sort_keys=True), source, "Absolute-index drift is disclosed; strict maturity refusals remain", None),
                ("Lender acceptance", core["lender_acceptance"], source, "Data Center / EV lender acceptance remains unverified", None),
            ])
        cur.kv(rows(ledger, sheet, items))
