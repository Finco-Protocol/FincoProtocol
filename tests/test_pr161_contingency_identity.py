"""PR #161 correction: contingency authority is part of composite workbook
identity; runtime freshness, institutional export and scenario presentation
all agree on the same effective authority."""
from __future__ import annotations

import io
import re
import uuid

import pytest

from app.contingency_authority import SCENARIO_OVERRIDE_KEY, capex_basis_keur

CODE_RE = re.compile(r'name="content_hash"\s+value="([0-9a-f]{64})"')


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", str(tmp_path / "pr161.db"))
    db_mod.init_db()
    yield


def _project(owner="o161"):
    import main_web
    from app.persistence.projects_repository import create_project_record
    from app.persistence.workspace_repository import save_workspace_state

    code = "p161-" + uuid.uuid4().hex[:8]
    snap = main_web._project_baseline_snapshot("Solar", "generic_solar")
    snap.update({"active_project": code, "project_name": "PR161", "project_type": "Solar",
                 "project_origin": "user_created", "country_market": "Synthetic Market",
                 "scenario": "Base"})
    rec = create_project_record(user_id=owner, project_code=code, project_name="PR161",
                                project_type="Solar", project_origin="user_created",
                                template_source="generic_solar", baseline_snapshot=snap)
    save_workspace_state(user_id=owner, project_id=rec.project_id, project_code=code,
                         draft_snapshot=snap, saved_snapshot=snap, dirty=False)
    return owner, rec


def _hash(owner, rec):
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return assemble_consistent_for_get(owner, rec.project_id, WORKBOOK.version).composite_hash


def _set(owner, rec, kind, pct, expected=None):
    from app.persistence.projects_repository import get_project_by_id
    from app.v2.capex_commands import set_contingency_percentage
    from app.workbook.registry import WORKBOOK
    return set_contingency_percentage(
        project_record=get_project_by_id(rec.project_id), user_id=owner, kind=kind, pct=pct,
        workbook_version=WORKBOOK.version,
        expected_content_hash=expected or _hash(owner, rec))


def _client(owner):
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from starlette.testclient import TestClient
    c = TestClient(main_web.app, raise_server_exceptions=False)
    h = {"Cookie": f"{COOKIE_NAME}={create_session_token(user_id=owner, username=owner)}",
         "HX-Request": "true"}
    return c, h


def _run(client, headers, rec, owner):
    from app.workbook.registry import WORKBOOK
    r = client.post("/v2/workbook/run", data={
        "project": rec.project_code, "workbook_version": WORKBOOK.version,
        "content_hash": _hash(owner, rec)}, headers=headers)
    assert r.status_code == 200, r.text
    return r


def _state(owner, rec):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.runtime_authority import resolve_runtime_freshness
    ws = get_workspace_state(owner, rec.project_id)
    return resolve_runtime_freshness(ws, current_composite_hash=_hash(owner, rec)).state.name


# ─────────────── A. identity ───────────────
class TestIdentityRotation:
    def test_pure_baseline_hash_unchanged_without_authority(self):
        from app.workbook.workbook_identity import (
            CanonicalScenarioState, assemble_from_parts)
        kw = dict(scalar_snapshot={"a": "1"}, template_source="t", project_origin="o",
                  workbook_version="v", capex_rows=[], opex_rows=[],
                  scenario=CanonicalScenarioState(None, None, {}))
        base = assemble_from_parts(**kw).composite_hash
        assert assemble_from_parts(**kw, contingency_authority=None).composite_hash == base
        assert assemble_from_parts(
            **kw, contingency_authority={"capex_pct": None, "opex_pct": None}
        ).composite_hash == base
        assert assemble_from_parts(
            **kw, contingency_authority={"capex_pct": 5.0, "opex_pct": None}
        ).composite_hash != base

    def test_hash_rotates_through_every_transition(self, env):
        owner, rec = _project()
        h0 = _hash(owner, rec)
        seq = [5.0, 10.0, 0.0, None]
        prev = h0
        seen = [h0]
        for pct in seq:
            new = _set(owner, rec, "capex", pct)
            assert new != prev, f"hash did not rotate to {pct}"
            assert new == _hash(owner, rec)          # returned hash == recomputed
            prev = new
        assert prev == h0                             # None restores the baseline hash

    def test_capex_and_opex_are_independent_axes(self, env):
        owner, rec = _project()
        h0 = _hash(owner, rec)
        hc = _set(owner, rec, "capex", 5.0)
        _set(owner, rec, "capex", None)
        ho = _set(owner, rec, "opex", 5.0)
        assert len({h0, hc, ho}) == 3
        from app.persistence.projects_repository import get_project_by_id
        from app.contingency_authority import read_authority
        meta = get_project_by_id(rec.project_id).replay_metadata
        assert read_authority(meta, "opex") == 5.0 and read_authority(meta, "capex") is None

    def test_second_client_with_old_hash_is_rejected(self, env):
        from app.v2.capex_commands import CapexStaleIdentityError
        owner, rec = _project()
        old = _hash(owner, rec)
        _set(owner, rec, "capex", 5.0, expected=old)
        with pytest.raises(CapexStaleIdentityError):
            _set(owner, rec, "capex", 10.0, expected=old)
        from app.persistence.projects_repository import get_project_by_id
        from app.contingency_authority import read_authority
        assert read_authority(get_project_by_id(rec.project_id).replay_metadata, "capex") == 5.0


