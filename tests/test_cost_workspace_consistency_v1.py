"""Cost Workspace Consistency V1 — CAPEX/OPEX line lifecycle (real integration).

ACTIVE -> INACTIVE -> REACTIVATED for CAPEX and OPEX on Solar, Wind, Data Center
and EV Charging, through the real HTTP/HTMX routes, the composite-identity CAS,
the persisted rows and (for the Run steps) the real canonical model.
"""
from __future__ import annotations

import re

import pytest

TECHNOLOGIES = [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
    "generic_ev_charging_reference",
]
HX = {"HX-Request": "true"}


@pytest.fixture(scope="module", autouse=True)
def _cost_workspace_executor_cleanup():
    """Close the global ModelExecutor after this module (real canonical runs
    below) so no worker pool outlives pytest."""
    yield
    from app.runtime import model_execution as me
    me.reset_model_executor_for_tests(None)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cost-ws.db"))
    db.init_db()
    yield


def _login(user_id):
    from app.auth import COOKIE_NAME, create_session_token
    from fastapi.testclient import TestClient
    import main_web

    client = TestClient(main_web.app, raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=user_id, username="admin"))
    return client


def _project(user_id, template, name="Cost WS", capacity=40.0):
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(
        user_id=user_id, template_source=template, requested_name=name, capacity_mw=capacity)
    return _login(user_id), record


def _page(client, code):
    pg = client.get(f"/v2/workbook?project={code}").text
    h = re.search(r'name="content_hash" value="([^"]+)"', pg).group(1)
    v = re.search(r'name="workbook_version" value="([^"]+)"', pg).group(1)
    return pg, h, v


def _state(client, code):
    pg = client.get(f"/v2/workbook?project={code}").text
    return re.search(r'data-testid="toolbar-runtime-state"[^>]*>([^<]+)<', pg).group(1).strip()


def _run(client, code):
    _, h, v = _page(client, code)
    r = client.post("/v2/workbook/run", headers=HX,
                    data={"project": code, "content_hash": h, "workbook_version": v})
    assert r.status_code == 200
    return r


KINDS = {
    "capex": dict(table="capex_sub_lines", group_col="parent_category_code", prefix="/v2/capex",
                  add_group="C.01", group_field="parent_category_code"),
    "opex": dict(table="opex_sub_lines", group_col="parent_group_code", prefix="/v2/opex",
                 add_group="B.02", group_field="parent_group_code"),
}


def _row(project_id, sub_line_id, kind):
    from app.persistence.db import get_cursor

    k = KINDS[kind]
    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM {k['table']} WHERE project_id=? AND sub_line_id=?",
                    (project_id, sub_line_id))
        r = cur.fetchone()
    return dict(r) if r else None


def _seeded_line(project_id, kind):
    """First ACTIVE seeded (reference) line of the project."""
    from app.persistence.db import get_cursor

    k = KINDS[kind]
    with get_cursor() as cur:
        cur.execute(f"SELECT sub_line_id FROM {k['table']} WHERE project_id=? AND is_active=1 "
                    "ORDER BY display_order LIMIT 1", (project_id,))
        return cur.fetchone()["sub_line_id"]


