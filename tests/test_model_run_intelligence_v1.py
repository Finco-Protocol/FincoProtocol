"""Run Intelligence V1 — Run History UI, historical detail, compare.

Covers the correction-gated contracts:

  RUN_INTEL_LISTING          newest-first immutable listing, metadata, scoping
  RUN_INTEL_STATUS_SEMANTICS canonical Last Run CURRENT/STALE; every older row
                             HISTORICAL; MATCHES WORKING COPY is a
                             presentation-only indicator that never makes a
                             row CURRENT
  RUN_INTEL_FAILED_HONESTY   failed attempts create no history entry (and the
                             surface says so)
  RUN_INTEL_DETAIL           read-only historical detail, fail-closed reads
  RUN_INTEL_COMPARE          Last Run vs selected historical run via the
                             existing compare machinery — no recomputation,
                             unavailable stays unavailable, zero stays zero
  RUN_INTEL_NO_ENGINE        no engine execution during any render
  RUN_INTEL_NAV              navigation availability + post-run refresh

The append-only run-history authority itself is NOT modified.
"""
from __future__ import annotations

import re
import sqlite3
from unittest import mock

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "run-intel.db"))
    db.init_db()
    yield


VERTICAL = ("generic_solar_reference", 64.0)


def _client_with_project(template_source: str = VERTICAL[0],
                         capacity_mw: float = VERTICAL[1],
                         user_id: str = "run-intel-user"):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    record = create_reference_seeded_project(
        user_id=user_id,
        template_source=template_source,
        requested_name=f"Run Intel {template_source}",
        capacity_mw=capacity_mw,
    )
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id,
                                                 username="admin")}
    client = TestClient(main_web.app, raise_server_exceptions=True)
    return client, cookies, record


def _run(client, cookies, code, *, tamper_hash: str | None = None):
    """Execute the canonical run route once (real engine, real commit)."""
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies)
    assert page.status_code == 200
    m = re.search(r'name="content_hash" value="([^"]+)"', page.text)
    mv = re.search(r'name="workbook_version" value="([^"]+)"', page.text)
    return client.post(
        "/v2/workbook/run",
        data={"project": code,
              "content_hash": tamper_hash or m.group(1),
              "workbook_version": mv.group(1)},
        cookies=cookies,
        headers={"HX-Request": "true"},
    )


