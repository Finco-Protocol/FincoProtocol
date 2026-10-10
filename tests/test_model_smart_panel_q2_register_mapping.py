"""Q2 Correction B — canonical Assumption Register path <-> workbook row mapping (server side).

The register identifies assumptions by canonical engine path; workbook rows by registry
field id.  They are deliberately different strings.  The only proven bridge is the registry
``FieldSpec.engine_path`` (exact equality, single claimant).  No fuzzy matching.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.v2 import register_path_map as rpm


def _spec(field_id, engine_path):
    return SimpleNamespace(field_id=field_id, engine_path=engine_path)


def _fake_workbook(*specs):
    section = SimpleNamespace(fields=tuple(specs))
    sheet = SimpleNamespace(sections=(section,))
    return SimpleNamespace(sheets=(sheet,))


@pytest.fixture(autouse=True)
def _clear_cache():
    rpm._field_to_register_path.cache_clear()
    yield
    rpm._field_to_register_path.cache_clear()


def test_real_registry_path_differs_from_field_id_and_is_exact():
    assert rpm.register_path_for_field("project_setup.technical.p50_hours") == "technical.operating_hours_p50"
    assert rpm.register_path_for_field("project_setup.technical.capacity_mw") == "technical.capacity_mw"
    for fid, path in rpm._field_to_register_path().items():
        assert fid != path, "register_path == field_id would not prove the mapping layer"


def test_unknown_or_empty_field_has_no_mapping():
    assert rpm.register_path_for_field("") is None
    assert rpm.register_path_for_field(None) is None
    assert rpm.register_path_for_field("project_setup.technical.p50_hours.") is None
    assert rpm.register_path_for_field("p50_hours") is None  # no suffix matching


def test_ambiguous_claims_fail_closed(monkeypatch):
    import app.workbook.registry as reg
    monkeypatch.setattr(reg, "WORKBOOK", _fake_workbook(
        _spec("sheet.a.one", "x.shared"), _spec("sheet.b.two", "x.shared"),
        _spec("sheet.c.three", "x.unique"), _spec("sheet.d.none", None)))
    rpm._field_to_register_path.cache_clear()
    assert rpm.register_path_for_field("sheet.a.one") is None
    assert rpm.register_path_for_field("sheet.b.two") is None
    assert rpm.register_path_for_field("sheet.c.three") == "x.unique"
    assert rpm.register_path_for_field("sheet.d.none") is None


def _render_row(register_path, field_id="a.b.c"):
    env = Environment(loader=FileSystemLoader("app/templates/v2"), autoescape=select_autoescape(["html"]))
    tmpl = env.from_string(
        '{% from "partials/field_editor.html" import render_field %}'
        '{{ render_field(f, "P", "v", "h", project_editable=False) }}')
    f = dict(field_id=field_id, label="L", unit="", field_type="number", binding_label="bound",
             options=[], option_labels={}, value=1, display_value=1, required=False,
             min_value=None, max_value=None, step="any", help_text="", register_path=register_path)
    return tmpl.render(f=f)


def test_row_renders_escaped_register_path_beside_unchanged_field_id():
    out = _render_row('x.y"><script>alert(1)</script>')
    assert 'data-field-id="a.b.c"' in out
    assert "<script>alert(1)</script>" not in out
    assert 'data-register-path="x.y&#34;&gt;&lt;script&gt;' in out


def test_row_without_proven_mapping_has_no_attribute():
    assert "data-register-path" not in _render_row(None)
    assert 'data-field-id="a.b.c"' in _render_row(None)


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.meta_paths = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if "v2-field-row" in cls and "data-field-id" in a:
            self.rows.append((a["data-field-id"], a.get("data-register-path"), "v2-field-editable" in cls))
        if "data-sp-field-meta" in a:
            self.meta_paths.append(a.get("data-path"))


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "q2map.db"))
    db.init_db()


def _page(template, user_id="q2map"):
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    rec = create_reference_seeded_project(user_id=user_id, template_source=template,
                                          requested_name="Q2 Map", capacity_mw=40.0)
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
    r = TestClient(main_web.app).get(f"/v2/workbook?project={rec.project_code}", cookies=cookies)
    assert r.status_code == 200
    p = _Rows(); p.feed(r.text)
    return p


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_real_workbook_mapping_coverage(seeded_db, template):
    p = _page(template)
    meta = set(p.meta_paths)
    mapped = [(fid, path) for fid, path, _ in p.rows if path]
    paths = [path for _, path in mapped]
    navigable = [(fid, path) for fid, path in mapped if path in meta]
    print(f"[{template}] register paths={len(meta)} workbook rows={len(p.rows)} "
          f"rows with registry path claim={len(mapped)} navigable (claim is a register path)={len(navigable)} "
          f"unmapped register paths={len(meta - {pth for _, pth in navigable})}")
    assert len(meta) == 236
    assert len(navigable) >= 20
    assert len(paths) == len(set(paths)), "ambiguous: two rows claim one register path"
    for fid, path in mapped:
        assert fid != path
    ids = dict(mapped)
    assert ids["project_setup.technical.p50_hours"] == "technical.operating_hours_p50"
    assert ids["project_setup.technical.capacity_mw"] == "technical.capacity_mw"


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_reference_project_rows_remain_read_only(seeded_db, template):
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    cookies = {COOKIE_NAME: create_session_token(user_id="q2ref", username="admin")}
    r = TestClient(main_web.app).get(f"/v2/workbook?project={template}-reference", cookies=cookies)
    assert r.status_code == 200
    p = _Rows(); p.feed(r.text)
    assert p.rows, "reference workbook must render field rows"
    assert any(path for _, path, _ in p.rows), "mapping attribute is presentation-only and also present"
    assert not any(editable for _, _, editable in p.rows)
    assert not re.search(r'<input[^>]+class="[^"]*v2-field-input', r.text)
