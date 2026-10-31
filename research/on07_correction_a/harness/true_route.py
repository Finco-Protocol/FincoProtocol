#!/usr/bin/env python3
"""ON-07 Correction A: USER_CREATED_CORE_RUN true-route materialisation (disposable SQLite DB per process).
Real app operations used: create_reference_seeded_project, app.v2.save_all_commands.save_all (guarded atomic Save All: scalar cells and cost
lines, composite-identity CAS, row-version checks, idempotency receipt), WorkbookService input-set build, Run-route steps 7-11
(to_projectinputs, CAPEX/OPEX sub-line folds, apply_state, run_project). NOT exercised: HTTP, auth, CSRF, run intent, process executor,
v2_atomic_run_commit, run history -> this is NOT a COMMITTED_RUN and NOT LIVE_UI_PARITY.
python -I true_route.py --repo R --fixtures CSV --out DIR [--fixture ID ...] [--override fixture_key=value ...] [--tag NAME]"""
import argparse, copy, csv, json, os, sys, tempfile, uuid
from decimal import Decimal, ROUND_HALF_EVEN
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C

TS = {"solar_pv": ("generic_solar_reference", "Solar"), "wind_onshore": ("generic_wind_reference", "Wind")}
SKIP_CELLS = {"project_type", "project_name", "country_market", "currency", "financial_close", "scenario", "period_frequency", "capacity_mw",
              "total_capex_keur", "opex_y1_keur", "operating_hours_p90_10y"}

def load(path):
    fx = {}
    for r in csv.DictReader(open(path, newline="")): fx.setdefault(r["fixture_id"], []).append(r)
    return fx

def coerce(v):
    v = v.strip()
    if v in ("(empty)", "*(empty)*", ""): return ""
    return v

def allocate(lines, target):
    """Deterministic PROPORTIONAL_RESCALE_OF_SEEDED_LINES: amount_j = seed_j * target / sum(seed); zero lines stay zero; 6-dp
    half-even rounding; the residual is added to the largest line so that the sum equals target exactly in Decimal."""
    seed = [Decimal(str(l["amount_keur"])) for l in lines]; tot = sum(seed)
    new = [(s * Decimal(str(target)) / tot).quantize(Decimal("0.000001"), ROUND_HALF_EVEN) for s in seed]
    resid = Decimal(str(target)) - sum(new)
    i = max(range(len(new)), key=lambda k: new[k]); new[i] += resid
    return [float(x) for x in new], float(resid)

def eff_inputs(pi):
    from run_helpers import effective
    return effective(pi)

