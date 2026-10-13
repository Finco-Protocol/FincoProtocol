"""Q3 Correction A — scenario display window and Run-History coverage (real SQLite, deterministic).

Defects pinned:
* the active scenario / Base Case could fall outside a display window that followed ``updated_at DESC``
  (first 8, and upstream ``list_scenarios`` default 25);
* a scenario whose newest committed Run is older than the newest 200 PROJECT Runs was shown as NO_RUN.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.persistence.scenario_insight_reads import (
    HISTORY_UNAVAILABLE, INSIGHT_SCENARIO_LIMIT, list_insight_scenarios, newest_committed_runs)
from app.v2.insight_scenario_projection import build_scenario_insight

OWNER, OTHER = "q3r-owner", "q3r-other"


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "q3r.db"))
    db.init_db()
    from app.services.reference_seed_service import create_reference_seeded_project
    mk = lambda user, name: create_reference_seeded_project(user_id=user, template_source="generic_solar_reference",
                                                           requested_name=name, capacity_mw=40.0)
    return SimpleNamespace(project=mk(OWNER, "P1"), project2=mk(OWNER, "P2"), foreign=mk(OTHER, "F1"))


def add_scenario(user, project, name, *, updated, base=False, archived=False):
    from app.persistence.db import get_cursor
    sid = uuid.uuid4().hex[:16]
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO scenarios (scenario_id, project_id, user_id, scenario_name, project_code, source_project_template,"
            " archived, is_base_case, snapshot_json, governance_state_json, last_run_summary_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, project.project_id, user, name, project.project_code, "generic_solar_reference",
             int(archived), int(base), "{}", "{}", "{}", updated, updated))
    return sid


def make_base(user, project, *, updated):
    """The seeded project already owns its Base Case; pin its updated_at for deterministic ordering."""
    from app.persistence.db import get_cursor
    from app.persistence.scenarios_repository import get_base_case_scenario
    rec = get_base_case_scenario(user, project.project_id)
    assert rec is not None
    with get_cursor() as cur:
        cur.execute("UPDATE scenarios SET updated_at=? WHERE scenario_id=?", (updated, rec.scenario_id))
    return rec.scenario_id


def add_run(user, project, scenario_id, ran_at, *, irr=0.1, malformed=False, history_id=None):
    from app.persistence.db import get_cursor
    hid = history_id or uuid.uuid4().hex
    summary = "{not json" if malformed else json.dumps({"project_irr": irr, "min_dscr": 1.3, "target_dscr": 1.2})
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO model_run_history (history_id, user_id, project_id, project_code, runtime_snapshot_id, ran_at,"
            " last_runtime_scenario_id, composite_hash, runtime_summary_json, financial_statements_json, debt_schedule_json,"
            " tax_schedule_json, distribution_schedule_json, sponsor_schedule_json, integrity_evidence_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (hid, user, project.project_id, project.project_code, f"snap-{hid[:8]}", ran_at, scenario_id, "ab" * 32,
             summary, "{}", "{}", "{}", "{}", "{}", "{}", ran_at))
    return hid


def ts(i):
    return f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00" if i < 3600 else f"2026-02-{1 + i // 86400:02d}T00:00:00+00:00"


# ───────────────────────────── display window ─────────────────────────────

def test_more_than_eight_scenarios_are_windowed_and_disclosed(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    for i in range(11):
        add_scenario(OWNER, p, f"S{i}", updated=ts(10 + i))
    chosen = list_insight_scenarios(OWNER, p.project_id, base)
    assert len(chosen.records) == INSIGHT_SCENARIO_LIMIT == 8 and chosen.candidates == 12 and chosen.omitted == 4
    view = build_scenario_insight(scenarios=chosen.records, latest_runs={s.scenario_id: None for s in chosen.records},
                                  active_scenario_id=base, active_run_state="NOT_RUN", last_run_snapshot_id=None,
                                  candidates=chosen.candidates)
    assert (view["shown"], view["total"], view["omitted"]) == (8, 12, 4)
    assert "Showing 8 of 12" in view["omitted_note"] and "Scenarios workspace" in view["omitted_note"]


def test_active_scenario_outside_the_first_eight_by_updated_at_is_always_included(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(500))
    ids = [add_scenario(OWNER, p, f"S{i}", updated=ts(1000 + i)) for i in range(12)]
    oldest_active = add_scenario(OWNER, p, "Old active", updated=ts(2))      # oldest updated_at of all
    chosen = list_insight_scenarios(OWNER, p.project_id, oldest_active)
    assert chosen.records[0].scenario_id == oldest_active, "active scenario is first"
    assert chosen.records[1].scenario_id == base, "Base Case is second"
    assert [r.scenario_id for r in chosen.records[2:]] == list(reversed(ids))[:6], "rest: most recently updated first"


def test_active_scenario_beyond_the_upstream_default_window_of_25_is_included(db_env):
    from app.persistence.scenarios_repository import list_scenarios
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(900))
    for i in range(30):
        add_scenario(OWNER, p, f"S{i}", updated=ts(1000 + i))
    active = add_scenario(OWNER, p, "Very old active", updated=ts(1))
    upstream = {r.scenario_id for r in list_scenarios(user_id=OWNER, project_id=p.project_id)}   # default limit 25
    assert active not in upstream and base not in upstream, "the regression the upstream list would cause"
    chosen = list_insight_scenarios(OWNER, p.project_id, active)
    assert {r.scenario_id for r in chosen.records[:2]} == {active, base}
    assert chosen.candidates == 32


def test_base_case_is_visible_when_it_is_not_active_and_ordering_is_deterministic(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    a = add_scenario(OWNER, p, "A", updated=ts(50))
    first = [r.scenario_id for r in list_insight_scenarios(OWNER, p.project_id, a).records]
    again = [r.scenario_id for r in list_insight_scenarios(OWNER, p.project_id, a).records]
    assert first == again == [a, base]
    no_active = [r.scenario_id for r in list_insight_scenarios(OWNER, p.project_id, None).records]
    assert no_active[0] == base                                   # workspace records no id for the Base Case


def test_archived_unauthorized_and_cross_project_scenarios_are_never_listed(db_env):
    p, p2, foreign = db_env.project, db_env.project2, db_env.foreign
    base = make_base(OWNER, p, updated=ts(1))
    mine = add_scenario(OWNER, p, "Mine", updated=ts(2))
    archived = add_scenario(OWNER, p, "Archived", updated=ts(3), archived=True)
    other_project = add_scenario(OWNER, p2, "Other project", updated=ts(4))
    other_owner = add_scenario(OTHER, foreign, "Other owner", updated=ts(5))
    forged = add_scenario(OTHER, p, "Other owner, same project id", updated=ts(6))     # row of another user
    ids = {r.scenario_id for r in list_insight_scenarios(OWNER, p.project_id, base).records}
    assert ids == {base, mine}
    assert not ids & {archived, other_project, other_owner, forged}
    # an unauthorised "active" id is not displayed, however it is supplied
    assert other_owner not in {r.scenario_id for r in list_insight_scenarios(OWNER, p.project_id, other_owner).records}
    # the ACTIVE scenario is shown even if archived (never silently omitted), flagged via the record
    assert archived in {r.scenario_id for r in list_insight_scenarios(OWNER, p.project_id, archived).records}


# ───────────────────────────── committed Run retrieval ─────────────────────────────

def test_run_older_than_the_newest_200_project_runs_is_still_found(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    old = add_scenario(OWNER, p, "Old runner", updated=ts(2))
    busy = add_scenario(OWNER, p, "Busy", updated=ts(3))
    old_hid = add_run(OWNER, p, old, ts(5), irr=0.05)
    for i in range(205):                                    # 205 newer project Runs (> the old scan window of 200)
        add_run(OWNER, p, busy, ts(100 + i))
    recs = list_insight_scenarios(OWNER, p.project_id, base).records
    runs = newest_committed_runs(OWNER, p.project_id, recs)
    assert runs[old].history_id == old_hid, "NO_RUN would be a false claim"
    assert runs[busy].ran_at == ts(100 + 204)
    assert runs[base] is None                               # genuinely never run


def test_newest_committed_run_wins_with_deterministic_tie_break(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    sc = add_scenario(OWNER, p, "S", updated=ts(2))
    add_run(OWNER, p, sc, ts(10), irr=0.01)
    add_run(OWNER, p, sc, ts(30), irr=0.03, history_id="a" * 32)
    add_run(OWNER, p, sc, ts(30), irr=0.04, history_id="b" * 32)          # same ran_at: higher history_id wins
    add_run(OWNER, p, sc, ts(20), irr=0.02)
    runs = newest_committed_runs(OWNER, p.project_id, list_insight_scenarios(OWNER, p.project_id, sc).records)
    assert runs[sc].history_id == "b" * 32 and runs[sc].runtime_summary["project_irr"] == 0.04


def test_pre_scenario_base_run_belongs_to_the_base_case_only(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    other = add_scenario(OWNER, p, "Other", updated=ts(2))
    hid = add_run(OWNER, p, None, ts(10))
    runs = newest_committed_runs(OWNER, p.project_id, list_insight_scenarios(OWNER, p.project_id, base).records)
    assert runs[base].history_id == hid and runs[other] is None


def test_history_of_other_projects_and_owners_never_leaks(db_env):
    p, p2, foreign = db_env.project, db_env.project2, db_env.foreign
    base = make_base(OWNER, p, updated=ts(1))
    sc = add_scenario(OWNER, p, "S", updated=ts(2))
    add_run(OWNER, p2, sc, ts(50))                      # same scenario id, other project
    add_run(OTHER, p, sc, ts(60))                       # same ids, other owner
    add_run(OTHER, foreign, sc, ts(70))
    runs = newest_committed_runs(OWNER, p.project_id, list_insight_scenarios(OWNER, p.project_id, sc).records)
    assert runs[sc] is None, "only this owner's, this project's Runs may count"


def test_malformed_newest_run_is_unavailable_never_an_older_run_and_never_no_run(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    sc = add_scenario(OWNER, p, "S", updated=ts(2))
    add_run(OWNER, p, sc, ts(10), irr=0.02)                      # older, valid
    add_run(OWNER, p, sc, ts(20), malformed=True)                # newest, malformed
    chosen = list_insight_scenarios(OWNER, p.project_id, sc)
    runs = newest_committed_runs(OWNER, p.project_id, chosen.records)
    assert runs[sc] == HISTORY_UNAVAILABLE
    view = build_scenario_insight(scenarios=chosen.records, latest_runs=runs, active_scenario_id=sc,
                                  active_run_state="CURRENT", last_run_snapshot_id=None, candidates=chosen.candidates)
    row = next(r for r in view["rows"] if r["scenario_id"] == sc)
    assert row["basis"] == "HISTORY_UNAVAILABLE" and "NOT established" in row["basis_note"] and not row["has_run"]
    assert view["comparisons"] == []


def test_incomplete_retrieval_cannot_claim_that_no_run_exists(db_env, monkeypatch):
    from app.persistence import db
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    sc = add_scenario(OWNER, p, "S", updated=ts(2))
    add_run(OWNER, p, sc, ts(10))
    chosen = list_insight_scenarios(OWNER, p.project_id, sc)

    real = db.get_cursor

    def failing(*a, **k):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(db, "get_cursor", failing)
    runs = newest_committed_runs(OWNER, p.project_id, chosen.records)
    assert set(runs.values()) == {HISTORY_UNAVAILABLE}, "a failed lookup is never NO_RUN"
    broken = list_insight_scenarios(OWNER, p.project_id, sc)
    assert broken.complete is False and broken.records == ()
    view = build_scenario_insight(scenarios=broken.records, latest_runs={}, active_scenario_id=sc, active_run_state="NOT_RUN",
                                  last_run_snapshot_id=None, scenarios_complete=False)
    assert view["available"] is False and "could not be retrieved" in view["message"]
    monkeypatch.setattr(db, "get_cursor", real)
    assert newest_committed_runs(OWNER, p.project_id, chosen.records)[sc] is not None


def test_retrieval_is_bounded_one_decode_per_displayed_scenario(db_env, monkeypatch):
    import app.persistence.run_history_repository as rh
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    scs = [add_scenario(OWNER, p, f"S{i}", updated=ts(10 + i)) for i in range(15)]
    for sid in scs:
        for k in range(20):
            add_run(OWNER, p, sid, ts(100 + k))
    calls = []
    monkeypatch.setattr(rh, "get_run_history_entry", lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr(rh, "get_run_history", lambda *a, **k: pytest.fail("unbounded history load"))
    chosen = list_insight_scenarios(OWNER, p.project_id, scs[0])
    newest_committed_runs(OWNER, p.project_id, chosen.records)
    assert len(calls) <= INSIGHT_SCENARIO_LIMIT


# ───────────────────────────── classification and comparison ─────────────────────────────

def test_classification_current_stale_historical_no_run_and_comparison_uses_committed_values(db_env):
    p = db_env.project
    base = make_base(OWNER, p, updated=ts(1))
    up = add_scenario(OWNER, p, "Up", updated=ts(2))
    never = add_scenario(OWNER, p, "Never", updated=ts(3))
    broken = add_scenario(OWNER, p, "Broken", updated=ts(4))
    add_run(OWNER, p, None, ts(10), irr=0.10, history_id="1" * 32)
    add_run(OWNER, p, up, ts(20), irr=0.14)
    add_run(OWNER, p, broken, ts(30), malformed=True)
    chosen = list_insight_scenarios(OWNER, p.project_id, base)
    runs = newest_committed_runs(OWNER, p.project_id, chosen.records)
    snap = runs[base].runtime_snapshot_id
    for state, expected in (("CURRENT", "CURRENT"), ("STALE", "STALE")):
        v = build_scenario_insight(scenarios=chosen.records, latest_runs=runs, active_scenario_id=base,
                                   active_run_state=state, last_run_snapshot_id=snap, candidates=chosen.candidates)
        basis = {r["name"]: r["basis"] for r in v["rows"]}
        assert basis == {"P1": expected, "Up": "HISTORICAL_RUN", "Never": "NO_RUN", "Broken": "HISTORY_UNAVAILABLE"}
    (cmp_,) = v["comparisons"]
    irr = next(r for r in cmp_["rows"] if r["key"] == "project_irr")
    assert (irr["active"], irr["other"], irr["delta"]) == ("10.00%", "14.00%", "+4.00 pp")
    assert v["banner"], "STALE active scenario is labelled as the PRIOR Run"
