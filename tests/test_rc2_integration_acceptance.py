"""RC-2 combined acceptance: Revenue V2/V3, Developer Economics, two-driver Sensitivity and Radar R3 together.

Everything runs through the existing canonical project runner and engines; no figure is computed here.
Revenue V3 is exercised only under the explicit test-only activation fixture (production stays closed).
"""

from tests.run_clone_csrf import post_valid_csrf
import copy
import json
import re

import pytest

from tests.revenue_v3_cases import book
from tests.test_developer_economics_persistence_v1 import OWNER, Flow, _doc, _fc, _form, _tokens, env  # noqa: F401
from tests.test_wf07_revenue_multistream import contracts
from tests.test_wf07_revenue_workspace import contract_tokens

DEV_SAVE = "/v2/developer-decision/configuration"
REV_SAVE = "/v2/workbook/revenue/contracts"
MATRIX = "/v2/workbook/sensitivity/matrix/run"


def _pi(flow):
    from app.workbook.service import WorkbookService
    return WorkbookService.build_draft_input_set_from_workspace(flow.ws()).to_projectinputs()


def _save_revenue(flow, payload, **extra):
    page = flow.env.client.get("/v2/workbook", params=flow.project).text
    return flow.env.client.post(REV_SAVE, headers={"HX-Request": "true"}, data={
        **flow.project, **contract_tokens(page), "contracts": json.dumps(payload), **extra})


@pytest.fixture
def v3_candidate(monkeypatch):
    from domain.revenue import advanced_products
    monkeypatch.setattr(advanced_products, "ACTIVATION_ENABLED", True)     # test-only, restored on exit
    yield advanced_products


# 1 ─ legacy parity: every new feature disabled/absent is bit-exact neutral
@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_all_new_features_disabled_leave_legacy_inputs_and_run_payload_unchanged(env, kind):
    from app.input_adapter import build_projectinputs_from_snapshot
    flow = Flow(env, kind)
    snapshot = dict(flow.ws().draft_snapshot)
    plain = build_projectinputs_from_snapshot(dict(snapshot))
    with_disabled = build_projectinputs_from_snapshot({**snapshot, "developer_economics_json": json.dumps(_doc(_fc(flow.record), enabled=False))})
    assert plain == with_disabled and plain.development_economics is None
    summary = flow.run()
    for key in ("developer_economics", "revenue_multistream_audit", "investor_agreement"):
        assert key not in summary
    from domain.revenue import advanced_products
    assert advanced_products.ACTIVATION_ENABLED is False                  # production activation stays closed


# 2/5/6/12 ─ Revenue V2 + Developer coexist; Save -> STALE -> Run -> CURRENT; immutable history; security
@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_revenue_v2_and_developer_coexist_with_stale_current_immutable_history_and_denials(env, kind):
    from app.persistence.run_history_repository import get_run_history
    flow = Flow(env, kind)
    pi = _pi(flow)
    v2 = contracts(pi, kind, price=95, merchant_price=90, strike=100)
    assert _save_revenue(flow, v2).status_code == 200
    assert flow.save(_doc(_fc(flow.record))).status_code == 303
    assert "STALE" in flow.page() or "NOT RUN" in flow.page()
    first = flow.run()
    assert first["revenue_multistream_audit"] and first["developer_economics"]["run_binding"]["snapshot_id"] == flow.ws().last_runtime_snapshot_id
    assert "CURRENT" in flow.page()
    history = get_run_history(OWNER, flow.record.project_id)
    frozen = copy.deepcopy(history[0].runtime_summary)
    # later edits to BOTH inputs never change the committed Run, and both turn the Last Run STALE
    changed = copy.deepcopy(v2)
    changed["streams"][0]["price_eur_mwh"] = 110
    assert _save_revenue(flow, changed).status_code == 200
    assert flow.save(_doc(_fc(flow.record), developer_fee_value=777.0)).status_code == 303
    assert "STALE" in flow.page()
    after = get_run_history(OWNER, flow.record.project_id)
    assert [h.history_id for h in after] == [h.history_id for h in history] and after[0].runtime_summary == frozen
    # security: stale CAS, missing CSRF and a foreign owner are rejected on BOTH writers, with no writes
    before = copy.deepcopy(flow.ws().draft_snapshot)
    stale = {**flow.project, **contract_tokens(env.client.get("/v2/workbook", params=flow.project).text), "contracts": json.dumps(v2)}
    stale["content_hash"] = "0" * 64
    assert env.client.post(REV_SAVE, headers={"HX-Request": "true"}, data=stale).status_code == 409
    assert env.client.post(REV_SAVE, data={**flow.project, "contracts": json.dumps(v2)}).status_code == 403
    form = _form(_doc(_fc(flow.record)), flow.page(), flow.record)
    assert env.client.post(DEV_SAVE, data={**form, "csrf_token": "x"}).status_code == 403
    assert env.client.post(DEV_SAVE, data={**form, "content_hash": "0" * 64}, follow_redirects=False).status_code == 409
    assert flow.ws().draft_snapshot == before


