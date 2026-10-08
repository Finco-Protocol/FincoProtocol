"""FINCO Decision Support V1 — expanded run compare + cross-project compare.

READ-ONLY analytical layer over persisted canonical successful Run data.
No engine execution anywhere on these surfaces (monkeypatch-proven), no
mutation of runs / Last Run / Working Copy, no persistence writes.

Same-project (§18):
  DS_A  current vs historical          DS_B  historical vs historical
  DS_C  failed run never a source      DS_D  malformed payload fails closed
  DS_E  CURRENT/STALE/HISTORICAL kept  DS_F  zero-denominator % safe
  DS_G  IRR variance in pp             DS_H  changed-assumptions only
  DS_I  no engine invocation

Cross-project (§19):
  X_A 2-5 projects         X_B latest successful run only
  X_C no-run project explicit  X_D mixed technologies
  X_E mixed countries         X_F deterministic sorting
  X_G persisted values unchanged
  X_H no Working Copy leak into canonical comparison
  X_I no engine invocation    X_J no cross-project mutation
"""
from __future__ import annotations

import re
from unittest import mock

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ds-v1.db"))
    db.init_db()
    yield


def _client_for(user_id: str, template: str = "generic_solar_reference",
                capacity: float = 64.0, name: str = "DS Project"):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    record = create_reference_seeded_project(
        user_id=user_id, template_source=template,
        requested_name=name, capacity_mw=capacity)
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id,
                                                 username="admin")}
    client = TestClient(main_web.app, raise_server_exceptions=True)
    return client, cookies, record


def _run_once(client, cookies, code):
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies)
    h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
    v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
    return client.post("/v2/workbook/run",
                       data={"project": code, "content_hash": h,
                             "workbook_version": v},
                       cookies=cookies, headers={"HX-Request": "true"})


def _edit_p50(client, cookies, code, value):
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies)
    h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
    v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
    resp = client.post("/v2/workbook/inputs-slice1/update",
                       data={"field_id": "project_setup.technical.p50_hours",
                             "value": str(value), "project": code,
                             "workbook_version": v, "content_hash": h},
                       cookies=cookies, headers={"HX-Request": "true"})
    assert resp.status_code == 200


def _history_ids(client, cookies, code):
    html = client.get(f"/v2/workbook/run-history?project={code}",
                      cookies=cookies).text
    return re.findall(r'data-history-id="([^"]+)"', html)


# ---------------------------------------------------------------------------
# Unit: variance arithmetic
# ---------------------------------------------------------------------------

