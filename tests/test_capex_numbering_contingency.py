"""Custom CAPEX display numbering, C.11 'Linked' presentation, and the typed
C.13 / B.13 contingency percentage authority."""
from __future__ import annotations

import dataclasses
import math

import pytest

from app.contingency_authority import (
    CAPEX_ELIGIBLE_CATEGORIES,
    CAPEX_ELIGIBLE_FIELDS,
    SCENARIO_OVERRIDE_KEY,
    apply_capex_contingency,
    apply_opex_contingency,
    capex_basis_keur,
    capex_lineage,
    read_authority,
    resolve_pct,
    validate_pct,
    write_authority,
)
from app.ui.capex_view_model import derive_custom_display_code


# ───────────────────────── fixtures ─────────────────────────
@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", str(tmp_path / "cap.db"))
    db_mod.init_db()
    yield db_mod


@pytest.fixture()
def solar_copy(seeded_db):
    from app.services.reference_seed_service import create_reference_seeded_project

    return create_reference_seeded_project(
        user_id="cap-user", template_source="generic_solar_reference",
        requested_name="Cap Solar", capacity_mw=64.0,
    )


def _reference_capex():
    from app.project_factories import create_generic_solar_reference

    return create_generic_solar_reference().capex


def _hash(user_id, record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    ws = get_workspace_state(user_id, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ident = assemble_consistent_for_get(
        user_id=user_id, project_id=record.project_id, workbook_version=pis.workbook_version,
    )
    return pis.workbook_version, ident.composite_hash


def _vm(user_id, record):
    from app.persistence.projects_repository import get_project_by_id
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.v2.router import _build_capex_vm_ctx

    wv, h = _hash(user_id, record)
    ws = get_workspace_state(user_id, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(h)
    return _build_capex_vm_ctx(get_project_by_id(record.project_id), pis, ws=ws, workspace_owner=user_id)


def _set_pct(user_id, record, kind, pct):
    from app.persistence.projects_repository import get_project_by_id
    from app.v2.capex_commands import set_contingency_percentage

    wv, h = _hash(user_id, record)
    set_contingency_percentage(
        project_record=get_project_by_id(record.project_id), user_id=user_id,
        kind=kind, pct=pct, workbook_version=wv, expected_content_hash=h,
    )


# ───────────────────── A. display numbering ─────────────────────
class TestDisplayNumbering:
    CANON = ["C.01.01", "C.01.02", "C.01.03", "C.01.04"]

    def test_first_custom_row_takes_next_reference_position(self):
        assert derive_custom_display_code("C.01.U001", self.CANON) == "C.01.05"

    def test_second_custom_row_follows(self):
        assert derive_custom_display_code("C.01.U002", self.CANON) == "C.01.06"

    def test_canonical_code_unchanged(self):
        assert derive_custom_display_code("C.01.03", self.CANON) == "C.01.03"

    def test_is_pure_so_delete_and_reload_cannot_renumber(self):
        # U002 keeps C.01.06 whether or not U001 still exists.
        assert derive_custom_display_code("C.01.U002", self.CANON) == "C.01.06"
        assert derive_custom_display_code("C.01.U002", self.CANON) == "C.01.06"

    def test_other_group_canonical_rows_are_ignored(self):
        assert derive_custom_display_code("C.02.U001", self.CANON) == "C.02.01"

    def test_vm_keeps_internal_identity_and_deactivated_row_is_stable(self, solar_copy):
        from app.persistence.capex_sub_lines import create_sub_line, soft_delete_sub_line
        from app.persistence.db import get_cursor

        with get_cursor() as cur:
            a = create_sub_line(cur, project_id=solar_copy.project_id,
                                parent_category_code="C.01", label="A", amount_keur=10.0)
            b = create_sub_line(cur, project_id=solar_copy.project_id,
                                parent_category_code="C.01", label="B", amount_keur=20.0)
        assert (a.business_code, b.business_code) == ("C.01.U001", "C.01.U002")

        def shown():
            vm = _vm("cap-user", solar_copy)["capex_vm"]
            grp = next(g for g in vm.groups if g.code == "C.01")
            return {ln.code: ln.display_code for ln in grp.lines if ln.code.startswith("C.01.U")}

        first = shown()
        assert set(first) == {"C.01.U001", "C.01.U002"}
        assert all(not v.startswith("C.01.U") for v in first.values())
        n1 = int(first["C.01.U001"].rsplit(".", 1)[1])
        assert first["C.01.U002"] == f"C.01.{n1 + 1:02d}"
        again = shown()                      # reload determinism
        assert again == first
        with get_cursor() as cur:
            soft_delete_sub_line(cur, project_id=solar_copy.project_id, sub_line_id=a.sub_line_id)
        after = shown()                      # deactivate: survivor keeps its number
        assert after == {"C.01.U002": first["C.01.U002"]}


# ───────────────────── B. C.11 linked ─────────────────────
class TestLinkedPresentation:
    def _tpl(self):
        from pathlib import Path
        return Path("app/templates/v2/partials/sheet_capex.html").read_text()

    def test_unexplained_shared_badge_removed(self):
        t = self._tpl()
        assert ">Shared<" not in t and "Shared / non-owning" not in t

    def test_linked_text_present(self):
        t = self._tpl()
        assert t.count("Linked to Audit &amp; Legal; this reference amount is not counted twice.") >= 2
        assert ">Linked</span>" in t

    def test_c08_c11_economics_unchanged(self):
        from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
        assert CAPEX_CATEGORY_TO_FIELD["C.08"] == CAPEX_CATEGORY_TO_FIELD["C.11"] == "audit_legal"


# ───────────────────── C. CAPEX contingency ─────────────────────
class TestCapexContingencyMath:
    def test_basis_table_has_no_circular_members(self):
        assert "C.13" not in CAPEX_ELIGIBLE_CATEGORIES
        assert "C.17" not in CAPEX_ELIGIBLE_CATEGORIES and "C.18" not in CAPEX_ELIGIBLE_CATEGORIES
        assert "contingencies" not in CAPEX_ELIGIBLE_FIELDS
        assert len(CAPEX_ELIGIBLE_FIELDS) == 14

    @pytest.mark.parametrize("pct", [0.0, 5.0, 100.0])
    def test_amounts(self, pct):
        capex = _reference_capex()
        basis = capex_basis_keur(capex)
        out = apply_capex_contingency(capex, pct)
        assert out.contingencies.amount_keur == pytest.approx(pct / 100.0 * basis)
        # Self exclusion: changing the contingency never changes the basis.
        assert capex_basis_keur(out) == pytest.approx(basis)

    def test_financing_fields_do_not_enter_basis(self):
        capex = _reference_capex()
        loaded = dataclasses.replace(capex, idc_keur=9e6, bank_fees_keur=9e6,
                                     reserve_accounts_keur=9e6, vat_costs_keur=9e6)
        assert capex_basis_keur(loaded) == pytest.approx(capex_basis_keur(capex))

    def test_zero_basis_is_explicit_zero_not_unavailable(self):
        capex = _reference_capex()
        zeros = {f: dataclasses.replace(getattr(capex, f), amount_keur=0.0)
                 for f in CAPEX_ELIGIBLE_FIELDS}
        z = dataclasses.replace(capex, **zeros)
        assert apply_capex_contingency(z, 5.0).contingencies.amount_keur == 0.0
        lin = capex_lineage(basis_keur=0.0, pct=5.0, source="project")
        assert lin.status == "zero_basis" and lin.amount_keur == 0.0

    def test_unavailable_is_not_zero(self):
        lin = capex_lineage(basis_keur=None, pct=5.0, source="project")
        assert lin.status == "unavailable" and lin.amount_keur is None

    def test_missing_authority_keeps_reference_object(self):
        capex = _reference_capex()
        assert apply_capex_contingency(capex, None) is capex

    @pytest.mark.parametrize("bad", [-1, 101, float("nan"), float("inf"), True, "5", None.__class__])
    def test_invalid_pct_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_pct(bad)

    def test_lineage_exposes_everything(self):
        d = capex_lineage(basis_keur=1000.0, pct=5.0, source="project").to_dict()
        assert d["pct"] == 5.0 and d["basis_mode"] == "OTHER_ELIGIBLE_CAPEX"
        assert d["basis_amount_keur"] == 1000.0 and d["amount_keur"] == pytest.approx(50.0)
        assert "C.13" in [c for c, _ in d["excluded_categories"]]
        assert "C.01" in d["included_categories"]


class TestAuthorityStorage:
    def test_roundtrip_and_clear(self):
        meta = write_authority({"x": 1}, "capex", 5.0)
        assert read_authority(meta, "capex") == 5.0 and meta["x"] == 1
        assert read_authority(write_authority(meta, "capex", None), "capex") is None

    def test_scenario_override_wins(self):
        meta = write_authority({}, "capex", 5.0)
        pct, src = resolve_pct(meta, {SCENARIO_OVERRIDE_KEY: {"capex": 7.5}}, "capex")
        assert (pct, src) == (7.5, "scenario_override")
        assert resolve_pct(meta, None, "capex") == (5.0, "project")
        assert resolve_pct({}, None, "capex") == (None, "reference_amount")


# ───────────────── Run / save-reload / custom rows ─────────────────
class TestRunFold:
    def test_no_authority_is_identical_to_prior_behaviour(self, solar_copy):
        from app.services import capex_sub_lines_integration as m
        capex = _reference_capex()
        a = m.apply_user_sub_lines_replacing_base(capex, project_id=solar_copy.project_id)
        b = m._fold_user_sub_lines_replacing_base(capex, project_id=solar_copy.project_id)
        assert a == b

    def test_authority_persists_and_custom_rows_included(self, solar_copy):
        from app.persistence.capex_sub_lines import create_sub_line
        from app.persistence.db import get_cursor
        from app.persistence.projects_repository import get_project_by_id
        from app.services import capex_sub_lines_integration as m

        _set_pct("cap-user", solar_copy, "capex", 5.0)
        # save/reload: re-read straight from the DB
        assert read_authority(get_project_by_id(solar_copy.project_id).replay_metadata, "capex") == 5.0

        capex = _reference_capex()
        before = m.apply_user_sub_lines_replacing_base(capex, project_id=solar_copy.project_id)
        b0 = capex_basis_keur(before)
        assert before.contingencies.amount_keur == pytest.approx(0.05 * b0)

        with get_cursor() as cur:
            create_sub_line(cur, project_id=solar_copy.project_id,
                            parent_category_code="C.05", label="X", amount_keur=1000.0)
        after = m.apply_user_sub_lines_replacing_base(capex, project_id=solar_copy.project_id)
        assert capex_basis_keur(after) == pytest.approx(b0 + 1000.0)
        assert after.contingencies.amount_keur == pytest.approx(0.05 * (b0 + 1000.0))

    def test_display_c13_equals_run_fold_with_custom_rows(self, solar_copy):
        from app.persistence.capex_sub_lines import create_sub_line
        from app.persistence.db import get_cursor
        from app.services import capex_sub_lines_integration as m

        with get_cursor() as cur:
            create_sub_line(cur, project_id=solar_copy.project_id,
                            parent_category_code="C.11", label="Legal x", amount_keur=250.0)
            create_sub_line(cur, project_id=solar_copy.project_id,
                            parent_category_code="C.03", label="Y", amount_keur=400.0)
        _set_pct("cap-user", solar_copy, "capex", 5.0)
        vm = _vm("cap-user", solar_copy)["capex_vm"]
        c13 = next(g for g in vm.groups if g.code == "C.13")
        run = m.apply_user_sub_lines_replacing_base(
            _reference_capex(), project_id=solar_copy.project_id)
        assert c13.contingency.mode == "percentage"
        assert c13.subtotal_keur == pytest.approx(run.contingencies.amount_keur, rel=1e-9)
        assert c13.contingency.basis_amount_keur == pytest.approx(capex_basis_keur(run), rel=1e-9)

    def test_scenario_override_applies_in_run_fold(self, solar_copy):
        from app.services import capex_sub_lines_integration as m
        _set_pct("cap-user", solar_copy, "capex", 5.0)
        capex = _reference_capex()
        out = m.apply_user_sub_lines_replacing_base(
            capex, project_id=solar_copy.project_id,
            scenario_overrides={SCENARIO_OVERRIDE_KEY: {"capex": 10.0}},
        )
        assert out.contingencies.amount_keur == pytest.approx(0.10 * capex_basis_keur(out))

    def test_clearing_restores_reference_amount(self, solar_copy):
        from app.services import capex_sub_lines_integration as m
        _set_pct("cap-user", solar_copy, "capex", 5.0)
        _set_pct("cap-user", solar_copy, "capex", None)
        capex = _reference_capex()
        a = m.apply_user_sub_lines_replacing_base(capex, project_id=solar_copy.project_id)
        b = m._fold_user_sub_lines_replacing_base(capex, project_id=solar_copy.project_id)
        assert a == b

    def test_export_identity_replay_matches_run(self):
        from app.services.export_service import _apply_capex_opex_folds_from_identity
        pi = __import__("app.project_factories", fromlist=["x"]).create_generic_solar_reference()
        out = _apply_capex_opex_folds_from_identity(
            pi, "p", {"contingency_authority": {"capex_pct": 5.0, "opex_pct": None}})
        assert out.capex.contingencies.amount_keur == pytest.approx(
            0.05 * capex_basis_keur(pi.capex))
        # no authority captured => untouched
        assert _apply_capex_opex_folds_from_identity(pi, "p", {"capex_rows": []}) is pi


# ───────────────────── reference parity ─────────────────────
class TestReferenceParity:
    @pytest.mark.parametrize("kind", ["capex", "opex"])
    def test_protected_reference_rejects_authority(self, kind):
        from types import SimpleNamespace
        from app.v2.capex_commands import CapexProtectedReferenceError, set_contingency_percentage

        rec = SimpleNamespace(project_id="ref", project_origin="factory_template", is_readonly=True)
        with pytest.raises(CapexProtectedReferenceError):
            set_contingency_percentage(project_record=rec, user_id="u", kind=kind, pct=5.0,
                                       workbook_version="x", expected_content_hash="y")

    def test_reference_capex_and_opex_objects_untouched_without_authority(self):
        from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
        for factory in (create_generic_solar_reference, create_generic_wind_reference):
            pi = factory()
            assert apply_capex_contingency(pi.capex, None) is pi.capex
            assert apply_opex_contingency(pi.opex, None) is pi.opex


# ───────────────────── D. OPEX B.13 ─────────────────────
class TestOpexContingency:
    def _schedule(self, pi, years=5):
        from finco_core.opex.projections import opex_schedule_annual
        return opex_schedule_annual(pi, years)

    def test_percentage_is_period_by_period(self):
        from app.project_factories import create_generic_solar_reference
        pi = create_generic_solar_reference()
        fixed = dataclasses.replace(
            pi, opex=tuple(i for i in pi.opex if i.percentage_of_opex <= 0))
        base = self._schedule(fixed)
        for pct in (0.0, 5.0, 100.0):
            pi2 = dataclasses.replace(pi, opex=apply_opex_contingency(pi.opex, pct))
            sched = self._schedule(pi2)
            for year, total in sched.items():
                assert total == pytest.approx(base[year] * (1 + pct / 100.0))

    def test_none_leaves_reference_rule(self):
        from app.project_factories import create_generic_solar_reference
        pi = create_generic_solar_reference()
        assert apply_opex_contingency(pi.opex, None) is pi.opex

    def test_run_fold_uses_authority(self, solar_copy):
        from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
        from app.project_factories import create_generic_solar_reference
        _set_pct("cap-user", solar_copy, "opex", 10.0)
        pi = create_generic_solar_reference()
        out = apply_user_sub_lines_to_opex(pi.opex, project_id=solar_copy.project_id)
        pcts = [i.percentage_of_opex for i in out if i.percentage_of_opex > 0]
        assert pcts and all(math.isclose(p, 0.10) for p in pcts)

    def test_opex_lineage_keeps_period_series(self):
        from app.contingency_authority import opex_lineage
        lin = opex_lineage(pct=5.0, source="project", period_basis_keur=[100.0, 200.0],
                           period_amount_keur=[5.0, 10.0])
        d = lin.to_dict()
        assert d["period_basis_keur"] == [100.0, 200.0] and d["basis_mode"] == "SAME_PERIOD_OTHER_OPEX"
        assert opex_lineage(pct=5.0, source="project", period_basis_keur=None,
                            period_amount_keur=None).amount_keur is None


# ───────────────────── HTTP surface ─────────────────────
class TestContingencyRoute:
    def _client(self):
        import main_web
        from fastapi.testclient import TestClient
        from app.auth import COOKIE_NAME, create_session_token

        return (TestClient(main_web.app, raise_server_exceptions=True),
                {COOKIE_NAME: create_session_token(user_id="cap-user", username="admin")})

    def test_post_saves_then_sheet_renders_authority(self, solar_copy):
        from app.persistence.projects_repository import get_project_by_id
        client, cookies = self._client()
        wv, h = _hash("cap-user", solar_copy)
        r = client.post("/v2/capex/contingency", cookies=cookies, follow_redirects=False, data={
            "project": solar_copy.project_code, "kind": "capex", "contingency_pct": "5",
            "workbook_version": wv, "content_hash": h})
        assert r.status_code == 303, r.text
        assert read_authority(get_project_by_id(solar_copy.project_id).replay_metadata, "capex") == 5.0
        page = client.get(f"/v2/workbook?project={solar_copy.project_code}", cookies=cookies)
        assert 'data-testid="capex-contingency-authority"' in page.text
        assert "OTHER_ELIGIBLE_CAPEX" in page.text

    def test_invalid_pct_rejected_422(self, solar_copy):
        client, cookies = self._client()
        wv, h = _hash("cap-user", solar_copy)
        r = client.post("/v2/capex/contingency", cookies=cookies, follow_redirects=False, data={
            "project": solar_copy.project_code, "kind": "capex", "contingency_pct": "101",
            "workbook_version": wv, "content_hash": h})
        assert r.status_code == 422

    def test_stale_hash_conflict(self, solar_copy):
        client, cookies = self._client()
        wv, _ = _hash("cap-user", solar_copy)
        r = client.post("/v2/capex/contingency", cookies=cookies, follow_redirects=False, data={
            "project": solar_copy.project_code, "kind": "capex", "contingency_pct": "5",
            "workbook_version": wv, "content_hash": "stale"})
        assert r.status_code == 409
