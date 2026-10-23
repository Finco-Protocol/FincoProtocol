"""Exception authority of the native regions (gap G1 / V10-05), machine-checked on the running interpreter.

1. Bytecode audit: every instruction of every authenticated native region (Stage 1 and Stage 2, incl.
   nested code objects) is classified; none may be UNCLASSIFIED and every RESIDUAL site (division,
   modulo, power, subscripts, dict membership) must carry an explicit discharge. Discharge rules are pinned
   to exact source lines, so ANY edit of an authenticated region re-opens its sites and fails here until it
   is re-reviewed (and the region resealed).
2. Explicit-raise inventory (tests/fixtures/native_v10_exception_inventory.json): no category C remains;
   every Stage 1 inventoried raise still exists in its function; the Stage 2 region's raise statements are
   exactly the inventoried ones.
"""
from __future__ import annotations

import ast
import dis
import importlib
import json
import types
from collections import Counter
from pathlib import Path

import pytest

from financial_engine.native_v10 import provenance as pv

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads((ROOT / "tests" / "fixtures" / "native_v10_exception_inventory.json").read_text())

NONRAISING = {"RESUME", "NOP", "CACHE", "LOAD_FAST", "LOAD_FAST_CHECK", "LOAD_FAST_AND_CLEAR", "LOAD_FAST_LOAD_FAST",
              "STORE_FAST", "STORE_FAST_LOAD_FAST", "STORE_FAST_STORE_FAST", "LOAD_CONST", "RETURN_CONST", "RETURN_VALUE",
              "POP_TOP", "PUSH_NULL", "COPY", "SWAP", "END_FOR", "END_SEND", "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE",
              "POP_JUMP_IF_NONE", "POP_JUMP_IF_NOT_NONE", "JUMP_FORWARD", "JUMP_BACKWARD", "JUMP_BACKWARD_NO_INTERRUPT",
              "JUMP", "IS_OP", "BUILD_TUPLE", "BUILD_LIST", "LIST_APPEND", "LIST_EXTEND", "BUILD_CONST_KEY_MAP",
              "MAKE_FUNCTION", "SET_FUNCTION_ATTRIBUTE", "MAKE_CELL", "COPY_FREE_VARS", "LOAD_DEREF", "STORE_DEREF",
              "LOAD_CLOSURE", "TO_BOOL", "UNARY_NOT", "POP_EXCEPT", "PUSH_EXC_INFO", "CHECK_EXC_MATCH", "NOT_TAKEN",
              "LOAD_SMALL_INT", "POP_ITER", "DELETE_FAST", "EXTENDED_ARG", "BUILD_MAP", "BUILD_SET", "SET_ADD",
              "MAP_ADD", "LIST_TO_TUPLE", "RETURN_GENERATOR", "YIELD_VALUE", "STORE_FAST_MAYBE_NULL", "INTERPRETER_EXIT",
              "LOAD_LOCALS", "BUILD_STRING", "FORMAT_SIMPLE", "FORMAT_WITH_SPEC", "CONVERT_VALUE", "FORMAT_VALUE",
              "CALL_INTRINSIC_1", "LOAD_ASSERTION_ERROR", "CLEANUP_THROW", "SEND", "GET_YIELD_FROM_ITER"}
RESIDUAL_ARITH = {"/", "//", "%", "/=", "//=", "%=", "**", "**=", "<<", ">>"}

