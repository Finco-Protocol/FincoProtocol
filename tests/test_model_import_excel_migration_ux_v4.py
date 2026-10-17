"""Focused, standalone read-only V4 review-projection and Jinja tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migration_ux", ROOT / "app/model_import/migration_ux.py")
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
ENV = Environment(loader=FileSystemLoader(str(ROOT / "app/templates/v2")),
                  autoescape=select_autoescape(("html",)))


def plan():
    return {
        "target": {"scenario_name": "Target Upside"},
        "scenarios": {"structures": [{"scenarios": [
            {"key": "base", "label": "Base case", "resolution": "STATIC_OBSERVABLE", "kind": "BASE"},
            {"key": "switch", "label": "Macro switch", "resolution": "SCENARIO_LOGIC_UNRESOLVED", "kind": "NUMBERED"},
            {"key": "unrepresented", "label": "Unrepresented", "resolution": "PARTIALLY_OBSERVABLE", "kind": "SOURCE_CASE"},
        ]}]},
        "slices": [
            {"key": "base", "label": "Base case", "resolution": "STATIC_OBSERVABLE", "kind": "BASE", "applyable_rows": 3, "apply_eligible": True, "notes": []},
            {"key": "switch", "label": "Macro switch", "resolution": "SCENARIO_LOGIC_UNRESOLVED", "kind": "NUMBERED", "applyable_rows": 0, "apply_eligible": False, "blockers": ["SCENARIO_LOGIC_UNRESOLVED"]},
            {"key": "common", "label": "Case-independent only", "resolution": "SCENARIO_LOGIC_UNRESOLVED", "kind": "COMMON", "applyable_rows": 2, "apply_eligible": True, "notes": ["SCENARIO_LOGIC_UNRESOLVED_ELSEWHERE_IN_WORKBOOK"]},
        ],
    }


def test_scenario_matrix_does_not_invent_per_scenario_status():
    rows = MOD.scenario_review_matrix(plan())
    assert len(rows) == 4
    base, macro, absent, common = rows
    assert base["mapped_scalar_count"] == 3
    assert base["target_scenario"] == "Target Upside"
    assert base["apply_eligibility"] == "REVIEW_ELIGIBLE"
    assert base["requires_review"] is True
    assert (base["applied_status"], base["reconciliation_status"]) == ("NOT_TRACKED", "NOT_TRACKED")
    assert macro["apply_eligibility"] == "BLOCKED"
    assert "SCENARIO_LOGIC_UNRESOLVED" in macro["unsupported_dependencies"]
    assert absent["apply_eligibility"] == "NOT_TRACKED"
    assert common["apply_eligibility"] == "REVIEW_ELIGIBLE"   # case-independent literals only


def test_duplicate_source_keys_not_duplicate_rows():
    p = plan()
    p["scenarios"]["structures"].append({"scenarios": [p["scenarios"]["structures"][0]["scenarios"][0]]})
    assert len(MOD.scenario_review_matrix(p)) == 4


def test_macro_matrix_escapes_untrusted_workbook_labels():
    p = plan()
    p["scenarios"]["structures"][0]["scenarios"][0]["label"] = '<script>alert("x")</script>'
    rows = MOD.scenario_review_matrix(p)
    tmpl = ENV.from_string('{% import "import_workflow.html" as wf %}{{ wf.matrix(rows) }}')
    out = tmpl.render(rows=rows)
    assert '<script>alert("x")</script>' not in out
    assert '&lt;script&gt;' in out
    assert 'NOT_TRACKED' in out and 'LABEL_ONLY_UNVERIFIED' in out


def test_five_stage_progress_never_calls_apply_a_run():
    tmpl = ENV.from_string('{% import "import_workflow.html" as wf %}{{ wf.stages(stage, comparison_status=status) }}')
    applied = tmpl.render(stage="result", status="")
    assert applied.count('<li>') == 5
    assert 'CHANGED — NOT RUN' in applied
    assert 'APPLIED' in applied
    assert 'CHECKED' not in applied
    compared = tmpl.render(stage="reconcile", status="NOT_COMPARABLE")
    assert 'CHECKED · NOT_COMPARABLE' in compared
    assert 'PASS' not in compared


def test_entry_acknowledgement_requires_explicit_user_action():
    assert MOD.scenario_review_acknowledged("on") is True
    for value in (None, "", "yes", "true", "off"):
        assert MOD.scenario_review_acknowledged(value) is False