def _canonical_total(user_id, record, kind):
    """Canonical economics for the kind: total CAPEX / total OPEX Y1 (kEUR)."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService

    ws = get_workspace_state(user_id, record.project_id)
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    if kind == "capex":
        from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
        return apply_user_sub_lines_replacing_base(
            pi.capex, project_id=record.project_id, scenario_overrides=None).total_capex
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    folded = apply_user_sub_lines_to_opex(pi.opex, project_id=record.project_id,
                                          scenario_overrides=None)
    return sum(float(i.y1_amount_keur) for i in folded)


def _post(client, kind, action, **fields):
    return client.post(f"{KINDS[kind]['prefix']}/line/{action}", headers=HX, data=fields)


def _line_fields(client, record, kind, sub_line_id):
    _, h, v = _page(client, record.project_code)
    row = _row(record.project_id, sub_line_id, kind)
    return dict(project=record.project_code, sub_line_id=sub_line_id,
                row_version=row["updated_at"], workbook_version=v, content_hash=h)


# ───────────────────────────── lifecycle matrix ──────────────────────────────

@pytest.mark.parametrize("kind", ["capex", "opex"])
@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_line_lifecycle_active_inactive_reactivated(seeded_db, template, kind):
    uid = f"u-cw-{kind}-{template[8:12]}"
    client, rec = _project(uid, template)
    code = rec.project_code
    k = KINDS[kind]

    _run(client, code)
    last_before = _state(client, code)
    assert last_before == "Current"
    total0 = _canonical_total(uid, rec, kind)

    # ADD a custom line (new identity)
    _, h, v = _page(client, code)
    # proportionate to the cost base (a large OPEX add can legitimately trip the
    # engine's shareholder-loan maturity check, which is not what this test is about)
    add_amount = 500.0 if kind == "capex" else 10.0
    extra = {"amount_keur": f"{add_amount:g}", "label": "Lifecycle add", "notes": "",
             "project": code, k["group_field"]: k["add_group"],
             "workbook_version": v, "content_hash": h}
    if kind == "opex":
        extra["inflation_pct"] = "0"
    assert _post(client, kind, "add", **extra).status_code == 200
    total_added = _canonical_total(uid, rec, kind)
    assert total_added == pytest.approx(total0 + add_amount)
    assert _state(client, code) == "Stale"

    # DEACTIVATE a seeded line
    sid = _seeded_line(rec.project_id, kind)
    before = _row(rec.project_id, sid, kind)
    assert _post(client, kind, "deactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    inactive = _row(rec.project_id, sid, kind)
    assert inactive["is_active"] == 0
    total_off = _canonical_total(uid, rec, kind)
    assert total_off == pytest.approx(total_added - float(before["amount_keur"]))

    # RELOAD: gone from the active list, listed as inactive with a Reactivate control
    page, _, _ = _page(client, code)
    assert f'data-testid="{kind}-reactivate-{sid}"' in page
    assert "Inactive lines" in page

    # REACTIVATE
    resp = _post(client, kind, "reactivate", **_line_fields(client, rec, kind, sid))
    assert resp.status_code == 200
    after = _row(rec.project_id, sid, kind)
    assert after["is_active"] == 1
    # identity and original data preserved exactly
    for col in ("sub_line_id", "business_code", "label", "amount_keur", "source",
                "comments", k["group_col"]):
        assert after[col] == before[col], col
    if kind == "opex":
        assert after["inflation_pct"] == before["inflation_pct"]
    assert _canonical_total(uid, rec, kind) == pytest.approx(total_added)

    # RELOAD: reactivated line is back in the active list, no longer listed inactive
    page, _, _ = _page(client, code)
    assert f'data-testid="{kind}-reactivate-{sid}"' not in page
    assert _state(client, code) == "Stale"

    # RUN: real canonical run reads the updated inputs; Current again
    _run(client, code)
    assert _state(client, code) == "Current"


# ─────────────────────── CAS / conflict / authorisation ──────────────────────

@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_reactivate_rejects_stale_hash_stale_row_version_and_active_rows(seeded_db, kind):
    uid = f"u-cw-cas-{kind}"
    client, rec = _project(uid, "generic_solar_reference")
    sid = _seeded_line(rec.project_id, kind)
    assert _post(client, kind, "deactivate", **_line_fields(client, rec, kind, sid)).status_code == 200

    # stale composite hash -> rejected, nothing changes
    bad_hash = _line_fields(client, rec, kind, sid)
    bad_hash["content_hash"] = "0" * 64
    _post(client, kind, "reactivate", **bad_hash)
    assert _row(rec.project_id, sid, kind)["is_active"] == 0

    # stale row_version -> rejected, nothing changes
    bad_ver = _line_fields(client, rec, kind, sid)
    bad_ver["row_version"] = "1999-01-01T00:00:00+00:00"
    _post(client, kind, "reactivate", **bad_ver)
    assert _row(rec.project_id, sid, kind)["is_active"] == 0

    # valid -> reactivated; a SECOND reactivate (row is now active) is rejected
    assert _post(client, kind, "reactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    assert _row(rec.project_id, sid, kind)["is_active"] == 1
    version_after = _row(rec.project_id, sid, kind)["updated_at"]
    _post(client, kind, "reactivate", **_line_fields(client, rec, kind, sid))
    assert _row(rec.project_id, sid, kind)["updated_at"] == version_after

    # unknown line id
    ghost = _line_fields(client, rec, kind, sid)
    ghost["sub_line_id"] = "does-not-exist"
    ghost["row_version"] = "x"
    r = _post(client, kind, "reactivate", **ghost)
    assert r.status_code in (200, 404, 409, 422)


@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_reactivate_is_owner_scoped_and_protected_references_are_immutable(seeded_db, kind):
    from app.persistence.projects_repository import get_reference_by_template_source

    client, rec = _project(f"u-cw-own-{kind}", "generic_solar_reference")
    sid = _seeded_line(rec.project_id, kind)
    assert _post(client, kind, "deactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    fields = _line_fields(client, rec, kind, sid)

    intruder = _login(f"u-cw-intruder-{kind}")
    r = intruder.post(f"{KINDS[kind]['prefix']}/line/reactivate", headers=HX, data=fields)
    assert r.status_code in (404, 401, 403, 302)
    assert _row(rec.project_id, sid, kind)["is_active"] == 0          # not touched

    ref = get_reference_by_template_source("generic_solar_reference")
    _, h, v = _page(client, ref.project_code)
    r = client.post(f"{KINDS[kind]['prefix']}/line/reactivate", headers=HX,
                    data=dict(project=ref.project_code, sub_line_id=sid, row_version="x",
                              workbook_version=v, content_hash=h))
    assert r.status_code in (200, 403, 404, 409, 422)
    assert _row(rec.project_id, sid, kind)["is_active"] == 0          # still untouched


# ───────────────────── Last Run / scenarios / history ────────────────────────

def test_lifecycle_never_rewrites_last_run_or_history_and_scenarios_see_it(seeded_db):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.workspace_repository import get_workspace_state

    uid = "u-cw-scen"
    client, rec = _project(uid, "generic_solar_reference")
    code = rec.project_code
    _run(client, code)
    base_run = get_workspace_state(uid, rec.project_id)
    hist = len(get_run_history(uid, rec.project_id))

    sid = _seeded_line(rec.project_id, "capex")
    assert _post(client, "capex", "deactivate", **_line_fields(client, rec, "capex", sid)).status_code == 200
    assert _state(client, code) == "Stale"               # economics changed -> Last Run STALE
    ws = get_workspace_state(uid, rec.project_id)
    assert ws.last_runtime_snapshot_id == base_run.last_runtime_snapshot_id      # immutable
    assert ws.last_runtime_composite_hash == base_run.last_runtime_composite_hash
    assert len(get_run_history(uid, rec.project_id)) == hist                      # not rewritten

    # Reactivating restores exactly the inputs the Last Run used: identity matches
    # again, so the run is truthfully CURRENT (not falsely stale), still unchanged.
    assert _post(client, "capex", "reactivate", **_line_fields(client, rec, "capex", sid)).status_code == 200
    assert _state(client, code) == "Current"
    ws = get_workspace_state(uid, rec.project_id)
    assert ws.last_runtime_snapshot_id == base_run.last_runtime_snapshot_id
    assert len(get_run_history(uid, rec.project_id)) == hist

    # leave the line deactivated and navigate scenarios
    assert _post(client, "capex", "deactivate", **_line_fields(client, rec, "capex", sid)).status_code == 200
    assert _state(client, code) == "Stale"

    # scenario navigation: cost lines are project-level, so every scenario's run reads Stale
    client.post("/v2/workbook/scenarios/create", headers=HX,
                data={"project": code, "scenario_name": "Scenario X"})
    base_id = next(s.scenario_id for s in list_scenarios(user_id=uid, project_id=rec.project_id)
                   if s.is_base_case)
    client.post("/v2/workbook/scenarios/select", headers=HX,
                data={"project": code, "scenario_id": base_id})
    assert _state(client, code) == "Stale"
    assert len(get_run_history(uid, rec.project_id)) == hist


# ───────────────────────── existing / legacy projects ────────────────────────

def test_legacy_unseeded_working_copy_is_not_reseeded_and_still_edits(seeded_db):
    """A working copy created before the seeding fix (bare snapshot copy, no line
    items) must not be silently reseeded or crash; custom lines still work."""
    from app.persistence.db import get_cursor
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service as pls

    client, seed_rec = _project("u-cw-legacy", "generic_solar_reference", name="seed")
    ref = get_reference_by_template_source("generic_solar_reference")
    legacy = pls.create_working_copy(user_id="u-cw-legacy", source_reference_id=ref.project_id)
    page, h, v = _page(client, legacy.project_code)
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM capex_sub_lines WHERE project_id=?", (legacy.project_id,))
        assert cur.fetchone()["c"] == 0                     # not silently reseeded by viewing
        cur.execute("SELECT COUNT(*) c FROM opex_sub_lines WHERE project_id=?", (legacy.project_id,))
        assert cur.fetchone()["c"] == 0
    assert "Inactive lines" not in page                      # nothing invented
    # a custom line can still be added and then deactivated / reactivated
    r = client.post("/v2/capex/line/add", headers=HX,
                    data={"project": legacy.project_code, "parent_category_code": "C.01",
                          "label": "Legacy add", "amount_keur": "100", "notes": "",
                          "workbook_version": v, "content_hash": h})
    assert r.status_code == 200
    with get_cursor() as cur:
        cur.execute("SELECT sub_line_id FROM capex_sub_lines WHERE project_id=?", (legacy.project_id,))
        sid = cur.fetchone()["sub_line_id"]
    fields = _line_fields(client, legacy, "capex", sid)
    assert _post(client, "capex", "deactivate", **fields).status_code == 200
    assert _post(client, "capex", "reactivate",
                 **_line_fields(client, legacy, "capex", sid)).status_code == 200
    assert _row(legacy.project_id, sid, "capex")["is_active"] == 1


def test_previously_deactivated_lines_become_reactivatable_without_changes(seeded_db):
    """A line deactivated before this feature existed is a plain is_active=0 row:
    it shows up under Inactive lines and reactivates with its data intact."""
    from app.persistence.db import get_cursor

    uid = "u-cw-prior"
    client, rec = _project(uid, "generic_wind_reference")
    sid = _seeded_line(rec.project_id, "opex")
    snap = _row(rec.project_id, sid, "opex")
    with get_cursor() as cur:                                # historical soft-delete
        cur.execute("UPDATE opex_sub_lines SET is_active=0 WHERE sub_line_id=?", (sid,))
    page, _, _ = _page(client, rec.project_code)
    assert f'data-testid="opex-reactivate-{sid}"' in page
    assert _post(client, "opex", "reactivate", **_line_fields(client, rec, "opex", sid)).status_code == 200
    back = _row(rec.project_id, sid, "opex")
    assert back["is_active"] == 1
    for col in ("label", "amount_keur", "inflation_pct", "business_code", "source"):
        assert back[col] == snap[col]


def test_reactivated_line_does_not_collide_with_display_order(seeded_db):
    uid = "u-cw-order"
    client, rec = _project(uid, "generic_solar_reference")
    from app.persistence.db import get_cursor

    sid = _seeded_line(rec.project_id, "capex")
    row = _row(rec.project_id, sid, "capex")
    assert _post(client, "capex", "deactivate", **_line_fields(client, rec, "capex", sid)).status_code == 200
    # another ACTIVE line in the same category takes over the freed display_order
    with get_cursor() as cur:
        cur.execute("UPDATE capex_sub_lines SET display_order=? WHERE project_id=? AND "
                    "parent_category_code=? AND is_active=1 AND sub_line_id!=? AND rowid=("
                    "SELECT MIN(rowid) FROM capex_sub_lines WHERE project_id=? AND "
                    "parent_category_code=? AND is_active=1)",
                    (row["display_order"], rec.project_id, row["parent_category_code"], sid,
                     rec.project_id, row["parent_category_code"]))
    assert _post(client, "capex", "reactivate", **_line_fields(client, rec, "capex", sid)).status_code == 200
    with get_cursor() as cur:
        cur.execute("SELECT display_order, COUNT(*) c FROM capex_sub_lines WHERE project_id=? AND "
                    "parent_category_code=? AND is_active=1 GROUP BY display_order HAVING c>1",
                    (rec.project_id, row["parent_category_code"]))
        assert cur.fetchall() == []                          # ordering stays unambiguous


# ──────────────── OPEX reaches canonical economics exactly once ──────────────

def _active_opex_sum(project_id, group=None):
    from app.persistence.db import get_cursor

    sql = "SELECT COALESCE(SUM(amount_keur),0) s FROM opex_sub_lines WHERE project_id=? AND is_active=1"
    args = [project_id]
    if group:
        sql += " AND parent_group_code=?"
        args.append(group)
    with get_cursor() as cur:
        cur.execute(sql, args)
        return float(cur.fetchone()["s"])


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_seeded_opex_lines_replace_the_aggregate_base_instead_of_adding_to_it(seeded_db, template):
    """Solar/Wind carry one aggregate Y1 OPEX item at non-reference capacity; the
    seeded lines decompose it. Canonical OPEX must equal the lines (counted once)."""
    uid = f"u-cw-once-{template[8:12]}"
    client, rec = _project(uid, template, capacity=40.0)
    assert _canonical_total(uid, rec, "opex") == pytest.approx(_active_opex_sum(rec.project_id))


@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_deactivating_every_line_of_a_category_removes_its_cost_for_good(seeded_db, template):
    """Deactivating all seeded lines of a category must lower canonical OPEX by
    exactly that category's lines (the replaced base item must not come back),
    and reactivating them restores the original total."""
    from app.persistence.db import get_cursor

    uid = f"u-cw-allgrp-{template[8:12]}"
    client, rec = _project(uid, template)
    total0 = _canonical_total(uid, rec, "opex")
    with get_cursor() as cur:
        cur.execute("SELECT sub_line_id, amount_keur FROM opex_sub_lines WHERE project_id=? AND "
                    "parent_group_code='B.01' AND is_active=1", (rec.project_id,))
        lines = [(r["sub_line_id"], float(r["amount_keur"])) for r in cur.fetchall()]
    assert lines
    for sid, _ in lines:
        assert _post(client, "opex", "deactivate", **_line_fields(client, rec, "opex", sid)).status_code == 200
    assert _canonical_total(uid, rec, "opex") == pytest.approx(total0 - sum(a for _, a in lines))
    for sid, _ in lines:
        assert _post(client, "opex", "reactivate", **_line_fields(client, rec, "opex", sid)).status_code == 200
    assert _canonical_total(uid, rec, "opex") == pytest.approx(total0)


# ─────────────── existing scenario cost overrides survive the lifecycle ───────

@pytest.mark.parametrize("kind,override_key", [("capex", "_capex_sub_line_overrides"),
                                                ("opex", "_opex_sub_line_overrides")])
def test_scenario_cost_override_survives_deactivate_and_reactivate(seeded_db, kind, override_key):
    import json

    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService

    uid = f"u-cw-ovr-{kind}"
    client, rec = _project(uid, "generic_solar_reference")
    client.post("/v2/workbook/scenarios/create", headers=HX,
                data={"project": rec.project_code, "scenario_name": "Override X"})
    sid = _seeded_line(rec.project_id, kind)
    base_amount = float(_row(rec.project_id, sid, kind)["amount_keur"])
    overrides = {override_key: {sid: base_amount + 123.0}}
    with get_cursor() as cur:
        cur.execute("UPDATE scenarios SET overrides_json=? WHERE user_id=? AND project_id=? "
                    "AND is_base_case=0", (json.dumps(overrides), uid, rec.project_id))

    def effective_total():
        ws = get_workspace_state(uid, rec.project_id)
        pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
        if kind == "capex":
            from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
            return apply_user_sub_lines_replacing_base(
                pi.capex, project_id=rec.project_id, scenario_overrides=overrides).total_capex
        from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
        return sum(float(i.y1_amount_keur) for i in apply_user_sub_lines_to_opex(
            pi.opex, project_id=rec.project_id, scenario_overrides=overrides))

    with_override = effective_total()
    assert with_override == pytest.approx(_canonical_total(uid, rec, kind) + 123.0)
    assert _post(client, kind, "deactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    assert effective_total() == pytest.approx(with_override - (base_amount + 123.0))   # override line out
    assert _post(client, kind, "reactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    assert effective_total() == pytest.approx(with_override)                          # override intact


# ───────────── no category editor that saves without reaching the model ───────

def _category_editor_ids(page, sheet):
    m = re.search(rf'id="panel-{sheet}".*?(?=<div class="v2-sheet-panel" role="tabpanel"|\Z)', page, re.S)
    return set(re.findall(r'name="field_id"\s+value="(opex\.lines\.[^"]+)"', m.group(0))) if m else set()


@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_opex_categories_with_lines_have_no_inert_category_editor(seeded_db, template):
    client, rec = _project(f"u-cw-noed-{template[8:12]}", template)
    page, h, v = _page(client, rec.project_code)
    editors = _category_editor_ids(page, "opex")
    # every seeded category (B.01 etc.) is an explained read-only total instead
    assert 'data-testid="opex-category-total-B.01"' in page
    assert "opex.lines.technical_management" not in editors
    assert "Sum of the line items below" in page


def test_capex_category_editor_remains_where_a_category_has_no_lines(seeded_db):
    """A legacy (unseeded) working copy has no line items: the CAPEX category value
    IS the input there, so its editor stays (it is only removed where the lines
    already own the total)."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service as pls

    client, _seed = _project("u-cw-legacy-ed", "generic_solar_reference", name="seed")
    ref = get_reference_by_template_source("generic_solar_reference")
    legacy = pls.create_working_copy(user_id="u-cw-legacy-ed", source_reference_id=ref.project_id)
    page, _, _ = _page(client, legacy.project_code)
    assert 'data-field-id="capex.C.production_units"' in page
    assert 'data-testid="capex-category-total-C.01"' not in page
