"""WF-09 candidate planner: catalogue, timeline, route safety and the hard 'no write / no Run' guarantee."""
from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.auth import COOKIE_NAME, create_session_token, generate_csrf_token
from app.capex_profiles.contract import ProfileShape as S, ProfileSpec
from app.capex_profiles.plan import build_plan
from app.capex_profiles.projection import KIND_SUB_LINE, build_timeline, catalogue
from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD, get_active_sub_lines_for_project, list_sub_lines_for_project
from app.persistence.db import get_cursor
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.v2 import capex_commands as commands
from app.workbook.registry import WORKBOOK
from app.workbook.service import WorkbookService
from app.workbook.workbook_identity import assemble_consistent_for_get
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401

OWNER = "decision-user"


@pytest.fixture(autouse=True)
def _routes(env):
    from app.v2.capex_router import capex_router
    if not any(getattr(r, "path", "") == "/v2/capex/spending-profiles" for r in env.client.app.routes):
        env.client.app.include_router(capex_router, prefix="/v2/capex")


def pis_of(project):
    return WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(OWNER, project.project_id))


def evidence(project):
    ws = get_workspace_state(OWNER, project.project_id)
    with get_cursor() as cur:
        rows = [(s.sub_line_id, s.amount_keur, s.is_active, s.schedule_json, s.updated_at)
                for s in list_sub_lines_for_project(cur, project.project_id, include_inactive=True)]
    return (ws.draft_snapshot, ws.saved_snapshot, ws.dirty, ws.last_runtime_snapshot_id, rows,
            assemble_consistent_for_get(OWNER, project.project_id, WORKBOOK.version).composite_hash,
            tuple(h.history_id for h in get_run_history(OWNER, project.project_id)))


def preview(env, project, rows, *, csrf=None):
    data = {"project": project.project_code, "csrf_token": csrf or generate_csrf_token()}
    for i, (key, shape, extra) in enumerate(rows):
        data[f"key_{i}"], data[f"shape_{i}"] = key, shape
        for k, v in extra.items():
            data[f"{k}_{i}"] = v
    return env.client.post("/v2/capex/spending-profiles/preview", data=data)


def hash_of(project):
    return assemble_consistent_for_get(OWNER, project.project_id, WORKBOOK.version).composite_hash


# ── catalogue / identity ─────────────────────────────────────────────────────────────────────────────────────
def test_catalogue_uses_leaf_rows_only_and_conserves_the_capex_total(env):
    project = env.create("solar")
    items, excluded = catalogue(pis_of(project), project.project_id)
    keys = [i.item_key for i in items]
    assert len(keys) == len(set(keys)) and all(re.fullmatch(r"C\.\d\d\.\d\d", k) or k.startswith("capex.") for k in keys)
    assert not any(re.fullmatch(r"C\.\d\d", k) for k in keys)                          # no parent roll-up is an item
    assert sum(i.amount_keur for i in items) == pytest.approx(8250.0)                  # == the committed hard CAPEX total
    excluded_keys = {e.item_key for e in excluded}
    assert {"capex.C.contingencies", "capex.F.idc", "capex.F.bank_fees", "capex.F.commitment_fees", "capex.F.vat_costs",
            "capex.R.reserve_accounts", "C.13.01"} <= excluded_keys                    # derived / financing / reserves
    assert all(not e.eligible for e in excluded) and not (excluded_keys & set(keys))


