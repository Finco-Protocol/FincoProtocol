"""EV Charging V1 — rendered-form acceptance (Z.10–Z.15).

Uses the exact PR #86 working-copy contract: reference read-only, working-copy
child rows editable over HTMX with fresh content_hash/row_version on every
mutation, reload persistence, and fail-closed direct mutation on the canonical
reference. The Z.15 journey is exercised at the HTTP level (technology labels,
charging terminology); pixel overflow is covered by the CI browser ring.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest


# ── helpers (mirrors tests/test_correction_a_required_gates.py) ──────────────

class _RenderedFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self._form = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "form":
            self._form = {"action": data.get("hx-post"), "values": {}}
        elif tag == "input" and self._form is not None and data.get("name"):
            self._form["values"][data["name"]] = data.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None


def _rendered_form_values(html: str, action: str, sub_line_id: str) -> dict[str, str]:
    parser = _RenderedFormParser()
    parser.feed(html)
    for form in parser.forms:
        values = form["values"]
        if form["action"] == action and values.get("sub_line_id") == sub_line_id:
            return dict(values)
    raise AssertionError(f"Rendered form {action!r} for {sub_line_id!r} not found")


@pytest.fixture()
def ev_db(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    db_path = str(tmp_path / "ev-acceptance.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    yield db_mod


@pytest.fixture()
def ev_working_copy(ev_db):
    """Admin user + an EV Charging working copy seeded at 8 MW (Z.10)."""
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project

    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="ev-acceptance-user",
        template_source="generic_ev_charging_reference",
        requested_name="EV Acceptance 8MW",
        capacity_mw=8.0,
    )
    return record


def _cookies():
    from app.auth import COOKIE_NAME, create_session_token
    return {COOKIE_NAME: create_session_token(user_id="ev-acceptance-user", username="admin")}


def _client():
    from fastapi.testclient import TestClient
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=True)


def _build_pis_with_hash(user_id: str, record):
    """ProjectInputSet with the current composite content_hash (PR #86 contract)."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    ws = get_workspace_state(user_id, record.project_id)
    assert ws is not None, "Workspace must exist for seeded project"
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    identity = assemble_consistent_for_get(
        user_id=user_id,
        project_id=record.project_id,
        workbook_version=pis.workbook_version,
    )
    return pis.with_composite_hash(identity.composite_hash)


# ── Z.10 working-copy scaling ────────────────────────────────────────────────

def test_ev_working_copy_scales_to_8mw(ev_working_copy):
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state("ev-acceptance-user", ev_working_copy.project_id)
    snapshot = ws.draft_snapshot
    assert float(snapshot["capacity_mw"]) == 8.0
    assert float(snapshot["total_capex_keur"]) == pytest.approx(14_400.0)
    assert ev_working_copy.project_type == "EV Charging"
    assert ev_working_copy.template_source == "generic_ev_charging_reference"


def test_ev_working_copy_runnable_with_scaled_economics(ev_working_copy):
    """The working copy runs through the canonical resolver and produces the
    scaled EV economics exactly (Z.10 + Z.9)."""
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    from app import ev_charging_economics as ev
    from app.services.production_waterfall_seam import execute_production_waterfall

    ws = get_workspace_state("ev-acceptance-user", ev_working_copy.project_id)
    pi = build_projectinputs_from_snapshot(dict(ws.draft_snapshot))
    assert pi.technical.capacity_mw == 8.0
    # stabilized charging revenue: 8 MW × 2000 h × 400 EUR/MWh / 1000 = 6,400 kEUR
    # (pre-escalation reconciliation is validated in the factory tests; here we
    # run the engine and check the cumulative revenue against the authority).
    result = execute_production_waterfall(pi).result
    authority_total = sum(ev.charging_revenue_keur(8.0, y) for y in range(1, 21))
    assert getattr(result, "total_revenue_keur") == pytest.approx(authority_total, rel=1e-6)
    # grid purchase at 8 MW stabilized: 16,000 / 0.94 MWh × 120 EUR/MWh
    assert ev.grid_energy_purchased_mwh(8.0, 3) == pytest.approx(16_000.0 / 0.94, rel=1e-12)


# ── Z.15 journey (HTTP level) ────────────────────────────────────────────────

def test_ev_journey_library_to_workbook_terminology(ev_db):
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    client = _client()
    cookies = _cookies()

    library = client.get("/library", cookies=cookies)
    assert library.status_code == 200
    assert "Generic EV Charging Hub Reference" in library.text
    assert 'data-testid="clone-generic_ev_charging_reference-reference"' in library.text

    page = client.get(
        "/v2/workbook?project=generic_ev_charging_reference-reference", cookies=cookies
    )
    assert page.status_code == 200
    assert "EV Charging" in page.text
    assert "Installed Charging Capacity (MW)" in page.text
    # Correction B: the editable EV driver section is the price authority.
    assert "Charging Price" in page.text
    assert "Equivalent Full-Load Hours — Y1" in page.text
    assert "Charging Efficiency" in page.text
    assert "Energy Delivered" in page.text
    assert "Grid Energy Purchased" in page.text
    # renewable/PPA terminology must not surface as EV economic controls
    assert "P50 Operating Hours" not in page.text
    assert "PPA Escalation Index" not in page.text
    assert "Base Tariff" not in page.text
    assert "Merchant Balancing" not in page.text


# ── Z.11 CAPEX rendered-form edits ───────────────────────────────────────────

def test_ev_capex_rendered_form_first_and_second_htmx_edit(ev_working_copy):
    from app.auth import COOKIE_NAME  # noqa: F401
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_capex_vm_ctx

    client = _client()
    cookies = _cookies()
    page = client.get(
        f"/v2/workbook?project={ev_working_copy.project_code}", cookies=cookies
    )
    assert page.status_code == 200

    capex_before = get_active_sub_lines_for_project(ev_working_copy.project_id)
    assert capex_before, "EV working copy must seed CAPEX detail lines"
    capex_total_before = sum(l.amount_keur for l in capex_before)
    line = next(l for l in capex_before if l.amount_keur > 0)
    form = _rendered_form_values(page.text, "/v2/capex/line/update", line.sub_line_id)
    assert {"project", "sub_line_id", "row_version", "workbook_version",
            "content_hash", "label", "amount_keur"}.issubset(form)

    first_delta = 17.0
    form["amount_keur"] = str(line.amount_keur + first_delta)
    resp = client.post("/v2/capex/line/update", data=form, cookies=cookies,
                       headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:500]
    after = get_active_sub_lines_for_project(ev_working_copy.project_id)
    changed = next(l for l in after if l.sub_line_id == line.sub_line_id)
    assert changed.amount_keur == pytest.approx(line.amount_keur + first_delta)
    assert changed.source == "user_override"
    assert sum(l.amount_keur for l in after) == pytest.approx(capex_total_before + first_delta)

    # Second edit through the freshly rendered form (fresh hash + row version).
    second_form = _rendered_form_values(resp.text, "/v2/capex/line/update", line.sub_line_id)
    assert second_form["row_version"] == changed.updated_at
    assert second_form["content_hash"] != form["content_hash"]
    second_delta = 11.0
    second_form["amount_keur"] = str(line.amount_keur + first_delta + second_delta)
    resp2 = client.post("/v2/capex/line/update", data=second_form, cookies=cookies,
                        headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp2.status_code == 200, resp2.text[:500]
    after2 = get_active_sub_lines_for_project(ev_working_copy.project_id)
    changed2 = next(l for l in after2 if l.sub_line_id == line.sub_line_id)
    assert changed2.amount_keur == pytest.approx(line.amount_keur + first_delta + second_delta)

    # Reload: the persisted sheet rebuilds the totals from the DB rows.
    ws = get_workspace_state("ev-acceptance-user", ev_working_copy.project_id)
    vm = _build_capex_vm_ctx(
        ev_working_copy, _build_pis_with_hash("ev-acceptance-user", ev_working_copy),
        ws, workspace_owner="ev-acceptance-user",
    )["capex_vm"]
    assert vm.total_capex_keur == pytest.approx(14_400.0 + first_delta + second_delta)


# ── Z.12 OPEX rendered-form edits (non-derived row) ──────────────────────────

def test_ev_opex_rendered_form_edits(ev_working_copy):
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as get_opex

    client = _client()
    cookies = _cookies()
    page = client.get(
        f"/v2/workbook?project={ev_working_copy.project_code}", cookies=cookies
    )
    assert page.status_code == 200

    opex_before = get_opex(ev_working_copy.project_id)
    assert opex_before, "EV working copy must seed OPEX detail lines"
    # non-derived row: any seeded OPEX line (B.08 electricity is never seeded)
    opex_line = next(l for l in opex_before if l.amount_keur > 0)
    assert opex_line.parent_group_code != "B.08"
    opex_total_before = sum(l.amount_keur for l in opex_before)

    form = _rendered_form_values(page.text, "/v2/opex/line/update", opex_line.sub_line_id)
    assert {"project", "sub_line_id", "row_version", "workbook_version",
            "content_hash", "label", "amount_keur"}.issubset(form)
    form["amount_keur"] = str(opex_line.amount_keur + 5.0)
    resp = client.post("/v2/opex/line/update", data=form, cookies=cookies,
                       headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:500]
    after = get_opex(ev_working_copy.project_id)
    changed = next(l for l in after if l.sub_line_id == opex_line.sub_line_id)
    assert changed.amount_keur == pytest.approx(opex_line.amount_keur + 5.0)

    second_form = _rendered_form_values(resp.text, "/v2/opex/line/update", opex_line.sub_line_id)
    assert second_form["content_hash"] != form["content_hash"]
    second_form["amount_keur"] = str(opex_line.amount_keur + 9.0)
    resp2 = client.post("/v2/opex/line/update", data=second_form, cookies=cookies,
                        headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp2.status_code == 200, resp2.text[:500]
    after2 = get_opex(ev_working_copy.project_id)
    changed2 = next(l for l in after2 if l.sub_line_id == opex_line.sub_line_id)
    assert changed2.amount_keur == pytest.approx(opex_line.amount_keur + 9.0)
    assert sum(l.amount_keur for l in after2) == pytest.approx(opex_total_before + 9.0)


# ── Z.13 derived electricity never double-counts ─────────────────────────────

def test_ev_derived_electricity_not_seedable_or_duplicated(ev_working_copy):
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as get_opex
    lines = get_opex(ev_working_copy.project_id)
    b08 = [l for l in lines if l.parent_group_code == "B.08"]
    assert not b08, (
        "the derived B.08 electricity line must never be seeded as an editable sub-line"
    )
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state("ev-acceptance-user", ev_working_copy.project_id)
    pi = build_projectinputs_from_snapshot(dict(ws.draft_snapshot))
    electricity = [i for i in pi.opex if i.name == "Electricity Procurement"]
    assert len(electricity) == 1, "exactly one electricity authority in the runtime vector"


# ── Z.14 reference protection ────────────────────────────────────────────────

def test_ev_canonical_reference_readonly_fails_closed(ev_db):
    from app.persistence.projects_repository import get_project_by_code
    from app.v2.capex_commands import CapexProtectedReferenceError, add_capex_line
    from app.workbook.registry import WORKBOOK
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    reference = get_project_by_code("__reference__", "generic_ev_charging_reference-reference")
    assert reference is not None and reference.is_readonly
    client = _client()
    page = client.get(
        "/v2/workbook?project=generic_ev_charging_reference-reference", cookies=_cookies()
    )
    assert page.status_code == 200
    assert "Reference project — create a working copy to edit." in page.text
    assert 'hx-post="/v2/capex/line/update"' not in page.text
    with pytest.raises(CapexProtectedReferenceError):
        add_capex_line(
            project_record=reference, user_id="__reference__", label="Rejected",
            parent_category_code="C.01", amount_keur=1.0,
            workbook_version=WORKBOOK.version, expected_content_hash="not-used",
        )