class TestVarianceArithmetic:
    def test_irr_variance_in_percentage_points_not_growth(self):
        """DS_G: rate variance is percentage points, never % growth."""
        from app.v2.decision_support_projection import build_run_variance
        sections = build_run_variance({"project_irr": 0.082},
                                      {"project_irr": 0.0855})
        row = next(r for sec in sections for r in sec.rows
                   if r.label == "Project IRR")
        assert row.value_a == "8.20%" and row.value_b == "8.55%"
        assert row.pp_delta == "+0.35 pp"
        assert row.pct_delta == "—"       # never +4.27%

    def test_zero_denominator_percentage_safe(self):
        """DS_F: % variance must fail safe when base is zero or None."""
        from app.v2.decision_support_projection import build_run_variance
        sections = build_run_variance(
            {"total_capex_keur": 0.0, "min_dscr": None},
            {"total_capex_keur": 5000.0, "min_dscr": 1.3})
        econ = {r.label: r for r in sections[1].rows}
        assert econ["Total CAPEX"].pct_delta == "—"   # zero base → no %
        assert econ["Total CAPEX"].abs_delta != "—"
        debt = {r.label: r for r in sections[2].rows}
        assert debt["Minimum DSCR"].value_a == "—"    # missing ≠ 0

    def test_legitimate_zero_stays_zero(self):
        from app.v2.decision_support_projection import build_run_variance
        sections = build_run_variance({"min_dscr": 0.0}, {"min_dscr": 1.3})
        row = next(r for sec in sections for r in sec.rows
                   if r.label == "Minimum DSCR")
        assert row.value_a == "0.00x"                 # real zero, not NA

    def test_direction_encoded_without_judgment(self):
        from app.v2.decision_support_projection import build_run_variance
        sections = build_run_variance({"total_capex_keur": 100.0,
                                       "min_dscr": 1.0},
                                      {"total_capex_keur": 120.0,
                                       "min_dscr": 1.2})
        econ = {r.label: r for sec in sections for r in sec.rows}
        debt = econ
        assert econ["Total CAPEX"].direction == "up"    # higher debt ≠ "good"
        assert debt["Minimum DSCR"].direction == "up"   # direction, not score

    def test_assumption_diff_changed_only(self):
        """DS_H: only genuine changes appear; identical rows are omitted."""
        from app.v2.decision_support_projection import build_assumption_diff
        a = {"capex_rows": [{"sub_line_id": "c1", "name": "EPC",
                             "amount_keur": 100.0},
                            {"sub_line_id": "c2", "name": "Grid",
                             "amount_keur": 50.0}],
             "opex_rows": [{"sub_line_id": "o1", "name": "O&M",
                            "amount_keur": 10.0}],
             "scenario_overrides": {"revenue.ppa.base_tariff": "55"}}
        b = {"capex_rows": [{"sub_line_id": "c1", "name": "EPC",
                             "amount_keur": 120.0},
                            {"sub_line_id": "c2", "name": "Grid",
                             "amount_keur": 50.0}],
             "opex_rows": [{"sub_line_id": "o1", "name": "O&M",
                            "amount_keur": 10.0}],
             "scenario_overrides": {"revenue.ppa.base_tariff": "60"}}
        rows = build_assumption_diff(a, b)
        names = [(r.category, r.name) for r in rows]
        assert ("capex", "EPC") in names
        assert ("scenario", "revenue.ppa.base_tariff") in names
        assert ("capex", "Grid") not in names      # unchanged → omitted
        assert ("opex", "O&M") not in names        # unchanged → omitted

    def test_drivers_of_change_is_factual(self):
        """§7: deterministic changed-assumptions + moved-outputs summary —
        no causal attribution text, no AI-generated explanations."""
        from app.v2.decision_support_projection import (
            build_drivers_of_change, build_run_variance,
            build_assumption_diff)
        assumptions = build_assumption_diff(
            {"capex_rows": [{"sub_line_id": "c1", "name": "EPC",
                             "amount_keur": 100.0}]},
            {"capex_rows": [{"sub_line_id": "c1", "name": "EPC",
                             "amount_keur": 120.0}]})
        sections = build_run_variance({"project_irr": 0.082},
                                      {"project_irr": 0.0855})
        drivers = build_drivers_of_change(assumptions, sections)
        assert drivers["changed_assumptions"] == ["EPC"]
        assert drivers["moved_outputs"][0][0] == "Project IRR"
        assert drivers["moved_outputs"][0][1] == "+0.35 pp"


# ---------------------------------------------------------------------------
# Correction — zero / missing numeric semantics (explicit None checks)
# ---------------------------------------------------------------------------

class TestZeroMissingSemantics:
    def _rows(self, capex, ebitda, revenue, capacity_mw=10.0):
        from app.v2.decision_support_projection import build_cross_project_rows
        return build_cross_project_rows([{
            "project_code": "z", "project_name": "Z", "technology": "solar",
            "country": "DE", "capacity_display": "10.0 MW",
            "capacity_mw": capacity_mw, "runnable": True,
            "ran_at_display": "2026-10-08 10:00",
            "runtime_summary": {
                "total_capex_keur": capex, "total_ebitda_keur": ebitda,
                "total_revenue_keur": revenue,
            },
            "sponsor_summary": {}, "debt_summary": {},
        }])

    def test_zero_ebitda_positive_revenue_renders_zero_margin(self):
        row = self._rows(1000.0, 0.0, 20000.0)[0]
        assert row.ebitda_margin == "0.0%"

    def test_negative_ebitda_renders_negative_margin(self):
        row = self._rows(1000.0, -500.0, 20000.0)[0]
        assert row.ebitda_margin == "-2.5%"

    def test_zero_revenue_margin_unavailable(self):
        row = self._rows(1000.0, 500.0, 0.0)[0]
        assert row.ebitda_margin == "—"

    def test_missing_ebitda_margin_unavailable(self):
        row = self._rows(1000.0, None, 20000.0)[0]
        assert row.ebitda_margin == "—"

    def test_zero_capex_valid_capacity_renders_zero(self):
        row = self._rows(0.0, 500.0, 20000.0)[0]
        assert row.metrics.get("capex_per_mw") == "0"

    def test_missing_capex_margin_unavailable(self):
        row = self._rows(None, 500.0, 20000.0)[0]
        assert row.metrics.get("capex_per_mw") is None