def _edit_p50(client, cookies, code, value):
    """Causal Working Copy edit (Canonical Inputs Slice 1 field)."""
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies)
    m = re.search(r'name="content_hash" value="([^"]+)"', page.text)
    mv = re.search(r'name="workbook_version" value="([^"]+)"', page.text)
    resp = client.post(
        "/v2/workbook/inputs-slice1/update",
        data={"field_id": "project_setup.technical.p50_hours",
              "value": str(value),
              "project": code,
              "workbook_version": mv.group(1),
              "content_hash": m.group(1)},
        cookies=cookies,
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp


def _listing(client, cookies, code):
    resp = client.get(f"/v2/workbook/run-history?project={code}",
                      cookies=cookies)
    assert resp.status_code == 200, resp.text[:300]
    return resp.text


def _row_blocks(html):
    """Split the listing into per-row text blocks (newest first)."""
    body = html.split('data-testid="run-history-table"')[1]
    parts = re.split(r'data-testid="run-history-row-\d+"', body)[1:]
    return [p.split("</tr>")[0] for p in parts]


class TestListing:
    def test_newest_first_with_metadata(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        assert _run(client, cookies, record.project_code).status_code == 200
        html = _listing(client, cookies, record.project_code)
        blocks = _row_blocks(html)
        assert len(blocks) == 2
        # newest first: first block ran_at >= second block ran_at
        ts = [re.search(r'class="v2-rh-ts">([^<]+)<', b).group(1) for b in blocks]
        assert ts[0] >= ts[1]
        # institutional metadata rendered
        assert "v2_run" in blocks[0]
        assert 'data-testid="run-history-status-1"' in html

    def test_user_project_scoping(self, seeded_db):
        client_a, cookies_a, record_a = _client_with_project(
            user_id="run-intel-user-a")
        assert _run(client_a, cookies_a, record_a.project_code).status_code == 200
        # another user's project cannot read user A's history entry
        client_b, cookies_b, record_b = _client_with_project(
            user_id="run-intel-user-b")
        page = client_b.get(
            f"/v2/workbook/run-history?project={record_b.project_code}",
            cookies=cookies_b)
        assert page.status_code == 200
        assert 'data-testid="run-history-empty"' in page.text
        entry_id = re.search(
            r'data-history-id="([^"]+)"',
            _listing(client_a, cookies_a, record_a.project_code)).group(1)
        detail = client_b.get(
            f"/v2/workbook/run-history/detail"
            f"?project={record_b.project_code}&history_id={entry_id}",
            cookies=cookies_b)
        assert detail.status_code == 404

    def test_empty_state(self, seeded_db):
        client, cookies, record = _client_with_project()
        html = _listing(client, cookies, record.project_code)
        assert 'data-testid="run-history-empty"' in html
        assert 'data-testid="run-history-failed-note"' in html


class TestStatusSemantics:
    def test_last_run_current_then_historical_rows(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        html = _listing(client, cookies, record.project_code)
        # canonical Last Run is CURRENT (header line)
        assert 'run-history-last-run-state-current' in html
        # the newest row is the Last Run; it is NOT labelled CURRENT per-row
        row1 = _row_blocks(html)[0]
        assert "LAST RUN" in row1
        assert ">CURRENT<" not in row1

    def test_stale_after_working_copy_edit(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        _edit_p50(client, cookies, record.project_code, 2100)
        html = _listing(client, cookies, record.project_code)
        assert 'run-history-last-run-state-stale' in html

    def test_older_row_matches_without_becoming_current(self, seeded_db):
        """Three consecutive runs on an unchanged Working Copy share one
        economic identity: the newest row is the LAST RUN; the two OLDER
        rows stay HISTORICAL and legitimately show the presentation-only
        MATCHES WORKING COPY indicator — none of them is CURRENT."""
        client, cookies, record = _client_with_project()
        for _ in range(3):
            assert _run(client, cookies, record.project_code).status_code == 200
        html = _listing(client, cookies, record.project_code)
        assert 'run-history-last-run-state-current' in html
        blocks = _row_blocks(html)
        assert len(blocks) == 3
        # newest row = LAST RUN
        assert "LAST RUN" in blocks[0]
        # older rows: HISTORICAL + MATCHES WORKING COPY, never CURRENT
        for block in blocks[1:]:
            assert "HISTORICAL" in block
            assert "MATCHES WORKING COPY" in block
            assert ">CURRENT<" not in block

    def test_edited_history_row_stops_matching(self, seeded_db):
        """After a Working Copy edit, the pre-edit historical row no longer
        matches the current identity; the header goes STALE."""
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        _edit_p50(client, cookies, record.project_code, 2100)
        html = _listing(client, cookies, record.project_code)
        assert 'run-history-last-run-state-stale' in html
        block = _row_blocks(html)[0]
        assert "MATCHES WORKING COPY" not in block

    def test_identical_inputs_share_identity(self, seeded_db):
        """Identical inputs → identical composite identity across runs."""
        client, cookies, record = _client_with_project()
        for _ in range(3):
            assert _run(client, cookies, record.project_code).status_code == 200
        blocks = _row_blocks(_listing(client, cookies, record.project_code))
        ids = [re.search(r'class="v2-rh-mono">([0-9a-f]+)<', b).group(1)
               for b in blocks]
        assert len(set(ids)) == 1  # same inputs → same composite identity


class TestFailedHonesty:
    def test_failed_run_creates_no_history_entry(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        before = len(_row_blocks(_listing(client, cookies, record.project_code)))
        # tampered composite hash → pre-engine CAS failure, no commit
        resp = _run(client, cookies, record.project_code,
                    tamper_hash="0" * 64)
        assert resp.status_code == 200  # HTMX error surface, no 500
        after = len(_row_blocks(_listing(client, cookies, record.project_code)))
        assert after == before  # failed attempt appended nothing
        # the honesty note is always present
        assert 'data-testid="run-history-failed-note"' in \
            _listing(client, cookies, record.project_code)


class TestMalformedFailClosed:
    def test_listing_fails_closed_on_malformed_payload(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        # corrupt one stored row directly
        from app.persistence import db as _db
        con = sqlite3.connect(_db.DB_PATH)
        try:
            con.execute("UPDATE model_run_history SET runtime_summary_json='{not json'")
            con.commit()
        finally:
            con.close()
        html = _listing(client, cookies, record.project_code)
        assert 'data-testid="run-history-error"' in html
        assert "RUN_HISTORY_PAYLOAD_MALFORMED" in html

    def test_detail_fails_closed_on_malformed_payload(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        entry_id = re.search(
            r'data-history-id="([^"]+)"',
            _listing(client, cookies, record.project_code)).group(1)
        from app.persistence import db as _db
        con = sqlite3.connect(_db.DB_PATH)
        try:
            con.execute("UPDATE model_run_history SET runtime_summary_json='{not json'")
            con.commit()
        finally:
            con.close()
        resp = client.get(
            f"/v2/workbook/run-history/detail"
            f"?project={record.project_code}&history_id={entry_id}",
            cookies=cookies)
        assert resp.status_code == 422
        assert "RUN_HISTORY_PAYLOAD_MALFORMED" in resp.text


class TestDetail:
    def test_detail_renders_identity_kpis_integrity(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        entry_id = re.search(
            r'data-history-id="([^"]+)"',
            _listing(client, cookies, record.project_code)).group(1)
        resp = client.get(
            f"/v2/workbook/run-history/detail"
            f"?project={record.project_code}&history_id={entry_id}",
            cookies=cookies)
        assert resp.status_code == 200
        html = resp.text
        assert 'data-testid="run-detail-identity"' in html
        assert "HISTORICAL" in html
        assert 'data-testid="run-detail-kpis"' in html
        assert "Project IRR" in html
        assert 'data-testid="run-detail-integrity"' in html

    def test_detail_is_read_only(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        entry_id = re.search(
            r'data-history-id="([^"]+)"',
            _listing(client, cookies, record.project_code)).group(1)
        html = client.get(
            f"/v2/workbook/run-history/detail"
            f"?project={record.project_code}&history_id={entry_id}",
            cookies=cookies).text
        assert "hx-post" not in html
        assert "<form" not in html
        assert ">Restore<" not in html
        assert ">Rerun<" not in html

    def test_unknown_history_id_404(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        resp = client.get(
            f"/v2/workbook/run-history/detail"
            f"?project={record.project_code}&history_id=does-not-exist",
            cookies=cookies)
        assert resp.status_code == 404


class TestCompare:
    def _two_runs(self, client, cookies, record):
        assert _run(client, cookies, record.project_code).status_code == 200
        _edit_p50(client, cookies, record.project_code, 2100)
        assert _run(client, cookies, record.project_code).status_code == 200
        html = _listing(client, cookies, record.project_code)
        # oldest row's history id (immutable historical run at H1)
        return re.findall(r'data-history-id="([^"]+)"', html)[-1]

    def test_compare_last_run_vs_historical(self, seeded_db):
        client, cookies, record = _client_with_project()
        hist_id = self._two_runs(client, cookies, record)
        resp = client.get(
            f"/v2/workbook/run-history/compare"
            f"?project={record.project_code}&history_id={hist_id}",
            cookies=cookies)
        assert resp.status_code == 200, resp.text[:300]
        html = resp.text
        assert 'data-testid="run-compare-columns"' in html
        # column states: Last Run CURRENT (fresh) + HISTORICAL column
        assert 'run-compare-col-state-1' in html
        assert "CURRENT" in html
        assert "HISTORICAL" in html
        # persisted KPI rows with delta cells
        assert 'data-testid="run-compare-project_irr-last"' in html
        assert 'data-testid="run-compare-project_irr-hist"' in html
        assert 'data-testid="run-compare-project_irr-delta"' in html

    def test_unavailable_stays_unavailable(self, seeded_db):
        client, cookies, record = _client_with_project()
        hist_id = self._two_runs(client, cookies, record)
        html = client.get(
            f"/v2/workbook/run-history/compare"
            f"?project={record.project_code}&history_id={hist_id}",
            cookies=cookies).text
        # documented raw gap: total_cfads_keur never fabricated
        cfads = re.search(
            r'data-kpi-key="total_cfads_keur".*?</tr>', html, re.S).group(0)
        assert "—" in cfads

    def test_legitimate_zero_stays_zero(self):
        """Unit: a persisted 0.0 renders as zero through the compare
        machinery — never as unavailable."""
        from app.v2.run_history_projection import build_run_compare
        from types import SimpleNamespace

        class _Entry:
            runtime_summary = {"min_dscr": 0.0, "project_irr": 0.05}
            debt_schedule = {}
            sponsor_schedule = {}
            ran_at = "2026-10-07T10:00:00"

        result = build_run_compare(
            last_run_kpis={"min_dscr": 0.0, "project_irr": 0.05},
            last_run_ran_at="2026-10-07 11:00",
            last_run_is_stale=False,
            history_entry=_Entry(),
        )
        dscr = next(r for r in result["rows"] if r.key == "min_dscr")
        assert dscr.values[0] == "0.00x"
        assert dscr.values[1] == "0.00x"
        assert dscr.deltas[1] == "+0.00x"

    def test_stale_last_run_disclosed(self, seeded_db):
        client, cookies, record = _client_with_project()
        hist_id = self._two_runs(client, cookies, record)
        # edit the Working Copy AFTER the second run → Last Run goes STALE
        _edit_p50(client, cookies, record.project_code, 2300)
        html = client.get(
            f"/v2/workbook/run-history/compare"
            f"?project={record.project_code}&history_id={hist_id}",
            cookies=cookies).text
        assert 'data-testid="run-compare-stale-note"' in html
        assert "STALE" in html


class TestNoEngineOnRender:
    def test_history_detail_compare_never_run_engine(self, seeded_db):
        client, cookies, record = _client_with_project()
        assert _run(client, cookies, record.project_code).status_code == 200
        entry_id = re.search(
            r'data-history-id="([^"]+)"',
            _listing(client, cookies, record.project_code)).group(1)
        with mock.patch("app.api.project_runner.run_project",
                        side_effect=AssertionError("engine ran")), \
             mock.patch("app.services.production_financial_authority.run_clean_production",
                        side_effect=AssertionError("clean engine ran")):
            assert client.get(
                f"/v2/workbook/run-history?project={record.project_code}",
                cookies=cookies).status_code == 200
            assert client.get(
                f"/v2/workbook/run-history/detail"
                f"?project={record.project_code}&history_id={entry_id}",
                cookies=cookies).status_code == 200
            assert client.get(
                f"/v2/workbook/run-history/compare"
                f"?project={record.project_code}&history_id={entry_id}",
                cookies=cookies).status_code == 200


class TestNavigationAndRefresh:
    def test_nav_item_available_and_tab_mounted(self, seeded_db):
        client, cookies, record = _client_with_project()
        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        assert page.status_code == 200
        assert 'id="tab-run-history"' in page.text
        assert 'id="panel-run-history"' in page.text
        # persistent left navigation: Run History is now available
        assert 'data-nav-tab="tab-run-history"' in page.text
        assert 'nav-future-run-history' not in page.text
        # listing is embedded in the workbook
        assert 'data-testid="run-history"' in page.text
        assert 'data-testid="run-history-failed-note"' in page.text

    def test_post_run_refreshes_history_listing(self, seeded_db):
        client, cookies, record = _client_with_project()
        run = _run(client, cookies, record.project_code)
        assert run.status_code == 200
        assert 'id="v2-sheet-run-history" hx-swap-oob="true"' in run.text
        assert 'data-testid="run-history"' in run.text
        # the just-committed run is visible in the refreshed listing
        assert "LAST RUN" in run.text

    def test_projection_marks_matches_only_for_equal_identity(self):
        """Unit: the MATCHES WORKING COPY indicator follows the stored
        composite hash; rows with different identity never match."""
        from types import SimpleNamespace
        from app.v2.run_history_projection import build_run_history_rows

        ws = SimpleNamespace(last_runtime_snapshot_id="snap-2",
                             last_runtime_identity=None)
        entries = [
            SimpleNamespace(history_id="h2", runtime_snapshot_id="snap-2",
                            composite_hash="H2", ran_at="2026-10-07T11:00:00",
                            active_scenario_name="Base", runtime_origin="v2_run",
                            engine_version="1.0", workbook_version="2.3.0",
                            model_v2_binding=None),
            SimpleNamespace(history_id="h1", runtime_snapshot_id="snap-1",
                            composite_hash="H1", ran_at="2026-10-07T10:00:00",
                            active_scenario_name="Base", runtime_origin="v2_run",
                            engine_version="1.0", workbook_version="2.3.0",
                            model_v2_binding=None),
        ]
        rows = build_run_history_rows(entries, ws=ws,
                                      current_composite_hash="H1",
                                      project_code="p1")
        assert rows[0].is_last_run and rows[0].status_label == "LAST RUN"
        assert not rows[1].is_last_run
        assert rows[1].status_label == "HISTORICAL"
        assert rows[1].matches_working_copy is True
        assert rows[0].matches_working_copy is False
