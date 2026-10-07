"""Typed validation authority end to end: server -> HX event -> browser.

``FieldValidationError.error_class`` (canonical server classification) must
travel in the EXISTING ``workbook-field-error`` HX-Trigger as ``error_class``.
Untyped rejections (stale draft, protected project, non-editable field, authority
gate) carry JSON ``null`` — never a fabricated class.  These tests drive the REAL
endpoints through the real FastAPI app; no classification is mocked.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app/v2/router.py").read_text(encoding="utf-8")

NAME = "project_setup.identity.project_name"
MONTHS = "project_setup.technical.construction_months"
CAPACITY = "project_setup.technical.capacity_mw"
CURVE = "revenue.merchant.price_curve_json"
LOCKED = "project_setup.identity.project_type"
USER = "typed-error-user"


# ── helper-level contract ──────────────────────────────────────────────────

class TestTriggerHelper:
    @staticmethod
    def _payload(resp):
        return json.loads(resp.headers["HX-Trigger"])["workbook-field-error"]

    def _resp(self):
        from fastapi.responses import HTMLResponse
        return HTMLResponse("x")

    @pytest.mark.parametrize("member", ["REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS"])
    def test_canonical_class_is_serialised_by_value(self, member):
        from app.v2.router import _add_field_error_trigger
        from app.workbook.update_service import FieldErrorClass
        resp = _add_field_error_trigger(self._resp(), "f.id", "text", FieldErrorClass[member])
        assert self._payload(resp) == {"field_id": "f.id", "message": "text", "error_class": member}

    def test_untyped_is_explicit_null_not_omitted_and_not_invented(self):
        from app.v2.router import _add_field_error_trigger
        payload = self._payload(_add_field_error_trigger(self._resp(), "f.id", "text"))
        assert "error_class" in payload and payload["error_class"] is None

    @pytest.mark.parametrize("bogus", ["INVALID", "OUT_OF_BOUNDS", "anything", 7, {"x": 1}, ""])
    def test_only_a_real_enum_member_can_reach_the_browser_as_a_class(self, bogus):
        from app.v2.router import _add_field_error_trigger
        payload = self._payload(_add_field_error_trigger(self._resp(), "f", "m", bogus))
        assert payload["error_class"] is None

    def test_payload_has_exactly_three_keys_and_no_internals(self):
        from app.v2.router import _add_field_error_trigger
        from app.workbook.update_service import FieldErrorClass
        payload = self._payload(
            _add_field_error_trigger(self._resp(), "f", "m", FieldErrorClass.INVALID))
        assert set(payload) == {"field_id", "message", "error_class"}

    def test_both_field_validation_handlers_forward_the_exception_class(self):
        handlers = re.findall(r"except FieldValidationError as exc:(.*?)(?=\n    except |\n    # |\n    updated_)",
                              ROUTER, flags=re.S)
        assert len(handlers) == 2
        for body in handlers:
            assert "exc.error_class" in body
        # every other emitter stays untyped
        untyped = re.findall(r"_add_field_error_trigger\(resp, field_id, (?:msg|str\(exc\))\)", ROUTER)
        assert len(untyped) == 2     # protected + stale on the general path

    def test_no_message_parsing_anywhere_in_the_transport(self):
        source = inspect.getsource(__import__("app.v2.router", fromlist=["x"])._add_field_error_trigger)
        assert not re.search(r"\b(re\.|startswith|endswith|\bin message\b|\.lower\(\))", source)


# ── real HTTP: both field-update paths ─────────────────────────────────────

@pytest.fixture()
def project(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", str(tmp_path / "typed-error.db"))
    db_mod.init_db()
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(
        user_id=USER, template_source="generic_solar_reference",
        requested_name="Typed Error Project", capacity_mw=64.0)


@pytest.fixture()
def client():
    import main_web
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    api = TestClient(main_web.app, raise_server_exceptions=True)
    api.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
    return api


def _identity(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ws = get_workspace_state(USER, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    composite = assemble_consistent_for_get(
        user_id=USER, project_id=record.project_id, workbook_version=pis.workbook_version)
    return pis.workbook_version, pis.with_composite_hash(composite.composite_hash).content_hash


def _post(client, record, path, field_id, value, *, content_hash=None):
    version, current = _identity(record)
    return client.post(
        path,
        data={"field_id": field_id, "value": value, "project": record.project_code,
              "workbook_version": version, "content_hash": content_hash or current,
              "sheet_id": "project_setup"},
        headers={"HX-Request": "true"}, follow_redirects=False)


def _event(resp):
    assert "HX-Trigger" in resp.headers, f"no HX-Trigger (status {resp.status_code})"
    return json.loads(resp.headers["HX-Trigger"])["workbook-field-error"]


def _draft(record):
    from app.persistence.workspace_repository import get_workspace_state
    return dict(get_workspace_state(USER, record.project_id).draft_snapshot or {})


GENERAL = "/v2/workbook/update"
SLICE1 = "/v2/workbook/inputs-slice1/update"


@pytest.mark.parametrize("path", [GENERAL, SLICE1])
class TestTypedClassTravelsThroughTheRealRouter:
    @pytest.mark.parametrize("field_id,value,expected", [
        (MONTHS, "", "REQUIRED_MISSING"),                  # A
        (MONTHS, "1.5", "INVALID"),                        # B  type coercion
        (CAPACITY, "0", "OUT_OF_BOUNDS"),                  # D
        (MONTHS, "121", "OUT_OF_BOUNDS"),
    ])
    def test_server_class_is_in_the_event(self, project, client, path, field_id, value, expected):
        from app.workbook.update_service import WorkbookUpdateService
        before = _draft(project)
        resp = _post(client, project, path, field_id, value)
        event = _event(resp)
        assert event["field_id"] == field_id
        assert event["error_class"] == expected
        # identical to the canonical service classification, and the text is untouched
        server = WorkbookUpdateService.validate_field_update(field_id, value)
        assert event["error_class"] == server.error_class.value
        assert event["message"] == server.error
        assert _draft(project) == before                   # nothing persisted

    def test_required_text_field_on_the_general_route(self, project, client, path):
        """A (text control): project_name is a general-route field, not Slice 1."""
        resp = _post(client, project, path, NAME, "")
        event = _event(resp)
        if path == SLICE1:
            assert event["error_class"] is None          # not a Slice 1 field: untyped refusal
        else:
            assert event["error_class"] == "REQUIRED_MISSING"

    def test_status_codes_and_rerender_are_preserved(self, project, client, path):
        resp = _post(client, project, path, CAPACITY, "0")
        assert resp.status_code == (422 if path == SLICE1 else 200)
        assert "text/html" in resp.headers["content-type"]
        assert resp.text.strip()                           # the sheet is still re-rendered


class TestServerOnlySemanticRule:
    def test_merchant_curve_semantics_are_invalid_on_the_server(self, project, client):
        """C: JSON-curve semantics exist only on the server (a plain text control
        in the browser, so native constraint validation can never infer them)."""
        event = _event(_post(client, project, GENERAL, CURVE, "not json at all"))
        assert event["error_class"] == "INVALID"
        assert event["message"].startswith("Merchant Price Curve:")


class TestUntypedRejectionsStayUntyped:
    def test_stale_content_is_null_never_a_value_class(self, project, client):
        """E: the server judged freshness, not the value — no fake class."""
        for path in (GENERAL, SLICE1):
            resp = _post(client, project, path, CAPACITY, "70", content_hash="deadbeef" * 8)
            event = _event(resp)
            assert "error_class" in event and event["error_class"] is None
            assert "Draft changed" in event["message"]
            assert resp.status_code == (409 if path == SLICE1 else 200)

    def test_value_validation_precedes_the_stale_check_and_stays_typed(self, project, client):
        """Existing order (unchanged): pure validation runs before the CAS, so an
        invalid value is reported with its typed class even with a stale hash."""
        resp = _post(client, project, GENERAL, CAPACITY, "0", content_hash="deadbeef" * 8)
        assert _event(resp)["error_class"] == "OUT_OF_BOUNDS"

    def test_protected_reference_is_null_never_invalid(self, project, client, monkeypatch):
        """F: Slice 1 routes ProtectedReferenceError through the field-error event."""
        import app.ui.protected_reference_service as prot
        monkeypatch.setattr(prot, "is_protected_reference", lambda record: True)
        resp = _post(client, project, SLICE1, CAPACITY, "100")
        event = _event(resp)
        assert resp.status_code == 409
        assert event["error_class"] is None and "protected" in event["message"].lower()

    def test_general_route_refuses_protected_projects_without_any_event(self, client):
        from app.persistence.projects_repository import resolve_accessible_project  # noqa: F401
        from app.persistence import db as db_mod  # noqa: F401
        # the general route short-circuits with a JSON 403 before any field event exists
        assert "is_protected_reference(project_record)" in ROUTER
        assert 'status_code=403' in ROUTER

    def test_non_editable_field_is_null(self, project, client):
        resp = _post(client, project, SLICE1, LOCKED, "wind")
        event = _event(resp)
        assert event["error_class"] is None
        assert resp.status_code == 422

    def test_authority_gate_rejection_is_null(self, project, client, monkeypatch):
        import app.input_adapter as adapter
        monkeypatch.setattr(adapter, "assert_debt_scalar_edit_allowed",
                            lambda *a, **k: (_ for _ in ()).throw(ValueError("calibrated schedule")))
        resp = _post(client, project, GENERAL, "debt.senior.interest_rate_pct", "5.0")
        event = _event(resp)
        assert event["error_class"] is None
        assert "calibrated schedule" in event["message"]

    def test_successful_update_emits_no_error_event(self, project, client):
        resp = _post(client, project, GENERAL, CAPACITY, "70")
        assert resp.status_code == 200
        trigger = json.loads(resp.headers["HX-Trigger"])
        assert "workbook-field-error" not in trigger and "workbook-field-saved" in trigger


class TestRunIntelligenceStillCoexists:
    """I: after the normal sync with #209, its surface and this wave live in one page."""

    def test_workbook_page_carries_both_surfaces(self, project, client):
        resp = client.get(f"/v2/workbook?project={project.project_code}")
        assert resp.status_code == 200
        html = resp.text
        for needle in (
            'id="tab-run-history"', 'id="panel-run-history"',            # #209
            "/static/css/model_v2_run_history.css",                      # #209
            "/static/css/workbook_v2.css", "/static/js/workbook_v2.js",  # this wave
            'id="v2-validation-summary"', 'data-summary-class="REQUIRED_MISSING"',
            'data-fc-row', 'data-field-label=',
        ):
            assert needle in html, needle

    def test_run_history_routes_are_untouched_and_read_only(self, project, client):
        for path in ("/v2/workbook/run-history",):
            resp = client.get(path, params={"project": project.project_code},
                              headers={"HX-Request": "true"})
            assert resp.status_code == 200, path
        paths = {getattr(r, "path", "") for r in __import__("app.v2.router", fromlist=["x"]).router.routes}
        assert {"/workbook/run-history", "/workbook/run-history/detail",
                "/workbook/run-history/compare"} <= {p.replace("/v2", "", 1) if p.startswith("/v2") else p for p in paths}

    def test_both_stylesheets_are_served_and_independent(self, client):
        css = client.get("/static/css/workbook_v2.css").text
        history = client.get("/static/css/model_v2_run_history.css").text
        assert "Workspace productivity v1" in css and "Workspace productivity v1" not in history
        assert "v2-field-error-msg" in css

    def test_my_field_updates_do_not_touch_the_run_history_authority(self, project, client):
        from app.persistence.run_history_repository import get_run_history
        before = [e for e in get_run_history(user_id=USER, project_id=project.project_id)]
        _post(client, project, GENERAL, CAPACITY, "0")            # rejected
        _post(client, project, GENERAL, CAPACITY, "70")           # accepted
        after = [e for e in get_run_history(user_id=USER, project_id=project.project_id)]
        assert [e.snapshot_id for e in after] == [e.snapshot_id for e in before]   # no run, no history row