def test_inactive_and_added_rows_follow_the_existing_cost_commands(env):
    project = env.create("solar")
    sub = next(s for s in get_active_sub_lines_for_project(project.project_id) if s.business_code == "C.02.02")
    _, h = commands.deactivate_capex_line(project_record=project, user_id=OWNER, sub_line_id=sub.sub_line_id, row_version=sub.updated_at,
                                          workbook_version=WORKBOOK.version, expected_content_hash=hash_of(project))
    items, _ = catalogue(pis_of(project), project.project_id)
    assert "C.02.02" not in {i.item_key for i in items} and sum(i.amount_keur for i in items) == pytest.approx(8250.0 - 1500.0)
    new, _ = commands.add_capex_line(project_record=project, user_id=OWNER, label="Added row", parent_category_code="C.02", amount_keur=222.5,
                                     workbook_version=WORKBOOK.version, expected_content_hash=hash_of(project))
    items, _ = catalogue(pis_of(project), project.project_id)
    added = next(i for i in items if i.item_key == new.business_code)
    assert added.kind == KIND_SUB_LINE and added.amount_keur == 222.5 and added.category_code == "C.02"
    # user override of an amount is the amount the planner profiles
    row = next(s for s in get_active_sub_lines_for_project(project.project_id) if s.business_code == "C.02.01")
    commands.update_capex_line(project_record=project, user_id=OWNER, sub_line_id=row.sub_line_id, label=row.label, amount_keur=4000.0,
                               row_version=row.updated_at, workbook_version=WORKBOOK.version, expected_content_hash=hash_of(project))
    items, _ = catalogue(pis_of(project), project.project_id)
    assert next(i for i in items if i.item_key == "C.02.01").amount_keur == 4000.0
    # per-category effective totals equal what the existing folding would add (children are the only profile-eligible rows)
    by_cat: dict[str, float] = {}
    for i in items:
        by_cat[i.category_code] = by_cat.get(i.category_code, 0.0) + i.amount_keur
    assert by_cat["C.02"] == pytest.approx(4000.0 + 222.5)
    inactive = frozenset({"C.02.02"})
    plan = build_plan(items, [ProfileSpec("C.02.02", S.UNIFORM)], 12, build_timeline(get_workspace_state(OWNER, project.project_id).draft_snapshot, 12),
                      inactive_keys=inactive)
    assert plan.global_errors == ("CAPEX_PROFILE_ITEM_INACTIVE: C.02.02",)


def test_timeline_reuses_the_existing_period_engine_and_maps_every_month(env):
    project = env.create("solar")
    ws = get_workspace_state(OWNER, project.project_id)
    t = build_timeline(ws.draft_snapshot, 14)
    assert t.available and len(t.month_start) == 14 and len(t.month_to_period) == 14
    assert t.month_to_period == (0,) * 6 + (1,) * 6 + (2,) * 2 and len(t.period_starts) == 3
    assert list(t.month_to_period) == sorted(t.month_to_period)
    assert t.month_start[0] == t.period_starts[0] and all(a < b for a, b in zip(t.month_start, t.month_start[1:]))
    assert build_timeline({}, 12).available is False                                   # degrades, never invents dates


# ── plan view ────────────────────────────────────────────────────────────────────────────────────────────────
def test_plan_reports_per_row_errors_without_hiding_valid_rows(env):
    project = env.create("solar")
    ws = get_workspace_state(OWNER, project.project_id)
    items, excluded = catalogue(pis_of(project), project.project_id)
    t = build_timeline(ws.draft_snapshot, 14)
    specs = [ProfileSpec("C.02.01", S.UNIFORM), ProfileSpec("C.02.02", S.EXPLICIT, explicit_percent=("50", "40") + ("0",) * 12),
             ProfileSpec("C.01.01", S.MILESTONE, milestone_month=3), ProfileSpec("C.02.01", S.FRONT_LOADED),
             ProfileSpec("capex.F.idc", S.UNIFORM), ProfileSpec("C.99.01", S.UNIFORM)]
    plan = build_plan(items, specs, 14, t, excluded_keys=frozenset(e.item_key for e in excluded))
    assert set(plan.global_errors) == {"CAPEX_PROFILE_DUPLICATE_ITEM: C.02.01", "CAPEX_PROFILE_ITEM_NOT_ELIGIBLE: capex.F.idc",
                                       "CAPEX_PROFILE_UNKNOWN_ITEM: C.99.01"}
    ok = {r.item.item_key for r in plan.rows if r.result}
    bad = {r.item.item_key: r for r in plan.rows if r.error_code}
    assert ok == {"C.02.01", "C.01.01"} and bad["C.02.02"].error_code == "CAPEX_PROFILE_WEIGHT_SUM_INVALID"
    assert bad["C.02.02"].unallocated_keur == Decimal("1500") and plan.unallocated_total_keur == Decimal("1500")
    assert plan.profiled_total_keur == Decimal("3500") + Decimal("390")
    assert sum(plan.monthly_total_keur) == plan.profiled_total_keur and plan.monthly_cumulative_keur[-1] == plan.profiled_total_keur
    assert plan.monthly_remaining_keur[-1] == 0 and sum(plan.period_equivalent_total_keur) == plan.profiled_total_keur
    assert plan.canonical is False and "PREVIEW ONLY" in plan.notice