# 3 ─ Revenue V3 candidate (explicit test-only activation) composes with Developer Economics
def test_revenue_v3_candidate_composes_with_developer_economics_only_under_test_activation(env, v3_candidate):
    from app.model_v2.developer_evidence import read_committed_evidence
    flow = Flow(env, "solar")
    raw, _ = book(_pi(flow), "solar")
    assert _save_revenue(flow, raw).status_code == 200
    assert flow.save(_doc(_fc(flow.record))).status_code == 303
    summary = flow.run()
    assert summary["revenue_multistream_audit"][0]["products"]
    evidence = read_committed_evidence(summary)
    assert evidence is not None and evidence["developer_fee_keur"] == 300.0


def test_revenue_v3_is_release_closed_without_the_test_activation(env):
    flow = Flow(env, "solar")
    raw, _ = book(_pi(flow), "solar")
    from domain.revenue import advanced_products
    assert advanced_products.ACTIVATION_ENABLED is False
    r = _save_revenue(flow, raw)
    assert r.status_code != 200 or "RELEASE_CLOSED" in r.text
    assert "multistream" not in json.dumps({k: v for k, v in flow.ws().draft_snapshot.items() if k == "rev_multistream_config_json" and v})


# 4/7 ─ base and child scenarios resolve the right revenue AND developer input; M3 reads the intended scenario
def test_child_scenario_resolves_its_own_revenue_and_developer_inputs_and_matrix_reads_it_without_writing(env):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import get_scenario, list_scenarios
    from app.model_v2.developer_evidence import read_committed_evidence
    flow = Flow(env, "solar")
    v2 = contracts(_pi(flow), "solar", price=95, merchant_price=90, strike=100)
    assert _save_revenue(flow, v2).status_code == 200
    assert flow.save(_doc(_fc(flow.record), developer_fee_value=100.0)).status_code == 303
    base = flow.run()
    assert env.client.post("/v2/workbook/scenarios/create", data={**flow.project, "scenario_name": "Alt"}).status_code == 200
    sc = next(s for s in list_scenarios(OWNER, flow.record.project_id) if not s.is_base_case)
    assert env.client.post("/v2/workbook/scenarios/select", data={**flow.project, "scenario_id": sc.scenario_id}).status_code == 200
    alt_v2 = copy.deepcopy(v2)
    alt_v2["streams"][0]["price_eur_mwh"] = 105
    assert _save_revenue(flow, alt_v2).status_code == 200
    assert flow.save(_doc(_fc(flow.record), developer_fee_value=250.0)).status_code == 303
    overrides = get_scenario(sc.scenario_id, OWNER).overrides
    assert json.loads(overrides["rev_multistream_config_json"]) == alt_v2
    assert json.loads(overrides["developer_economics_json"])["developer_fee_value"] == 250.0
    child = flow.run()
    assert child["total_revenue_keur"] > base["total_revenue_keur"]
    assert read_committed_evidence(child)["developer_fee_keur"] == 250.0
    assert read_committed_evidence(base)["developer_fee_keur"] == 100.0
    # M3: read-only matrix over the SELECTED scenario; nothing persisted, no Run History entry
    ws0, history0 = flow.ws(), [h.history_id for h in get_run_history(OWNER, flow.record.project_id)]
    r = env.client.post(MATRIX, data={**flow.project, "scenario_id": sc.scenario_id, "driver_a": "capex", "driver_b": "opex",
                                      "metric": "project_irr", "levels_a": "-5,0,5", "levels_b": "-5,0,5"})
    assert r.status_code == 200, r.text[:400]
    ws1 = flow.ws()
    for name in ("draft_snapshot", "last_runtime_summary", "last_runtime_snapshot_id", "active_scenario_id", "dirty"):
        assert getattr(ws1, name, None) == getattr(ws0, name, None), name
    assert [h.history_id for h in get_run_history(OWNER, flow.record.project_id)] == history0
    assert 'data-state="CURRENT"' not in r.text