# ---------------------------------------------------------------------------
# Same-project expanded compare (integration, real persisted runs)
# ---------------------------------------------------------------------------

@pytest.fixture
def two_runs(seeded_db):
    client, cookies, record = _client_for("ds-user")
    assert _run_once(client, cookies, record.project_code).status_code == 200
    _edit_p50(client, cookies, record.project_code, 2100)
    assert _run_once(client, cookies, record.project_code).status_code == 200
    ids = _history_ids(client, cookies, record.project_code)
    return client, cookies, record, ids   # newest first


class TestExpandedRunCompare:
    def test_current_vs_historical(self, two_runs):
        client, cookies, record, ids = two_runs
        resp = client.get(
            f"/v2/workbook/run-compare?project={record.project_code}"
            f"&run_a=last&run_b={ids[-1]}", cookies=cookies)
        assert resp.status_code == 200, resp.text[:300]
        assert 'data-testid="run-compare-expanded"' in resp.text
        assert "Last Run" in resp.text
        assert "HISTORICAL" in resp.text
        assert 'data-testid="ds-section-returns"' in resp.text
        assert "Project IRR" in resp.text

    def test_historical_vs_historical(self, two_runs):
        client, cookies, record, ids = two_runs
        resp = client.get(
            f"/v2/workbook/run-compare?project={record.project_code}"
            f"&run_a={ids[-1]}&run_b={ids[-1] if len(ids) < 2 else ids[0]}",
            cookies=cookies)
        assert resp.status_code == 200
        assert "HISTORICAL" in resp.text
        assert "Last Run" not in resp.text      # both sides historical

    def test_stale_label_after_working_copy_edit(self, two_runs):
        client, cookies, record, ids = two_runs
        _edit_p50(client, cookies, record.project_code, 2300)  # edit AFTER runs
        resp = client.get(
            f"/v2/workbook/run-compare?project={record.project_code}"
            f"&run_a=last&run_b={ids[-1]}", cookies=cookies)
        assert 'data-testid="ds-side-a-state"' in resp.text
        assert "STALE" in resp.text

    def test_changed_assumptions_section_present(self, two_runs):
        client, cookies, record, ids = two_runs
        resp = client.get(
            f"/v2/workbook/run-compare?project={record.project_code}"
            f"&run_a=last&run_b={ids[-1]}", cookies=cookies)
        assert 'data-testid="ds-assumptions"' in resp.text
        assert 'data-testid="ds-drivers"' in resp.text

    def test_malformed_history_payload_fails_closed(self, two_runs):
        import sqlite3
        from app.persistence import db as _db
        client, cookies, record, ids = two_runs
        con = sqlite3.connect(_db.DB_PATH)
        try:
            con.execute("UPDATE model_run_history SET runtime_summary_json='{bad'")
            con.commit()
        finally:
            con.close()
        resp = client.get(
            f"/v2/workbook/run-compare?project={record.project_code}"
            f"&run_a=last&run_b={ids[-1]}", cookies=cookies)
        assert resp.status_code == 422
        assert "RUN_HISTORY_PAYLOAD_MALFORMED" in resp.text

    def test_no_engine_invocation_on_compare_render(self, two_runs):
        client, cookies, record, ids = two_runs
        with mock.patch("app.api.project_runner.run_project",
                        side_effect=AssertionError("engine ran")), \
             mock.patch("app.services.production_financial_authority.run_clean_production",
                        side_effect=AssertionError("clean engine ran")):
            resp = client.get(
                f"/v2/workbook/run-compare?project={record.project_code}"
                f"&run_a=last&run_b={ids[-1]}", cookies=cookies)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cross-project compare
# ---------------------------------------------------------------------------

