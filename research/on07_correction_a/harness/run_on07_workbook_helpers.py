"""Shared effective-input read-back + comparison helpers (copied verbatim from the verified ON-07 workbook runner)."""
import json
SKIP = {"project_type","currency","financial_close","scenario","project_name","country_market","period_frequency"}
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