# 9 ─ a failed combined financial Run commits nothing
def test_failed_combined_run_commits_nothing(env, monkeypatch):
    from app.persistence.run_history_repository import get_run_history
    flow = Flow(env, "solar")
    assert _save_revenue(flow, contracts(_pi(flow), "solar", price=95, merchant_price=90, strike=100)).status_code == 200
    assert flow.save(_doc(_fc(flow.record))).status_code == 303
    summary, count = copy.deepcopy(flow.ws().last_runtime_summary), len(get_run_history(OWNER, flow.record.project_id))
    import app.api.project_runner as runner
    monkeypatch.setattr(runner, "run_project", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    wb = env.client.get("/v2/workbook", params=flow.project)
    post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data={**flow.project, **_tokens(wb.text)})
    assert flow.ws().last_runtime_summary == summary and flow.ws().dirty
    assert len(get_run_history(OWNER, flow.record.project_id)) == count


# 10/11 ─ Radar stays separate from the Model, and historical Deepstate evidence is never a current quote
def test_radar_r3_and_model_code_do_not_import_each_other():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    def imports(path):
        names = set()
        for node in ast.walk(ast.parse((root / path).read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        return names
    radar = imports("app/crypto_terminal/deepstate_composition.py")
    assert not [m for m in radar if m.startswith(("app.v2", "app.workbook", "app.model_v2", "app.api.project_runner",
                                                  "financial_engine", "finco_core", "domain"))]
    for model in ("app/workbook/developer_economics_service.py", "app/workbook/developer_economics_config.py",
                  "app/model_v2/developer_evidence.py", "app/v2/developer_committed_projection.py",
                  "app/services/sensitivity_matrix.py", "domain/revenue/advanced_products.py"):
        assert not [m for m in imports(model) if m.startswith(("app.crypto_terminal", "finco_radar"))], model


def test_historical_deepstate_context_is_never_a_current_or_executable_quote():
    from tests.test_radar_r3_deepstate_composition import _fill, _normalized, _read, _rlive, BLOCK_TIME, store as _store  # noqa: F401
    from datetime import timedelta
    import tempfile, os
    from finco_radar.venues.store import VenueMarketStore
    with tempfile.TemporaryDirectory() as tmp:
        store = VenueMarketStore(os.path.join(tmp, "v.db"))
        store.append_observation(_normalized())
        store.append_observation(_rlive(BLOCK_TIME + timedelta(seconds=10)))
        result = _read(store)
        assert result.current_cross_venue_state == "UNAVAILABLE"
        assert all(row.current_market_state == "UNAVAILABLE" for row in result.evidence)


def test_deepstate_window_read_is_bounded_by_escalating_spans():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.crypto_terminal import deepstate_composition as d
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    calls = []
    def rows(count):
        return [SimpleNamespace(collected_at=(now - timedelta(minutes=i)).isoformat()) for i in range(count)]
    class Store:
        def __init__(self, count): self.count = count
        def get_window_for_identity(self, *a, since, until, **k):
            calls.append((until - since))
            return rows(self.count)
    busy = d._recent_deepstate_rows(Store(500), now - d.HISTORY_WINDOW, now)
    assert len(busy) == d.MAX_HISTORICAL_FILLS and calls == [timedelta(days=1)]        # stopped after the first, smallest read
    calls.clear()
    sparse = d._recent_deepstate_rows(Store(3), now - d.HISTORY_WINDOW, now)
    assert len(sparse) == 3 and calls == [timedelta(days=1), timedelta(days=7), d.HISTORY_WINDOW]


# ───────────── M3 read-only boundary (reviewer-confirmed: no CSRF on this authenticated analysis POST) ─────────────

M3_FILES = ("app/v2/sensitivity_matrix_router.py", "app/services/sensitivity_matrix.py", "app/v2/sensitivity_matrix_projection.py")
_FORBIDDEN_MODULES = ("app.persistence.run_history_repository", "app.workbook.update_service", "app.workbook.revenue_contracts_service",
                      "app.workbook.investor_agreement_service", "app.workbook.developer_economics_service",
                      "app.persistence.projects_repository_writes")
_WRITE_CALL = re.compile(r"^(save|commit|append|update|delete|insert|create|set|write|persist|promote|duplicate|archive|restore)_|^v2_atomic_|apply_.*update")
_ALLOWED_REPOSITORY_NAMES = {"get_workspace_state", "get_scenario", "resolve_active_scenario_runtime_snapshot", "resolve_accessible_project"}


def _m3_ast(path):
    import ast
    from pathlib import Path
    return ast.parse((Path(__file__).resolve().parent.parent / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", M3_FILES)
def test_m3_has_no_persistence_writer_import_or_call(path):
    import ast
    tree = _m3_ast(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in _FORBIDDEN_MODULES, (path, node.module)
            if node.module.startswith(("app.persistence", "app.workbook")) and node.module != "app.workbook.service":
                for alias in node.names:
                    assert alias.name in _ALLOWED_REPOSITORY_NAMES | {"SNAPSHOT_KEY", "assert_materialized_fee_authority",
                                                                      "apply_state", "WorkbookIdentityError"} or alias.name.isupper(), (path, alias.name)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            assert not _WRITE_CALL.search(name) or name in {"apply_state", "apply_user_sub_lines_replacing_base", "apply_user_sub_lines_to_opex",
                                                           "_apply_shock", "_apply_fmt"}, (path, name)


def test_m3_exposes_exactly_one_post_route_with_bounded_admission_and_no_other_verb():
    import ast
    tree = _m3_ast("app/v2/sensitivity_matrix_router.py")
    verbs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.value.__class__ is ast.Name \
                        and decorator.func.value.id == "router":
                    verbs.append((decorator.func.attr, decorator.args[0].value))
    assert sorted(verbs) == [("get", verbs[0][1]), ("post", "/workbook/sensitivity/matrix/run")] or \
        [v for v in verbs if v[0] != "get"] == [("post", "/workbook/sensitivity/matrix/run")]
    source = ast.unparse(tree)
    assert source.count("run_model_process(") == 1                      # one bounded executor submission per request
    assert "ModelExecutionBusy" in source and "429" in source and "Retry-After" in source
    assert "sensitivity_grid_size_error" in source and "MAX_CELLS" in source
    from app.v2 import sensitivity_matrix_projection as proj
    assert proj.MAX_CELLS <= 26


def test_m3_post_is_session_authenticated_owner_scoped_and_never_commits(env):
    from app.persistence.run_history_repository import get_run_history
    flow = Flow(env, "solar")
    flow.run()
    ws0, history0 = flow.ws(), [h.history_id for h in get_run_history(OWNER, flow.record.project_id)]
    ok = env.client.post(MATRIX, data={**flow.project, "driver_a": "capex", "driver_b": "opex", "metric": "project_irr"})
    assert ok.status_code == 200 and 'data-state="CURRENT"' not in ok.text
    assert ok.headers.get("cache-control", "").lower().startswith("no-store")
    ws1 = flow.ws()
    for name in ("draft_snapshot", "last_runtime_summary", "last_runtime_snapshot_id", "last_runtime_composite_hash", "dirty"):
        assert getattr(ws1, name, None) == getattr(ws0, name, None), name
    assert [h.history_id for h in get_run_history(OWNER, flow.record.project_id)] == history0
    # a CSRF token is NOT required (reviewer decision) but authentication and ownership are
    env.client.cookies.clear()
    assert env.client.post(MATRIX, data={**flow.project, "driver_a": "capex", "driver_b": "opex", "metric": "project_irr"}).status_code == 401


def test_production_never_supplies_a_usdg_usd_normalization_policy():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for path in ("app/crypto_terminal/tokenized_read.py", "app/api/v1/crypto_router.py"):
        for node in ast.walk(ast.parse((root / path).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "build_deepstate_historical_context":
                assert "normalization_policy" not in {k.arg for k in node.keywords}, path
