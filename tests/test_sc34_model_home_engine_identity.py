"""SC-03 on Model Home: engine identity is shown as its own fact; the list still never classifies CURRENT/STALE."""
from types import SimpleNamespace

from app.library.model_home import build_recent_project_rows


def record(code):
    return SimpleNamespace(project_id=code, project_code=code, project_name=code, project_type="solar", project_role="working_copy", updated_at="2026-10-01")


def ws(**kw):
    return SimpleNamespace(last_runtime_at="2026-10-02T10:00:00", **kw)


def test_engine_currency_on_recent_rows(monkeypatch):
    rows = build_recent_project_rows(
        [record("a"), record("b"), record("c"), record("d")],
        {"a": ws(last_runtime_identity={"engine_version": "clean_senior_debt_v0"}),
         "b": ws(last_runtime_identity={"engine_version": "older"}),
         "c": ws(last_runtime_identity={}), "d": None})
    by = {r.project_code: r for r in rows}
    assert by["a"].engine_currency == "CURRENT_ENGINE"
    assert by["b"].engine_currency == "ENGINE_SUPERSEDED"
    assert by["c"].engine_currency == "ENGINE_IDENTITY_UNKNOWN"
    assert by["d"].has_last_run is False and by["d"].engine_currency == ""     # no Run: no engine claim


def test_rows_remain_constructible_without_the_new_field():
    from app.library.model_home import RecentProjectRow
    row = RecentProjectRow("c", "n", "solar", True, None, False, None)
    assert row.engine_currency == ""
