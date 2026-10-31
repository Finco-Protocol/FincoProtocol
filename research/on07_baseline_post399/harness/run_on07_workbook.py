#!/usr/bin/env python3
"""ON-07 canonical-workbook-route local runner (disposable SQLite DB, in-process, no network, no HTTP, no auth).
Emulates: reference-seeded Working Copy -> EXPLICIT fixture cells -> POST /v2/workbook/run steps 7-11
(ProjectInputSet.from_snapshot -> to_projectinputs -> CAPEX/OPEX sub-line folds -> run_project). It does NOT run
steps 1-6 (auth/CSRF/CAS), the atomic commit, history persistence, or the process executor.
python -I run_on07_workbook.py --repo <main checkout> --fixtures <ON07_PROJECT_FIXTURES.csv> --out <dir> [--fixture SOL-01 ...]
"""
import argparse, csv, json, os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C

TS = {"solar_pv": ("generic_solar_reference", "Solar"), "wind_onshore": ("generic_wind_reference", "Wind")}
# fixture_key -> snapshot keys written for NON-registry or mirrored keys (all recorded in the capture)
EXTRA_KEYS = {"operating_hours_p90_10y": ["operating_hours_p90_10y"], "total_capex_keur": ["total_capex_keur"],
              "opex_y1_keur": ["opex_y1_keur"], "rev_ppa_base_tariff": ["tariff_eur_mwh"], "rev_ppa_term_years": ["ppa_term_years"]}
SKIP = {"project_type", "currency", "financial_close", "scenario", "project_name", "country_market", "period_frequency"}

def load(path):
    fx = {}
    for r in csv.DictReader(open(path, newline="")):
        fx.setdefault(r["fixture_id"], []).append(r)
    return fx

def coerce(v):
    v = v.strip()
    if v in ("(empty)", "*(empty)*", ""): return ""
    if v.lower() in ("true", "false"): return v.lower() == "true"
    return v

def get_path(o, path):
    for p in path.split("."):
        o = getattr(o, p, None)
        if o is None: return None
    return o

def effective(pi):
    from_paths = {
     "capacity_mw": "technical.capacity_mw", "p50_hours": "technical.operating_hours_p50",
     "operating_hours_p90_10y": "technical.operating_hours_p90_10y", "operating_hours_p99_1y": "technical.operating_hours_p99_1y",
     "pv_degradation": "technical.pv_degradation", "cod_date": "info.cod_date", "construction_months": "info.construction_months",
     "financial_close": "info.financial_close", "horizon_years": "info.horizon_years",
     "rev_ppa_base_tariff": "revenue.ppa_base_tariff", "rev_ppa_term_years": "revenue.ppa_term_years",
     "rev_ppa_index": "revenue.ppa_index", "rev_ppa_production_share": "revenue.ppa_production_share",
     "rev_ppa_indexation_start_policy": "revenue.ppa_indexation_start_policy", "rev_balancing_cost_eur_per_mwh": "revenue.balancing_cost_eur_per_mwh",
     "rev_co2_enabled": "revenue.co2_enabled", "rev_co2_price_eur_mwh": "revenue.co2_certificate_price_eur_per_mwh",
     "total_capex_keur": "capex.total_capex", "gearing_pct": "financing.gearing_ratio", "tenor_years": "financing.senior_tenor_years",
     "target_dscr": "financing.target_dscr", "cit_rate_pct": "tax.corporate_rate", "loss_carryforward_years": "tax.loss_carryforward_years"}
    out = {k: get_path(pi, p) for k, p in from_paths.items()}
    try: out["opex_y1_keur"] = sum(float(i.y1_amount_keur) for i in pi.opex)
    except Exception: out["opex_y1_keur"] = None
    try: out["interest_rate_pct"] = pi.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates
    except Exception: out["interest_rate_pct"] = None
    try: out["rev_merchant_curve"] = list(pi.revenue.market_prices_by_calendar_year_eur_mwh)
    except Exception: out["rev_merchant_curve"] = None
    try: out["rev_merchant_balancing_pct"] = [pi.revenue.balancing_cost_pv, pi.revenue.balancing_cost_wind_eur_mwh]
    except Exception: out["rev_merchant_balancing_pct"] = None
    return out

def to_num(x):
    try: return float(x)
    except Exception: return None

