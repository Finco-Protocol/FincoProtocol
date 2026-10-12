"""F3.6 Capital Stack projection: labels come from persisted backend state; nothing is calculated."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.v2 import capital_stack_projection as cs
from app.workbook import multisenior_config as config
from tests.test_model_financing_f3_workspace import case, state


class _Fresh:
    def __init__(self, value):
        self.state = type("S", (), {"value": value})()


def _view(*, active=False, saved=True, runtime=None):
    pi, _ = case()
    raw = state(active=active) if saved else None
    return config.build_view(pi, raw, "base", runtime, owner_id="o", project_id="p")


def test_unsaved_default_is_draft_never_executable():
    stack = cs.build_capital_stack(_view(saved=False), _Fresh("NOT_RUN"))
    assert stack["status"] == cs.DRAFT and len(stack["rows"]) == 2
    assert all(r["status"] == cs.DRAFT and not r["executable"] for r in stack["rows"])
    assert stack["last_run"] is None and stack["last_run_label"] == "NOT RUN"


def test_saved_proposal_is_not_active_and_shows_no_last_run_results():
    runtime = {"financing_evidence": {"facility_schedules": [{"instrument_id": "x"}]}}
    stack = cs.build_capital_stack(_view(saved=True, active=False, runtime=runtime), _Fresh("STALE"))
    assert stack["status"] == cs.SAVED and not any(r["executable"] for r in stack["rows"])
    assert stack["last_run"] is None            # a proposal is never presented as calculated financing
    assert not stack["last_run_is_current"] and "STALE" in stack["last_run_label"]


def test_active_state_comes_from_digest_bound_activation():
    stack = cs.build_capital_stack(_view(active=True), _Fresh("CURRENT"))
    assert stack["status"] == cs.ACTIVE and all(r["executable"] for r in stack["rows"])
    assert stack["last_run_is_current"]


def test_working_totals_are_sums_of_typed_inputs_and_reconcile_flag():
    stack = cs.build_capital_stack(_view(), None)
    w = stack["working"]
    assert w["facility_count"] == 2 and w["junior_commitments_keur"] == 0.0
    assert w["senior_commitments_keur"] == pytest.approx(sum(r["commitment_keur"] for r in stack["rows"]))
    assert w["reconciled"] == all(abs(r["draws_total_keur"] - r["commitment_keur"]) < 1e-6 for r in stack["rows"])


def test_unsupported_structures_are_labelled_and_carry_no_amount():
    stack = cs.build_capital_stack(_view(), None)
    names = " ".join(u["name"] for u in stack["unsupported"])
    assert "Junior" in names and "Mezzanine" in names and "Floating" in names
    assert all(u["status"] == cs.UNSUPPORTED and set(u) == {"name", "reason", "status"} for u in stack["unsupported"])


def test_unavailable_view_is_passed_through():
    assert cs.build_capital_stack({"available": False, "reason": "r"}, None) == {"available": False, "reason": "r"}


def test_projection_imports_no_engine_or_writer():
    tree = ast.parse(Path(cs.__file__).read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in mods if m.startswith(("financial_engine", "finco_core", "app.persistence"))]


def test_junior_activation_stays_closed_when_the_f35_contracts_exist():
    if not Path("app/workbook/junior_debt_config.py").exists():      # F3.5 not on this base yet
        pytest.skip("F3.5-A is not on this branch")
    from app.workbook import junior_debt_config
    assert junior_debt_config.ACTIVATION_ENABLED is False


def _junior_view():
    import json
    from dataclasses import replace
    from finco_core.inputs.financing_instruments import FinancingCollection, InstrumentType
    pi, _ = case()
    senior, junior = pi.financing_collection.instruments
    junior = replace(junior, instrument_type=InstrumentType.JUNIOR_DEBT, seniority_rank=2, fees=(), name="Junior Debt",
                     commitment_keur=500.0,
                     drawdowns=(replace(junior.drawdowns[0], amount_keur=500.0),))
    raw = state(collection=FinancingCollection((senior, junior)))
    return config.build_view(pi, raw, "base", None, owner_id="o", project_id="p"), junior


def test_junior_proposal_row_is_read_only_non_executable_with_closed_activation():
    view, junior = _junior_view()
    stack = cs.build_capital_stack(view, _Fresh("NOT_RUN"))
    row = next(r for r in stack["rows"] if r["junior"])
    assert row["type"] == "Junior term loan" and not row["editable"] and not row["executable"]
    assert row["status"] == cs.SAVED and "Activation closed" in (row["readiness"] or "")
    assert stack["working"]["junior_commitments_keur"] == 500.0 and stack["working"]["junior_present"]
    assert stack["junior_activation_closed"] is True and stack["last_run"] is None


def test_junior_row_is_never_a_posted_instrument_in_the_template():
    from app.v2.router import _templates
    view, junior = _junior_view()
    html = _templates.get_template("partials/_financing_multisenior.html").render(
        multisenior=view, capital_stack=cs.build_capital_stack(view, None), project_editable=True,
        project_code="x", workbook_version="v", content_hash="h")
    assert f'data-cs-readonly-instrument="{junior.instrument_id}"' in html
    assert f'data-f3-instrument="{junior.instrument_id}"' not in html      # the serializer cannot touch it
    assert "cs-junior-readiness" in html