# Code whose execution a kernel substitutes; residual sites anywhere else are canonical code that still
# executes in the native arm (admission-time static computation or the canonical tail on bit-identical
# kernel outputs) and therefore raise identically by construction.
REPLACED = {
    "financial_engine.senior_debt.solver": ("_solve_dscr", "_finalise_authoritative", "_forward_roll_numeric",
                                            "_backward_dscr_capacity", "_schedules_converged", "_field_converged",
                                            "_compute_max_abs_diff"),
    "financial_engine.tax.engine": ("SolverTaxPlan.evaluate", "_evaluate_numeric_tax_vectors",
                                    "_evaluate_numeric_tax_vectors_uncached", "_pack_numeric_tax_vector",
                                    "calculate_cfads_and_cash_tax"),
    "financial_engine.tax.loss_ledger": ("taxable_income_after_lcf_series",),
    "financial_engine.tax.tax_year": ("_resolve_shl_tax_eligible_interest",),
    "financial_engine.cfads": ("calculate_canonical_cfads_value",),
    "financial_engine.orchestrator": ("_make_solver_tax_cfads_fn", "run_senior_debt_model.tax_cfads_fn",
                                      "_run_senior_debt_model_with_shl.final_tax_cfads_fn"),
    "financial_engine.shl.production": ("compute_shareholder_loan_schedules", "_ShlOperatingChain.evaluate",
                                        "_ShlOperatingChain.advance", "_check_finite"),
    "financial_engine.shl.waterfall": ("compute_shl_waterfall_period", "_check_finite"),
}
# (module suffix, function prefix, exact source lines or None, discharge class, reason)
RULES = [
    ("orchestrator", "_make_solver_tax_cfads_fn._evaluate_fast", None, "NO_RAISE",
     "Run-scope dict / OrderedDict stores and 2-tuple reads of an entry it wrote itself; hashable bytes keys"),
    ("orchestrator", "_make_solver_tax_cfads_fn.tax_cfads_fn", None, "GUARDED",
     "subscript only under the immediately preceding `idx in senior_interest_by_period` test (int keys)"),
    ("solver", "_backward_dscr_capacity", (475, 476, 480), "ADMISSION_EXECUTES_SAME_LOOKUP",
     "build_roll_plan (canonical, executed by admission) performs the same dscr_map / availability_map / "
     "period_start_end lookups; a KeyError raises there -> decline -> canonical replays and raises"),
    ("solver", "_backward_dscr_capacity", (478, 483, 485), "GUARDED",
     "divisions guarded in canonical source: target_dscr > 0, f > 1e-15, denom > 1e-15"),
    ("solver", "_field_converged", None, "GUARDED", "ref = max(|a|, |b|, 1.0) >= 1"),
    ("solver", "_forward_roll_numeric", (371,), "GUARDED", "cfads / target only under `if target > 0`"),
    ("solver", "_forward_roll_numeric", (383, 386), "NOT_ADMITTED",
     "level_principal / explicit methods decline (ROLL_METHOD) before any kernel call"),
    ("solver", "_forward_roll_numeric", None, "AXIS_PREDICATE",
     "index i in range(len(indices)); every roll-plan tuple has len(indices) (ROLL_PLAN_AXIS predicate)"),
    ("production", "compute_shareholder_loan_schedules", (474, 479), "NO_RAISE", "membership of int in frozenset"),
    ("production", "compute_shareholder_loan_schedules", None, "TEMPLATE_EXECUTES",
     "construction / override branch: cash-independent, executed by the Stage 2 canonical template (raise -> decline)"),
    ("engine", "SolverTaxPlan.evaluate", (1027, 1028), "GUARDED", "candidate[idx] only after `idx in candidate`"),
    ("engine", "SolverTaxPlan.evaluate", None, "AXIS_PREDICATE",
     "row_pos from enumerate(plan rows); static vectors have n_rows entries (NUMERIC_TAX_VECTOR_AXIS_MISMATCH)"),
    ("engine", "_evaluate_numeric_tax_vectors", None, "NO_RAISE", "Run-scope cache stores and reads of its own 2-tuples"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached", (698, 699, 700, 701, 817), "AXIS_PREDICATE",
     "row vectors have n_rows entries (mirrored canonical predicate, engine.py raise site)"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached",
     (721, 722, 723, 724, 726, 727, 728, 729, 730, 732, 733, 734, 735, 736), "KERNEL_VALIDATES",
     "slot year positions: validate_plan requires 0 <= slot_pos < n_years (else INVALID_PLAN -> decline)"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached", (744, 745, 746, 747, 748, 749), "AXIS_PREDICATE",
     "k in range(n_years); y_ebitda / y_dep lengths == n_years (TAX_PLAN_YEAR_AXIS)"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached", (794,), "NO_RAISE", "enum membership in a constant tuple"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached", (803, 804), "MIRRORED_PREDICATE",
     "payment-period KeyError predicate mirrored in admission (CASH_TAX_PAYMENT_PERIOD_MISSING)"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached", (809, 810), "ADMISSION_EXECUTES_SAME_LOOKUP",
     "same_period_contributions[idx] read for every sorted idx by the admission geometry; sp_k validated in [0, n_years)"),
    ("engine", "_evaluate_numeric_tax_vectors_uncached", (818, 823), "NO_RAISE", "dict stores with int keys"),
    ("loss_ledger", "taxable_income_after_lcf_series", (330,), "GUARDED", "[0] only when the sequence is non-empty"),
    ("loss_ledger", "taxable_income_after_lcf_series", (354,), "UNREACHABLE",
     "length equality guaranteed by construction (loss_ledger.py:328, inventory class U)"),
]


def _classify(ins) -> str:
    op = ins.opname
    if op in NONRAISING:
        return "NONRAISING"
    if op in ("RAISE_VARARGS", "RERAISE"):
        return "EXPLICIT_RAISE"
    if op == "BINARY_OP":
        if ins.argrepr in RESIDUAL_ARITH or ins.argrepr == "[]":     # 3.14+: subscript is BINARY_OP []
            return "RESIDUAL"
        return "ARITH_FLOAT_INT"
    if op in ("UNARY_NEGATIVE", "UNARY_INVERT", "COMPARE_OP"):
        return "ARITH_FLOAT_INT"
    if op in ("LOAD_ATTR", "LOAD_GLOBAL", "LOAD_NAME", "LOAD_SUPER_ATTR", "LOAD_METHOD", "IMPORT_NAME", "IMPORT_FROM",
              "STORE_ATTR"):
        return "ATTR_GLOBAL"
    if op in ("GET_ITER", "FOR_ITER", "UNPACK_SEQUENCE", "UNPACK_EX", "BUILD_SLICE", "BINARY_SLICE"):
        return "ITER_UNPACK"
    if op in ("BINARY_SUBSCR", "STORE_SUBSCR", "DELETE_SUBSCR", "CONTAINS_OP"):
        return "RESIDUAL"
    if op.startswith("CALL") or op in ("PRECALL", "KW_NAMES"):
        return "CALL"
    return "UNCLASSIFIED"