def compare(key, intended, eff):
    """Binding verdict per EXPLICIT key. Never silently PASS an unreadable effective value."""
    if key not in eff: return "NOT_READ_BACK", ""
    e = eff[key]
    if e is None: return "NOT_READ_BACK", "effective value not found at probed path"
    if key == "rev_merchant_balancing_pct":
        want = to_num(intended)
        ok = any(n is not None and abs(n * 100 - want) < 1e-9 for n in e)
        return ("MATCH" if ok else "MISMATCH"), f"effective(pv_fraction, wind_eur_mwh)={e}; Solar reads balancing_cost_pv; Wind path unconfirmed"
    if key == "interest_rate_pct":
        vals = list(e) if hasattr(e, "__iter__") and not isinstance(e, (str, float)) else [e]
        want = to_num(intended); nums = [to_num(v) for v in vals]
        ok = want is not None and nums and all(n is not None and (abs(n - want / 100) < 1e-12 or abs(n - want) < 1e-12) for n in nums)
        return ("MATCH" if ok else "MISMATCH"), f"effective={vals[:3]}"
    scale = {"rev_ppa_index": 100.0, "rev_ppa_production_share": 100.0, "gearing_pct": 100.0, "cit_rate_pct": 100.0}.get(key)
    if isinstance(e, bool) or isinstance(intended, bool): return ("MATCH" if bool(e) == bool(intended) else "MISMATCH"), f"effective={e}"
    n_i, n_e = to_num(intended), to_num(e)
    if n_i is not None and n_e is not None:
        cands = [n_e] + ([n_e * scale] if scale else [])
        return ("MATCH" if any(abs(c - n_i) <= 1e-9 * max(1, abs(n_i)) for c in cands) else "MISMATCH"), f"effective={e}"
    return ("MATCH" if str(e)[:10] == str(intended)[:10] else "MISMATCH"), f"effective={e}"

