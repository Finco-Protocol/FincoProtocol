"""F3.9 numerical validation V2 — pure tests (no application, no database, no engine).

Pins the reusable reconciliation workflow: Decimal independent checks, exact-period alignment, approved tolerances,
explicit outcomes, earliest divergence, deterministic reports, and the scope guard (the tools never import the engine).
"""
from __future__ import annotations

import ast
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tools.numerical_validation import coverage, oracles
from tools.numerical_validation.identities import KEUR_FULL, KEUR_2DP, RATIO, XIRR, default_policies, expected_unit
from tools.numerical_validation.periodic import (CLASS_CALCULATION, CLASS_DOWNSTREAM, KIND_CALCULATION, BASIS_2DP,
                                                 BASIS_FULL, Reconciler, TolerancePolicy, reports,
                                                 representation_allowance)
from tools.numerical_validation.reconcile import ReconciliationInputError

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "numerical_validation"
D = Decimal


def _rec() -> Reconciler:
    rec = Reconciler(default_policies(), identity={"run_key": "r"})
    rec.register("A", "revenue", KIND_CALCULATION, "a", BASIS_FULL, KEUR_FULL)
    rec.register("B", "debt", KIND_CALCULATION, "b", BASIS_FULL, KEUR_FULL)
    rec.register("S", "statements", KIND_CALCULATION, "s", BASIS_2DP, KEUR_2DP)
    return rec


# ── approved tolerances are exactly the product's ───────────────────────────────────────────────────────────────
def test_tolerances_equal_the_approved_application_constants():
    from app.run_integrity.contracts import TOL_KEUR, TOL_RATIO, TOL_XIRR
    from app.v2.financing_sources_uses_projection import FINANCE_TOLERANCE_KEUR

    policies = {p.key: p for p in default_policies()}
    assert policies[KEUR_FULL].abs_tolerance == D(repr(TOL_KEUR)) == D(repr(FINANCE_TOLERANCE_KEUR))
    assert policies[KEUR_2DP].abs_tolerance == policies[KEUR_FULL].abs_tolerance
    assert policies[XIRR].abs_tolerance == D(repr(TOL_XIRR))
    assert policies[RATIO].abs_tolerance == D(repr(TOL_RATIO)) * 100
    for p in policies.values():
        assert p.origin.strip() and p.justification.strip()


def test_a_policy_without_origin_or_with_negative_allowance_is_refused():
    with pytest.raises(ReconciliationInputError):
        TolerancePolicy("X", D(0), D(0), "", "why")
    with pytest.raises(ReconciliationInputError):
        TolerancePolicy("X", D(-1), D(0), "origin", "why")


def test_representation_allowance_is_half_quantum_per_rounded_term_and_separate():
    assert representation_allowance(0) == 0
    assert representation_allowance(4) == D("0.02")
    rec = _rec()
    inside = rec.check("S", "2030-06-30", D("100.01"), D("100.00"), rounded_terms=3)
    assert inside.status == "PASS" and inside.representation_allowance == D("0.015")
    outside = rec.check("S", "2030-12-31", D("100.04"), D("100.00"), rounded_terms=3)
    assert outside.status == "FAIL"
    full = rec.check("A", "2030-06-30", D("100.0000011"), D("100"))
    assert full.status == "FAIL" and full.representation_allowance == 0  # full precision never gets the allowance


# ── negatives ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_negative_residual_is_signed_and_fails():
    out = _rec().check("A", "p1", D("99"), D("100"))
    assert out.status == "FAIL" and out.residual == D("-1") and out.abs_residual == D("1")
    assert out.rel_residual == D("0.01")


def test_duplicate_period_is_refused():
    rec = _rec()
    rec.check("A", "p1", D(1), D(1))
    with pytest.raises(ReconciliationInputError, match="duplicate period"):
        rec.check("A", "p1", D(1), D(1))


def test_missing_period_is_unavailable_never_zero():
    rec = _rec()
    rec.unavailable("A", "p2", "PERIOD_ABSENT")
    result = rec.finalise()
    assert result["counts"]["UNAVAILABLE"] == 1 and result["counts"]["PASS"] == 0
    row = result["by_identity"][0]
    assert row["verdict"] == "UNAVAILABLE" and row["max_abs_residual"] is None


def test_unknown_identity_stage_policy_are_refused():
    rec = _rec()
    with pytest.raises(ReconciliationInputError):
        rec.check("ZZ", "p", D(0), D(0))
    with pytest.raises(ReconciliationInputError):
        rec.register("C", "nope", KIND_CALCULATION, "c", BASIS_FULL, KEUR_FULL)
    with pytest.raises(ReconciliationInputError):
        rec.register("C", "debt", KIND_CALCULATION, "c", BASIS_FULL, "NOPE")


def test_unit_mismatch_is_withheld_and_not_comparable():
    from tools.numerical_validation.identities import View

    assert expected_unit("rev.generation_display") == "MWh"
    assert expected_unit("rv2.stream.s1.price") == "EUR/MWh"
    assert expected_unit("summary.project_irr") == "ratio"
    assert expected_unit("ev.senior.interest") == "kEUR"
    bundle = {"series": {"ev.senior.interest": {"unit": "EUR", "values": {"p": "1"}}},
              "scalars": {"summary.total_tax_keur": {"unit": "kEUR", "value": "1"}}}
    view = View(bundle)
    assert view.series("ev.senior.interest") is None and view.unit_errors == {"ev.senior.interest": ("EUR", "kEUR")}
    assert view.scalar("summary.total_tax_keur") == 1