@pytest.mark.parametrize("months", [6, 12, 18, 24])
def test_plan_conserves_uses_for_each_construction_duration(env, months):
    project = env.create("solar")
    items, _ = catalogue(pis_of(project), project.project_id)
    t = build_timeline(get_workspace_state(OWNER, project.project_id).draft_snapshot, months)
    shapes = [S.UNIFORM, S.FRONT_LOADED, S.BACK_LOADED]
    specs = [ProfileSpec(i.item_key, shapes[n % 3]) for n, i in enumerate(items)]
    plan = build_plan(items, specs, months, t)
    assert plan.profiled_total_keur == plan.planned_total_keur and plan.unallocated_total_keur == 0 and not plan.global_errors
    assert sum(plan.monthly_total_keur) == plan.planned_total_keur
    for r in plan.rows:
        assert sum(m.amount_keur for m in r.result.months) == r.result.total_keur
    if t.available and len(t.month_to_period) == months:
        assert sum(plan.period_equivalent_total_keur) == plan.planned_total_keur


# ── route: read-only, authenticated, CSRF, no write, no Run ────────────────────────────────────────────────
def test_page_and_preview_work_and_change_nothing(env):
    project = env.create("solar")
    page = env.client.get("/v2/capex/spending-profiles", params={"project": project.project_code})
    assert page.status_code == 200 and 'data-testid="preview-banner"' in page.text and "no Run is started" in page.text
    before = evidence(project)
    r = preview(env, project, [("C.02.01", "UNIFORM", {}), ("C.01.01", "MILESTONE", {"milestone": "3"}),
                               ("C.02.02", "EXPLICIT", {"explicit": ",".join(["50", "50"] + ["0"] * 12)})])
    assert r.status_code == 200 and 'data-canonical="false"' in r.text and "PREVIEW ONLY" in r.text
    assert 'data-testid="profiled-total"' in r.text and "5390" in r.text.replace(" ", "")      # 3500+390+1500
    assert evidence(project) == before                                              # no write, no Run, no CAS movement
    assert not get_run_history(OWNER, project.project_id)


def test_invalid_rows_are_rejected_in_the_view_and_still_change_nothing(env):
    project = env.create("solar")
    before = evidence(project)
    r = preview(env, project, [("C.02.01", "EXPLICIT", {"explicit": "50,40,0,0,0,0,0,0,0,0,0,0,0,0"}),
                               ("C.02.02", "EXPLICIT", {"explicit": "nan," + ",".join(["0"] * 12) + ",100"}),
                               ("C.01.01", "EXPLICIT", {"explicit": "-5,105," + ",".join(["0"] * 12)}),
                               ("C.01.02", "MILESTONE", {"milestone": "99"}),
                               ("C.01.03", "UNIFORM", {})])
    assert r.status_code == 200
    codes = re.findall(r'data-testid="row-error">([A-Z_]+)<', r.text)
    assert codes == ["CAPEX_PROFILE_WEIGHT_SUM_INVALID", "CAPEX_PROFILE_WEIGHT_NON_FINITE", "CAPEX_PROFILE_WEIGHT_NEGATIVE",
                     "CAPEX_PROFILE_MILESTONE_MONTH_INVALID"]
    assert evidence(project) == before
    dup = env.client.post("/v2/capex/spending-profiles/preview", data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "key_0": "C.02.01", "shape_0": "UNIFORM",
        "key_1": "C.02.01", "shape_1": "BACK_LOADED"})
    assert dup.status_code == 200 and "CAPEX_PROFILE_DUPLICATE_ITEM" in dup.text and evidence(project) == before
    bad_shape = preview(env, project, [("C.02.01", "GAUSSIAN", {})])
    assert bad_shape.status_code == 422 and "CAPEX_PROFILE_SHAPE_INVALID" in bad_shape.text