def run_fixture(fid, rows, a):
    from datetime import date
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.service import WorkbookService
    from app.workbook.update_service import WorkbookUpdateService
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.api.project_runner import run_project
    from dataclasses import replace
    ex = {r["fixture_key"]: r for r in rows if r["source_class"] == "EXPLICIT"}
    ptype = ex["project_type"]["intended_value"]; tsrc, key = TS[ptype]
    rec = create_reference_seeded_project(user_id="on07-local", template_source=tsrc, requested_name=ex["project_name"]["intended_value"],
                                          capacity_mw=float(ex["capacity_mw"]["intended_value"]), country_market=ex["country_market"]["intended_value"])
    snap = dict(get_workspace_state("on07-local", rec.project_id).draft_snapshot)
    seed_snapshot = dict(snap)
    applied, validation = {}, {}
    for k, r in ex.items():
        if k in SKIP: continue
        val = coerce(r["intended_value"])
        fld = WORKBOOK.field_id_to_snapshot_key
        spec = None
        try: spec = WORKBOOK.field(r["finco_field_id"])
        except Exception: pass
        targets = ([spec.snapshot_key] if spec else []) + EXTRA_KEYS.get(k, [])
        if not targets: validation[k] = "NO_SNAPSHOT_TARGET"; continue
        if spec is not None and val != "":
            try:
                v = WorkbookUpdateService.validate_field_update(spec.field_id, str(val))
                validation[k] = "VALID" if v.is_valid else f"INVALID:{getattr(v,'error',None) or getattr(v,'message',None)}"
            except Exception as e: validation[k] = f"VALIDATOR_ERROR:{type(e).__name__}"
        else: validation[k] = "NOT_VALIDATED(registry-less or empty)"
        for t in targets: snap[t] = val; applied.setdefault(k, []).append(t)
    snap["cod_date"] = ex["cod_date"]["intended_value"]; snap["construction_months"] = ex["construction_months"]["intended_value"]
    pis = WorkbookService.build_input_set(snap)
    cap = {"fixture": fid, "status": "UNSET", "snapshot_applied_keys": applied, "registry_validation": validation,
           "seed_snapshot_digest": C.sha(seed_snapshot), "fixture_snapshot_digest": C.sha(snap),
           "unknown_keys": list(pis.unknown_keys), "coercion_errors": list(pis.coercion_errors), "workbook_version": pis.workbook_version,
           "workbook_snapshot_fingerprint_NOT_STABLE_ACROSS_DBS": pis.content_hash,
           "fixture_cell_digest": C.sha({k: coerce(r["intended_value"]) for k, r in sorted(ex.items())})}
    try:
        override = WorkbookService.to_projectinputs(pis)
        cap["effective_before_folds"] = {k: (str(v) if v is not None else None) for k, v in effective(override).items()}
        cap["variant"] = "SNAPSHOT_TOTALS_NO_SUBLINE_FOLD (NOT the Run route)" if a.no_subline_fold else "RUN_ROUTE_STEPS_7_TO_11"
        fc = override.capex if a.no_subline_fold else apply_user_sub_lines_replacing_base(override.capex, project_id=rec.project_id, scenario_overrides=None)
        if fc is not override.capex: override = replace(override, capex=fc)
        fo = override.opex if a.no_subline_fold else apply_user_sub_lines_to_opex(override.opex, project_id=rec.project_id, scenario_overrides=None)
        if fo is not override.opex: override = replace(override, opex=fo)
        eff = effective(override)
        cap["effective_inputs"] = {k: (str(v) if v is not None else None) for k, v in eff.items()}
        cap["binding_check"] = {}
        for k, r in ex.items():
            if k in SKIP: continue
            if k == "rev_merchant_price_curve_json":
                import json as _j
                want = [round(float(x["price_eur_mwh"]), 6) for x in _j.loads(r["intended_value"])] if coerce(r["intended_value"]) else None
                got = [round(float(x), 6) for x in (eff.get("rev_merchant_curve") or [])]
                ok = want is None or got[:len(want)] == want
                cap["binding_check"][k] = {"verdict": "MATCH" if ok else "MISMATCH", "intended": f"{len(want or [])} points", "detail": f"effective points={len(got)}; intended prefix equal={ok}" if want else "intended empty: factory curve remains (recorded, not harmonised)"}
                continue
            cap["binding_check"][k] = dict(zip(("verdict", "detail"), compare(k, coerce(r["intended_value"]), eff)), intended=r["intended_value"])
        res = run_project(key, "Base", "Semiannual", project_inputs_override=override)
        cap.update(model_input_digest=C.sha(repr(override)))
        if res.get("kpis") is None or res.get("integration_status") != "full":
            cap.update(status="REFUSED", integration_status=res.get("integration_status"), messages=res.get("messages"))
        else:
            cap.update(status="RUN_OK", kpis=res["kpis"], sources_uses=res.get("sources_uses"), debt_schedule=res["debt_schedule"],
                       tax_schedule=res.get("tax_schedule"), distribution_schedule=res.get("distribution_schedule"),
                       sponsor_schedule=res.get("sponsor_schedule"), tables=res.get("tables"), financial_statements=res.get("financial_statements"),
                       derivation_evidence=res.get("derivation_evidence"), integrity_evidence=res.get("integrity_evidence"),
                       financing_evidence=res.get("financing_evidence"), runtime_authority=res.get("runtime_authority"),
                       identities=C.identities(res), integrity_digest=(res.get("integrity_evidence") or {}).get("digest"))
            cap["evidence_digest"] = C.sha({k: cap[k] for k in ("kpis", "sources_uses", "debt_schedule", "fixture_cell_digest", "model_input_digest")})
            cap["input_fingerprint"] = cap["model_input_digest"]   # stable economic fingerprint = sha256(repr(effective ProjectInputs))
            bad = [k for k, v in cap["binding_check"].items() if v["verdict"] != "MATCH"]
            cap["binding_mismatches"] = bad
    except Exception as e:
        cap.update(status="REFUSED_OR_ERROR", error_type=type(e).__name__, error=str(e)[:600])
    cap["environment"] = C.environment(a.repo)
    return cap

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--fixtures", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--fixture", action="append")
    ap.add_argument("--no-subline-fold", action="store_true", help="VARIANT (not the Run route): skip step 9-10 sub-line folds so snapshot CAPEX/OPEX totals bind")
    a = ap.parse_args()
    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07_"), "disposable.db")
    C.repo_setup(a.repo); os.makedirs(a.out, exist_ok=True)
    fx = load(a.fixtures); summary = {}
    for fid in (a.fixture or ["SOL-01", "SOL-02", "WND-01", "WND-02"]):
        cap = run_fixture(fid, fx[fid], a)
        json.dump(cap, open(os.path.join(a.out, f"{fid}.json"), "w"), indent=1, default=str)
        summary[fid] = {"status": cap["status"], "binding_mismatches": cap.get("binding_mismatches"), "error": cap.get("error")}
        print(fid, summary[fid])
    json.dump(summary, open(os.path.join(a.out, "RUN_SUMMARY.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