def test_first_divergence_is_the_earliest_stage_and_later_fails_are_downstream():
    rec = _rec()
    rec.check("B", "p1", D(5), D(6))    # debt fails
    rec.check("A", "p1", D(5), D(6))    # revenue fails (earlier stage)
    rec.check("S", "p1", D(5), D(6), rounded_terms=1)
    result = rec.finalise()
    assert result["first_divergence"]["identity"] == "A" and result["first_divergence"]["stage"] == "revenue"
    classes = {o["identity"]: o["classification"] for o in result["outcomes"]}
    assert classes["A"] == CLASS_CALCULATION and classes["B"] == classes["S"] == CLASS_DOWNSTREAM


def test_reports_are_deterministic_and_never_embed_payloads():
    def build():
        rec = _rec()
        rec.check("A", "p1", D("1.5"), D("1.5"))
        rec.unavailable("B", "p1", "NOT_PERSISTED")
        return reports(rec.finalise())

    one, two = build(), build()
    assert one == two and set(one) == {"report.json", "report.csv", "report.md"}
    assert json.loads(one["report.json"])["schema"] == "FINCO_NUMERICAL_RECONCILIATION_V1"
    assert b"UNAVAILABLE and NOT_COMPARABLE are never treated as agreement" in one["report.md"]


# ── independent oracles ───────────────────────────────────────────────────────────────────────────────────────────
def test_oracles_independent_decimal_identities():
    tol = D("1e-6")
    # signed two-way CfD: strike below the reference price pays back (negative settlement)
    assert oracles.cfd_settlement(1000, 40, 90, -50, tolerance=tol).status == "PASS"
    assert oracles.cfd_settlement(1000, 100, 90, 10, tolerance=tol).status == "PASS"
    assert oracles.cfd_settlement(1000, 40, 90, 50, tolerance=tol).status == "FAIL"   # wrong sign is caught
    assert oracles.debt_service(3, 4, 7, tolerance=tol).status == "PASS"
    assert oracles.dscr(150, 100, "1.5", tolerance=tol).status == "PASS"
    assert oracles.ebitda(10, 4, 6, tolerance=tol).status == "PASS"
    assert oracles.cash_after_service(150, 100, 50, tolerance=tol).status == "PASS"
    # DCF / IRR identity: NPV at the independent IRR is ~0
    from datetime import date

    flows = [D(-100), D(60), D(60)]
    dates = ["2030-01-01", "2031-01-01", "2032-01-01"]
    rate = oracles.xirr(flows, dates)
    npv = sum(f / (D(1) + rate) ** (D((date.fromisoformat(d) - date.fromisoformat(dates[0])).days) / D(365))
              for f, d in zip(flows, dates))
    assert abs(npv) < D("1e-9")


def test_sum_of_periods_total_is_independent_of_the_periods():
    ok = oracles.sum_of_periods([D(1), D(2)], D(3), tolerance=D("1e-6"), name="t")
    bad = oracles.sum_of_periods([D(1), D(2)], D("3.1"), tolerance=D("1e-6"), name="t")
    assert ok.status == "PASS" and bad.status == "FAIL"
    with pytest.raises(ReconciliationInputError):
        oracles.sum_of_periods([], D(0), tolerance=D("1e-6"))


# ── coverage matrix ─────────────────────────────────────────────────────────────────────────────────────────────
def _result(verdicts):
    rows = [{"identity": k, "stage": "debt", "title": k, "verdict": v, "counts": {}, "max_abs_residual": None,
             "reasons": r} for k, (v, r) in verdicts.items()]
    return {"by_identity": rows, "counts": {"PASS": 1, "FAIL": 0, "UNAVAILABLE": 1, "NOT_COMPARABLE": 0}}


def test_coverage_marks_not_applicable_but_never_promotes_unavailable():
    results = {"solar/legacy": _result({"X": ("UNAVAILABLE", ["NO_JUNIOR_FACILITY_IN_THIS_CONFIGURATION"]),
                                         "Y": ("UNAVAILABLE", ["TAX_AUDIT_FIELDS_NOT_PERSISTED"]),
                                         "Z": ("VERIFIED", [])})}
    matrix = coverage.build_matrix(results)
    cells = {k: v["cells"]["solar/legacy"]["verdict"] for k, v in matrix["identities"].items()}
    assert cells == {"X": "NOT_APPLICABLE", "Y": "UNAVAILABLE", "Z": "VERIFIED"}
    assert {u["capability"] for u in matrix["unsupported_capabilities"]} >= {"npv", "external_workbook_parity"}
    rendered = coverage.render(results)
    assert rendered == coverage.render(results) and set(rendered) == {"coverage.json", "coverage.csv", "coverage.md"}


# ── scope guard ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tools_never_import_the_engine_and_only_source_touches_the_app():
    forbidden = ("financial_engine", "finco_core", "domain")
    for path in sorted(TOOLS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root not in forbidden, f"{path.name} imports {name}"
                if root == "app":
                    assert path.name == "source.py", f"{path.name} touches the application"


def test_source_adapter_is_read_only():
    text = (TOOLS / "source.py").read_text(encoding="utf-8")
    for token in ("insert", "update(", "delete", "commit(", "execute(", "write_text", "open("):
        assert token not in text.lower().replace("get_run_history_entry", "").replace("update_", ""), token


def test_reports_deepcopy_stable():
    rec = _rec()
    rec.check("A", "p", D(1), D(1))
    result = rec.finalise()
    assert reports(copy.deepcopy(result)) == reports(result)