def test_csrf_authentication_and_ownership_are_enforced(env):
    project = env.create("solar")
    other = env.create("wind")
    before = evidence(project)
    assert preview(env, project, [("C.02.01", "UNIFORM", {})], csrf="forged").status_code == 403
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="capex-intruder", username="admin"))
    foreign = env.client.get("/v2/capex/spending-profiles", params={"project": project.project_code}, follow_redirects=False)
    assert foreign.status_code in (302, 303, 307) and "spending-profiles" not in foreign.headers.get("location", "")
    foreign_post = env.client.post("/v2/capex/spending-profiles/preview", follow_redirects=False, data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "key_0": "C.02.01", "shape_0": "UNIFORM"})
    assert foreign_post.status_code in (302, 303, 307)
    env.client.cookies.clear()
    anon = env.client.get("/v2/capex/spending-profiles", params={"project": project.project_code}, follow_redirects=False)
    assert anon.status_code in (302, 303, 307) and "/login" in anon.headers["location"]
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
    assert evidence(project) == before and other is not None


def test_there_is_no_canonical_save_route_for_profiles(env):
    project = env.create("solar")
    before = evidence(project)
    for path in ("save", "apply", "commit", "run"):
        r = env.client.post(f"/v2/capex/spending-profiles/{path}", data={"project": project.project_code, "csrf_token": generate_csrf_token()})
        assert r.status_code in (404, 405), path
    assert evidence(project) == before
    from pathlib import Path
    for f in ("app/v2/capex_profile_router.py", "app/capex_profiles/plan.py", "app/capex_profiles/projection.py", "app/capex_profiles/contract.py"):
        src = Path(f).read_text()
        for needle in (".execute(", "INSERT", "UPDATE ", "DELETE ", "apply_batch_draft_update", "run_project", "create_sub_line(", "update_sub_line(",
                       "schedule_json ="):
            assert needle not in src, (f, needle)


def test_preview_leaves_committed_runs_and_history_immutable(env):
    project = env.create("solar")
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    assert env.client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                           data={"project": project.project_code, **tokens(page.text)}).status_code == 200
    history = [h.to_dict() for h in get_run_history(OWNER, project.project_id)]
    before = evidence(project)
    for shape in ("UNIFORM", "FRONT_LOADED", "BACK_LOADED"):
        assert preview(env, project, [("C.02.01", shape, {}), ("C.02.02", shape, {})]).status_code == 200
    assert [h.to_dict() for h in get_run_history(OWNER, project.project_id)] == history and evidence(project) == before
    ws = get_workspace_state(OWNER, project.project_id)
    assert not ws.dirty                                                             # still CURRENT: a preview never makes the Run stale


def test_capex_sheet_links_to_the_planner_without_other_change(env):
    project = env.create("solar")
    html = env.client.get("/v2/workbook", params={"project": project.project_code}).text
    assert 'data-testid="capex-profile-link"' in html and "preview only" in html


def test_csrf_token_is_required_and_a_forged_or_missing_token_changes_nothing(env):
    """The CSRF successor admits the preview POST only because the token is mandatory and checked before any work."""
    project = env.create("solar")
    before = evidence(project)
    row = {"project": project.project_code, "key_0": "C.02.01", "shape_0": "UNIFORM"}
    missing = env.client.post("/v2/capex/spending-profiles/preview", data=row)
    assert missing.status_code == 422 and "plan-result" not in missing.text
    forged = env.client.post("/v2/capex/spending-profiles/preview", data={**row, "csrf_token": "forged"})
    assert forged.status_code == 403 and "CAPEX_PROFILE_CSRF_INVALID" in forged.text and "plan-result" not in forged.text
    empty = env.client.post("/v2/capex/spending-profiles/preview", data={**row, "csrf_token": ""})
    assert empty.status_code in (403, 422) and "plan-result" not in empty.text
    ok = env.client.post("/v2/capex/spending-profiles/preview", data={**row, "csrf_token": generate_csrf_token()})
    assert ok.status_code == 200 and "plan-result" in ok.text
    assert evidence(project) == before