def run_fixture(fid, rows, a, overrides=None):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.db import get_cursor
    from app.persistence.capex_sub_lines import list_sub_lines_for_project as lc
    from app.persistence.opex_sub_lines import list_sub_lines_for_project as lo
    from app.workbook.registry import WORKBOOK
    from app.workbook.service import WorkbookService
    from app.workbook.update_service import WorkbookUpdateService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.v2.save_all_commands import save_all, SaveAllInput
    from app.v2.cost_batch_commands import CostLineEdit
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.api.project_runner import run_project
    from dataclasses import replace
    ex = {r["fixture_key"]: dict(r) for r in rows if r["source_class"] == "EXPLICIT"}
    for k, v in (overrides or {}).items(): ex[k]["intended_value"] = v
    uid = "on07-local"; tsrc, key = TS[ex["project_type"]["intended_value"]]
    rec = create_reference_seeded_project(user_id=uid, template_source=tsrc, requested_name=ex["project_name"]["intended_value"],
                                          capacity_mw=float(ex["capacity_mw"]["intended_value"]), country_market=ex["country_market"]["intended_value"])
    pr, owner = resolve_accessible_project(uid, rec.project_code)
    wv = WORKBOOK.version
    def hash_now(): return assemble_consistent_for_get(uid, rec.project_id, wv).composite_hash
    def snap(): return dict(get_workspace_state(uid, rec.project_id).draft_snapshot)
    with get_cursor() as cur:
        capex0 = [dict(sub_line_id=r.sub_line_id, code=r.business_code, label=r.label, amount_keur=r.amount_keur, source=r.source, row_version=r.updated_at) for r in lc(cur, rec.project_id)]
        opex0 = [dict(sub_line_id=r.sub_line_id, code=r.business_code, label=r.label, amount_keur=r.amount_keur, inflation_pct=r.inflation_pct, source=r.source, row_version=r.updated_at) for r in lo(cur, rec.project_id)]
    cap = {"fixture": fid, "route": "USER_CREATED_CORE_RUN", "tag": a.tag, "project_code": rec.project_code, "status": "UNSET", "overrides": overrides or {},
           "before_run": {"seed_snapshot": {k: v for k, v in snap().items() if not k.startswith("_")}, "capex_lines": capex0, "opex_lines": opex0,
                          "seed_capex_total": sum(l["amount_keur"] for l in capex0), "seed_opex_y1_total": sum(l["amount_keur"] for l in opex0)}}
    # --- scalar cells: one real Save All per cell so each acceptance/refusal is attributable ---
    cells = {}
    for k, r in ex.items():
        if k in SKIP_CELLS: continue
        try: spec = WORKBOOK.field(r["finco_field_id"])
        except Exception: spec = None
        cells[k] = {"intended": r["intended_value"], "field_id": r["finco_field_id"], "registry": bool(spec), "editable": bool(spec and spec.editable)}
        if not spec: cells[k].update(outcome="NO_REGISTRY_FIELD"); continue
        if not spec.editable: cells[k].update(outcome="REGISTRY_NOT_EDITABLE"); continue
        val = coerce(r["intended_value"])
        v = WorkbookUpdateService.validate_field_update(spec.field_id, val)
        if not v.is_valid: cells[k].update(outcome="VALIDATION_REFUSED", detail=str(getattr(v, "error", None) or getattr(v, "message", None))[:160]); continue
        try:
            res = save_all(project_record=pr, user_id=uid, data=SaveAllInput(request_id="c-" + uuid.uuid4().hex[:12], workbook_version=wv,
                           content_hash=hash_now(), scenario_id=None, cells=((spec.field_id, val),)))
            cells[k].update(outcome="SAVED_VIA_SAVE_ALL", replayed=res.replayed)
        except Exception as e:
            cells[k].update(outcome="SAVE_ALL_REFUSED", detail=f"{type(e).__name__}: {str(e)[:160]}")
    cap["scalar_cells"] = cells
    # --- cost lines: one real Save All with the deterministic allocation ---
    plan = {}
    edits = []
    for kind, lines, tkey in (("capex", capex0, "total_capex_keur"), ("opex", opex0, "opex_y1_keur")):
        target = float(ex[tkey]["intended_value"]); new, resid = allocate(lines, target)
        plan[kind] = {"target": target, "seed_total": sum(l["amount_keur"] for l in lines), "rounding_residual_on_largest": resid, "rule": "PROPORTIONAL_RESCALE_OF_SEEDED_LINES"}
        for l, n in zip(lines, new):
            plan[kind].setdefault("lines", []).append({"code": l["code"], "label": l["label"], "seed": l["amount_keur"], "allocated": n})
            if n != l["amount_keur"]:
                edits.append(CostLineEdit(kind=kind, sub_line_id=l["sub_line_id"], label=l["label"], amount_keur=n, row_version=l["row_version"]))
    cap["cost_line_plan"] = plan; cap["cost_line_edits_count"] = len(edits)
    try:
        res = save_all(project_record=pr, user_id=uid, data=SaveAllInput(request_id="l-" + uuid.uuid4().hex[:12], workbook_version=wv,
                       content_hash=hash_now(), scenario_id=None, cost_lines=tuple(edits)))
        cap["cost_lines_outcome"] = "SAVED_VIA_SAVE_ALL"; cap["cost_lines_saved"] = res.counts
    except Exception as e:
        cap["cost_lines_outcome"] = f"SAVE_ALL_REFUSED {type(e).__name__}: {str(e)[:200]}"
    # --- materialise exactly as POST /v2/workbook/run steps 7-10 ---
    ws = get_workspace_state(uid, rec.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    cap["after_save"] = {"draft_snapshot": {k: v for k, v in dict(ws.draft_snapshot).items() if not k.startswith("_")}, "dirty": ws.dirty,
                         "unknown_keys": list(pis.unknown_keys), "coercion_errors": list(pis.coercion_errors)}
    try:
        override = WorkbookService.to_projectinputs(pis)
        eff0 = C_eff(override)
        override = replace(override, capex=apply_user_sub_lines_replacing_base(override.capex, project_id=rec.project_id, scenario_overrides=None))
        override = replace(override, opex=apply_user_sub_lines_to_opex(override.opex, project_id=rec.project_id, scenario_overrides=None))
        from app.workbook.bankability_config import SNAPSHOT_KEY as BK, assert_materialized_fee_authority
        from app.workbook.multisenior_config import SNAPSHOT_KEY as F3, apply_state
        assert_materialized_fee_authority(override, pis.snapshot_origin.get(BK))
        override = apply_state(override, pis.snapshot_origin.get(F3), "base", bankability_raw=pis.snapshot_origin.get(BK))
        eff = C_eff(override)
        cap["effective_before_folds"] = eff0; cap["effective_inputs"] = eff
        cap["capex_items_after_fold"] = [(i.name if hasattr(i, "name") else str(i)) for i in override.capex.items][:60] if hasattr(override.capex, "items") else None
        cap["opex_items_after_fold"] = [dict(name=i.name, y1=i.y1_amount_keur, infl=i.annual_inflation, pct=getattr(i, "percentage_of_opex", None)) for i in override.opex]
        cap["model_input_digest"] = C.sha(repr(override)); cap["input_fingerprint"] = cap["model_input_digest"]
        cap["intended_vs_effective"] = intended_vs_effective(ex, eff)
        res = run_project(key, "Base", "Semiannual", project_inputs_override=override)
        if res.get("kpis") is None or res.get("integration_status") != "full":
            cap.update(status="REFUSED", integration_status=res.get("integration_status"), messages=res.get("messages"))
        else:
            cap.update(status="RUN_OK", kpis=res["kpis"], sources_uses=res.get("sources_uses"), debt_schedule=res["debt_schedule"], tax_schedule=res.get("tax_schedule"),
                       distribution_schedule=res.get("distribution_schedule"), sponsor_schedule=res.get("sponsor_schedule"), tables=res.get("tables"),
                       financial_statements=res.get("financial_statements"), derivation_evidence=res.get("derivation_evidence"), integrity_evidence=res.get("integrity_evidence"),
                       financing_evidence=res.get("financing_evidence"), runtime_authority=res.get("runtime_authority"), messages=res.get("messages"))
            cap["evidence_digest"] = C.sha({k: cap[k] for k in ("kpis", "sources_uses", "debt_schedule", "model_input_digest")})
    except Exception as e:
        cap.update(status="REFUSED_OR_ERROR", error_type=type(e).__name__, error=str(e)[:700])
    cap["environment"] = C.environment(a.repo)
    return cap

def C_eff(pi):
    import run_on07_workbook_helpers as H
    return H.effective(pi)

def intended_vs_effective(ex, eff):
    import run_on07_workbook_helpers as H
    out = {}
    for k, r in ex.items():
        if k in H.SKIP or k == "rev_merchant_price_curve_json":
            continue
        v, d = H.compare(k, H.coerce(r["intended_value"]), eff)
        out[k] = {"verdict": v, "detail": d, "intended": r["intended_value"]}
    r = ex.get("rev_merchant_price_curve_json")
    if r is not None:
        want = [round(float(x["price_eur_mwh"]), 6) for x in json.loads(r["intended_value"])] if H.coerce(r["intended_value"]) else None
        got = [round(float(x), 6) for x in (eff.get("rev_merchant_curve") or [])]
        out["rev_merchant_price_curve_json"] = {"verdict": "MATCH" if (want is None or got[:len(want)] == want) else "MISMATCH", "intended": f"{len(want or [])} pts", "detail": f"effective pts={len(got)}"}
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--fixtures", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--fixture", action="append"); ap.add_argument("--override", action="append", default=[]); ap.add_argument("--tag", default="TRUE_ROUTE")
    a = ap.parse_args()
    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07ca_"), "disposable.db")
    C.repo_setup(a.repo); os.makedirs(a.out, exist_ok=True); fx = load(a.fixtures); summary = {}
    ov = dict(x.split("=", 1) for x in a.override)
    for fid in (a.fixture or ["SOL-01", "SOL-02", "WND-01", "WND-02"]):
        cap = run_fixture(fid, fx[fid], a, ov)
        json.dump(cap, open(os.path.join(a.out, f"{fid}.json"), "w"), indent=1, default=str)
        mm = [k for k, v in (cap.get("intended_vs_effective") or {}).items() if v["verdict"] != "MATCH"]
        summary[fid] = {"status": cap["status"], "mismatches": mm, "error": cap.get("error")}; print(fid, summary[fid])
    json.dump(summary, open(os.path.join(a.out, "RUN_SUMMARY.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
