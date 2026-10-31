#!/usr/bin/env python3
"""One-input-at-a-time binding probe over every v1 ProjectInputsSchema field (Solar). Writes ON07_V1_API_BINDING_PROBE.csv.
python -I binding_probe.py --repo <checkout> --out <csv>"""
import argparse, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
PROBES = [  # (label, base-schema patch, expected on07-concern)
 ("capacity_mw", {"capacity_mw": 70}), ("cod_date (+construction_months coupled)", {"cod_date": "2032-01-01", "construction_months": 18}),
 ("horizon_years", {"horizon_years": 30}), ("country_iso", {"country_iso": "DE"}), ("project_name", {"project_name": "X"}),
 ("operating_hours_p90_10y", {"operating_hours_p90_10y": 1300}), ("operating_hours_p99_1y", {"operating_hours_p99_1y": 1100}),
 ("revenue.tariff_eur_mwh", {"revenue": {"tariff_eur_mwh": 58}}), ("revenue.p50_hours", {"revenue": {"p50_hours": 1400}}),
 ("revenue.degradation_pct", {"revenue": {"degradation_pct": 3.0}}), ("revenue.ppa_term_years", {"revenue": {"ppa_term_years": 10}}),
 ("capex.total_capex_keur", {"capex": {"total_capex_keur": 40000}}), ("opex.opex_y1_keur", {"opex": {"opex_y1_keur": 700}}),
 ("opex.inflation_pct", {"opex": {"inflation_pct": 8.0}}), ("debt.gearing_pct", {"debt": {"gearing_pct": 60}}),
 ("debt.senior_debt_keur", {"debt": {"senior_debt_keur": 20000}}), ("debt.interest_rate_pct", {"debt": {"interest_rate_pct": 7.0}}),
 ("debt.tenor_years", {"debt": {"tenor_years": 12}}), ("debt.target_dscr", {"debt": {"target_dscr": 1.4}}),
 ("tax.cit_rate_pct", {"tax": {"cit_rate_pct": 30}}), ("tax.loss_carryforward_years", {"tax": {"loss_carryforward_years": 3}}),
]
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--out", required=True); a = ap.parse_args(); C.repo_setup(a.repo)
    bp, br = C.run_engine("Solar", "Base", "Annual", {"project_type": "Solar"})
    rows = []
    for label, patch in PROBES:
        d = {"project_type": "Solar", **patch}
        try:
            p, r = C.run_engine("Solar", "Base", "Annual", d)
            mi_changed, kpi_changed = (p != bp), (r["kpis"] != br["kpis"])
            if r.get("kpis") is None: verdict, note = "NOT_TESTED", "Run returned no KPIs: " + str(r.get("messages"))
            elif not mi_changed and not kpi_changed: verdict, note = "CONFIRMED_UNBOUND", "accepted by schema; model input and all KPIs identical to baseline"
            elif mi_changed and not kpi_changed: verdict, note = "BOUND_NO_KPI_EFFECT", "model input changed, headline KPIs unchanged (inspect tables)"
            else: verdict, note = "BOUND_AND_CONSUMED", "model input and KPIs changed"
            extra = f"p50/p90/p99={p.technical.operating_hours_p50}/{p.technical.operating_hours_p90_10y}/{p.technical.operating_hours_p99_1y}"
        except Exception as e:
            fc = "FAIL_CLOSED" in str(e)
            verdict, note, extra, mi_changed, kpi_changed = ("REFUSED_FAIL_CLOSED" if fc else "NOT_TESTED"), f"{type(e).__name__}: {e}"[:260], "", "", ""
        rows.append({"field": label, "probe_value": str(patch), "model_input_changed": mi_changed, "kpis_changed": kpi_changed, "verdict": verdict, "note": note, "tech_hours_after": extra})
        print(label, verdict)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
if __name__ == "__main__": main()