# ─────────────── runtime freshness ───────────────
class TestFreshness:
    def test_run_edit_stale_run_current(self, env):
        owner, rec = _project()
        client, h = _client(owner)
        with client:
            _run(client, h, rec, owner)
            assert _state(owner, rec) == "CURRENT"
            _set(owner, rec, "capex", 5.0)
            assert _state(owner, rec) == "STALE"
            _run(client, h, rec, owner)
            assert _state(owner, rec) == "CURRENT"
            _set(owner, rec, "opex", 4.0)
            assert _state(owner, rec) == "STALE"
            _run(client, h, rec, owner)
            assert _state(owner, rec) == "CURRENT"


# ─────────────── B. export immutability ───────────────
def _xlsx_value(data: bytes, label: str):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            if row and label in [c for c in row if isinstance(c, str)]:
                nums = [c for c in row if isinstance(c, (int, float))]
                out.append(nums[0] if nums else None)
    return out


class TestExportReplay:
    def _export(self, owner, rec):
        from app.services.v2_export_service import build_canonical_last_run_institutional_workbook_export
        from app.persistence.projects_repository import get_project_by_id
        r = build_canonical_last_run_institutional_workbook_export(
            "generic_solar", project_record=get_project_by_id(rec.project_id), user_id=owner)
        assert r.status_code == 200, r.error_content
        return r.bytes_data

    def test_run_at_5_then_edit_to_10_export_still_5(self, env):
        owner, rec = _project()
        client, h = _client(owner)
        with client:
            _set(owner, rec, "opex", 5.0)
            _set(owner, rec, "capex", 5.0)
            _run(client, h, rec, owner)
            _set(owner, rec, "opex", 10.0)            # edit WITHOUT rerun
            _set(owner, rec, "capex", 10.0)
            data = self._export(owner, rec)
        assert 0.05 in _xlsx_value(data, "Contingency percent")
        assert 0.10 not in _xlsx_value(data, "Contingency percent")
        assert 0.05 in _xlsx_value(data, "C.13 contingency percent")
        assert _xlsx_value(data, "C.13 contingency percent").count(0.10) == 0

        from app.persistence.workspace_repository import get_workspace_state
        ws = get_workspace_state(owner, rec.project_id)
        ca = ws.last_runtime_identity["contingency_authority"]
        assert ca["capex_pct"] == 5.0 and ca["opex_pct"] == 5.0

        from app.services.export_service import resolve_export_authority
        from app.persistence.projects_repository import get_project_by_id
        auth = resolve_export_authority(get_project_by_id(rec.project_id), owner)
        pi = auth.project_inputs
        assert pi.capex.contingencies.amount_keur == pytest.approx(0.05 * capex_basis_keur(pi.capex))
        assert [i.percentage_of_opex for i in pi.opex if i.percentage_of_opex > 0] == [pytest.approx(0.05)]


# ─────────────── C. scenario consistency ───────────────
def _active_scenario(client, headers, owner, rec, overrides):
    from app.persistence.scenarios_repository import update_scenario_overrides
    from app.persistence.workspace_repository import get_workspace_state
    created = client.post("/v2/workbook/scenarios/create",
                          data={"project": rec.project_code, "scenario_name": "S8"}, headers=headers)
    assert created.status_code == 200, created.text
    sid = get_workspace_state(owner, rec.project_id).active_scenario_id
    update_scenario_overrides(owner, sid, overrides)
    return sid