class TestCrossProject:
    def _multi(self, seeded_db):
        clients = []
        projects = []
        for i, (tpl, cap) in enumerate(
                [("generic_solar_reference", 64.0),
                 ("generic_wind_reference", 48.0),
                 ("generic_data_center_reference", 20.0)]):
            client, cookies, record = _client_for(
                f"ds-x-user-{i}", tpl, cap, f"X Project {i}")
            assert _run_once(client, cookies, record.project_code).status_code == 200
            clients.append((client, cookies))
            projects.append(record)
        return clients, projects

    def _run_all(self, seeded_db):
        made = []
        client = cookies = None
        for i, (tpl, cap) in enumerate(
                [("generic_solar_reference", 64.0),
                 ("generic_wind_reference", 48.0)]):
            client, cookies, record = _client_for(
                "ds-x-shared", tpl, cap, f"X Project {i}")
            assert _run_once(client, cookies, record.project_code).status_code == 200
            made.append((client, cookies, record))
        return made

    def test_two_project_comparison_works(self, seeded_db):
        made = self._run_all(seeded_db)
        client, cookies, _ = made[0]
        codes = ",".join(m[2].project_code for m in made)
        resp = client.get(f"/v2/compare-projects?projects={codes}&sort=project_irr",
                          cookies=cookies)
        assert resp.status_code == 200, resp.text[:300]
        assert 'data-testid="ds-cross-table"' in resp.text
        assert "Project IRR" in resp.text
        for m in made:
            assert m[2].project_code in resp.text

    def test_sorting_deterministic(self, seeded_db):
        made = self._run_all(seeded_db)
        client, cookies, _ = made[0]
        codes = ",".join(m[2].project_code for m in made)
        html = client.get(f"/v2/compare-projects?projects={codes}&sort=project_irr",
                          cookies=cookies).text
        col = re.findall(r'data-ds-metric="project_irr">([^<]*)<', html)
        vals = [float(v.rstrip("%")) for v in col]
        assert vals == sorted(vals, reverse=True)

    def test_project_without_run_explicitly_unavailable(self, seeded_db):
        made = self._run_all(seeded_db)
        client, cookies, _ = made[0]
        # third project never run — same shared user so the page resolves it
        _, _, record_c = _client_for(
            "ds-x-shared", "generic_data_center_reference", 20.0, "Never Run")
        codes = ",".join([m[2].project_code for m in made] + [record_c.project_code])
        html = client.get(f"/v2/compare-projects?projects={codes}", cookies=cookies).text
        assert "NO CANONICAL RUN" in html

    def test_no_working_copy_leak_into_comparison(self, seeded_db):
        """DS-X_H strengthened: capture the canonical Project IRR display
        BEFORE a causal Working Copy edit, re-render after, assert the value
        is EXACTLY unchanged (canonical Last Run only — no WC leak)."""
        import re as _re
        made = self._run_all(seeded_db)
        client, cookies, record = made[0]
        other = made[1][2].project_code
        codes = f"{other},{record.project_code}"  # runnable project LAST

        def _irr_cell(html):
            m = _re.search(r'data-ds-metric="project_irr">([^<]*)<', html)
            return m.group(1) if m else None

        before = _irr_cell(client.get(
            f"/v2/compare-projects?projects={codes}", cookies=cookies).text)
        assert before is not None and before != "—", (
            "runnable project must show canonical IRR")
        _edit_p50(client, cookies, record.project_code, 2300)  # causal WC edit, no run
        after = _irr_cell(client.get(
            f"/v2/compare-projects?projects={codes}", cookies=cookies).text)
        assert after == before  # canonical value unchanged after WC edit

    def test_compare_get_is_persistence_read_only(self, seeded_db):
        """DS §7 strengthened: a Compare GET performs ZERO database writes —
        row counts stable across projects/workspaces/scenarios/references,
        and known bootstrap/mutation authorities raise if invoked."""
        from unittest import mock

        import sqlite3

        client, cookies, record = _client_for("ds-ro-user")
        other = _client_for("ds-ro-user", "generic_wind_reference",
                            48.0, "DS Wind")[2]
        codes = f"{record.project_code},{other.project_code}"
        # seed one canonical run so the "runnable" path is exercised too
        assert _run_once(client, cookies, record.project_code).status_code == 200

        from app.persistence import db as _db

        def _counts():
            con = sqlite3.connect(_db.DB_PATH)
            try:
                tables = ("projects", "workspace_states", "scenarios",
                          "model_run_history")
                return {t: con.execute(
                    f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in tables}
            finally:
                con.close()

        before = _counts()
        import app.services.project_library_service as _lib
        import app.persistence.projects_repository as _repo
        with mock.patch.object(
                _lib, "ensure_reference_models",
                side_effect=AssertionError("bootstrap ran during compare")),              mock.patch.object(
                 _repo, "save_project",
                 side_effect=AssertionError("project write during compare")),              mock.patch.object(
                 _repo, "save_project",
                 side_effect=AssertionError("project write during compare 2")):
            resp = client.get(f"/v2/compare-projects?projects={codes}",
                              cookies=cookies)
        assert resp.status_code == 200
        assert _counts() == before  # zero persistence mutation

    def test_five_project_cap_with_six_accessible(self, seeded_db):
        """§7 genuine cap test: SIX accessible projects under ONE user, all
        six requested — exactly CROSS_PROJECT_MAX (5) unique columns render
        and the sixth accessible project is excluded."""
        from app.services.reference_seed_service import (
            create_reference_seeded_project,
        )
        client, cookies, _first = _client_for("ds-cap-shared")
        codes = []
        for i in range(6):
            record = create_reference_seeded_project(
                user_id="ds-cap-shared",
                template_source="generic_solar_reference",
                requested_name=f"Cap Project {i}",
                capacity_mw=10.0 + i,
            )
            assert _run_once(client, cookies, record.project_code).status_code == 200
            codes.append(record.project_code)
        assert len(codes) == 6
        html = client.get(
            f"/v2/compare-projects?projects={','.join(codes)}",
            cookies=cookies).text
        shown = re.findall(r'data-testid="ds-col-([^"]+)"', html)
        assert len(shown) == 5, f"expected exactly 5 columns, got {len(shown)}"
        excluded = [c for c in codes if c not in shown]
        assert len(excluded) == 1  # exactly one of the six is excluded

    def test_unknown_prefix_does_not_block_valid_selection(self, seeded_db):
        """§10: the cap applies AFTER resolution — garbage prefixes never
        crowd out a valid later code, and duplicates never consume slots."""
        client, cookies, record = _client_for("ds-unknown-user")
        assert _run_once(client, cookies, record.project_code).status_code == 200
        raw = ",".join(["bad1", "bad2", "bad3", "bad4", "bad5",
                        record.project_code, record.project_code])
        html = client.get(f"/v2/compare-projects?projects={raw}",
                          cookies=cookies).text
        assert 'data-testid="ds-cross-table"' in html
        assert f'data-testid="ds-col-{record.project_code}"' in html

    def test_access_isolation_between_users(self, seeded_db):
        """§9: user A owns project A; user B owns project B.  When user A
        requests A,B — A renders, B exposes nothing (no metadata, no name,
        no KPI values).  Reference projects keep their established
        cross-user accessibility."""
        client_a, cookies_a, record_a = _client_for(
            "ds-iso-user-a", name="Isolation Alpha")
        client_b, cookies_b, record_b = _client_for(
            "ds-iso-user-b", name="Isolation Beta")
        assert _run_once(client_a, cookies_a, record_a.project_code).status_code == 200

        codes = f"{record_a.project_code},{record_b.project_code}"
        html = client_a.get(f"/v2/compare-projects?projects={codes}",
                            cookies=cookies_a).text
        # A renders with its canonical data…
        assert record_a.project_code in html
        assert "Project IRR" in html
        # …B's project name must NOT leak into the rendered comparison
        assert record_b.project_name not in html

    def test_no_engine_invocation_on_compare_render(self, seeded_db):
        client, cookies, record = _client_for("ds-iso-engine-guard")
        with mock.patch("app.api.project_runner.run_project",
                        side_effect=AssertionError("engine ran")), \
             mock.patch("app.services.production_financial_authority.run_clean_production",
                        side_effect=AssertionError("clean engine ran")):
            resp = client.get("/v2/compare-projects", cookies=cookies)
        assert resp.status_code == 200

    def test_five_project_cap(self, seeded_db):
        made = []
        for i in range(6):
            client, cookies, record = _client_for(
                f"ds-cap-user-{i}", "generic_solar_reference", 10.0 + i,
                f"Cap {i}")
            made.append((client, cookies, record))
        client, cookies, _ = made[0]
        codes = ",".join(m[2].project_code for m in made)
        html = client.get(f"/v2/compare-projects?projects={codes}",
                          cookies=cookies).text
        shown = len(re.findall(r'data-testid="ds-col-', html))
        assert shown <= 5
