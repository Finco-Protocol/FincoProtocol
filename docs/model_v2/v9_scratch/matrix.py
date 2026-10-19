"""V9-A benchmark/parity matrix over synthetic inputs (scratch)."""
import dataclasses as dc
import json
import sys
import time
from datetime import date

sys.path.insert(0, ".")
import harness as H  # noqa: E402
from app import project_factories as pf  # noqa: E402
from dateutil.relativedelta import relativedelta  # noqa: E402
from financial_engine.financing import generic_product_policy as GP  # noqa: E402

VARIANTS = {
    "B1": ("B1",), "D": ("D",), "BA": ("BA",), "BW": ("BW",), "B1+D": ("B1", "D"),
    "BG": ("BG",), "B": ("B1", "BA", "BW", "BG"), "C": ("C", "B1"), "FULL": ("C", "B1", "D", "BW", "BG"),
    "FULLnoD": ("C", "B1", "BW", "BG"),
    "CBW": ("C", "B1", "BW"),
}


def scale_capex(pi, k):
    cx = pi.capex
    upd = {}
    for f in cx._CAPEX_ITEM_FIELDS:
        it = getattr(cx, f)
        if hasattr(it, "amount_keur") and it.amount_keur:
            upd[f] = dc.replace(it, amount_keur=it.amount_keur * k)
    return dc.replace(pi, capex=dc.replace(cx, **upd))


def fin(pi, **kw):
    return dc.replace(pi, financing=dc.replace(pi.financing, **kw))


def opex(pi, k):
    return dc.replace(pi, opex=type(pi.opex)([dc.replace(i, y1_amount_keur=i.y1_amount_keur * k) for i in pi.opex]))


def info(pi, **kw):
    return dc.replace(pi, info=dc.replace(pi.info, **kw))


def S16(**kw):
    # 16 MW with CAPEX scaled to the plant size (factory amounts are 50 MW-sized)
    return scale_capex(pf.create_default_solar_project(capacity_mw=16.0, **kw), 0.26)


def S16r(**kw):
    # 16 MW with a lower CAPEX level so that high-DSCR / low-gearing variants remain feasible
    return scale_capex(pf.create_default_solar_project(capacity_mw=16.0, **kw), 0.18)


def W25r(**kw):
    # 25 MW wind with a lower CAPEX level so that high-DSCR / low-gearing variants remain feasible
    return scale_capex(pf.create_default_wind_project(capacity_mw=25.0, **kw), 0.7)


def W25(**kw):
    return pf.create_default_wind_project(capacity_mw=25.0, **kw)


def DC(**kw):
    return pf.create_default_data_center_project(**kw)


def leap(pi):
    fc = date(2028, 2, 29)
    return info(pi, financial_close=fc, cod_date=fc + relativedelta(months=pi.info.construction_months))


NO_CF = GP.GenericFinancingPolicy(apply_construction_financing=False)
NO_DSRA = GP.GenericFinancingPolicy(apply_cash_dsra=False)

