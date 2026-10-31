"""Shared helpers: isolated engine import, deterministic fingerprints, accounting identities. Read-only against the repo."""
import hashlib, json, os, platform, subprocess, sys

def repo_setup(repo):
    sys.path.insert(0, repo)

def git(repo, *a):
    return subprocess.check_output(["git", "-C", repo, *a], text=True).strip()

def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

def environment(repo):
    return {"main_sha": git(repo, "rev-parse", "HEAD"), "tree": git(repo, "rev-parse", "HEAD^{tree}"),
            "python": platform.python_version(), "platform": platform.platform(),
            "db": "none (in-process engine call, no persistence)", "network": "none"}

def run_engine(project_type, scenario, period_view, schema_dict):
    from app.input_schema import ProjectInputsSchema
    from app.input_adapter import build_projectinputs
    from app.api.project_runner import run_project
    pi = build_projectinputs(ProjectInputsSchema(**schema_dict))
    return pi, run_project(project_type, scenario, period_view, project_inputs_override=pi)

def identities(res, tol=1e-6):
    """Independent accounting identities on one engine payload. Each returns (status, detail)."""
    out = {}
    su = res.get("sources_uses") or {}
    try:
        uses = su["total_uses_keur"]
        srcs = su["senior_debt_keur"] + su["junior_or_other_keur"] + su["share_capital_and_other_equity_keur"] + su["shareholder_loan_cash_keur"]
        out["sources_equal_uses"] = ("PASS" if abs(uses - srcs) <= 1e-3 else "FAIL", {"uses": uses, "sources": srcs, "diff": uses - srcs})
    except Exception as e:
        out["sources_equal_uses"] = ("NOT_EVALUATED", repr(e))
    per = [p for p in res["debt_schedule"]["periods"] if p.get("senior_ds_keur") is not None]
    ROUND = 0.0151  # payload tables are rounded to 2 dp; this is a rounding allowance, not a financial tolerance
    live = [p for p in per if p["senior_ds_keur"] > 1e-6]
    if per:
        ds_err = max(abs(p["senior_ds_keur"] - (p["senior_principal_keur"] + p["senior_interest_keur"])) for p in per)
        out["debt_service_eq_principal_plus_interest"] = ("PASS" if ds_err <= ROUND else "FAIL", {"max_abs_err": ds_err, "periods": len(per), "tol": ROUND})
        rf = [abs(a["senior_balance_keur"] - b["senior_principal_keur"] - b["senior_balance_keur"]) for a, b in zip(per, per[1:])]
        out["senior_roll_forward"] = ("PASS" if (not rf or max(rf) <= ROUND) else "FAIL",
            {"definition": "payload senior_balance_keur is a CLOSING balance: close_t = close_t-1 - principal_t", "max_abs_err": max(rf) if rf else None, "tol": ROUND})
        out["final_balance_zero"] = ("PASS" if abs(per[-1]["senior_balance_keur"]) <= ROUND else "FAIL", {"final": per[-1]["senior_balance_keur"]})
        d = [p for p in live if p.get("dscr") is not None]
        out["dscr_present_for_all_debt_service_periods"] = ("PASS" if len(d) == len(live) else "FAIL", {"debt_service_periods": len(live), "with_dscr": len(d)})
        mn = min(p["dscr"] for p in d) if d else None
        k = (res.get("kpis") or {}).get("min_dscr")
        out["min_dscr_profile_matches_kpi"] = ("PASS" if mn is not None and k is not None and abs(mn - k) <= ROUND else "FAIL", {"profile_min": mn, "kpi_min": k})
    else:
        out["senior_periods"] = ("NOT_EVALUATED", "no periods with senior debt service")
    return out