def _walk(code, qual):
    yield qual, code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from _walk(c, f"{qual}.{c.co_name}")


def _audit():
    regions: dict = {}
    for table in (pv.REGION_FUNCTIONS, pv.STAGE2_REGION_FUNCTIONS):
        for mod, quals in table.items():
            regions.setdefault(mod, set()).update(quals)
    totals, residual, unclassified = Counter(), [], []
    for mod_name, quals in sorted(regions.items()):
        mod = importlib.import_module(mod_name)
        for q in sorted(quals):
            for sub, code in _walk(pv._resolve(mod, q).__code__, q):
                for ins in dis.get_instructions(code):
                    cls = _classify(ins)
                    totals[cls] += 1
                    line = ins.positions.lineno if ins.positions else None
                    if cls == "RESIDUAL":
                        residual.append({"module": mod_name, "function": sub, "line": line, "op": ins.opname})
                    elif cls == "UNCLASSIFIED":
                        unclassified.append((mod_name, sub, line, ins.opname))
    return totals, residual, unclassified


def _discharge(site):
    replaced = any(site["function"] == q or site["function"].startswith(q + ".")
                   for q in REPLACED.get(site["module"], ()))
    if not replaced:
        return "EXECUTED_CANONICAL"
    mod = site["module"].split(".")[-1]
    for m, fn, lines, cls, _why in RULES:
        if mod == m and (site["function"] == fn or site["function"].startswith(fn + ".")) \
                and (lines is None or site["line"] in lines):
            return cls
    return None


def test_every_native_region_instruction_is_classified_and_every_residual_site_is_discharged():
    from financial_engine.native_v10 import eligibility
    reason = eligibility.check_runtime()
    if reason:   # the audit concerns the bytecode of an interpreter that may execute native code
        pytest.skip(f"bytecode audit applies to validated native runtimes only: {reason}")
    totals, residual, unclassified = _audit()
    assert sum(totals.values()) > 5000 and residual                # the audit really covers the regions
    assert unclassified == []
    open_sites = [s for s in residual if _discharge(s) is None]
    assert open_sites == [], open_sites


def test_no_category_c_and_inventory_counts():
    counts = Counter((s["region"], s["category"]) for s in INVENTORY["sites"])
    assert not [k for k in counts if k[1] == "C"]
    assert {r: dict(c) for r, c in INVENTORY["counts"].items()} == {
        "STAGE1": {"A": 72, "B": 9, "P": 1, "U": 1}, "STAGE2_EXPERIMENTAL": {"S": 23, "P": 15, "U": 1}}


def _functions(path):
    tree = ast.parse((ROOT / path).read_text())
    found = {}

    def walk(node, prefix=""):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.ClassDef)):
                q = f"{prefix}{ch.name}"
                if isinstance(ch, ast.FunctionDef):
                    found[q] = ch
                walk(ch, q + ".")

    walk(tree)
    return found


def _norm(text: str) -> str:
    return " ".join(text.split())


def _raises(path, fn, *, whole: bool = False) -> list[str]:
    """Raise statements of ``fn``: first source line (Stage 2 inventory form) or the whole statement."""
    source = (ROOT / path).read_text()
    lines = source.splitlines()
    out = []
    for r in ast.walk(fn):
        if isinstance(r, ast.Raise):
            out.append(_norm(ast.get_source_segment(source, r)) if whole else lines[r.lineno - 1].strip())
    return out


def test_stage1_inventoried_raises_still_exist_in_their_functions():
    by_file: dict = {}
    for s in INVENTORY["sites"]:
        if s["region"] == "STAGE1":
            by_file.setdefault(s["path"], []).append(s)
    for path, sites in by_file.items():
        functions = _functions(path)
        for s in sites:
            qual = s["scope"].split("module.", 1)[-1]
            candidates = [f for q, f in functions.items() if q == qual or q.endswith("." + qual)] or list(functions.values())
            wanted = _norm(s["raise"])
            assert any(wanted in _raises(path, f, whole=True) or s["raise"] in _raises(path, f) for f in candidates), \
                (path, s["scope"], s["raise"])


def test_stage2_region_raises_are_exactly_the_inventoried_ones():
    expected = Counter((s["path"], s["scope"], s["raise"]) for s in INVENTORY["sites"] if s["region"] == "STAGE2_EXPERIMENTAL")
    actual = Counter()
    for path in {p for p, _s, _r in expected}:
        scopes = {s for p, s, _r in expected if p == path}
        for q, fn in _functions(path).items():
            if q in scopes:
                for text in _raises(path, fn):
                    actual[(path, q, text)] += 1
    assert actual == expected