CASES = {
    # --- reference projects (semiannual 6/6) ---
    "S16": (S16, "Solar", None),
    "W25": (W25, "Wind", None),
    "DC": (DC, "DataCenter", None),
    "S50": (pf.create_default_solar_project, "Solar", None),
    # --- DSCR targets ---
    "S16-dscr1.45": (lambda: fin(S16(), target_dscr=1.45), "Solar", None),
    "S16-dscr2.0": (lambda: fin(S16(), target_dscr=2.0), "Solar", None),
    "S16-dscr3.0": (lambda: fin(S16(), target_dscr=3.0), "Solar", None),
    "W25-dscr1.45": (lambda: fin(W25(), target_dscr=1.45), "Wind", None),
    "W25-dscr2.0": (lambda: fin(W25(), target_dscr=2.0), "Wind", None),
    "W25-dscr3.0": (lambda: fin(W25(), target_dscr=3.0), "Wind", None),
    "DC-dscr2.0": (lambda: fin(DC(), target_dscr=2.0), "DataCenter", None),
    # --- binding constraint ---
    "S16-gear0.50": (lambda: fin(S16(), gearing_ratio=0.50), "Solar", None),
    "W25-gear0.50": (lambda: fin(W25(), gearing_ratio=0.50), "Wind", None),
    "W25-gear0.90": (lambda: fin(W25(), gearing_ratio=0.90), "Wind", None),
    # --- DSRA months ---
    "S16-dsra0": (lambda: fin(S16(), dsra_months=0), "Solar", None),
    "S16-dsra12": (lambda: fin(S16(), dsra_months=12), "Solar", None),
    "W25-dsra12": (lambda: fin(W25(), dsra_months=12), "Wind", None),
    # --- SHL / construction financing / DSRA policy switches ---
    "S16-noCF": (S16, "Solar", NO_CF),
    "W25-noCF": (W25, "Wind", NO_CF),
    "W25-noDSRA": (W25, "Wind", NO_DSRA),
    "S16-shl-small": (lambda: fin(S16(), share_capital_keur=4000.0), "Solar", None),
    # --- tenors ---
    "S16-tenor10": (lambda: fin(S16(), senior_tenor_years=10), "Solar", None),
    "W25-tenor18": (lambda: fin(W25(), senior_tenor_years=18), "Wind", None),
    # --- zero / near-zero / infeasible financing ---
    "S16-gear0": (lambda: fin(S16(), gearing_ratio=0.0), "Solar", None),
    "S16-gear0.001": (lambda: fin(S16(), gearing_ratio=0.001), "Solar", None),
    "S16-raw-infeasible": (lambda: pf.create_default_solar_project(capacity_mw=16.0), "Solar", None),
    "S16-capex0.32-infeasible": (lambda: scale_capex(pf.create_default_solar_project(capacity_mw=16.0), 0.32), "Solar", None),
    "S16-gearbound": (lambda: scale_capex(pf.create_default_solar_project(capacity_mw=16.0), 0.24), "Solar", None),
    "W25-dscr9-infeasible": (lambda: fin(W25(), target_dscr=9.0), "Wind", None),
    # --- tax losses vs positive tax ---
    "S16-taxloss": (lambda: opex(S16(), 1.8), "Solar", None),
    "W25-taxloss": (lambda: opex(W25(), 1.8), "Wind", None),
    # --- calendar: leap-year close and COD stub ---
    "S16-leap": (lambda: leap(S16()), "Solar", None),
    "S16-codstub9": (lambda: S16(construction_months=9), "Solar", None),
    "W25-codstub15": (lambda: W25(construction_months=15), "Wind", None),
    "DC-leap": (lambda: leap(DC()), "DataCenter", None),
    # --- feasible financing variations on a lower-CAPEX 16 MW solar base ---
    "S16r": (S16r, "Solar", None),
    "S16r-dscr2.0": (lambda: fin(S16r(), target_dscr=2.0), "Solar", None),
    "S16r-dscr3.0": (lambda: fin(S16r(), target_dscr=3.0), "Solar", None),
    "S16r-gear0.50": (lambda: fin(S16r(), gearing_ratio=0.50), "Solar", None),
    "S16r-tenor10": (lambda: fin(S16r(), senior_tenor_years=10), "Solar", None),
    "S16r-tenor12": (lambda: fin(S16r(), senior_tenor_years=12), "Solar", None),
    "S16r-taxloss": (lambda: opex(S16r(), 1.8), "Solar", None),
    "S16r-dsra12": (lambda: fin(S16r(), dsra_months=12), "Solar", None),
    "S16r-gear0.001": (lambda: fin(S16r(), gearing_ratio=0.001), "Solar", None),
    # --- feasible financing variations on a lower-CAPEX 25 MW wind base ---
    "W25r-dscr2.0": (lambda: fin(W25r(), target_dscr=2.0), "Wind", None),
    "W25r-dscr3.0": (lambda: fin(W25r(), target_dscr=3.0), "Wind", None),
    "W25r-gear0.50": (lambda: fin(W25r(), gearing_ratio=0.50), "Wind", None),
    "W25r-tenor10": (lambda: fin(W25r(), senior_tenor_years=10), "Wind", None),
    "W25r-taxloss": (lambda: opex(W25r(), 1.8), "Wind", None),
}


def run(case_names, out_path):
    results = {}
    for name in case_names:
        build, ptype, policy = CASES[name]
        case = {"build": build, "ptype": ptype}
        if policy is not None:
            case["policy"] = policy
        base, tb, _ = H.run_case(case)
        db = H.outcome_digest(base)
        row = {"baseline_s": tb, "baseline_exc": "<exception>" in db,
               "baseline_summary": H.summary(base), "variants": {}}
        import os
        only = [v for v in os.environ.get("V9_VARIANTS", "").split(",") if v]
        for vname, flags in VARIANTS.items():
            if only and vname not in only:
                continue
            out, t, st = H.run_case(case, flags)
            d = H.outcome_digest(out)
            r = H.compare(db, d)
            row["variants"][vname] = {
                "s": t, "stats": st, "floats": r["float_leaves"], "identical": r["bit_identical_floats"],
                "max_abs": r["max_abs"], "max_abs_path": r["max_abs_path"],
                "max_rel": r["max_rel"], "max_rel_path": r["max_rel_path"],
                "categorical": [list(map(str, c)) for c in r["categorical"][:20]],
                "n_categorical": len(r["categorical"]), "n_structural": len(r["structural"]),
                "text_numeric": r.get("text_numeric", [])[:10],
                "structural": r["structural"][:10],
                "diag": [list(map(str, c)) for c in r["diagnostic"]][:40],
                "exc": d.get("<exception>"), "summary": H.summary(out),
            }
            print(f"{name:22s} {vname:5s} base={tb:6.2f}s cand={t:6.2f}s x{tb / max(t, 1e-9):4.2f} "
                  f"id={r['bit_identical_floats']}/{r['float_leaves']} max_abs={r['max_abs']:.2e} "
                  f"cat={len(r['categorical'])} struct={len(r['structural'])} "
                  f"{'EXC ' + d['<exception>'][:80] if '<exception>' in d else ''}", flush=True)
        results[name] = row
        with open(out_path, "w") as fh:
            json.dump(results, fh, indent=1, default=str)


if __name__ == "__main__":
    names = sys.argv[2:] or list(CASES)
    run(names, sys.argv[1])