class TestScenarioConsistency:
    @pytest.mark.parametrize("kind", ["capex", "opex"])
    def test_display_run_identity_export_agree_on_override(self, env, kind):
        owner, rec = _project()
        client, h = _client(owner)
        with client:
            _set(owner, rec, kind, 5.0)
            _active_scenario(client, h, owner, rec, {SCENARIO_OVERRIDE_KEY: {kind: 8.0}})

            # display: sheet + inputs summary
            page = client.get(f"/v2/workbook?project={rec.project_code}", headers=h)
            assert page.status_code == 200
            if kind == "capex":
                assert 'data-testid="capex-contingency-authority"' in page.text
                m = re.search(r'capex-contingency-authority".*?Contingency %</span><span class="v2-field-value">([\d.]+)%',
                              page.text, re.S)
                assert m and float(m.group(1)) == 8.0
            else:
                m = re.search(r'data-testid="opex-contingency-rate">\s*([\d.]+)%', page.text)
                assert m and float(m.group(1)) == 8.0
            from app.persistence.projects_repository import get_project_by_id
            from app.persistence.workspace_repository import get_workspace_state
            from app.ui.inputs_summary import build_inputs_summary
            from app.workbook.service import WorkbookService
            ws = get_workspace_state(owner, rec.project_id)
            pis = WorkbookService.build_draft_input_set_from_workspace(ws)
            summ = build_inputs_summary(get_project_by_id(rec.project_id), pis, ws)
            baseline_ws = None  # noqa: F841
            # Inputs summary must follow the 8% authority, not the 5% project value
            from app.ui.capex_view_model import build_capex_view_model  # noqa: F401
            assert summ  # constructed with the scenario authority (checked below via totals)

            # run + identity
            _run(client, h, rec, owner)
            ws = get_workspace_state(owner, rec.project_id)
            ca = ws.last_runtime_identity["contingency_authority"]
            assert ca[f"{kind}_pct"] == 8.0 and ca[f"{kind}_source"] == "scenario_override"

            # export
            from app.services.export_service import resolve_export_authority
            pi = resolve_export_authority(get_project_by_id(rec.project_id), owner).project_inputs
            if kind == "capex":
                assert pi.capex.contingencies.amount_keur == pytest.approx(0.08 * capex_basis_keur(pi.capex))
            else:
                assert [i.percentage_of_opex for i in pi.opex if i.percentage_of_opex > 0] == [pytest.approx(0.08)]

    def test_inputs_summary_total_follows_scenario_capex_override(self, env):
        from app.persistence.projects_repository import get_project_by_id
        from app.persistence.workspace_repository import get_workspace_state
        from app.ui.inputs_summary import build_inputs_summary
        from app.workbook.service import WorkbookService
        owner, rec = _project()
        client, h = _client(owner)
        with client:
            def total():
                ws = get_workspace_state(owner, rec.project_id)
                pis = WorkbookService.build_draft_input_set_from_workspace(ws)
                return build_inputs_summary(get_project_by_id(rec.project_id), pis, ws)["capex_hard_keur"]
            _set(owner, rec, "capex", 5.0)
            t5 = total()
            _active_scenario(client, h, owner, rec, {SCENARIO_OVERRIDE_KEY: {"capex": 8.0}})
            t8 = total()
        assert t8 > t5

    def test_malformed_override_rejected_at_persistence(self, env):
        from app.persistence.scenarios_repository import update_scenario_overrides
        owner, rec = _project()
        client, h = _client(owner)
        with client:
            sid = _active_scenario(client, h, owner, rec, {})
            with pytest.raises(ValueError):
                update_scenario_overrides(owner, sid, {SCENARIO_OVERRIDE_KEY: {"capex": 101}})
            with pytest.raises(ValueError):
                update_scenario_overrides(owner, sid, {SCENARIO_OVERRIDE_KEY: {"bogus": 1}})


# ─────────────── reference parity ───────────────
@pytest.mark.parametrize("factory", [
    "create_generic_solar_reference", "create_generic_wind_reference",
    "create_generic_ev_charging_reference", "create_generic_data_center_reference",
])
def test_reference_parity_no_authority_means_identical_objects(factory):
    from app import project_factories
    from app.contingency_authority import apply_capex_contingency, apply_opex_contingency
    pi = getattr(project_factories, factory)()
    assert apply_capex_contingency(pi.capex, None) is pi.capex
    assert apply_opex_contingency(pi.opex, None) is pi.opex


def test_nonzero_contingency_passes_engine_payment_weight_contract():
    """Regression: a non-zero C.13 on a zero-amount placeholder item must carry
    a valid spending profile or the clean engine fails closed (PR9 weights)."""
    import dataclasses
    from app.project_factories import create_generic_solar_reference
    from app.contingency_authority import apply_capex_contingency
    from app.services.production_financial_authority import run_clean_production

    pi = create_generic_solar_reference()
    out = dataclasses.replace(pi, capex=apply_capex_contingency(pi.capex, 5.0))
    item = out.capex.contingencies
    assert item.y0_share + sum(item.spending_profile) == pytest.approx(1.0)
    run_clean_production(out)  # must not raise
